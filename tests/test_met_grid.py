"""src/met_grid.py: Open-Meteo responses -> web/api/v1/met_grid.json."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import met_grid as M

N = M.GRID["nx"] * M.GRID["ny"]


def _times(start="2026-11-27T00:00", hours=72):
    t0 = datetime.fromisoformat(start)
    return [(t0.replace(tzinfo=None) + __import__("datetime").timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
            for h in range(hours)]


def _locs(fields: dict):
    t = _times()
    return [{"hourly": {"time": t, **{f: [fn(p, h) for h in range(len(t))] for f, fn in fields.items()}}}
            for p in range(N)]


WIND = _locs({"windspeed_10m": lambda p, h: p + h / 10, "winddirection_10m": lambda p, h: 270})
MARINE = _locs({"swell_wave_height": lambda p, h: None if p == 0 else 1.234,
                "swell_wave_direction": lambda p, h: 250, "swell_wave_period": lambda p, h: 14.04})


def test_grid_matches_charts_jsx_row_major():
    lats, lons = M.grid_points()
    assert len(lats) == N and lats[0] == "35.00" and lons[0] == "-121.00"
    assert lats[-1] == "31.00" and lons[-1] == "-117.00" and lats[9] == "34.50"


def test_build_starts_at_the_current_utc_hour():
    now = datetime(2026, 11, 27, 17, 42, tzinfo=timezone.utc)
    g = M.build(WIND, MARINE, now)
    assert g["start"] == "2026-11-27T17:00:00Z" and g["grid"] == M.GRID
    assert len(g["wind"]["speed"]) == M.HOURS and len(g["wind"]["speed"][0]) == N
    assert g["wind"]["speed"][0][3] == 4.7          # point 3, hour index 17
    assert g["wind"]["dir"][0][0] == 270
    assert g["swell"]["height"][0][0] is None        # land point stays null
    assert g["swell"]["height"][0][1] == 1.23 and g["swell"]["period"][0][1] == 14.0


def test_build_rejects_wrong_point_count_and_missing_hour():
    with pytest.raises(ValueError):
        M.build(WIND[:-1], MARINE, datetime(2026, 11, 27, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        M.build(WIND, MARINE, datetime(2026, 12, 5, 1, tzinfo=timezone.utc))
