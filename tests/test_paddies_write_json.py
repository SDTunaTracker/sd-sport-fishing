"""Tests for scraper.paddies.write_json: window math + schema shape."""
from __future__ import annotations
import json
import os
import sqlite3
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scraper.paddies import ingest_bd, extract as ex, write_json as wj


def _seed(conn, features):
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    # 2 sources; one inside window, one outside
    today = date.today()
    inside_pub  = (today - timedelta(days=3)).isoformat() + "T12:00:00+00:00"
    outside_pub = (today - timedelta(days=30)).isoformat() + "T12:00:00+00:00"
    conn.execute("""INSERT INTO paddy_sources
        (id,source,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('src_in','bdoutdoors','http://x/in','A',NULL,?,?, 'body A',1,0)""",
        (inside_pub, inside_pub))
    conn.execute("""INSERT INTO paddy_sources
        (id,source,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('src_out','bdoutdoors','http://x/out','B',NULL,?,?, 'body B',1,0)""",
        (outside_pub, outside_pub))
    # Mentions for src_in
    now = "2026-09-06T00:00:00+00:00"
    conn.execute("""INSERT INTO paddy_mentions
        (source_id,trip_date,bank,route_json,paddy_count,holding,species_json,water_temp_f,confidence,quote,extracted_at)
        VALUES ('src_in','2026-09-05','182','[]',3,1,'[\"yellowtail\"]',null,0.9,'q1',?)""", (now,))
    conn.execute("""INSERT INTO paddy_mentions
        (source_id,trip_date,bank,route_json,paddy_count,holding,species_json,water_temp_f,confidence,quote,extracted_at)
        VALUES ('src_in','2026-09-04','182','[]',null,0,'[]',null,0.6,'q2',?)""", (now,))
    conn.execute("""INSERT INTO paddy_mentions
        (source_id,trip_date,bank,route_json,paddy_count,holding,species_json,water_temp_f,confidence,quote,extracted_at)
        VALUES ('src_in','2026-09-03',null,'[]',null,null,'[]',null,0.4,'unresolved',?)""", (now,))
    # Mention outside window — should be excluded
    conn.execute("""INSERT INTO paddy_mentions
        (source_id,trip_date,bank,route_json,paddy_count,holding,species_json,water_temp_f,confidence,quote,extracted_at)
        VALUES ('src_out',NULL,'182','[]',10,1,'[]',null,0.5,'ancient',?)""", (now,))
    conn.commit()


@pytest.fixture
def conn_with_data(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setattr(wj, "DB_PATH", p)
    conn = sqlite3.connect(p, timeout=10)
    conn.row_factory = sqlite3.Row
    # Set trip_date on inside mentions so they are always inside the window
    # regardless of when tests run.
    _seed(conn, features=None)
    # override trip dates to be relative to today so window math is deterministic
    today = date.today()
    conn.execute("UPDATE paddy_mentions SET trip_date=? WHERE quote='q1'",
                 ((today - timedelta(days=1)).isoformat(),))
    conn.execute("UPDATE paddy_mentions SET trip_date=? WHERE quote='q2'",
                 ((today - timedelta(days=2)).isoformat(),))
    conn.execute("UPDATE paddy_mentions SET trip_date=? WHERE quote='unresolved'",
                 ((today - timedelta(days=3)).isoformat(),))
    conn.commit()
    yield conn
    conn.close()


def _load_features_from_real_gaz():
    return wj.load_gazetteer_features()


def test_paddies_json_shape_and_window(conn_with_data):
    features = _load_features_from_real_gaz()
    payload = wj.build_paddies_json(conn_with_data, features, "abc1234",
                                     "2026-09-06T00:00:00Z")
    assert payload["build"] == "abc1234"
    assert payload["window_days"] == 14
    # 182 present; ancient outside-window mention excluded
    assert "182" in payload["banks"]
    b = payload["banks"]["182"]
    assert b["name"] == "182"
    assert b["mentions_14d"] == 2       # q1 + q2 (unresolved excluded from bank)
    assert b["paddies_reported_14d"] == 3  # 3 + None(=0)
    assert b["holding_ratio_14d"] == 0.5   # 1 true / (1 true + 1 false)
    assert b["last_report"] == b["recent"][0]["trip_date"]
    # ancient mention is out of window
    assert not any(r["quote"] == "ancient" for r in b["recent"])


def test_unresolved_counted(conn_with_data):
    features = _load_features_from_real_gaz()
    payload = wj.build_paddies_json(conn_with_data, features, "abc", "z")
    # One unresolved mention in-window
    assert payload["unresolved"] == 1


def test_only_banks_with_mentions_in_window(conn_with_data):
    features = _load_features_from_real_gaz()
    payload = wj.build_paddies_json(conn_with_data, features, "abc", "z")
    # Only the '182' bank has 14d mentions in fixture
    assert set(payload["banks"].keys()) == {"182"}


def test_recent_capped_at_5(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setattr(wj, "DB_PATH", p)
    conn = sqlite3.connect(p, timeout=10)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    today = date.today()
    conn.execute("""INSERT INTO paddy_sources
        (id,source,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('s','bdoutdoors','http://x','T',NULL,?,?, 'body',1,0)""",
        (today.isoformat()+"T00:00:00+00:00", today.isoformat()+"T00:00:00+00:00"))
    for i in range(8):
        d = (today - timedelta(days=i)).isoformat()
        conn.execute("""INSERT INTO paddy_mentions
            (source_id,trip_date,bank,route_json,paddy_count,holding,species_json,water_temp_f,confidence,quote,extracted_at)
            VALUES ('s',?,'182','[]',1,1,'[]',null,0.9,?,'2026-09-06T00:00:00+00:00')""",
            (d, f"q{i}"))
    conn.commit()
    features = _load_features_from_real_gaz()
    payload = wj.build_paddies_json(conn, features, "b", "z")
    assert len(payload["banks"]["182"]["recent"]) == 5
    conn.close()


def test_banks_json_excludes_admin_and_has_build():
    features = _load_features_from_real_gaz()
    payload = wj.build_banks_json(features, "sha1234", "2026-09-06T00:00:00Z")
    assert payload["build"] == "sha1234"
    for f in payload["features"]:
        assert f["properties"]["kind"] != "admin"


def test_holding_ratio_none_when_no_definite_holds(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setattr(wj, "DB_PATH", p)
    conn = sqlite3.connect(p, timeout=10)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    today = date.today()
    conn.execute("""INSERT INTO paddy_sources
        (id,source,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('s','bdoutdoors','http://x','T',NULL,?,?, 'body',1,0)""",
        (today.isoformat()+"T00:00:00+00:00", today.isoformat()+"T00:00:00+00:00"))
    # both holding NULL
    conn.execute("""INSERT INTO paddy_mentions
        (source_id,trip_date,bank,route_json,paddy_count,holding,species_json,water_temp_f,confidence,quote,extracted_at)
        VALUES ('s',?,'182','[]',1,NULL,'[]',null,0.9,'a','2026-09-06T00:00:00+00:00')""",
        (today.isoformat(),))
    conn.commit()
    features = _load_features_from_real_gaz()
    payload = wj.build_paddies_json(conn, features, "b", "z")
    assert payload["banks"]["182"]["holding_ratio_14d"] is None
    conn.close()
