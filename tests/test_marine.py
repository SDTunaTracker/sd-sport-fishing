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


def test_wind_less_than_reads_as_zero_to_n():
    assert M.parse_marine_text("Wind variable less than 10 kt. Seas 3 to 5 ft.") == (0, 10, 3, 5)
    assert M.parse_marine_text("Wind NW 10 kt this evening...becoming variable less than 10 kt. "
                               "Seas 5 to 7 ft.") == (0, 10, 5, 7)


def test_parse_ndbc_merges_wind_and_wave_reports_in_an_hour():
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    wind_only = f"{now + timedelta(minutes=50):%Y %m %d %H %M} 330  5.0  7.0    MM    MM    MM  MM 1017 22  MM 16 MM MM MM"
    waves = f"{now + timedelta(minutes=40):%Y %m %d %H %M} 320  6.0  8.0   3.2    MM   9.6 301 1018 19 19.1 17 MM MM MM"
    rows = M.parse_ndbc("\n".join(["#h", wind_only, waves]), "46047")
    assert len(rows) == 1
    st, src, ts, wvht, period, mwd, wspd, wdir, wtmp = rows[0]
    assert ts.endswith(":50:00+00:00")             # newest report's time
    assert (wvht, period, mwd, wspd, wdir, wtmp) == (3.2, 9.6, 301, 5.0, 330, 19.1)  # APD fallback


def test_cdip_water_temp_matching():
    sst = {1000.0: 18.5, 5000.0: 999.0}
    assert M.cdip_water_c(sst, 1600) == 18.5
    assert M.cdip_water_c(sst, 3000) is None          # > 30 min from any reading
    assert M.cdip_water_c(sst, 5000) is None          # fill value
    assert M.cdip_water_c({}, 1000) is None


def test_buoys_payload_history_units_and_ndbc_temp_fill(tmp_path):
    conn = sqlite3.connect(tmp_path / "b.db")
    conn.executescript(M.DDL)
    now = datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc)
    ins = "INSERT INTO buoy_obs VALUES (?,?,?,?,?,?,?,?,?)"
    conn.execute(ins, ("191", "cdip", "2026-11-26T18:00:00+00:00", 1.0, 13.3, 270, None, None, None))
    conn.execute(ins, ("191", "cdip", "2026-11-26T18:30:00+00:00", 1.1, 13.3, 270, None, None, None))
    conn.execute(ins, ("191", "cdip", "2026-11-26T19:00:00+00:00", 1.2, 14.0, 265, None, None, 17.0))
    conn.execute(ins, ("46232", "ndbc", "2026-11-26T18:26:00+00:00", 1.0, 13, 270, None, None, 18.0))
    conn.execute(ins, ("46047", "ndbc", "2026-11-26T19:40:00+00:00", 3.2, 9.6, 301, 7.0, 320, 19.1))
    conn.execute(ins, ("46047", "ndbc", "2026-11-23T19:40:00+00:00", 3.0, 9.0, 300, 7.0, 320, 19.0))  # > 48 h
    p = M.buoys_payload(conn, now)
    by = {b["id"]: b for b in p["buoys"]}
    assert set(by) == {"46047", "46086", "191", "100", "045", "220"}
    pl = by["191"]
    assert [h["t"][11:16] for h in pl["history"]] == ["18:00", "19:00"]   # one per hour
    assert pl["history"][0]["waterF"] == 64.4                         # filled from NDBC 46232
    assert pl["latest"] == {"t": "2026-11-26T19:00:00+00:00", "waveFt": 3.9, "periodS": 14.0,
                            "dirDeg": 265, "windKt": None, "windDirDeg": None, "waterF": 62.6}
    tb = by["46047"]
    assert len(tb["history"]) == 1 and tb["latest"]["windKt"] == 13.6 and tb["latest"]["waveFt"] == 10.5
    assert by["46086"]["latest"] is None and by["46086"]["history"] == []
    assert (tb["lat"], tb["lon"], tb["name"]) == (32.418, -119.535, "Tanner Bank")
    assert p["staleAfterHours"] == 6 and p["hours"] == 48


def test_san_diego_buoys_include_tanner_bank_and_torrey_pines():
    sd = M.REGIONS["san_diego"]
    assert sd["zones"] == ["PZZ740", "PZZ745"]
    assert "46047" in sd["ndbc"] and {"100", "220"} <= set(sd["cdip"])
