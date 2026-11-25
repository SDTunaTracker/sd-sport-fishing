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
                  "ndbc": ["46232", "46086"], "cdip": ["191", "045"]},
    "oc_la":     {"zones": ["PZZ655", "PZZ676"], "tide": "9410660",
                  "ndbc": ["46221", "46222", "46025"], "cdip": ["092", "028"]},
    "sf_bay":    {"zones": ["PZZ530", "PZZ531", "PZZ545", "PZZ571"], "tide": "9414290",
                  "ndbc": ["46026", "46237"], "cdip": ["142"]},
}

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
_SEAS_SENT_RE = re.compile(r"\bSeas\b[^.]*", re.I)   # "Seas 3 to 5 ft, building to 5 to 7 ft"
_FT_RE = re.compile(r"(\d+)(?:\s+to\s+(\d+))?\s*(?:ft|feet|foot)\b", re.I)


def parse_marine_text(text: str) -> tuple[float | None, float | None, float | None, float | None]:
    """(wind_min, wind_max, seas_min, seas_max) from an NWS period's text."""
    winds = [(int(a), int(b or a)) for a, b in _WIND_RE2.findall(text) + _WIND_RE.findall(text)]
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
    """NDBC realtime2 .txt -> hourly buoy_obs rows (first report each hour)."""
    rows, seen = [], set()
    cutoff = _now() - timedelta(hours=hours)
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        c = line.split()
        if len(c) < 15:
            continue
        ts = datetime(int(c[0]), int(c[1]), int(c[2]), int(c[3]), int(c[4]), tzinfo=timezone.utc)
        hour = ts.replace(minute=0)
        if ts < cutoff or hour in seen:
            continue
        seen.add(hour)
        rows.append((station, "ndbc", _iso(ts), _f(c[8]), _f(c[9]), _f(c[11]), _f(c[6]), _f(c[5]), _f(c[14])))
    return rows


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


def fetch_cdip(conn: sqlite3.Connection, station: str, records: int = 48) -> int:
    dds = _get(_CDIP.format(s=station) + ".dds").text
    m = re.search(r"Int32 waveTime\[waveTime = (\d+)\]", dds)
    if not m:
        return 0
    n = int(m.group(1))
    a, b = max(0, n - records), n - 1
    sl = f"[{a}:1:{b}]"
    q = ",".join(f"{v}{sl}" for v in ("waveTime", "waveHs", "waveTp", "waveDp"))
    data = parse_cdip_ascii(_get(_CDIP.format(s=station) + ".ascii?" + q).text)
    rows = [(station, "cdip", _iso(datetime.fromtimestamp(t, timezone.utc)), hs, tp, dp, None, None, None)
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


def refresh(conn: sqlite3.Connection, force: bool = False) -> dict[str, str]:
    """Fetch whatever is due. Never raises; returns {kind: summary or error}."""
    conn.executescript(DDL)
    now = _now()
    zones = [z for r in REGIONS.values() for z in r["zones"]]
    jobs = {
        "alerts": lambda: f"{fetch_alerts(conn, zones)} active",
        "forecasts": lambda: f"+{fetch_forecasts(conn, zones)} periods",
        "tides": lambda: f"{sum(fetch_tides(conn, r['tide']) for r in REGIONS.values())} hi/lo",
        "buoys": lambda: "+{} obs".format(
            sum(fetch_ndbc(conn, s) for r in REGIONS.values() for s in r["ndbc"])
            + sum(fetch_cdip(conn, s) for r in REGIONS.values() for s in r["cdip"])),
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
                           " WHERE zone=? AND updated_at=? ORDER BY period LIMIT 6", (z, upd))]
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
