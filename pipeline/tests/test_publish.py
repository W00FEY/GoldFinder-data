from goldpipe.publish import geojson


def test_geojson_strips_null_properties():
    fc = geojson(
        [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [143.0, -36.0]},
                "properties": {
                    "id": "x", "name": "Spot", "deposit_model": None,
                    "url": None, "alluvial": False, "weight": 0.6,
                },
            }
        ]
    )
    props = fc["features"][0]["properties"]
    assert "deposit_model" not in props
    assert "url" not in props
    assert props["alluvial"] is False  # falsy-but-not-None values survive
    assert props["weight"] == 0.6


def test_geojson_walks_all_features():
    fc = geojson(
        [
            {"type": "Feature", "geometry": None, "properties": {"a": None}},
            {"type": "Feature", "geometry": None, "properties": {"b": 1, "c": None}},
        ]
    )
    for f in fc["features"]:
        assert None not in f["properties"].values()
