"""Tests for scraper.paddies.replies (reports inside BloodyDecks thread replies) and photo links."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.paddies import boat_reports as br
from scraper.paddies import extract, feeds, ingest_bd as bd
from scraper.paddies import replies as rp

FIX = Path(__file__).parent / "fixtures" / "bd_replies"
NOW = datetime(2026, 11, 26, 5, 0, tzinfo=timezone.utc)
FORUM = "https://www.bdoutdoors.com/forums/forum/southern-california-offshore-fishing-reports/"
YFT = "https://www.bdoutdoors.com/forums/threads/yellowfin-november-24th.872655/"
CAT = "https://www.bdoutdoors.com/forums/threads/cat-east-end-yellowfin.872635/"


def page(name):
    return (FIX / name).read_bytes()


@pytest.fixture
def conn(tmp_path):
    c = bd.open_db(tmp_path / "paddies.db")
    c.row_factory = sqlite3.Row
    rp.ensure_schema(c)
    yield c
    c.close()


def fetcher(calls):
    def f(url):
        calls.append(url)
        if url == FORUM:
            return page("listing_socal_offshore.html")
        if url == YFT:
            return page("thread_yellowfin.html")
        if url == CAT:
            return page("thread_cat_east_end.html")
        return b"<html><body></body></html>"
    return f


# ------------------------------------------------------------------ parsing

def test_listing_has_reply_counts_and_pinned_threads():
    ts = list(bd.parse_listing(page("listing_socal_offshore.html")))
    by = {t["url"]: t for t in ts}
    assert by[YFT]["replies"] == 22 and not by[YFT]["sticky"]
    pinned = [t["title"] for t in ts if t["sticky"]]
    assert any("Bait Reports" in t for t in pinned)


def test_count_text():
    assert bd._count_text("22") == 22 and bd._count_text("1,204") == 1204
    assert bd._count_text("1.2K") == 1200 and bd._count_text("") == 0


def test_thread_page_posts_without_quoted_text():
    posts = rp.parse_thread_page(page("thread_yellowfin.html"))
    assert len(posts) == 23 and posts[0]["post_id"] < posts[1]["post_id"]
    assert all(p["published_at"] and p["published_at"].tzinfo for p in posts)
    op_text = posts[0]["text"][:60]
    assert not any(op_text in p["text"] for p in posts[1:])       # quotes stripped


def test_photo_links_are_absolute_and_deduped():
    html = ('<a href="https://www.bdoutdoors.com/forums/attachments/img_8315-jpeg.1742545/">View</a>'
            '<img src="/forums/attachments/a-jpg.12/"> '
            'https://www.bdoutdoors.com/forums/attachments/img_8315-jpeg.1742545/')
    assert bd.extract_photos(html) == [
        "https://www.bdoutdoors.com/forums/attachments/img_8315-jpeg.1742545/",
        "https://www.bdoutdoors.com/forums/attachments/a-jpg.12/"]
    posts = rp.parse_thread_page(page("thread_cat_east_end.html"))
    assert posts[0]["photos"] and all("/forums/attachments/" in u for u in posts[0]["photos"])


def test_report_filter_drops_pleasantries():
    assert rp.looks_like_report("Five miles off Pt Loma, 5 pound yellowfin like piranha all morning.")
    assert not rp.looks_like_report("Great report! Thanks for sharing the yellowfin pics, nice work man.")
    assert not rp.looks_like_report("lol")


def test_rss_items_carry_photo_links():
    xml = (b'<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
           b'<item><title>T</title><link>https://www.bdoutdoors.com/forums/threads/t.1/</link>'
           b'<pubDate>Tue, 24 Nov 2026 10:00:00 +0000</pubDate><content:encoded><![CDATA['
           b'Yellowfin at the 302 <a href="https://www.bdoutdoors.com/forums/attachments/x-jpg.9/">View attachment</a>'
           b']]></content:encoded></item></channel></rss>')
    item = next(bd.parse_feed(xml))
    assert item["photos"] == ["https://www.bdoutdoors.com/forums/attachments/x-jpg.9/"]


# ------------------------------------------------------------------ run

def test_run_stores_report_replies_as_their_own_rows(conn):
    calls = []
    bd.upsert_source(conn, {"url": CAT, "title": "Cat East End Yellowfin", "author": "x",
                            "published_at": NOW, "raw_text": "op"}, NOW, feed_id="bd-socal-offshore")
    st = rp.run(conn, feed_ids=["bd-socal-offshore"], now=NOW, fetcher=fetcher(calls), sleep=lambda s: None)
    assert st["error"] is None and st["listings"] == 1 and st["replies_stored"] >= 3
    rows = conn.execute("SELECT * FROM paddy_sources WHERE reply_to IS NOT NULL").fetchall()
    assert rows and all(r["feed_id"] == "bd-socal-offshore" for r in rows)
    yft = [r for r in rows if r["reply_to"] == YFT]
    assert yft and all(r["url"].startswith(YFT + "post-") for r in yft)
    assert all(r["raw_text"].startswith('Reply in the thread "') for r in rows)
    assert all(r["extracted"] == 0 for r in rows)                # the paddy extractor will read them
    op = conn.execute("SELECT photos FROM paddy_sources WHERE id = ?", (bd.sha1_hex(CAT),)).fetchone()
    assert op["photos"] and json.loads(op["photos"])            # first post gained its photo links

    calls.clear()
    st2 = rp.run(conn, feed_ids=["bd-socal-offshore"], now=NOW, fetcher=fetcher(calls), sleep=lambda s: None)
    assert calls == [FORUM] and st2["replies_stored"] == 0      # nothing new: listing only


def test_page_cap_and_block_stop_politely(conn):
    calls = []
    st = rp.run(conn, feed_ids=["bd-socal-offshore"], now=NOW, max_pages=1,
                fetcher=fetcher(calls), sleep=lambda s: None)
    assert st["pages"] == 1 and len(calls) == 2

    def blocked(url):
        if url == FORUM:
            return page("listing_socal_offshore.html")
        raise rp.Blocked(f"HTTP 429 on {url}")
    st = rp.run(conn, feed_ids=["bd-socal-offshore"], now=NOW, fetcher=blocked, sleep=lambda s: None)
    assert st["blocked"] and "429" in st["error"]


def test_old_threads_and_old_replies_are_skipped(conn):
    calls = []
    later = datetime(2027, 3, 1, tzinfo=timezone.utc)
    st = rp.run(conn, feed_ids=["bd-socal-offshore"], now=later, fetcher=fetcher(calls), sleep=lambda s: None)
    assert st["threads_active"] == 0 and calls == [FORUM]


# ------------------------------------------------------------------ feeds + exports

def test_trip_planning_and_kayak_go_to_the_paddy_extractor():
    for fid in ("bd-socal-trip-planning", "bd-kayak"):
        f = feeds.get_feed(fid)
        assert f and f["enabled"] and f["kind"] == "paddies" and f["initial_backfill_days"] <= 90
        assert fid in extract.PADDY_FEED_IDS


def test_boat_report_export_counts_photos_and_flags_replies(tmp_path, monkeypatch):
    p = tmp_path / "paddies.db"
    c = bd.open_db(p)
    bd.ensure_schema(c)
    c.close()
    conn = br.open_db(p)
    photos = json.dumps(["https://www.bdoutdoors.com/forums/attachments/a-jpg.1/",
                         "https://www.bdoutdoors.com/forums/attachments/b-jpg.2/"])
    conn.execute("INSERT INTO paddy_sources (id, source, feed_id, url, title, published_at, fetched_at, "
                 "raw_text, photos, reply_to) VALUES ('r1', 'bdoutdoors', 'bd-socal-sportboats', "
                 "'https://www.bdoutdoors.com/forums/threads/pq.1/post-9', 'PQ 2 day', "
                 "'2026-11-20T00:00:00+00:00', '2026-11-20T01:00:00+00:00', 'x', ?, "
                 "'https://www.bdoutdoors.com/forums/threads/pq.1/')", (photos,))
    conn.execute("INSERT INTO forum_boat_reports (source_id, feed_id, boat_raw, boat, landing, trip_date, "
                 "trip_length, quotes, tackle, spots, bait, match_confidence, extracted_at) VALUES "
                 "('r1', 'bd-socal-sportboats', 'PQ', 'Pacific Queen', 'Fisherman''s Landing', '2026-11-19', "
                 "'2 Day', '{}', '[\"40 lb fluoro\"]', '[]', 'sardine', 1.0, '2026-11-20T02:00:00Z')")
    conn.commit()
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)
    rep = br.build_export(conn, now=now)["boats"]["Pacific Queen"]["reports"][0]
    assert rep["photos"] == 2 and rep["reply"] is True
    item = br.build_whats_working(conn, now=now)["classes"]["multi"]["items"][0]
    assert item["photos"] == 2 and item["reply"] is True and item["source"] == "forum"
    conn.close()


def test_a_stored_reply_does_not_hide_a_new_feeds_first_backfill(conn):
    bd.upsert_source(conn, {"url": YFT + "post-1", "title": "t", "author": "a", "published_at": NOW,
                            "raw_text": "r", "reply_to": YFT}, NOW, feed_id="bd-kayak")
    assert bd._newest_published(conn, "bd-kayak") is None
    bd.upsert_source(conn, {"url": YFT, "title": "t", "author": "a", "published_at": NOW,
                            "raw_text": "op"}, NOW, feed_id="bd-kayak")
    assert bd._newest_published(conn, "bd-kayak") == NOW
