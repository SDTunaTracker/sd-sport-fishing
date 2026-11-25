"""Tests for scraper.paddies.boat_reports (forum trip reports -> per-boat summaries)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.paddies import boat_reports as br
from scraper.paddies import extract, feeds, ingest_bd

BODY = ("Just got back from a 2 day trip on the PQ. 24 anglers, 11 yellowfin to 50 lb. "
        "Captain bobby and the deckhands really made the whole experience a plus. "
        "Cook dave fed us well. Will look to get on again next year.")

KNOWN = {"Pacific Queen": ["Fisherman's Landing"], "New Lo-An": ["Point Loma Sportfishing"],
         "Patriot": ["H&M Landing", "Newport Landing"]}


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    # Claude is stubbed in every test; the runners only check the key is set.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    p = tmp_path / "tracker.db"
    c = sqlite3.connect(p)
    c.executescript("""
        CREATE TABLE trips (boat TEXT, landing TEXT, date TEXT, trip_length TEXT,
                            anglers INTEGER, full_catch TEXT);
        CREATE TABLE boats (name TEXT, landing TEXT);
        INSERT INTO trips VALUES ('Pacific Queen', 'Fisherman''s Landing', '2026-11-10', '2 Day', 24,
                                  '{"Yellowfin": 11}');
        INSERT INTO boats VALUES ('New Lo-An', 'Point Loma Sportfishing');
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(br, "TRACKER_DB_PATH", p)
    return p


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "paddies.db"
    conn = ingest_bd.open_db(p)
    ingest_bd.ensure_schema(conn)
    conn.close()
    return p


def add_source(db, sid, feed_id, title="Pacific Queen 2 day 11/8-11/10", body=BODY,
               published="2026-11-10T20:00:00Z", fetched="2026-11-11T00:00:00Z", truncated=0):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO paddy_sources (id, source, feed_id, url, title, author, published_at, "
              "fetched_at, raw_text, truncated) VALUES (?, 'bdoutdoors', ?, ?, ?, 'someone', ?, ?, ?, ?)",
              (sid, feed_id, f"https://example.test/threads/{sid}/", title, published, fetched,
               body, truncated))
    c.commit()
    c.close()


def model_entry(**over):
    e = {"boat_raw": "PQ", "boat": "Pacific Queen", "trip_date": "2026-11-08",
         "trip_length": "2 Day", "overall": 2, "captain": 2, "crew": 2, "galley": 1,
         "bunks": None, "fish_finding": 1, "would_rebook": True,
         "quotes": {"overall": "really made the whole experience a plus",
                    "captain": "Captain bobby and the deckhands",
                    "crew": "the deckhands really made the whole experience a plus",
                    "galley": "Cook dave fed us well",
                    "fish_finding": "11 yellowfin to 50 lb",
                    "would_rebook": "Will look to get on again next year"},
         "catch_summary": "11 YFT to 50 lb for 24 anglers", "tackle": ["40-50 lb fluoro"],
         "spots": ["Colonet"]}
    e.update(over)
    return e


# ------------------------------------------------------------------ feeds

def test_new_feeds_are_boat_reports_and_kept_out_of_paddy_extract():
    assert set(feeds.feed_ids("boat_reports")) == {"bd-socal-sportboats", "bd-long-range"}
    assert not set(extract.PADDY_FEED_IDS) & set(feeds.feed_ids("boat_reports"))
    assert "bd-socal-offshore" in extract.PADDY_FEED_IDS


def test_paddy_extract_skips_boat_report_posts(db, monkeypatch):
    add_source(db, "a" * 40, "bd-socal-sportboats")
    add_source(db, "b" * 40, "bd-socal-offshore", title="paddy report")
    seen = []
    monkeypatch.setattr(extract, "DB_PATH", db)
    monkeypatch.setattr(extract, "extract_one",
                        lambda conn, row, gaz, dry_run=False: seen.append(row["id"]) or
                        {"ok": True, "mentions": 0, "unresolved": 0})
    monkeypatch.setattr(extract, "REQUEST_SLEEP", 0)
    extract.run()
    assert seen == ["b" * 40]


# ------------------------------------------------------------------ matching

def test_match_boat_prefers_known_model_choice_then_normalised():
    assert br.match_boat("Pacific Queen", "PQ", KNOWN) == "Pacific Queen"
    assert br.match_boat(None, "new lo an", KNOWN) == "New Lo-An"
    assert br.match_boat("Made Up Boat", "Made Up", KNOWN) is None


def test_match_trip_finds_landing_count_by_return_date(tracker):
    m = br.match_trip("Pacific Queen", "2026-11-08", "2 Day")
    assert m["date"] == "2026-11-10" and m["anglers"] == 24 and m["catch"] == {"Yellowfin": 11}
    assert br.match_trip("Pacific Queen", "2026-10-01", "2 Day") is None


def test_load_known_boats_reads_trips_and_boats(tracker):
    known = br.load_known_boats(tracker)
    assert "Pacific Queen" in known and "New Lo-An" in known


# ------------------------------------------------------------------ validation

def test_validate_keeps_quoted_scores():
    v = br.validate_entry(model_entry(), BODY, "2026-11-10T20:00:00Z", KNOWN)
    assert v["boat"] == "Pacific Queen"
    assert v["captain"] == 2 and v["galley"] == 1 and v["would_rebook"] == 1
    assert v["bunks"] is None
    assert v["quotes"]["would_rebook"].startswith("Will look")


def test_validate_drops_scores_whose_quote_is_not_in_the_post():
    e = model_entry(bunks=-2, quotes={**model_entry()["quotes"], "bunks": "bunks were filthy"})
    v = br.validate_entry(e, BODY, "2026-11-10T20:00:00Z", KNOWN)
    assert v["bunks"] is None and "bunks" not in v["quotes"]


def test_validate_drops_unquoted_rebook_and_bad_values():
    q = dict(model_entry()["quotes"])
    del q["would_rebook"]
    v = br.validate_entry(model_entry(quotes=q, crew=5, captain=True), BODY, None, KNOWN)
    assert v["would_rebook"] is None and v["crew"] is None and v["captain"] is None


def test_validate_rejects_implausible_trip_date_and_length():
    v = br.validate_entry(model_entry(trip_date="2026-12-25", trip_length="Forever"),
                          BODY, "2026-11-10T20:00:00Z", KNOWN)
    assert v["trip_date"] is None and v["trip_length"] is None


def test_long_quotes_are_clipped_to_15_words():
    long_q = "Captain bobby and the deckhands really made the whole experience a plus. Cook dave fed us well."
    v = br.validate_entry(model_entry(quotes={"captain": long_q}), BODY, None, KNOWN)
    assert len(v["quotes"]["captain"].rstrip("…").split()) == 15


# ------------------------------------------------------------------ pending

def test_pending_rows_filters_feed_truncation_and_stale_bumps(db):
    add_source(db, "1" * 40, "bd-socal-sportboats")
    add_source(db, "2" * 40, "bd-socal-offshore")
    add_source(db, "3" * 40, "bd-long-range", truncated=1)
    add_source(db, "4" * 40, "bd-long-range", published="2010-10-01T00:00:00Z")
    conn = br.open_db(db)
    assert [r["id"] for r in br.pending_rows(conn)] == ["1" * 40]
    conn.close()


# ------------------------------------------------------------------ process + export

def test_process_row_stores_entries_and_exports(db, tracker, monkeypatch):
    add_source(db, "5" * 40, "bd-socal-sportboats")
    add_source(db, "6" * 40, "bd-long-range", title="Gear question")
    answers = {"5" * 40: {"is_trip_report": True, "boats": [model_entry()]},
               "6" * 40: {"is_trip_report": False, "boats": []}}
    monkeypatch.setattr(br, "build_prompt", lambda row, known: row["id"])
    monkeypatch.setattr(br, "call_claude", lambda prompt: answers[prompt])
    monkeypatch.setattr(br, "REQUEST_SLEEP", 0)

    stats = br.run(limit=None, db_path=db)
    assert stats == {"posts": 2, "ok": 2, "failed": 0, "entries": 1, "pending_after": 0}

    conn = br.open_db(db)
    statuses = dict(conn.execute("SELECT source_id, status FROM boat_report_runs"))
    assert statuses == {"5" * 40: "ok", "6" * 40: "not_report"}
    data = br.build_export(conn, now=datetime(2026, 11, 24, tzinfo=timezone.utc))
    conn.close()

    pq = data["boats"]["Pacific Queen"]
    assert pq["report_count"] == 1 and pq["landing"] == "Fisherman's Landing"
    assert pq["aspects"]["captain"] == {"pos": 1, "mixed": 0, "neg": 0}
    assert pq["rebook"] == {"yes": 1, "no": 0}
    rep = pq["reports"][0]
    assert rep["url"].startswith("https://") and rep["landing_count"]["anglers"] == 24
    assert "author" not in rep and "body" not in rep          # never republish the post
    assert "bunks" not in rep["scores"]


def test_failed_posts_retry_then_stop(db, tracker, monkeypatch):
    add_source(db, "7" * 40, "bd-socal-sportboats")
    monkeypatch.setattr(br, "build_prompt", lambda row, known: "p")
    monkeypatch.setattr(br, "call_claude", lambda prompt: None)
    monkeypatch.setattr(br, "REQUEST_SLEEP", 0)
    for _ in range(br.MAX_ATTEMPTS):
        assert br.run(limit=None, db_path=db)["failed"] == 1
    assert br.run(limit=None, db_path=db)["posts"] == 0


def test_record_health_keeps_other_keys(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps({"last_success_utc": "x"}))
    br.record_health({"posts": 2, "failed": 0, "pending_after": 5}, sp)
    st = json.loads(sp.read_text())
    assert st["last_success_utc"] == "x" and st["boat_reports_pending"] == 5
    assert st["boat_reports_last_success_utc"]


def test_report_tool_schema_requires_quotes_and_scores():
    item = br.REPORT_TOOL["input_schema"]["properties"]["boats"]["items"]
    for k in (*br.ASPECTS, "would_rebook", "quotes"):
        assert k in item["required"]


def test_short_posts_skip_claude_and_undated_asides_are_dropped(db, tracker, monkeypatch):
    add_source(db, "8" * 40, "bd-socal-sportboats", body="pics")
    add_source(db, "9" * 40, "bd-socal-sportboats")
    aside = model_entry(boat_raw="Tribute", boat=None, trip_date=None, trip_length=None)
    calls = []
    monkeypatch.setattr(br, "build_prompt", lambda row, known: row["id"])
    monkeypatch.setattr(br, "call_claude", lambda p: calls.append(p) or
                        {"is_trip_report": True, "boats": [model_entry(), aside]})
    monkeypatch.setattr(br, "REQUEST_SLEEP", 0)
    stats = br.run(limit=None, db_path=db)
    assert calls == ["9" * 40] and stats["entries"] == 1


# ------------------------------------------------------------------ confidence, signals, what's working

SIG_BODY = BODY + " Shearwaters were brutal on every bait. Water was 72 degrees and blue. Bite was at grey light."


def model_signals(**over):
    sig = {"bird_pressure": 3, "bait_type": "sardine", "bait_size_in": None, "bait_quality": None,
           "water_temp_f": 72, "water_color": "blue", "bite_windows": ["grey_light"],
           "size_grade": "YFT 20-50 lb",
           "evidence": {"bird_pressure": "Shearwaters were brutal on every bait",
                        "bait_type": "sardine is made up",
                        "water_temp_f": "Water was 72 degrees",
                        "water_color": "72 degrees and blue",
                        "bite_windows": "Bite was at grey light"}}
    sig.update(over)
    return sig


def test_match_confidence_levels():
    assert br.match_confidence("Pacific Queen", "Pacific Queen", "Pacific Queen", None) == 0.95
    assert br.match_confidence("Pacific Queen", "PQ", "Pacific Queen", None) == 0.8
    assert br.match_confidence("Pacific Queen", "PQ", "Pacific Queen", {"date": "x"}) == 0.95
    assert br.match_confidence(None, "Mystery", None, None) == 0.0


def test_signals_need_a_matching_quote_and_valid_range():
    sig = br.validate_signals(model_signals(water_temp_f=140), SIG_BODY)
    assert sig["bird_pressure"] == 3 and sig["water_color"] == "blue"
    assert sig["bite_windows"] == ["grey_light"]
    assert sig["bait_type"] is None            # quote not in the post
    assert sig["water_temp_f"] is None         # out of range
    assert "bait_type" not in sig["evidence"]


def _run_with(db, monkeypatch, answers):
    monkeypatch.setattr(br, "build_prompt", lambda row, known: row["id"])
    monkeypatch.setattr(br, "call_claude", lambda prompt: answers[prompt])
    monkeypatch.setattr(br, "REQUEST_SLEEP", 0)
    return br.run(limit=None, db_path=db)


def test_signals_stored_for_research_and_not_in_public_export(db, tracker, monkeypatch, tmp_path):
    add_source(db, "a1" * 20, "bd-socal-sportboats", body=SIG_BODY)
    _run_with(db, monkeypatch, {"a1" * 20: {"is_trip_report": True, "boats": [
        model_entry(bait="green sardine, lively", conditions="72F blue, birds bad",
                    signals=model_signals())]}})
    conn = br.open_db(db)
    sig = conn.execute("SELECT * FROM forum_signals").fetchone()
    assert sig["bird_pressure"] == 3 and json.loads(sig["bite_windows"]) == ["grey_light"]
    pub = json.dumps(br.build_export(conn, now=datetime(2026, 11, 24, tzinfo=timezone.utc)))
    conn.close()
    assert "bird_pressure" not in pub and "water_temp" not in pub
    n = br.write_signals_csv(tmp_path / "sig.csv", db_path=db)
    assert n == 1 and "bird_pressure" in (tmp_path / "sig.csv").read_text().splitlines()[0]


def test_low_confidence_boats_are_not_published(db, tracker, monkeypatch):
    add_source(db, "b1" * 20, "bd-socal-sportboats")
    _run_with(db, monkeypatch, {"b1" * 20: {"is_trip_report": True, "boats": [model_entry()]}})
    conn = br.open_db(db)
    conn.execute("UPDATE forum_boat_reports SET match_confidence = 0.5")
    data = br.build_export(conn, now=datetime(2026, 11, 24, tzinfo=timezone.utc))
    conn.close()
    assert data["boats"] == {} and data["label"] == "From BloodyDecks trip reports"


def test_whats_working_groups_by_trip_type_with_recency(db, tracker, monkeypatch):
    add_source(db, "c1" * 20, "bd-socal-sportboats", title="PQ 2 day", published="2026-11-20T00:00:00Z")
    add_source(db, "c2" * 20, "bd-socal-sportboats", title="PQ again", published="2026-11-21T00:00:00Z")
    add_source(db, "c3" * 20, "bd-socal-sportboats", title="Old 1/2 day", published="2026-10-15T00:00:00Z")
    e2 = lambda d: model_entry(trip_date=d, bait="sardine", tackle=["40 lb fluoro", "#1 circle"])
    half = model_entry(trip_date="2026-10-14", trip_length="1/2 Day", tackle=["dropper loop"])
    _run_with(db, monkeypatch, {"c1" * 20: {"is_trip_report": True, "boats": [e2("2026-11-18")]},
                                "c2" * 20: {"is_trip_report": True, "boats": [e2("2026-11-19")]},
                                "c3" * 20: {"is_trip_report": True, "boats": [half]}})
    conn = br.open_db(db)
    ww = br.build_whats_working(conn, now=datetime(2026, 11, 24, tzinfo=timezone.utc))
    conn.close()
    multi = ww["classes"]["multi"]
    assert multi["report_count"] == 2 and multi["window_days"] == br.WW_WINDOW_DAYS
    assert multi["items"][0]["trip_date"] == "2026-11-19"
    assert multi["items"][0]["url"].startswith("https://")
    assert multi["top_spots"] == ["Colonet"]          # merged across both reports
    short = ww["classes"]["short"]                  # one old report -> wider window
    assert short["window_days"] == br.WW_FALLBACK_DAYS and short["report_count"] == 1
    assert ww["classes"]["long_range"]["items"] == []


def test_trip_class():
    assert br.trip_class("3/4 Day") == "short"
    assert br.trip_class("2.5 Day") == "multi"
    assert br.trip_class("10 Day") == "long_range"
    assert br.trip_class(None) is None


def test_missing_key_fails_fast_without_calls(db, tracker, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(br, "_client", None)
    add_source(db, "d1" * 20, "bd-socal-sportboats")
    monkeypatch.setattr(br, "call_claude", lambda p: pytest.fail("should not call Claude"))
    stats = br.run(limit=None, db_path=db)
    assert stats["failed"] == 1 and stats["pending_after"] == 1
    assert br._last_error == "ANTHROPIC_API_KEY is not set"


def test_run_stops_after_consecutive_failures(db, tracker, monkeypatch):
    for i in range(8):
        add_source(db, f"e{i}" * 20, "bd-socal-sportboats")
    calls = []
    monkeypatch.setattr(br, "build_prompt", lambda row, known: "p")
    monkeypatch.setattr(br, "call_claude", lambda p: calls.append(p))
    monkeypatch.setattr(br, "REQUEST_SLEEP", 0)
    stats = br.run(limit=None, db_path=db)
    assert len(calls) == extract.MAX_CONSECUTIVE_FAILURES == stats["failed"]


def test_paddy_extract_missing_key_and_streak(db, monkeypatch):
    for i in range(8):
        add_source(db, f"f{i}" * 20, "bd-socal-offshore", title="paddy")
    monkeypatch.setattr(extract, "DB_PATH", db)
    monkeypatch.setattr(extract, "REQUEST_SLEEP", 0)
    seen = []
    monkeypatch.setattr(extract, "extract_one", lambda conn, row, gaz, dry_run=False:
                        seen.append(1) or {"ok": False, "mentions": 0, "unresolved": 0})
    st = extract.run()
    assert len(seen) == extract.MAX_CONSECUTIVE_FAILURES and st["posts_failed"] == len(seen)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    seen.clear()
    st = extract.run()
    assert seen == [] and st["posts_failed"] == 8 and extract._last_error == "ANTHROPIC_API_KEY is not set"
