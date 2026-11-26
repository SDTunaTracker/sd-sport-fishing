"""
Read the replies in active BloodyDecks threads.

ingest_bd stores each thread's first post only. Busy report threads run
10-35 replies and about 1 in 6 is a report of its own ("we were there
too", a second count, water temp, what bit). This pass:

  1. reads page 1 of each enabled forum's listing (one request per forum)
     for each thread's reply count and last-post time;
  2. for non-sticky threads with new replies in the last ACTIVE_DAYS,
     fetches the newest unread thread page(s) (25 posts a page);
  3. stores each reply that looks like a report (length plus a species,
     place, bait or water-temp word, quoted text removed) as its own
     paddy_sources row, with reply_to = the thread URL and the thread
     title as context, so the existing extractors (extract.py for paddy
     feeds, boat_reports.py for boat-report feeds) pick it up unchanged;
  4. records attachment links (photos) on replies and on the thread's
     first post.

Polite: one request per REQUEST_SLEEP seconds, at most MAX_PAGES_PER_RUN
thread pages a run, stop on 403/429. Guest pages only; robots.txt allows
/forums/threads/.

Usage:
    .venv/Scripts/python.exe -m scraper.paddies.replies [--max-pages 40]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
from datetime import datetime, timedelta, timezone

from . import feeds as feeds_mod
from . import ingest_bd as bd

POSTS_PER_PAGE = 25
ACTIVE_DAYS = 14
MAX_PAGES_PER_RUN = 40
MAX_PAGES_PER_THREAD = 3
REQUEST_SLEEP = 2.5
MIN_REPLY_CHARS = 60

REPORT_WORDS = re.compile(
    r"\b(bluefin|yellowfin|yft|bft|yellowtail|\byt\b|dorado|mahi|wahoo|tuna|albacore|skipjack|"
    r"calico|bass|halibut|white ?sea ?bass|wsb|rockfish|lingcod|bonito|barracuda|sheephead|"
    r"sardine|anchov|squid|mackerel|bait|paddy|paddies|kelp|bank|ridge|island|"
    r"\d+\s?(?:lb|lbs|pound|pounds)|\d{2}(?:\.\d)?\s?(?:deg|°|degrees)|water temp|"
    r"limits?|landed|caught|hooked|boated|bit|bite|biting|trolling|jig|popper|flyline|"
    r"miles?|knots|stops?)\b", re.I)

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS bd_threads (
    url           TEXT PRIMARY KEY,   -- canonical thread URL (ends with '/')
    feed_id       TEXT NOT NULL,
    title         TEXT,
    replies_seen  INTEGER NOT NULL DEFAULT 0,
    last_page     INTEGER NOT NULL DEFAULT 0,  -- highest page read
    last_post_at  TEXT,
    checked_at    TEXT
);
"""


class Blocked(RuntimeError):
    pass


def ensure_schema(conn: sqlite3.Connection) -> None:
    bd.ensure_schema(conn)
    conn.executescript(STATE_SCHEMA)
    conn.commit()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _page_url(thread_url: str, page: int) -> str:
    base = thread_url if thread_url.endswith("/") else thread_url + "/"
    return base if page <= 1 else f"{base}page-{page}"


def parse_thread_page(html: bytes | str) -> list[dict]:
    """Posts on one thread page: {post_id, author, published_at, text, photos}."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out = []
    for art in soup.select("article.message--post"):
        pid = (art.get("data-content") or art.get("id") or "").replace("js-post-", "")
        m = re.search(r"post-(\d+)", pid)
        if not m:
            continue
        bb = art.select_one(".message-body .bbWrapper") or art.select_one(".bbWrapper")
        if bb is None:
            continue
        raw_html = str(bb)
        for q in bb.select("blockquote, .bbCodeBlock--quote"):
            q.decompose()
        for tag in bb.find_all(["script", "style", "img"]):
            tag.decompose()
        for br in bb.find_all("br"):
            br.replace_with("\n")
        text = re.sub(r"[ \t]+", " ", bb.get_text(" "))
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        # "View attachment IMG_1.jpeg" lines are noise in the text.
        text = re.sub(r"View attachment \S+", "", text).strip()
        t = art.select_one("time.u-dt")
        out.append({
            "post_id": int(m.group(1)),
            "author": art.get("data-author") or None,
            "published_at": bd._parse_xf_time(t.get("datetime")) if t else None,
            "text": text,
            "photos": bd.extract_photos(raw_html),
        })
    return out


PLEASANTRY = re.compile(r"^\s*(thanks|thank you|thx|great|nice|awesome|congrats|good job|"
                        r"way to go|sick|epic|well done|right on)\b", re.I)


def looks_like_report(text: str) -> bool:
    """Long enough, names a fish / place / bait / temp, and isn't just a 'nice report!'."""
    text = text or ""
    if len(text) < MIN_REPLY_CHARS or not REPORT_WORDS.search(text):
        return False
    return not (len(text) < 200 and PLEASANTRY.match(text))


def _fetch(url: str, sleep) -> bytes:
    try:
        body = bd.fetch_with_retry(url, bd.HTML_ACCEPT, attempts=2, sleep=sleep)
    except urllib.error.HTTPError as e:
        if e.code in bd.TRUNC_STOP_STATUSES:
            raise Blocked(f"HTTP {e.code} on {url}") from e
        raise
    sleep(REQUEST_SLEEP)
    return body


def _set_op_photos(conn, thread_url: str, photos: list[str]) -> None:
    if photos:
        conn.execute("UPDATE paddy_sources SET photos = ? WHERE id = ? AND photos IS NULL",
                     (json.dumps(photos), bd.sha1_hex(thread_url)))


def run(conn: sqlite3.Connection, *, feed_ids: list[str] | None = None,
        max_pages: int = MAX_PAGES_PER_RUN, now: datetime | None = None,
        fetcher=None, sleep=time.sleep) -> dict:
    now = now or datetime.now(timezone.utc)
    fetch = fetcher or (lambda u: _fetch(u, sleep))
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    feeds = [f for f in feeds_mod.enabled_feeds() if not feed_ids or f["id"] in feed_ids]
    st = {"listings": 0, "threads_active": 0, "pages": 0, "replies_seen": 0,
          "replies_stored": 0, "photos": 0, "blocked": False, "error": None}
    cutoff = now - timedelta(days=ACTIVE_DAYS)
    todo = []
    try:
        for feed in feeds:
            html = fetch(bd._listing_url(feed["forum_url"], 1))
            st["listings"] += 1
            for t in bd.parse_listing(html):
                if t["sticky"] or not t.get("replies") or t["last_post_at"] < cutoff:
                    continue
                row = conn.execute("SELECT * FROM bd_threads WHERE url = ?", (t["url"],)).fetchone()
                if row and row["replies_seen"] >= t["replies"]:
                    continue
                todo.append((t, feed, row))
        todo.sort(key=lambda x: x[0]["last_post_at"], reverse=True)
        st["threads_active"] = len(todo)
        for t, feed, row in todo:
            if st["pages"] >= max_pages:
                break
            last = t["replies"] // POSTS_PER_PAGE + 1
            # First sighting: the newest page only (older replies are old news).
            # After that: from the last page read (it may have filled up), at
            # most MAX_PAGES_PER_THREAD pages.
            first = last if row is None else max(row["last_page"], last - MAX_PAGES_PER_THREAD + 1, 1)
            read_to = first - 1
            for page in range(first, last + 1):
                if st["pages"] >= max_pages:
                    break
                posts = parse_thread_page(fetch(_page_url(t["url"], page)))
                st["pages"] += 1
                read_to = page
                for i, p in enumerate(posts):
                    if page == 1 and i == 0:          # the first post: ingest_bd has it
                        _set_op_photos(conn, t["url"], p["photos"])
                        continue
                    st["replies_seen"] += 1
                    if (not p["published_at"] or p["published_at"] < cutoff
                            or not looks_like_report(p["text"])):
                        continue
                    item = {"url": f"{t['url']}post-{p['post_id']}",
                            "title": t["title"], "author": p["author"],
                            "published_at": p["published_at"],
                            "raw_text": f"Reply in the thread \"{t['title']}\":\n{p['text']}",
                            "photos": p["photos"], "reply_to": t["url"]}
                    if bd.upsert_source(conn, item, now, feed_id=feed["id"]):
                        st["replies_stored"] += 1
                        st["photos"] += len(p["photos"])
            done = read_to >= last
            conn.execute(
                "INSERT INTO bd_threads (url, feed_id, title, replies_seen, last_page, last_post_at, "
                "checked_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
                "replies_seen = excluded.replies_seen, last_page = excluded.last_page, "
                "last_post_at = excluded.last_post_at, checked_at = excluded.checked_at, "
                "title = excluded.title",
                (t["url"], feed["id"], t["title"],
                 t["replies"] if done else (row["replies_seen"] if row else 0),
                 max(read_to, row["last_page"] if row else 0), _iso(t["last_post_at"]), _iso(now)))
            conn.commit()
    except Blocked as e:
        st["blocked"], st["error"] = True, str(e)
        print(f"[paddies:replies] STOP: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - never take the workflow down
        st["error"] = repr(e)[:300]
        print(f"[paddies:replies] FAILED: {e!r}", file=sys.stderr)
    conn.commit()
    return st


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read replies in active BloodyDecks threads.")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES_PER_RUN)
    ap.add_argument("--feed", action="append", dest="feeds")
    args = ap.parse_args(argv if argv is not None else [])
    conn = bd.open_db()
    try:
        st = run(conn, feed_ids=args.feeds, max_pages=args.max_pages)
    finally:
        conn.close()
    print("[paddies:replies] " + ", ".join(f"{k}={v}" for k, v in st.items()))
    if st["blocked"]:
        print(f"::warning title=paddies replies::stopped: {st['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
