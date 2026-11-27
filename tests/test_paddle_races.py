"""Paddle Tracker races: data files, course geometry, leg scoring, forecast build (offline)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.paddle import course as CO
from src.paddle import forecast as F
from src.paddle import score as S

ROOT = Path(__file__).resolve().parents[1]
RACES = json.loads((ROOT / "web/api/v1/paddle_races.json").read_text(encoding="utf-8"))


# ── data files ──────────────────────────────────────────────────────────────

def test_race_ids_unique_and_fields():
    ids = [r["id"] for r in RACES["races"]]
    assert len(ids) == len(set(ids))
    for r in RACES["races"]:
        assert r["name"] and r["status"] and r["location"]["name"]
        assert r["distances"], r["id"]
        if r["date"]:
            assert str(r["year"]) == r["date"][:4]
        if r.get("paddleguru"):
            assert r["paddleguru"].startswith("https://paddleguru.com/")
        if r.get("startLocal"):
            h, m = r["startLocal"].split(":")
            assert 0 <= int(h) < 24 and 0 <= int(m) < 60


def test_every_course_file_validates_and_is_used():
    files = {p.stem for p in CO.COURSES.glob("*.geojson")}
    used = {d["courseId"] for r in RACES["races"] for d in r["distances"] if d.get("courseId")}
    assert used <= files
    for cid in files:
        fc = CO.load(cid)
        assert fc["properties"]["id"] == cid
        assert fc["properties"]["status"]


def test_loop_course_matches_published_length():
    fc = CO.load("the-loop")
    assert 10.5 <= CO.total_mi(fc) <= 12.0          # published 11.25 mi
    legs = CO.legs(fc)
    assert legs[0]["water"] == "ocean" and any(l.get("current") == "PCT0031" for l in legs)


def test_validate_catches_mismatched_waypoint():
    fc = CO.load("plank-to-plank")
    fc = json.loads(json.dumps(fc))
    fc["features"][1]["geometry"]["coordinates"] = [-117.0, 32.0]
    assert any("not on the course line" in e for e in CO.validate(fc))


def test_bearing_and_distance():
    assert CO.bearing_deg(32.7, -117.2, 32.8, -117.2) == pytest.approx(0, abs=0.01)
    assert CO.bearing_deg(32.7, -117.2, 32.7, -117.1) == pytest.approx(90, abs=0.1)
    assert CO.distance_mi(32.7, -117.2, 32.8, -117.2) == pytest.approx(6.91, abs=0.02)


# ── scoring ─────────────────────────────────────────────────────────────────

def _s(kt, frm, bearing, gust=None, ocean=True):
    return S.leg_score((kt, gust or kt, frm), bearing, ocean)


def test_downwind_beats_light_beats_side_beats_head():
    down = _s(12, 90, 270)
    light = _s(3, 0, 270)
    side = _s(12, 0, 270)
    head = _s(12, 270, 270)
    assert down["windRel"] == "tail" and side["windRel"] == "cross" and head["windRel"] == "head"
    assert light["windRel"] == "light"
    assert down["score"] > light["score"] > side["score"] > head["score"]
    assert down["label"] == "Great" and head["label"] in ("Poor", "Hard")


def test_stronger_and_gustier_is_worse_upwind():
    assert _s(15, 270, 270)["score"] < _s(9, 270, 270)["score"]
    assert _s(12, 0, 270, gust=24)["score"] < _s(12, 0, 270)["score"]


def test_light_wind_with_model_gusts_stays_light():
    assert _s(3, 200, 0, gust=9)["windRel"] == "light"


def test_swell_against_and_big_swell_penalised():
    base = S.leg_score((3, 3, 0), 270, True)["score"]
    against = S.leg_score((3, 3, 0), 270, True, swell=(5, 12, 270))["score"]   # from W, paddling W
    withit = S.leg_score((3, 3, 0), 270, True, swell=(4, 12, 90))["score"]
    big = S.leg_score((3, 3, 0), 270, True, swell=(7, 14, 180))["score"]
    assert against < base <= withit and big < base


def test_swell_ignored_on_bay_legs():
    assert S.leg_score((3, 3, 0), 270, False, swell=(8, 14, 270))["score"] == 3.0


def test_current_with_and_against():
    assert S.leg_score((3, 3, 0), 0, False, current_kt=1.0)["score"] > 3.0
    assert S.leg_score((3, 3, 0), 0, False, current_kt=-1.0)["score"] < 3.0


def test_reason_reads_plainly():
    legs = [
        {"leg": "on the ocean leg", "miles": 3, "windKt": 12, "windFrom": 315, "windRel": "tail", "score": 3.8},
        {"leg": "into the bay", "miles": 2, "windKt": 12, "windFrom": 315, "windRel": "head", "score": 1.0},
    ]
    assert S.reason(legs) == "NW 12 kt → downwind on the ocean leg, headwind into the bay"
    o = S.overall(legs, water_f=64)
    assert o["label"] == "Fair" and o["reason"].startswith("NW 12 kt")


def test_reason_cold_water_and_light():
    legs = [{"leg": "down the Silver Strand", "miles": 5, "windKt": 3, "windFrom": 200, "windRel": "light", "score": 3}]
    assert S.reason(legs, water_f=55) == "Light wind (SSW 3 kt) all race; cold water (55°F)"


# ── current interpolation ──────────────────────────────────────────────────

def test_current_at_interpolates_between_slack_and_max():
    t0 = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    ev = [{"t": t0.isoformat(), "type": "slack", "kt": 0, "towardDeg": None},
          {"t": (t0 + timedelta(hours=3)).isoformat(), "type": "ebb", "kt": 2.0, "towardDeg": 190}]
    assert F.current_at(ev, t0)[0] == pytest.approx(0)
    kt, toward = F.current_at(ev, t0 + timedelta(hours=1.5))
    assert kt == pytest.approx(1.0, abs=0.01) and toward == 190
    assert F.current_at(ev, t0 + timedelta(hours=5)) is None


# ── build, offline ─────────────────────────────────────────────────────────

@pytest.fixture
def offline(monkeypatch):
    def wind(pts):
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        hrs = {int((now + timedelta(hours=h)).timestamp()): (12.0, 315.0, 16.0) for h in range(-24, 24 * 8)}
        return [dict(hrs) for _ in pts]
    monkeypatch.setattr(F.SF, "wind_hourly", wind)
    monkeypatch.setattr(F.SF, "mop_series", lambda *a, **k: {})
    monkeypatch.setattr(F.SF, "currents", lambda *a, **k: [])
    monkeypatch.setattr(F, "water_temp", lambda now: {"station": "201", "f": 64, "c": 17.8, "t": now.isoformat()})


def test_build_skips_races_out_of_range(offline):
    p = F.build(now=datetime(2026, 11, 27, 18, tzinfo=timezone.utc))
    assert p["races"] == {}


def test_build_preview_scores_every_leg(offline, tmp_path):
    now = datetime.now(timezone.utc)
    day = (now.astimezone(F.TZ).date() + timedelta(days=1)).isoformat()
    p = F.build(now=now, as_if={"the-loop-2025": day})
    e = p["races"]["the-loop-2025"]["loop"]
    assert e["preview"] and e["startAssumed"] and e["start"] == "08:00"
    assert all(l["score"] is not None for l in e["legs"])
    assert e["reason"].startswith("NW 12 kt → ")
    # pace: last leg ETA ≈ start + 11 mi / 4.5 mph
    first, last = datetime.fromisoformat(e["legs"][0]["eta"]), datetime.fromisoformat(e["legs"][-1]["eta"])
    assert 2.0 < (last - first).total_seconds() / 3600 < 2.7


def test_best_start_window_when_flexible(offline, tmp_path):
    races = json.loads(json.dumps(RACES))
    for r in races["races"]:
        if r["id"] == "plank-to-plank":
            r["startFlexible"] = True
    f = tmp_path / "races.json"
    f.write_text(json.dumps(races), encoding="utf-8")
    now = datetime.now(timezone.utc)
    day = (now.astimezone(F.TZ).date() + timedelta(days=2)).isoformat()
    e = F.build(now=now, as_if={"plank-to-plank": day}, races_path=f)["races"]["plank-to-plank"]["main"]
    b = e["bestStart"]
    assert b and b["from"] <= b["best"] <= b["to"] and b["byStart"][0]["start"] == "06:00"
