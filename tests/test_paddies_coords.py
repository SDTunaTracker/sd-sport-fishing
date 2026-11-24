"""Coordinate parser + offset resolver tests for scraper.paddies.coords."""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scraper.paddies import coords as C


# ---------------------------------------------------------------------
# parse_coords — 15+ cases (DD / DDM / DMS, hemispheres, missing hemi)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected_lat,expected_lon", [
    # DD (decimal degrees)
    ("32.4083, -117.3017",           32.4083, -117.3017),
    ("32.4083,-117.3017",            32.4083, -117.3017),
    ("32.4083 -117.3017",            32.4083, -117.3017),
    ("32.4083°N 117.3017°W",         32.4083, -117.3017),
    ("32.4083 N 117.3017 W",         32.4083, -117.3017),
    ("32.4083 117.3017",             32.4083, -117.3017),  # missing hemi -> N/W
    # DDM (degrees, decimal minutes)
    ("32 24.50 N 117 18.10 W",       32 + 24.50/60, -(117 + 18.10/60)),
    ("32°24.5' 117°18.1'",           32 + 24.5/60, -(117 + 18.1/60)),
    ("32 24.500 N 117 18.100 W",     32 + 24.500/60, -(117 + 18.100/60)),
    # DMS (degrees, minutes, seconds)
    ("32°24'30\" N 117°18'06\" W",   32 + 24/60 + 30/3600, -(117 + 18/60 + 6/3600)),
    ("32°24'30\" 117°18'06\"",       32 + 24/60 + 30/3600, -(117 + 18/60 + 6/3600)),
    ("32 24 30 N 117 18 06 W",       32 + 24/60 + 30/3600, -(117 + 18/60 + 6/3600)),
    # South / East hemispheres actually flip signs (defensive)
    ("32.4083 S 117.3017 E",         -32.4083, 117.3017),
    # Cortes Bank neighborhood
    ("32.4515 -119.1855",             32.4515, -119.1855),
    # SCI area
    ("32.9 N 118.5 W",                32.9, -118.5),
])
def test_parse_coords_all_formats(raw, expected_lat, expected_lon):
    got = C.parse_coords(raw)
    assert got is not None, f"failed to parse {raw!r}"
    assert got["lat"] == pytest.approx(expected_lat, abs=1e-4)
    assert got["lon"] == pytest.approx(expected_lon, abs=1e-4)


def test_parse_coords_returns_none_when_no_pattern():
    assert C.parse_coords("we fished a paddy and got some yellows") is None
    assert C.parse_coords("") is None
    assert C.parse_coords("just 8 fish") is None


def test_parse_coords_format_tag():
    assert C.parse_coords("32.4083, -117.3017")["format"] == "dd"
    assert C.parse_coords("32 24.50 N 117 18.10 W")["format"] == "ddm"
    assert C.parse_coords("32°24'30\" N 117°18'06\" W")["format"] == "dms"


# ---------------------------------------------------------------------
# Sanity box + land test
# ---------------------------------------------------------------------

@pytest.mark.parametrize("lat,lon,ok", [
    (32.7,  -117.4,  True),   # offshore SD
    (32.4,  -117.3,  True),   # Coronados
    (32.9,  -118.5,  True),   # SCI
    (33.4,  -118.4,  True),   # Catalina
    (32.45, -119.2,  True),   # Cortes Bank
    (29.9,  -117.0,  False),  # too far south (below sanity box)
    (34.7,  -119.0,  False),  # too far north
    (32.7,  -115.0,  False),  # too far east
    (32.7,  -122.0,  False),  # too far west
])
def test_in_sanity_box(lat, lon, ok):
    assert C.in_sanity_box(lat, lon) is ok


@pytest.mark.parametrize("lat,lon,expected_land", [
    # Spec's literal simple test: lon > -117.05 AND lat > 32.5.
    # Coordinates east of -117.05 up in SD/OC are firmly inland (I-5 corridor).
    (32.75, -116.95, True),   # El Cajon area
    (33.00, -116.90, True),   # inland north SD county
    (32.40, -117.25, False),  # Coronado Islands (south of 32.5)
    (32.60, -117.40, False),  # 9-Mile Bank (west of -117.05)
    (33.38, -118.40, False),  # Catalina (well west)
    (32.72, -117.16, False),  # downtown SD — west of -117.05, so simple test
                              # doesn't catch it. Documented in code.
])
def test_on_land(lat, lon, expected_land):
    assert C.on_land(lat, lon) is expected_land


def test_valid_offshore_composite():
    assert C.valid_offshore(32.60, -117.40) is True   # 9-Mile Bank
    assert C.valid_offshore(32.75, -116.95) is False  # El Cajon -> on land
    assert C.valid_offshore(29.9,  -117.0) is False   # out of sanity box


# ---------------------------------------------------------------------
# 4 explicit land/out-of-box rejections (per spec's stop-and-ask rule)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("lat,lon", [
    (32.75, -116.95),  # El Cajon (lon > -117.05, lat > 32.5)
    (33.00, -116.60),  # inland east SD county
    (29.9,  -117.0),   # below sanity box
    (35.0,  -120.0),   # above sanity box
])
def test_rejects_land_or_out_of_box(lat, lon):
    assert C.valid_offshore(lat, lon) is False


# ---------------------------------------------------------------------
# coords_agree — for reconciling model-vs-code parse
# ---------------------------------------------------------------------

def test_coords_agree_within_tolerance():
    assert C.coords_agree((32.7, -117.4), (32.705, -117.395)) is True
    assert C.coords_agree((32.7, -117.4), (32.72, -117.4)) is False  # 0.02° apart
    assert C.coords_agree(None, (32.7, -117.4)) is False
    assert C.coords_agree((32.7, -117.4), None) is False


# ---------------------------------------------------------------------
# Bearing / distance word parsing
# ---------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_deg", [
    ("6 miles SW of the 182",        225.0),
    ("a couple miles west of X",     270.0),
    ("outside the 302",              240.0),
    ("inside the 43",                 60.0),
    ("SSE of the 267",               157.5),
    ("northeast of Cortes",           45.0),
    ("just N of the corner",           0.0),
])
def test_bearing_from_words(text, expected_deg):
    assert C.bearing_from_words(text) == pytest.approx(expected_deg, abs=0.1)


def test_bearing_from_words_returns_none():
    assert C.bearing_from_words("fished a paddy") is None
    assert C.bearing_from_words("") is None


@pytest.mark.parametrize("text,expected_nm", [
    # Bare "miles" from an offshore angler = nm. No conversion.
    ("6 miles SW of the 182",        6.0),
    ("3 nm off Point Loma",          3.0),
    ("a couple miles west of X",     2.0),
    ("a few miles off the 302",      3.0),
    ("handful of miles from Cortes", 4.0),
    ("several miles outside",        5.0),
    # Only convert when explicitly statute.
    ("6 statute miles SW of the 182", 6 * 0.868976),
    ("6 sm SW of the 182",            6 * 0.868976),
    ("a few statute miles off",       3 * 0.868976),
])
def test_distance_from_words(text, expected_nm):
    got = C.distance_from_words(text)
    assert got == pytest.approx(expected_nm, abs=0.02)


def test_distance_from_words_returns_none():
    assert C.distance_from_words("outside the 302") is None
    assert C.distance_from_words("") is None


# ---------------------------------------------------------------------
# Offset resolver — reference points from the gazetteer
# ---------------------------------------------------------------------

# From data/banks.geojson (rebuilt Phase 1)
REF = {
    "182":            (32.485, -117.760),   # approx; exact values below via lookup
    "302":            None,
    "the-corner":     None,
    "43-fathom-spot": None,
    "9-mile-bank":    (32.59085, -117.39165),
}


@pytest.fixture(scope="module")
def gaz_lookup():
    """Bank id -> (lat, lon) from the real gazetteer."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "data" / "banks.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in data["features"]:
        lon, lat = f["geometry"]["coordinates"]
        out[f["properties"]["id"]] = (lat, lon)
    return out


def test_offset_6_miles_sw_of_182(gaz_lookup):
    """'6 miles SW of the 182' → bare 'miles' = 6 nm, within 0.3 nm."""
    ref_lat, ref_lon = gaz_lookup["182"]
    d_nm = C.distance_from_words("6 miles SW of the 182")
    b_deg = C.bearing_from_words("6 miles SW of the 182")
    assert d_nm == 6.0
    assert b_deg == 225.0
    lat, lon = C.apply_offset(ref_lat, ref_lon, b_deg, d_nm)
    dist_from_ref = C.haversine_nm(ref_lat, ref_lon, lat, lon)
    assert abs(dist_from_ref - d_nm) < 0.3


def test_offset_outside_302(gaz_lookup):
    ref_lat, ref_lon = gaz_lookup["302"]
    b_deg = C.bearing_from_words("outside the 302")
    assert b_deg == 240.0
    # "outside" without a distance: distance is None → precision=bank fallback,
    # NOT applying an offset. Verify distance is indeed None.
    d = C.distance_from_words("outside the 302")
    assert d is None


def test_offset_couple_miles_west_of_corner(gaz_lookup):
    ref_lat, ref_lon = gaz_lookup["the-corner"]
    d_nm = C.distance_from_words("a couple miles west of the Corner")
    b_deg = C.bearing_from_words("a couple miles west of the Corner")
    assert b_deg == 270.0
    assert d_nm == 2.0   # bare "miles" = 2 nm now
    lat, lon = C.apply_offset(ref_lat, ref_lon, b_deg, d_nm)
    assert lat == pytest.approx(ref_lat, abs=0.01)
    assert lon < ref_lon   # west = smaller lon
    dist = C.haversine_nm(ref_lat, ref_lon, lat, lon)
    assert abs(dist - d_nm) < 0.3


def test_offset_lands_offshore_not_on_land(gaz_lookup):
    """Sanity: an offset from an offshore bank should still be offshore."""
    ref_lat, ref_lon = gaz_lookup["182"]
    lat, lon = C.apply_offset(ref_lat, ref_lon, 225.0, 5.0)  # 5 nm SW
    assert C.valid_offshore(lat, lon)


# ---------------------------------------------------------------------
# haversine sanity
# ---------------------------------------------------------------------

def test_haversine_zero():
    assert C.haversine_nm(32.7, -117.2, 32.7, -117.2) == pytest.approx(0.0, abs=1e-6)


def test_haversine_sd_to_catalina():
    # ~66 nm — well-known
    d = C.haversine_nm(32.72, -117.17, 33.38, -118.40)
    assert 60 < d < 75
