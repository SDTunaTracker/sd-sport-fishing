"""YouTube trip videos for boat pages, via the YouTube Data API v3. No scraping.

    YOUTUBE_API_KEY=... python -m src.youtube            # search + refresh + export
    python -m src.youtube --export-only                  # rewrite the JSON from the DB

Writes tracker.db tables `boat_videos` and `youtube_search_log`, and
web/api/v1/boat_videos.json, which web/boat-videos.jsx reads.

Quota (10,000 units/day free): search.list costs 100 units, so each run
searches at most MAX_SEARCHES boats (default 40 = 4,000 units), oldest-searched
first. Every boat gets searched about every 4–5 days. videos.list refresh
costs 1 unit per 50 ids.

YouTube API Services policy: we store only video ids plus basic metadata, refresh
them every run, and delete anything not confirmed within 30 days, or that is no
longer public or embeddable. Videos are shown only through the YouTube player.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
OUT = ROOT / "web" / "api" / "v1" / "boat_videos.json"
API = "https://www.googleapis.com/youtube/v3"
MAX_SEARCHES = int(os.environ.get("YOUTUBE_MAX_SEARCHES", "40"))
PER_BOAT = 6
STALE_DAYS = 30
LOOKBACK_YEARS = 2

FISH_WORDS = {
    "tuna", "bluefin", "yellowfin", "yellowtail", "dorado", "albacore", "wahoo", "fishing",
    "sportfishing", "rockfish", "lingcod", "halibut", "salmon", "seabass", "calico", "bass",
    "jig", "kite", "bait", "catch", "limits",
}
CONTEXT_WORDS = {
    "sportfishing", "sport fishing", "party boat", "long range", "landing", "san diego",
    "point loma", "seaforth", "fisherman's landing", "h&m", "1/2 day", "3/4 day", "full day",
    "overnight", "1.5 day", "2 day", "3 day", "offshore", "catalina", "coronado", "socal",
    "oceanside", "dana point", "newport", "long beach", "san pedro", "emeryville", "berkeley",
    "half moon bay", "bodega", "monterey", "sausalito",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS boat_videos (
    video_id      TEXT PRIMARY KEY,
    boat          TEXT NOT NULL,
    title         TEXT NOT NULL,
    channel_title TEXT,
    published_at  TEXT,
    fetched_at    TEXT NOT NULL,
    refreshed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_boat_videos_boat ON boat_videos(boat);
CREATE TABLE IF NOT EXISTS youtube_search_log (
    boat        TEXT PRIMARY KEY,
    searched_at TEXT NOT NULL,
    n_found     INTEGER NOT NULL DEFAULT 0
);
"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9&/.' ]+", " ", (s or "").lower())).strip()


def is_match(boat: str, title: str, description: str = "", landing: str = "") -> bool:
    """True when a video is plausibly a trip on this boat.

    It needs the boat name as whole words in the title, a fishing word, and a
    party-boat context word (port, landing, trip type). This keeps out
    common-word names like "Liberty" or "Dolphin" that aren't about fishing.
    """
    t, d, b = _norm(title), _norm(description), _norm(boat)
    if not b or not re.search(rf"(?<![a-z0-9]){re.escape(b)}(?![a-z0-9])", t):
        return False
    text = f"{t} {d}"
    words = set(text.split())
    if not words & FISH_WORDS:
        return False
    ctx = set(CONTEXT_WORDS)
    if landing:
        ctx.add(_norm(landing))
    return any(c in text for c in ctx)


def _get(path: str, key: str, **params) -> dict:
    r = requests.get(f"{API}/{path}", params={**params, "key": key}, timeout=20)
    r.raise_for_status()
    return r.json()


def search_boat(key: str, boat: str, landing: str) -> list[dict]:
    after = (datetime.now(timezone.utc) - timedelta(days=365 * LOOKBACK_YEARS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    j = _get("search", key, part="snippet", q=f'"{boat}" sportfishing', type="video",
             maxResults=15, order="relevance", publishedAfter=after, regionCode="US",
             relevanceLanguage="en", safeSearch="strict", videoEmbeddable="true")
    out = []
    for it in j.get("items", []):
        sn = it.get("snippet", {})
        vid = it.get("id", {}).get("videoId")
        if vid and is_match(boat, sn.get("title", ""), sn.get("description", ""), landing):
            out.append({"video_id": vid, "title": sn.get("title", ""),
                        "channel_title": sn.get("channelTitle", ""), "published_at": sn.get("publishedAt")})
    return out


def refresh(conn: sqlite3.Connection, key: str) -> tuple[int, int]:
    """Re-confirm stored videos (1 unit per 50 ids); drop gone, private or non-embeddable ones."""
    now = datetime.now(timezone.utc).isoformat()
    ids = [r[0] for r in conn.execute("SELECT video_id FROM boat_videos")]
    kept = dropped = 0
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        j = _get("videos", key, part="snippet,status", id=",".join(chunk), maxResults=50)
        ok = {}
        for it in j.get("items", []):
            st = it.get("status", {})
            if st.get("privacyStatus") == "public" and st.get("embeddable", False):
                ok[it["id"]] = it.get("snippet", {})
        for vid in chunk:
            if vid in ok:
                sn = ok[vid]
                conn.execute("UPDATE boat_videos SET title=?, channel_title=?, refreshed_at=? WHERE video_id=?",
                             (sn.get("title", ""), sn.get("channelTitle", ""), now, vid))
                kept += 1
            else:
                conn.execute("DELETE FROM boat_videos WHERE video_id=?", (vid,))
                dropped += 1
    return kept, dropped


def purge_stale(conn: sqlite3.Connection) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)).isoformat()
    return conn.execute("DELETE FROM boat_videos WHERE refreshed_at < ?", (cutoff,)).rowcount


def boats_to_search(conn: sqlite3.Connection, limit: int) -> list[tuple[str, str]]:
    since = (datetime.now(timezone.utc) - timedelta(days=365)).date().isoformat()
    return conn.execute(
        """SELECT t.boat, MAX(t.landing) FROM trips t
           LEFT JOIN youtube_search_log l ON l.boat = t.boat
           WHERE t.date >= ?
           GROUP BY t.boat
           ORDER BY COALESCE(MAX(l.searched_at), '') ASC, COUNT(*) DESC
           LIMIT ?""", (since, limit)).fetchall()


def export_json(conn: sqlite3.Connection, out: Path = OUT) -> int:
    boats: dict[str, list] = {}
    for boat, vid, title, ch, pub in conn.execute(
            "SELECT boat, video_id, title, channel_title, published_at FROM boat_videos "
            "ORDER BY boat, published_at DESC"):
        lst = boats.setdefault(boat, [])
        if len(lst) < PER_BOAT:
            lst.append({"id": vid, "title": title, "channel": ch, "published": (pub or "")[:10]})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "source": "YouTube Data API v3", "boats": boats},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return sum(len(v) for v in boats.values())


def run(db_path: Path = DB_PATH, export_only: bool = False) -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "")
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    try:
        if export_only or not key:
            n = export_json(conn)
            return f"YouTube: {'no YOUTUBE_API_KEY, ' if not key and not export_only else ''}exported {n} videos"
        kept, dropped = refresh(conn, key)
        stale = purge_stale(conn)
        now = datetime.now(timezone.utc).isoformat()
        added = searched = 0
        for boat, landing in boats_to_search(conn, MAX_SEARCHES):
            try:
                found = search_boat(key, boat, landing or "")
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 403:
                    log.warning("YouTube quota or key error; stopping searches: %s", e)
                    break
                raise
            searched += 1
            for v in found:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO boat_videos VALUES (?,?,?,?,?,?,?)",
                    (v["video_id"], boat, v["title"], v["channel_title"], v["published_at"], now, now))
                added += cur.rowcount
            conn.execute("INSERT OR REPLACE INTO youtube_search_log VALUES (?,?,?)", (boat, now, len(found)))
        conn.commit()
        n = export_json(conn)
        return (f"YouTube: searched {searched} boats, +{added} videos, refreshed {kept}, "
                f"dropped {dropped + stale}, exported {n}")
    finally:
        conn.commit()
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--export-only", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(run(export_only=a.export_only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
