"""Schema and size budget for web/api/v1/app.json (the mobile app's dataset).

Builds the payload from the real tracker.db the same way export() does, so a
growing dataset that breaks the 250 KB gzipped budget fails here first.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import completeness as C
from src import export as E

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "tracker.db"

TOP_KEYS = {"schemaVersion", "generatedAt", "META", "LANDINGS_META", "TODAY",
            "SCHEDULE", "TRIPS", "HALF_DAY_TRIPS", "MONTHLY", "BOAT_PROFILES"}
DROPPED = {"ADMIN", "FORECAST", "REVIEWS", "SCRAPE_STATUS"}
TRIP_KEYS = {"id", "date", "year", "month", "day", "boat", "landing", "tripLength",
             "tripLengthDays", "anglers", "Bluefin", "Yellowfin", "Yellowtail", "Dorado",
             "trophyCount", "trophyPerAngler", "trophyPerAnglerPerDay", "region"}
MONTHLY_KEYS = {"year", "month", "trips", "anglerDays", "trophy", "bluefin", "yellowfin"}


@pytest.fixture(scope="module")
def built():
    if not DB.exists():
        pytest.skip("tracker.db not present")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trips WHERE is_preliminary = 0 ORDER BY date, id").fetchall()
    full_trips = [E._trip_to_js(r) for r in rows if not r["is_half_day"]]
    half = [E._trip_to_js(r, include_full_catch=True) for r in rows if r["is_half_day"]]
    sched = [E._scheduled_to_js(r) for r in conn.execute("SELECT * FROM scheduled_trips")]
    full = {
        "META": {"lastScrape": None}, "LANDINGS_META": E.LANDINGS_META,
        "TODAY": E._today_summary(full_trips), "SCHEDULE": sched,
        "TRIPS": full_trips, "HALF_DAY_TRIPS": half,
        "BOAT_PROFILES": E._boat_profiles_payload(conn),
        "ADMIN": {}, "FORECAST": {}, "REVIEWS": {}, "SCRAPE_STATUS": {},
    }
    today = date.today()
    payload = E.build_app_payload(conn, full, today=today)
    conn.close()
    return payload, today


def test_shape(built):
    p, today = built
    assert set(p) == TOP_KEYS and not (DROPPED & set(p))
    assert p["schemaVersion"] == E.APP_SCHEMA_VERSION
    assert datetime.fromisoformat(p["generatedAt"].replace("Z", "+00:00")).tzinfo
    for t in p["TRIPS"] + p["HALF_DAY_TRIPS"]:
        assert TRIP_KEYS <= set(t)
        assert t["region"] == "san_diego"
        assert not (set(t.get("fullCatch", {})) & E._TOP_SPECIES)
    assert {t["year"] for t in p["TRIPS"]} <= {today.year, today.year - 1}
    assert {t["year"] for t in p["HALF_DAY_TRIPS"]} <= {today.year}
    for m in p["MONTHLY"]:
        assert set(m) == MONTHLY_KEYS and m["year"] >= 2015


def test_schedule_is_upcoming_san_diego_with_source_id(built):
    p, today = built
    sd = {m["name"] for m in E.LANDINGS_META if m["region"] == "san_diego"}
    for s in p["SCHEDULE"]:
        assert s["departureAt"][:10] >= today.isoformat()
        assert s["landing"] in sd
        assert "sourceId" in s


def test_recent_trips_have_reported_at(built):
    p, today = built
    cutoff = (today - timedelta(days=7)).isoformat()
    recent = [t for t in p["TRIPS"] + p["HALF_DAY_TRIPS"] if t["date"] >= cutoff]
    assert all(t.get("reportedAt") for t in recent)


def test_gzipped_size_budget(built):
    p, _ = built
    body = json.dumps(p, separators=(",", ":"), default=str).encode("utf-8")
    gz = len(gzip.compress(body, 9))
    assert gz <= E.APP_JSON_GZ_BUDGET, f"app.json is {gz / 1024:.0f} KB gzipped"


def test_stale_app_json_is_flagged(tmp_path):
    conn = sqlite3.connect(":memory:")
    for ddl in ("CREATE TABLE scrape_log (landing, status, started_at)",
                "CREATE TABLE trips (date, landing)",
                "CREATE TABLE ocean_temps (date, location)",
                "CREATE TABLE scheduled_trips (landing, scraped_at)"):
        conn.execute(ddl)
    for t in C.FEEDS:
        conn.execute(f"CREATE TABLE {t} (date)")
    now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    f = tmp_path / "app.json"

    def keys():
        return {p.key for p in C.check(conn, today=now.date(), now=now, app_json=f)}

    assert "export:app.json" in keys()                      # missing file
    f.write_text(json.dumps({"generatedAt": "2026-11-22T00:00:00Z"}))
    assert "export:app.json" in keys()                      # 2.5 days old
    f.write_text(json.dumps({"generatedAt": "2026-11-24T06:00:00Z"}))
    assert "export:app.json" not in keys()


def test_boat_profiles_are_san_diego_only(built):
    p, _ = built
    sd = {m["name"] for m in E.LANDINGS_META if m.get("region") == "san_diego"}
    assert p["BOAT_PROFILES"], "expected some SD boat profiles"
    assert all(v["landing"] in sd for v in p["BOAT_PROFILES"].values())
