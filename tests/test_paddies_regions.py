"""Region tags (san_diego / oc_la / both) for BloodyDecks items."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.paddies import boat_reports as br
from scraper.paddies import extract, feeds, ingest_bd, regions, spots
from scraper.paddies import write_json as wj


def test_landing_regions_follow_web_regions_js():
    lr = regions.landing_regions()
    assert lr["H&M Landing"] == "san_diego" and lr["Oceanside Sea Center"] == "san_diego"
    for l in ("Davey's Locker", "Dana Wharf Sportfishing", "22nd Street Landing", "Newport Landing",
              "Long Beach Sportfishing", "Redondo Beach Sportfishing", "Marina Del Rey Sportfishing",
              "Pierpoint Landing"):
        assert lr[l] == "oc_la", l
    # the fallback list mirrors regions.js
    assert {n for names in regions._FALLBACK.values() for n in names} == set(lr)


@pytest.mark.parametrize("name,region", [
    ("Catalina", "oc_la"), ("the Isthmus", "oc_la"), ("Avalon", "oc_la"),
    ("Horseshoe Kelp", "oc_la"), ("14 Mile Bank", "oc_la"), ("Lasuen Knoll", "oc_la"),
    ("Palos Verdes", "oc_la"), ("Huntington Flats", "oc_la"), ("Dana Point", "oc_la"),
    ("Santa Cruz Island", "oc_la"), ("San Clemente Island", "both"), ("Oceanside", "both"),
    ("9 Mile Bank", "san_diego"), ("Coronado Islands", "san_diego"), ("Cedros", "san_diego"),
])
def test_spots_get_the_region_they_are_in(name, region):
    p = spots.Gazetteer().lookup(name)
    assert p, name
    assert regions.region_for_point(p["lat"], p["lon"]) == region


def test_item_region_unions_landing_spots_title_then_feed():
    g = spots.Gazetteer()
    cat = g.lookup("Catalina")
    nine = g.lookup("9 Mile Bank")
    assert regions.item_region(landings=["Davey's Locker"]) == "oc_la"
    assert regions.item_region(landings=["H&M Landing"], places=[nine]) == "san_diego"
    assert regions.item_region(landings=["H&M Landing"], places=[cat]) == "both"
    assert regions.item_region(title="Catalina yellowtail report 11/20") == "oc_la"
    assert regions.item_region(title="Point Loma kelp calico") == "san_diego"
    assert regions.item_region(title="random gear question", feed_id="bd-long-range") == "san_diego"
    assert regions.item_region(title="random gear question", feed_id="bd-socal-sportboats") is None
    assert regions.in_region("both", "oc_la") and not regions.in_region(None, "oc_la")


def test_new_california_feed_goes_to_the_paddy_extractor():
    f = feeds.get_feed("bd-california")
    assert f and f["kind"] == "paddies" and f["initial_backfill_days"] == 120
    assert "bd-california" in extract.PADDY_FEED_IDS


# ------------------------------------------------------------------ exports

@pytest.fixture
def db(tmp_path):
    p = tmp_path / "paddies.db"
    conn = ingest_bd.open_db(p)
    ingest_bd.ensure_schema(conn)
    conn.close()
    br.open_db(p).close()
    return p


def _add(db, sid, title, boat, landing, spots_, length="Full Day", day="2026-11-20"):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO paddy_sources (id, source, feed_id, url, title, author, published_at, "
              "fetched_at, raw_text, truncated) VALUES (?, 'bdoutdoors', 'bd-socal-sportboats', ?, ?, "
              "'x', ?, ?, 'x', 0)", (sid, f"https://example.test/{sid}/", title,
                                     day + "T20:00:00Z", day + "T21:00:00Z"))
    c.execute("INSERT INTO forum_boat_reports (source_id, feed_id, boat_raw, boat, landing, trip_date, "
              "trip_length, quotes, tackle, spots, bait, match_confidence, extracted_at) "
              "VALUES (?, 'bd-socal-sportboats', ?, ?, ?, ?, ?, '{}', '[\"40 lb\"]', ?, 'sardine', 0.95, ?)",
              (sid, boat, boat, landing, day, length, json.dumps(spots_), day))
    c.commit()
    c.close()


def test_boat_reports_and_whats_working_are_region_tagged(db):
    _add(db, "a", "Thunderbird full day", "Thunderbird", "Davey's Locker", ["Catalina"])
    _add(db, "b", "Pacific Queen 1.5 day", "Pacific Queen", "Fisherman's Landing", ["9 Mile Bank"])
    _add(db, "c", "Dolphin to SCI", "Dolphin", "Fisherman's Landing", ["San Clemente Island"])
    _add(db, "d", "Vagabond 10 day", "Vagabond", "Fisherman's Landing", ["Potato Bank", "Catalina"],
         length="10 Day")
    conn = br.open_db(db)
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    ex = br.build_export(conn, now=now)
    assert ex["boats"]["Thunderbird"]["region"] == "oc_la"
    assert ex["boats"]["Pacific Queen"]["region"] == "san_diego"
    assert ex["boats"]["Dolphin"]["reports"][0]["region"] == "both"
    assert ex["boats"]["Vagabond"]["reports"][0]["region"] == "san_diego"   # long range: landing decides
    ww = br.build_whats_working(conn, now=now)
    titles = lambda cls: {i["title"] for i in cls["full"]["items"]}
    assert titles(ww["by_region"]["oc_la"]) == {"Thunderbird full day", "Dolphin to SCI"}
    assert titles(ww["by_region"]["san_diego"]) == {"Pacific Queen 1.5 day", "Dolphin to SCI"}
    assert len(ww["classes"]["full"]["items"]) == 3          # all regions together
    assert {i["region"] for i in ww["classes"]["full"]["items"]} == {"oc_la", "san_diego", "both"}
    conn.close()


def test_banks_and_spot_features_carry_a_region():
    feats = wj.load_gazetteer_features()
    banks = wj.build_banks_json(feats, "b", "z")
    by_id = {f["properties"]["id"]: f["properties"]["region"] for f in banks["features"]}
    assert by_id["catalina"] == "oc_la" and by_id["9-mile-bank"] == "san_diego"
