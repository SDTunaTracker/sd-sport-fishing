import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src import ais_archive as A

TRACKED = {"367150450": {"name": "Wildcard 95", "landing": "H&M Landing"}}


def _msg(mmsi="367150450", lat=32.6, lon=-117.4, t="2026-11-25 18:03:11.123456789 +0000 UTC",
         mtype="PositionReport", **extra):
    return json.dumps({"MessageType": mtype,
                       "MetaData": {"MMSI": int(mmsi), "latitude": lat, "longitude": lon, "time_utc": t},
                       "Message": {mtype: {"Sog": 9.5, "Cog": 210.0, "TrueHeading": 511, **extra}}})


def test_parse_keeps_tracked_boat_only():
    row = A.parse_message(_msg(), TRACKED)
    assert row[:7] == (367150450, "2026-11-25T18:03:11+00:00", 32.6, -117.4, 9.5, 210.0, None)
    assert row[8] == "aisstream"
    assert A.parse_message(_msg(mmsi="111111111"), TRACKED) is None
    assert A.parse_message(_msg(lat=0.0, lon=0.0), TRACKED) is None
    assert A.parse_message("not json", TRACKED) is None


def test_archive_is_append_only_and_deduped(tmp_path):
    conn = A.open_db(tmp_path / "a.db")
    row = A.parse_message(_msg(), TRACKED)
    conn.execute("INSERT INTO archive_runs (started_at) VALUES ('x')")
    stats = {"messages": 2, "stored": 0}
    A._flush(conn, 1, [row, row], stats)
    A._flush(conn, 1, [row], stats)
    assert conn.execute("SELECT COUNT(*) FROM ais_positions").fetchone()[0] == 1
    assert stats["stored"] == 1


def test_subscription_filters_by_mmsi_when_allowed():
    assert A.subscription("k", TRACKED)["FiltersShipMMSI"] == ["367150450"]
    many = {str(100000000 + i): {} for i in range(A.MAX_MMSI_FILTER + 1)}
    assert "FiltersShipMMSI" not in A.subscription("k", many)


@pytest.mark.real_ais_check
def test_ais_health_rules(tmp_path):
    from src import completeness as C
    now = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)
    assert C.check_ais_archive(now, tmp_path / "missing.db", in_ci=True) == []
    assert {p.key for p in C.check_ais_archive(now, tmp_path / "missing.db", in_ci=False)} == {"ais:archive:missing"}
    conn = A.open_db(tmp_path / "a.db")
    conn.execute("INSERT INTO archive_runs (started_at, ended_at) VALUES (?,?)",
                 ((now - timedelta(hours=5)).isoformat(), (now - timedelta(hours=3)).isoformat()))
    conn.commit(); conn.close()
    keys = {p.key for p in C.check_ais_archive(now, tmp_path / "a.db", in_ci=False)}
    assert keys == {"ais:archive:down", "ais:archive:stale"}
    conn = sqlite3.connect(tmp_path / "a.db")
    conn.execute("UPDATE archive_runs SET ended_at=?", ((now - timedelta(minutes=1)).isoformat(),))
    conn.execute("INSERT INTO ais_positions VALUES (1,?,32,-117,0,0,NULL,'x','aisstream','x')",
                 ((now - timedelta(hours=2)).isoformat(),))
    conn.commit(); conn.close()
    assert C.check_ais_archive(now, tmp_path / "a.db", in_ci=False) == []
