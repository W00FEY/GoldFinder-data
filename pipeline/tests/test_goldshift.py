from goldpipe.goldshift import compute_goldshift, rain_factor
from goldpipe.grid import cell_key, gold_grid


def _occ(lon, lat, alluvial=True, name="Test Diggings"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"alluvial": alluvial, "name": name, "weight": 1.0},
    }


def _flat_rain(grid, r7=0.0, rmax24=0.0):
    return {
        cell_key(cx, cy): {"r7": r7, "r14": r7, "rmax24": rmax24}
        for cx, cy in grid
    }


def test_rain_factor_saturates():
    assert rain_factor(0, 0) == 0.0
    assert rain_factor(60, 30) == 1.0
    assert rain_factor(600, 300) == 1.0
    assert 0 < rain_factor(30, 0) < 0.5


def test_no_rain_no_signal():
    grid = gold_grid([_occ(143.7, -36.9) for _ in range(20)])
    assert compute_goldshift(grid, _flat_rain(grid)) == []


def test_heavy_rain_over_alluvial_cluster_scores():
    grid = gold_grid([_occ(143.7 + i * 0.01, -36.9) for i in range(20)])
    shift = compute_goldshift(grid, _flat_rain(grid, r7=80.0, rmax24=40.0))
    assert shift, "expected hotspot cells"
    top = shift[0]["properties"]
    assert top["score"] > 50
    assert top["r"] == 1.0
    assert top["w"] == 0.5  # neutral in v1
    assert top["label"] == "Test Diggings"


def test_non_alluvial_region_scores_lower():
    # Same-size clusters in one dataset: alluvial country must outscore
    # non-alluvial (which contributes at 0.3 weight).
    occs = [_occ(143.7, -36.9, alluvial=True) for _ in range(10)] + [
        _occ(120.7, -30.9, alluvial=False, name="Hard Rock") for _ in range(10)
    ]
    grid = gold_grid(occs)
    shift = compute_goldshift(grid, _flat_rain(grid, r7=80.0, rmax24=40.0))
    by_label = {}
    for f in shift:
        label = f["properties"]["label"]
        by_label[label] = max(by_label.get(label, 0), f["properties"]["score"])
    assert by_label["Test Diggings"] > by_label["Hard Rock"]


def test_buffer_cells_do_not_outscore_occupied():
    grid = gold_grid([_occ(143.7, -36.9) for _ in range(10)])
    shift = compute_goldshift(grid, _flat_rain(grid, r7=100.0, rmax24=50.0))
    scores = {f["properties"]["cell"]: f["properties"]["score"] for f in shift}
    occupied_key = max(scores, key=scores.get)
    assert grid[tuple(map(int, occupied_key.split("_")))]["occupied"]
