"""Tests for scraper.paddies.ingest_bd (parsers + idempotency)."""
from __future__ import annotations
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scraper.paddies import ingest_bd


SAMPLE_FEED = ("""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>SoCal Offshore</title>
    <item>
      <title>9 Mile paddies</title>
      <link>https://www.bdoutdoors.com/forums/threads/nine-mile-paddies.111/?utm_source=rss&amp;utm_medium=rss</link>
      <pubDate>Sat, 06 Sep 2026 12:34:56 +0000</pubDate>
      <dc:creator>angler_one</dc:creator>
      <content:encoded><![CDATA[<div class="bbWrapper">Ran out to the <b>9 mile bank</b> - saw a few paddies with rats on them.<br/>Also hit the <a href="x">182</a>. <img src="pic.jpg"/></div>]]></content:encoded>
    </item>
    <item>
      <title>Nothing to report</title>
      <link>https://www.bdoutdoors.com/forums/threads/nothing.112/</link>
      <pubDate>Sat, 06 Sep 2026 13:00:00 +0000</pubDate>
      <dc:creator>quiet_guy</dc:creator>
      <content:encoded><![CDATA[<div class="bbWrapper">Skunked. Back at the dock.</div>]]></content:encoded>
    </item>
    <item>
      <title>No body</title>
      <link>https://www.bdoutdoors.com/forums/threads/empty.113/</link>
      <pubDate>Sat, 06 Sep 2026 13:15:00 +0000</pubDate>
      <dc:creator>ghost</dc:creator>
      <content:encoded></content:encoded>
    </item>
  </channel>
</rss>
""").encode("utf-8")


def test_canonical_url_strips_utm():
    url = "https://x.com/t/foo?utm_source=rss&utm_medium=rss&keep=1"
    got = ingest_bd.canonical_url(url)
    assert "utm_" not in got
    assert "keep=1" in got


def test_canonical_url_no_change_when_no_params():
    url = "https://x.com/t/foo"
    assert ingest_bd.canonical_url(url) == url


def test_sha1_hex_deterministic():
    a = ingest_bd.sha1_hex("https://x.com/y")
    b = ingest_bd.sha1_hex("https://x.com/y")
    assert a == b and len(a) == 40


def test_strip_html_removes_tags_and_images():
    html = 'Hello <b>world</b> <img src="pic.jpg" alt="x"/> <a href="/foo">link</a> text.'
    got = ingest_bd.strip_html(html)
    assert "<" not in got and ">" not in got
    assert "pic.jpg" not in got
    assert "Hello" in got and "world" in got and "text." in got


def test_strip_html_preserves_line_breaks():
    html = "Line 1<br/>Line 2<br />Line 3</p>Paragraph 2"
    got = ingest_bd.strip_html(html)
    assert "Line 1\nLine 2\nLine 3" in got


def test_parse_feed_yields_items():
    items = list(ingest_bd.parse_feed(SAMPLE_FEED))
    # 2 usable items (the third has an empty body and is skipped)
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "9 Mile paddies"
    assert first["author"] == "angler_one"
    assert first["published_at"].tzinfo is not None
    assert first["published_at"].utcoffset().total_seconds() == 0
    assert "9 mile bank" in first["raw_text"]
    assert "utm_" not in first["url"]


def test_parse_feed_skips_empty_body():
    items = list(ingest_bd.parse_feed(SAMPLE_FEED))
    urls = [i["url"] for i in items]
    assert not any("empty.113" in u for u in urls)


def test_upsert_and_idempotency(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    try:
        ingest_bd.ensure_schema(conn)
        items = list(ingest_bd.parse_feed(SAMPLE_FEED))
        now = datetime.now(timezone.utc)
        assert ingest_bd.upsert_source(conn, items[0], now) is True
        assert ingest_bd.upsert_source(conn, items[0], now) is False  # no dup
        assert ingest_bd.upsert_source(conn, items[1], now) is True
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM paddy_sources").fetchone()[0]
        assert n == 2
        pending = conn.execute(
            "SELECT COUNT(*) FROM paddy_sources WHERE extracted=0"
        ).fetchone()[0]
        assert pending == 2
    finally:
        conn.close()


def test_is_truncated():
    assert ingest_bd.is_truncated("some body ... Read more") is True
    assert ingest_bd.is_truncated("some body ... Read more   \n\n") is True
    assert ingest_bd.is_truncated("some body ending normally.") is False
    assert ingest_bd.is_truncated("") is False


def test_migration_adds_truncated_and_backfills(tmp_path):
    """Old schema (no truncated col) migrates cleanly + backfills 'Read more' rows."""
    p = tmp_path / "t.db"
    conn = sqlite3.connect(p)
    # simulate the OLD schema (pre-migration)
    conn.executescript("""
        CREATE TABLE paddy_sources (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
            title TEXT, author TEXT, published_at TEXT NOT NULL,
            fetched_at TEXT NOT NULL, raw_text TEXT NOT NULL,
            extracted INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.execute("""INSERT INTO paddy_sources VALUES
        ('a','bdoutdoors','http://x/a','A',NULL,'2026-09-06T12:00:00+00:00',
         '2026-09-06T12:00:00+00:00','body A ends normally.',0)""")
    conn.execute("""INSERT INTO paddy_sources VALUES
        ('b','bdoutdoors','http://x/b','B',NULL,'2026-09-06T13:00:00+00:00',
         '2026-09-06T13:00:00+00:00','body B truncated... Read more',0)""")
    conn.commit()
    conn.close()

    conn = ingest_bd.open_db(p)
    ingest_bd.ensure_schema(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(paddy_sources)")}
    assert "truncated" in cols
    a_trunc = conn.execute("SELECT truncated FROM paddy_sources WHERE id='a'").fetchone()[0]
    b_trunc = conn.execute("SELECT truncated FROM paddy_sources WHERE id='b'").fetchone()[0]
    assert a_trunc == 0
    assert b_trunc == 1
    conn.close()


def test_busy_timeout_second_writer_waits(tmp_path):
    """
    A second connection with busy_timeout set should WAIT for a held writer
    lock, not immediately raise 'database is locked'.
    """
    import threading
    p = tmp_path / "lock.db"

    conn1 = ingest_bd.open_db(p)
    conn1.executescript("CREATE TABLE t (x INTEGER)")
    conn1.commit()

    conn1.isolation_level = None
    conn1.execute("BEGIN IMMEDIATE")
    conn1.execute("INSERT INTO t VALUES (1)")

    lock_error = []
    done = threading.Event()

    def writer2():
        try:
            c2 = ingest_bd.open_db(p)
            c2.execute("INSERT INTO t VALUES (2)")
            c2.commit()
            c2.close()
        except sqlite3.OperationalError as e:
            lock_error.append(str(e))
        finally:
            done.set()

    t = threading.Thread(target=writer2)
    t.start()
    time.sleep(0.5)
    assert not done.is_set(), "writer2 should still be waiting for the lock"
    assert not lock_error, "writer2 raised instead of waiting"

    conn1.execute("COMMIT")
    conn1.close()

    t.join(timeout=5)
    assert done.is_set(), "writer2 never finished after lock release"
    assert not lock_error, f"writer2 raised: {lock_error}"

    conn3 = sqlite3.connect(p)
    rows = sorted(r[0] for r in conn3.execute("SELECT x FROM t"))
    assert rows == [1, 2]
    conn3.close()


def test_consecutive_zero_runs_warning_after_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ingest_bd, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(ingest_bd, "STATE_PATH", tmp_path / "state.json")
    # empty feed (0 items)
    empty_feed = (b'<?xml version="1.0"?><rss version="2.0"><channel>'
                  b'<title>x</title></channel></rss>')
    monkeypatch.setattr(ingest_bd, "fetch_feed", lambda: empty_feed)
    # first zero-run: info only, no warning annotation
    ingest_bd.main()
    out = capsys.readouterr().out
    assert "::warning" not in out
    # second zero-run: emit warning annotation
    ingest_bd.main()
    out = capsys.readouterr().out
    assert "::warning" in out
    assert "consecutive" in out.lower()


def test_zero_run_counter_resets_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_bd, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(ingest_bd, "STATE_PATH", tmp_path / "state.json")
    empty_feed = (b'<?xml version="1.0"?><rss version="2.0"><channel>'
                  b'<title>x</title></channel></rss>')
    # zero run
    monkeypatch.setattr(ingest_bd, "fetch_feed", lambda: empty_feed)
    ingest_bd.main()
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["consecutive_zero_runs"] == 1
    # non-zero run: counter resets
    monkeypatch.setattr(ingest_bd, "fetch_feed", lambda: SAMPLE_FEED)
    ingest_bd.main()
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["consecutive_zero_runs"] == 0
    assert st["last_items_seen"] == 2


def test_run_end_to_end_uses_mock_feed(tmp_path, monkeypatch):
    """Full run() with a mocked fetch_feed — verifies stats + schema install."""
    db = tmp_path / "t.db"
    monkeypatch.setattr(ingest_bd, "DB_PATH", db)
    monkeypatch.setattr(ingest_bd, "fetch_feed", lambda: SAMPLE_FEED)
    stats = ingest_bd.run()
    assert stats["items_seen"] == 2
    assert stats["new_rows"] == 2
    assert stats["total_rows"] == 2
    # second run: idempotent
    stats2 = ingest_bd.run()
    assert stats2["items_seen"] == 2
    assert stats2["new_rows"] == 0
    assert stats2["total_rows"] == 2
