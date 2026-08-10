from datetime import date

from goldpipe.fetch_news import _AU, _NOISE, _RELEVANT, locate
from goldpipe.publish import Publisher, geojson


def _kept(title: str) -> bool:
    return bool(
        _RELEVANT.search(title)
        and not _NOISE.search(title)
        and (locate(title) or _AU.search(title))
    )


def test_clickbait_rejected():
    assert not _kept("Largest gold nugget ever found weighed as much as a man")
    assert not _kept("The biggest gold nuggets ever discovered | listicle.com")
    assert not _kept("Top 10 gold nuggets of all time")
    assert not _kept("Gold nugget found — here's how much it's worth")


def test_australian_finds_kept():
    assert _kept("Australian found over 4kg gold nugget in abandoned mines")
    assert _kept("Prospector unearths nugget near Dunolly")
    assert _kept("Metal detector find stuns Kalgoorlie prospectors")


def test_foreign_finds_rejected():
    assert not _kept("Prospector finds gold nugget in California river")
    assert not _kept("Alaska gold rush: miner finds 3oz nugget")


def _report(source: str, first_seen: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [143.0, -36.0]},
        "properties": {"id": source + first_seen, "source": source,
                       "title": "x", "first_seen": first_seen},
    }


def test_news_excluded_from_notify_count(tmp_path):
    pub = Publisher(tmp_path)
    today = date(2026, 8, 7)
    reports = [
        _report("news", "2026-08-06"),
        _report("news", "2026-08-05"),
        _report("youtube", "2026-08-06"),
        _report("ozmin", "2026-08-04"),
        _report("youtube", "2026-01-01"),  # outside 14-day window
    ]
    pub.section("new_reports", "new_reports.geojson", geojson(reports), len(reports))
    manifest = pub.finish(reports, today)
    assert manifest["new_report_count"] == 2  # youtube + ozmin only
