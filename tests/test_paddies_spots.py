"""Tests for forum spot reports: trip-report locations, geocoding, privacy, GeoJSON."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.paddies import boat_reports as br
from scraper.paddies import coords, ingest_bd, spots

LOC_BODY = ("Just got back from a 3 day on the PQ. First day we fished San Martin Island, "
            "slow pick on yellowtail. Second day the fleet was at Colonet. "
            "Found a kelp 12 miles SW of the Coronados holding dorado, water 71 degrees. "
            "Paddy at 31 50.20 N 117 10.40 W was loaded.")

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "paddies.db"
    conn = ingest_bd.open_db(p)
    ingest_bd.ensure_schema(conn)
    conn.close()
    br.open_db(p).close()
    from scraper.paddies import extract
    c = extract.open_db(p)
    extract.ensure_schema(c)
    c.close()
    return p


@pytest.fixture
def gaz():
    return spots.Gazetteer()


def _loc(**over):
    d = {"name": None, "kind": "area", "distance_nm": None, "bearing": None, "from_place": None,
         "species": [], "quality": None, "water_temp_f": None, "quote": ""}
    d.update(over)
    return d


# ------------------------------------------------------------------ validation

def test_locations_need_a_verbatim_quote_that_names_the_place():
    items = [
        _loc(name="San Martin Island", kind="island", species=["yellowtail"], quality="slow",
             quote="First day we fished San Martin Island, slow pick on yellowtail"),
        _loc(name="Cedros", kind="island", quote="we fished Cedros"),            # not in the post
        _loc(name="Guadalupe", kind="island", quote="the fleet was at Colonet"),  # quote lacks the name
        _loc(name="Colonet", kind="fleet", quote="the fleet was at Colonet"),
    ]
    out = br.validate_locations(items, LOC_BODY)
    assert [(o["name"], o["kind"]) for o in out] == [("San Martin Island", "island"), ("Colonet", "fleet")]
    assert out[0]["species"] == ["yellowtail"] and out[0]["quality"] == "slow"


def test_coordinates_and_offsets_come_from_the_quote_not_the_model():
    items = [
        _loc(name=None, kind="paddy", quote="Paddy at 31 50.20 N 117 10.40 W was loaded"),
        _loc(name="kelp", kind="kelp", distance_nm=99, bearing="N", from_place="the Coronados",
             species=["dorado"], water_temp_f=71,
             quote="Found a kelp 12 miles SW of the Coronados holding dorado, water 71 degrees"),
    ]
    out = br.validate_locations(items, LOC_BODY)
    assert out[0]["kind"] == "coords"
    assert out[0]["lat"] == pytest.approx(31.8367, abs=1e-3)
    assert out[0]["lon"] == pytest.approx(-117.1733, abs=1e-3)
    assert out[1]["distance_nm"] == 12 and out[1]["bearing_deg"] == 225.0
    assert out[1]["from_place"] == "the Coronados" and out[1]["water_temp_f"] == 71


def test_locations_are_append_only(db, monkeypatch):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO paddy_sources (id, source, feed_id, url, title, author, published_at, "
              "fetched_at, raw_text, truncated) VALUES ('s1', 'bdoutdoors', 'bd-long-range', "
              "'https://example.test/threads/s1/', 'PQ 3 day', 'x', '2026-11-12T00:00:00Z', "
              "'2026-11-12T01:00:00Z', ?, 0)", (LOC_BODY,))
    c.commit()
    c.close()
    entry = {"boat_raw": "PQ", "boat": "Pacific Queen", "trip_date": "2026-11-09", "trip_length": "3 Day",
             **{a: None for a in br.ASPECTS}, "would_rebook": None, "quotes": {}, "catch_summary": None,
             "tackle": [], "spots": [], "bait": None, "conditions": None, "signals": {},
             "locations": [_loc(name="Colonet", kind="fleet", quote="the fleet was at Colonet")]}
    monkeypatch.setattr(br, "build_prompt", lambda row, known: row["id"])
    monkeypatch.setattr(br, "match_trip", lambda *a, **k: None)
    monkeypatch.setattr(br, "load_known_boats", lambda *a, **k: {"Pacific Queen": ["Fisherman's Landing"]})
    monkeypatch.setattr(br, "REQUEST_SLEEP", 0)
    monkeypatch.setattr(br, "call_claude", lambda p: {"is_trip_report": True, "boats": [entry]})
    br.run(limit=None, db_path=db)
    conn = br.open_db(db)
    conn.execute("DELETE FROM boat_report_runs")
    conn.commit()
    conn.close()
    entry2 = dict(entry, locations=[_loc(name="San Martin Island", kind="island",
                                         quote="First day we fished San Martin Island")])
    monkeypatch.setattr(br, "call_claude", lambda p: {"is_trip_report": True, "boats": [entry2]})
    br.run(limit=None, db_path=db)
    conn = br.open_db(db)
    rows = conn.execute("SELECT name, kind, fetched_at FROM forum_locations").fetchall()
    conn.close()
    assert [tuple(r) for r in rows] == [("Colonet", "fleet", "2026-11-12T01:00:00Z")]


def test_tool_schema_requires_locations():
    item = br.REPORT_TOOL["input_schema"]["properties"]["boats"]["items"]
    assert "locations" in item["required"]
    assert set(item["properties"]["locations"]["items"]["properties"]["kind"]["enum"]) == set(br.LOCATION_KINDS)


# ------------------------------------------------------------------ geocoding

def test_gazetteer_resolves_swyc_banks_baja_places_and_forum_spellings(gaz):
    assert gaz.lookup("the 9 Mile Bank")["id"] == "9-mile-bank"
    assert gaz.lookup("43 Fathom Spot")["id"] == "43-fathom-spot"
    assert gaz.lookup("Cedros")["id"] == "cedros-island"
    assert gaz.lookup("St Martin Island")["id"] == "san-martin-island"
    assert gaz.lookup("Pt Loma")["id"] == "point-loma-kelp"
    assert gaz.lookup("Avalon")["id"] == "catalina"         # the town, not Avalon Bank
    assert gaz.lookup("the Ridge") is None                   # ambiguous: left unresolved
    assert gaz.lookup(None) is None


def test_public_point_snaps_to_a_spot_or_rounds_to_about_two_miles(gaz):
    bank = gaz.get("9-mile-bank")
    lat, lon, prec, snapped = spots.public_point(bank["lat"] + 0.004, bank["lon"] - 0.003, gaz)
    assert snapped and (lat, lon) == (bank["lat"], bank["lon"]) and prec >= 2
    # open ocean far from any spot -> grid
    lat, lon, prec, snapped = spots.public_point(31.12345, -119.98765, gaz)
    assert snapped is None and prec == spots.GRID_PRECISION_NM
    assert coords.haversine_nm(lat, lon, 31.12345, -119.98765) <= 1.5
    assert (lat, lon) != (31.12345, -119.98765)


# ------------------------------------------------------------------ build + publish

def _seed(db):
    c = sqlite3.connect(db)
    c.executemany(
        "INSERT INTO paddy_sources (id, source, feed_id, url, title, author, published_at, "
        "fetched_at, raw_text, truncated) VALUES (?, 'bdoutdoors', ?, ?, ?, 'someone', ?, ?, 'x', 0)",
        [("a", "bd-socal-offshore", "https://example.test/a/", "9 mile yesterday",
          "2026-11-18T20:00:00Z", "2026-11-18T21:00:00Z"),
         ("b", "bd-long-range", "https://example.test/b/", "PQ 3 day",
          "2026-11-12T20:00:00Z", "2026-11-12T21:00:00Z"),
         ("old", "bd-socal-offshore", "https://example.test/old/", "Sept",
          "2026-09-01T20:00:00Z", "2026-09-01T21:00:00Z")])
    c.executemany(
        'INSERT INTO report_mentions (source_id, feed_id, type, trip_date, bank, lat, lon, "precision", '
        "payload, confidence, quote, extracted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?, '2026-11-19')",
        [("a", "bd-socal-offshore", "bite", "2026-11-18", "9-mile-bank", None, None, "bank",
          json.dumps({"species": ["yellowfin"], "outcome": "wide_open", "water_temp_f": 68}), 0.9,
          "wide open at the 9"),
         ("a", "bd-socal-offshore", "position", "2026-11-18", None, 32.12345, -118.65432, None,
          json.dumps({"kind": "gps", "raw": "32.12345 -118.65432"}), 0.9, "32.12345 -118.65432"),
         ("old", "bd-socal-offshore", "bite", "2026-09-01", "9-mile-bank", None, None, "bank",
          json.dumps({"species": ["bluefin"]}), 0.9, "old")])
    c.commit()
    c.close()
    conn = br.open_db(db)
    conn.executemany(
        "INSERT INTO forum_locations (source_id, feed_id, boat, trip_date, trip_length, published_at, "
        "fetched_at, name, kind, distance_nm, bearing_deg, from_place, lat, lon, species, quality, "
        "water_temp_f, quote, extracted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, '2026-11-13')",
        [("b", "bd-long-range", "Pacific Queen", "2026-11-10", "3 Day", "2026-11-12T20:00:00Z",
          "2026-11-12T21:00:00Z", "San Martin Island", "island", None, None, None, None, None,
          '["yellowtail"]', "slow", None, "fished San Martin Island"),
         ("b", "bd-long-range", "Pacific Queen", "2026-11-11", "3 Day", "2026-11-12T20:00:00Z",
          "2026-11-12T21:00:00Z", "kelp", "kelp", 12, 225.0, "the Coronados", None, None,
          '["dorado"]', "good", 71, "kelp 12 miles SW of the Coronados"),
         ("b", "bd-long-range", "Pacific Queen", "2026-11-11", "3 Day", "2026-11-12T20:00:00Z",
          "2026-11-12T21:00:00Z", "the Ridge", "area", None, None, None, None, None, "[]", None, None,
          "the Ridge")])
    conn.commit()
    return conn


def test_rebuild_geocodes_every_source_and_keeps_exact_points_private(db, gaz):
    conn = _seed(db)
    stats = spots.rebuild(conn, gaz)
    assert stats["rows"] == 6 and stats["unresolved_names"] == {"the Ridge": 1}
    conn.row_factory = sqlite3.Row
    rows = {(r["origin"], r["kind"]): r for r in conn.execute(
        "SELECT * FROM forum_spot_reports WHERE source_id != 'old'")}
    gps = rows[("paddy_mention", "coords")]
    assert (gps["lat_exact"], gps["lon_exact"]) == (32.12345, -118.65432)
    assert (gps["lat_pub"], gps["lon_pub"]) != (32.12345, -118.65432)
    assert gps["fetched_at"] == "2026-11-18T21:00:00Z" and gps["url"] == "https://example.test/a/"
    kelp = rows[("trip_location", "kelp")]
    assert kelp["geocode"] == "offset" and kelp["quality"] == "good"
    assert kelp["precision_nm"] >= 3                   # 12 nm offset -> 3 nm uncertainty
    bite = rows[("paddy_mention", "bite")]
    assert bite["place_id"] == "9-mile-bank" and bite["quality"] == "wide_open"


def test_geojson_has_recent_spots_only_and_no_exact_numbers_or_quotes(db, gaz):
    conn = _seed(db)
    spots.rebuild(conn, gaz)
    gj = spots.build_geojson(conn, gaz, now=NOW)
    names = {f["properties"]["name"]: f for f in gj["features"]}
    assert "9 Mile Bank" in names and "San Martin Island" in names
    nine = names["9 Mile Bank"]["properties"]
    assert nine["reports_7d"] == 1 and nine["reports_14d"] == 1       # September row is out
    assert nine["species"] == {"yellowfin": 1} and nine["quality"] == {"wide_open": 1}
    assert nine["sources"][0]["url"] == "https://example.test/a/"
    assert names["San Martin Island"]["properties"]["reports_7d"] == 0
    text = json.dumps(gj)
    assert "32.12345" not in text and "118.65432" not in text
    assert "quote" not in text and "someone" not in text
    assert gj["label"] == "Recent forum reports by spot" and gj["window_days"] == 14


def test_research_csv_has_the_dated_series(db, gaz, tmp_path):
    conn = _seed(db)
    spots.rebuild(conn, gaz)
    n = spots.write_research_csv(tmp_path / "r.csv", conn)
    head = (tmp_path / "r.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
    assert n == 6 and {"report_date", "fetched_at", "species", "quality", "precision_nm", "url"} <= set(head)
