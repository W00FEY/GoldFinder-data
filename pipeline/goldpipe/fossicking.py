"""Legal fossicking area registry — where recreational prospecting is
allowed (QLD fossicking areas/GPAs, NSW fossicking districts) or explicitly
prohibited/restricted (VIC restricted Crown land, NSW state-forest
exclusions). WA publishes no such dataset (Miner's Right rules apply
statewide); TAS/SA/NT have no official open services — honest gaps.

Each source's `rule` field_map const tells the app the semantics:
allowed | prohibited | restricted. All endpoints verified live 2026-08.
"""
from datetime import datetime, timezone

from . import config
from .http import SESSION
from .tenements import fill_bbox

_QLD_BASE = (
    "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Boundaries/"
    "MiningAdministrativeAreas/MapServer"
)
_QLD_SUFFIX = (
    "/query?where=1%3D1&geometry={bbox}&geometryType=esriGeometryEnvelope&inSR=4326"
    "&spatialRel=esriSpatialRelIntersects&outFields=parcel_type,parcel_name,lot_plan"
    "&returnGeometry=true&outSR=4326&resultRecordCount=1000"
    "&maxAllowableOffset=0.0003&geometryPrecision=5&f=geojson"
)

FOSSICK_REGISTRY: dict[str, dict] = {
    "QLD_ALLOWED": {
        "name": "QLD Fossicking Areas, Designated Land & General Permission Areas",
        "states": ["QLD"],
        "query_templates": [
            f"{_QLD_BASE}/11{_QLD_SUFFIX}",
            f"{_QLD_BASE}/15{_QLD_SUFFIX}",
            f"{_QLD_BASE}/20{_QLD_SUFFIX}",
        ],
        "field_map": {
            "name": ["parcel_name"],
            "type": ["parcel_type"],
            "rule": ["const:allowed"],
        },
        "attribution": "© State of Queensland (Department of Resources)",
    },
    "NSW_DISTRICTS": {
        "name": "NSW Fossicking Districts",
        "states": ["NSW"],
        "query_templates": [
            "https://spatial.industry.nsw.gov.au/arcgis/rest/services/PUBLIC/Fossicking_Districts/MapServer/0"
            "/query?where=1%3D1&geometry={bbox}&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects&outFields=District_Name,District_Number"
            "&returnGeometry=true&outSR=4326&resultRecordCount=1000"
            "&maxAllowableOffset=0.0003&geometryPrecision=5&f=geojson"
        ],
        "field_map": {
            "name": ["District_Name"],
            "type": ["const:Fossicking District"],
            "rule": ["const:allowed"],
        },
        "attribution": "© State of New South Wales (NSW Resources)",
    },
    "NSW_SF_EXCLUSIONS": {
        "name": "NSW State Forest Fossicking Exclusions",
        "states": ["NSW"],
        "query_templates": [
            "https://services2.arcgis.com/iCBB4zKDwkw2iwDD/arcgis/rest/services/State_Forest_Fossicking_Exclusions/FeatureServer/0"
            "/query?where=1%3D1&geometry={bbox}&geometryType=esriGeometryEnvelope&inSR=4326"
            "&spatialRel=esriSpatialRelIntersects&outFields=FossickingExclusion"
            "&returnGeometry=true&outSR=4326&resultRecordCount=1000"
            "&maxAllowableOffset=0.0003&geometryPrecision=5&f=geojson"
        ],
        "field_map": {
            "name": ["FossickingExclusion"],
            "type": ["const:State forest fossicking exclusion"],
            "rule": ["const:prohibited"],
        },
        "attribution": "© Forestry Corporation of NSW",
    },
    "VIC_RESTRICTED": {
        "name": "VIC Restricted/Unavailable Crown Land (MRSDA)",
        "states": ["VIC"],
        "query_templates": [
            "https://opendata.maps.vic.gov.au/geoserver/wfs?service=WFS&version=2.0.0"
            "&request=GetFeature&typeNames=open-data-platform:plm25_mrsda"
            "&outputFormat=application/json"
            "&bbox={bbox_latlon},urn:ogc:def:crs:EPSG::4326&count=1000"
        ],
        "field_map": {
            "name": ["label_short"],
            "type": ["act_desc"],
            "rule": ["const:restricted"],
        },
        "attribution": "© State of Victoria (DEECA, Vicmap)",
    },
}

_PROBE_BBOX = {
    "QLD_ALLOWED": (147.5, -22.9, 147.7, -22.7),       # Clermont GPAs (layer 20)
    "NSW_DISTRICTS": (149.4, -33.8, 149.9, -33.3),     # Bathurst/Blayney
    "NSW_SF_EXCLUSIONS": (148.0, -34.0, 152.0, -32.0), # central NSW forests
    "VIC_RESTRICTED": (144.1, -36.9, 144.5, -36.6),    # Bendigo
}


def _probe(key: str, src: dict) -> bool:
    # QLD_ALLOWED spans 3 layers; probe the GPA layer (last) which covers the
    # probe bbox. Others have a single template.
    template = src["query_templates"][-1]
    url = fill_bbox(template, _PROBE_BBOX[key])
    try:
        r = SESSION.get(url, timeout=45)
        r.raise_for_status()
        body = r.json()
        return body.get("type") == "FeatureCollection" and len(body.get("features", [])) > 0
    except Exception as e:  # noqa: BLE001 — health check must not raise
        print(f"[fossicking] {key} probe failed: {e}")
        return False


def build_fossicking_sources() -> dict:
    sources = {}
    for key, src in FOSSICK_REGISTRY.items():
        ok = _probe(key, src)
        sources[key] = {**src, "status": "ok" if ok else "down"}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": config.SCHEMA_VERSION,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "sources": sources,
    }
