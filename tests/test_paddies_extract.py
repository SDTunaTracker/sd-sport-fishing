"""Tests for scraper.paddies.extract — validation + 6 fixture posts."""
from __future__ import annotations
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scraper.paddies import extract as ex
from scraper.paddies import ingest_bd


# ---------------------------------------------------------------------
# Gazetteer loading
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def gaz():
    return ex.load_gazetteer()


def test_gazetteer_has_known_ids(gaz):
    for i in ("catalina", "san-clemente-island", "9-mile-bank",
              "coronado-islands", "cortes-bank", "bishop-rock",
              "43-fathom-spot", "the-corner", "182", "the-worm"):
        assert i in gaz["valid_ids"], f"missing valid id: {i}"


def test_gazetteer_excludes_admin(gaz):
    # Any bracketed / Area N.N slug should NOT be a valid target
    admin_ish = [i for i in gaz["valid_ids"] if i.startswith("area-") or "boundary" in i]
    assert not admin_ish, f"admin leaked into valid_ids: {admin_ish[:5]}"


def test_gazetteer_prompt_lines_nonempty(gaz):
    assert len(gaz["prompt_lines"]) > 1000
    assert "9-mile-bank" in gaz["prompt_lines"]


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

def test_validate_unknown_bank_becomes_null(gaz):
    v = ex.validate_mention(
        {"bank": "no-such-place", "route": [], "species": [], "confidence": 0.5, "quote": "x"},
        gaz["valid_ids"], "src1",
    )
    assert v["bank"] is None


def test_validate_species_subset(gaz):
    v = ex.validate_mention(
        {"bank": "182", "route": [], "species": ["yellowtail", "wahoo", "DORADO"],
         "confidence": 0.9, "quote": "x"},
        gaz["valid_ids"], "src1",
    )
    got = json.loads(v["species_json"])
    assert "wahoo" not in got
    assert set(got) == {"yellowtail", "dorado"}


def test_validate_route_filters_unknowns(gaz):
    v = ex.validate_mention(
        {"bank": None, "route": ["182", "no-such", "312", "209"], "species": [],
         "confidence": 0.5, "quote": "x"},
        gaz["valid_ids"], "src1",
    )
    assert json.loads(v["route_json"]) == ["182", "312", "209"]


def test_validate_confidence_clamped(gaz):
    hi = ex.validate_mention({"bank": None, "route": [], "species": [],
                              "confidence": 1.5, "quote": "x"}, gaz["valid_ids"], "s")
    lo = ex.validate_mention({"bank": None, "route": [], "species": [],
                              "confidence": -0.2, "quote": "x"}, gaz["valid_ids"], "s")
    assert hi["confidence"] == 1.0
    assert lo["confidence"] == 0.0


def test_validate_bad_date(gaz):
    v = ex.validate_mention({"bank": None, "trip_date": "yesterday", "route": [],
                             "species": [], "confidence": 0.5, "quote": "x"},
                            gaz["valid_ids"], "s")
    assert v["trip_date"] is None


def test_validate_non_dict_returns_none(gaz):
    assert ex.validate_mention("not-a-dict", gaz["valid_ids"], "s") is None


# ---------------------------------------------------------------------
# 6 fixture posts + expected-mentions round-trip
# ---------------------------------------------------------------------

FIXTURES = [
    # (a) "didn't see any kelp" — negative paddy count
    {
        "post": {
            "id": "fix-a", "url": "http://x/a", "title": "A",
            "published_at": "2026-09-06T12:00:00+00:00",
            "raw_text": "Ran to the 182 today. Didn't see any kelp. Home empty."
        },
        "claude_response": [{
            "trip_date": "2026-09-06", "bank": "182", "route": [],
            "paddy_count": 0, "holding": False, "species": [],
            "water_temp_f": None, "confidence": 0.9,
            "quote": "Didn't see any kelp."
        }],
    },
    # (b) loop route of 4 ids
    {
        "post": {
            "id": "fix-b", "url": "http://x/b", "title": "B",
            "published_at": "2026-09-06T13:00:00+00:00",
            "raw_text": "Ran 182 to 181 to 312 to 209. Paddies at the 312 with rats."
        },
        "claude_response": [{
            "trip_date": "2026-09-06", "bank": "312",
            "route": ["182", "181", "312", "209"],
            "paddy_count": 3, "holding": True, "species": ["yellowtail"],
            "water_temp_f": None, "confidence": 0.85,
            "quote": "Paddies at the 312 with rats."
        }],
    },
    # (c) no paddy language at all -> empty array
    {
        "post": {
            "id": "fix-c", "url": "http://x/c", "title": "C",
            "published_at": "2026-09-06T14:00:00+00:00",
            "raw_text": "Rockfished the coast. Full limits of reds."
        },
        "claude_response": [],
    },
    # (d) "10 to 15 paddies... all dry"
    {
        "post": {
            "id": "fix-d", "url": "http://x/d", "title": "D",
            "published_at": "2026-09-06T15:00:00+00:00",
            "raw_text": "Saw 10 to 15 paddies working east of the Corner today. All dry."
        },
        "claude_response": [{
            "trip_date": "2026-09-06", "bank": "the-corner", "route": [],
            "paddy_count": 12, "holding": False, "species": [],
            "water_temp_f": None, "confidence": 0.9,
            "quote": "10 to 15 paddies working east of the Corner today. All dry."
        }],
    },
    # (e) simple: paddy at the 43 with YT
    {
        "post": {
            "id": "fix-e", "url": "http://x/e", "title": "E",
            "published_at": "2026-09-06T16:00:00+00:00",
            "raw_text": "Popped a nice YT off a paddy at the 43. Water was 68F."
        },
        "claude_response": [{
            "trip_date": "2026-09-06", "bank": "43-fathom-spot", "route": [],
            "paddy_count": 1, "holding": True, "species": ["yellowtail"],
            "water_temp_f": 68.0, "confidence": 0.95,
            "quote": "Popped a nice YT off a paddy at the 43."
        }],
    },
    # (f) unknown bank id from Claude -> normalized to null
    {
        "post": {
            "id": "fix-f", "url": "http://x/f", "title": "F",
            "published_at": "2026-09-06T17:00:00+00:00",
            "raw_text": "Fished the Mystery Reef. A few paddies, no bites."
        },
        "claude_response": [{
            "trip_date": "2026-09-06", "bank": "mystery-reef", "route": [],
            "paddy_count": 3, "holding": False, "species": [],
            "water_temp_f": None, "confidence": 0.4,
            "quote": "Fished the Mystery Reef. A few paddies, no bites."
        }],
    },
]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    # seed all fixture sources so extract_one can operate on rows
    for fx in FIXTURES:
        row = fx["post"]
        conn.execute("""
            INSERT INTO paddy_sources
                (id, source, url, title, author, published_at, fetched_at, raw_text, extracted)
            VALUES (?, 'bdoutdoors', ?, ?, NULL, ?, ?, ?, 0)
        """, (row["id"], row["url"], row["title"], row["published_at"],
              row["published_at"], row["raw_text"]))
    conn.commit()
    yield conn, p
    conn.close()


def _run_fixture(conn, gaz, fx):
    """Simulate extract_one but with a mocked Claude call."""
    with patch("scraper.paddies.extract.call_claude",
               return_value=fx["claude_response"]):
        row = conn.execute(
            "SELECT id, url, title, author, published_at, raw_text "
            "FROM paddy_sources WHERE id = ?", (fx["post"]["id"],)
        ).fetchone()
        return ex.extract_one(conn, row, gaz)


def test_fixture_a_zero_kelp(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[0])
    assert r["ok"] and r["mentions"] == 1
    m = conn.execute("SELECT * FROM paddy_mentions WHERE source_id='fix-a'").fetchone()
    assert m["bank"] == "182"
    assert m["paddy_count"] == 0
    assert m["holding"] == 0
    # source flipped to extracted=1
    ex_flag = conn.execute("SELECT extracted FROM paddy_sources WHERE id='fix-a'").fetchone()[0]
    assert ex_flag == 1


def test_fixture_b_loop_route(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[1])
    assert r["ok"] and r["mentions"] == 1
    m = conn.execute("SELECT * FROM paddy_mentions WHERE source_id='fix-b'").fetchone()
    route = json.loads(m["route_json"])
    assert route == ["182", "181", "312", "209"]
    assert m["bank"] == "312"


def test_fixture_c_no_paddy_language(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[2])
    assert r["ok"] and r["mentions"] == 0
    ex_flag = conn.execute("SELECT extracted FROM paddy_sources WHERE id='fix-c'").fetchone()[0]
    assert ex_flag == 1  # still marked extracted per spec


def test_fixture_d_ten_to_fifteen_dry(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[3])
    assert r["ok"] and r["mentions"] == 1
    m = conn.execute("SELECT * FROM paddy_mentions WHERE source_id='fix-d'").fetchone()
    assert m["paddy_count"] == 12
    assert m["holding"] == 0
    assert m["bank"] == "the-corner"


def test_fixture_e_yt_on_43(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[4])
    assert r["ok"] and r["mentions"] == 1
    m = conn.execute("SELECT * FROM paddy_mentions WHERE source_id='fix-e'").fetchone()
    assert m["bank"] == "43-fathom-spot"
    assert m["water_temp_f"] == 68.0
    assert json.loads(m["species_json"]) == ["yellowtail"]


def test_fixture_f_unknown_bank_becomes_null(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[5])
    assert r["ok"] and r["mentions"] == 1
    m = conn.execute("SELECT * FROM paddy_mentions WHERE source_id='fix-f'").fetchone()
    assert m["bank"] is None            # unknown -> null
    assert r["unresolved"] == 1


# ---------------------------------------------------------------------
# Idempotency: re-extract same source deletes + reinserts
# ---------------------------------------------------------------------

def test_reextract_replaces_prior_mentions(db, gaz):
    conn, _ = db
    # first pass: 1 mention
    with patch("scraper.paddies.extract.call_claude",
               return_value=FIXTURES[4]["claude_response"]):
        row = conn.execute(
            "SELECT id, url, title, author, published_at, raw_text FROM paddy_sources WHERE id='fix-e'"
        ).fetchone()
        ex.extract_one(conn, row, gaz)
    first_count = conn.execute(
        "SELECT COUNT(*) FROM paddy_mentions WHERE source_id='fix-e'"
    ).fetchone()[0]
    assert first_count == 1

    # second pass: model returns 2 mentions this time
    new_response = FIXTURES[4]["claude_response"] + [{
        "trip_date": "2026-09-06", "bank": "182", "route": [],
        "paddy_count": 1, "holding": None, "species": [],
        "water_temp_f": None, "confidence": 0.6,
        "quote": "one more paddy on the way home"
    }]
    with patch("scraper.paddies.extract.call_claude", return_value=new_response):
        ex.extract_one(conn, row, gaz)
    second_count = conn.execute(
        "SELECT COUNT(*) FROM paddy_mentions WHERE source_id='fix-e'"
    ).fetchone()[0]
    assert second_count == 2  # replaced, not appended


# ---------------------------------------------------------------------
# API failure: don't mark extracted
# ---------------------------------------------------------------------

def test_main_exits_nonzero_when_all_posts_fail(db, monkeypatch, capsys):
    """If every post fails (e.g. Claude client broken), main() must exit non-zero
    so the nightly workflow surfaces the failure."""
    conn, dbpath = db
    monkeypatch.setattr(ex, "DB_PATH", dbpath)
    monkeypatch.setattr(ex, "call_claude", lambda prompt: None)
    monkeypatch.setattr(sys, "argv", ["extract", "--limit", "2"])
    rc = ex.main()
    assert rc == 2
    err = capsys.readouterr().err
    assert "FATAL" in err


def test_api_failure_leaves_extracted_zero(db, gaz):
    conn, _ = db
    with patch("scraper.paddies.extract.call_claude", return_value=None):
        row = conn.execute(
            "SELECT id, url, title, author, published_at, raw_text FROM paddy_sources WHERE id='fix-a'"
        ).fetchone()
        r = ex.extract_one(conn, row, gaz)
    assert r["ok"] is False
    ex_flag = conn.execute("SELECT extracted FROM paddy_sources WHERE id='fix-a'").fetchone()[0]
    assert ex_flag == 0  # unchanged
