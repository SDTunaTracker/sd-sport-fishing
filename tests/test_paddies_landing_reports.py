"""Tests for scraper.paddies.landing_reports (the landings' own trip reports)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.paddies import boat_reports as br
from scraper.paddies import ingest_bd
from scraper.paddies import landing_reports as lr

FIX = Path(__file__).parent / "fixtures" / "landing_reports"
KNOWN = {"San Diego": ["Seaforth Sportfishing"], "Sea Watch": ["Seaforth Sportfishing"],
         "Shogun": ["Fisherman's Landing"], "Aztec": ["Seaforth Sportfishing"],
         "Freelance": ["Davey's Locker"]}


def page(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "paddies.db"
    c = ingest_bd.open_db(p)
    ingest_bd.ensure_schema(c)
    c.close()
    br.open_db(p).close()
    lr.open_db(p).close()
    return p


# ------------------------------------------------------------------ parsing

def test_listing_parses_landing_and_long_range_cards():
    items = lr.parse_listing(page("sdfr_listing.html"), "sdfr")
    assert len(items) == 24
    fl = next(i for i in items if i["report_id"] == 247456)
    assert fl["landing"] == "Fisherman's Landing" and fl["published_at"] == "2026-11-25T06:23:00"
    shogun = next(i for i in items if i["report_id"] == 247457)
    assert shogun["source_name"] == "Shogun" and "longrangesportfishing.net/reports/247457/" in shogun["url"]


def test_socal_listing_has_landing_date_and_photo_thumb():
    items = lr.parse_listing(page("scfr_listing.html"), "scfr")
    ci = next(i for i in items if i["report_id"] == 247455)
    assert ci["landing"] == "Channel Islands Sportfishing" and ci["published_at"] == "2026-11-24"
    assert ci["thumb"] == "https://media.fishreports.com/reports/img-20261124-e25ff4a2.jpg"


def test_report_body_and_photos():
    sea = lr.parse_report(page("report_seaforth.html"), lr.SITES["sdfr"]["base"])
    assert sea["body"].startswith("Sunday Returning Trips")
    assert "205 Yellowfin Tuna" in sea["body"] and "Previous Report" not in sea["body"]
    lrp = lr.parse_report(page("report_longrange.html"), "https://www.longrangesportfishing.net")
    assert lrp["body"].startswith("We couldn't have asked for better weather")
    assert len(lrp["photos"]) == 12 and all(u.startswith("https://media.fishreports.com/photos/")
                                            for u in lrp["photos"])


def test_ingest_is_polite_and_incremental(db):
    calls = []

    def fetcher(url):
        calls.append(url)
        if "saltwater.php" in url:
            return page("sdfr_listing.html") if "sandiego" in url else page("scfr_listing.html")
        return page("report_seaforth.html")

    conn = lr.open_db(db)
    s1 = lr.ingest(conn, max_pages=1, max_details=3, fetcher=fetcher, sleep=lambda s: None)
    assert s1["new_reports"] == 24 + 22 and s1["details_fetched"] == 3
    calls.clear()
    s2 = lr.ingest(conn, max_details=0, fetcher=fetcher, sleep=lambda s: None)
    assert s2["new_reports"] == 0 and len(calls) == 2          # one listing page per site, nothing else
    conn.close()


# ------------------------------------------------------------------ extraction

BODY = page("report_seaforth.html")


def _seed_report(db, rid=247404, landing="Seaforth Sportfishing", site="sdfr", body=None,
                 published="2026-11-22T16:00:00"):
    conn = lr.open_db(db)
    conn.execute("INSERT INTO landing_reports (report_id, site, url, title, source_name, author, landing, "
                 "published_at, fetched_at, body, photos) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (rid, site, f"https://example.test/fish_reports/{rid}/x.php", "Sunday Recap", landing,
                  "Seaforth Staff", landing, published, "2026-11-22T17:00:00Z",
                  body or lr.parse_report(BODY, lr.SITES["sdfr"]["base"])["body"],
                  json.dumps(["https://media.fishreports.com/photos/a.jpg"])))
    conn.commit()
    conn.close()


def _entry(**kw):
    e = {"boat_raw": "San Diego", "boat": "San Diego", "trip_date": "2026-11-22", "trip_length": "Full Day",
         "anglers": None, "species": [{"name": "yellowfin", "count": 205, "max_lb": None, "min_lb": None}],
         "size_quote": None, "bait_type": None, "bait_on_board": None, "bait_quote": None,
         "tackle": [], "tackle_quote": None, "skipper_note": "Action-packed full day on yellowfin.",
         "conditions": None, "quote": "had an action packed day reporting 205 Yellowfin Tuna"}
    e.update(kw)
    return e


def _run(db, monkeypatch, answer):
    monkeypatch.setattr(lr, "call_claude", lambda prompt: answer)
    monkeypatch.setattr(br, "load_known_boats", lambda *a, **k: KNOWN)
    monkeypatch.setattr(lr, "REQUEST_SLEEP", 0)
    return lr.run(limit=None, db_path=db)


def test_sizes_bait_and_tackle_need_quotes_from_the_post(db, monkeypatch):
    _seed_report(db)
    ans = {"is_fishing_report": True, "open_spots": [], "boats": [
        _entry(),
        _entry(boat_raw="Sea Watch", boat="Sea Watch", trip_length="1/2 Day",
               species=[{"name": "yellowfin", "count": 100, "max_lb": 25, "min_lb": None}],
               size_quote="Yellowfin to 25 pounds",                     # not in the post -> dropped
               tackle=["25 lb flyline", "#2 and #4 hooks"],
               tackle_quote="A 25lb flyline outfit has been recommended with size 2 and 4 hooks",
               bait_type="sardine", bait_quote="sardines on board"),     # not in the post -> dropped
    ]}
    st = _run(db, monkeypatch, ans)
    assert st["entries"] == 2 and st["failed"] == 0
    conn = lr.open_db(db)
    sw = conn.execute("SELECT * FROM landing_notes WHERE boat = 'Sea Watch'").fetchone()
    assert json.loads(sw["species"])[0]["max_lb"] is None and sw["size_quote"] is None
    assert json.loads(sw["tackle"]) == ["25 lb flyline", "#2 and #4 hooks"]
    assert sw["bait_type"] is None and sw["region"] == "san_diego"
    conn.close()


def test_export_boat_notes_photos_region_and_whats_working_merge(db, monkeypatch):
    _seed_report(db)
    _run(db, monkeypatch, {"is_fishing_report": True, "open_spots": [], "boats": [
        _entry(tackle=["25 lb flyline"], tackle_quote="A 25lb flyline outfit has been recommended")]})
    conn = lr.open_db(db)
    ex = lr.build_export(conn, now=datetime(2026, 11, 25, tzinfo=timezone.utc))
    note = ex["boats"]["San Diego"]["notes"][0]
    assert note["photos"] == ["https://media.fishreports.com/photos/a.jpg"]
    assert note["catch"] == [{"name": "yellowfin", "count": 205}] and note["region"] == "san_diego"
    assert ex["by_region"]["san_diego"]["notes"] and not ex["by_region"]["oc_la"]["notes"]
    conn.close()
    conn = br.open_db(db)
    ww = br.build_whats_working(conn, now=datetime(2026, 11, 25, tzinfo=timezone.utc))
    items = ww["by_region"]["san_diego"]["full"]["items"]
    assert items and items[0]["source"] == "landing" and items[0]["tackle"] == ["25 lb flyline"]
    assert not ww["by_region"]["oc_la"]["full"]["items"]
    conn.close()


def test_ocla_landing_is_tagged_and_open_spots_are_kept(db, monkeypatch):
    body = ("Todays fish count. 66 passengers 94 Whitefish 1 Yellowtail. "
            "Lots of room for Sunday's 3/4 day trip, come join us!")
    _seed_report(db, rid=9, landing="Davey's Locker", site="scfr", body=body)
    _run(db, monkeypatch, {"is_fishing_report": True,
                           "open_spots": [{"boat": "Freelance", "trip_date": "2026-11-29",
                                           "trip_length": "3/4 Day",
                                           "quote": "Lots of room for Sunday's 3/4 day trip"}],
                           "boats": [_entry(boat_raw="Freelance", boat="Freelance", trip_length="3/4 Day",
                                            species=[{"name": "whitefish", "count": 94, "max_lb": None,
                                                      "min_lb": None}], quote="66 passengers 94 Whitefish")]})
    conn = lr.open_db(db)
    assert conn.execute("SELECT region FROM landing_notes").fetchone()[0] == "oc_la"
    ex = lr.build_export(conn, now=datetime(2026, 11, 22, tzinfo=timezone.utc))
    assert ex["open_spots"][0]["boat"] == "Freelance" and ex["open_spots"][0]["region"] == "oc_la"
    conn.close()


def test_missing_key_stops_before_any_call(db, monkeypatch):
    _seed_report(db)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(lr, "call_claude", lambda p: pytest.fail("called Claude without a key"))
    st = lr.run(limit=None, db_path=db)
    assert st["last_error"] == "ANTHROPIC_API_KEY is not set"


def test_notes_are_append_only(db, monkeypatch):
    _seed_report(db)
    _run(db, monkeypatch, {"is_fishing_report": True, "open_spots": [], "boats": [_entry()]})
    conn = lr.open_db(db)
    conn.execute("DELETE FROM landing_report_runs")
    conn.commit()
    conn.close()
    _run(db, monkeypatch, {"is_fishing_report": True, "open_spots": [],
                           "boats": [_entry(skipper_note="different")]})
    conn = lr.open_db(db)
    assert [r[0] for r in conn.execute("SELECT skipper_note FROM landing_notes")] == \
        ["Action-packed full day on yellowfin."]
    conn.close()
