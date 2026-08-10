"""Australian gold-prospecting news via Google News RSS (keyless, and unlike
Reddit it doesn't block cloud servers). Fail-soft like every fetcher."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import config
from .gazetteer import locate
from .http import SESSION

NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q=%22gold+nugget%22+OR+%22gold+prospecting%22+OR+%22gold+detecting%22+"
    "OR+%22gold+panning%22+australia&hl=en-AU&gl=AU&ceid=AU:en"
)

_RELEVANT = re.compile(
    r"nugget|prospect|detect|panning|goldfield|alluvial|fossick|found gold|"
    r"gold rush|metal detector",
    re.I,
)
_NOISE = re.compile(
    r"asx|share price|stock|dividend|takeover|merger|marketing licen|"
    r"quarterly report|drill result|"
    # Clickbait/listicle patterns (were triggering user notifications).
    r"largest .{0,20}ever|biggest .{0,20}ever|weighed as much|"
    r"here'?s how much|of all time|in history|top \d+|"
    r"most expensive|most valuable|you won'?t believe",
    re.I,
)
_AU = re.compile(config.COMMUNITY_AU_HINTS, re.I)
MAX_AGE_DAYS = 90


def fetch_news_reports() -> list[dict] | None:
    try:
        r = SESSION.get(NEWS_RSS, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception as e:  # noqa: BLE001 — fail-soft by design
        print(f"[news] google news fetch failed: {e}")
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    reports = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        if not _RELEVANT.search(title) or _NOISE.search(title):
            continue
        # Must be verifiably Australian: a goldfield locality or an AU term
        # in the title (global listicles were polluting the feed).
        if not (locate(title) or _AU.search(title)):
            continue
        try:
            posted = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if posted < cutoff:
            continue
        reports.append(
            {
                "id": link,
                "title": title[:200],
                "source": "news",
                "posted_at": posted.astimezone(timezone.utc)
                .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "url": link,
                "lat": None,
                "lon": None,
            }
        )
    reports.sort(key=lambda r: r["posted_at"], reverse=True)
    return reports
