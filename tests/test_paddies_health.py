"""Tests for scraper.paddies.health rules and extract.record_health."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.paddies import extract, health

NOW = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def healthy_state():
    return {
        "last_success_utc": _iso(NOW - timedelta(hours=2)),
        "consecutive_failures": 0,
        "newest_post_published_at": _iso(NOW - timedelta(hours=5)),
        "pending_extract": 0,
        "extract_last_success_utc": _iso(NOW - timedelta(hours=2)),
        "extract_consecutive_failed_runs": 0,
    }


def keys(probs):
    return {p.key for p in probs}


def test_healthy_has_no_problems():
    assert health.evaluate(healthy_state(), {"generated_at": _iso(NOW - timedelta(hours=2))}, NOW) == []


def test_missing_state_is_a_problem():
    assert keys(health.evaluate(None, None, NOW)) == {"bd:health"}


def test_ingest_stall_after_24h_is_critical():
    st = healthy_state()
    st["last_success_utc"] = _iso(NOW - timedelta(hours=25))
    probs = health.evaluate(st, None, NOW)
    assert keys(probs) == {"bd:ingest"}
    assert probs[0].severity == "critical"


def test_never_succeeded_is_critical():
    st = healthy_state()
    del st["last_success_utc"]
    assert keys(health.evaluate(st, None, NOW)) == {"bd:ingest"}


def test_ingest_23h_is_fine():
    st = healthy_state()
    st["last_success_utc"] = _iso(NOW - timedelta(hours=23))
    assert health.evaluate(st, None, NOW) == []


def test_repeated_feed_errors_warn():
    st = healthy_state()
    st["consecutive_failures"] = 3
    st["last_error"] = "HTTPError 403"
    probs = health.evaluate(st, None, NOW)
    assert keys(probs) == {"bd:feed-errors"}
    assert "403" in probs[0].detail


def test_no_new_posts_warns_after_3_days():
    st = healthy_state()
    st["newest_post_published_at"] = _iso(NOW - timedelta(days=4))
    assert keys(health.evaluate(st, None, NOW)) == {"bd:no-new-posts"}


def test_extract_failing_with_backlog_warns():
    st = healthy_state()
    st.update(pending_extract=12, extract_last_success_utc=_iso(NOW - timedelta(days=3)),
              extract_consecutive_failed_runs=20, extract_last_error="AuthenticationError: bad key")
    probs = health.evaluate(st, None, NOW)
    assert keys(probs) == {"bd:extract"}
    assert "AuthenticationError" in probs[0].detail


def test_extract_never_ran_but_failing_warns():
    st = healthy_state()
    st.update(pending_extract=5, extract_last_success_utc=None, extract_consecutive_failed_runs=2)
    assert keys(health.evaluate(st, None, NOW)) == {"bd:extract"}


def test_extract_backlog_without_failures_is_fine():
    st = healthy_state()
    st.update(pending_extract=5)
    assert health.evaluate(st, None, NOW) == []


def test_stale_published_json_warns():
    probs = health.evaluate(healthy_state(), {"generated_at": "2026-09-06T22:25:34Z"}, NOW)
    assert keys(probs) == {"bd:publish"}


def test_problem_shape_matches_completeness():
    p = health.evaluate(None, None, NOW)[0]
    assert set(vars(p)) == {"key", "feed", "severity", "detail"}


def test_check_local_reads_files(tmp_path, monkeypatch):
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps(healthy_state()))
    pj = tmp_path / "paddies.json"
    pj.write_text(json.dumps({"generated_at": _iso(NOW)}))
    monkeypatch.setattr(health, "STATE_PATH", sp)
    monkeypatch.setattr(health, "PADDIES_JSON_PATH", pj)
    assert health.check(NOW, local=True) == []


def test_check_published_falls_back_to_local_state(tmp_path, monkeypatch):
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps(healthy_state()))
    monkeypatch.setattr(health, "STATE_PATH", sp)

    def offline(url, timeout=20):
        raise OSError("offline")

    monkeypatch.setattr(health, "_get_json", offline)
    assert health.check(NOW) == []


# ------------------------------------------------------------- extract health

def test_record_health_success(tmp_path):
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps({"pending_extract": 3, "last_success_utc": "x"}))
    st = extract.record_health({"posts": 3, "posts_extracted": 3, "posts_failed": 0}, NOW, sp)
    assert st["extract_last_success_utc"] == _iso(NOW)
    assert st["extract_consecutive_failed_runs"] == 0
    assert st["pending_extract"] == 0
    assert st["last_success_utc"] == "x"  # ingest keys untouched


def test_record_health_all_failed(tmp_path, monkeypatch):
    sp = tmp_path / "state.json"
    monkeypatch.setattr(extract, "_last_error", "AuthenticationError: invalid x-api-key")
    st = extract.record_health({"posts": 2, "posts_extracted": 0, "posts_failed": 2}, NOW, sp)
    st = extract.record_health({"posts": 2, "posts_extracted": 0, "posts_failed": 2}, NOW, sp)
    assert st["extract_consecutive_failed_runs"] == 2
    assert "AuthenticationError" in st["extract_last_error"]
    assert "extract_last_success_utc" not in st
