"""Waterway (creeks/rivers) and track registries — live viewport layers.

Same registry pattern as land.py/tenements.py. Both endpoints verified live
(2026-08):
- Waterways: GA Australian Surface Hydrology, regional detail layer (1:250k),
  named creeks/rivers with hierarchy + perenniality. Dense data — server-side
  simplification and a record cap keep payloads phone-sized.
- Tracks: Digital Atlas of Australia (Geoscape) National Roads, filtered to
  vehicle tracks + footpaths, with surface and 2WD/4WD trafficability.
"""
from datetime import datetime, timezone

from . import config
from .http import SESSION
from .tenements import fill_bbox

_ALL_STATES = ["WA", "NT", "SA", "QLD", "NSW", "VIC", "TAS"]

WATER_REGISTRY: dict[str, dict] = {
    "GA_HYDRO": {
        "name": "Australian Surface Hydrology (Geoscience Australia)",
        "states": _ALL_STATES,
        "query_templates": [
            "https://services.ga.gov.au/gis/rest/services/Surface_Hydrology/MapServer/3/query"
            "?where=1%3D1&geometry={bbox}&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects"
            "&outFields=name,hierarchy,perenniality,featuretype&outSR=4326"
            "&resultRecordCount=1000&maxAllowableOffset=0.0002&geometryPrecision=5"
            "&f=geojson"
        ],
        "field_map": {
            "name": ["name"],
            "type": ["hierarchy"],
            "flow": ["perenniality"],
        },
        "attribution": "© Geoscience Australia (AusHydro, CC BY 4.0)",
    },
}

TRACK_REGISTRY: dict[str, dict] = {
    "NATIONAL_ROADS": {
        "name": "Vehicle tracks & footpaths (Digital Atlas of Australia)",
        "states": _ALL_STATES,
        "query_templates": [
            "https://services-ap1.arcgis.com/ypkPEy1AmwPKGNNv/arcgis/rest/services/National_Roads/FeatureServer/0/query"
            "?where=hierarchy%20IN%20(%27VEHICLE%20TRACK%27,%27FOOTPATH%27)"
            "&geometry={bbox}&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects"
            "&outFields=full_street_name,hierarchy,surface,trafficability&outSR=4326"
            "&resultRecordCount=1500&maxAllowableOffset=0.0002&geometryPrecision=5"
            "&f=geojson"
        ],
        "field_map": {
            "name": ["full_street_name"],
            "type": ["hierarchy"],
            "surface": ["surface"],
            "traffic": ["trafficability"],
        },
        "attribution": "© Geoscape Australia / Digital Atlas of Australia (CC BY 4.0)",
    },
}

_PROBE_BBOX = {
    "GA_HYDRO": (143.75, -37.7, 143.95, -37.5),        # Yarrowee River, Ballarat
    "NATIONAL_ROADS": (144.2, -37.5, 144.4, -37.35),   # Wombat State Forest tracks
}


def _probe(key: str, src: dict) -> bool:
    url = fill_bbox(src["query_templates"][0], _PROBE_BBOX[key])
    try:
        r = SESSION.get(url, timeout=45)
        r.raise_for_status()
        body = r.json()
        return body.get("type") == "FeatureCollection" and len(body.get("features", [])) > 0
    except Exception as e:  # noqa: BLE001 — health check must not raise
        print(f"[waterways] {key} probe failed: {e}")
        return False


def _build(registry: dict[str, dict]) -> dict:
    sources = {}
    for key, src in registry.items():
        ok = _probe(key, src)
        sources[key] = {**src, "status": "ok" if ok else "down"}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": config.SCHEMA_VERSION,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "sources": sources,
    }


def build_waterway_sources() -> dict:
    return _build(WATER_REGISTRY)


def build_track_sources() -> dict:
    return _build(TRACK_REGISTRY)
