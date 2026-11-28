"""Surf forecast pipeline: physics, rating, NWS Surf Zone parsing, run archive."""
import math
import sqlite3
from datetime import datetime, timezone

from src.surf import forecast as F
from src.surf import physics as P
from src.surf import runs as R
from src.surf.breaks import BREAKS, BY_ID


def test_dispersion_limits():
    T = 12
    assert math.isclose(P.wavenumber(T, 1000), (2 * math.pi / T) ** 2 / 9.81, rel_tol=1e-6)
    assert math.isclose(P.celerity(30, 1.0), math.sqrt(9.81), rel_tol=0.01)   # shallow: c = sqrt(gh)


def test_shoaling_and_breaking():
    assert 1.05 < P.shoal_hs(1.0, 14, 10) < 1.15              # deep -> 10 m, long period
    hb, hbd, a = P.break_wave(1.0, 14, 260, 260, 10, 0.78)
    assert 1.3 < hb < 1.6 and math.isclose(hb, 0.78 * hbd, rel_tol=0.05) and a == 0
    hb_angle, _, ab = P.break_wave(1.0, 14, 300, 260, 10, 0.78)
    assert hb_angle < hb and 0 < ab < 40                       # refraction loses height, turns the wave
    assert P.break_wave(1.0, 14, 100, 260, 10, 0.78)[0] == 0   # from behind the beach
    assert P.break_wave(9.0, 14, 260, 260, 10, 0.78)[0] == 9.0  # already breaking at 10 m
    kg = P.komar_gaughan(P.deep_water_height(1.0, 14, 10), 14)
    assert 0.8 < kg / hb < 1.4                                 # closed-form cross-check agrees


def test_wind_score_directions():
    normal = 260                                               # beach faces W; offshore wind is from E (80)
    assert F.wind_score(2, 270, normal) == (1.0, "glassy")
    assert F.wind_score(10, 80, normal) == (1.0, "offshore")
    assert F.wind_score(20, 80, normal)[0] == 0.7
    assert F.wind_score(15, 260, normal) == (0.1, "blown out")
    assert F.wind_score(10, 260, normal) == (0.3, "onshore")
    s, kind = F.wind_score(12, 170, normal)
    assert kind == "cross" and math.isclose(s, 1 - 0.08 * 4)


def test_tide_score():
    assert F.tide_score(2.0, (0.0, 4.0)) == 1.0
    assert math.isclose(F.tide_score(4.75, (0.0, 4.0)), 0.5)
    assert F.tide_score(7.0, (0.0, 4.0)) == 0.0


def test_rating_gate_ceiling_and_faded():
    b = BY_ID["blacks"]
    flat = F.rate(0.5, 14, 270, (2, 80, None), 1.0, b, 260)
    assert flat["score"] == 0 and flat["label"] == "FLAT"
    great = F.rate(5.0, 16, 250, (3, 80, None), 1.0, b, 260)
    assert great["label"] == "FAIR–GOOD" and great["score"] <= F.MODEL_CEILING   # model can't call GOOD
    blown = F.rate(5.0, 16, 250, (18, 260, None), 1.0, b, 260)
    assert blown.get("faded") is True and blown["score"] < great["score"]
    shores = F.rate(3.0, 14, 275, (2, 80, None), 2.0, BY_ID["la-jolla-shores"], 297)
    assert shores["score"] <= BY_ID["la-jolla-shores"]["potential"]


SRF = """000
FZUS56 KSGX 262011
SRFSGX

CAZ552-271015-
Orange County Coastal Areas-
...HIGH SURF ADVISORY THROUGH 4 AM FRIDAY...

.THIS AFTERNOON THROUGH FRIDAY...
Rip Current Risk*.............High.
Surf Height...................5 to 8 feet.
$$

CAZ043-271015-
San Diego County Coastal Areas-
1211 PM PST Thu Nov 26 2026

...HIGH SURF ADVISORY THROUGH 4 AM FRIDAY...
...HIGH RIP CURRENT RISK...

.THIS AFTERNOON THROUGH FRIDAY...
Rip Current Risk*.............High.
Surf Height...................6 to 9 feet with sets to 10 feet today. 3 to 5 feet Friday.
Thunderstorm Potential........None expected.
Water Temperature.............70 to 72 degrees.
Remarks.......................Mixed west swell from 280 degrees and south swell from 200 degrees.

.SATURDAY...
Rip Current Risk*.............Moderate.
Surf Height...................3 to 6 feet with sets to 7 feet.
Remarks.......................West swell from 280 degrees.

&&
$$
"""


def test_parse_nws_surf_zone_san_diego_block():
    p = F.parse_srf(SRF, "2026-11-26T20:11:00+00:00")
    assert p["zone"] == "CAZ043"
    assert p["headlines"] == ["High surf advisory through 4 am friday", "High rip current risk"]
    assert [x["name"] for x in p["periods"]] == ["This Afternoon Through Friday", "Saturday"]
    assert p["periods"][0]["ripRisk"] == "High"
    assert p["periods"][0]["surf"] == "6 to 9 feet with sets to 10 feet today. 3 to 5 feet Friday"
    assert p["periods"][0]["water"] == "70 to 72 degrees"
    assert p["periods"][1]["ripRisk"] == "Moderate"
    assert F.parse_srf("no san diego block", None) is None


def test_body_band_and_breaks_config():
    assert F.body_band(3.5) == "waist–chest" and F.body_band(9) == "well overhead"
    ids = [b["id"] for b in BREAKS]
    assert len(ids) == len(set(ids)) == 12
    for b in BREAKS:
        assert b["type"] in F.HEIGHT_TRAP and b["mop"].startswith("D") and b["buoy"] in F.CAL["sites"]


def test_run_created_parse_and_archive_schema(tmp_path):
    das = ('history "2026-11-27T03:28:25Z: dataset created; Net_model version 2.1. Runtime arguments: '
           '/project/f90_bin/net_model_gf -s 202611261500 -h 180";')
    assert R.run_created(das) == datetime(2026, 11, 27, 3, 28, 25, tzinfo=timezone.utc)
    assert R.run_created("nothing") is None
    c = sqlite3.connect(tmp_path / "r.db")
    c.executescript(R.DDL)
    c.execute("INSERT INTO surf_runs VALUES ('BP201','ecmwf_fc','2026-11-27T03:28','2026-11-28T03:00',23.5,1.2,14,270)")
    c.execute("INSERT OR IGNORE INTO surf_runs VALUES ('BP201','ecmwf_fc','2026-11-27T03:28','2026-11-28T03:00',23.5,9,9,9)")
    assert c.execute("SELECT COUNT(*), MAX(hs) FROM surf_runs").fetchone() == (1, 1.2)


def test_spectral_breaking_matches_bulk_for_a_narrow_spectrum_and_drops_for_mixed():
    # One energetic 14 s band from the beach normal ≈ bulk break_wave with Tp = 14 s.
    f, df = [1 / 14, 1 / 7], [0.005, 0.005]
    e_narrow = [(1.0 / 4) ** 2 / 0.005, 0.0]                  # Hm0 = 1.0 m all in the 14 s band
    hb_s, _ = P.break_spectrum(f, df, e_narrow, [260, 260], 260, 10, 0.78)
    hb_b, _, _ = P.break_wave(1.0, 14, 260, 260, 10, 0.78)
    assert math.isclose(hb_s, hb_b, rel_tol=0.03)
    # Same Hm0 split between 14 s and 7 s: short waves shoal less, so Hb is lower.
    e_mixed = [e_narrow[0] / 2, e_narrow[0] / 2]
    assert P.spectral_hs(f, df, e_mixed) == P.spectral_hs(f, df, e_narrow)
    assert P.break_spectrum(f, df, e_mixed, [260, 260], 260, 10, 0.78)[0] < hb_s
    # Energy from behind the beach is dropped.
    assert P.break_spectrum(f, df, e_narrow, [80, 80], 260, 10, 0.78) == (0.0, 0.0)


def test_parse_grid_opendap_ascii():
    from src.surf import cdip as C
    txt = ("waveEnergyDensity.waveEnergyDensity[2][3]\n[0], 0.1, 0.2, 0.3\n[1], 1.0, 2.0, 3.0\n\n"
           "waveEnergyDensity.waveTime[2]\n1, 2\n")
    assert C.parse_grid(txt, "waveEnergyDensity") == [[0.1, 0.2, 0.3], [1.0, 2.0, 3.0]]


def test_battjes_janssen_random_wave_breaking():
    hs, d = P.bj_profile(1.0, 14, 10, 1 / 50, 260, 260)
    mono = P.break_wave(1.0, 14, 260, 260, 10, 0.78)[0]
    assert 1.0 < hs < mono                      # grows by shoaling, less than monochromatic breaking
    assert 0.3 < d < 10
    assert P.bj_profile(1.0, 14, 10, 1 / 50, 80, 260) == (0.0, 0.0)   # from behind the beach
    assert P.bj_profile(0.0, 14, 10, 1 / 50) == (0.0, 0.0)
    assert P._bj_qb(0.1, 1.0) == 0.0 and P._bj_qb(2.0, 1.0) == 1.0
    q = P._bj_qb(0.8, 1.0)
    assert 0 < q < 1 and math.isclose((1 - q) / math.log(q), -(0.8 ** 2), rel_tol=1e-3)


def test_face_range_and_size_dependent_scale():
    assert F.RANGE == (0.85, 1.15)
    assert F.nws_scale(3.0) == F.nws_scale(12.0) == 1.0     # round 6: unscaled (pier sensor + lifeguards)
    assert "lifeguard" in F.VERIFICATION["observed"] and "Scripps Pier" in F.VERIFICATION["observed"]


def test_wind_falls_back_to_gfs_when_ecmwf_fails(monkeypatch):
    from src.surf import forecast as F
    calls = []

    def fake(breaks, model):
        calls.append(model)
        if model == "ecmwf_ifs025":
            raise RuntimeError("down")
        return [{0: (5.0, 270.0, 8.0)} for _ in breaks]

    monkeypatch.setattr(F, "_wind_hourly", fake)
    out = F.wind_hourly([{"lat": 0, "lon": 0}])
    assert calls == ["ecmwf_ifs025", "gfs_seamless"]
    assert out == [{0: (5.0, 270.0, 8.0)}]


def test_face_mid_is_unrounded_and_inside_band():
    from src.surf.forecast import RANGE
    lo, hi = 3.84 * RANGE[0], 3.84 * RANGE[1]
    band = [max(0, math.floor(lo)), max(0, math.ceil(hi))]
    assert band[0] <= round(3.84, 1) <= band[1]


def test_sets_ratio_is_h1_10_and_scorecard_is_breaking_height():
    from src.surf.forecast import RANGE, SETS_RATIO, VERIFICATION
    assert SETS_RATIO == 1.27 and SETS_RATIO > RANGE[1]        # sets sit above the band top
    card = VERIFICATION["scorecard"]
    assert "breaking" in card["truth"].lower() or "surf" in card["truth"].lower()
    whos = [r["who"] for r in card["rows"]]
    assert whos[0] == "Surftracker" and any("NWS" in w for w in whos)
    for r in card["rows"]:
        assert set(r) >= {"biasFt", "rmseFt", "within1_5"} and 0 <= r["within1_5"] <= 1


def test_break_forecast_emits_wind_gusts(monkeypatch):
    from datetime import datetime, timezone
    from src.surf import forecast as F
    t = 1795800000 - 1795800000 % 10800
    monkeypatch.setattr(F, "mop_meta", lambda p: (270.0, 10.0))
    monkeypatch.setattr(F, "mop_series", lambda p, k, s: {t: (1.0, 14.0, 270.0), t + 10800: (1.0, 14.0, 270.0)})
    monkeypatch.setattr(F, "breaking_ratios", lambda *a, **k: {})
    wind = {t: (6.0, 90.0, 11.6), t + 10800: (5.0, 80.0, None)}
    out = F.break_forecast(BY_ID["ocean-beach"], wind, {}, datetime.fromtimestamp(t, timezone.utc))
    assert [h["windGustKt"] for h in out["hours"]] == [12, None]


def test_currents_parse_and_tides_station(monkeypatch):
    from datetime import datetime, timezone
    from src.surf import forecast as F
    seen = []

    def fake(url, params=None, **k):
        seen.append(params)
        if params["product"] == "currents_predictions":
            return {"current_predictions": {"cp": [
                {"Type": "flood", "Time": "2026-11-27 04:24", "Velocity_Major": 1.57, "meanFloodDir": 355, "meanEbbDir": 173},
                {"Type": "ebb", "Time": "2026-11-27 10:00", "Velocity_Major": -0.81, "meanFloodDir": 355, "meanEbbDir": 173},
                {"Type": "slack", "Time": "2026-11-27 07:50", "Velocity_Major": 0, "meanFloodDir": 355, "meanEbbDir": 173}]}}
        return {"predictions": [{"t": "2026-11-27 00:00", "v": "3.1", "type": "H"}]}
    monkeypatch.setattr(F, "_get_json", fake)
    c = F.currents(datetime(2026, 11, 27, tzinfo=timezone.utc))
    assert [x["type"] for x in c] == ["flood", "ebb", "slack"]
    assert c[1]["kt"] == 0.81 and c[1]["towardDeg"] == 173 and c[2]["towardDeg"] is None
    assert seen[-1]["station"] == "PCT0031"
    F.tides(datetime(2026, 11, 27, tzinfo=timezone.utc), station="9410170")
    assert seen[-1]["station"] == "9410170"
    F.tides(datetime(2026, 11, 27, tzinfo=timezone.utc))
    assert seen[-1]["station"] == F.TIDE_STATION
