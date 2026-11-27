"""Posted GPS pins and spot names from BloodyDecks posts (forum_spots.geojson)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.paddies import coords, extract, ingest_bd, spots

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


# ------------------------------------------------------------------ formats

@pytest.mark.parametrize("raw,lat,lon", [
    ("N32 50.639 W117 31.854", 32.84398, -117.53090),     # hemisphere first
    ("N 32° 40.5' W 117° 30.2'", 32.675, -117.50333),
    ("32 40.5 / 117 30.2", 32.675, -117.50333),           # slash, no hemisphere
    ("32 40.5N / 117 30.2W", 32.675, -117.50333),
    ("32-40.5 117-30.2", 32.675, -117.50333),             # dash between deg and min
    ("32.675, -117.503", 32.675, -117.503),               # decimal degrees
    ("32.675,-117.503", 32.675, -117.503),
    ("N32.675 W117.503", 32.675, -117.503),
    ("32°40.5'N 117°30.2'W", 32.675, -117.50333),
    ("N30 22.1 W116 05.3", 30.36833, -116.08833),         # northern Baja
])
def test_common_forum_formats_parse(raw, lat, lon):
    p = coords.parse_coords(raw)
    assert p is not None
    assert p["lat"] == pytest.approx(lat, abs=1e-4)
    assert p["lon"] == pytest.approx(lon, abs=1e-4)


def test_negative_decimal_longitude_is_not_read_as_a_dash():
    assert coords.normalise("32.675, -117.503") == "32.675, -117.503"


@pytest.mark.parametrize("lat,lon,ok", [
    (32.60, -117.40, True),    # 9 Mile Bank
    (32.84, -117.53, True),    # off La Jolla
    (33.40, -118.40, True),    # Catalina channel
    (32.57, -119.13, True),    # Tanner / Cortes
    (30.37, -116.09, True),    # off San Quintin
    (28.20, -115.20, True),    # Cedros
    (32.72, -117.16, False),   # downtown San Diego
    (33.60, -117.70, False),   # Irvine
    (31.00, -115.00, False),   # Baja interior
    (30.00, -114.50, False),   # Gulf of California
    (27.00, -114.50, False),   # south of northern Baja
    (36.00, -121.50, False),   # Big Sur
    (32.70, -125.00, False),   # far offshore
])
def test_pin_area_is_offshore_socal_and_northern_baja(lat, lon, ok):
    assert coords.in_pin_area(lat, lon) is ok


def test_find_coords_reads_every_position_and_skips_prose():
    text = ("Started at (N32 50.639 W117 31.854), slid up to 32 58.634 / 117 29.124 later. "
            "Biggest was 32.5 lb, ran 117.4 miles total. 30 fish at 32 degrees. "
            "Same spot again: N32 50.639 W117 31.854")
    got = coords.find_coords(text)
    assert [(round(p["lat"], 3), round(p["lon"], 3)) for p in got] == [(32.844, -117.531), (32.977, -117.485)]


def test_find_coords_drops_points_on_land():
    assert coords.find_coords("met up at 32 43.2 N 117 09.6 W for breakfast") == []


# ------------------------------------------------------------------ pins

@pytest.fixture
def db(tmp_path):
    p = tmp_path / "paddies.db"
    conn = ingest_bd.open_db(p)
    ingest_bd.ensure_schema(conn)
    conn.close()
    c = extract.open_db(p)
    extract.ensure_schema(c)
    c.close()
    return p


def _source(c, sid, text, published="2026-11-18T20:00:00+00:00", title="Report"):
    c.execute("INSERT INTO paddy_sources (id, source, feed_id, url, title, author, published_at, "
              "fetched_at, raw_text, truncated) VALUES (?, 'bdoutdoors', 'bd-socal-offshore', ?, ?, "
              "'someone', ?, ?, ?, 0)",
              (sid, f"https://www.bdoutdoors.com/forums/threads/{sid}.1/", title, published,
               published, text))


def _mention(c, sid, typ, payload, bank=None, lat=None, lon=None):
    c.execute('INSERT INTO report_mentions (source_id, feed_id, type, trip_date, bank, lat, lon, '
              '"precision", payload, confidence, quote, extracted_at) '
              "VALUES (?, 'bd-socal-offshore', ?, '2026-11-18', ?, ?, ?, NULL, ?, 0.9, 'q', '2026-11-19')",
              (sid, typ, bank, lat, lon, json.dumps(payload)))


def _build(db):
    conn = sqlite3.connect(db)
    gaz = spots.Gazetteer()
    spots.rebuild(conn, gaz)
    data = spots.build_geojson(conn, gaz, now=NOW)
    conn.close()
    return data


def _posted(data):
    return [f for f in data["features"] if f["properties"]["position"] == "posted"]


def test_unread_gps_from_the_extractor_becomes_a_pin_with_the_posts_species(db):
    c = sqlite3.connect(db)
    _source(c, "a", "Yellowfin and yellowtail on a paddy. N32 50.639 W117 31.854")
    # the extractor stored the raw text but an older parser left lat/lon empty
    _mention(c, "a", "position", {"kind": "gps", "raw": "N32 50.639 W117 31.854"})
    _mention(c, "a", "paddy", {"species": ["yellowfin", "yellowtail"]})
    c.commit()
    c.close()
    pins = _posted(_build(db))
    assert len(pins) == 1
    p = pins[0]["properties"]
    assert pins[0]["geometry"]["coordinates"] == pytest.approx([-117.5309, 32.84398], abs=1e-4)
    assert p["precision_nm"] == spots.COORD_PRECISION_NM
    assert p["species"] == {"yellowfin": 1, "yellowtail": 1}
    assert p["posted_at"] == "2026-11-18T20:00:00+00:00"
    assert p["last_report"] == "2026-11-18"
    assert p["sources"][0]["url"].startswith("https://www.bdoutdoors.com/forums/threads/a")
    assert p["region"] == "san_diego"


def test_positions_in_posts_the_model_never_read_still_become_pins(db):
    c = sqlite3.connect(db)
    _source(c, "r", "Reply in the thread \"Wed bite\":\nBluefin boils at 32 40.5 / 117 30.2 around 9am, "
                    "then a kelp at 32-38.0 117-25.0 with yellows.")
    c.commit()
    c.close()
    pins = _posted(_build(db))
    assert len(pins) == 2
    assert all(f["properties"]["species"] == {"bluefin": 1, "yellowtail": 1} for f in pins)


def test_text_scan_does_not_duplicate_a_point_the_extractor_already_has(db):
    c = sqlite3.connect(db)
    _source(c, "a", "Dorado at 32.675, -117.503 today")
    _mention(c, "a", "position", {"kind": "gps", "raw": "32.675, -117.503", "species": ["dorado"]},
             lat=32.675, lon=-117.503)
    c.commit()
    c.close()
    assert len(_posted(_build(db))) == 1


def test_implausible_points_are_dropped(db):
    c = sqlite3.connect(db)
    _source(c, "land", "Breakfast at 32 43.2 N 117 09.6 W then out")
    _mention(c, "land", "position", {"kind": "gps", "raw": "32 43.2 N 117 09.6 W"})
    c.commit()
    c.close()
    assert _posted(_build(db)) == []


def test_old_posts_age_out_of_the_feed(db):
    c = sqlite3.connect(db)
    _source(c, "old", "Yellowfin at 32 40.5 / 117 30.2", published="2026-10-01T20:00:00+00:00")
    c.commit()
    c.close()
    assert _posted(_build(db)) == []


# ------------------------------------------------------------------ spot names

@pytest.mark.parametrize("name,pid", [
    ("9-Mile", "9-mile-bank"), ("the 302", "302"), ("43 Fathom", "43-fathom-spot"),
    ("Coronados", "coronado-islands"), ("Tanner", "tanner-bank"), ("Cortez", "cortes-bank"),
    ("SCI", "san-clemente-island"), ("NW of SCI", "san-clemente-island"),
    ("14 Mile", "lasuen-knoll"), ("14 Mile Bank", "lasuen-knoll"),
    ("East Butterfly", "east-butterfly"), ("West Butterfly", "west-butterfly-162"),
])
def test_common_spot_names_resolve(name, pid):
    got = spots.Gazetteer().lookup(name)
    assert got is not None and got["id"] == pid


@pytest.mark.parametrize("name", ["the Butterfly", "Butterfly", "Tanner/Cortez"])
def test_ambiguous_spot_names_stay_unresolved(name):
    assert spots.Gazetteer().lookup(name) is None


# ------------------------------------------------------------------ tuna counts

@pytest.mark.parametrize("payload,expected", [
    ({"species": ["yellowfin"], "count": 12}, 12),
    ({"species": ["bluefin", "yellowfin"], "count": 5}, 5),
    ({"species": ["yellowfin"], "count": 0}, 0),
    ({"species": ["yellowfin", "yellowtail"], "count": 12}, None),   # can't split
    ({"species": ["yellowtail"], "count": 30}, None),
    ({"species": ["yellowfin"], "count": None}, None),
    ({"species": [], "count": 4}, None),
    ({"species": ["bluefin"], "count": True}, None),
])
def test_stated_tuna_only_counts_what_the_post_says(payload, expected):
    assert spots.stated_tuna(payload) == expected


def test_spot_and_pin_tuna_counts(db):
    c = sqlite3.connect(db)
    _source(c, "a", "Wide open at the 9, 12 yellowfin")
    _mention(c, "a", "bite", {"species": ["yellowfin"], "count": 12, "outcome": "wide_open"}, bank="9-mile-bank")
    _source(c, "b", "Few bluefin at the 9")
    _mention(c, "b", "bite", {"species": ["bluefin"], "count": 3}, bank="9-mile-bank")
    _source(c, "c", "Some yellowfin at the 9, didn't count")
    _mention(c, "c", "bite", {"species": ["yellowfin"], "count": None}, bank="9-mile-bank")
    _source(c, "d", "Bluefin at N32 50.639 W117 31.854, we got 4")
    _mention(c, "d", "position", {"kind": "gps", "raw": "N32 50.639 W117 31.854"})
    _mention(c, "d", "bite", {"species": ["bluefin"], "count": 4})
    _source(c, "e", "Yellowtail on the kelp at 32 40.5 / 117 30.2")
    c.commit()
    c.close()
    data = _build(db)
    by_id = {f["properties"]["id"]: f["properties"] for f in data["features"]}
    nine = by_id["9-mile-bank"]
    assert nine["tuna_7d"] == 15 and nine["tuna_reports_7d"] == 2 and nine["tuna"] is None
    pins = {round(f["geometry"]["coordinates"][1], 1): f["properties"] for f in _posted(data)}
    assert pins[32.8]["tuna"] == 4 and pins[32.8]["tuna_7d"] == 4
    assert pins[32.7]["tuna"] is None and pins[32.7]["tuna_7d"] is None
    assert pins[32.7]["tuna_reports_7d"] == 0
    assert pins[32.8]["sources"][0]["date"] == "2026-11-18"
