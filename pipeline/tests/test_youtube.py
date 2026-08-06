from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from goldpipe import fetch_youtube

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <title>Test Prospecting</title>
 <entry>
  <title>Found a 5 gram nugget in the Golden Triangle!</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
  <published>{recent}</published>
 </entry>
 <entry>
  <title>My camera gear tour</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=def456"/>
  <published>{recent}</published>
 </entry>
 <entry>
  <title>Detecting old gold diggings</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=old111"/>
  <published>{old}</published>
 </entry>
</feed>
"""


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_channel_parse_filters_and_windows():
    now = datetime.now(timezone.utc)
    xml = FIXTURE.format(
        recent=(now - timedelta(days=3)).isoformat(),
        old=(now - timedelta(days=200)).isoformat(),
    )
    cutoff = now - timedelta(days=90)
    with patch.object(fetch_youtube.SESSION, "get", return_value=_Resp(xml)):
        reports = fetch_youtube._fetch_channel("Test", "UCx", cutoff)
    # nugget video kept; gear tour filtered (no keywords); old video windowed out
    assert len(reports) == 1
    r = reports[0]
    assert r["source"] == "youtube"
    assert "nugget" in r["title"].lower()
    assert "Test" in r["title"]
    assert r["url"] == "https://www.youtube.com/watch?v=abc123"
