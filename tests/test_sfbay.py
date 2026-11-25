"""SF Bay Area (NorCal) parser, metric and health rules.

The HTML fixture is synthetic (made-up boats, the same markup shape as
norcalfishreports.com boats.php, including its unclosed <tr> tags).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from src import norcal as N
from src import scrape_norcal as S
from src import export_sfbay as E
from src import sfbay_health as H

DAY = date(2026, 7, 18)


def _row(boat, bslug, landing, lslug, city, detail, counts):
    return f"""
        <tr>
        <td>
            <a href="/charter_boats/{bslug}.php"><b>{boat}</b></a><br>
            <a href="/landings/{lslug}.php">{landing}</a><br>
            {city}      </td>
        <td>{detail}</td>
        <td>{counts}</td>
        <td></td>"""


def _page(rows_by_city: dict[str, list[str]], title=f"Fish Counts by Boat - July 18, 2026") -> str:
    body = ""
    for city, rows in rows_by_city.items():
        body += f"""<h2 class='text-center'>{city} Fish Counts</h2>
        <table class='table table-stripped'><thead><tr>
          <th>Boat</th><th>Trip Details</th><th>Dock Totals</th><th>Audio</th>
        </tr></thead><tbody>{''.join(rows)}</tbody></table>"""
    return f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>"


PAGE = _page({
    "Emeryville": [
        _row("Test Wolf", "testwolf", "Fish Emeryville", "fish_emeryville", "Emeryville, CA",
             "20 Anglers<br>Full Day", "40 Lingcod, 200 Rockfish"),
        _row("Tiny Six", "tinysix", "Fish Emeryville", "fish_emeryville", "Emeryville, CA",
             "6 Anglers<br>1/2 Day AM", "1 Lingcod, 60 Rockfish"),
    ],
    "Berkeley": [
        _row("Salmon Queen", "salmonqueen", "Bay Charters", "bay_charters", "Berkeley, CA",
             "10 Anglers<br>Full Day San Mateo Coastline",
             "12 Chinoook Salmon, 1 Striped Bass, 2 California Halibut Released"),
    ],
    "Half Moon Bay": [
        _row("Coast Runner (Half Moon Bay, CA)", "coastrunner", "HMB Sportfishing", "hmb", "Half Moon Bay, CA",
             "15 Anglers<br>Crab Combo", "150 Dungeness Crab, 90 Rockfish"),
    ],
    "Bodega Bay": [
        _row("North Boat", "northboat", "Bodega Center", "bodega", "Bodega Bay, CA",
             "12 Anglers<br>Full Day", "20 King Salmon, 3 Mystery Fish"),
    ],
})


def test_parse_day_rows_regions_and_species():
    trips, no_counts = S.parse_day(PAGE, DAY)
    assert not no_counts
    by = {t["boat"]: t for t in trips}
    assert set(by) == {"Test Wolf", "Tiny Six", "Salmon Queen", "Coast Runner", "North Boat"}
    assert by["Coast Runner"]["region"] == "sf_bay" and by["Coast Runner"]["port"] == "Half Moon Bay"
    assert by["North Boat"]["region"] == "norcal_other"
    sq = by["Salmon Queen"]
    assert sq["anglers"] == 10 and sq["trip_type_raw"] == "Full Day San Mateo Coastline"
    assert json.loads(sq["landed_json"]) == {"King Salmon": 12, "Striped Bass": 1}
    assert json.loads(sq["released_json"]) == {"California Halibut": 2}
    assert by["Tiny Six"]["trip_length"].startswith("Half Day")
    assert by["North Boat"]["_unknowns"] == [("Mystery Fish", 3)]


def test_wrong_page_date_rejected_and_no_count_day_detected():
    assert S.parse_day(PAGE, DAY + timedelta(days=1)) == ([], False)
    fallback = "<html><h1>Dock Totals - November 12, 2026</h1>nothing</html>"
    assert S.parse_day(fallback, date(2026, 11, 16)) == ([], True)


@pytest.mark.parametrize("label,landed,anglers,target,rate", [
    ("Full Day", {"Rockfish": 200, "Lingcod": 40}, 20, "rockfish", 1.0),
    ("Full Day", {"King Salmon": 12, "Striped Bass": 1}, 10, "salmon", 0.6),
    ("Crab Combo", {"Dungeness Crab": 150, "Rockfish": 90}, 15, "crab_combo", (1.0 + 0.6) / 2),
    ("Full Day", {"Dungeness Crab": 100, "Rockfish": 100}, 10, "crab_combo", 1.0),
    ("Full Day", {"California Halibut": 15}, 10, "halibut", 0.5),
    ("Full Day", {}, 10, "unknown", None),
    ("Sturgeon", {"White Sturgeon": 3}, 10, "sturgeon", None),
    ("Salmon Trolling California Ocean", {}, 10, "salmon", 0.0),
])
def test_target_and_limit_rate(label, landed, anglers, target, rate):
    t = N.infer_target(label, landed, anglers)
    assert t == target
    r = N.limit_rate(t, landed, anglers)
    assert (r is None and rate is None) or r == pytest.approx(rate)


def test_skunk_borrows_boat_target():
    trips = [
        {"date": "2026-07-10", "boat": "A", "target": "salmon"},
        {"date": "2026-07-12", "boat": "A", "target": "salmon"},
        {"date": "2026-07-13", "boat": "A", "target": "unknown"},
        {"date": "2026-09-30", "boat": "A", "target": "unknown"},
    ]
    N.fill_unknown_targets(trips)
    assert trips[2]["target"] == "salmon"
    assert trips[3]["target"] == "unknown"   # nothing within 14 days


def test_trip_length_never_fails():
    assert N.trip_length("7 Hour") == ("Full Day", 0.75)
    assert N.trip_length("1/4 Day") == ("Half Day", 0.25)
    assert N.trip_length("Bay")[0] == "Full Day"
    assert N.trip_length("1/2 Day Twilight")[1] < 0.75


def _db():
    conn = sqlite3.connect(":memory:")
    S.ensure_schema(conn)
    return conn


def test_insert_idempotent_and_export_excludes_other_regions():
    conn = _db()
    trips, _ = S.parse_day(PAGE, DAY)
    today = DAY + timedelta(days=30)
    assert S.insert_trips(conn, trips, today=today) == 5
    assert S.insert_trips(conn, trips, today=today) == 0          # old day: insert-only
    p = E.build_payload(conn, today=DAY + timedelta(days=1))
    names = {b["name"] for b in p["BOATS"]}
    assert "North Boat" not in names and "Coast Runner" in names
    six = {b["name"]: b["sixpack"] for b in p["BOATS"]}
    assert six["Tiny Six"] is True and six["Test Wolf"] is False
    assert p["TRIP_FIELDS"][5] == "limitRate"
    assert all(len(t) == len(p["TRIP_FIELDS"]) for t in p["TRIPS"])


def test_recent_day_updates_counts_in_place():
    conn = _db()
    trips, _ = S.parse_day(PAGE, DAY)
    S.insert_trips(conn, trips, today=DAY)
    trips[0]["landed_json"] = json.dumps({"Rockfish": 199})
    S.insert_trips(conn, trips, today=DAY)
    assert conn.execute("SELECT COUNT(*) FROM norcal_trips").fetchone()[0] == 5
    assert conn.execute("SELECT landed_json FROM norcal_trips WHERE boat='Test Wolf'").fetchone()[0] == '{"Rockfish": 199}'


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_block_stops_and_is_sticky(tmp_path):
    conn = _db()
    f = S.Fetcher(cache_dir=tmp_path, min_delay=0, max_delay=0)
    f.session.get = lambda *a, **k: _Resp(403)
    with pytest.raises(S.SourceBlocked):
        S.scrape_days(conn, [DAY], fetcher=f, today=DAY)
    assert conn.execute("SELECT error FROM norcal_fetch_log").fetchone()[0] == "blocked"
    assert S.run_daily(conn) is None                              # sticky until owner clears
    probs = H.check(conn, today=DAY)
    assert any(p.key == "sfbay:blocked" and p.severity == "blocked" for p in probs)


def test_challenge_page_counts_as_block(tmp_path):
    f = S.Fetcher(cache_dir=tmp_path, min_delay=0, max_delay=0)
    f.session.get = lambda *a, **k: _Resp(200, "<html>Attention Required! captcha</html>")
    with pytest.raises(S.SourceBlocked):
        f.get_day(DAY, today=DAY)


def test_cache_used_for_old_days(tmp_path):
    f = S.Fetcher(cache_dir=tmp_path, min_delay=0, max_delay=0)
    calls = []
    f.session.get = lambda *a, **k: calls.append(1) or _Resp(200, PAGE)
    f.get_day(DAY, today=DAY + timedelta(days=10))
    html, cached = f.get_day(DAY, today=DAY + timedelta(days=10))
    assert cached and len(calls) == 1 and "Test Wolf" in html


def test_health_no_alert_on_no_trip_days():
    conn = _db()
    now = datetime(2026, 11, 25, 18, tzinfo=timezone.utc)
    for i in range(1, 10):
        S.log_fetch(conn, date(2026, 11, 25) - timedelta(days=i), 200, 0, True)
    conn.execute("UPDATE norcal_fetch_log SET fetched_at = ?", (now.isoformat(),))
    assert H.check(conn, today=date(2026, 11, 25), now=now) == []


def test_health_flags_layout_change_and_stale_fetch():
    conn = _db()
    now = datetime(2026, 7, 20, 18, tzinfo=timezone.utc)
    S.log_fetch(conn, date(2026, 7, 19), 200, 0, False)
    conn.execute("UPDATE norcal_fetch_log SET fetched_at = ?", ((now - timedelta(hours=40)).isoformat(),))
    keys = {p.key for p in H.check(conn, today=date(2026, 7, 20), now=now)}
    assert {"sfbay:parse", "sfbay:fetch"} <= keys


def test_seed_roundtrip_loads_once(tmp_path):
    src = _db()
    trips, _ = S.parse_day(PAGE, DAY)
    S.insert_trips(src, trips, today=DAY + timedelta(days=30))
    S.log_fetch(src, DAY, 200, len(trips), False)
    seed = tmp_path / "seed.jsonl.gz"
    assert S.export_seed(src, seed) == (5, 1)
    dst = _db()
    S.insert_trips(dst, trips[:1], today=DAY + timedelta(days=30))   # existing row wins
    assert S.load_seed(dst, seed) == 4
    assert S.load_seed(dst, seed) is None                            # marker: once per seed
    assert dst.execute("SELECT COUNT(*) FROM norcal_trips").fetchone()[0] == 5
    assert S.load_seed(dst, tmp_path / "missing.gz") is None
