"""Unit tests for parse_text_reports and the new verb-agnostic narrative harvest.

Legacy tests: 5/29 Dolphin AM/PM + Pegasus reports (parse_text_reports templates).
Phase 2 tests: 6/2 Seaforth narrative Update report (boat-anchored harvest).

Run:
    .venv\\Scripts\\python.exe tests\\test_text_parser.py
    # or with pytest if installed:
    .venv\\Scripts\\python.exe -m pytest tests/test_text_parser.py -v
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
from unittest.mock import patch

from src.scrape import (
    parse_text_reports, _extract_pairs, _trip_length_from_prose,
    classify_report_status, _harvest_narrative_reports, LandingSource,
)

_LANDING = "Seaforth Sportfishing"
_DATE    = date(2026, 5, 29)
_BOATS   = ["Dolphin", "Pegasus", "Mission Belle", "Aztec"]


def test_calledin_template_am():
    """'called in' template extracts boat + AM qualifier + species counts."""
    trips = parse_text_reports(
        ["Dolphin AM called in – 22 Bluefin Tuna, 5 Yellowtail"],
        _LANDING, _DATE, _BOATS,
    )
    assert len(trips) == 1, f"expected 1 trip, got {len(trips)}"
    t = trips[0]
    assert t["boat"] == "Dolphin"
    assert t["trip_length"] == "Half Day AM"
    assert t["bluefin"] == 22
    assert t["yellowtail"] == 5
    assert t["is_preliminary"] == 1


def test_returned_template_pm():
    """'returned with' template is classified as final (is_preliminary=0)."""
    trips = parse_text_reports(
        ["Dolphin PM returned with 18 Bluefin Tuna, 3 Dorado"],
        _LANDING, _DATE, _BOATS,
    )
    assert len(trips) == 1
    t = trips[0]
    assert t["boat"] == "Dolphin"
    assert t["trip_length"] == "Half Day PM"
    assert t["bluefin"] == 18
    assert t["dorado"] == 3
    assert t["is_preliminary"] == 0


def test_calledin_no_am_pm():
    """Boat without AM/PM qualifier gets Full Day trip_length."""
    trips = parse_text_reports(
        ["Pegasus called in – 15 Bluefin Tuna (50-80lbs), 2 Yellowtail"],
        _LANDING, _DATE, _BOATS,
    )
    assert len(trips) == 1
    t = trips[0]
    assert t["boat"] == "Pegasus"
    assert t["bluefin"] == 15
    assert t["yellowtail"] == 2
    assert t["trip_length"] == "Full Day"


def test_caught_template_mixed_rockfish():
    """'caught aboard' template + 'mixed Rockfish' routes to rockfish column."""
    trips = parse_text_reports(
        ["Caught aboard the Dolphin AM: 12 Yellowtail, 20 mixed Rockfish"],
        _LANDING, _DATE, _BOATS,
    )
    assert len(trips) == 1
    t = trips[0]
    assert t["boat"] == "Dolphin"
    assert t["trip_length"] == "Half Day AM"
    assert t["yellowtail"] == 12
    assert t.get("rockfish", 0) == 20


def test_timestamp_prefix_stripped():
    """Timestamp / 'UPDATE:' prefix is stripped before template matching."""
    trips = parse_text_reports(
        ["UPDATE 10:30AM: Pegasus called in with 8 Bluefin Tuna, 14 Yellowtail"],
        _LANDING, _DATE, _BOATS,
    )
    assert len(trips) == 1
    t = trips[0]
    assert t["boat"] == "Pegasus"
    assert t["bluefin"] == 8
    assert t["yellowtail"] == 14


# ---------------------------------------------------------------------------
# Phase 2 — verb-agnostic, boat-anchored harvest (6/2 Seaforth Update report)
# ---------------------------------------------------------------------------

_SEAFORTH_SRC = LandingSource(
    name="Seaforth Sportfishing",
    url="https://www.fishcounts.com/seaforth/fishcounts.php",
    referer="https://www.seaforthlanding.com/",
    main_url="https://www.seaforthlanding.com/",
    news_url="https://www.seaforthlanding.com/fish-reports/",
)

_POLARIS_BLOCK = (
    "The Polaris Supreme checked in from their 3 Day with 38 Yellowfin Tuna, "
    "70 Skipjack and 5 Yellowtail. They are switching gears to Bluefin today, "
    "so stay tuned."
)

_SAN_DIEGO_BLOCK = (
    "The San Diego back down to the Coronado Islands found the yellowtail and "
    "connected with 25 Yellowtail along with 5 Barracuda, 18 Rockfish, and "
    "75 Whitefish! There are still spots available for tomorrow 6/2."
)

_CHATTER_BLOCKS = [
    "switching gears to Bluefin today — stay tuned for updates!",
    "spots available for tomorrow 6/2, book now at seaforthlanding.com",
    "The weather looks great for tomorrow 6/2 — join us!",
]

_ALL_BOATS = ["Polaris Supreme", "San Diego", "Dolphin", "Pegasus", "Mission Belle"]
_DATE_6_2  = date(2026, 6, 2)


def _fake_html(blocks: list[str]) -> str:
    """Wrap text blocks in minimal HTML so _extract_text_blocks can parse them."""
    paras = "".join(f"<p>{b}</p>" for b in blocks)
    return f"<html><body>{paras}</body></html>"


def _run_harvest(blocks: list[str], today_trips: list[dict] | None = None) -> list[dict]:
    """Call _harvest_narrative_reports with mocked HTTP fetches."""
    html = _fake_html(blocks)
    with patch("src.scrape._fetch_optional", return_value=html):
        return _harvest_narrative_reports(
            _SEAFORTH_SRC,
            today_trips or [],
            _ALL_BOATS,
            _DATE_6_2,
        )


def test_extract_pairs_polaris():
    """_extract_pairs correctly harvests Yellowfin, Skipjack, Yellowtail."""
    tracked, other, unknown = _extract_pairs(_POLARIS_BLOCK)
    assert tracked["Yellowfin"] == 38, tracked
    assert tracked["Skipjack"]  == 70, tracked
    assert tracked["Yellowtail"] == 5, tracked
    assert not any(unknown), f"unexpected unknowns: {unknown}"


def test_extract_pairs_san_diego():
    """_extract_pairs harvests Yellowtail, Barracuda, Rockfish, Whitefish."""
    tracked, other, unknown = _extract_pairs(_SAN_DIEGO_BLOCK)
    assert tracked["Yellowtail"]    == 25, tracked
    assert other.get("Barracuda")   ==  5, other
    assert other.get("Rockfish")    == 18, other
    assert other.get("Whitefish")   == 75, other
    assert not any(unknown), f"unexpected unknowns: {unknown}"


def test_trip_length_from_prose_3day():
    """Detects '3 Day' in the Polaris Supreme block."""
    bucket, days, raw = _trip_length_from_prose(_POLARIS_BLOCK)
    assert bucket == "3 Day", bucket
    assert days == 3.0, days


def test_trip_length_from_prose_none():
    """Returns (None, None, '') when no trip length in prose."""
    bucket, days, raw = _trip_length_from_prose(_SAN_DIEGO_BLOCK)
    assert bucket is None
    assert raw == ''


def test_status_polaris_still_fishing():
    """'checked in' + 'switching gears' + 'stay tuned' → preliminary."""
    assert classify_report_status(_POLARIS_BLOCK) == 'preliminary'


def test_status_san_diego_returned():
    """'back down to' → final; 'still spots available' is not a trigger."""
    assert classify_report_status(_SAN_DIEGO_BLOCK) == 'final'


def test_chatter_produces_no_counts():
    """Pure chatter blocks with no known boat + species pairs → no new trips."""
    new = _run_harvest(_CHATTER_BLOCKS)
    assert new == [], f"chatter should produce nothing, got: {new}"


def test_harvest_polaris_new_trip():
    """Polaris Supreme (not in today's structured table) → new provisional trip."""
    new = _run_harvest([_POLARIS_BLOCK])
    assert len(new) == 1, f"expected 1 new trip, got {len(new)}"
    t = new[0]
    assert t["boat"]          == "Polaris Supreme"
    assert t["yellowfin"]     == 38
    assert t["skipjack"]      == 70
    assert t["yellowtail"]    ==  5
    assert t["trip_length"]   == "3 Day"
    assert t["anglers"]       ==  0,  "anglers unknown → sentinel 0"
    assert t["is_preliminary"] == 1,  "always preliminary when anglers unknown"
    assert t["source"]        == "text_fallback"


def test_harvest_san_diego_fills_blank_structured():
    """San Diego in structured table with trophy_count=0 → filled in-place, NOT new trip."""
    existing = {
        "boat": "San Diego", "landing": "Seaforth Sportfishing",
        "trip_length": "Full Day", "trip_length_days": 0.75,
        "anglers": 22, "trophy_count": 0,
        "source": "fish_count_page", "is_preliminary": 0,
        "bluefin": 0, "yellowfin": 0, "yellowtail": 0, "dorado": 0,
        "skipjack": 0, "bigeye": 0, "albacore": 0,
    }
    new = _run_harvest([_SAN_DIEGO_BLOCK], today_trips=[existing])
    assert new == [], "should fill in-place, not emit a new trip"
    assert existing["yellowtail"]   == 25
    assert existing["trophy_count"] == 25   # yellowtail is a trophy species
    assert existing["source"]       == "text_fallback"
    assert existing["is_preliminary"] == 0  # 'back down to' = final/returned


if __name__ == "__main__":
    _tests = [
        test_calledin_template_am,
        test_returned_template_pm,
        test_calledin_no_am_pm,
        test_caught_template_mixed_rockfish,
        test_timestamp_prefix_stripped,
        # Phase 2 — verb-agnostic harvest
        test_extract_pairs_polaris,
        test_extract_pairs_san_diego,
        test_trip_length_from_prose_3day,
        test_trip_length_from_prose_none,
        test_status_polaris_still_fishing,
        test_status_san_diego_returned,
        test_chatter_produces_no_counts,
        test_harvest_polaris_new_trip,
        test_harvest_san_diego_fills_blank_structured,
    ]
    passed = 0
    for fn in _tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(_tests)} tests passed")
    sys.exit(0 if passed == len(_tests) else 1)
