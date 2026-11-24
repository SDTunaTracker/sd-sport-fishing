"""Tests for scraper.paddies.write_json: window math + schema shape."""
from __future__ import annotations
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scraper.paddies import ingest_bd, extract as ex, write_json as wj


def _paddy_payload(*, route=None, paddy_count=None, holding=None,
                   species=None, water_temp_f=None):
    return json.dumps({
        "route":        route or [],
        "paddy_count":  paddy_count,
        "holding":      holding,
        "species":      species or [],
        "water_temp_f": water_temp_f,
    })


def _seed(conn, features):
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    today = date.today()
    inside_pub  = (today - timedelta(days=3)).isoformat() + "T12:00:00+00:00"
    outside_pub = (today - timedelta(days=30)).isoformat() + "T12:00:00+00:00"
    conn.execute("""INSERT INTO paddy_sources
        (id,source,feed_id,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('src_in','bdoutdoors','bd-socal-offshore','http://x/in','A',NULL,?,?, 'body A',1,0)""",
        (inside_pub, inside_pub))
    conn.execute("""INSERT INTO paddy_sources
        (id,source,feed_id,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('src_out','bdoutdoors','bd-socal-offshore','http://x/out','B',NULL,?,?, 'body B',1,0)""",
        (outside_pub, outside_pub))
    now = "2026-09-06T00:00:00+00:00"
    def ins(source_id, trip_date, bank, payload, confidence, quote):
        precision = "bank" if bank else None
        conn.execute(
            'INSERT INTO report_mentions '
            '(source_id,feed_id,type,trip_date,bank,lat,lon,"precision",'
            'payload,confidence,quote,extracted_at) '
            "VALUES (?,'bd-socal-offshore','paddy',?,?,NULL,NULL,?,?,?,?,?)",
            (source_id, trip_date, bank, precision, payload, confidence, quote, now),
        )
    ins("src_in", "2026-09-05", "182",
        _paddy_payload(paddy_count=3, holding=True, species=["yellowtail"]),
        0.9, "q1")
    ins("src_in", "2026-09-04", "182",
        _paddy_payload(paddy_count=None, holding=False),
        0.6, "q2")
    ins("src_in", "2026-09-03", None,
        _paddy_payload(),
        0.4, "unresolved")
    # Mention outside window — should be excluded from the 14-day count.
    ins("src_out", None, "182",
        _paddy_payload(paddy_count=10, holding=True),
        0.5, "ancient")
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
    conn.execute("UPDATE report_mentions SET trip_date=? WHERE quote='q1'",
                 ((today - timedelta(days=1)).isoformat(),))
    conn.execute("UPDATE report_mentions SET trip_date=? WHERE quote='q2'",
                 ((today - timedelta(days=2)).isoformat(),))
    conn.execute("UPDATE report_mentions SET trip_date=? WHERE quote='unresolved'",
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
        (id,source,feed_id,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('s','bdoutdoors','bd-socal-offshore','http://x','T',NULL,?,?, 'body',1,0)""",
        (today.isoformat()+"T00:00:00+00:00", today.isoformat()+"T00:00:00+00:00"))
    for i in range(8):
        d = (today - timedelta(days=i)).isoformat()
        payload = _paddy_payload(paddy_count=1, holding=True)
        conn.execute(
            'INSERT INTO report_mentions '
            '(source_id,feed_id,type,trip_date,bank,lat,lon,"precision",'
            'payload,confidence,quote,extracted_at) '
            "VALUES ('s','bd-socal-offshore','paddy',?,'182',NULL,NULL,'bank',"
            "?,0.9,?,'2026-09-06T00:00:00+00:00')",
            (d, payload, f"q{i}"),
        )
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


# =====================================================================
# build_reports_json — v2
# =====================================================================


def _bite_payload(species=None, count=None, size_lb=None,
                  method=None, bait=None, outcome=None):
    return json.dumps({
        "species": species or [], "count": count, "size_lb": size_lb,
        "method": method, "bait": bait, "outcome": outcome,
    })


def _cond_payload(water_temp_f=None, water_color=None, current=None,
                  bait_marks=None, life=None, sea_state=None):
    return json.dumps({
        "water_temp_f": water_temp_f, "water_color": water_color,
        "current": current, "bait_marks": bait_marks,
        "life": life or [], "sea_state": sea_state,
    })


def _pos_payload(raw, kind, ref_bank=None, bearing_deg=None, distance_nm=None):
    return json.dumps({
        "raw": raw, "kind": kind, "ref_bank": ref_bank,
        "bearing_deg": bearing_deg, "distance_nm": distance_nm,
    })


def _mk_conn_with_v2_data(path):
    """Fixture DB: 2 sources across 2 feeds, mentions of all 4 types."""
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)

    today = date.today()

    def src(sid, feed, pub_days_ago, url):
        pub = (today - timedelta(days=pub_days_ago)).isoformat() + "T00:00:00+00:00"
        conn.execute("""INSERT INTO paddy_sources
            (id, source, feed_id, url, title, author, published_at, fetched_at,
             raw_text, extracted, truncated)
            VALUES (?, 'bdoutdoors', ?, ?, 'T', NULL, ?, ?, 'body', 1, 0)""",
            (sid, feed, url, pub, pub))

    def ment(source_id, mtype, bank, trip_days_ago, payload, quote, *,
             lat=None, lon=None, precision=None, feed_id="bd-socal-offshore"):
        td = (today - timedelta(days=trip_days_ago)).isoformat()
        conn.execute(
            'INSERT INTO report_mentions '
            '(source_id, feed_id, type, trip_date, bank, lat, lon, "precision", '
            'payload, confidence, quote, extracted_at) '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.9, ?, '2026-09-06T00:00:00+00:00')",
            (source_id, feed_id, mtype, td, bank, lat, lon, precision,
             payload, quote),
        )

    src("s-a", "bd-socal-offshore", 0, "http://x/a")
    src("s-b", "bd-spearfishing",   0, "http://x/b")

    # In-window (14d), some in last 48h:
    # bite today at 182 (48h)
    ment("s-a", "bite", "182", 0, _bite_payload(
        species=["yellowtail"], count=8, outcome="steady", method="surface_iron"
    ), "8 nice YT")
    # bite yesterday at 182 (48h)
    ment("s-a", "bite", "182", 1, _bite_payload(
        species=["yellowtail","dorado"], count=3, outcome="scratchy"
    ), "few YT and a dodo")
    # bite 3 days ago at the-corner (in 14d window, not 48h)
    ment("s-a", "bite", "the-corner", 3, _bite_payload(
        species=["dorado"], count=1, outcome="skunk"
    ), "one dodo")
    # paddy 5 days ago at 302 (in 14d)
    ment("s-a", "paddy", "302", 5, json.dumps({
        "route": [], "paddy_count": 4, "holding": True,
        "species": ["yellowtail"], "water_temp_f": 68.0
    }), "found some paddies at 302")
    # conditions today at 182 with water_color blue (48h)
    ment("s-a", "conditions", "182", 0, _cond_payload(
        water_temp_f=69.5, water_color="blue", life=["birds"]
    ), "blue and 69F")
    # conditions yesterday, water_color green (48h)
    ment("s-b", "conditions", "182", 1, _cond_payload(
        water_temp_f=68.0, water_color="blue",
    ), "blue clean", feed_id="bd-spearfishing")

    # a GPS position today with a bite tied via matching lat/lon
    ment("s-a", "position", None, 0,
         _pos_payload("32.4083 -117.3017", "gps"),
         "32.4083 -117.3017",
         lat=32.4083, lon=-117.3017, precision="gps")
    ment("s-a", "bite", None, 0,
         _bite_payload(species=["yellowtail"], count=2, outcome="wide_open"),
         "wide open here",
         lat=32.4083, lon=-117.3017, precision="gps")

    # an offset position, from spearfishing feed, at 6 nm SW of 182
    ment("s-b", "position", None, 0,
         _pos_payload("6 miles SW of the 182", "offset",
                       ref_bank="182", bearing_deg=225, distance_nm=6.0),
         "6 miles SW of the 182",
         lat=32.412, lon=-117.842, precision="offset", feed_id="bd-spearfishing")

    # An UNRESOLVED bite (no bank, no lat) — should bump unresolved_14d
    ment("s-a", "bite", None, 0,
         _bite_payload(species=["yellowtail"]),
         "somewhere out there")

    # Out of window mention (30 days back) — should NOT appear anywhere
    ment("s-a", "bite", "182", 30, _bite_payload(species=["yellowtail"]),
         "ancient")

    conn.commit()
    return conn


FAKE_FEEDS = [
    {"id": "bd-socal-offshore", "name": "BD SoCal Offshore",
     "forum_url": "http://x/socal", "rss_url": "x", "enabled": True},
    {"id": "bd-spearfishing",   "name": "BD Spearfishing",
     "forum_url": "http://x/spear", "rss_url": "x", "enabled": True},
]


@pytest.fixture
def reports_db(tmp_path):
    return _mk_conn_with_v2_data(tmp_path / "r.db")


def test_reports_top_level_schema(reports_db):
    features = _load_features_from_real_gaz()
    p = wj.build_reports_json(reports_db, features, "abc1234",
                               "2026-09-06T00:00:00Z", FAKE_FEEDS)
    for key in ("build", "generated_at", "window_days", "feeds",
                 "summary_48h", "banks", "pins", "unresolved_14d"):
        assert key in p, f"missing top-level key {key}"
    assert p["build"] == "abc1234"
    assert p["window_days"] == 14


def test_reports_feeds_items_14d(reports_db):
    features = _load_features_from_real_gaz()
    p = wj.build_reports_json(reports_db, features, "b", "z", FAKE_FEEDS)
    by_id = {f["id"]: f for f in p["feeds"]}
    assert by_id["bd-socal-offshore"]["items_14d"] == 1  # 1 source
    assert by_id["bd-spearfishing"]["items_14d"] == 1


def test_reports_banks_rollup(reports_db):
    features = _load_features_from_real_gaz()
    p = wj.build_reports_json(reports_db, features, "b", "z", FAKE_FEEDS)
    assert "182" in p["banks"]
    b = p["banks"]["182"]
    assert b["mentions_14d"] == 4   # 2 bites + 2 conditions
    assert b["bite_14d"] == 2
    assert b["species_14d"]["yellowtail"] == 2
    assert b["species_14d"]["dorado"] == 1
    # outcome mode: 'steady' and 'scratchy' each 1x -> tied; Counter picks first
    assert b["outcome_mode"] in ("steady", "scratchy")
    assert b["lat"] is not None and b["lon"] is not None
    assert b["radius_nm"] is not None


def test_reports_recent_capped_at_8(tmp_path):
    p = tmp_path / "many.db"
    conn = sqlite3.connect(p, timeout=10)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    today = date.today()
    conn.execute("""INSERT INTO paddy_sources
        (id, source, feed_id, url, title, author, published_at, fetched_at,
         raw_text, extracted, truncated)
        VALUES ('s', 'bdoutdoors', 'bd-socal-offshore', 'http://x', 'T',
         NULL, ?, ?, 'body', 1, 0)""",
        (today.isoformat()+"T00:00:00+00:00", today.isoformat()+"T00:00:00+00:00"))
    for i in range(12):
        td = (today - timedelta(days=i)).isoformat()
        conn.execute(
            'INSERT INTO report_mentions '
            '(source_id, feed_id, type, trip_date, bank, lat, lon, "precision", '
            'payload, confidence, quote, extracted_at) '
            "VALUES ('s', 'bd-socal-offshore', 'bite', ?, '182', NULL, NULL, "
            "'bank', ?, 0.9, ?, '2026-09-06T00:00:00+00:00')",
            (td, _bite_payload(species=["yellowtail"], count=1), f"q{i}"),
        )
    conn.commit()
    features = _load_features_from_real_gaz()
    p = wj.build_reports_json(conn, features, "b", "z", FAKE_FEEDS)
    assert len(p["banks"]["182"]["recent"]) == 8
    conn.close()


def test_reports_pins_include_resolution(reports_db):
    features = _load_features_from_real_gaz()
    p = wj.build_reports_json(reports_db, features, "b", "z", FAKE_FEEDS)
    assert len(p["pins"]) == 2
    kinds = {pin["resolution"] for pin in p["pins"]}
    assert "gps" in kinds
    assert "offset:182" in kinds
    # gps pin picks up species/bank from its sibling bite in the same source
    gps_pin = next(pin for pin in p["pins"] if pin["resolution"] == "gps")
    assert gps_pin["species"] == ["yellowtail"]
    assert gps_pin["raw"] == "32.4083 -117.3017"
    assert gps_pin["precision"] == "gps"


def test_reports_summary_48h(reports_db):
    features = _load_features_from_real_gaz()
    # Pin `now` at today-noon UTC so today-and-yesterday trip_dates are both
    # comfortably inside the 48h window regardless of wall-clock hour.
    now_fixed = datetime.combine(date.today(),
                                 datetime.min.time().replace(hour=12),
                                 tzinfo=timezone.utc)
    p = wj.build_reports_json(reports_db, features, "b", "z", FAKE_FEEDS,
                                now=now_fixed)
    s = p["summary_48h"]
    assert len(s["top_banks"]) >= 1
    assert s["top_banks"][0]["bank"] == "182"
    assert s["water_temp_f"] is not None
    assert s["water_temp_f"]["min"] == 68.0
    assert s["water_temp_f"]["max"] == 69.5
    # water_color_mode "blue" (2x blue in 48h from 2 conditions rows)
    assert s["water_color_mode"] == "blue"


def test_reports_unresolved_14d(reports_db):
    features = _load_features_from_real_gaz()
    p = wj.build_reports_json(reports_db, features, "b", "z", FAKE_FEEDS)
    # We seeded exactly one unresolved bite (no bank, no lat)
    assert p["unresolved_14d"] == 1


def test_reports_out_of_window_excluded(reports_db):
    features = _load_features_from_real_gaz()
    p = wj.build_reports_json(reports_db, features, "b", "z", FAKE_FEEDS)
    # The "ancient" bite (30 days back) is NOT in recent[] of the 182 bank
    for r in p["banks"]["182"]["recent"]:
        assert r["quote"] != "ancient"


def test_write_emits_reports_json(tmp_path, monkeypatch):
    monkeypatch.setattr(wj, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(wj, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(wj, "PADDIES_OUT", tmp_path / "out" / "paddies.json")
    monkeypatch.setattr(wj, "BANKS_OUT",   tmp_path / "out" / "banks.json")
    monkeypatch.setattr(wj, "REPORTS_OUT", tmp_path / "out" / "reports.json")
    # Seed
    _mk_conn_with_v2_data(tmp_path / "t.db").close()
    # Mock enabled_feeds so the write() call doesn't rely on the real feeds.py
    monkeypatch.setattr(wj, "enabled_feeds", lambda: FAKE_FEEDS)
    stats = wj.write()
    assert (tmp_path / "out" / "reports.json").exists()
    assert stats["reports_pins"] == 2
    assert stats["reports_unresolved"] == 1


def test_holding_ratio_none_when_no_definite_holds(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    monkeypatch.setattr(wj, "DB_PATH", p)
    conn = sqlite3.connect(p, timeout=10)
    conn.row_factory = sqlite3.Row
    ingest_bd.ensure_schema(conn)
    ex.ensure_schema(conn)
    today = date.today()
    conn.execute("""INSERT INTO paddy_sources
        (id,source,feed_id,url,title,author,published_at,fetched_at,raw_text,extracted,truncated)
        VALUES ('s','bdoutdoors','bd-socal-offshore','http://x','T',NULL,?,?, 'body',1,0)""",
        (today.isoformat()+"T00:00:00+00:00", today.isoformat()+"T00:00:00+00:00"))
    # holding NULL
    payload = _paddy_payload(paddy_count=1, holding=None)
    conn.execute(
        'INSERT INTO report_mentions '
        '(source_id,feed_id,type,trip_date,bank,lat,lon,"precision",'
        'payload,confidence,quote,extracted_at) '
        "VALUES ('s','bd-socal-offshore','paddy',?,'182',NULL,NULL,'bank',"
        "?,0.9,'a','2026-09-06T00:00:00+00:00')",
        (today.isoformat(), payload),
    )
    conn.commit()
    features = _load_features_from_real_gaz()
    payload_out = wj.build_paddies_json(conn, features, "b", "z")
    assert payload_out["banks"]["182"]["holding_ratio_14d"] is None
    conn.close()
