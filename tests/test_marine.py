import sqlite3
from datetime import datetime, timedelta, timezone

from src import marine as M


def test_parse_marine_text():
    assert M.parse_marine_text("NW wind 10 to 15 kt. Seas 3 to 5 ft, building to 5 to 7 ft.") == (10, 15, 3, 7)
    assert M.parse_marine_text("Wind NE 10 kt...becoming NW this afternoon. Seas 3 to 5 ft.") == (10, 10, 3, 5)
    assert M.parse_marine_text("Variable winds less than 10 kt.")[2:] == (None, None)


def test_parse_ndbc_hourly_and_missing_values():
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    def line(dt, wvht="1.9"):
        return f"{dt:%Y %m %d %H %M}  MM   MM   MM   {wvht}    14   8.8 274     MM    MM  23.0    MM   MM   MM    MM"
    text = "\n".join(["#YY MM DD hh mm WDIR ...", "#yr mo ...",
                      line(now + timedelta(minutes=56)), line(now + timedelta(minutes=26), "MM"),
                      line(now - timedelta(minutes=4))])
    rows = M.parse_ndbc(text, "46232")
    assert len(rows) == 2                      # one per hour
    assert rows[0][3] == 1.9 and rows[0][8] == 23.0 and rows[0][6] is None


def test_parse_cdip_ascii():
    txt = "Dataset {...}\n---\nwaveTime[2]\n1795627800, 1795629600\n\nwaveHs[2]\n2.0, 2.15\n"
    assert M.parse_cdip_ascii(txt) == {"waveTime": [1795627800.0, 1795629600.0], "waveHs": [2.0, 2.15]}


def test_region_payload_and_small_craft_badge(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db")
    conn.executescript(M.DDL)
    now = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)
    conn.execute("INSERT INTO marine_forecasts VALUES ('PZZ740','u1',1,'Today',NULL,NULL,'x',10,15,3,5,'f')")
    conn.execute("INSERT INTO marine_alerts VALUES ('a1','Small Craft Advisory','h','Minor','PZZ745',"
                 "'s','2026-11-25T10:00:00+00:00','2026-11-26T10:00:00+00:00',NULL,'f')")
    conn.execute("INSERT INTO marine_alerts VALUES ('a2','Gale Warning','h','Minor','PZZ655',"
                 "'s','o','2026-11-26T10:00:00+00:00',NULL,'f')")
    conn.execute("INSERT INTO tide_predictions VALUES ('9410170','2026-11-26T05:31:00+00:00',4.18,'H')")
    conn.execute("INSERT INTO buoy_obs VALUES ('46232','ndbc','2026-11-25T18:56:00+00:00',1.9,14,274,NULL,NULL,23)")
    sd = M.region_payload(conn, "san_diego", now)
    assert sd["zones"]["PZZ740"]["periods"][0]["windKt"] == [10, 15]
    assert sd["smallCraftAdvisory"] is True and [a["event"] for a in sd["alerts"]] == ["Small Craft Advisory"]
    assert sd["tides"]["events"][0]["type"] == "H"
    assert sd["buoys"]["46232"]["waveM"] == 1.9
    oc = M.region_payload(conn, "oc_la", now)
    assert oc["smallCraftAdvisory"] is False and oc["alerts"][0]["event"] == "Gale Warning"


def test_payload_without_tables_is_empty(tmp_path):
    conn = sqlite3.connect(tmp_path / "e.db")
    assert M.region_payload(conn, "sf_bay")["zones"] == {}


def test_period_window_names():
    upd = "2026-11-25T12:09:00-08:00"          # a Wednesday
    assert M.period_window("Today", upd) == ("2026-11-25T06:00:00-08:00", "2026-11-25T18:00:00-08:00")
    assert M.period_window("Tonight", upd) == ("2026-11-25T18:00:00-08:00", "2026-11-26T06:00:00-08:00")
    assert M.period_window("Thu", upd) == ("2026-11-26T06:00:00-08:00", "2026-11-26T18:00:00-08:00")
    assert M.period_window("Thu Night", upd) == ("2026-11-26T18:00:00-08:00", "2026-11-27T06:00:00-08:00")
    assert M.period_window("Wed", upd)[0].startswith("2026-12-02")   # next week's Wednesday
    assert M.period_window("Rest of week", upd) == (None, None)
