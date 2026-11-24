"""Tests for ingest_bd reliability: fetch retry, listing backfill, gap detection, health state."""
from __future__ import annotations

import os
import sqlite3
import sys
import urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scraper.paddies import feeds, ingest_bd

PRIMARY = next(f for f in feeds.FEEDS if f["id"] == ingest_bd.PRIMARY_FEED_ID)
UTC = timezone.utc


def _thread(tid, title, start, latest, author="angler", sticky=False):
    cls = "structItem structItem--thread js-inlineModContainer"
    if sticky:
        cls += " structItem--sticky"
    return f"""
<div class="{cls} js-threadListItem-{tid}" data-author="{author}">
  <div class="structItem-cell structItem-cell--main">
    <div class="structItem-title">
      <a href="/forums/forum/x/?prefix_id=30" class="labelLink">Report</a>
      <a href="/forums/threads/{title.lower().replace(' ', '-')}.{tid}/">{title}</a>
    </div>
    <ul class="structItem-parts">
      <li class="structItem-startDate"><a href="/forums/threads/t.{tid}/">
        <time class="u-dt" datetime="{start}">x</time></a></li>
    </ul>
  </div>
  <div class="structItem-cell structItem-cell--latest">
    <a href="/forums/threads/t.{tid}/latest">
      <time class="structItem-latestDate u-dt" datetime="{latest}">x</time></a>
  </div>
</div>"""


def _page(*threads):
    return ("<html><body><div class='structItemContainer'>"
            + "".join(threads) + "</div></body></html>").encode()


PAGE1 = _page(
    _thread(1, "Report it here", "2020-01-01T00:00:00-0800", "2026-11-24T10:00:00-0800", sticky=True),
    _thread(10, "Bluefin at the 43", "2026-11-20T06:00:00-0800", "2026-11-21T06:00:00-0800"),
    _thread(9, "Yellowtail on kelp", "2026-11-12T06:00:00-0800", "2026-11-19T06:00:00-0800"),
)
PAGE2 = _page(
    _thread(8, "Dorado paddy", "2026-11-05T06:00:00-0800", "2026-11-11T06:00:00-0800"),
    _thread(7, "Old report", "2026-10-01T06:00:00-0700", "2026-11-04T06:00:00-0800"),
)
PAGE3 = _page(
    _thread(6, "Ancient", "2026-09-01T06:00:00-0700", "2026-09-02T06:00:00-0700"),
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "paddies.db"
    monkeypatch.setattr(ingest_bd, "DB_PATH", path)
    monkeypatch.setattr(ingest_bd, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(ingest_bd.feeds_mod, "enabled_feeds", lambda: [PRIMARY])
    conn = ingest_bd.open_db(path)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def fake_site(monkeypatch):
    """Serve PAGE1..3 for listing URLs; thread pages return a body."""
    calls = []
    pages = {1: PAGE1, 2: PAGE2, 3: PAGE3}

    def fake_fetch(url, accept, **kw):
        calls.append(url)
        if url.rstrip("/").endswith("southern-california-offshore-fishing-reports"):
            return pages[1]
        n = int(url.rsplit("page-", 1)[1])
        return pages.get(n, _page())

    monkeypatch.setattr(ingest_bd, "fetch_with_retry", fake_fetch)
    monkeypatch.setattr(ingest_bd, "fetch_thread_body",
                        lambda url: f"full body of {url}")
    return calls


# --------------------------------------------------------------- retry

def test_fetch_with_retry_recovers_from_transient(monkeypatch):
    attempts = {"n": 0}

    def flaky(url, accept):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise urllib.error.URLError("reset")
        return b"ok"

    monkeypatch.setattr(ingest_bd, "_fetch_once", flaky)
    sleeps = []
    assert ingest_bd.fetch_with_retry("u", "a", sleep=sleeps.append) == b"ok"
    assert attempts["n"] == 3 and len(sleeps) == 2


def test_fetch_with_retry_does_not_retry_404(monkeypatch):
    attempts = {"n": 0}

    def notfound(url, accept):
        attempts["n"] += 1
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    monkeypatch.setattr(ingest_bd, "_fetch_once", notfound)
    with pytest.raises(urllib.error.HTTPError):
        ingest_bd.fetch_with_retry("u", "a", sleep=lambda s: None)
    assert attempts["n"] == 1


def test_fetch_with_retry_gives_up_after_attempts(monkeypatch):
    def down(url, accept):
        raise urllib.error.HTTPError(url, 503, "down", {}, None)

    monkeypatch.setattr(ingest_bd, "_fetch_once", down)
    sleeps = []
    with pytest.raises(urllib.error.HTTPError):
        ingest_bd.fetch_with_retry("u", "a", attempts=3, sleep=sleeps.append)
    assert len(sleeps) == 2


# --------------------------------------------------------------- listing

def test_parse_listing_extracts_threads():
    rows = list(ingest_bd.parse_listing(PAGE1))
    assert len(rows) == 3
    sticky, t10, t9 = rows
    assert sticky["sticky"] is True
    assert t10["url"] == "https://www.bdoutdoors.com/forums/threads/bluefin-at-the-43.10/"
    assert t10["title"] == "Bluefin at the 43"
    assert t10["author"] == "angler"
    assert t10["published_at"] == datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
    assert t10["last_post_at"] == datetime(2026, 11, 21, 14, 0, tzinfo=UTC)


def test_listing_url():
    assert ingest_bd._listing_url("https://x/forum/a/", 1) == "https://x/forum/a/"
    assert ingest_bd._listing_url("https://x/forum/a", 3) == "https://x/forum/a/page-3"


# --------------------------------------------------------------- backfill

def test_backfill_walks_until_page_older_than_since(db, fake_site):
    since = datetime(2026, 11, 1, tzinfo=UTC)
    st = ingest_bd.backfill_from_listing(db, PRIMARY, since, datetime.now(UTC),
                                         sleep=lambda s: None)
    # page 2 still has a thread with last post >= since; page 3 is all older
    assert st["pages"] == 3 and st["reached_since"] is True
    # threads 10, 9, 8 started after `since`; 7 and the sticky did not
    assert st["new_rows"] == 3
    titles = {r[0] for r in db.execute("SELECT title FROM paddy_sources")}
    assert titles == {"Bluefin at the 43", "Yellowtail on kelp", "Dorado paddy"}
    row = db.execute("SELECT * FROM paddy_sources WHERE title='Dorado paddy'").fetchone()
    assert row["raw_text"].startswith("full body of")
    assert row["truncated"] == 0 and row["extracted"] == 0
    assert row["feed_id"] == PRIMARY["id"]


def test_backfill_is_idempotent(db, fake_site):
    since = datetime(2026, 11, 1, tzinfo=UTC)
    ingest_bd.backfill_from_listing(db, PRIMARY, since, datetime.now(UTC), sleep=lambda s: None)
    st2 = ingest_bd.backfill_from_listing(db, PRIMARY, since, datetime.now(UTC), sleep=lambda s: None)
    assert st2["new_rows"] == 0
    assert db.execute("SELECT COUNT(*) FROM paddy_sources").fetchone()[0] == 3


def test_backfill_stores_title_as_truncated_when_body_missing(db, fake_site, monkeypatch):
    monkeypatch.setattr(ingest_bd, "fetch_thread_body", lambda url: None)
    since = datetime(2026, 11, 15, tzinfo=UTC)
    st = ingest_bd.backfill_from_listing(db, PRIMARY, since, datetime.now(UTC), sleep=lambda s: None)
    assert st["new_rows"] == 1 and st["body_failures"] == 1
    row = db.execute("SELECT raw_text, truncated FROM paddy_sources").fetchone()
    assert row["truncated"] == 1 and "Bluefin at the 43" in row["raw_text"]


def test_backfill_stops_on_bot_block(db, fake_site, monkeypatch):
    def blocked(url):
        raise ingest_bd.BotBlocked(429, url)

    monkeypatch.setattr(ingest_bd, "fetch_thread_body", blocked)
    since = datetime(2026, 11, 1, tzinfo=UTC)
    st = ingest_bd.backfill_from_listing(db, PRIMARY, since, datetime.now(UTC), sleep=lambda s: None)
    assert st["blocked"] is True and st["pages"] == 1 and st["new_rows"] == 0


def test_backfill_respects_max_pages(db, fake_site):
    since = datetime(2026, 1, 1, tzinfo=UTC)
    st = ingest_bd.backfill_from_listing(db, PRIMARY, since, datetime.now(UTC),
                                         max_pages=2, sleep=lambda s: None)
    assert st["pages"] == 2 and st["reached_since"] is False


# --------------------------------------------------------------- gap detection

def _rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>https://www.bdoutdoors.com/forums/threads/{t}.{i}/</link>"
        f"<pubDate>{d}</pubDate><content:encoded><![CDATA[<p>body {t}</p>]]></content:encoded></item>"
        for i, (t, d) in enumerate(items, start=100))
    return (f'<?xml version="1.0"?><rss version="2.0" '
            f'xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>{body}'
            f"</channel></rss>").encode()


def test_run_detects_gap_and_backfills(db, fake_site, monkeypatch):
    # we last stored a post on Nov 1; the feed now only reaches back to Nov 22
    old = {"url": "https://www.bdoutdoors.com/forums/threads/old.1/", "title": "old",
           "author": None, "published_at": datetime(2026, 11, 1, tzinfo=UTC), "raw_text": "x"}
    ingest_bd.upsert_source(db, old, datetime.now(UTC))
    db.commit()
    monkeypatch.setattr(ingest_bd, "fetch_feed", lambda *a, **k: _rss(
        ("new-a", "Mon, 23 Nov 2026 10:00:00 +0000"),
        ("new-b", "Sun, 22 Nov 2026 10:00:00 +0000")))
    stats = ingest_bd.run(sleep=lambda s: None)
    fs = stats["feeds"][PRIMARY["id"]]
    assert fs["gap_detected"] is True
    assert fs["backfill"]["new_rows"] == 3  # threads 10, 9, 8 from the listing
    assert fs["new_rows"] == 2 + 3


def test_run_no_gap_when_feed_overlaps(db, fake_site, monkeypatch):
    feed = _rss(("a", "Mon, 23 Nov 2026 10:00:00 +0000"),
                ("b", "Sun, 22 Nov 2026 10:00:00 +0000"))
    monkeypatch.setattr(ingest_bd, "fetch_feed", lambda *a, **k: feed)
    ingest_bd.run(sleep=lambda s: None)
    stats = ingest_bd.run(sleep=lambda s: None)
    fs = stats["feeds"][PRIMARY["id"]]
    assert fs["gap_detected"] is False and fs["backfill"] is None
    assert fs["overlap"] == 2 and fs["new_rows"] == 0
    assert not any("page-" in c for c in fake_site)


def test_run_survives_one_feed_failing(db, monkeypatch):
    other = dict(PRIMARY, id="bd-other", rss_url="https://example/other.rss")
    monkeypatch.setattr(ingest_bd.feeds_mod, "enabled_feeds", lambda: [PRIMARY, other])

    def fetch(url=None):
        if "other" in url:
            raise urllib.error.URLError("down")
        return _rss(("a", "Mon, 23 Nov 2026 10:00:00 +0000"))

    monkeypatch.setattr(ingest_bd, "fetch_feed", fetch)
    stats = ingest_bd.run(sleep=lambda s: None)
    assert stats["feeds"][PRIMARY["id"]]["ok"] is True
    assert stats["feeds"]["bd-other"]["ok"] is False
    assert stats["new_rows"] == 1


# --------------------------------------------------------------- state / exit code

def test_update_state_tracks_health_fields():
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    ok = {"feeds": {PRIMARY["id"]: {"ok": True, "new_rows": 2, "error": None,
                                     "newest_published_at": "2026-11-24T10:00:00Z"}},
          "items_seen": 25, "total_rows": 30, "pending_extract": 2}
    st = ingest_bd.update_state({}, ok, now)
    assert st["last_success_utc"] == "2026-11-24T12:00:00Z"
    assert st["last_new_row_utc"] == "2026-11-24T12:00:00Z"
    assert st["newest_post_published_at"] == "2026-11-24T10:00:00Z"
    assert st["consecutive_failures"] == 0

    later = now + timedelta(hours=2)
    bad = {"feeds": {PRIMARY["id"]: {"ok": False, "new_rows": 0, "error": "URLError"}},
           "items_seen": 0, "total_rows": 30, "pending_extract": 0}
    st = ingest_bd.update_state(st, bad, later)
    assert st["last_success_utc"] == "2026-11-24T12:00:00Z"  # unchanged
    assert st["consecutive_failures"] == 1
    assert st["last_error"] == "URLError"
    assert st["last_run_utc"] == "2026-11-24T14:00:00Z"


def test_main_exits_nonzero_when_primary_feed_fails(db, monkeypatch):
    def down(url=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(ingest_bd, "fetch_feed", down)
    assert ingest_bd.main([]) == 1


def test_repair_gives_up_after_max_attempts(db, monkeypatch):
    item = {"url": "https://www.bdoutdoors.com/forums/threads/t.5/", "title": "t",
            "author": None, "published_at": datetime(2026, 11, 1, tzinfo=UTC),
            "raw_text": "excerpt ... Read more"}
    ingest_bd.upsert_source(db, item, datetime.now(UTC))
    db.commit()
    calls = []
    monkeypatch.setattr(ingest_bd, "fetch_thread_body", lambda url: calls.append(url))
    monkeypatch.setattr(ingest_bd.time, "sleep", lambda s: None)
    for _ in range(ingest_bd.TRUNC_MAX_ATTEMPTS_PER_ROW + 2):
        ingest_bd.repair_truncated(db)
    assert len(calls) == ingest_bd.TRUNC_MAX_ATTEMPTS_PER_ROW
