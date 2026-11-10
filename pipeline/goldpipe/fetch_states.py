"""Western Australia's and New South Wales' own gold registers.

Both state geological surveys publish their mineral occurrence registers
through the same open national standard service (mo:MinOccView) that
Victoria's GSV uses. Verified live 2026-11:

  * GSWA (WA):   ~85,900 gold records, many with site names.
  * GSNSW (NSW): ~6,600 gold records, no per-site names in the open service.

OZMIN, the national database, holds only a small fraction of these.

The state registers are dense: WA lists every abandoned mine feature, so a
single goldfield can hold thousands of points metres apart. Publishing them
all would swamp the phone and the heatmap, so nearby records are folded into
one site per grid cell. Each published site keeps the best-named record's
identity, says how many records it stands for, and carries a weight that
grows gently with that number.

Queensland, South Australia and the Northern Territory do not offer this
service, and Tasmania's refuses automated clients, so those states still
rely on the national database.
"""
import math

from . import config
from .fetch_vic import _Grid, _metres  # noqa: F401 — shared helpers
from .http import get_json

REGISTERS = {
    "gswa": {
        "state": "WA",
        "url": "https://geossdi.dmp.wa.gov.au/services/ows",
        "cql": "commodity LIKE '%Au%'",
        "token": "au",
        "page": 10000,
        "cell": 0.01,  # ~1 km
    },
    "gsnsw": {
        "state": "NSW",
        "url": "https://gs.geoscience.nsw.gov.au/geoserver/ows",
        "cql": "commodity LIKE '%gold%'",
        "token": "gold",
        "page": 5000,
        "cell": 0.005,  # ~500 m
    },
}

_ELEMENTS = {
    "au": "Gold", "ag": "Silver", "cu": "Copper", "pb": "Lead", "zn": "Zinc",
    "ni": "Nickel", "sn": "Tin", "w": "Tungsten", "sb": "Antimony",
    "pt": "Platinum", "fe": "Iron", "as": "Arsenic", "bi": "Bismuth",
    "co": "Cobalt", "mo": "Molybdenum",
}


def _commodities(raw: str) -> str:
    """'Au,Ag' -> 'Gold, Silver'; 'copper,gold' -> 'Copper, Gold'."""
    parts = [t.strip() for t in raw.split(",") if t.strip()]
    return ", ".join(_ELEMENTS.get(t.lower(), t.capitalize() if t.islower() else t) for t in parts)


BASE_WEIGHT = config.GSV_WEIGHT
MAX_WEIGHT = 3.0
MAX_PAGES = 40
DEDUPE_RADIUS_M = 100.0


def site_weight(records: int) -> float:
    """One lone record counts like a Victorian one; a cluster counts for more,
    but logarithmically, so a field of 2,000 shafts doesn't flatten the map."""
    return round(min(MAX_WEIGHT, BASE_WEIGHT * (1 + math.log(max(1, records)))), 2)


def _is_named(name: str) -> bool:
    n = name.strip().lower()
    return bool(n) and not n.startswith(("wabmines", "er.mineraloccurrence", "unnamed"))


def normalize(feature: dict, source: str) -> dict | None:
    """One raw register record -> a flat dict, or None if unusable."""
    reg = REGISTERS[source]
    geom = feature.get("geometry") or {}
    if geom.get("type") != "Point":
        return None
    lon, lat = geom["coordinates"][:2]
    x0, y0, x1, y1 = config.AUS_BBOX
    if not (x0 <= lon <= x1 and y0 <= lat <= y1):
        return None
    props = feature.get("properties") or {}
    commodity = str(props.get("commodity") or "")
    tokens = [t.strip().lower() for t in commodity.split(",")]
    if reg["token"] not in tokens:
        return None  # e.g. '%Au%' also matches unrelated codes
    num = str(feature.get("id") or "").rsplit(".", 1)[-1]
    if not num:
        return None
    kind = str(props.get("earthResourceType") or "").lower()
    name = str(props.get("name") or "").strip()
    return {
        "num": num,
        "lon": lon,
        "lat": lat,
        "name": name if _is_named(name) else "",
        "occ_type": "deposit" if "deposit" in kind else "occurrence",
        "commodity": _commodities(commodity),
    }


def aggregate(records: list[dict], source: str) -> list[dict]:
    """Fold records into one published site per grid cell."""
    reg = REGISTERS[source]
    cell = reg["cell"]
    cells: dict[tuple[int, int], list[dict]] = {}
    for r in records:
        key = (math.floor(r["lon"] / cell), math.floor(r["lat"] / cell))
        cells.setdefault(key, []).append(r)
    out = []
    for group in cells.values():
        # Representative: named first, then deposits, then the lowest id —
        # deterministic, so a site keeps its identity from day to day.
        rep = min(
            group,
            key=lambda r: (not r["name"], r["occ_type"] != "deposit", r["num"]),
        )
        n = len(group)
        label = rep["name"] or f"{reg['state']} gold {rep['occ_type']} #{rep['num']}"
        props = {
            "id": f"{source}.{rep['num']}",
            "name": label,
            "occ_type": rep["occ_type"],
            "commodity": rep["commodity"],
            "weight": site_weight(n),
            "src": source,
        }
        if n > 1:
            props["sites"] = n
        out.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(rep["lon"], 5), round(rep["lat"], 5)],
            },
            "properties": props,
        })
    out.sort(key=lambda f: f["properties"]["id"])
    return out


def _fetch_raw(source: str) -> list[dict]:
    reg = REGISTERS[source]
    out: list[dict] = []
    for i in range(MAX_PAGES):
        page = get_json(
            reg["url"],
            params={
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeNames": "mo:MinOccView", "outputFormat": "application/json",
                "cql_filter": reg["cql"], "sortBy": "identifier",
                "count": reg["page"], "startIndex": i * reg["page"],
            },
            timeout=240,
        )
        batch = page.get("features", [])
        out.extend(batch)
        if len(batch) < reg["page"]:
            break
    return out


def fetch_state_gold(source: str) -> tuple[list[dict], int]:
    """(published sites, number of raw register records they stand for)."""
    records = [r for r in (normalize(f, source) for f in _fetch_raw(source)) if r]
    return aggregate(records, source), len(records)


def merge(existing: list[dict], state: list[dict]) -> list[dict]:
    """Existing records plus state sites not already present within
    DEDUPE_RADIUS_M (the national database wins a tie: it has richer detail)."""
    grid = _Grid()
    for f in existing:
        lon, lat = f["geometry"]["coordinates"][:2]
        grid.add(lon, lat)
    extra = [
        f for f in state
        if grid.nearest(*f["geometry"]["coordinates"][:2], DEDUPE_RADIUS_M) is None
    ]
    merged = existing + extra
    merged.sort(key=lambda f: f["properties"]["id"])
    return merged
