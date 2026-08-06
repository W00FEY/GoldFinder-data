"""Per-state tenement service registry + daily health check.

The app queries these services live for its viewport; this module verifies
they respond and publishes the registry (tenement_sources.json) so endpoints
can be hot-fixed on the data branch without an app update.

Every endpoint below was verified with live bbox queries (2026-08). Formats:
- query_templates: list of URLs with {bbox} (lon_min,lat_min,lon_max,lat_max)
  or {bbox_latlon} (lat,lon order — GeoServer WFS with urn axis order)
  placeholders. All return GeoJSON FeatureCollections.
- field_map: normalized key -> list of candidate property names (first match
  wins; states with multiple layers need fallbacks).
"""
from datetime import datetime, timezone

from . import config
from .http import SESSION

# maxAllowableOffset simplifies polygons server-side (~33 m at 0.0003 deg) and
# geometryPrecision trims coordinate decimals — without them a dense viewport
# OOM-crashed the app on a 256 MB heap.
_ARCGIS_SUFFIX = (
    "query?where=1%3D1&geometry={bbox}&geometryType=esriGeometryEnvelope"
    "&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields={fields}"
    "&outSR=4326&resultRecordCount=800&maxAllowableOffset=0.0003"
    "&geometryPrecision=5&f=geojson"
)


def _arcgis(base: str, fields: str) -> str:
    return f"{base}/{_ARCGIS_SUFFIX.replace('{fields}', fields)}"


REGISTRY: dict[str, dict] = {
    "WA": {
        "name": "WA Mining Tenements (DMIRS / SLIP)",
        "query_templates": [
            _arcgis(
                "https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Industry_and_Mining/MapServer/3",
                "fmt_tenid,type,tenstatus,holder1,startdate,enddate",
            )
        ],
        "field_map": {
            "id": ["fmt_tenid"], "type": ["type"], "status": ["tenstatus"],
            "holder": ["holder1"], "start": ["startdate"], "end": ["enddate"],
        },
        "attribution": "© Government of Western Australia (DMIRS)",
    },
    "QLD": {
        "name": "QLD Mineral Tenements",
        "query_templates": [
            _arcgis(
                "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Economy/MineralTenement/FeatureServer/0",
                "tenname,tentype,tenstatus,tenowner,grantdate,expiredate",
            )
        ],
        "field_map": {
            "id": ["tenname"], "type": ["tentype"], "status": ["tenstatus"],
            "holder": ["tenowner"], "start": ["grantdate"], "end": ["expiredate"],
        },
        "attribution": "© State of Queensland",
    },
    "NSW": {
        "name": "NSW Mineral Titles (MinView)",
        "query_templates": [
            "https://gs.geoscience.nsw.gov.au/geoserver/ows?service=WFS&version=2.0.0"
            "&request=GetFeature&typeNames=mt:MineralTenement"
            "&bbox={bbox_latlon},urn:ogc:def:crs:EPSG::4326"
            "&count=400&outputFormat=application/json"
        ],
        "field_map": {
            "id": ["name"], "type": ["tenementType"], "status": ["status"],
            "holder": ["owner"], "start": ["grantDate"], "end": ["expireDate"],
        },
        "attribution": "© State of New South Wales",
    },
    "VIC": {
        "name": "VIC Mineral Tenements (GeoVic)",
        "query_templates": [
            "https://geology.data.vic.gov.au/nvcl/wfs?service=WFS&version=2.0.0"
            "&request=GetFeature&typeNames=mt:MineralTenement"
            "&outputFormat=application/json&count=400&bbox={bbox},EPSG:4326"
        ],
        "field_map": {
            "id": ["name"], "type": ["tenementType"], "status": ["status"],
            "holder": ["owner"], "start": ["grantDate"], "end": ["expireDate"],
        },
        "attribution": "© State of Victoria (Geological Survey of Victoria)",
    },
    "SA": {
        "name": "SA Mineral Tenements (SARIG)",
        "query_templates": [
            "https://services.sarig.sa.gov.au/vector/mineral_tenements/wfs?service=WFS"
            "&version=1.1.0&request=GetFeature"
            "&typeName=mineral_tenements:mineral_and_or_opal_exploration_licence,"
            "mineral_tenements:mineral_leases,mineral_tenements:extractive_mineral_leases,"
            "mineral_tenements:retention_leases,mineral_tenements:mineral_claims"
            "&outputFormat=application/json&maxFeatures=400&bbox={bbox},EPSG:4326"
        ],
        "field_map": {
            "id": ["TENEMENT_LABEL"],
            "type": ["TENEMENT_TYPE"],
            "status": ["TENEMENT_STATUS", "OPERATION_STATUS"],
            "holder": ["LICENCEES", "TENEMENT_HOLDERS"],
            "start": ["TENEMENT_START_DATE", "REGISTRATION_GRANT_DATE"],
            "end": ["TENEMENT_EXPIRY_DATE", "EXPIRY_DATE"],
        },
        "attribution": "© Government of South Australia (Dept for Energy and Mining)",
    },
    "NT": {
        "name": "NT Mineral Titles (STRIKE)",
        "query_templates": [
            "https://geology.data.nt.gov.au/geoserver/wfs?service=WFS&version=2.0.0"
            "&request=GetFeature&typeNames=mt:MineralTenement"
            "&bbox={bbox_latlon},urn:ogc:def:crs:EPSG::4326"
            "&count=400&outputFormat=application/json"
        ],
        # NT publishes no grant/expiry dates in this service.
        "field_map": {
            "id": ["name"], "type": ["tenementType"], "status": ["status"],
            "holder": ["owner"], "start": ["applicationDate"], "end": [],
        },
        "attribution": "© Northern Territory Government (NTGS)",
    },
    "TAS": {
        "name": "TAS Mineral Tenements (MRT)",
        "query_templates": [
            _arcgis(
                "https://data.stategrowth.tas.gov.au/ags/rest/services/MRT/Tenements_Land_Management/MapServer/3",
                "NAME,TENEMENTTYPE,STATUS,OWNER,GRANTDATE,EXPIREDATE",
            ),
            _arcgis(
                "https://data.stategrowth.tas.gov.au/ags/rest/services/MRT/Tenements_Land_Management/MapServer/5",
                "NAME,TENEMENTTYPE,STATUS,OWNER,GRANTDATE,EXPIREDATE",
            ),
        ],
        "field_map": {
            "id": ["NAME"], "type": ["TENEMENTTYPE"], "status": ["STATUS"],
            "holder": ["OWNER"], "start": ["GRANTDATE"], "end": ["EXPIREDATE"],
        },
        "attribution": "© Mineral Resources Tasmania",
    },
}

# A small bbox inside each state used by the health check (known active areas).
_PROBE_BBOX = {
    "WA": (121.4, -30.8, 121.5, -30.7),      # Kalgoorlie
    "QLD": (146.2, -20.1, 146.4, -19.9),     # Charters Towers
    "NSW": (149.2, -33.5, 149.4, -33.3),     # Orange
    "VIC": (143.7, -37.0, 143.9, -36.8),     # Ballarat
    "SA": (137.4, -33.1, 137.9, -32.6),      # Middleback
    "NT": (133.8, -19.7, 134.0, -19.5),      # Tennant Creek
    "TAS": (145.2, -41.95, 145.45, -41.7),   # Zeehan
}


def fill_bbox(template: str, bbox: tuple[float, float, float, float]) -> str:
    w, s, e, n = bbox
    return template.replace("{bbox}", f"{w},{s},{e},{n}").replace(
        "{bbox_latlon}", f"{s},{w},{n},{e}"
    )


def _probe(state: str, src: dict) -> bool:
    url = fill_bbox(src["query_templates"][0], _PROBE_BBOX[state])
    try:
        r = SESSION.get(url, timeout=45)
        r.raise_for_status()
        body = r.json()
        return body.get("type") == "FeatureCollection" and len(body.get("features", [])) > 0
    except Exception as e:  # noqa: BLE001 — health check must not raise
        print(f"[tenements] {state} probe failed: {e}")
        return False


def build_tenement_sources() -> dict:
    sources = {}
    for state, src in REGISTRY.items():
        ok = _probe(state, src)
        sources[state] = {**src, "status": "ok" if ok else "down"}
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": config.SCHEMA_VERSION,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "sources": sources,
    }
