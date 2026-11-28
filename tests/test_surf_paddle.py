from src.surf import paddle as P


def test_bay_light_wind_is_good_and_says_flat_water():
    r = P.rate_hour("bay", (5, 300, 7), 3.0, 3.1, None, None, False)
    assert r["label"] == "Good" and "flat water" in r["reason"]


def test_bay_wind_thresholds_and_gusts():
    assert P.rate_hour("bay", (11, 300, 12), None, None, None, None, False)["label"] == "OK"
    hard = P.rate_hour("bay", (12, 300, 22), None, None, None, None, False)   # gusts (0.7 x 22) push it over
    assert hard["label"] == "Hard" and "gusts 22" in hard["reason"]


def test_coast_offshore_wind_is_hard_with_reason():
    # beach faces W (270); wind from E (90) is offshore
    r = P.rate_hour("coast", (10, 90, 12), None, None, {"faceFt": [1, 2]}, 270, False)
    assert r["label"] == "Hard" and "offshore" in r["reason"] and "out to sea" in r["reason"]


def test_coast_onshore_chop_and_surf_to_launch_through():
    r = P.rate_hour("coast", (9, 280, 10), None, None, {"faceFt": [3, 5]}, 270, False)
    assert r["label"] == "Hard"
    assert r["reason"].startswith("3–5 ft surf") and "onshore, choppy" in r["reason"]


def test_falling_tide_at_a_mouth_caps_at_ok():
    calm = P.rate_hour("bay", (4, 300, 5), 4.0, 3.2, None, None, True)
    assert calm["label"] == "OK" and "outgoing tide" in calm["reason"]
    away = P.rate_hour("bay", (4, 300, 5), 4.0, 3.2, None, None, False)
    assert away["label"] == "Good"
    windy = P.rate_hour("bay", (11, 300, 12), 4.0, 3.2, None, None, True)   # OK wind + ebb stays OK
    assert windy["label"] == "OK"


def test_no_wind_means_no_rating():
    r = P.rate_hour("bay", None, 3.0, 3.1, None, None, False)
    assert r["level"] is None and "No wind" in r["reason"]


def test_best_window_is_longest_daylight_run_at_the_days_best_level():
    sun = [{"date": "2026-11-28", "sunrise": "2026-11-28T14:30+00:00", "sunset": "2026-11-29T00:43+00:00"}]
    lv = [2, 2, 2, 1, 1, 2, 0, 0, 1, 1, 1]   # 15:00 .. 01:00 UTC
    hours = [{"t": f"2026-11-28T{15 + i:02d}:00+00:00" if 15 + i < 24 else f"2026-11-29T{15 + i - 24:02d}:00+00:00",
              "level": v, "reason": "x"} for i, v in enumerate(lv)]
    w = P.best_windows(hours, sun)[0]
    assert w["label"] == "Good" and w["from"] == "2026-11-28T15:00+00:00" and w["to"] == "2026-11-28T18:00+00:00"
    assert "worseAfter" in w


def test_paddle_spots_are_unique_and_coast_spots_name_a_surf_spot():
    ids = [s[0] for s in P.PADDLE_SPOTS]
    assert len(ids) == len(set(ids))
    from src.surf.breaks import BREAKS
    from src.surf.spots import SPOTS
    surf_ids = {b["id"] for b in BREAKS} | {s[0] for s in SPOTS}
    for s in P.PADDLE_SPOTS:
        assert s[4] in ("bay", "harbour", "lagoon", "coast")
        assert (s[6] in surf_ids) if s[4] == "coast" else s[6] is None
        assert 32.5 < s[2] < 33.3 and -117.45 < s[3] < -117.1


EV = [{"t": "2026-11-28T00:00+00:00", "type": "slack", "kt": 0.0, "towardDeg": None},
      {"t": "2026-11-28T03:00+00:00", "type": "ebb", "kt": 2.4, "towardDeg": 173},
      {"t": "2026-11-28T06:00+00:00", "type": "slack", "kt": 0.0, "towardDeg": None}]


def _ep(iso):
    from datetime import datetime
    return int(datetime.fromisoformat(iso).timestamp())


def test_current_at_eases_from_slack_to_max_ebb():
    assert P.current_at(EV, _ep("2026-11-28T00:00+00:00"))["type"] == "slack"
    mid = P.current_at(EV, _ep("2026-11-28T01:30+00:00"))
    assert mid["type"] == "ebb" and 1.0 <= mid["kt"] <= 1.4 and mid["towardDeg"] == 173
    peak = P.current_at(EV, _ep("2026-11-28T03:00+00:00"))
    assert peak["kt"] == 2.4
    assert P.current_at(EV, _ep("2026-11-28T09:00+00:00")) is None


def test_ebb_current_scores_at_bay_entrance_spots():
    hard = P.rate_hour("bay", (4, 300, 5), 4.0, 3.2, None, None, True, {"kt": 2.2, "type": "ebb", "towardDeg": 173})
    assert hard["label"] == "Hard" and "ebb current about 2.2 kt" in hard["reason"].lower()
    ok = P.rate_hour("bay", (4, 300, 5), 4.0, 3.2, None, None, True, {"kt": 1.1, "type": "ebb", "towardDeg": 173})
    assert ok["label"] == "OK" and "outgoing tide" not in ok["reason"]   # real current replaces the tide proxy
    calm = P.rate_hour("bay", (4, 300, 5), 4.0, 3.2, None, None, True, {"kt": 0.3, "type": "flood", "towardDeg": 355})
    assert calm["label"] == "Good"
