"""
Ingest new posts from the Bloodydecks SoCal Offshore Fishing Reports
forum. Reads the per-forum RSS feed once and upserts each item into the
`paddy_sources` table in tracker.db.

- Idempotent: PK is sha1(canonical_url); re-running never duplicates.
- No thread fetches — the RSS content:encoded carries the full post body.
- No image downloads (HTML is stripped to text before storage).
- No backfill in v1: coverage = whatever depth the feed exposes (~25 items).

Usage:
    .venv/Scripts/python.exe -m scraper.paddies.ingest_bd
"""
from __future__ import annotations

import hashlib
import html as html_module
import json
import re
import sqlite3
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "tracker.db"
STATE_PATH = ROOT / "data" / "paddies_ingest_state.json"

FEED_URL = (
    "https://www.bdoutdoors.com/forums/forum/"
    "southern-california-offshore-fishing-reports/index.rss"
)
USER_AGENT = "TunaTracker/1.0 (+https://thetunatracker.com)"
TIMEOUT_SECONDS = 15
DB_TIMEOUT_SECONDS = 30
DB_BUSY_TIMEOUT_MS = 30000

# Truncation-repair fetch parameters (thread page fetch when RSS body ends
# with "Read more"). Confirmed accessible without login/CF wall in Phase 0.
TRUNC_MAX_FETCHES_PER_RUN = 25
TRUNC_RATE_LIMIT_SECONDS = 1.0
TRUNC_MARKER = "Read more"
TRUNC_STOP_STATUSES = (403, 429)

SCHEMA = """
-- Free-text fishing reports we pull in from public forums, to be
-- extracted into structured paddy_mentions by scraper/paddies/extract.py.
CREATE TABLE IF NOT EXISTS paddy_sources (
    id            TEXT PRIMARY KEY,      -- sha1(canonical_url)
    source        TEXT NOT NULL,         -- 'bdoutdoors'
    url           TEXT NOT NULL UNIQUE,
    title         TEXT,
    author        TEXT,
    published_at  TEXT NOT NULL,         -- ISO-8601 UTC
    fetched_at    TEXT NOT NULL,         -- ISO-8601 UTC
    raw_text      TEXT NOT NULL,         -- HTML-stripped post body
    extracted     INTEGER NOT NULL DEFAULT 0,
    truncated     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_paddy_sources_extracted
    ON paddy_sources(extracted);
CREATE INDEX IF NOT EXISTS idx_paddy_sources_published
    ON paddy_sources(published_at);
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
    # Migration: pre-existing DBs lack the `truncated` column. Add it and
    # backfill from the RSS "Read more" tail marker.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(paddy_sources)")}
    if "truncated" not in cols:
        conn.execute(
            "ALTER TABLE paddy_sources ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0"
        )
        conn.execute(
            "UPDATE paddy_sources SET truncated = 1 "
            f"WHERE raw_text LIKE '%{TRUNC_MARKER}'"
        )
    conn.commit()


def open_db(path: Path = None) -> sqlite3.Connection:
    """Open tracker.db with the timeouts we need to coexist with the hourly scrape."""
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


def fetch_feed(url: str = FEED_URL) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
        return r.read()


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


def upsert_source(conn: sqlite3.Connection, item: dict, fetched_at: datetime) -> bool:
    """Insert if new. Returns True if a new row was created."""
    row = {
        "id":           sha1_hex(item["url"]),
        "source":       "bdoutdoors",
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
            (id, source, url, title, author, published_at, fetched_at, raw_text, extracted, truncated)
        VALUES
            (:id, :source, :url, :title, :author, :published_at, :fetched_at, :raw_text, 0, :truncated)
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
        "SELECT id, url FROM paddy_sources WHERE truncated = 1 ORDER BY published_at DESC"
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


def run() -> dict:
    conn = open_db()
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        t0 = time.monotonic()
        xml_bytes = fetch_feed()
        fetch_elapsed = time.monotonic() - t0
        fetched_at = datetime.now(timezone.utc)

        items_seen = 0
        new_rows = 0
        for item in parse_feed(xml_bytes):
            items_seen += 1
            if upsert_source(conn, item, fetched_at):
                new_rows += 1
        conn.commit()

        repair_stats = repair_truncated(conn)

        total = conn.execute(
            "SELECT COUNT(*) FROM paddy_sources WHERE source='bdoutdoors'"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM paddy_sources WHERE source='bdoutdoors' AND extracted=0"
        ).fetchone()[0]
        still_truncated = conn.execute(
            "SELECT COUNT(*) FROM paddy_sources WHERE source='bdoutdoors' AND truncated=1"
        ).fetchone()[0]

        return {
            "feed_bytes": len(xml_bytes),
            "fetch_seconds": round(fetch_elapsed, 3),
            "items_seen": items_seen,
            "new_rows": new_rows,
            "truncation_repair": repair_stats,
            "total_rows": total,
            "pending_extract": pending,
            "still_truncated": still_truncated,
        }
    finally:
        conn.close()


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"consecutive_zero_runs": 0, "last_run_utc": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"consecutive_zero_runs": 0, "last_run_utc": None}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    print(f"[paddies:ingest_bd] db={DB_PATH}")
    print(f"[paddies:ingest_bd] feed={FEED_URL}")
    try:
        stats = run()
    except Exception as e:
        print(f"[paddies:ingest_bd] FAILED: {e!r}", file=sys.stderr)
        return 1
    for k, v in stats.items():
        print(f"  {k}: {v}")

    state = _load_state()
    if stats["items_seen"] == 0:
        state["consecutive_zero_runs"] = state.get("consecutive_zero_runs", 0) + 1
    else:
        state["consecutive_zero_runs"] = 0
    state["last_run_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["last_items_seen"] = stats["items_seen"]
    _save_state(state)

    if state["consecutive_zero_runs"] >= 2:
        # GitHub Actions warning annotation (rendered prominently, does NOT fail the job).
        msg = (f"BD feed returned 0 items for {state['consecutive_zero_runs']} "
               f"consecutive runs — feed may be broken.")
        print(f"::warning title=paddies ingest::{msg}")
        print(f"[paddies:ingest_bd] WARNING: {msg}", file=sys.stderr)
    elif stats["items_seen"] == 0:
        # First zero-run — informational, not a warning.
        print("[paddies:ingest_bd] INFO: feed returned 0 items (not consecutive yet)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
