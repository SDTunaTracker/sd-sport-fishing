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
    got = json.loads(v["payload"])["species"]
    assert "wahoo" not in got
    assert set(got) == {"yellowtail", "dorado"}


def test_validate_route_filters_unknowns(gaz):
    v = ex.validate_mention(
        {"bank": None, "route": ["182", "no-such", "312", "209"], "species": [],
         "confidence": 0.5, "quote": "x"},
        gaz["valid_ids"], "src1",
    )
    assert json.loads(v["payload"])["route"] == ["182", "312", "209"]


def test_validate_produces_new_schema(gaz):
    v = ex.validate_mention(
        {"bank": "182", "route": [], "paddy_count": 3, "holding": True,
         "species": ["yellowtail"], "water_temp_f": 68.0,
         "confidence": 0.9, "quote": "x", "trip_date": "2026-09-06"},
        gaz["valid_ids"], "src1",
    )
    # top-level fields
    assert v["type"] == "paddy"
    assert v["bank"] == "182"
    assert v["precision"] == "bank"  # bank set -> precision=bank
    assert v["lat"] is None and v["lon"] is None
    # payload fields
    p = json.loads(v["payload"])
    assert p == {
        "route": [], "paddy_count": 3, "holding": True,
        "species": ["yellowtail"], "water_temp_f": 68.0,
    }


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
                (id, source, feed_id, url, title, author, published_at,
                 fetched_at, raw_text, extracted)
            VALUES (?, 'bdoutdoors', 'bd-socal-offshore', ?, ?, NULL, ?, ?, ?, 0)
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
            "SELECT id, url, title, author, published_at, raw_text, truncated, feed_id "
            "FROM paddy_sources WHERE id = ?", (fx["post"]["id"],)
        ).fetchone()
        return ex.extract_one(conn, row, gaz)


def _fetch_paddy(conn, source_id):
    row = conn.execute(
        "SELECT * FROM report_mentions WHERE source_id = ? AND type = 'paddy'",
        (source_id,)
    ).fetchone()
    if row is None:
        return None, None
    return row, json.loads(row["payload"])


def test_fixture_a_zero_kelp(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[0])
    assert r["ok"] and r["mentions"] == 1
    m, payload = _fetch_paddy(conn, "fix-a")
    assert m["type"] == "paddy"
    assert m["feed_id"] == "bd-socal-offshore"
    assert m["bank"] == "182"
    assert m["precision"] == "bank"
    assert payload["paddy_count"] == 0
    assert payload["holding"] is False
    # source flipped to extracted=1
    ex_flag = conn.execute("SELECT extracted FROM paddy_sources WHERE id='fix-a'").fetchone()[0]
    assert ex_flag == 1


def test_fixture_b_loop_route(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[1])
    assert r["ok"] and r["mentions"] == 1
    m, payload = _fetch_paddy(conn, "fix-b")
    assert payload["route"] == ["182", "181", "312", "209"]
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
    m, payload = _fetch_paddy(conn, "fix-d")
    assert payload["paddy_count"] == 12
    assert payload["holding"] is False
    assert m["bank"] == "the-corner"


def test_fixture_e_yt_on_43(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[4])
    assert r["ok"] and r["mentions"] == 1
    m, payload = _fetch_paddy(conn, "fix-e")
    assert m["bank"] == "43-fathom-spot"
    assert payload["water_temp_f"] == 68.0
    assert payload["species"] == ["yellowtail"]


def test_fixture_f_unknown_bank_becomes_null(db, gaz):
    conn, _ = db
    r = _run_fixture(conn, gaz, FIXTURES[5])
    assert r["ok"] and r["mentions"] == 1
    m, _ = _fetch_paddy(conn, "fix-f")
    assert m["bank"] is None            # unknown -> null
    assert m["precision"] is None       # no bank -> no precision
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
            "SELECT id, url, title, author, published_at, raw_text, truncated, feed_id "
            "FROM paddy_sources WHERE id='fix-e'"
        ).fetchone()
        ex.extract_one(conn, row, gaz)
    first_count = conn.execute(
        "SELECT COUNT(*) FROM report_mentions WHERE source_id='fix-e'"
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
        "SELECT COUNT(*) FROM report_mentions WHERE source_id='fix-e'"
    ).fetchone()[0]
    assert second_count == 2  # replaced, not appended


# ---------------------------------------------------------------------
# API failure: don't mark extracted
# ---------------------------------------------------------------------

def test_quote_matches_source_curly_apostrophe():
    """Regression: XenForo posts contain U+2019 (curly '), Claude returns
    U+0027 (straight '). Verify our matcher folds them via NFKC."""
    source = "Upon arrival at barn kelp we couldn’t get them to commit."
    quote  = "we couldn't get them to commit"
    assert ex.quote_matches_source(quote, source) is True


def test_quote_matches_source_curly_double_quote_and_dash():
    source = "They yelled “wide open on dorados!” out to 60 miles — wild."
    quote  = 'wide open on dorados!" out to 60 miles - wild'
    assert ex.quote_matches_source(quote, source) is True


def test_quote_matches_source_negative():
    assert ex.quote_matches_source("no match here", "totally different text") is False


def test_quote_matches_source_empty_inputs():
    assert ex.quote_matches_source("", "abc") is False
    assert ex.quote_matches_source("abc", "") is False


def test_quote_matches_source_whitespace_collapsed():
    """Line breaks / multiple spaces in the source don't defeat the match."""
    source = "line one.\n\nUpon arrival\tat  barn kelp    we couldn't get them to commit"
    quote  = "Upon arrival at barn kelp we couldn't get them to commit"
    assert ex.quote_matches_source(quote, source) is True


# ---------------------------------------------------------------------
# v2 fixtures — 8 posts covering all four types
# ---------------------------------------------------------------------

V2_FIXTURES = [
    # 1) pure bite
    {
        "post": {"id": "v2-bite", "url": "http://x/bite", "title": "YT bite 43",
                 "feed_id": "bd-socal-offshore",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "Ran to the 43 fathom spot, hooked 8 nice YT on surface iron."},
        "claude": [{
            "type": "bite", "trip_date": "2026-09-06", "bank": "43-fathom-spot",
            "position_ref": None, "confidence": 0.9,
            "quote": "hooked 8 nice YT on surface iron",
            "species": ["yellowtail"], "count": 8, "size_lb": None,
            "method": "surface_iron", "bait": None, "outcome": "steady",
        }],
        "assert": lambda conn: _one_row(conn, "v2-bite", "bite",
            lambda r, p: (r["bank"] == "43-fathom-spot"
                          and p["method"] == "surface_iron"
                          and p["species"] == ["yellowtail"]
                          and p["count"] == 8
                          and p["outcome"] == "steady")),
    },
    # 2) pure conditions
    {
        "post": {"id": "v2-cond", "url": "http://x/cond", "title": "conds",
                 "feed_id": "bd-socal-offshore",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "Water was 68F, blue and clean out at the 182. Lots of birds working."},
        "claude": [{
            "type": "conditions", "trip_date": "2026-09-06", "bank": "182",
            "position_ref": None, "confidence": 0.85,
            "quote": "Water was 68F, blue and clean out at the 182. Lots of birds working.",
            "water_temp_f": 68.0, "water_color": "blue", "current": None,
            "bait_marks": None, "life": ["birds"], "sea_state": None,
        }],
        "assert": lambda conn: _one_row(conn, "v2-cond", "conditions",
            lambda r, p: (r["bank"] == "182"
                          and p["water_temp_f"] == 68.0
                          and p["water_color"] == "blue"
                          and p["life"] == ["birds"])),
    },
    # 3) explicit GPS position + a bite tied via position_ref
    {
        "post": {"id": "v2-gps-bite", "url": "http://x/gps", "title": "gps yt",
                 "feed_id": "bd-socal-offshore",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "Hit the numbers 32.4083 -117.3017 for a wide-open YT bite."},
        "claude": [
            {"type": "position", "kind": "gps",
             "raw": "32.4083 -117.3017",
             "lat": 32.4083, "lon": -117.3017,
             "confidence": 0.95,
             "quote": "the numbers 32.4083 -117.3017"},
            {"type": "bite", "trip_date": "2026-09-06", "bank": None,
             "position_ref": 0, "confidence": 0.9,
             "quote": "wide-open YT bite",
             "species": ["yellowtail"], "count": None, "outcome": "wide_open",
             "method": None, "bait": None, "size_lb": None},
        ],
        "assert": lambda conn: _two_rows_gps_bite(conn),
    },
    # 4) offset position — "6 miles SW of the 182"
    {
        "post": {"id": "v2-offset", "url": "http://x/off", "title": "off",
                 "feed_id": "bd-socal-offshore",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "Fished 6 miles SW of the 182 and got a couple dodos."},
        "claude": [
            {"type": "position", "kind": "offset",
             "raw": "6 miles SW of the 182",
             "ref_bank": "182", "bearing_deg": 225, "distance_nm": 5.2,
             "confidence": 0.8,
             "quote": "6 miles SW of the 182"},
            {"type": "bite", "trip_date": "2026-09-06", "bank": "182",
             "position_ref": 0, "confidence": 0.85,
             "quote": "got a couple dodos",
             "species": ["dorado"], "count": 2, "outcome": None,
             "method": None, "bait": None, "size_lb": None},
        ],
        "assert": lambda conn: _offset_pos_and_bite(conn),
    },
    # 5) MODEL vs CODE disagreement — model says (33, -118), code parses raw = "32.4083 -117.3017"
    {
        "post": {"id": "v2-disagree", "url": "http://x/dis", "title": "dis",
                 "feed_id": "bd-socal-offshore",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "Numbers were 32.4083 -117.3017. Bit off."},
        "claude": [{
            "type": "position", "kind": "gps",
            "raw": "32.4083 -117.3017",
            "lat": 33.0, "lon": -118.0,   # wrong on purpose
            "confidence": 0.9,
            "quote": "Numbers were 32.4083 -117.3017",
        }],
        "assert": lambda conn: _code_wins(conn),
    },
    # 6) Spearfishing feed — paddies in a spearfishing report
    {
        "post": {"id": "v2-spear", "url": "http://x/spear", "title": "spear",
                 "feed_id": "bd-spearfishing",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "Dove some paddies off the corner, saw kelpies and a few dorado."},
        "claude": [{
            "type": "paddy", "trip_date": "2026-09-06", "bank": "the-corner",
            "position_ref": None, "confidence": 0.75,
            "quote": "Dove some paddies off the corner, saw kelpies and a few dorado.",
            "paddy_count": 3, "holding": True, "species": ["dorado"],
            "water_temp_f": None, "route": [],
        }],
        # generic-word bank -> confidence capped at 0.5
        "assert": lambda conn: _spearfishing_paddy(conn),
    },
    # 7) Multi-type post: paddy + bite + conditions in one array
    {
        "post": {"id": "v2-multi", "url": "http://x/multi", "title": "multi",
                 "feed_id": "bd-socal-offshore",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "182: paddy with a rat YT. Water blue, 69F."},
        "claude": [
            {"type": "paddy", "trip_date": "2026-09-06", "bank": "182",
             "position_ref": None, "confidence": 0.85,
             "quote": "paddy with a rat YT",
             "paddy_count": 1, "holding": True, "species": ["yellowtail"],
             "water_temp_f": None, "route": []},
            {"type": "bite", "trip_date": "2026-09-06", "bank": "182",
             "position_ref": None, "confidence": 0.8,
             "quote": "rat YT",
             "species": ["yellowtail"], "count": 1, "size_lb": None,
             "method": None, "bait": None, "outcome": None},
            {"type": "conditions", "trip_date": "2026-09-06", "bank": "182",
             "position_ref": None, "confidence": 0.85,
             "quote": "Water blue, 69F.",
             "water_temp_f": 69.0, "water_color": "blue", "current": None,
             "bait_marks": None, "life": [], "sea_state": None},
        ],
        "assert": lambda conn: _multi_type(conn),
    },
    # 8) Empty response (post has nothing relevant)
    {
        "post": {"id": "v2-empty", "url": "http://x/empty", "title": "shore",
                 "feed_id": "bd-socal-offshore",
                 "published_at": "2026-09-06T00:00:00+00:00",
                 "raw_text": "Bay bass on the surface iron. Fun morning."},
        "claude": [],
        "assert": lambda conn: (
            conn.execute("SELECT COUNT(*) FROM report_mentions WHERE source_id='v2-empty'").fetchone()[0] == 0
            and conn.execute("SELECT extracted FROM paddy_sources WHERE id='v2-empty'").fetchone()[0] == 1
        ),
    },
]


# Helper accessors used by the v2 fixture asserts.
def _one_row(conn, source_id, mtype, ok):
    row = conn.execute(
        "SELECT * FROM report_mentions WHERE source_id = ? AND type = ?",
        (source_id, mtype),
    ).fetchone()
    if row is None:
        return False
    return ok(row, json.loads(row["payload"]))


def _two_rows_gps_bite(conn):
    rows = list(conn.execute(
        "SELECT * FROM report_mentions WHERE source_id='v2-gps-bite' ORDER BY id"
    ))
    if len(rows) != 2:
        return False
    pos, bite = rows
    return (pos["type"] == "position"
            and pos["precision"] == "gps"
            and pos["lat"] == pytest.approx(32.4083, abs=1e-3)
            and pos["lon"] == pytest.approx(-117.3017, abs=1e-3)
            and bite["type"] == "bite"
            # bite inherited lat/lon from position via position_ref
            and bite["lat"] == pos["lat"]
            and bite["lon"] == pos["lon"]
            and bite["precision"] == "gps")


def _offset_pos_and_bite(conn):
    rows = list(conn.execute(
        "SELECT * FROM report_mentions WHERE source_id='v2-offset' ORDER BY id"
    ))
    if len(rows) != 2:
        return False
    pos, bite = rows
    if pos["type"] != "position" or pos["precision"] != "offset":
        return False
    # bite inherited lat/lon from offset position
    if bite["lat"] != pos["lat"] or bite["lon"] != pos["lon"]:
        return False
    if bite["precision"] != "offset":
        return False
    # confidence capped at 0.7 for offset
    if pos["confidence"] is not None and pos["confidence"] > 0.7 + 1e-9:
        return False
    return True


def _code_wins(conn):
    row = conn.execute(
        "SELECT * FROM report_mentions WHERE source_id='v2-disagree'"
    ).fetchone()
    if row is None or row["type"] != "position":
        return False
    # Code parsed 32.4083, -117.3017 from raw. Model said 33, -118 (wrong).
    # We should have used the code parse (32.4083, -117.3017), NOT the model's.
    return (abs(row["lat"] - 32.4083) < 1e-3
            and abs(row["lon"] - (-117.3017)) < 1e-3)


def _spearfishing_paddy(conn):
    row = conn.execute(
        "SELECT * FROM report_mentions WHERE source_id='v2-spear'"
    ).fetchone()
    if row is None:
        return False
    payload = json.loads(row["payload"])
    return (row["type"] == "paddy"
            and row["feed_id"] == "bd-spearfishing"
            and row["bank"] == "the-corner"
            # generic-word bank -> confidence capped at 0.5
            and row["confidence"] == pytest.approx(0.5, abs=1e-9)
            and payload["species"] == ["dorado"])


def _multi_type(conn):
    rows = list(conn.execute(
        "SELECT type FROM report_mentions WHERE source_id='v2-multi'"
    ))
    types = sorted(r[0] for r in rows)
    return types == ["bite", "conditions", "paddy"]


@pytest.fixture
def v2_db(tmp_path):
    p = tmp_path / "v2.db"
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    for fx in V2_FIXTURES:
        r = fx["post"]
        conn.execute("""INSERT INTO paddy_sources
            (id, source, feed_id, url, title, author, published_at,
             fetched_at, raw_text, extracted, truncated)
            VALUES (?, 'bdoutdoors', ?, ?, ?, NULL, ?, ?, ?, 0, 0)""",
            (r["id"], r["feed_id"], r["url"], r["title"],
             r["published_at"], r["published_at"], r["raw_text"]))
    conn.commit()
    yield conn
    conn.close()


@pytest.mark.parametrize("fx", V2_FIXTURES, ids=[f["post"]["id"] for f in V2_FIXTURES])
def test_v2_fixture(v2_db, gaz, fx):
    with patch("scraper.paddies.extract.call_claude", return_value=fx["claude"]):
        row = v2_db.execute(
            "SELECT id, url, title, author, published_at, raw_text, truncated, feed_id "
            "FROM paddy_sources WHERE id = ?", (fx["post"]["id"],)
        ).fetchone()
        result = ex.extract_one(v2_db, row, gaz)
    assert result["ok"] is True, f"extract_one failed for {fx['post']['id']}"
    assert fx["assert"](v2_db), f"post-assertion failed for {fx['post']['id']}"


def test_offset_falling_on_land_falls_back_to_bank(gaz):
    """
    An offset from a coastal landmark that mathematically lands on the
    mainland (per the coarse land test) must fall back to precision='bank'
    on the ref, NOT null out lat/lon.
    """
    id_to_coord = gaz["id_to_coord"]
    ref_id = "new-point-loma-lighthouse"    # coastal landmark from gazetteer
    assert ref_id in id_to_coord
    ref_lat, ref_lon = id_to_coord[ref_id]

    # 20 nm east from Point Loma at ~lat 32.66 pushes lon > -117.05, so the
    # coarse `lon > -117.05 AND lat > 32.5` on_land test fires.
    m = {"type": "position", "kind": "offset",
         "raw": "20 miles east of Point Loma lighthouse",
         "ref_bank": ref_id,
         "confidence": 0.9,
         "quote": "20 miles east of Point Loma lighthouse"}
    v = ex._validate_position(m, gaz["valid_ids"], "src", id_to_coord)
    assert v["type"] == "position"
    # Fell back to the ref coord (unrounded); precision downgraded to 'bank'.
    assert v["lat"] == pytest.approx(ref_lat, abs=1e-6)
    assert v["lon"] == pytest.approx(ref_lon, abs=1e-6)
    assert v["precision"] == "bank"


def test_v1_paddy_mentions_migrate_to_report_mentions(tmp_path):
    """Simulate a pre-v2 DB with paddy_mentions populated; ensure_schema
    must copy every row into report_mentions as type='paddy' with the
    old fields packed into payload, then drop paddy_mentions."""
    p = tmp_path / "t.db"
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row

    # 1) Set up the v1 shape (pre-migration). paddy_sources without feed_id.
    conn.executescript("""
        CREATE TABLE paddy_sources (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
            title TEXT, author TEXT,
            published_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
            raw_text TEXT NOT NULL, extracted INTEGER NOT NULL DEFAULT 0,
            truncated INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE paddy_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL, trip_date TEXT, bank TEXT,
            route_json TEXT NOT NULL DEFAULT '[]',
            paddy_count INTEGER, holding INTEGER,
            species_json TEXT NOT NULL DEFAULT '[]',
            water_temp_f REAL, confidence REAL, quote TEXT,
            extracted_at TEXT NOT NULL
        );
    """)
    conn.execute("""INSERT INTO paddy_sources VALUES
        ('s1','bdoutdoors','http://x/1','T','a',
         '2026-09-01T12:00:00+00:00','2026-09-01T12:00:00+00:00',
         'body',1,0)""")
    conn.execute("""INSERT INTO paddy_mentions
        (source_id, trip_date, bank, route_json, paddy_count, holding,
         species_json, water_temp_f, confidence, quote, extracted_at)
        VALUES
        ('s1','2026-09-01','302','["9-mile-bank-s","302","371"]',
         3,0,'["yellowtail"]',68.5,0.85,'a few micro paddies',
         '2026-09-01T13:00:00+00:00')""")
    conn.execute("""INSERT INTO paddy_mentions
        (source_id, trip_date, bank, route_json, paddy_count, holding,
         species_json, water_temp_f, confidence, quote, extracted_at)
        VALUES
        ('s1',NULL,NULL,'[]',NULL,NULL,'[]',NULL,0.4,'unresolved',
         '2026-09-01T13:00:01+00:00')""")
    conn.commit()

    # 2) Migrate: order matters — ingest first (paddy_sources.feed_id),
    #    then extract (paddy_mentions → report_mentions).
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)

    # 3) paddy_mentions is gone; report_mentions has both rows as paddy.
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "paddy_mentions" not in tables
    assert "report_mentions" in tables

    rows = list(conn.execute("SELECT * FROM report_mentions ORDER BY id"))
    assert len(rows) == 2
    for r in rows:
        assert r["type"] == "paddy"
        assert r["feed_id"] == "bd-socal-offshore"

    # row 1: bank set -> precision=bank; payload has intact v1 fields
    r0, r1 = rows
    assert r0["bank"] == "302"
    assert r0["precision"] == "bank"
    assert r0["lat"] is None and r0["lon"] is None
    payload0 = json.loads(r0["payload"])
    assert payload0 == {
        "route": ["9-mile-bank-s", "302", "371"],
        "paddy_count": 3, "holding": False,
        "species": ["yellowtail"], "water_temp_f": 68.5,
    }

    # row 2: bank null -> precision null; payload has nulls preserved
    assert r1["bank"] is None
    assert r1["precision"] is None
    payload1 = json.loads(r1["payload"])
    assert payload1["paddy_count"] is None
    assert payload1["holding"] is None
    assert payload1["route"] == []


def test_ensure_schema_is_idempotent_after_migration(tmp_path):
    """Calling ensure_schema twice on a fresh DB is safe (no double-migration)."""
    p = tmp_path / "t.db"
    conn = sqlite3.connect(p)
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    ex.ensure_schema(conn)  # second call must not throw
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "report_mentions" in tables
    assert "paddy_mentions" not in tables


def test_main_exits_nonzero_when_all_posts_fail(db, monkeypatch, capsys):
    """If every post fails (e.g. Claude client broken), main() must exit non-zero
    so the nightly workflow surfaces the failure."""
    conn, dbpath = db
    monkeypatch.setattr(ex, "DB_PATH", dbpath)
    monkeypatch.setattr(ingest_bd, "STATE_PATH", dbpath.parent / "state.json")
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
