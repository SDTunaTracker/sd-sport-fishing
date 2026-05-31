"""Unit tests for parse_text_reports (called-in / returned-with templates).

Based on 5/29 Dolphin AM/PM + Pegasus reports from Seaforth Sportfishing.

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
from src.scrape import parse_text_reports

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


if __name__ == "__main__":
    _tests = [
        test_calledin_template_am,
        test_returned_template_pm,
        test_calledin_no_am_pm,
        test_caught_template_mixed_rockfish,
        test_timestamp_prefix_stripped,
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
