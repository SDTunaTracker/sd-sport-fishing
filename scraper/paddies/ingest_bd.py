"""
Ingest new posts from the BloodyDecks forums (feeds.py lists which). Each
run reads every enabled forum RSS feed and upserts the items into the
`paddy_sources` table in data/paddies.db.

- Idempotent: PK is sha1(canonical_url); re-running never duplicates.
- Feed fetches retry transient errors (network, 5xx, 429) with backoff.
- RSS bodies are ~500-char excerpts ending "Read more"; repair_truncated()
  replaces them with the OP body from the thread page (capped, rate-limited).
- Gap recovery: if a feed's ~25-item window no longer overlaps what we have
  stored (we were down for days), the forum listing pages are walked back to
  our newest stored post. `--backfill-since` forces that walk from a date.
- Health state for alerting is written to data/paddies_ingest_state.json.

Usage:
    .venv/Scripts/python.exe -m scraper.paddies.ingest_bd
    .venv/Scripts/python.exe -m scraper.paddies.ingest_bd --backfill-since 2026-09-06
"""
from __future__ import annotations

import hashlib
import html as html_module
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from . import feeds as feeds_mod

ROOT = Path(__file__).resolve().parents[2]
# Paddy data lives in its own SQLite file, NOT tracker.db. tracker.db is a
# 45 MB binary the hourly landing scrape commits; a second workflow pushing
# the same binary loses every rebase race. A dedicated file means the
# paddies workflow and the scrape workflow never touch the same paths.
DB_PATH = Path(os.environ.get("PADDIES_DB") or (ROOT / "data" / "paddies.db"))
STATE_PATH = ROOT / "data" / "paddies_ingest_state.json"

FEED_URL = (
    "https://www.bdoutdoors.com/forums/forum/"
    "southern-california-offshore-fishing-reports/index.rss"
)
PRIMARY_FEED_ID = "bd-socal-offshore"
USER_AGENT = "TunaTracker/1.0 (+https://thetunatracker.com)"
TIMEOUT_SECONDS = 15

# Feed-fetch retry policy: transient network / 5xx / 429 errors are retried
# with growing backoff before the feed counts as failed for this run.
FETCH_ATTEMPTS = 4
FETCH_BACKOFF_SECONDS = (5, 20, 60)

# Listing-page backfill (forum page-N walk) used to recover posts that
# scrolled out of the ~25-item RSS window. robots.txt allows these paths;
# we stay well under one request per 2 s and stop on 403/429.
BACKFILL_RATE_LIMIT_SECONDS = 2.0
BACKFILL_MAX_PAGES = 40
BACKFILL_MAX_THREADS = 600
DB_TIMEOUT_SECONDS = 30
DB_BUSY_TIMEOUT_MS = 30000

# Truncation-repair fetch parameters (thread page fetch when RSS body ends
# with "Read more"). Confirmed accessible without login/CF wall in Phase 0.
TRUNC_MAX_FETCHES_PER_RUN = 25
TRUNC_RATE_LIMIT_SECONDS = 1.0
TRUNC_MARKER = "Read more"
TRUNC_STOP_STATUSES = (403, 429)
TRUNC_MAX_ATTEMPTS_PER_ROW = 3   # give up on a thread page after this many misses

SCHEMA = """
-- Free-text fishing reports we pull in from public forums, to be
-- extracted into structured report_mentions by scraper/paddies/extract.py.
CREATE TABLE IF NOT EXISTS paddy_sources (
    id            TEXT PRIMARY KEY,      -- sha1(canonical_url)
    source        TEXT NOT NULL,         -- 'bdoutdoors'
    feed_id       TEXT NOT NULL DEFAULT 'bd-socal-offshore',  -- from feeds.py
    url           TEXT NOT NULL UNIQUE,
    title         TEXT,
    author        TEXT,
    published_at  TEXT NOT NULL,         -- ISO-8601 UTC
    fetched_at    TEXT NOT NULL,         -- ISO-8601 UTC
    raw_text      TEXT NOT NULL,         -- HTML-stripped post body
    extracted     INTEGER NOT NULL DEFAULT 0,
    truncated     INTEGER NOT NULL DEFAULT 0,
    repair_attempts INTEGER NOT NULL DEFAULT 0  -- thread-page fetch tries
);

CREATE INDEX IF NOT EXISTS idx_paddy_sources_extracted
    ON paddy_sources(extracted);
CREATE INDEX IF NOT EXISTS idx_paddy_sources_published
    ON paddy_sources(published_at);
-- idx_paddy_sources_feed is created inside ensure_schema() AFTER the
-- feed_id ALTER TABLE runs, so it's safe against pre-v2 databases.
"""


class BotBlocked(RuntimeError):
    """Raised when a thread-page fetch returns a status in TRUNC_STOP_STATUSES."""

    def __init__(self, status: int, url: str):
        super().__init__(f"blocked: HTTP {status} on {url}")
        self.status = status
        self.url = url

RSS_NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(paddy_sources)")}
    # Migration: v1 -> v1.1 (truncation-repair flag).
    if "truncated" not in cols:
        conn.execute(
            "ALTER TABLE paddy_sources ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute(
            "UPDATE paddy_sources SET truncated = 1 "
            f"WHERE raw_text LIKE '%{TRUNC_MARKER}'"
        )
    # Migration: v1 -> v2 (per-feed id). All v1 rows came from SoCal offshore.
    if "feed_id" not in cols:
        conn.execute(
            "ALTER TABLE paddy_sources ADD COLUMN feed_id TEXT NOT NULL "
            "DEFAULT 'bd-socal-offshore'"
        )
    # Migration: cap thread-page re-fetches for rows that never repair.
    if "repair_attempts" not in cols:
        conn.execute(
            "ALTER TABLE paddy_sources ADD COLUMN repair_attempts INTEGER NOT NULL DEFAULT 0"
        )
    # Always ensure the feed index exists (safe once feed_id is present).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_paddy_sources_feed "
        "ON paddy_sources(feed_id)"
    )
    conn.commit()


def open_db(path: Path = None) -> sqlite3.Connection:
    """Open the paddies DB with the timeouts we need to coexist with the hourly scrape."""
    conn = sqlite3.connect(path or DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    return conn


def is_truncated(text: str) -> bool:
    """RSS body ends with 'Read more' when XenForo cut the post."""
    return bool(text) and text.rstrip().endswith(TRUNC_MARKER)


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def canonical_url(url: str) -> str:
    """Strip RSS tracking params (utm_*) so re-fetch dedup works."""
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if not k.startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(kept), ""))


def strip_html(html: str) -> str:
    """Turn XenForo bbWrapper HTML into readable plain text."""
    if not html:
        return ""
    s = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)     # drops <img>, <a>, everything else
    s = html_module.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _fetch_once(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
        return r.read()


def _retryable(e: Exception) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    # URLError, timeouts, connection resets, truncated reads
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))


def fetch_with_retry(url: str, accept: str, *, attempts: int = FETCH_ATTEMPTS,
                     backoff=FETCH_BACKOFF_SECONDS, sleep=time.sleep) -> bytes:
    """GET with retry on transient failures. Raises the last error."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return _fetch_once(url, accept)
        except Exception as e:  # noqa: BLE001
            last = e
            if not _retryable(e) or i == attempts - 1:
                break
            wait = backoff[min(i, len(backoff) - 1)]
            print(f"[paddies:ingest_bd] fetch failed ({e!r}); retry {i + 1} in {wait}s",
                  file=sys.stderr)
            sleep(wait)
    assert last is not None
    raise last


def fetch_feed(url: str = FEED_URL) -> bytes:
    return fetch_with_retry(url, "application/rss+xml, application/xml, text/xml, */*")


def fetch_thread_body(url: str) -> str | None:
    """
    Fetch a XenForo thread page and return the OP's post body as plain text.
    Raises BotBlocked on 403 / 429 so the caller can stop further fetches.
    Returns None on any other failure (soft — caller continues).
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        if e.code in TRUNC_STOP_STATUSES:
            raise BotBlocked(e.code, url)
        return None
    except Exception:
        return None
    if status in TRUNC_STOP_STATUSES:
        raise BotBlocked(status, url)
    if status != 200:
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(body, "lxml")
    # First article.message--post is the OP; class list may include modifiers.
    op = soup.find("article", class_=lambda c: c and "message--post" in c)
    if not op:
        return None
    bb = op.find("div", class_="bbWrapper")
    if not bb:
        return None
    for tag in bb.find_all(["script", "style", "img"]):
        tag.decompose()
    for br in bb.find_all("br"):
        br.replace_with("\n")
    text = bb.get_text(separator=" ", strip=False)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def parse_feed(xml_bytes: bytes):
    """
    Yield dicts of {url, title, author, published_at (datetime UTC), raw_text}.
    Skips items missing a parseable pubDate or an empty body.
    """
    root = ET.fromstring(xml_bytes)
    for item in root.findall(".//item"):
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        url = canonical_url(link)

        title = (item.findtext("title") or "").strip() or None

        pub_raw = (item.findtext("pubDate") or "").strip()
        try:
            pub_dt = parsedate_to_datetime(pub_raw).astimezone(timezone.utc)
        except (TypeError, ValueError, AttributeError):
            continue

        author = item.findtext("dc:creator", default="", namespaces=RSS_NS).strip()
        if not author:
            author = (item.findtext("author") or "").strip()
        author = author or None

        html = item.findtext("content:encoded", default="", namespaces=RSS_NS) or ""
        if not html:
            html = item.findtext("description", default="") or ""
        text = strip_html(html)
        if not text:
            continue

        yield {
            "url": url,
            "title": title,
            "author": author,
            "published_at": pub_dt,
            "raw_text": text,
        }


def upsert_source(conn: sqlite3.Connection, item: dict, fetched_at: datetime,
                  feed_id: str = "bd-socal-offshore") -> bool:
    """Insert if new. Returns True if a new row was created."""
    row = {
        "id":           sha1_hex(item["url"]),
        "source":       "bdoutdoors",
        "feed_id":      feed_id,
        "url":          item["url"],
        "title":        item["title"],
        "author":       item["author"],
        "published_at": item["published_at"].strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "fetched_at":   fetched_at.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "raw_text":     item["raw_text"],
        "truncated":    1 if is_truncated(item["raw_text"]) else 0,
    }
    cur = conn.execute("""
        INSERT INTO paddy_sources
            (id, source, feed_id, url, title, author, published_at, fetched_at,
             raw_text, extracted, truncated)
        VALUES
            (:id, :source, :feed_id, :url, :title, :author, :published_at, :fetched_at,
             :raw_text, 0, :truncated)
        ON CONFLICT(id) DO NOTHING
    """, row)
    return cur.rowcount == 1


def repair_truncated(conn: sqlite3.Connection, max_fetches: int = TRUNC_MAX_FETCHES_PER_RUN) -> dict:
    """
    Fetch thread pages for rows currently marked truncated=1 and replace their
    raw_text with the full OP body. Stops on 403/429 or when the cap is hit.
    Re-fetched rows have extracted reset to 0 so downstream extraction re-runs.
    """
    stats = {"attempted": 0, "repaired": 0, "no_change": 0, "blocked": False}
    rows = list(conn.execute(
        "SELECT id, url FROM paddy_sources "
        "WHERE truncated = 1 AND repair_attempts < ? ORDER BY published_at DESC",
        (TRUNC_MAX_ATTEMPTS_PER_ROW,),
    ))
    if not rows:
        return stats
    for row in rows[:max_fetches]:
        stats["attempted"] += 1
        try:
            body = fetch_thread_body(row["url"])
        except BotBlocked as e:
            stats["blocked"] = True
            print(f"[paddies:ingest_bd] STOP: bot-wall status {e.status} on {row['url']}",
                  file=sys.stderr)
            break
        if body is None:
            stats["no_change"] += 1
            conn.execute(
                "UPDATE paddy_sources SET repair_attempts = repair_attempts + 1 WHERE id = ?",
                (row["id"],),
            )
        else:
            conn.execute(
                "UPDATE paddy_sources "
                "SET raw_text = ?, truncated = 0, extracted = 0 "
                "WHERE id = ?",
                (body, row["id"]),
            )
            stats["repaired"] += 1
        conn.commit()
        time.sleep(TRUNC_RATE_LIMIT_SECONDS)
    return stats




# ------------------------------------------------------------------ backfill

BD_BASE = "https://www.bdoutdoors.com"
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


def _parse_xf_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except ValueError:
        return None


def parse_listing(html_bytes: bytes):
    """
    Yield thread stubs from a XenForo forum listing page (forum/page-N):
    {url, title, author, published_at, last_post_at, sticky}. Listing pages
    are ordered by last-post date, newest first (stickies on top).
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soup = BeautifulSoup(html_bytes, "lxml")
    for div in soup.select("div.structItem--thread"):
        a = None
        for cand in div.select(".structItem-title a[href]"):
            href = cand["href"]
            if "/threads/" in href and not re.search(r"/(latest|unread|vote)\b", href):
                a = cand
                break
        if a is None:
            continue
        times = div.select("time.u-dt")
        start = _parse_xf_time(times[0].get("datetime")) if times else None
        latest_el = div.select_one("time.structItem-latestDate")
        latest = _parse_xf_time(latest_el.get("datetime")) if latest_el else start
        if start is None:
            continue
        yield {
            "url": canonical_url(urljoin(BD_BASE, a["href"])),
            "title": a.get_text(strip=True) or None,
            "author": div.get("data-author") or None,
            "published_at": start,
            "last_post_at": latest or start,
            "sticky": "structItem--sticky" in (div.get("class") or []),
        }


def _listing_url(forum_url: str, page: int) -> str:
    base = forum_url if forum_url.endswith("/") else forum_url + "/"
    return base if page == 1 else f"{base}page-{page}"


def backfill_from_listing(conn: sqlite3.Connection, feed: dict, since: datetime,
                          fetched_at: datetime, *, max_pages: int = BACKFILL_MAX_PAGES,
                          max_threads: int = BACKFILL_MAX_THREADS,
                          sleep=time.sleep) -> dict:
    """
    Walk forum listing pages newest-first and insert every thread started at
    or after `since` that we don't already have, fetching the OP body from
    the thread page. Stops when a whole page is older than `since`, on
    403/429, or at the page / thread caps. Idempotent (ON CONFLICT DO NOTHING).
    Threads whose body can't be fetched are stored as title + truncation
    marker so repair_truncated() retries them later.
    """
    stats = {"since": _iso(since), "pages": 0, "threads_in_window": 0,
             "new_rows": 0, "body_failures": 0, "blocked": False,
             "reached_since": False, "error": None}
    attempted = 0
    for page in range(1, max_pages + 1):
        url = _listing_url(feed["forum_url"], page)
        try:
            html_bytes = fetch_with_retry(url, HTML_ACCEPT, sleep=sleep)
        except urllib.error.HTTPError as e:
            if e.code in TRUNC_STOP_STATUSES:
                stats["blocked"] = True
            stats["error"] = f"HTTP {e.code} on {url}"
            break
        except Exception as e:  # noqa: BLE001
            stats["error"] = f"{e!r} on {url}"
            break
        stats["pages"] += 1
        threads = list(parse_listing(html_bytes))
        if not threads:
            break
        page_has_recent = False
        for t in threads:
            if not t["sticky"] and t["last_post_at"] >= since:
                page_has_recent = True
            if t["published_at"] < since:
                continue
            stats["threads_in_window"] += 1
            sid = sha1_hex(t["url"])
            if conn.execute("SELECT 1 FROM paddy_sources WHERE id = ?", (sid,)).fetchone():
                continue
            if attempted >= max_threads:
                break
            attempted += 1
            try:
                body = fetch_thread_body(t["url"])
            except BotBlocked as e:
                stats["blocked"] = True
                stats["error"] = f"HTTP {e.status} on {e.url}"
                break
            sleep(BACKFILL_RATE_LIMIT_SECONDS)
            if not body:
                stats["body_failures"] += 1
                body = f"{t['title'] or ''}\n\n{TRUNC_MARKER}"
            item = {"url": t["url"], "title": t["title"], "author": t["author"],
                    "published_at": t["published_at"], "raw_text": body}
            if upsert_source(conn, item, fetched_at, feed_id=feed["id"]):
                stats["new_rows"] += 1
        conn.commit()
        if stats["blocked"] or attempted >= max_threads:
            break
        if not page_has_recent:
            stats["reached_since"] = True
            break
        sleep(BACKFILL_RATE_LIMIT_SECONDS)
    return stats


# ------------------------------------------------------------------ run

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _newest_published(conn: sqlite3.Connection, feed_id: str) -> datetime | None:
    r = conn.execute(
        "SELECT MAX(published_at) FROM paddy_sources WHERE feed_id = ?", (feed_id,)
    ).fetchone()
    if not r or not r[0]:
        return None
    return datetime.fromisoformat(r[0]).astimezone(timezone.utc)


def run(feed_ids: list[str] | None = None, backfill_since: datetime | None = None,
        max_pages: int = BACKFILL_MAX_PAGES, sleep=time.sleep) -> dict:
    """
    One ingest pass over every enabled feed:
      1. fetch RSS (with retry) and upsert items;
      2. if the feed window no longer overlaps what we already have (we were
         down long enough for posts to scroll off), walk the forum listing
         pages back to our newest stored post and backfill the gap;
         `backfill_since` forces that walk from an explicit date;
      3. repair truncated RSS bodies from thread pages.
    """
    conn = open_db()
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        feeds = [f for f in feeds_mod.enabled_feeds()
                 if not feed_ids or f["id"] in feed_ids]
        per_feed: dict[str, dict] = {}
        for feed in feeds:
            fs = {"ok": False, "items_seen": 0, "new_rows": 0, "overlap": 0,
                  "gap_detected": False, "backfill": None, "error": None,
                  "newest_published_at": None}
            newest_before = _newest_published(conn, feed["id"])
            t0 = time.monotonic()
            try:
                xml_bytes = fetch_feed(feed["rss_url"])
                items = list(parse_feed(xml_bytes))
            except Exception as e:  # noqa: BLE001
                fs["error"] = repr(e)[:300]
                per_feed[feed["id"]] = fs
                print(f"[paddies:ingest_bd] {feed['id']}: FEED FAILED {e!r}", file=sys.stderr)
                continue
            fs["ok"] = True
            fs["fetch_seconds"] = round(time.monotonic() - t0, 3)
            fs["items_seen"] = len(items)
            fetched_at = datetime.now(timezone.utc)
            for item in items:
                if conn.execute("SELECT 1 FROM paddy_sources WHERE id = ?",
                                (sha1_hex(item["url"]),)).fetchone():
                    fs["overlap"] += 1
                elif upsert_source(conn, item, fetched_at, feed_id=feed["id"]):
                    fs["new_rows"] += 1
            conn.commit()

            since = backfill_since
            if since is None and newest_before and items and fs["overlap"] == 0:
                oldest = min(i["published_at"] for i in items)
                if oldest > newest_before:
                    fs["gap_detected"] = True
                    since = newest_before
                    print(f"[paddies:ingest_bd] {feed['id']}: GAP - oldest feed item "
                          f"{_iso(oldest)} is newer than newest stored {_iso(newest_before)}; "
                          f"backfilling from listing pages", file=sys.stderr)
            # A feed added to feeds.py with initial_backfill_days gets one walk
            # of its listing pages on its first run, so it starts with a season
            # of history instead of just the ~25 RSS items.
            if since is None and newest_before is None and feed.get("initial_backfill_days"):
                since = fetched_at - timedelta(days=feed["initial_backfill_days"])
                fs["initial_backfill"] = True
                print(f"[paddies:ingest_bd] {feed['id']}: new feed - initial backfill "
                      f"from {_iso(since)}", file=sys.stderr)
            if since is not None:
                fs["backfill"] = backfill_from_listing(
                    conn, feed, since, fetched_at, max_pages=max_pages, sleep=sleep)
                fs["new_rows"] += fs["backfill"]["new_rows"]
            newest = _newest_published(conn, feed["id"])
            fs["newest_published_at"] = _iso(newest) if newest else None
            per_feed[feed["id"]] = fs

        repair_stats = repair_truncated(conn)

        def _count(where: str) -> int:
            return conn.execute(
                f"SELECT COUNT(*) FROM paddy_sources WHERE source='bdoutdoors' {where}"
            ).fetchone()[0]

        return {
            "feeds": per_feed,
            "items_seen": sum(f["items_seen"] for f in per_feed.values()),
            "new_rows": sum(f["new_rows"] for f in per_feed.values()),
            "truncation_repair": repair_stats,
            "total_rows": _count(""),
            # Only paddy-kind feeds go through extract.py; boat-report feeds
            # are tracked by boat_reports.py's own table.
            "pending_extract": _count("AND extracted=0 AND feed_id IN (%s)" % ",".join(
                "'%s'" % f for f in feeds_mod.feed_ids("paddies"))),
            "still_truncated": _count("AND truncated=1"),
        }
    finally:
        conn.close()


# ------------------------------------------------------------------ state

def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"consecutive_zero_runs": 0, "last_run_utc": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"consecutive_zero_runs": 0, "last_run_utc": None}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_state(state: dict, stats: dict, now: datetime) -> dict:
    """
    Fold one run's stats into the persisted health state. This file is the
    contract for data-health alerting (read by scraper/paddies/health.py):
      last_success_utc         - last run where the primary feed fetched OK
      last_new_row_utc         - last run that stored at least one new post
      newest_post_published_at - newest stored post on the primary feed
      consecutive_failures     - primary-feed fetch failures in a row
    """
    now_s = _iso(now)
    state["last_run_utc"] = now_s
    state["last_items_seen"] = stats["items_seen"]
    state["consecutive_zero_runs"] = (
        state.get("consecutive_zero_runs", 0) + 1 if stats["items_seen"] == 0 else 0)
    feeds_state = state.setdefault("feeds", {})
    for fid, fs in stats["feeds"].items():
        st = feeds_state.setdefault(fid, {})
        if fs["ok"]:
            st["last_success_utc"] = now_s
            st["consecutive_failures"] = 0
            st["last_error"] = None
        else:
            st["consecutive_failures"] = st.get("consecutive_failures", 0) + 1
            st["last_error"] = fs["error"]
        if fs["new_rows"]:
            st["last_new_row_utc"] = now_s
        if fs.get("newest_published_at"):
            st["newest_post_published_at"] = fs["newest_published_at"]
        if fs.get("gap_detected"):
            st["last_gap_utc"] = now_s
    primary = feeds_state.get(PRIMARY_FEED_ID, {})
    for k in ("last_success_utc", "last_new_row_utc", "newest_post_published_at",
              "consecutive_failures", "last_error"):
        if k in primary:
            state[k] = primary[k]
    state["total_rows"] = stats["total_rows"]
    state["pending_extract"] = stats["pending_extract"]
    return state


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest BloodyDecks forum posts.")
    ap.add_argument("--backfill-since", metavar="YYYY-MM-DD",
                    help="walk forum listing pages and backfill threads started on/after this date")
    ap.add_argument("--feed", action="append", dest="feeds",
                    help="limit to this feed id (repeatable; default: all enabled)")
    ap.add_argument("--max-pages", type=int, default=BACKFILL_MAX_PAGES)
    args = ap.parse_args(argv if argv is not None else [])

    since = None
    if args.backfill_since:
        since = datetime.strptime(args.backfill_since, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print(f"[paddies:ingest_bd] db={DB_PATH}")
    try:
        stats = run(feed_ids=args.feeds, backfill_since=since, max_pages=args.max_pages)
    except Exception as e:  # noqa: BLE001
        print(f"[paddies:ingest_bd] FAILED: {e!r}", file=sys.stderr)
        return 1
    for fid, fs in stats["feeds"].items():
        print(f"  [{fid}] " + ", ".join(f"{k}={v}" for k, v in fs.items()))
    for k, v in stats.items():
        if k != "feeds":
            print(f"  {k}: {v}")

    state = update_state(_load_state(), stats, datetime.now(timezone.utc))
    _save_state(state)

    if state["consecutive_zero_runs"] >= 2:
        msg = (f"BD feed returned 0 items for {state['consecutive_zero_runs']} "
               f"consecutive runs - feed may be broken.")
        print(f"::warning title=paddies ingest::{msg}")
        print(f"[paddies:ingest_bd] WARNING: {msg}", file=sys.stderr)
    elif stats["items_seen"] == 0:
        print("[paddies:ingest_bd] INFO: feed returned 0 items (not consecutive yet)",
              file=sys.stderr)

    primary = stats["feeds"].get(PRIMARY_FEED_ID)
    if primary is not None and not primary["ok"]:
        print(f"::error title=paddies ingest::primary BD feed fetch failed: {primary['error']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
