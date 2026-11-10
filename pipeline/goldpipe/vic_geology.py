"""Victorian geology registry: the open data behind GSV's GeoVic viewer.

Published as vic_geology_sources.json (hot-fixable, like the other
registries). All endpoints verified live 2026-11 on Victoria's open data
GeoServer:

- GEOLOGY: 1:50k seamless geology (~49k units). Far too heavy as vector
  data, so the app shows the server's own map tiles (GSV's official
  colours) and asks the server what rock is under a tap.
- FAULTS: mapped faults from the 1:100k line layer (~222k lines incl.
  contacts); a CQL filter draws faults only. Tiles + tap lookup as above.
- SHAFTS: ~29k recorded historic mine shafts. Live viewport points.
- GOLDFIELDS: named goldfield outlines. Only Bendigo and the Mt William
  fields near Ararat are published — not statewide.

Raster templates use MapLibre's {bbox-epsg-3857} token. Lookup templates
use {bbox} (lon/lat), {width}, {height}, {x}, {y}, filled in by the app.
"""
from datetime import datetime, timezone

from . import config
from .http import SESSION
from .tenements import fill_bbox

_OPEN = "https://opendata.maps.vic.gov.au/geoserver"
_FAULT_FILTER = "&CQL_FILTER=feature%3D%27FAULT%27"


def _tiles(layer: str, extra: str = "") -> str:
    return (
        f"{_OPEN}/wms?service=WMS&version=1.1.1&request=GetMap"
        f"&layers=open-data-platform:{layer}&styles=&format=image/png&transparent=true"
        "&srs=EPSG:3857&width=256&height=256&bbox={bbox-epsg-3857}" + extra
    )


def _lookup(layer: str, buffer: int, extra: str = "") -> str:
    return (
        f"{_OPEN}/wms?service=WMS&version=1.1.1&request=GetFeatureInfo"
        f"&layers=open-data-platform:{layer}&query_layers=open-data-platform:{layer}"
        "&styles=&srs=EPSG:4326&bbox={bbox}&width={width}&height={height}"
        "&x={x}&y={y}&info_format=application/json&feature_count=1"
        f"&buffer={buffer}" + extra
    )


def _wfs(layer: str, props: str, count: int) -> str:
    return (
        f"{_OPEN}/wfs?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeNames=open-data-platform:{layer}&outputFormat=application/json"
        f"&srsName=EPSG:4326&count={count}&propertyName=geom,{props}"
        "&bbox={bbox_latlon},urn:ogc:def:crs:EPSG::4326"
    )


_ATTRIB = "© State of Victoria (Geological Survey of Victoria), CC BY 4.0"

REGISTRY: dict[str, dict] = {
    "VIC_GEOLOGY": {
        "name": "Victorian geology 1:50k (GSV)",
        "kind": "raster",
        "states": ["VIC"],
        "query_templates": [
            _tiles("sg_geological_unit_50k"),
            _lookup("sg_geological_unit_50k", buffer=1),
        ],
        "field_map": {
            "name": ["name"],
            "desc": ["description"],
            "lith": ["lithology"],
            "history": ["geologichistory"],
        },
        "attribution": _ATTRIB,
    },
    "VIC_FAULTS": {
        "name": "Victorian faults 1:100k (GSV)",
        "kind": "raster",
        "states": ["VIC"],
        "query_templates": [
            _tiles("geol100_arc", _FAULT_FILTER),
            _lookup("geol100_arc", buffer=12, extra=_FAULT_FILTER),
        ],
        "field_map": {
            "name": ["name", "flt_system"],
            "desc": ["desc_sde"],
            "accuracy": ["accuracy"],
        },
        "attribution": _ATTRIB,
    },
    "VIC_SHAFTS": {
        "name": "Historic mine shafts (GSV)",
        "kind": "vector",
        "states": ["VIC"],
        "query_templates": [
            _wfs("shaft", "name,depth_m,recl_meth,locn_desc,locacc", 1500),
        ],
        "field_map": {
            "name": ["name"],
            "depth": ["depth_m"],
            "capped": ["recl_meth"],
            "note": ["locn_desc"],
        },
        "attribution": _ATTRIB,
    },
    "VIC_GOLDFIELDS": {
        "name": "Goldfield boundaries (GSV)",
        "kind": "vector",
        "states": ["VIC"],
        "query_templates": [
            _wfs("goldfld100_polygon", "name,hectares", 500),
        ],
        "field_map": {
            "name": ["name"],
            "hectares": ["hectares"],
        },
        "attribution": _ATTRIB,
    },
}

# Probe areas: Ballarat for geology/faults/shafts; Bendigo for goldfields.
_PROBE = {
    "VIC_GEOLOGY": (143.79, -37.58, 143.89, -37.48),
    "VIC_FAULTS": (143.70, -37.65, 144.00, -37.40),
    "VIC_SHAFTS": (143.75, -37.65, 143.95, -37.45),
    "VIC_GOLDFIELDS": (144.22, -36.83, 144.32, -36.70),
}
# One web-mercator tile over Ballarat for raster probes.
_PROBE_3857 = "15996000,-4530000,16030000,-4496000"


def _probe(key: str, src: dict) -> bool:
    try:
        if src.get("kind") == "raster":
            url = src["query_templates"][0].replace("{bbox-epsg-3857}", _PROBE_3857)
            r = SESSION.get(url, timeout=60)
            r.raise_for_status()
            return r.headers.get("content-type", "").startswith("image/") and len(r.content) > 500
        url = fill_bbox(src["query_templates"][0], _PROBE[key])
        r = SESSION.get(url, timeout=60)
        r.raise_for_status()
        body = r.json()
        return body.get("type") == "FeatureCollection" and len(body.get("features", [])) > 0
    except Exception as e:  # noqa: BLE001 — a health check must not raise
        print(f"[vic_geology] {key} probe failed: {e}")
        return False


def build_vic_geology_sources() -> dict:
    sources = {}
    for key, src in REGISTRY.items():
        sources[key] = {**src, "status": "ok" if _probe(key, src) else "down"}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": config.SCHEMA_VERSION,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "sources": sources,
    }
