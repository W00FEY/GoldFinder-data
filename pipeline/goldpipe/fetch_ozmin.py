"""Fetch all gold occurrences from Geoscience Australia's OZMIN WFS."""
import re

from . import config
from .http import get_json

_ALLUVIAL = re.compile(config.ALLUVIAL_RE, re.I)


def _occ_type(props: dict) -> str:
    raw = (props.get("mineralOccurrenceType") or "").strip().lower()
    if raw:
        return raw
    uri = props.get("observationMethod") or ""
    return uri.rsplit("/", 1)[-1] or "occurrence"


def _in_australia(lon: float, lat: float) -> bool:
    x0, y0, x1, y1 = config.AUS_BBOX
    return x0 <= lon <= x1 and y0 <= lat <= y1


def _normalize(feature: dict) -> dict | None:
    geom = feature.get("geometry")
    if not geom or geom.get("type") != "Point":
        return None
    lon, lat = geom["coordinates"][:2]
    if not _in_australia(lon, lat):
        return None
    props = feature.get("properties", {})
    occ_type = _occ_type(props)
    name = props.get("name") or props.get("mineName") or "Unnamed"
    model = props.get("mineralDepositModel") or ""
    alluvial = bool(_ALLUVIAL.search(f"{model} {name}"))
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        "properties": {
            "id": str(feature.get("id") or props.get("identifier")),
            "name": name,
            "occ_type": occ_type,
            "commodity": props.get("commodity") or "Gold",
            "deposit_model": model or None,
            "alluvial": alluvial,
            "weight": config.OCC_WEIGHTS.get(occ_type, config.DEFAULT_OCC_WEIGHT),
            "url": props.get("specification_uri"),
        },
    }


def fetch_gold_occurrences() -> list[dict]:
    """All OZMIN gold occurrences inside the Australian bbox, paged."""
    features: list[dict] = []
    start = 0
    while True:
        page = get_json(
            config.OZMIN_WFS,
            params={
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": config.OZMIN_TYPENAME,
                "outputFormat": "application/json",
                "cql_filter": "commodity LIKE '%Gold%'",
                "count": config.OZMIN_PAGE_SIZE,
                "startIndex": start,
            },
            timeout=120,
        )
        batch = page.get("features", [])
        for f in batch:
            norm = _normalize(f)
            if norm:
                features.append(norm)
        if len(batch) < config.OZMIN_PAGE_SIZE:
            break
        start += config.OZMIN_PAGE_SIZE
    # Stable order so diffs and git commits are deterministic.
    features.sort(key=lambda f: f["properties"]["id"])
    return features
