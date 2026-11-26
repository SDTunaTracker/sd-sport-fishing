"""src/bait.py: Everingham bait-report parser, change-only storage, export."""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import bait  # noqa: E402

FIXTURE = (ROOT / "tests" / "fixtures" / "everingham_bait_2026-11-26.csv").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)


def test_parse_sheet_reads_all_three_barges():
    got = {e["barge"]: e for e in bait.parse_sheet(FIXTURE, NOW)}
    assert set(got) == {"san_diego_bay", "mission_bay", "dana_point"}
    sd = got["san_diego_bay"]
    assert sd["raw"] == "5-7 inch Sardine"
    assert (sd["species"], sd["min_in"], sd["max_in"]) == ("sardine", 5.0, 7.0)
    assert sd["as_of"] == "2026-11-25T08:45:00-08:00"
    assert got["dana_point"]["species"] == "anchovy"
    assert got["mission_bay"]["as_of"] == "2026-11-26T08:16:00-08:00"


def test_parse_bait_variants():
    assert bait.parse_bait("5 - 7in Sardine") == {"species": "sardine", "min_in": 5.0, "max_in": 7.0}
    assert bait.parse_bait("4 to 6 inch anchovy")["max_in"] == 6.0
    assert bait.parse_bait("6 inch Mackerel") == {"species": "mackerel", "min_in": 6.0, "max_in": 6.0}
    assert bait.parse_bait("Squid") == {"species": "squid", "min_in": None, "max_in": None}
    assert bait.parse_bait("Closed today")["species"] is None


def test_as_of_year_rollover():
    jan = datetime(2027, 1, 1, 18, 0, tzinfo=timezone.utc)
    assert bait.parse_as_of("12/31 - 4:05p", jan) == "2026-12-31T16:05:00-08:00"
    assert bait.parse_as_of("1/1 - 12:10a", jan) == "2027-01-01T00:10:00-08:00"
    assert bait.parse_as_of("garbage", jan) is None


def test_layout_change_returns_empty_not_crash():
    assert bait.parse_sheet("a,b,c\n1,2,3\n", NOW) == []
    assert bait.parse_sheet("", NOW) == []


def test_store_is_change_only_and_export_flags_stale():
    conn = sqlite3.connect(":memory:")
    entries = bait.parse_sheet(FIXTURE, NOW)
    assert bait.store(conn, entries, "2026-11-26T17:00:00+00:00") == 3
    assert bait.store(conn, entries, "2026-11-26T18:00:00+00:00") == 0  # unchanged
    p = bait.build_payload(conn, NOW)
    by = {b["id"]: b for b in p["barges"]}
    assert by["san_diego_bay"]["landings"] == ["H&M Landing", "Fisherman's Landing", "Point Loma Sportfishing"]
    assert by["mission_bay"]["stale"] is False
    # San Diego's "As of" is 11/25 08:45 PT, 25+ hours before NOW.
    assert by["san_diego_bay"]["stale"] is True
    assert p["source"]["url"] == "https://baitbarge.com/"

    changed = [dict(entries[0], raw="4-6 inch Anchovy", species="anchovy", as_of="2026-11-26T09:30:00-08:00")]
    assert bait.store(conn, changed, "2026-11-26T18:30:00+00:00") == 1
    p = bait.build_payload(conn, NOW)
    sd = next(b for b in p["barges"] if b["id"] == "san_diego_bay")
    assert sd["bait"] == "4-6 inch Anchovy" and sd["stale"] is False
