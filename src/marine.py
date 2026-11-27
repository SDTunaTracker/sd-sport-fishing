"""Trip-day marine conditions: NWS marine forecasts and alerts, NOAA tides,
NDBC and CDIP buoys, for San Diego, OC/LA and the SF Bay.

All sources are free US-government (or UCSD/CDIP) public data, fetched with
an identifying User-Agent as api.weather.gov asks. Stored in tracker.db:

  marine_forecasts  NWS zone forecast periods, kept 30 days
  marine_alerts     NWS alerts touching our zones (Small Craft Advisory etc.)
  tide_predictions  CO-OPS high/low predictions, 14 days ahead
  buoy_obs          NDBC realtime2 (hourly) + CDIP THREDDS wave records
  marine_fetch_log  last successful fetch per kind, for freshness alerts

    .venv\\Scripts\\python.exe -m src.marine            # refresh everything now
    .venv\\Scripts\\python.exe -m src.marine --show san_diego
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .net import get_with_retry

log = logging.getLogger(__name__)

UA = "TunaTrackerBot/1.0 (+https://thetunatracker.com; trip-day marine conditions)"

# NWS marine zones (api.weather.gov ids; PZZ750/775 don't exist), CO-OPS tide
# station, NDBC buoys and CDIP stations per site region.
REGIONS: dict[str, dict] = {
    "san_diego": {"zones": ["PZZ740", "PZZ745"], "tide": "9410170",
                  "ndbc": ["46232", "46086", "46047"], "cdip": ["191", "045", "100", "220"]},
    "oc_la":     {"zones": ["PZZ655", "PZZ676"], "tide": "9410660",
                  "ndbc": ["46221", "46222", "46025"], "cdip": ["092", "028"]},
    "sf_bay":    {"zones": ["PZZ530", "PZZ531", "PZZ545", "PZZ571"], "tide": "9414290",
                  "ndbc": ["46026", "46237"], "cdip": ["142"]},
}

# Buoys shown as pins on the Charts map (web/api/v1/buoys.json), with their
# NDBC positions (activestations.xml). NDBC 46232 is the same physical buoy as
# CDIP 191, so it has no pin of its own: its water temp fills CDIP 191's gaps.
BUOY_PINS: dict[str, dict] = {
    "46047": {"source": "ndbc", "name": "Tanner Bank", "lat": 32.418, "lon": -119.535},
    "46086": {"source": "ndbc", "name": "San Clemente Basin", "lat": 32.504, "lon": -118.029},
    "191":   {"source": "cdip", "name": "Point Loma South", "lat": 32.517, "lon": -117.425,
              "alsoNdbc": "46232"},
    "100":   {"source": "cdip", "name": "Torrey Pines Outer", "lat": 32.933, "lon": -117.391},
    "045":   {"source": "cdip", "name": "Oceanside Offshore", "lat": 33.178, "lon": -117.472},
    "220":   {"source": "cdip", "name": "Mission Bay West", "lat": 32.749, "lon": -117.502},
}
BUOY_HISTORY_HOURS = 48
BUOY_KEEP_DAYS = 14
BUOYS_JSON = Path(__file__).resolve().parents[1] / "web" / "api" / "v1" / "buoys.json"

# Minimum time between fetches of each kind (alerts change any time).
EVERY = {
    "alerts": timedelta(minutes=10),
    "forecasts": timedelta(hours=3),
    "buoys": timedelta(minutes=50),
    "tides": timedelta(hours=24),
}
FORECAST_KEEP_DAYS = 30

DDL = """
CREATE TABLE IF NOT EXISTS marine_forecasts (
    zone TEXT NOT NULL, updated_at TEXT NOT NULL, period INTEGER NOT NULL,
    name TEXT, start_time TEXT, end_time TEXT, detail TEXT,
    wind_kt_min REAL, wind_kt_max REAL, seas_ft_min REAL, seas_ft_max REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (zone, updated_at, period)
);
CREATE TABLE IF NOT EXISTS marine_alerts (
    alert_id TEXT PRIMARY KEY, event TEXT, headline TEXT, severity TEXT,
    zones TEXT, sent TEXT, onset TEXT, ends TEXT, expires TEXT, fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tide_predictions (
    station TEXT NOT NULL, ts TEXT NOT NULL, height_ft REAL, type TEXT,
    PRIMARY KEY (station, ts)
);
CREATE TABLE IF NOT EXISTS buoy_obs (
    station TEXT NOT NULL, source TEXT NOT NULL, ts TEXT NOT NULL,
    wvht_m REAL, dpd_s REAL, mwd_deg REAL, wspd_ms REAL, wdir_deg REAL, wtmp_c REAL,
    PRIMARY KEY (station, source, ts)
);
CREATE TABLE IF NOT EXISTS marine_fetch_log (
    kind TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, detail TEXT
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _get(url: str, params: dict | None = None, accept: str = "*/*", timeout: float = 30.0):
    return get_with_retry(url, params=params, headers={"User-Agent": UA, "Accept": accept},
                          timeout=timeout, attempts=3, backoff=5.0)


# ── NWS ─────────────────────────────────────────────────────────────────────

_WIND_RE = re.compile(r"\b(?:wind|winds)\b[^.]*?(\d+)(?:\s+to\s+(\d+))?\s*kt", re.I)
_WIND_RE2 = re.compile(r"\b[NSEW]{1,3}\s+(?:wind\s+)?(\d+)(?:\s+to\s+(\d+))?\s*kt", re.I)
_WIND_LT_RE = re.compile(r"less than (\d+)\s*kt", re.I)
_SEAS_SENT_RE = re.compile(r"\bSeas\b[^.]*", re.I)   # "Seas 3 to 5 ft, building to 5 to 7 ft"
_FT_RE = re.compile(r"(\d+)(?:\s+to\s+(\d+))?\s*(?:ft|feet|foot)\b", re.I)


def parse_marine_text(text: str) -> tuple[float | None, float | None, float | None, float | None]:
    """(wind_min, wind_max, seas_min, seas_max) from an NWS period's text.

    "Wind variable less than 10 kt" gives (0, 10), shown as "<10 kt".
    """
    winds = [(0, int(n)) for n in _WIND_LT_RE.findall(text)]
    text_w = _WIND_LT_RE.sub(" ", text)
    winds += [(int(a), int(b or a)) for a, b in _WIND_RE2.findall(text_w) + _WIND_RE.findall(text_w)]
    seas = [(int(a), int(b or a)) for sent in _SEAS_SENT_RE.findall(text)
            for a, b in _FT_RE.findall(sent)]
    wmin = min((a for a, _ in winds), default=None)
    wmax = max((b for _, b in winds), default=None)
    smin = min((a for a, _ in seas), default=None)
    smax = max((b for _, b in seas), default=None)
    return wmin, wmax, smin, smax


_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def period_window(name: str | None, updated: str | None) -> tuple[str | None, str | None]:
    """Approximate (start, end) for an NWS zone-forecast period from its name.

    Zone forecasts carry only names ("Today", "This Afternoon", "Tonight",
    "Thu", "Thu Night"). Days run 06:00-18:00 and nights 18:00-06:00 Pacific,
    the NWS convention; "This Afternoon" starts at 12:00. Returns ISO strings
    with the Pacific offset, or (None, None) if the name isn't recognised.
    """
    from .dates import PACIFIC
    if not name or not updated:
        return None, None
    try:
        base = datetime.fromisoformat(updated).astimezone(PACIFIC)
    except ValueError:
        return None, None
    day = base.replace(hour=0, minute=0, second=0, microsecond=0)
    n = name.strip().lower()
    def at(d, h):
        return d.replace(hour=h) if h < 24 else (d + timedelta(days=1)).replace(hour=h - 24)
    if n in ("today", "this morning"):
        s, e = at(day, 6), at(day, 18)
    elif n == "this afternoon":
        s, e = at(day, 12), at(day, 18)
    elif n in ("tonight", "this evening", "overnight"):
        s, e = at(day, 18), at(day, 30)
    else:
        night = n.endswith(" night")
        key = n.replace(" night", "")[:3].title()
        if key not in _DAYS:
            return None, None
        ahead = (_DAYS.index(key) - day.weekday()) % 7 or 7
        d = day + timedelta(days=ahead)
        s, e = (at(d, 18), at(d, 30)) if night else (at(d, 6), at(d, 18))
    return s.isoformat(), e.isoformat()


def fetch_forecasts(conn: sqlite3.Connection, zones: list[str]) -> int:
    n = 0
    fetched = _iso(_now())
    for z in zones:
        r = _get(f"https://api.weather.gov/zones/forecast/{z}/forecast", accept="application/geo+json")
        props = r.json().get("properties", {})
        updated = props.get("updated") or fetched
        rows = []
        for p in props.get("periods", []):
            text = p.get("detailedForecast") or ""
            start, end = p.get("startTime"), p.get("endTime")
            if not (start and end):
                start, end = period_window(p.get("name"), updated)
            rows.append((z, updated, p.get("number"), p.get("name"), start, end,
                         text, *parse_marine_text(text), fetched))
        before = conn.total_changes
        conn.executemany("INSERT OR IGNORE INTO marine_forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        n += conn.total_changes - before
    cutoff = _iso(_now() - timedelta(days=FORECAST_KEEP_DAYS))
    conn.execute("DELETE FROM marine_forecasts WHERE fetched_at < ?", (cutoff,))
    return n


def fetch_alerts(conn: sqlite3.Connection, zones: list[str]) -> int:
    r = _get("https://api.weather.gov/alerts/active", params={"zone": ",".join(zones)},
             accept="application/geo+json")
    fetched = _iso(_now())
    rows = []
    for f in r.json().get("features", []):
        p = f.get("properties", {})
        zs = sorted({u.rsplit("/", 1)[-1] for u in p.get("affectedZones", [])} & set(zones))
        rows.append((p.get("id") or f.get("id"), p.get("event"), p.get("headline"), p.get("severity"),
                     ",".join(zs), p.get("sent"), p.get("onset"), p.get("ends"), p.get("expires"), fetched))
    conn.executemany("""INSERT INTO marine_alerts VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(alert_id) DO UPDATE SET headline=excluded.headline, ends=excluded.ends,
        expires=excluded.expires, fetched_at=excluded.fetched_at""", rows)
    return len(rows)


# ── Tides (CO-OPS) ──────────────────────────────────────────────────────────

def fetch_tides(conn: sqlite3.Connection, station: str, days: int = 14) -> int:
    start = _now() - timedelta(days=1)
    r = _get("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter", params={
        "product": "predictions", "datum": "MLLW", "station": station, "time_zone": "gmt",
        "units": "english", "interval": "hilo", "format": "json",
        "begin_date": start.strftime("%Y%m%d"), "range": 24 * (days + 1),
        "application": "TunaTracker"})
    preds = r.json().get("predictions", [])
    rows = [(station, f"{p['t'].replace(' ', 'T')}:00+00:00", float(p["v"]), p.get("type"))
            for p in preds]
    conn.executemany("INSERT OR REPLACE INTO tide_predictions VALUES (?,?,?,?)", rows)
    return len(rows)


# ── Buoys ───────────────────────────────────────────────────────────────────

def _f(v: str) -> float | None:
    return None if v in ("MM", "", "999", "99.0", "999.0", "9999.0") else float(v)


def parse_ndbc(text: str, station: str, hours: int = 48) -> list[tuple]:
    """NDBC realtime2 .txt -> hourly buoy_obs rows.

    Stations report wind every 10 min but waves once an hour, so each hour's
    row takes the newest report's time and, field by field, the newest
    non-missing value in that hour. Dominant period (DPD) falls back to the
    average period (APD) when the buoy doesn't send DPD.
    """
    by_hour: dict[datetime, list] = {}
    cutoff = _now() - timedelta(hours=hours)
    for line in text.splitlines():                 # newest first in the feed
        if line.startswith("#") or not line.strip():
            continue
        c = line.split()
        if len(c) < 15:
            continue
        ts = datetime(int(c[0]), int(c[1]), int(c[2]), int(c[3]), int(c[4]), tzinfo=timezone.utc)
        if ts < cutoff:
            continue
        period = _f(c[9])
        if period is None:
            period = _f(c[10])
        vals = [_f(c[8]), period, _f(c[11]), _f(c[6]), _f(c[5]), _f(c[14])]
        cur = by_hour.get(ts.replace(minute=0))
        if cur is None:
            by_hour[ts.replace(minute=0)] = [ts] + vals
        else:
            for i, v in enumerate(vals, 1):
                if cur[i] is None:
                    cur[i] = v
    return [(station, "ndbc", _iso(r[0]), *r[1:]) for r in by_hour.values()]


def fetch_ndbc(conn: sqlite3.Connection, station: str) -> int:
    r = _get(f"https://www.ndbc.noaa.gov/data/realtime2/{station}.txt")
    rows = parse_ndbc(r.text, station)
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO buoy_obs VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return conn.total_changes - before


_CDIP = "https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/realtime/{s}p1_rt.nc"


def parse_cdip_ascii(text: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for name, body in re.findall(r"^(\w+)\[\d+\]\n([^\n]+)", text, re.M):
        out[name] = [float(x) for x in body.split(",")]
    return out


def cdip_water_c(sst: dict[float, float], t: float, within_s: float = 1800) -> float | None:
    """The CDIP water temp nearest to wave time t (within 30 min), else None."""
    if not sst:
        return None
    k = min(sst, key=lambda x: abs(x - t))
    v = sst[k]
    if abs(k - t) > within_s or v is None or v < -5 or v > 40:   # CDIP fill values
        return None
    return round(v, 2)


def fetch_cdip(conn: sqlite3.Connection, station: str, records: int = 96) -> int:
    dds = _get(_CDIP.format(s=station) + ".dds").text
    m = re.search(r"Int32 waveTime\[waveTime = (\d+)\]", dds)
    if not m:
        return 0
    n = int(m.group(1))
    a, b = max(0, n - records), n - 1
    sl = f"[{a}:1:{b}]"
    q = ",".join(f"{v}{sl}" for v in ("waveTime", "waveHs", "waveTp", "waveDp"))
    data = parse_cdip_ascii(_get(_CDIP.format(s=station) + ".ascii?" + q).text)
    # Water temperature has its own time axis (sstTime); match it to wave records.
    sst: dict[float, float] = {}
    m2 = re.search(r"Int32 sstTime\[sstTime = (\d+)\]", dds)
    if m2:
        ns = int(m2.group(1))
        sl2 = f"[{max(0, ns - records)}:1:{ns - 1}]"
        try:
            sd = parse_cdip_ascii(_get(_CDIP.format(s=station) + ".ascii?"
                                       + f"sstTime{sl2},sstSeaSurfaceTemperature{sl2}").text)
            sst = dict(zip(sd.get("sstTime", []), sd.get("sstSeaSurfaceTemperature", [])))
        except Exception as e:  # noqa: BLE001 — waves still useful without temp
            log.info("CDIP %s sst fetch failed: %s", station, e)
    rows = [(station, "cdip", _iso(datetime.fromtimestamp(t, timezone.utc)), hs, tp, dp, None, None,
             cdip_water_c(sst, t))
            for t, hs, tp, dp in zip(data.get("waveTime", []), data.get("waveHs", []),
                                     data.get("waveTp", []), data.get("waveDp", []))]
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO buoy_obs VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return conn.total_changes - before


# ── Orchestration ───────────────────────────────────────────────────────────

def _due(conn: sqlite3.Connection, kind: str, now: datetime) -> bool:
    row = conn.execute("SELECT fetched_at FROM marine_fetch_log WHERE kind=?", (kind,)).fetchone()
    return not row or now - datetime.fromisoformat(row[0]) >= EVERY[kind]


def _mark(conn: sqlite3.Connection, kind: str, detail: str) -> None:
    conn.execute("INSERT OR REPLACE INTO marine_fetch_log VALUES (?,?,?)", (kind, _iso(_now()), detail))


def _fetch_buoys(conn: sqlite3.Connection) -> str:
    """Every buoy, each on its own so one dead station doesn't stop the rest."""
    n, bad = 0, []
    for src, fn in (("ndbc", fetch_ndbc), ("cdip", fetch_cdip)):
        for s in sorted({s for r in REGIONS.values() for s in r[src]}):
            try:
                n += fn(conn, s)
            except Exception as e:  # noqa: BLE001
                bad.append(s)
                log.warning("buoy %s %s failed: %s", src, s, e)
    conn.execute("DELETE FROM buoy_obs WHERE ts < ?", (_iso(_now() - timedelta(days=BUOY_KEEP_DAYS)),))
    if bad and n == 0:
        raise RuntimeError("all buoys failed: " + ",".join(bad))
    return f"+{n} obs" + (f" (failed: {','.join(bad)})" if bad else "")


def refresh(conn: sqlite3.Connection, force: bool = False) -> dict[str, str]:
    """Fetch whatever is due. Never raises; returns {kind: summary or error}."""
    conn.executescript(DDL)
    now = _now()
    zones = [z for r in REGIONS.values() for z in r["zones"]]
    jobs = {
        "alerts": lambda: f"{fetch_alerts(conn, zones)} active",
        "forecasts": lambda: f"+{fetch_forecasts(conn, zones)} periods",
        "tides": lambda: f"{sum(fetch_tides(conn, r['tide']) for r in REGIONS.values())} hi/lo",
        "buoys": lambda: _fetch_buoys(conn),
    }
    out = {}
    for kind, job in jobs.items():
        if not (force or _due(conn, kind, now)):
            continue
        try:
            out[kind] = job()
            _mark(conn, kind, out[kind])
        except Exception as e:  # noqa: BLE001 — one source down shouldn't stop the rest
            out[kind] = f"ERROR {type(e).__name__}: {e}"[:200]
            log.warning("marine %s fetch failed: %s", kind, e)
        conn.commit()
    return out


def region_payload(conn: sqlite3.Connection, region: str, now: datetime | None = None) -> dict:
    """Compact trip-day conditions for one region (for data.js / region files).

    {"zones": {zone: {"updated", "periods": [{"name","start","end","text",
               "windKt": [min,max], "seasFt": [min,max]}]}},
     "alerts": [{"event","headline","zones","onset","ends"}],
     "smallCraftAdvisory": bool,
     "tides": {"station", "events": [{"t","ft","type"}]}   # next 7 days
     "buoys": {station: {"source","t","waveM","periodS","dirDeg","windMs","waterC"}}}
    """
    now = now or _now()
    cfg = REGIONS[region]
    out: dict = {"zones": {}, "alerts": [], "smallCraftAdvisory": False,
                 "tides": {"station": cfg["tide"], "events": []}, "buoys": {}}
    try:
        for z in cfg["zones"]:
            upd = conn.execute("SELECT MAX(updated_at) FROM marine_forecasts WHERE zone=?", (z,)).fetchone()[0]
            if not upd:
                continue
            periods = [{"name": r[0], "start": r[1] or period_window(r[0], upd)[0],
                        "end": r[2] or period_window(r[0], upd)[1], "text": r[3],
                        "windKt": [r[4], r[5]], "seasFt": [r[6], r[7]]}
                       for r in conn.execute(
                           "SELECT name, start_time, end_time, detail, wind_kt_min, wind_kt_max,"
                           " seas_ft_min, seas_ft_max FROM marine_forecasts"
                           " WHERE zone=? AND updated_at=? ORDER BY period LIMIT 10", (z, upd))]
            out["zones"][z] = {"updated": upd, "periods": periods}
        nowi = _iso(now)
        for r in conn.execute("SELECT event, headline, zones, onset, ends, expires FROM marine_alerts"
                              " WHERE COALESCE(ends, expires) > ? ORDER BY onset", (nowi,)):
            zs = set((r[2] or "").split(","))
            if zs & set(cfg["zones"]):
                out["alerts"].append({"event": r[0], "headline": r[1], "zones": sorted(zs & set(cfg["zones"])),
                                      "onset": r[3], "ends": r[4] or r[5]})
        out["smallCraftAdvisory"] = any("small craft" in (a["event"] or "").lower() for a in out["alerts"])
        out["tides"]["events"] = [{"t": r[0], "ft": r[1], "type": r[2]} for r in conn.execute(
            "SELECT ts, height_ft, type FROM tide_predictions WHERE station=? AND ts BETWEEN ? AND ?"
            " ORDER BY ts", (cfg["tide"], _iso(now - timedelta(hours=12)), _iso(now + timedelta(days=7))))]
        for src, stations in (("ndbc", cfg["ndbc"]), ("cdip", cfg["cdip"])):
            for s in stations:
                r = conn.execute("SELECT ts, wvht_m, dpd_s, mwd_deg, wspd_ms, wdir_deg, wtmp_c FROM buoy_obs"
                                 " WHERE station=? AND source=? ORDER BY ts DESC LIMIT 1", (s, src)).fetchone()
                if r:
                    out["buoys"][s] = {"source": src, "t": r[0], "waveM": r[1], "periodS": r[2],
                                       "dirDeg": r[3], "windMs": r[4], "windDirDeg": r[5], "waterC": r[6]}
    except sqlite3.OperationalError:
        pass   # tables not created yet
    return out


def _r(v, n=1):
    return None if v is None else round(v, n)


def buoys_payload(conn: sqlite3.Connection, now: datetime | None = None,
                  hours: int = BUOY_HISTORY_HOURS) -> dict:
    """Charts buoy pins with a 48-hour hourly history (web/api/v1/buoys.json).

    Display units: waveFt, periodS, dirDeg (where the swell comes from),
    windKt, windDirDeg (where the wind comes from), waterF. Missing values are
    null; CDIP waveriders have no wind sensor. `latest` is the newest record;
    readers treat it as stale when `t` is older than staleAfterHours.
    """
    now = now or _now()
    since = _iso(now - timedelta(hours=hours))
    out = {"generatedAt": _iso(now), "source": "NOAA NDBC and CDIP (Scripps / UC San Diego)",
           "staleAfterHours": 6, "hours": hours, "buoys": []}
    for sid, meta in BUOY_PINS.items():
        try:
            rows = conn.execute("SELECT ts, wvht_m, dpd_s, mwd_deg, wspd_ms, wdir_deg, wtmp_c FROM buoy_obs"
                                " WHERE station=? AND source=? AND ts >= ? ORDER BY ts",
                                (sid, meta["source"], since)).fetchall()
            temps = {}
            if meta.get("alsoNdbc"):
                temps = {r[0][:13]: r[1] for r in conn.execute(
                    "SELECT ts, wtmp_c FROM buoy_obs WHERE station=? AND source='ndbc' AND ts >= ?"
                    " AND wtmp_c IS NOT NULL", (meta["alsoNdbc"], since))}
        except sqlite3.OperationalError:
            rows, temps = [], {}
        hist, seen = [], set()
        for ts, hs, tp, dp, ws, wd, wt in rows:
            hour = ts[:13]
            if hour in seen:          # CDIP reports every 30 min: keep one per hour
                continue
            seen.add(hour)
            if wt is None:
                wt = temps.get(hour)
            hist.append({"t": ts, "waveFt": _r(hs * 3.281 if hs is not None else None),
                         "periodS": _r(tp), "dirDeg": None if dp is None else round(dp),
                         "windKt": _r(ws * 1.944 if ws is not None else None),
                         "windDirDeg": None if wd is None else round(wd),
                         "waterF": _r(wt * 9 / 5 + 32 if wt is not None else None)})
        out["buoys"].append({"id": sid, "source": meta["source"], "name": meta["name"],
                             "lat": meta["lat"], "lon": meta["lon"],
                             "latest": hist[-1] if hist else None, "history": hist})
    return out


def write_buoys_json(conn: sqlite3.Connection, path: Path = BUOYS_JSON) -> int:
    payload = buoys_payload(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return sum(1 for b in payload["buoys"] if b["latest"])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[1] / "tracker.db")
    ap.add_argument("--show", choices=sorted(REGIONS))
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.db)
    if a.show:
        print(json.dumps(region_payload(conn, a.show), indent=1))
        return 0
    print(json.dumps(refresh(conn, force=True), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
