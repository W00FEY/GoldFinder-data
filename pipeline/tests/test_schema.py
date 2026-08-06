"""Validate a published out/v1 tree against the v1 contract.

Runs against pipeline/out/v1 when present (after a real run) and always
against a synthetic minimal publish.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from goldpipe.publish import Publisher, geojson

OUT = Path(__file__).resolve().parent.parent / "out" / "v1"

REQUIRED_SECTIONS = {
    "gold_occurrences", "new_reports", "rainfall", "goldshift",
    "community_reports", "tenement_sources", "camp_sites", "land_sources",
    "waterway_sources", "track_sources", "towers", "fossicking_sources",
}


def _check_manifest(manifest: dict):
    assert manifest["schema_version"] == 1
    assert "generated_at" in manifest
    assert isinstance(manifest["new_report_count"], int)
    assert REQUIRED_SECTIONS <= set(manifest["sections"])
    for s in manifest["sections"].values():
        assert s["status"] in ("ok", "stale", "empty")
        assert isinstance(s["count"], int)


def test_synthetic_publish_matches_contract(tmp_path):
    pub = Publisher(tmp_path)
    pub.section("gold_occurrences", "gold_occurrences.geojson", geojson([]), 0)
    pub.section("new_reports", "new_reports.geojson", geojson([]), 0)
    pub.section("rainfall", "rainfall_grid.geojson", None, None)  # stale path
    pub.section("goldshift", "goldshift.geojson", None, None)
    pub.section("community_reports", "community_reports.json",
                {"schema_version": 1, "updated_at": "x", "reports": []}, 0)
    pub.section("tenement_sources", "tenement_sources.json",
                {"schema_version": 1, "updated_at": "x", "sources": {}}, 0)
    pub.section("camp_sites", "camp_sites.geojson", geojson([]), 0)
    pub.section("land_sources", "land_sources.json",
                {"schema_version": 1, "updated_at": "x", "sources": {}}, 0)
    pub.section("waterway_sources", "waterway_sources.json",
                {"schema_version": 1, "updated_at": "x", "sources": {}}, 0)
    pub.section("track_sources", "track_sources.json",
                {"schema_version": 1, "updated_at": "x", "sources": {}}, 0)
    pub.section("towers", "towers.geojson", geojson([]), 0)
    pub.section("fossicking_sources", "fossicking_sources.json",
                {"schema_version": 1, "updated_at": "x", "sources": {}}, 0)
    manifest = pub.finish([], date(2026, 8, 5))
    _check_manifest(manifest)
    assert manifest["sections"]["rainfall"]["status"] == "stale"
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == manifest


@pytest.mark.skipif(not (OUT / "manifest.json").exists(), reason="no real run yet")
def test_real_output_matches_contract():
    manifest = json.loads((OUT / "manifest.json").read_text())
    _check_manifest(manifest)
    for name, s in manifest["sections"].items():
        f = OUT / s["file"]
        if s["status"] == "stale" and s["count"] == 0 and not f.exists():
            continue  # section has never succeeded; no file to validate
        assert f.exists(), f"{name} file missing"
        body = json.loads(f.read_text())
        if s["file"].endswith(".geojson"):
            assert body["type"] == "FeatureCollection"
            assert body["goldfinder"]["schema_version"] == 1
            if s["status"] == "ok":
                assert len(body["features"]) == s["count"]
        else:
            assert body["schema_version"] == 1

    occ = json.loads((OUT / "gold_occurrences.geojson").read_text())
    for f in occ["features"][:50]:
        p = f["properties"]
        assert p["id"] and p["name"]
        assert isinstance(p["alluvial"], bool)
        assert 0 < p["weight"] <= 1.0
        lon, lat = f["geometry"]["coordinates"]
        assert 112.0 <= lon <= 154.5 and -44.0 <= lat <= -9.0
