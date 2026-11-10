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
        src_el = item.find("source")
        publisher = (src_el.text or "").strip() if src_el is not None else ""
        domain = (src_el.get("url") or "") if src_el is not None else ""
        # Google appends " - Publisher" to every headline; keep it separate.
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        hit = locate(title)
        reports.append(
            {
                "id": link,
                "title": title[:200],
                "publisher": publisher or None,
                "australian": ".au" in domain.split("//")[-1].split("/")[0],
                "place": hit[2] if hit else None,
                "source": "news",
                "posted_at": posted.astimezone(timezone.utc)
                .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "url": link,
                "lat": None,
                "lon": None,
            }
        )
    return dedupe_stories(reports)


_WORD = re.compile(r"[a-z0-9$]+")
_STOP = {"the", "a", "an", "in", "of", "to", "and", "for", "on", "after", "with",
         "his", "her", "at", "is", "as", "by", "from", "gold", "australian",
         "australia", "man", "prospector", "finds", "found", "nugget"}


def _key_words(title: str) -> set[str]:
    return {w for w in _WORD.findall(title.lower()) if w not in _STOP and len(w) > 2}


def dedupe_stories(reports: list[dict]) -> list[dict]:
    """The same find is re-reported by dozens of overseas outlets. Keep one
    article per story, preferring an Australian publisher, then the earliest."""
    ranked = sorted(reports, key=lambda r: (not r.get("australian"), r["posted_at"]))
    kept: list[tuple[set[str], dict]] = []
    for r in ranked:
        words = _key_words(r["title"])
        dup = False
        for other, _ in kept:
            union = words | other
            if union and len(words & other) / len(union) >= 0.5:
                dup = True
                break
        if not dup:
            kept.append((words, r))
    out = [r for _, r in kept]
    out.sort(key=lambda r: r["posted_at"], reverse=True)
    return out
