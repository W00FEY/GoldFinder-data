"""Best-effort community gold-find reports from Reddit.

Uses Reddit's OFFICIAL OAuth API when REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET
env vars are set (register a free "script" app at reddit.com/prefs/apps and
add both as repo secrets) — this is the sanctioned way to read Reddit from a
server. Without credentials it falls back to the public JSON endpoint, which
Reddit blocks from most cloud IPs, so expect stale.

Entire module is fail-soft: any error returns None and the manifest marks the
section stale.
"""
import os
import re
from datetime import datetime, timezone

from . import config
from .http import SESSION, get_json

_KEYWORDS = re.compile(config.COMMUNITY_KEYWORDS, re.I)
_AU_HINTS = re.compile(config.COMMUNITY_AU_HINTS, re.I)

_SUBREDDITS = "Goldpanning+GoldProspecting+metaldetecting"


def _fetch_posts_oauth(client_id: str, client_secret: str) -> list[dict]:
    token_resp = SESSION.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    token_resp.raise_for_status()
    token = token_resp.json()["access_token"]
    r = SESSION.get(
        f"https://oauth.reddit.com/r/{_SUBREDDITS}/new",
        params={"limit": 100},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["data"]["children"]


def fetch_community_reports() -> list[dict] | None:
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    try:
        if client_id and client_secret:
            posts = _fetch_posts_oauth(client_id, client_secret)
            print(f"[community] reddit oauth: {len(posts)} posts")
        else:
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
