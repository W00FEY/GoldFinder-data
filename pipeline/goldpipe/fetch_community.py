"""Best-effort community gold-find reports from public Reddit JSON.

Entire module is fail-soft: any error returns None and the manifest marks the
section stale. Reddit intermittently 403s cloud IPs — expected.
"""
import re
from datetime import datetime, timezone

from . import config
from .http import get_json

_KEYWORDS = re.compile(config.COMMUNITY_KEYWORDS, re.I)
_AU_HINTS = re.compile(config.COMMUNITY_AU_HINTS, re.I)


def fetch_community_reports() -> list[dict] | None:
    try:
        data = get_json(config.REDDIT_URL, timeout=30)
        posts = data["data"]["children"]
    except Exception as e:  # noqa: BLE001 — fail-soft by design
        print(f"[community] reddit fetch failed: {e}")
        return None

    reports = []
    for p in posts:
        d = p.get("data", {})
        text = f"{d.get('title', '')} {d.get('selftext', '')[:500]}"
        if not _KEYWORDS.search(text) or not _AU_HINTS.search(text):
            continue
        url = f"https://www.reddit.com{d.get('permalink', '')}"
        posted = datetime.fromtimestamp(
            d.get("created_utc", 0), tz=timezone.utc
        ).replace(microsecond=0)
        reports.append(
            {
                "id": url,
                "title": d.get("title", "")[:200],
                "source": "reddit",
                "posted_at": posted.isoformat().replace("+00:00", "Z"),
                "url": url,
                "lat": None,
                "lon": None,
            }
        )
    return reports
