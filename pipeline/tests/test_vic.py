from datetime import date

from goldpipe import config
from goldpipe.diff import diff_occurrences
from goldpipe.fetch_vic import _Grid, _number, merge, normalize
from goldpipe.grid import gold_grid


def _raw(num, lon, lat, kind="mineral deposit", ore="urn:ogc:def:nil:OGC::unknown"):
    return {
        "type": "Feature",
        "id": f"er.mineraloccurrence.{num}",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "earthResourceType": kind,
            "totalOreAmount": ore,
            "positionalAccuracy": "5 (http://www.opengis.net/def/uom/OGC/1.0/metre )",
        },
    }


def _oz(oid, lon, lat):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"id": oid, "name": "Oz", "occ_type": "mine", "commodity": "Gold",
                       "weight": 1.0},
    }


def test_numbers_parse_and_nils_are_dropped():
    assert _number("802395 (http://www.opengis.net/def/uom/UCUM/0/m3)") == 802395.0
    assert _number("urn:ogc:def:nil:OGC::unknown") is None
    assert _number("0") is None
    assert _number(None) is None


def test_normalize_labels_weights_and_names_nearby_shaft():
    shafts = _Grid()
    shafts.add(143.8501, -37.5501, "ORIENTAL")   # ~14 m away
    shafts.add(143.90, -37.60, "FAR AWAY")
    f = normalize(_raw(361023, 143.85, -37.55, ore="1200 (m3)"), shafts)
    p = f["properties"]
    assert p["id"] == "gsv.361023"
    assert p["name"] == "VIC gold deposit #361023"
    assert p["src"] == "gsv"
    assert p["weight"] == config.GSV_WEIGHT
    assert p["ore_m3"] == 1200
    assert p["acc_m"] == 5
    assert p["near_shaft"].startswith("Oriental (")


def test_normalize_occurrence_kind_and_rejects_bad_records():
    assert normalize(_raw(1, 143.0, -37.0, kind="occurrence"))["properties"]["occ_type"] == "occurrence"
    bad = _raw(2, 10.0, 50.0)  # outside Australia
    assert normalize(bad) is None
    no_geom = _raw(3, 143.0, -37.0)
    no_geom["geometry"] = None
    assert normalize(no_geom) is None


def test_merge_drops_vic_duplicates_of_national_records():
    national = [_oz("oz.1", 143.8500, -37.5500)]
    vic = [
        normalize(_raw(10, 143.8503, -37.5502)),  # ~35 m from oz.1: duplicate
        normalize(_raw(11, 143.8700, -37.5600)),  # ~2 km: kept
    ]
    ids = [f["properties"]["id"] for f in merge(national, vic)]
    assert ids == ["gsv.11", "oz.1"]


def test_grid_counts_vic_records_partially():
    feats = [_oz("oz.1", 143.85, -37.55), normalize(_raw(10, 143.86, -37.56))]
    cells = gold_grid(feats)
    occupied = [c for c in cells.values() if c["occupied"]]
    assert len(occupied) == 1
    assert abs(occupied[0]["count"] - (1 + config.GSV_WEIGHT)) < 1e-9


def test_new_source_is_baselined_not_announced_as_new_finds():
    today = date(2026, 11, 10)
    national = [_oz("oz.1", 143.85, -37.55)]
    # Existing state from before GSV joined: OZMIN baseline only.
    _, state = diff_occurrences(national, {"ids": {}, "community": {}}, today)
    vic = [normalize(_raw(n, 144.0 + n * 0.01, -37.0)) for n in range(5)]
    new, state = diff_occurrences(national + vic, state, today)
    assert new == [], "16k existing Victorian records must not become new finds"
    assert "gsv" in state["seeded_sources"]
    # A genuinely new Victorian record next day IS reported, as source gsv.
    later = vic + [normalize(_raw(99, 145.0, -37.0))]
    new, _ = diff_occurrences(national + later, state, date(2026, 11, 11))
    assert [r["properties"]["id"] for r in new] == ["gsv.99"]
    assert new[0]["properties"]["source"] == "gsv"


def test_old_state_without_seeded_sources_still_treats_ozmin_as_baselined():
    today = date(2026, 11, 10)
    state = {"ids": {"oz.1": {"hash": "x", "first_seen": "2026-08-01", "seeded": True}}}
    new, state = diff_occurrences([_oz("oz.1", 1.0, 1.0), _oz("oz.2", 2.0, 2.0)], state, today)
    assert [r["properties"]["id"] for r in new] == ["oz.2"]
