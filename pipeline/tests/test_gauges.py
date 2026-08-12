from goldpipe.fetch_gauges import _feature, _flow_category, _near_gold
from goldpipe.grid import gold_grid


def _occ(lon, lat):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"alluvial": False, "name": "x"},
    }


def test_flow_categories():
    assert _flow_category(0.0) == "dry"
    assert _flow_category(0.1) == "low"
    assert _flow_category(5.0) == "medium"
    assert _flow_category(50.0) == "high"


def test_near_gold_uses_buffered_grid():
    cells = gold_grid([_occ(143.85, -37.55)])  # Ballarat-ish
    assert _near_gold(143.85, -37.55, cells)
    assert _near_gold(144.1, -37.6, cells)   # neighbouring cell
    assert not _near_gold(150.0, -30.0, cells)


def test_feature_shape_and_units():
    f = _feature("VIC", "405232", "Goulburn @ McCoys Bridge", 145.1, -36.2,
                 152.927, "2026-08-12T22:00")
    p = f["properties"]
    assert p["id"] == "VIC:405232"
    assert p["cat"] == "high"
    assert abs(p["flow_mld"] - 152.927 * 86.4) < 0.1
    assert f["geometry"]["coordinates"] == [145.1, -36.2]
