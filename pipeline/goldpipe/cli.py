"""Pipeline orchestrator.

Usage:
    python -m goldpipe.cli all --out out/v1 --state state
    python -m goldpipe.cli ozmin            # just fetch + print count
    python -m goldpipe.cli tenements        # just the registry health check
"""
import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import config
from .diff import diff_community, diff_occurrences, load_state, save_state
from .fetch_camps import fetch_camp_sites
from .fetch_community import fetch_community_reports
from .fetch_news import fetch_news_reports
from .fetch_towers import fetch_tower_sites
from .fetch_youtube import fetch_youtube_reports
from .fetch_ozmin import fetch_gold_occurrences
from .fetch_rainfall import fetch_rainfall
from .goldshift import compute_goldshift, rainfall_features
from .grid import gold_grid
from .land import build_land_sources
from .waterways import build_track_sources, build_waterway_sources
from .publish import Publisher, geojson
from .tenements import build_tenement_sources


def run_all(out_dir: Path, state_dir: Path) -> int:
    today = date.today()
    pub = Publisher(out_dir)
    state = load_state(state_dir)

    # --- Gold occurrences (the backbone; hard-fail only if we have no previous data)
    occurrences = None
    try:
        occurrences = fetch_gold_occurrences()
        print(f"[ozmin] {len(occurrences)} gold occurrences")
    except Exception as e:  # noqa: BLE001
        print(f"[ozmin] FAILED: {e}")

    new_reports: list[dict] = []
    if occurrences is not None:
        new_reports, state = diff_occurrences(occurrences, state, today)
        pub.section(
            "gold_occurrences", "gold_occurrences.geojson",
            geojson(occurrences), len(occurrences),
        )
    else:
        pub.section("gold_occurrences", "gold_occurrences.geojson", None, None)

    # --- Community: gold news RSS + AU prospecting YouTube channels (and
    # reddit if it ever becomes reachable again — currently exception-only).
    reddit = fetch_community_reports()
    news = fetch_news_reports()
    youtube = fetch_youtube_reports()
    community = None
    if reddit is not None or news is not None or youtube is not None:
        community = (reddit or []) + (news or []) + (youtube or [])
    if community is not None:
        community, state = diff_community(community, state, today)
        print(f"[community] {len(community)} reports")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        pub.section(
            "community_reports", "community_reports.json",
            {
                "schema_version": config.SCHEMA_VERSION,
                "updated_at": now.isoformat().replace("+00:00", "Z"),
                "reports": community,
            },
            len(community),
        )
        for r in community:
            if r.get("lat") is not None and r.get("lon") is not None:
                new_reports.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                        "properties": {
                            "id": r["id"],
                            "source": "community",
                            "title": r["title"],
                            "detail": None,
                            "first_seen": r["first_seen"],
                            "url": r["url"],
                        },
                    }
                )
    else:
        pub.section("community_reports", "community_reports.json", None, None)

    pub.section("new_reports", "new_reports.geojson", geojson(new_reports), len(new_reports))

    # --- Rainfall + goldshift (need occurrences for the grid)
    if occurrences is not None:
        grid = gold_grid(occurrences)
        print(f"[grid] {len(grid)} cells")
        rainfall, source = fetch_rainfall(grid)
        if rainfall is not None:
            print(f"[rainfall] {len(rainfall)} cells via {source}")
            rf = rainfall_features(grid, rainfall)
            pub.section("rainfall", "rainfall_grid.geojson", geojson(rf), len(rf))
            shift = compute_goldshift(grid, rainfall)
            print(f"[goldshift] {len(shift)} hotspot cells")
            pub.section("goldshift", "goldshift.geojson", geojson(shift), len(shift))
        else:
            pub.section("rainfall", "rainfall_grid.geojson", None, None)
            pub.section("goldshift", "goldshift.geojson", None, None)
    else:
        pub.section("rainfall", "rainfall_grid.geojson", None, None)
        pub.section("goldshift", "goldshift.geojson", None, None)

    # --- Campgrounds (fail-soft; OSM data changes slowly so stale is fine)
    camps = fetch_camp_sites()
    if camps is not None:
        print(f"[camps] {len(camps)} camp sites")
        pub.section("camp_sites", "camp_sites.geojson", geojson(camps), len(camps))
    else:
        pub.section("camp_sites", "camp_sites.geojson", None, None)

    # --- Mobile tower sites (ACMA RRL, fail-soft; ~70MB download)
    towers = fetch_tower_sites()
    if towers is not None:
        print(f"[towers] {len(towers)} mobile tower sites")
        pub.section("towers", "towers.geojson", geojson(towers), len(towers))
    else:
        pub.section("towers", "towers.geojson", None, None)

    # --- Tenement registry health check
    sources = build_tenement_sources()
    ok = sum(1 for s in sources["sources"].values() if s["status"] == "ok")
    print(f"[tenements] {ok}/{len(sources['sources'])} state services healthy")
    pub.section("tenement_sources", "tenement_sources.json", sources, len(sources["sources"]))

    # --- Public land (parks/forests) registry health check
    land = build_land_sources()
    ok = sum(1 for s in land["sources"].values() if s["status"] == "ok")
    print(f"[land] {ok}/{len(land['sources'])} land services healthy")
    pub.section("land_sources", "land_sources.json", land, len(land["sources"]))

    # --- Waterway + track registries health check
    water = build_waterway_sources()
    pub.section("waterway_sources", "waterway_sources.json", water, len(water["sources"]))
    tracks = build_track_sources()
    pub.section("track_sources", "track_sources.json", tracks, len(tracks["sources"]))
    print(f"[waterways] water={list(water['sources'].values())[0]['status']} "
          f"tracks={list(tracks['sources'].values())[0]['status']}")

    manifest = pub.finish(new_reports, today)
    save_state(state_dir, state)
    print(f"[publish] manifest generated_at={manifest['generated_at']} "
          f"new_report_count={manifest['new_report_count']}")
    # Fail the run (for CI visibility) only if the backbone fetch failed AND
    # there was no previous data to fall back to.
    if occurrences is None and manifest["sections"]["gold_occurrences"]["count"] == 0:
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="goldpipe")
    ap.add_argument("command", choices=["all", "ozmin", "tenements", "community"])
    ap.add_argument("--out", default="out/v1")
    ap.add_argument("--state", default="state")
    args = ap.parse_args(argv)

    if args.command == "all":
        return run_all(Path(args.out), Path(args.state))
    if args.command == "ozmin":
        feats = fetch_gold_occurrences()
        alluvial = sum(1 for f in feats if f["properties"]["alluvial"])
        print(f"{len(feats)} gold occurrences ({alluvial} alluvial-tagged)")
        return 0
    if args.command == "tenements":
        sources = build_tenement_sources()
        for st, s in sources["sources"].items():
            print(f"{st}: {s['status']}  {s['query_templates'][0][:100]}")
        return 0
    if args.command == "community":
        reports = fetch_community_reports()
        print(f"{len(reports) if reports is not None else 'FAILED'} reports")
        for r in reports or []:
            print(f"  {r['posted_at']}  {r['title']}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
