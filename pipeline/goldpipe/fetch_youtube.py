"""New videos from Australian gold prospecting YouTube channels, via each
channel's official keyless RSS feed (youtube.com/feeds/videos.xml).

Per-channel failures are tolerated; the module only fails (returns None) if
every channel fails. Prospecting Australia forum was evaluated as a source
but blocks non-browser clients outright (Cloudflare 403), so YouTube + news
carry the community section.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from . import config
from .gazetteer import locate
from .http import SESSION

_ATOM = "{http://www.w3.org/2005/Atom}"
MAX_AGE_DAYS = 90

# Video titles that suggest an actual find/session rather than gear reviews.
_RELEVANT = re.compile(
    r"gold|nugget|detect|prospect|panning|paydirt|sluic|crevic|digging|"
    r"found|patch|reef|goldfield|alluvial|fossick",
    re.I,
)


def _fetch_channel(name: str, channel_id: str, cutoff: datetime) -> list[dict]:
    r = SESSION.get(
        "https://www.youtube.com/feeds/videos.xml",
        params={"channel_id": channel_id},
        timeout=30,
    )
    r.raise_for_status()
    root = ET.fromstring(r.text)
    reports = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        link_el = entry.find(f"{_ATOM}link")
        url = link_el.get("href") if link_el is not None else None
        published_raw = entry.findtext(f"{_ATOM}published") or ""
        if not title or not url:
            continue
        if not _RELEVANT.search(title):
            continue
        try:
            published = datetime.fromisoformat(published_raw)
        except ValueError:
            continue
        if published < cutoff:
            continue
        # Title place-name wins; otherwise pin to the channel's usual region.
        hit = locate(title)
        if hit:
            lon, lat, place = round(hit[0], 3), round(hit[1], 3), hit[2]
        else:
            home = config.YOUTUBE_CHANNEL_HOMES.get(name)
            lon, lat, place = (home[0], home[1], home[2]) if home else (None, None, None)
        reports.append(
            {
                "id": url,
                "title": f"{title} — {name}"[:200],
                "source": "youtube",
                "posted_at": published.astimezone(timezone.utc)
                .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "url": url,
                "lat": lat,
                "lon": lon,
                "place": place,
                "approx": lat is not None,
            }
        )
    return reports


def fetch_youtube_reports() -> list[dict] | None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    reports: list[dict] = []
    ok = 0
    for name, channel_id in config.YOUTUBE_CHANNELS.items():
        try:
            found = _fetch_channel(name, channel_id, cutoff)
            reports.extend(found)
            ok += 1
        except Exception as e:  # noqa: BLE001 — per-channel fail-soft
            print(f"[youtube] {name} failed: {e}")
    if ok == 0:
        return None
    reports.sort(key=lambda r: r["posted_at"], reverse=True)
    return reports
