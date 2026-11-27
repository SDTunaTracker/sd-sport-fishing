from datetime import datetime, timedelta, timezone

from src.surf import obscheck as O


def test_location_names_map_to_breaks():
    assert O.break_for("La Jolla Shores Tower") == "la-jolla-shores"
    assert O.break_for("Oceanside Harbor Beach") == "oceanside-harbor"
    assert O.break_for("Mission Beach") == "pacific-beach"
    assert O.break_for("ocean-beach") == "ocean-beach"
    assert O.break_for("Somewhere Else") is None


def test_load_records_parses_csv(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("date,time,location,surf_lo_ft,surf_hi_ft,surf_form,source\n"
                 "2025-09-14,08:00,Ocean Beach,2,3,Fair,lifeguard\n"
                 "2025-09-15,,Pacific Beach,4,,good,lifeguard\n"
                 "2025-09-16,08:00,Nowhere,2,3,Poor,x\n", encoding="utf-8")
    r = O.load_records(p)
    assert len(r) == 2
    assert r[0]["break"] == "ocean-beach" and r[0]["mid"] == 2.5 and r[0]["form"] == 1
    assert r[0]["t"] == datetime(2025, 9, 14, 15, 0, tzinfo=timezone.utc)   # 08:00 PDT
    assert r[1]["mid"] == 4.0 and r[1]["form"] == 2


def test_evaluate_reports_bias_heldout_and_rating():
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(45):
        ours = 2 + (i % 5)
        rows.append({"t": t0 + timedelta(days=i), "break": "ocean-beach", "mid": 1.0 + 0.8 * ours,
                     "form": i % 3, "score": float(i % 3) * 2,
                     "ours": {"ft": float(ours), "hs10Ft": ours / 1.2, "tp": 14.0}})
    res = O.evaluate(rows)
    assert res["n"] == 45
    ho = res["heldOut"]
    assert abs(ho["fit"]["a"] - 1.0) < 1e-6 and abs(ho["fit"]["b"] - 0.8) < 1e-6
    assert ho["observerScale"]["rmseFt"] == 0.0
    assert ho["current"]["rmseFt"] > 0
    assert res["rating"]["spearman"] == 1.0
