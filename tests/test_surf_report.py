"""Surftracker written report: facts, template writer, fact checker, Claude path."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.surf import report as R

NOW = datetime(2026, 11, 27, 14, 0, tzinfo=timezone.utc)      # Fri 6 AM PST


def _hours(face, sets, wind_kt, wind_from=90, tp=15.0, dp=265, days=6):
    out = []
    t0 = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
    for i in range(days * 8):
        t = t0 + timedelta(hours=3 * i)
        loc_h = (t.hour - 8) % 24
        out.append({"t": t.isoformat(timespec="minutes"), "faceFt": list(face), "faceMidFt": sum(face) / 2,
                    "setsFt": sets, "hsM": 1.0, "tpS": tp, "dpDeg": dp, "windKt": wind_kt if loc_h < 11 else wind_kt + 8,
                    "windFrom": wind_from if loc_h < 11 else 270, "windGustKt": wind_kt + 4, "tideFt": 3.0,
                    "conf": "high" if i < 16 else "medium" if i < 40 else "low",
                    "score": 3.2 if loc_h < 11 else 2.0, "label": "FAIR" if loc_h < 11 else "POOR–FAIR",
                    "windType": "offshore" if loc_h < 11 else "onshore"})
    return out


def surf_payload(face=(3, 5), sets=6, wind=3):
    breaks = []
    for bid, name, lat in (("oceanside-pier", "Oceanside Pier", 33.19), ("swamis", "Swamis", 33.03),
                           ("blacks", "Blacks", 32.88), ("ocean-beach", "Ocean Beach Pier", 32.75),
                           ("imperial-beach", "Imperial Beach Pier", 32.58)):
        breaks.append({"id": bid, "name": name, "lat": lat, "lon": -117.3, "type": "beach",
                       "hours": _hours(face, sets, wind)})
    sun = []
    for d in range(8):
        day = datetime(2026, 11, 26, tzinfo=timezone.utc) + timedelta(days=d)
        sun.append({"date": day.date().isoformat(),
                    "firstLight": (day + timedelta(hours=14, minutes=2)).isoformat(timespec="minutes"),
                    "sunrise": (day + timedelta(hours=14, minutes=29)).isoformat(timespec="minutes"),
                    "sunset": (day + timedelta(hours=24, minutes=44)).isoformat(timespec="minutes"),
                    "lastLight": (day + timedelta(hours=25, minutes=10)).isoformat(timespec="minutes")})
    return {
        "generatedAt": NOW.isoformat(timespec="minutes"), "breaks": breaks, "sun": sun,
        "tides": {"hilo": [{"t": "2026-11-27T18:03+00:00", "ft": 6.4, "type": "H"},
                           {"t": "2026-11-28T01:41+00:00", "ft": -1.1, "type": "L"},
                           {"t": "2026-11-28T08:37+00:00", "ft": 3.6, "type": "H"}]},
        "waterTemp": {"station": "201", "t": NOW.isoformat(timespec="minutes"), "f": 64},
        "buoys": {"191": {"t": NOW.isoformat(timespec="minutes"), "hsFt": 7.3, "tpS": 14.3, "dpDeg": 263}},
        "nwsAlerts": [{"event": "Beach Hazards Statement", "until": "2026-11-28T16:00:00-08:00"}],
        "nws": {"periods": [{"ripRisk": "High"}]},
    }


def test_facts_come_from_data():
    f = R.facts(surf_payload(), None, NOW)
    t = f["today"]
    assert f["reportDay"] == "Friday" and f["covers"] == "morning"
    assert t["size"]["typicalFaceFt"] == [3, 5] and t["size"]["biggestSetsFt"] == 6
    assert t["waterTempF"] == 64 and t["wetsuit"] == "3/2 fullsuit"
    assert t["swell"]["buoy"]["swellFt"] == 7.3 and t["swell"]["periodS"] == 15
    assert [r["region"] for r in f["regions"]] == R.REGION_NAMES
    assert t["wind"]["morning"]["type"] == "offshore"
    assert f["nws"]["alerts"][0]["until"] == "Saturday 4 PM"
    assert 1 <= len(f["outlook"]) <= R.OUTLOOK_DAYS


def test_template_passes_its_own_fact_check():
    f = R.facts(surf_payload(), None, NOW)
    rep = R.template(f)
    assert R.check(rep, f) == []
    assert "3–5 ft" in rep["today"] and "sets to 6 ft" in rep["today"]
    assert "64°F" in rep["today"] and "tide" in rep["today"].lower()
    assert rep["paddle"]


def test_flat_day_template():
    f = R.facts(surf_payload(face=(0, 1), sets=1, wind=2), None, NOW)
    rep = R.template(f)
    assert "flat to 1 ft" in rep["today"]
    assert R.check(rep, f) == []


@pytest.mark.parametrize("bad, why", [
    ("Most spots 4–7 ft this morning.", "range"),                   # invented height range
    ("Sets to 9 ft at Blacks.", "sets"),                             # sets value not in data
    ("Most spots run 3–5 ft with sets to 5 ft.", "sets"),            # face top used as sets
    ("A 7.3 ft long-period west swell is running.", "swell"),        # buoy swell fine...
    ("Expect 3–5 ft west swell all day.", "calls a surf height swell"),
    ("Offshore 12 kt early.", "kt"),
    ("High tide at 9:15 AM.", "time"),
    ("A south swell fills in.", "direction"),
    ("Lines are stacking, we saw it on the cams!", "banned"),
    ("Water is 70°F.", "°F"),
])
def test_check_rejects_invented_facts(bad, why):
    f = R.facts(surf_payload(), None, NOW)
    rep = R.template(f)
    rep["today"] = rep["today"] + " " + bad
    probs = R.check(rep, f)
    if why == "swell":
        assert not any("7.3" in p for p in probs)      # labelled buoy swell height is allowed
    else:
        assert probs, bad


def test_check_requires_the_essentials():
    f = R.facts(surf_payload(), None, NOW)
    rep = R.template(f)
    rep["today"] = "Most spots run 3–5 ft."
    probs = " ".join(R.check(rep, f))
    for need in ("tide", "wind", "swell", "water"):
        assert need in probs


def _fake_client(*texts, raise_exc=None):
    calls = []

    class Msgs:
        def create(self, **kw):
            calls.append(kw)
            if raise_exc:
                raise raise_exc
            text = texts[min(len(calls), len(texts)) - 1]
            return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=5000, output_tokens=900),
                                   content=[SimpleNamespace(type="text", text=text)])
    return SimpleNamespace(messages=Msgs()), calls


def test_claude_path_accepts_a_clean_draft():
    f = R.facts(surf_payload(), None, NOW)
    good = json.dumps(R.template(f))
    client, calls = _fake_client(good)
    out = R.write_report(f, client=client)
    assert out["engine"] == R.MODEL and out["tries"] == 1
    kw = calls[0]
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "FACTS" in kw["messages"][0]["content"]


def test_claude_path_retries_then_falls_back():
    f = R.facts(surf_payload(), None, NOW)
    bad = R.template(f)
    bad["today"] += " Sets to 12 ft at Blacks."
    good = R.template(f)
    client, calls = _fake_client(json.dumps(bad), json.dumps(good))
    out = R.write_report(f, client=client)
    assert out["engine"] == R.MODEL and out["tries"] == 2
    assert "fact check" in calls[1]["messages"][0]["content"]

    client, calls = _fake_client(json.dumps(bad), json.dumps(bad))
    out = R.write_report(f, client=client)
    assert out["engine"] == "template" and out["tries"] == 2 and out["rejected"]
    assert R.check({k: out[k] for k in ("headline", "today", "outlook", "regions", "paddle")}, f) == []


def test_api_failure_and_no_key_fall_back(monkeypatch):
    f = R.facts(surf_payload(), None, NOW)
    client, _ = _fake_client(raise_exc=RuntimeError("down"))
    assert R.write_report(f, client=client)["engine"] == "template"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = R.write_report(f)
    assert out["engine"] == "template" and out["tries"] == 0


def test_build_and_due(tmp_path):
    rep = R.build(NOW, use_claude=False, surf=surf_payload(), spots=None)
    assert rep["engine"] == "template" and rep["note"].startswith("Auto-written")
    assert R.due(None, surf_payload(), NOW)
    assert R.due(rep, surf_payload(), NOW + timedelta(hours=R.REFRESH_H))


def test_tide_direction_body_size_and_paddle_order():
    f = R.facts(surf_payload(), None, NOW)
    t = f["today"]
    assert t["tideTrend"] == {"morning": "rising, then falling (on the drop) after the high",  # 10:03 AM high
                              "afternoon": "falling (on the drop)"}
    assert t["size"]["feel"] == "chest to shoulder"                  # middle of 3–5 ft, as the page's sfBand
    rep = R.template(f)
    assert R.check(dict(rep, today=rep["today"] + " Head high sets."), f)
    assert not R.check(dict(rep, today=rep["today"] + " Chest to shoulder high, cleaner on the drop."), f)
    f2 = dict(f, today=dict(t, tideTrend={"afternoon": "falling (on the drop)"}))
    assert R.check(dict(rep, today=rep["today"] + " Best on the push."), f2)
    p = f["paddle"]
    assert p["calmest"]["kt"] == 3 and p["windRisesTo"]["kt"] == 11
    order = [R.WEEKDAYS.index(p[k]["day"]) * 24 + int(p[k]["around"].split()[0]) % 12
             + (12 if "PM" in p[k]["around"] or p[k]["around"] == "noon" else 0) for k in ("calmest", "windRisesTo")]
    assert order[0] < order[1]


def test_outlook_and_region_ranges_are_scoped():
    f = R.facts(surf_payload(), None, NOW)
    day = f["outlook"][0]
    day.update(typicalFaceFt=[5, 8], biggestFaceFt=[6, 9])
    rep = R.template(f)
    assert R.check(rep, f) == []
    bad = dict(rep, outlook=f"{day['day']} builds to 3–5 ft. " + rep["outlook"])
    assert any("outlook " + day["day"] in p for p in R.check(bad, f))
    regs = [dict(r) for r in rep["regions"]]
    f["regions"][0].update(typicalFaceFt=[1, 2], biggestFaceFt=[1, 2])
    f["regions"][0]["best"]["faceFt"] = [1, 2]
    regs[0]["line"] = "Most spots run 3–5 ft."
    assert any("region North County" in p for p in R.check(dict(rep, regions=regs), f))
