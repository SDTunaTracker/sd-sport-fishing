"""Boat-profile spec parsing (year built, length) and its data-health check."""
from __future__ import annotations

import sqlite3
from datetime import date

from src import completeness as C
from src.boats import find_length_ft, find_year_built

TODAY = date(2026, 11, 26)

# Trimmed from fishermanslanding.com/boats/pacific-queen.php (Nov 2026).
PACIFIC_QUEEN = (
    "Trip Types Season Anglers Price Overnight - Spring/Fall 2026 Charter Rates 34 $10,500 Cash "
    "Overnight- Summer 2026 Charter Rates 34 $11,000 Cash Captain Drew Card Full Galley Service "
    "85 ft. x 22 ft. Sleeps 40 People Refrigerated Fish-hold The Pacific Queen is a graceful, "
    "smooth riding sportfishing vessel 88 feet in overall length."
)


def test_rate_year_is_not_year_built():
    assert find_year_built(PACIFIC_QUEEN, TODAY) is None


def test_year_next_to_built_or_year():
    assert find_year_built("Built in 1944 by Wilmington Boat Works", TODAY) == 1944
    assert find_year_built("Year Built: 1981. Summer 2026 rates", TODAY) == 1981
    assert find_year_built("Year: 1999", TODAY) == 1999
    assert find_year_built("She was launched in 2004.", TODAY) == 2004


def test_year_built_range_is_1900_to_last_year():
    assert find_year_built("Built in 2026", TODAY) is None
    assert find_year_built("Built in 2025", TODAY) == 2025
    assert find_year_built("built 1899", TODAY) is None
    assert find_year_built("rebuilt in 2019", TODAY) is None


def test_length_prefers_overall():
    assert find_length_ft(PACIFIC_QUEEN) == 88
    assert find_length_ft("LOA: 65' Beam 20'") == 65
    assert find_length_ft("Length overall 72 ft") == 72
    assert find_length_ft("80 ft. x 24 ft. sleeps 30") == 80
    # H&M: the spec line puts the width last; the bare "10 foot" is a bait tank.
    assert find_length_ft("Open Trips 85 x 22 Feet Sleeps 30. her 10 foot deep bait tank") == 85
    assert find_length_ft("Trips 80 x 25 Feet Sleeps 28 and at 85 feet in length") == 85


def _db(tmp_path, years):
    conn = sqlite3.connect(tmp_path / "b.db")
    conn.execute("CREATE TABLE boat_profiles (boat TEXT, landing TEXT, year_built INTEGER)")
    conn.executemany("INSERT INTO boat_profiles VALUES (?,?,?)",
                     [(f"Boat {i}", "L", y) for i, y in enumerate(years)])
    return conn


def test_health_check_flags_impossible_year(tmp_path):
    probs = C.check_boat_profiles(_db(tmp_path, [1944, 2026, None]), TODAY)
    assert [p.key for p in probs] == ["boat_profiles:year_built"]
    assert "Boat 1 (2026)" in probs[0].detail


def test_health_check_passes_good_years(tmp_path):
    assert C.check_boat_profiles(_db(tmp_path, [1944, 2025, None]), TODAY) == []
