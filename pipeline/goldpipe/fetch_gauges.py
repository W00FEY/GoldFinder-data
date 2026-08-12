"""Current river flow from state gauge networks, for gauges near gold country.

Two stacks cover five states (verified live 2026-08):
- Hydstra JSON web services: VIC (data.water.vic.gov.au/WMIS) and QLD
  (water-monitoring.information.qld.gov.au). Variable 100.00 is level,
  rated to 140.00 = discharge in m^3/s.
- Aquarius WebPortal: TAS (portal.wrt.tas.gov.au), SA (water.data.sa.gov.au),
  NT (ntg.aquaticinformatics.net). POST /Data/Data_List lists discharge
  datasets with coordinates; GET /Export/BulkExport returns a CSV whose last
  row is the latest instantaneous discharge in m^3/s.

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


def _feature(state, sid, name, lon, lat, cumecs, obs_time) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        "properties": {
            "id": f"{state}:{sid}",
            "state": state,
            "name": name or sid,
            "flow": round(cumecs, 3),
            "flow_mld": round(cumecs * 86.4, 1),
            "cat": _flow_category(cumecs),
            "obs": obs_time,
        },
    }


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
        ret = _hydstra(base, {
            "function": "get_site_geojson",
            "version": "2",
            "params": {"site_list": ",".join(chunk), "fields": ["stname"], "get_elev": 0},
        })
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


def _hydstra_latest(base: str, datasource: str, sites: list[str]) -> dict[str, tuple[float, str]]:
    """site -> (discharge m^3/s, obs time ISO) via 100.00 -> 140.00 rating."""
    out: dict[str, tuple[float, str]] = {}
    for i in range(0, len(sites), 60):
        chunk = sites[i:i + 60]
        try:
            ret = _hydstra(base, {
                "function": "get_latest_ts_values",
                "version": "2",
                "params": {
                    "site_list": ",".join(chunk),
                    "datasource": datasource,
                    "trace_list": [{"varfrom": "100.00", "varto": "140.00"}],
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
                out[str(sid)] = (v, iso)
    return out


def _fetch_hydstra_state(state: str, cfg: dict, cells) -> list[dict]:
    sites = _hydstra_sites(cfg["base"], cfg["datasource"])
    coords = _hydstra_coords(cfg["base"], sites)
    near = {
        sid: c for sid, c in coords.items()
        if _near_gold(c[0], c[1], cells)
    }
    picked = list(near.keys())[: config.GAUGE_MAX_PER_STATE]
    latest = _hydstra_latest(cfg["base"], cfg["datasource"], picked)
    feats = []
    for sid, (v, iso) in latest.items():
        lon, lat, name = near[sid]
        if v >= 0:
            feats.append(_feature(state, sid, name, lon, lat, v, iso))
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


def _aquarius_latest_batch(cfg: dict, datasets: list[str]) -> dict[str, tuple[float, str]]:
    """dataset -> (m^3/s, obs time) — one CSV export, one column per dataset."""
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
    out: dict[str, tuple[float, str]] = {}
    for col, ds in enumerate(datasets, start=1):
        last = None
        for row in rows:
            if len(row) > col and row[col].strip():
                last = (row[col], row[0])
        if last:
            try:
                out[ds] = (float(last[0]), last[1][:16].replace(" ", "T"))
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
                got[0], got[1],
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
