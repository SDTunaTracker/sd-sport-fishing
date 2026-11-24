"""
Feed catalogue for the paddies / reports ingest pipeline.

Each entry:
  id         — stable slug used in paddy_sources.feed_id
  name       — human display name
  forum_url  — forum landing page (used for the RSS URL and, later, for
               UI attribution links)
  rss_url    — the per-forum XenForo RSS feed
  enabled    — flip to False to skip a feed without deleting the entry

The order here is intentional: SoCal Offshore stays entry 1 (that's the
existing v1 feed and its rows are already migrated). New feeds are
appended in the order they were added.

Phase 0 access probe (2026-09-06) verified all three feeds:
  * status 200, application/rss+xml, 25 items
  * mixture of full-body and "Read more"-truncated items (thread-page
    fetch already handles truncation via the v1 code path)
  * thread pages return 200 with no Cloudflare / login walls
  * robots.txt has no disallow on any of these forum paths
"""
from __future__ import annotations
from typing import TypedDict


class Feed(TypedDict):
    id: str
    name: str
    forum_url: str
    rss_url: str
    enabled: bool


FEEDS: list[Feed] = [
    {
        "id":        "bd-socal-offshore",
        "name":      "BD Southern California Offshore",
        "forum_url": "https://www.bdoutdoors.com/forums/forum/southern-california-offshore-fishing-reports/",
        "rss_url":   "https://www.bdoutdoors.com/forums/forum/southern-california-offshore-fishing-reports/index.rss",
        "enabled":   True,
    },
    {
        "id":        "bd-spearfishing",
        "name":      "BD Spearfishing Reports",
        "forum_url": "https://www.bdoutdoors.com/forums/forum/spear-fishing-reports/",
        "rss_url":   "https://www.bdoutdoors.com/forums/forum/spear-fishing-reports/index.rss",
        "enabled":   True,
    },
    {
        # Baja subforum covers the west-coast Baja peninsula reports (Cedros,
        # San Quintin, Ensenada, WSB grounds) that SoCal boats actually run
        # to. The parent "Mexico Fishing Reports" forum ALSO aggregates
        # Mainland (Cabo / East Cape / mainland Sea of Cortez) which is a
        # different fishery. Add mainland separately later if you want it.
        "id":        "bd-baja",
        "name":      "BD Baja Mexico Fishing Reports",
        "forum_url": "https://www.bdoutdoors.com/forums/forum/baja-mexico-fishing-reports-discussion/",
        "rss_url":   "https://www.bdoutdoors.com/forums/forum/baja-mexico-fishing-reports-discussion/index.rss",
        "enabled":   True,
    },
]


def enabled_feeds() -> list[Feed]:
    return [f for f in FEEDS if f["enabled"]]


def get_feed(feed_id: str) -> Feed | None:
    for f in FEEDS:
        if f["id"] == feed_id:
            return f
    return None
