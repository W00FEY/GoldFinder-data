"""Public land registry: national parks / protected areas / state forests.

Same shape as the tenement registry (query_templates with {bbox} or
{bbox_latlon} placeholders + field_map with candidate lists; "const:X"
candidates are literals) so the app queries these live per viewport and the
registry stays hot-fixable from the data branch.

CAPAD (national) excludes production state forests, so VIC and NSW state
forest services supplement it; other states' forests are a known gap.
All endpoints verified live 2026-08.
"""
from datetime import datetime, timezone

from . import config
from .http import SESSION
from .tenements import fill_bbox

_ALL_STATES = ["WA", "NT", "SA", "QLD", "NSW", "VIC", "TAS"]

LAND_REGISTRY: dict[str, dict] = {
    "CAPAD": {
        "name": "Protected Areas (CAPAD, national)",
        "states": _ALL_STATES,
        "query_templates": [
            "https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/CAPAD/FeatureServer/0/query"
            "?where=1%3D1&geometry={bbox}&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects&outFields=NAME,TYPE,STATE&outSR=4326"
            "&resultRecordCount=1000&f=geojson"
        ],
        "field_map": {"name": ["NAME"], "type": ["TYPE"], "state": ["STATE"]},
        "attribution": "© Australian Government DCCEEW (CAPAD)",
    },
    "VIC_PUBLIC_LAND": {
        "name": "VIC Public Land incl. State Forests (Vicmap PLM25)",
        "states": ["VIC"],
        "query_templates": [
            "https://opendata.maps.vic.gov.au/geoserver/wfs?service=WFS&version=1.1.0"
            "&request=GetFeature&typeName=open-data-platform:plm25"
            "&outputFormat=application/json"
            "&bbox={bbox_latlon},urn:ogc:def:crs:EPSG::4326&maxFeatures=500"
        ],
        "field_map": {
            "name": ["label", "name"],
            "type": ["mmtgen"],
            "state": ["const:VIC"],
        },
        "attribution": "© State of Victoria (Vicmap, CC BY 4.0)",
    },
    "NSW_STATE_FORESTS": {
        "name": "NSW Dedicated State Forests",
        "states": ["NSW"],
        "query_templates": [
            "https://services2.arcgis.com/iCBB4zKDwkw2iwDD/arcgis/rest/services/NSW_Dedicated_State_Forests/FeatureServer/0/query"
            "?where=1%3D1&geometry={bbox}&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects&outFields=SFName&outSR=4326"
            "&resultRecordCount=1000&f=geojson"
        ],
        "field_map": {
            "name": ["SFName"],
            "type": ["const:State Forest"],
            "state": ["const:NSW"],
        },
        "attribution": "© Forestry Corporation of NSW",
    },
}

_PROBE_BBOX = {
    "CAPAD": (143.7, -37.3, 144.3, -36.7),            # VIC goldfields
    "VIC_PUBLIC_LAND": (144.20, -37.60, 144.45, -37.40),  # Wombat State Forest
    "NSW_STATE_FORESTS": (151.2, -33.2, 151.6, -32.9),    # Awaba
}


def _probe(key: str, src: dict) -> bool:
    url = fill_bbox(src["query_templates"][0], _PROBE_BBOX[key])
    try:
        r = SESSION.get(url, timeout=45)
        r.raise_for_status()
        body = r.json()
        return body.get("type") == "FeatureCollection" and len(body.get("features", [])) > 0
    except Exception as e:  # noqa: BLE001 — health check must not raise
        print(f"[land] {key} probe failed: {e}")
        return False


def build_land_sources() -> dict:
    sources = {}
    for key, src in LAND_REGISTRY.items():
        ok = _probe(key, src)
        sources[key] = {**src, "status": "ok" if ok else "down"}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": config.SCHEMA_VERSION,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "sources": sources,
    }
