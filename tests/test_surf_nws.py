from datetime import datetime, timezone
from pathlib import Path

from src.surf import nws as N

FIX = (Path(__file__).parent / "fixtures" / "afd_sgx_sample.txt").read_text(encoding="utf-8")


def test_beaches_section_from_real_afd():
    paras = N.afd_section(FIX)
    assert paras and paras[0].startswith("High tide peaks")
    assert any("breaking waves of 3-5 feet" in p for p in paras)
    joined = " ".join(paras)
    assert ".SKYWARN" not in joined and "&&" not in joined
    assert "\n" not in joined                      # hard wraps joined


def test_section_order_and_terminators():
    marine_first = ".MARINE...\nSeas 4 ft.\n\n.BEACHES...\nSurf 2-3 ft\nat west-facing beaches.\n\n.SKYWARN...\nNone.\n"
    assert N.afd_section(marine_first) == ["Surf 2-3 ft at west-facing beaches."]
    beaches_last = ".DISCUSSION...\nDry.\n&&\n.BEACHES...\nSets to 6 ft.\n"
    assert N.afd_section(beaches_last) == ["Sets to 6 ft."]
    inline = ".BEACHES...Surf 4-6 ft.\n&&\n"
    assert N.afd_section(inline) == ["Surf 4-6 ft."]
    assert N.afd_section(".DISCUSSION...\nNo beach section.\n&&\n") is None
    assert N.afd_section("") is None


def _alert(event, until, level_msg="Alert", status="Actual", headline=None):
    return {"properties": {"event": event, "ends": until, "expires": until, "status": status,
                           "messageType": level_msg, "severity": "Moderate",
                           "headline": f"{event} issued", "description": "* WHAT...Surf 4-7 ft.",
                           "instruction": "", "areaDesc": "San Diego County Coastal Areas",
                           "parameters": {"NWSheadline": [headline]} if headline else {}}}


def test_alerts_filter_sort_and_expiry():
    now = datetime(2026, 11, 27, 22, 0, tzinfo=timezone.utc)
    gj = {"features": [
        _alert("Beach Hazards Statement", "2026-11-28T16:00:00-08:00", headline="BEACH HAZARDS STATEMENT IN EFFECT"),
        _alert("High Surf Advisory", "2026-11-29T00:00:00-08:00"),
        _alert("Wind Advisory", "2026-11-29T00:00:00-08:00"),               # not a surf product
        _alert("Rip Current Statement", "2026-11-27T10:00:00-08:00"),       # expired
        _alert("Coastal Flood Advisory", "2026-11-29T00:00:00-08:00", level_msg="Cancel"),
        _alert("High Surf Advisory", "2026-11-29T00:00:00-08:00", status="Test"),
    ]}
    out = N.parse_alerts(gj, now=now)
    assert [a["event"] for a in out] == ["High Surf Advisory", "Beach Hazards Statement"]
    assert out[0]["level"] == "advisory" and out[1]["level"] == "statement"
    assert out[1]["headline"] == "BEACH HAZARDS STATEMENT IN EFFECT"
    assert out[0]["instruction"] is None and out[0]["source"] == N.SOURCE
    wrapped = {"features": [dict(_alert("High Surf Warning", "2026-11-29T00:00:00-08:00"))]}
    wrapped["features"][0]["properties"]["description"] = "* WHAT...Surf 8 to\n12 feet.\n\n* WHERE...San Diego\nCounty."
    assert N.parse_alerts(wrapped, now=now)[0]["description"] == "* WHAT...Surf 8 to 12 feet.\n\n* WHERE...San Diego County."
    assert N.parse_alerts({}, now=now) == []


def test_forecaster_notes_skips_afd_without_beaches(monkeypatch):
    texts = {"a": ".DISCUSSION...\nShort update.\n&&\n", "b": FIX}

    def fake(url, params=None, accept=None):
        if url.endswith("/locations/SGX"):
            return {"@graph": [{"id": "a", "issuanceTime": "2026-11-27T23:00:00+00:00"},
                               {"id": "b", "issuanceTime": "2026-11-27T21:22:00+00:00"}]}
        pid = url.rsplit("/", 1)[1]
        return {"productText": texts[pid], "issuanceTime": "2026-11-27T21:22:00+00:00" if pid == "b" else None}
    monkeypatch.setattr(N, "_get", fake)
    n = N.forecaster_notes()
    assert n["issued"] == "2026-11-27T21:22:00+00:00" and n["url"] == N.AFD_PAGE
    assert n["paragraphs"][0].startswith("High tide peaks")


def test_build_survives_nws_failures(monkeypatch):
    from src.surf import forecast as F

    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(F, "wind_hourly", lambda breaks: [{} for _ in breaks])
    monkeypatch.setattr(F, "tides", lambda *a, **k: ({}, []))
    monkeypatch.setattr(F, "break_forecast", boom)
    monkeypatch.setattr(F, "nws_surf_zone", lambda: None)
    monkeypatch.setattr(F, "buoy_now", lambda s: None)
    monkeypatch.setattr(F, "enrich", lambda payload, *a, **k: payload)
    monkeypatch.setattr(N, "forecaster_notes", boom)
    monkeypatch.setattr(N, "surf_alerts", boom)
    out = F.build(datetime(2026, 11, 27, 22, 0, tzinfo=timezone.utc))
    assert out["nwsNotes"] is None and out["nwsAlerts"] is None
    assert "breaks" in out
