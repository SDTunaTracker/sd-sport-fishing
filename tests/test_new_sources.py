"""Offline tests for src/youtube.py and src/enso.py (no network)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src import enso, youtube


# ── YouTube matching ─────────────────────────────────────────────────────────

def test_match_requires_boat_fish_and_context():
    assert youtube.is_match("Pacific Queen", "Pacific Queen 3 day yellowfin tuna trip - San Diego")
    assert youtube.is_match("Tribute", "Tribute 1.5 day bluefin on the kite", "Seaforth Sportfishing")


def test_match_rejects_common_word_names_without_fishing_context():
    assert not youtube.is_match("Liberty", "Statue of Liberty tour 4K")
    assert not youtube.is_match("Dolphin", "Dolphin pod off Dana Point, whale watching")  # no fish word
    assert not youtube.is_match("Fortune", "Wheel of Fortune fishing category")            # no context word


def test_match_whole_word_only():
    assert not youtube.is_match("Islander", "Islanders hockey: tuna fishing jokes in San Diego")


def test_export_json_caps_per_boat(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript(youtube.SCHEMA)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(9):
        conn.execute("INSERT INTO boat_videos VALUES (?,?,?,?,?,?,?)",
                     (f"vid{i}", "Pacific Queen", f"PQ {i}", "ch", f"2026-0{i+1}-01T00:00:00Z", now, now))
    out = tmp_path / "boat_videos.json"
    assert youtube.export_json(conn, out) == youtube.PER_BOAT
    data = json.loads(out.read_text(encoding="utf-8"))
    vids = data["boats"]["Pacific Queen"]
    assert vids[0]["id"] == "vid8" and vids[0]["published"] == "2026-09-01"  # newest first


def test_purge_drops_unconfirmed_after_30_days(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.executescript(youtube.SCHEMA)
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO boat_videos VALUES ('a','B','t','c',NULL,?,?)", (old, old))
    conn.execute("INSERT INTO boat_videos VALUES ('b','B','t','c',NULL,?,?)", (new, new))
    assert youtube.purge_stale(conn) == 1
    assert [r[0] for r in conn.execute("SELECT video_id FROM boat_videos")] == ["b"]


# ── ENSO ─────────────────────────────────────────────────────────────────────

ONI_SAMPLE = """ SEAS  YR   TOTAL   ANOM
  DJF 1950  25.01  -1.32
  JAS 2026  29.12   2.16
  ASO 2026  29.23   2.46
"""

DISC_SAMPLE = """<html><body><p>ENSO Alert System Status: El Ni&ntilde;o Advisory</p>
<p>Synopsis: El Ni&ntilde;o continues to strengthen, with a strong El Ni&ntilde;o likely. More text.</p></body></html>"""


def test_parse_oni_and_status():
    rows = enso.parse_oni(ONI_SAMPLE)
    assert rows[-1] == ("ASO", 2026, 29.23, 2.46) and len(rows) == 3
    alert, syn = enso.parse_status(DISC_SAMPLE)
    assert alert == "El Niño Advisory"
    assert syn.startswith("El Niño continues") and syn.endswith("likely.")


def test_classify_thresholds():
    assert enso.classify(0.4) == ("Neutral", None)
    assert enso.classify(-0.5) == ("La Niña", "weak")
    assert enso.classify(1.5) == ("El Niño", "strong")
    assert enso.classify(2.46) == ("El Niño", "very strong")


def test_export_uses_latest_season_order(tmp_path):
    conn = sqlite3.connect(tmp_path / "e.db")
    conn.executescript(enso.SCHEMA)
    conn.executemany("INSERT INTO enso_oni VALUES (?,?,?,?)",
                     [("NDJ", 2025, 26.0, -0.6), ("DJF", 2026, 26.1, -0.4), ("ASO", 2026, 29.2, 2.46)])
    conn.execute("INSERT INTO enso_status VALUES ('2026-11-25T00:00:00+00:00','El Niño Advisory','x.')")
    d = enso.export_json(conn, tmp_path / "enso.json")
    assert d["latest"] == {"season": "ASO", "year": 2026, "oni": 2.46, "phase": "El Niño", "strength": "very strong"}
    assert [r["season"] for r in d["recent"]] == ["NDJ", "DJF", "ASO"]


# ── Copernicus currents → leaflet-velocity ───────────────────────────────────

def test_to_velocity_json_orders_north_first_and_zeros_land():
    from src import currents_cmems as cc
    nan = float("nan")
    lats = [30.0, 30.25, 30.5]            # ascending, as CMEMS returns them
    lons = [-118.0, -117.75]
    u = [[0.1, nan], [0.2, 0.3], [0.4, 0.5]]
    v = [[-0.1, nan], [-0.2, -0.3], [-0.4, -0.5]]
    g = cc.to_velocity_json(lats, lons, u, v, "2026-11-25T12:00:00Z", stride=1)
    h = g["data"][0]["header"]
    assert (h["la1"], h["la2"], h["lo1"], h["nx"], h["ny"]) == (30.5, 30.0, -118.0, 2, 3)
    assert g["data"][0]["data"] == [0.4, 0.5, 0.2, 0.3, 0.1, 0.0]   # north row first, NaN → 0
    assert g["data"][1]["header"]["parameterNumber"] == 3
    assert g["credit"] == "Generated using E.U. Copernicus Marine Service Information"
    assert g["validCells"] == 5


def test_currents_run_skips_without_credentials(monkeypatch, tmp_path):
    from src import currents_cmems as cc
    monkeypatch.delenv("COPERNICUSMARINE_SERVICE_USERNAME", raising=False)
    out = tmp_path / "g.json"
    assert "no Copernicus credentials" in cc.run(out)
    assert not out.exists()
