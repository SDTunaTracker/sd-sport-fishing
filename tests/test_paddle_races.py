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
        assert r.get("series") and r["id"].startswith(r["series"] + "-")
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
    fc = CO.load("malibu-downwinder")
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
        if r["id"] == "malibu-downwinder-2026":
            r["startFlexible"] = True
    f = tmp_path / "races.json"
    f.write_text(json.dumps(races), encoding="utf-8")
    now = datetime.now(timezone.utc)
    day = (now.astimezone(F.TZ).date() + timedelta(days=2)).isoformat()
    e = F.build(now=now, as_if={"malibu-downwinder-2026": day}, races_path=f)["races"]["malibu-downwinder-2026"]["main"]
    b = e["bestStart"]
    assert b and b["from"] <= b["best"] <= b["to"] and b["byStart"][0]["start"] == "06:00"


# ── race list editing (src/paddle/races.py) ────────────────────────────────

from src.paddle import races as RA


def test_race_file_checks_clean():
    assert RA.check(RACES) == []


def test_every_series_has_a_2027_entry_awaiting_a_date():
    series = {r["series"] for r in RACES["races"]}
    tba = {r["series"] for r in RACES["races"] if r["year"] == 2027}
    assert series == tba
    assert all(r["status"] == RA.TBA and r["date"] is None for r in RACES["races"] if r["year"] == 2027)


def test_set_date_moves_tba_to_draft_and_cleans_url():
    doc = json.loads(json.dumps(RACES))
    r = RA.set_fields(doc, "the-loop-2027", day="2027-05-15", start="07:30",
                      url="https://paddleguru.com/races/THELOOP2027/schedule?fbclid=x")
    assert r["date"] == "2027-05-15" and r["status"] == RA.DRAFT and r["startLocal"] == "07:30"
    assert r["paddleguru"] == "https://paddleguru.com/races/THELOOP2027"
    assert RA.check(doc) == []
    RA.set_fields(doc, "the-loop-2027", confirm=True)
    assert r["status"] == RA.CONFIRMED


def test_new_season_adds_one_tba_per_series():
    doc = json.loads(json.dumps(RACES))
    added = RA.new_season(doc, 2028)
    assert len(added) == len({r["series"] for r in RACES["races"]})
    assert RA.new_season(doc, 2028) == []
    assert RA.check(doc) == []


def test_check_flags_bad_rows():
    doc = {"races": [{"id": "x-2027", "series": "x", "year": 2027, "date": "2026-01-01", "status": "nope",
                      "startLocal": "7am", "paddleguru": "https://example.com", "location": {},
                      "distances": [{"id": "a", "courseId": "missing"}]}]}
    errs = " | ".join(RA.check(doc))
    for bit in ("status", "not in year", "HH:MM", "paddleguru", "location", "missing"):
        assert bit in errs


def test_water_temp_only_for_san_diego_races():
    by = {r["id"]: r for r in RACES["races"]}
    assert F.near_sst_buoy(by["the-loop-2026"]) and F.near_sst_buoy(by["waterman-challenge-2026"])
    assert not F.near_sst_buoy(by["catalina-classic-2026"]) and not F.near_sst_buoy(by["seaside-slide-2026"])


# ── past-race conditions (src/paddle/conditions.py) ────────────────────────

from src.paddle import conditions as CD


def test_conditions_scores_past_races_once(monkeypatch, tmp_path):
    calls = []

    def fake(points, day):
        calls.append(day)
        t0 = int(datetime.fromisoformat(day + "T00:00:00+00:00").timestamp())
        return [{t0 + h * 3600: (15.0, 270.0, 18.0) for h in range(48)} for _ in points]
    monkeypatch.setattr(CD, "archive_wind", fake)
    monkeypatch.setattr(CD.SF, "currents", lambda *a, **k: [])
    out = CD.build(today=datetime(2026, 11, 27).date())
    mal = out["races"]["malibu-downwinder-2026"]["main"]
    assert mal["reason"].startswith("W 15 kt → downwind")      # W wind, paddling ESE
    assert mal["label"] in ("Great", "Good")
    n = len(calls)
    again = CD.build(existing=out, today=datetime(2026, 11, 27).date())
    assert len(calls) == n and again["races"].keys() == out["races"].keys()
    assert "the-loop-2027" not in out["races"]                   # no date yet


# ── paddler profiles (src/paddle/results.py) ───────────────────────────────

from src.paddle import results as RS

FIX = ROOT / "tests" / "fixtures" / "paddle"


def test_fixture_results_check_clean():
    people, results = RS.load(FIX)
    assert RS.check(people, results, RACES) == []


def test_hidden_paddler_and_results_never_published(tmp_path):
    pub = RS.build(src=FIX, out=tmp_path / "people.json")
    ids = {p["id"] for p in pub["paddlers"]}
    assert "test-paddler-hidden" not in ids
    assert all(r["paddler"] in ids for r in pub["results"])
    assert "Hidden" not in (tmp_path / "people.json").read_text(encoding="utf-8")
    assert pub["remove"].startswith("mailto:")
    assert all(set(p) == {"id", "name", "crew", "note"} for p in pub["paddlers"])


def test_check_rejects_unknown_ids_extra_fields_and_bad_places():
    people = {"paddlers": [{"id": "a-b", "name": "A B", "hidden": False, "email": "x"}]}
    results = {"results": [
        {"paddler": "nobody", "race": "the-loop-2026", "distance": "loop", "craft": "Prone 14'"},
        {"paddler": "a-b", "race": "no-race", "craft": "Kayak"},
        {"paddler": "a-b", "race": "the-loop-2026", "distance": "loop", "craft": "SUP", "time": "2h", "place": 5,
         "field": 3, "age": 44},
    ]}
    errs = " | ".join(RS.check(people, results, RACES))
    for bit in ("unknown paddler", "unknown race", "craft", "not h:mm:ss", "field 3", "fields not allowed: age",
                "fields not allowed: email"):
        assert bit in errs, bit


def test_times_parse():
    assert RS.seconds("2:05:31") == 7531 and RS.seconds("58:02") == 3482 and RS.seconds("1:00:00.5") == 3600.5


def test_live_people_file_matches_source_and_has_no_test_data(tmp_path):
    live = json.loads((ROOT / "web/api/v1/paddle_people.json").read_text(encoding="utf-8"))
    built = RS.build(out=tmp_path / "p.json")
    assert live == built, "run: python -m src.paddle.results build"
    assert not any("test" in p["id"] for p in live["paddlers"])


# ── imports from any source (src/paddle/importer.py) ───────────────────────

import shutil

from src.paddle import importer as IM
from src.paddle.sources import catalina_classic as CC


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "paddle"
    d.mkdir()
    (d / "paddle_paddlers.json").write_text(json.dumps({"paddlers": [
        {"id": "pat-lee", "name": "Pat Lee", "hidden": False, "crew": True, "note": None},
        {"id": "sam-ray", "name": "Sam Ray", "hidden": False, "crew": False, "note": None},
        {"id": "sam-ray-2", "name": "Sam Ray", "hidden": False, "crew": False, "note": None},
    ]}), encoding="utf-8")
    (d / "paddle_results.json").write_text(json.dumps({"results": []}), encoding="utf-8")
    return d


def _csv(tmp_path, text):
    f = tmp_path / "r.csv"
    f.write_text(text, encoding="utf-8")
    return IM.read_csv(f)


def test_norm_name_and_craft():
    assert IM.norm_name("José  O'Neil-Smith Jr.") == "jose oneil smith"
    assert IM.craft_of("Prone 14' Men 40-49") == "Prone 14'" and IM.craft_of("Unlimited") == "Prone unlimited"
    assert IM.craft_of("SUP 14 Women") == "SUP" and IM.craft_of("OC-1 Men") == "OC1" and IM.craft_of("") is None


def test_csv_import_matches_listed_and_flags_shared_names(src, tmp_path):
    rows = _csv(tmp_path, "First Name,Last Name,Division,Time,Place,Age,Hometown\n"
                          "pat,LEE,Prone 14' Men,2:10:00,2,44,Somewhere\n"
                          "Sam,Ray,Prone stock Men,2:20:00,3,50,X\n"
                          "Alex,Kim,Prone stock Men,2:30:00,4,30,Y\n"
                          "Jo,Fin,SUP Women,2:00:00,1,30,Z\n"
                          "Dee,Nf,Prone stock Men,,,30,Z\n")
    rep = IM.import_rows(rows, "the-loop-2026", source="https://example.org/r", full_results=True, src=src)
    assert rep == {"added": 1, "updated": 0, "newPaddlers": 0, "notListed": 2, "notProne": 0, "dnf": 1, "ambiguous": 1}
    res = json.loads((src / "paddle_results.json").read_text())["results"]
    assert res == [{"paddler": "pat-lee", "race": "the-loop-2026", "distance": "loop", "division": "Prone 14' Men",
                    "craft": "Prone 14'", "time": "2:10:00", "place": 2, "field": 2, "source": "https://example.org/r"}]
    assert "44" not in (src / "paddle_results.json").read_text()          # age never stored
    amb = json.loads((src / "paddle_ambiguous.json").read_text())["ambiguous"]
    assert amb[0]["name"] == "Sam Ray" and set(amb[0]["candidates"]) == {"sam-ray", "sam-ray-2"}


def test_override_assign_resolves_ambiguous_and_reimport_updates(src, tmp_path):
    (src / "paddle_overrides.json").write_text(json.dumps({"aliases": {}, "assign": [
        {"name": "Sam Ray", "race": "the-loop-2026", "paddler": "sam-ray-2"}]}), encoding="utf-8")
    rows = _csv(tmp_path, "name,division,time,place,field\nSam Ray,Prone stock Men,2:20:00,3,9\n")
    assert IM.import_rows(rows, "the-loop-2026", src=src)["added"] == 1
    rows = _csv(tmp_path, "name,division,time,place,field\nSam Ray,Prone stock Men,2:19:00,2,9\n")
    assert IM.import_rows(rows, "the-loop-2026", src=src)["updated"] == 1
    res = json.loads((src / "paddle_results.json").read_text())["results"]
    assert len(res) == 1 and res[0]["paddler"] == "sam-ray-2" and res[0]["time"] == "2:19:00"


def test_add_new_prone_only_and_division_history(src, tmp_path):
    rows = _csv(tmp_path, "name,division,time,place,field\nAlex Kim,Prone stock Men,2:30:00,4,9\n"
                          "Jo Fin,SUP Women,2:00:00,1,5\n")
    rep = IM.import_rows(rows, "the-loop-2026", prone_only=True, add_new=True, src=src)
    assert rep["newPaddlers"] == 1 and rep["notProne"] == 1
    # same name later in an OC race: history doesn't fit -> flagged, not merged
    rows = _csv(tmp_path, "name,division,time,place,field\nAlex Kim,OC-1 Men,1:30:00,2,9\n")
    rep = IM.import_rows(rows, "waterman-challenge-2026", add_new=True, src=src)
    assert rep["ambiguous"] == 1 and rep["added"] == 0


def test_same_name_twice_in_one_race_is_flagged(src, tmp_path):
    rows = _csv(tmp_path, "name,division,time\nChris Day,Prone stock Men,2:00:00\nChris Day,Prone 14' Men,2:05:00\n")
    rep = IM.import_rows(rows, "the-loop-2026", add_new=True, src=src)
    assert rep["ambiguous"] == 2 and rep["newPaddlers"] == 0


CC_HTML = """<table><tr><th>PLACE</th><th>TIME</th><th>NAME</th><th>S/U</th><th>M/F</th><th>NOTES</th></tr>
<tr><td>1</td><td>5:38:44</td><td>ANN MCRAE</td><td>U</td><td>F</td><td></td></tr>
<tr><td>2</td><td>6:01:00</td><td>BO DIAZ</td><td>S</td><td>M</td><td></td></tr>
<tr><td>3</td><td>5:59:00</td><td>CY LO</td><td>S</td><td>M</td><td></td></tr>
<tr><td></td><td>DNF</td><td>DEE NO</td><td>S</td><td>M</td><td>DNF</td></tr></table>"""


def test_catalina_parse_keeps_only_allowed_fields_and_division_places():
    rows = CC.parse(CC_HTML, "https://x/2021")
    assert [r["name"] for r in rows] == ["Ann McRae", "Bo Diaz", "Cy Lo"]
    bo, cy = rows[1], rows[2]
    assert (cy["place"], cy["field"], bo["place"]) == ("1", "2", "2")     # by time within Stock Men
    assert rows[0]["division"] == "Unlimited Women" and rows[0]["craft"] == "Prone unlimited"
    assert set(rows[0]) == {"name", "division", "craft", "time", "source", "place", "field"}


CC_HTML_2 = """<table><tr><th>Place</th><th>Time</th><th>Last</th><th>First</th><th>Class</th><th>Gender</th></tr>
<tr><td>1</td><td>5:23:14</td><td>Ash</td><td>Al</td><td>UL</td><td>M</td></tr>
<tr><td>2</td><td>05:55.1</td><td>Bay</td><td>Bo</td><td>UL</td><td>M</td></tr>
<tr><td>3</td><td>5:58 51</td><td>Cole</td><td>Cy</td><td>UL</td><td>M</td></tr>
<tr><td>4</td><td>Unofficial Time</td><td>Dunn</td><td>Di</td><td>UL</td><td>M</td></tr>
<tr><td>999</td><td>DNF</td><td>Eck</td><td>Ed</td><td>UL</td><td>M</td></tr>
<tr><td>999</td><td>DNS</td><td>Fox</td><td>Fi</td><td>S</td><td>F</td></tr></table>"""


def test_catalina_parse_odd_cells_last_first_and_ul():
    rows = CC.parse(CC_HTML_2, "https://x/2018")
    assert [(r["name"], r["time"], r["place"], r["field"]) for r in rows] == [
        ("Al Ash", "5:23:14", "1", "3"), ("Bo Bay", None, "2", "3"), ("Cy Cole", "5:58:51", "3", "3")]
    assert rows[0]["division"] == "Unlimited Men"                       # "UL" is unlimited


def test_transcribed_csvs_hold_only_allowed_fields_and_known_races():
    from src.paddle.sources import transcribed as TR
    races = {r["id"] for r in json.loads((ROOT / "web/api/v1/paddle_races.json").read_text(encoding="utf-8"))["races"]}
    files = sorted(CC.TRANSCRIBED.glob("*.csv"))
    assert files, "expected transcribed organiser PDFs in data/paddle/imports/"
    for f in files:
        head = f.read_text(encoding="utf-8").splitlines()[0].split(",")
        assert set(head) <= {"name", "division", "craft", "time", "place", "field", "source"}, f.name
        assert f.stem in races, f.name
    assert {f.stem for f in TR.files()} >= {"waterman-challenge-2018"}


def test_live_people_are_all_prone_finishers_from_allowed_sources():
    live = json.loads((ROOT / "web/api/v1/paddle_people.json").read_text(encoding="utf-8"))
    allowed = ("https://catalinaclassicpaddleboardrace.com/", "https://watermanchallenge.weebly.com/")
    assert all(r["source"].startswith(allowed) for r in live["results"])
    assert all(r["craft"] in IM.PRONE for r in live["results"])
