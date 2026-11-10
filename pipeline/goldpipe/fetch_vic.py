"""Victoria's own gold register, from the Geological Survey of Victoria (GSV).

OZMIN (the national database) holds roughly 440 gold sites inside Victoria;
GSV's mineral occurrence register holds about 16,350. Both verified live
2026-11 via GSV's open WFS (the same data GeoVic displays).

GSV publishes no per-site names in its open services (the name field is the
record id), so each site is labelled by record number and, where a recorded
mine shaft lies within SHAFT_NAME_RADIUS_M, by that shaft's name.

Because Victoria records far more sites than other states, its records get a
reduced weight so the national heatmap compares states fairly.
"""
import math

from . import config
from .http import get_json

GSV_WFS = "https://geology.data.vic.gov.au/nvcl/wfs"
VIC_OPEN_WFS = "https://opendata.maps.vic.gov.au/geoserver/wfs"
PAGE = 1000  # both servers cap a single response at 1000 features

GSV_WEIGHT = config.GSV_WEIGHT
DEDUPE_RADIUS_M = 100.0
SHAFT_NAME_RADIUS_M = 300.0


def _metres(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2)) * 111_320.0
    return math.hypot((lon2 - lon1) * k, (lat2 - lat1) * 110_540.0)


def _paged(base: str, params: dict) -> list[dict]:
    out: list[dict] = []
    start = 0
    while True:
        page = get_json(
            base,
            params={**params, "count": PAGE, "startIndex": start},
            timeout=180,
        )
        batch = page.get("features", [])
        out.extend(batch)
        if len(batch) < PAGE:
            return out
        start += PAGE


def _number(raw) -> float | None:
    """'802395 (http://…/m3)' -> 802395.0; nil URNs and junk -> None."""
    if raw is None:
        return None
    head = str(raw).split(" ", 1)[0]
    try:
        v = float(head)
    except ValueError:
        return None
    return v if v > 0 else None


class _Grid:
    """Bucketed points for fast nearest-within-radius lookups."""

    CELL = 0.01  # ~1 km

    def __init__(self):
        self.cells: dict[tuple[int, int], list[tuple[float, float, str]]] = {}

    def add(self, lon: float, lat: float, label: str = "") -> None:
        key = (math.floor(lon / self.CELL), math.floor(lat / self.CELL))
        self.cells.setdefault(key, []).append((lon, lat, label))

    def nearest(self, lon: float, lat: float, radius_m: float):
        cx, cy = math.floor(lon / self.CELL), math.floor(lat / self.CELL)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for plon, plat, label in self.cells.get((cx + dx, cy + dy), ()):
                    d = _metres(lon, lat, plon, plat)
                    if d <= radius_m and (best is None or d < best[0]):
                        best = (d, label)
        return best


def fetch_shaft_names() -> _Grid:
    """All named recorded shafts in Victoria (~29k), for labelling sites."""
    grid = _Grid()
    feats = _paged(VIC_OPEN_WFS, {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "open-data-platform:shaft",
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "propertyName": "geom,name", "sortBy": "id",
    })
    for f in feats:
        name = (f.get("properties") or {}).get("name") or ""
        name = name.strip()
        geom = f.get("geometry") or {}
        if name and geom.get("type") == "Point":
            lon, lat = geom["coordinates"][:2]
            grid.add(lon, lat, name)
    return grid


def normalize(feature: dict, shafts: _Grid | None = None) -> dict | None:
    geom = feature.get("geometry") or {}
    if geom.get("type") != "Point":
        return None
    lon, lat = geom["coordinates"][:2]
    x0, y0, x1, y1 = config.AUS_BBOX
    if not (x0 <= lon <= x1 and y0 <= lat <= y1):
        return None
    props = feature.get("properties") or {}
    raw_id = str(feature.get("id") or "")
    num = raw_id.rsplit(".", 1)[-1]
    if not num:
        return None
    kind = (props.get("earthResourceType") or "").lower()
    occ_type = "deposit" if "deposit" in kind else "occurrence"
    out_props = {
        "id": f"gsv.{num}",
        "name": f"VIC gold {occ_type} #{num}",
        "occ_type": occ_type,
        "weight": GSV_WEIGHT,
        "src": "gsv",
    }
    ore = _number(props.get("totalOreAmount"))
    if ore:
        out_props["ore_m3"] = round(ore)
    acc = _number(props.get("positionalAccuracy"))
    if acc:
        out_props["acc_m"] = round(acc)
    if shafts is not None:
        hit = shafts.nearest(lon, lat, SHAFT_NAME_RADIUS_M)
        if hit:
            out_props["near_shaft"] = f"{hit[1].title()} ({round(hit[0])} m)"
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        "properties": out_props,
    }


def fetch_vic_gold_occurrences() -> list[dict]:
    raw = _paged(GSV_WFS, {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "mo:MinOccView", "outputFormat": "application/json",
        "cql_filter": "commodity LIKE '%commodity:Au%'", "sortBy": "identifier",
    })
    try:
        shafts = fetch_shaft_names()
    except Exception as e:  # noqa: BLE001 — names are a nicety, not essential
        print(f"[gsv] shaft names unavailable: {e}")
        shafts = None
    feats = [f for f in (normalize(r, shafts) for r in raw) if f]
    feats.sort(key=lambda f: f["properties"]["id"])
    return feats


def merge(national: list[dict], vic: list[dict]) -> list[dict]:
    """National records plus Victorian ones that aren't already in it (any
    GSV site within DEDUPE_RADIUS_M of a national record is a duplicate)."""
    grid = _Grid()
    for f in national:
        lon, lat = f["geometry"]["coordinates"][:2]
        grid.add(lon, lat)
    extra = [
        f for f in vic
        if grid.nearest(*f["geometry"]["coordinates"][:2], DEDUPE_RADIUS_M) is None
    ]
    merged = national + extra
    merged.sort(key=lambda f: f["properties"]["id"])
    return merged
