"""
Feed catalogue for the paddies / reports ingest pipeline.

Each entry:
  id         — stable slug used in paddy_sources.feed_id
  name       — human display name
  forum_url  — forum landing page (used for the RSS URL and, later, for
               UI attribution links)
  rss_url    — the per-forum XenForo RSS feed
  enabled    — flip to False to skip a feed without deleting the entry
  kind       — which extractor reads its posts: "paddies" (extract.py: paddies,
               bites, conditions) or "boat_reports" (boat_reports.py: party-boat
               trip reports summarised per boat). Ingest treats both the same.
  initial_backfill_days — optional: on the feed's first run (nothing stored
               yet) walk its listing pages back this many days.

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
from typing import NotRequired, TypedDict


class Feed(TypedDict):
    id: str
    name: str
    forum_url: str
    rss_url: str
    enabled: bool
    kind: str
    initial_backfill_days: NotRequired[int]


FEEDS: list[Feed] = [
    {
        "id":        "bd-socal-offshore",
        "name":      "BD Southern California Offshore",
        "forum_url": "https://www.bdoutdoors.com/forums/forum/southern-california-offshore-fishing-reports/",
        "rss_url":   "https://www.bdoutdoors.com/forums/forum/southern-california-offshore-fishing-reports/index.rss",
        "enabled":   True,
        "kind":      "paddies",
    },
    {
        "id":        "bd-spearfishing",
        "name":      "BD Spearfishing Reports",
        "forum_url": "https://www.bdoutdoors.com/forums/forum/spear-fishing-reports/",
        "rss_url":   "https://www.bdoutdoors.com/forums/forum/spear-fishing-reports/index.rss",
        "enabled":   True,
        "kind":      "paddies",
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
        "kind":      "paddies",
    },
    {
        # Party-boat trip reports (SoCal landings, 1/2 day to 5 day). Almost
        # every thread names a boat in the title; ~25-35 threads/month in
        # season. Feeds the "From forum trip reports" panel on boat pages.
        "id":        "bd-socal-sportboats",
        "name":      "BD Southern California Sportboats",
        "forum_url": "https://www.bdoutdoors.com/forums/forum/southern-california-sportboats/",
        "rss_url":   "https://www.bdoutdoors.com/forums/forum/southern-california-sportboats/index.rss",
        "enabled":   True,
        "kind":      "boat_reports",
        "initial_backfill_days": 150,
    },
    {
        # San Diego long-range (5-16 day) trip reports plus gear/etiquette
        # chatter; the boat_reports classifier drops the non-reports.
        "id":        "bd-long-range",
        "name":      "BD Long Range Fishing",
        "forum_url": "https://www.bdoutdoors.com/forums/forum/san-diego-long-range-sportfishing-reports/",
        "rss_url":   "https://www.bdoutdoors.com/forums/forum/san-diego-long-range-sportfishing-reports/index.rss",
        "enabled":   True,
        "kind":      "boat_reports",
        "initial_backfill_days": 150,
    },
]


def enabled_feeds() -> list[Feed]:
    return [f for f in FEEDS if f["enabled"]]


def feed_ids(kind: str) -> list[str]:
    """All feed ids (enabled or not) whose posts go to the given extractor."""
    return [f["id"] for f in FEEDS if f.get("kind", "paddies") == kind]


def get_feed(feed_id: str) -> Feed | None:
    for f in FEEDS:
        if f["id"] == feed_id:
            return f
    return None
