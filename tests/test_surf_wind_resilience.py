import json
from datetime import datetime, timezone

from src.surf import forecast as F


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._p, self.headers = status, payload or {}, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} error")

    def json(self):
        return self._p


def test_429_waits_for_retry_after_then_succeeds(monkeypatch):
    calls, sleeps = [], []
    seq = [_Resp(429, headers={"Retry-After": "7"}), _Resp(200, {"ok": 1})]
    monkeypatch.setattr(F.requests, "get", lambda *a, **k: calls.append(1) or seq.pop(0))
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    assert F._get_json("https://api.open-meteo.com/v1/forecast") == {"ok": 1}
    assert len(calls) == 2 and sleeps == [7.0]


def test_429_on_every_try_raises(monkeypatch):
    monkeypatch.setattr(F.requests, "get", lambda *a, **k: _Resp(429))
    monkeypatch.setattr("time.sleep", lambda s: None)
    try:
        F._get_json("https://api.open-meteo.com/v1/forecast", attempts=2)
    except RuntimeError as e:
        assert "429" in str(e)
    else:
        raise AssertionError("expected a failure")


def _write_prev(path, key="breaks"):
    path.write_text(json.dumps({"generatedAt": "2026-11-27T17:21+00:00", key: [
        {"id": "ocean-beach", "hours": [
            {"t": "2026-11-28T15:00+00:00", "windKt": 4, "windFrom": 80, "windGustKt": 9},
            {"t": "2026-11-28T18:00+00:00", "windKt": None, "windFrom": None}]},
    ]}), encoding="utf-8")


def test_fallback_only_when_all_live_wind_failed(tmp_path):
    p = tmp_path / "surf.json"
    _write_prev(p)
    items = [{"id": "ocean-beach"}, {"id": "blacks"}]
    live = [{1: (5.0, 90.0, 8.0)}, {}]
    assert F.with_wind_fallback(items, live, p) == (live, None)
    winds, note = F.with_wind_fallback(items, [{}, {}], p)
    ep = int(datetime(2026, 11, 28, 15, tzinfo=timezone.utc).timestamp())
    assert winds[0] == {ep: (4.0, 80.0, 9.0)} and winds[1] == {}
    assert "previous forecast run" in note and "2026-11-27T17:21" in note
    assert F.with_wind_fallback(items, [{}, {}], tmp_path / "missing.json") == ([{}, {}], None)


def test_build_uses_previous_wind_when_open_meteo_is_down(monkeypatch, tmp_path):
    p = tmp_path / "surf.json"
    _write_prev(p)
    seen = {}

    def fake_break(b, wind, tide_h, now):
        seen[b["id"]] = wind
        return {"id": b["id"], "hours": []}

    def boom(*a, **k):
        raise RuntimeError("429 Too Many Requests")
    monkeypatch.setattr(F, "OUT", p)
    monkeypatch.setattr(F, "wind_hourly", boom)
    monkeypatch.setattr(F, "tides", lambda *a, **k: ({}, []))
    monkeypatch.setattr(F, "break_forecast", fake_break)
    monkeypatch.setattr(F, "nws_surf_zone", lambda: None)
    monkeypatch.setattr(F, "buoy_now", lambda s: None)
    monkeypatch.setattr(F, "enrich", lambda payload, *a, **k: payload)
    from src.surf import nws as N
    monkeypatch.setattr(N, "forecaster_notes", lambda: None)
    monkeypatch.setattr(N, "surf_alerts", lambda: [])
    out = F.build(datetime(2026, 11, 28, 0, tzinfo=timezone.utc))
    assert out["windNote"] and seen["ocean-beach"] and seen["blacks"] == {}
