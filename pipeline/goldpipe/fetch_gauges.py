"""Current river flow from state gauge networks, for gauges near gold country.

Two stacks cover five states (verified live 2026-08):
- Hydstra JSON web services: VIC (data.water.vic.gov.au/WMIS) and QLD
  (water-monitoring.information.qld.gov.au). Variable 100.00 is level,
  rated to 140.00 = discharge in m^3/s.
- Aquarius WebPortal: TAS (portal.wrt.tas.gov.au), SA (water.data.sa.gov.au),
  NT (ntg.aquaticinformatics.net). POST /Data/Data_List lists discharge
  datasets with coordinates; GET /Export/BulkExport returns a CSV whose last
  row is the latest instantaneous discharge in m^3/s.

Each gauge also reports whether the water is rising or falling, and in VIC
and QLD the current water level (height on the gauge) alongside the flow.

Honest gaps: NSW's Hydstra blocks datacenter IPs (same class of block as
BOM) and WA publishes no keyless machine-readable discharge — both states
ship no gauges and the app says so.
"""
import csv
import io
import json
import urllib.parse
from datetime import datetime, timezone

from . import config
from .grid import cell_of
from .http import SESSION

HYDSTRA_STATES = {
    "VIC": {
        "base": "https://data.water.vic.gov.au/WMIS/cgi/webservice.exe",
        "datasource": "TELEM",
    },
    "QLD": {
        "base": "https://water-monitoring.information.qld.gov.au/cgi/webservice.exe",
        "datasource": "AT",
    },
}

AQUARIUS_STATES = {
    "TAS": {
        "base": "https://portal.wrt.tas.gov.au",
        "parameter": "8",
        "tz": "10",
        "utc_offset": "-600",
        "prefixes": ("Discharge.",),
    },
    "SA": {
        "base": "https://water.data.sa.gov.au",
        "parameter": "47",
        "tz": "9.5",
        "utc_offset": "-570",
        # Only the continuous best-available record — spot gaugings and
        # ML/day daily-read datasets 404 or carry different units.
        "prefixes": ("Discharge.Best Available",),
    },
    "NT": {
        "base": "https://ntg.aquaticinformatics.net",
        "parameter": "44",
        "tz": "9.5",
        "utc_offset": "-570",
        "prefixes": ("Stream Discharge.",),
    },
}


def _flow_category(cumecs: float) -> str:
    if cumecs < 0.005:
        return "dry"
    if cumecs < 0.5:
        return "low"
    if cumecs < 10:
        return "medium"
    return "high"


def _near_gold(lon: float, lat: float, cells) -> bool:
    cx, cy = cell_of(lon, lat)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if (cx + dx, cy + dy) in cells:
                return True
    return False


def _feature(state, sid, name, lon, lat, cumecs, obs_time,
             level=None, trend=None, dataset=None) -> dict:
    """One gauge. [cumecs] may be None when only the water level is current;
    [level] is the height on the gauge's staff in metres; [trend] is
    'rising' / 'falling' / 'steady' over roughly the last day."""
    props = {
        "id": f"{state}:{sid}",
        "state": state,
        "name": name or sid,
        "obs": obs_time,
    }
    if cumecs is not None:
        props["flow"] = round(cumecs, 3)
        props["flow_mld"] = round(cumecs * 86.4, 1)
        props["cat"] = _flow_category(cumecs)
    else:
        props["cat"] = "level"
    if level is not None:
        props["level"] = round(level, 2)
    if trend:
        props["trend"] = trend
    if dataset:
        # Lets the app fetch this gauge's last week for a chart.
        props["ds"] = dataset
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        "properties": props,
    }


STALE_DAYS = 10


def _fresh(iso: str, now: datetime | None = None) -> bool:
    """False for readings so old they'd mislead (some gauges still return a
    flow figure from years ago once their rating lapses)."""
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return False
    now = now or datetime.now(timezone.utc)
    # Gauge times are local standard time; a day's slack covers the offset.
    return (now.replace(tzinfo=None) - t).days <= STALE_DAYS


def _trend_from_change(first: float, last: float) -> str:
    """Trend from the first and last reading of the past day."""
    change = last - first
    if abs(change) < max(0.002, 0.05 * max(abs(first), abs(last))):
        return "steady"
    return "rising" if change > 0 else "falling"


# --- Hydstra (VIC, QLD) -----------------------------------------------------

def _hydstra(base: str, obj: dict):
    url = base + "?" + urllib.parse.quote(json.dumps(obj, separators=(",", ":")))
    r = SESSION.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("error_num") not in (0, "0"):
        raise RuntimeError(f"hydstra error {data.get('error_num')}: {data.get('error_msg')}")
    return data.get("return") or {}


def _hydstra_sites(base: str, datasource: str) -> list[str]:
    ret = _hydstra(base, {
        "function": "get_sites_by_datasource",
        "version": "1",
        "params": {"datasources": [datasource]},
    })
    # Response shape: {"datasources": [{"datasource": "TELEM", "sites": [...]}]}
    sites: list[str] = []
    for ds in ret.get("datasources", []):
        for entry in ds.get("sites", []):
            if isinstance(entry, dict):
                sid = entry.get("site") or entry.get("station")
                if sid:
                    sites.append(str(sid))
            else:
                sites.append(str(entry))
    return sites


def _hydstra_coords(base: str, sites: list[str]) -> dict[str, tuple[float, float, str]]:
    """site -> (lon, lat, name) via get_site_geojson, chunked."""
    out: dict[str, tuple[float, float, str]] = {}
    # IIS caps query strings (~2KB) and answers 404 past it — keep chunks small.
    for i in range(0, len(sites), 60):
        chunk = sites[i:i + 60]
        try:
            ret = _hydstra(base, {
                "function": "get_site_geojson",
                "version": "2",
                "params": {"site_list": ",".join(chunk), "fields": ["stname"], "get_elev": 0},
            })
        except Exception:  # noqa: BLE001 — a timed-out chunk shouldn't lose the state
            continue
        for f in ret.get("features", []):
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or []
            props = f.get("properties") or {}
            sid = str(f.get("id") or props.get("station") or "")
            if len(coords) >= 2 and sid:
                out[sid] = (
                    float(coords[0]), float(coords[1]),
                    str(props.get("stname") or "").strip(),
                )
    return out


_HYDSTRA_TREND = {"+": "rising", "-": "falling", "0": "steady"}


def _hydstra_latest(base: str, datasource: str, sites: list[str],
                    limit: int = 10**9) -> dict[str, dict]:
    """site -> {flow, flow_time, level, level_time, trend}.

    Level is variable 100.00 (metres on the gauge); flow is the same reading
    passed through the site's rating to 140.00 (m^3/s). The service also
    says whether each is rising or falling."""
    out: dict[str, dict] = {}
    # 40 per call: two traces per site make the query longer, and IIS
    # answers 404 once it passes ~2KB.
    for i in range(0, len(sites), 40):
        if len(out) >= limit:
            break
        chunk = sites[i:i + 40]
        try:
            ret = _hydstra(base, {
                "function": "get_latest_ts_values",
                "version": "2",
                "params": {
                    "site_list": ",".join(chunk),
                    "datasource": datasource,
                    "trace_list": [
                        {"varfrom": "100.00", "varto": "140.00"},
                        {"varfrom": "100.00", "varto": "100.00"},
                    ],
                },
            })
        except Exception:  # noqa: BLE001 — a bad chunk shouldn't kill the state
            continue
        # v2 response: {"<site>": [{"values": [{"v": "...", "time": "..."}],
        #               "varfrom": "100.00", "varto": "140.00"}], ...}
        for sid, traces in ret.items():
            if not isinstance(traces, list):
                continue
            for tr in traces:
                vals = tr.get("values") or []
                if not vals:
                    continue
                last = vals[-1]
                try:
                    v = float(last.get("v"))
                except (TypeError, ValueError):
                    continue
                t = str(last.get("time") or "")
                iso = ""
                if len(t) >= 12:
                    iso = f"{t[0:4]}-{t[4:6]}-{t[6:8]}T{t[8:10]}:{t[10:12]}"
                rec = out.setdefault(str(sid), {})
                kind = "flow" if str(tr.get("varto")) == "140.00" else "level"
                rec[kind] = v
                rec[kind + "_time"] = iso
                trend = _HYDSTRA_TREND.get(str(last.get("trend") or ""))
                # The level's own trend is the one people can see at the creek.
                if trend and (kind == "level" or "trend" not in rec):
                    rec["trend"] = trend
    return out


def _fetch_hydstra_state(state: str, cfg: dict, cells) -> list[dict]:
    sites = _hydstra_sites(cfg["base"], cfg["datasource"])
    coords = _hydstra_coords(cfg["base"], sites)
    near = {
        sid: c for sid, c in coords.items()
        if _near_gold(c[0], c[1], cells)
    }
    # Many listed sites have no live stream data (bores, closed stations),
    # so keep asking until enough reporting gauges are found rather than
    # looking only at the first handful.
    latest = _hydstra_latest(cfg["base"], cfg["datasource"], list(near.keys()),
                             limit=config.GAUGE_MAX_PER_STATE)
    feats = []
    for sid, rec in latest.items():
        lon, lat, name = near[sid]
        flow = rec.get("flow")
        if flow is not None and (flow < 0 or not _fresh(rec.get("flow_time", ""))):
            flow = None
        level = rec.get("level")
        if level is not None and not _fresh(rec.get("level_time", "")):
            level = None
        if flow is None and level is None:
            continue
        if len(feats) >= config.GAUGE_MAX_PER_STATE:
            break
        obs = rec.get("flow_time") if flow is not None else rec.get("level_time")
        feats.append(_feature(state, sid, name, lon, lat, flow, obs or "",
                              level=level, trend=rec.get("trend")))
    return feats


# --- Aquarius WebPortal (TAS, SA, NT) --------------------------------------

def _aquarius_datasets(cfg: dict) -> list[dict]:
    r = SESSION.post(
        cfg["base"] + "/Data/Data_List",
        data={
            "page": "1",
            "pageSize": "3000",
            "parameters[0]": cfg["parameter"],
            "value": "LATEST",
            "type": "Statistic",
            "interval": "Latest",
            "utcOffset": cfg["utc_offset"],
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    rows = None
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) \
                    and "LocationIdentifier" in v[0]:
                rows = v
                break
    return rows or []


def _aquarius_latest_batch(cfg: dict, datasets: list[str]) -> dict[str, tuple[float, str, str]]:
    """dataset -> (m^3/s, obs time, trend over the day) — one CSV export,
    one column per dataset."""
    params: dict[str, str] = {
        "DateRange": "Days1",
        "TimeZone": cfg["tz"],
        "Calendar": "CALENDARYEAR",
        "Interval": "PointsAsRecorded",
        "Step": "1",
        "ExportFormat": "csv",
        "TimeAligned": "True",
        "RoundData": "False",
    }
    for i, ds in enumerate(datasets):
        params[f"Datasets[{i}].DatasetName"] = ds
        params[f"Datasets[{i}].Calculation"] = "Instantaneous"
    r = SESSION.get(cfg["base"] + "/Export/BulkExport", params=params, timeout=120)
    r.raise_for_status()
    lines = r.text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("Timestamp")), None)
    if start is None:
        return {}
    rows = list(csv.reader(io.StringIO("\n".join(lines[start + 1:]))))
    out: dict[str, tuple[float, str, str]] = {}
    for col, ds in enumerate(datasets, start=1):
        first = None
        last = None
        for row in rows:
            if len(row) > col and row[col].strip():
                if first is None:
                    first = row[col]
                last = (row[col], row[0])
        if last:
            try:
                v = float(last[0])
                out[ds] = (v, last[1][:16].replace(" ", "T"),
                           _trend_from_change(float(first), v))
            except ValueError:
                pass
    return out


def _fetch_aquarius_state(state: str, cfg: dict, cells) -> list[dict]:
    rows = _aquarius_datasets(cfg)
    near: list[dict] = []
    for row in rows:
        try:
            lon = float(row.get("LocX"))
            lat = float(row.get("LocY"))
        except (TypeError, ValueError):
            continue
        if not (112.0 < lon < 154.5 and -44.0 < lat < -9.0):
            continue
        if not _near_gold(lon, lat, cells):
            continue
        dataset = row.get("DatasetIdentifier") or ""
        # Continuous records with known units only — one bad dataset name
        # 404s the whole export batch.
        if not dataset or "Field Visits" in dataset:
            continue
        if not dataset.startswith(cfg["prefixes"]):
            continue
        # One dataset per location.
        loc = row.get("LocationIdentifier")
        if any(r.get("LocationIdentifier") == loc for r in near):
            continue
        near.append(row)
        if len(near) >= config.GAUGE_MAX_PER_STATE:
            break

    feats = []
    for i in range(0, len(near), 20):
        batch = near[i:i + 20]
        try:
            latest = _aquarius_latest_batch(cfg, [r["DatasetIdentifier"] for r in batch])
        except Exception:  # noqa: BLE001 — one bad dataset 404s the batch
            latest = {}
            for r in batch:
                try:
                    latest.update(_aquarius_latest_batch(cfg, [r["DatasetIdentifier"]]))
                except Exception:  # noqa: BLE001
                    pass
        for row in batch:
            got = latest.get(row["DatasetIdentifier"])
            if got is None or got[0] < 0:
                continue
            feats.append(_feature(
                state,
                str(row.get("LocationIdentifier") or row["DatasetIdentifier"]),
                str(row.get("Location") or "").strip(),
                float(row["LocX"]), float(row["LocY"]),
                got[0], got[1], trend=got[2], dataset=row["DatasetIdentifier"],
            ))
    return feats


# --- entry point ------------------------------------------------------------

def fetch_gauges(occurrences: list[dict]) -> list[dict] | None:
    """Gauge features near gold country, or None if every state failed."""
    from .grid import gold_grid
    cells = gold_grid(occurrences)
    feats: list[dict] = []
    any_ok = False
    for state, cfg in HYDSTRA_STATES.items():
        try:
            got = _fetch_hydstra_state(state, cfg, cells)
            print(f"[gauges] {state}: {len(got)} gauges")
            feats.extend(got)
            any_ok = True
        except Exception as e:  # noqa: BLE001
            print(f"[gauges] {state} FAILED: {e}")
    for state, cfg in AQUARIUS_STATES.items():
        try:
            got = _fetch_aquarius_state(state, cfg, cells)
            print(f"[gauges] {state}: {len(got)} gauges")
            feats.extend(got)
            any_ok = True
        except Exception as e:  # noqa: BLE001
            print(f"[gauges] {state} FAILED: {e}")
    if not any_ok:
        return None
    feats.sort(key=lambda f: f["properties"]["id"])
    return feats
