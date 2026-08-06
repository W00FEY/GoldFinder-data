"""Campgrounds across Australia from OpenStreetMap via Overpass.

Fail-soft like every fetcher: any error returns None and the section goes
stale. Multiple Overpass instances are tried in order (the main one is often
busy).
"""
from . import config
from .http import SESSION

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

_QUERY = """
[out:json][timeout:180];
nwr["tourism"~"^(camp_site|caravan_site)$"]({s},{w},{n},{e});
out center qt;
""".strip()


def _element_to_feature(el: dict) -> dict | None:
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lon is None:
        return None
    tags = el.get("tags", {})
    props = {
        "id": f"{el['type']}/{el['id']}",
        "name": tags.get("name") or "Campground",
        "camp_type": tags.get("tourism"),
    }
    # Only keep the tags prospectors care about, to hold the file size down.
    for key in ("fee", "operator", "access", "drinking_water", "toilets"):
        if tags.get(key):
            props[key] = tags[key]
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        "properties": props,
    }


def fetch_camp_sites() -> list[dict] | None:
    w, s, e, n = config.AUS_BBOX
    query = _QUERY.format(s=s, w=w, n=n, e=e)
    for url in OVERPASS_ENDPOINTS:
        try:
            r = SESSION.post(url, data={"data": query}, timeout=240)
            r.raise_for_status()
            elements = r.json().get("elements", [])
        except Exception as ex:  # noqa: BLE001 — fail-soft by design
            print(f"[camps] {url} failed: {ex}")
            continue
        features = [f for el in elements if (f := _element_to_feature(el))]
        features.sort(key=lambda f: f["properties"]["id"])
        return features
    return None
