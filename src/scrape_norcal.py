"""SF Bay Area (NorCal) daily fish counts from norcalfishreports.com.

One page per day lists every NorCal boat that posted:
    https://www.norcalfishreports.com/dock_totals/boats.php?date=YYYY-MM-DD
Each row: boat (+ /charter_boats/<slug>.php), landing (+ /landings/<slug>.php),
city, "N Anglers<br>Trip Type", and a dock-totals string.

Footprint rules (the owner accepted this network's terms-of-use risk on
2026-11-25, on the condition that we stay polite):
  * one request per page, at most one every MIN_DELAY_S seconds
  * every response is cached on disk; a cached day is never fetched again
    unless it is recent (counts can still change for a couple of days)
  * an honest User-Agent, no proxies, no header games, no retries on 4xx
  * any sign of a block (403/401/429/451, a challenge page, a notice) raises
    SourceBlocked. Callers must stop and tell the owner, not work around it.

Rows go into their own table, `norcal_trips`, so no San Diego / OC-LA query
can pick them up by accident. Inserts are idempotent: older days are
INSERT OR IGNORE; the last RECENT_DAYS days update counts in place.
"""
from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import norcal as N
from .dates import pacific_today

log = logging.getLogger(__name__)

BASE = "https://www.norcalfishreports.com"
DAY_URL = BASE + "/dock_totals/boats.php?date={d}"
UA = "TunatrackerBot/1.0 (+https://thetunatracker.com; fish-count analytics)"

MIN_DELAY_S = 3.0
MAX_DELAY_S = 5.0
RECENT_DAYS = 3
CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "norcal"

SCHEMA = """
CREATE TABLE IF NOT EXISTS norcal_trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    boat TEXT NOT NULL,
    boat_slug TEXT NOT NULL,
    landing TEXT NOT NULL,
    landing_slug TEXT,
    city TEXT,
    port TEXT,
    region TEXT NOT NULL,
    trip_type_raw TEXT NOT NULL,
    trip_length TEXT,
    trip_length_days REAL,
    anglers INTEGER NOT NULL,
    landed_json TEXT NOT NULL,
    released_json TEXT,
    counts_raw TEXT,
    source_url TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    UNIQUE(date, boat_slug, landing, trip_type_raw, anglers)
);
CREATE INDEX IF NOT EXISTS idx_norcal_trips_date ON norcal_trips(date);
CREATE INDEX IF NOT EXISTS idx_norcal_trips_region ON norcal_trips(region, date);

CREATE TABLE IF NOT EXISTS norcal_fetch_log (
    date TEXT PRIMARY KEY,           -- the report date requested
    fetched_at TEXT NOT NULL,
    status INTEGER,
    rows INTEGER,
    no_counts INTEGER DEFAULT 0,     -- 1 = page said no counts that day
    error TEXT
);
"""


class SourceBlocked(RuntimeError):
    """The source refused us or posted a notice. Stop and tell the owner."""


_BLOCK_MARKERS = re.compile(
    r"access denied|attention required|cf-challenge|captcha|you have been blocked|"
    r"unusual traffic|rate limit|cease and desist|terms of (?:use|service) violation",
    re.I,
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


# --- Fetching -------------------------------------------------------------------

@dataclass
class Fetcher:
    """Polite, cached fetcher. One instance per run so the delay is shared."""
    cache_dir: Path = CACHE_DIR
    min_delay: float = MIN_DELAY_S
    max_delay: float = MAX_DELAY_S
    offline: bool = False            # cache only, never hit the network
    sleep = staticmethod(time.sleep)
    _last: float = 0.0
    requests_made: int = 0

    def __post_init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept": "text/html"})

    def _cache_path(self, d: date) -> Path:
        return self.cache_dir / f"boats_{d.isoformat()}.html"

    def get_day(self, d: date, today: date | None = None) -> tuple[str | None, bool]:
        """Return (html, from_cache). Recent days are refetched; older days are
        served from cache when present."""
        today = today or pacific_today()
        path = self._cache_path(d)
        recent = (today - d).days < RECENT_DAYS
        if path.exists() and (not recent or self.offline):
            return path.read_text(encoding="utf-8"), True
        if self.offline:
            return None, True
        wait = self._last + random.uniform(self.min_delay, self.max_delay) - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        url = DAY_URL.format(d=d.isoformat())
        try:
            r = self.session.get(url, timeout=30, allow_redirects=True)
        finally:
            self._last = time.monotonic()
            self.requests_made += 1
        if r.status_code in (401, 403, 429, 451):
            raise SourceBlocked(f"HTTP {r.status_code} from {url}")
        r.raise_for_status()
        html = r.text
        if _BLOCK_MARKERS.search(html[:20000]) and "Fish Counts by Boat" not in html:
            raise SourceBlocked(f"block/notice page at {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return html, False


# --- Parsing --------------------------------------------------------------------

_H1_DATE = re.compile(r"Fish Counts by Boat\s*-\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
_ANGLERS = re.compile(r"(\d+)\s*Anglers?", re.I)
_SLUG = re.compile(r"/(?:charter_boats|landings)/([^/]+?)\.php")
_PAREN_SUFFIX = re.compile(r"\s*\([^)]*,\s*[A-Z]{2}\)\s*$")   # "Outer Limits (Sausalito, CA)"
_NO_COUNTS = re.compile(r"No Counts Provided", re.I)
_FALLBACK_H1 = re.compile(r"<h1>\s*Dock Totals\s*-\s*[A-Z][a-z]+ \d{1,2}, \d{4}\s*</h1>")


def page_date(html: str) -> date | None:
    m = _H1_DATE.search(html)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%B %d, %Y").date()


def parse_day(html: str, expected: date, source_url: str | None = None) -> tuple[list[dict], bool]:
    """Parse one boats.php page. Returns (trips, no_counts_flag).

    Rows whose page date doesn't match `expected` are rejected (the site shows
    the latest day for out-of-range dates)."""
    pd = page_date(html)
    if pd != expected:
        # On a day with no posted counts the site serves "Dock Totals - <last
        # day that had counts>" instead. That's a no-trip day, not an outage.
        fallback = _FALLBACK_H1.search(html)
        if pd is None and fallback:
            return [], True
        log.warning("norcal: page date %s != requested %s, skipping", pd, expected)
        return [], False
    source_url = source_url or DAY_URL.format(d=expected.isoformat())
    soup = BeautifulSoup(html, "lxml")
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out: list[dict] = []
    for table in soup.find_all("table"):
        heads = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "boat" not in heads or not any("dock totals" in h for h in heads):
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue
            boat_a = tds[0].find("a", href=re.compile(r"/charter_boats/"))
            land_a = tds[0].find("a", href=re.compile(r"/landings/"))
            if not boat_a:
                continue
            boat = _PAREN_SUFFIX.sub("", boat_a.get_text(" ", strip=True)).strip()
            bslug = _SLUG.search(boat_a["href"])
            landing = land_a.get_text(" ", strip=True) if land_a else boat
            lslug = _SLUG.search(land_a["href"]) if land_a else None
            # City is the trailing text node after the landing link.
            parts = [s.strip() for s in tds[0].stripped_strings]
            city = parts[-1] if parts and "," in parts[-1] else None
            port, region = N.port_for_city(city)

            detail = [s.strip() for s in tds[1].stripped_strings]
            am = _ANGLERS.search(" ".join(detail))
            if not am:
                continue
            anglers = int(am.group(1))
            trip_raw = " ".join(s for s in detail if not _ANGLERS.fullmatch(s)).strip() or "Unknown"
            tl, tld = N.trip_length(trip_raw)

            counts = tds[2].get_text(" ", strip=True)
            landed, released, unknowns = N.parse_counts(counts)
            out.append({
                "date": expected.isoformat(),
                "boat": boat,
                "boat_slug": bslug.group(1) if bslug else boat.lower().replace(" ", ""),
                "landing": landing,
                "landing_slug": lslug.group(1) if lslug else None,
                "city": city,
                "port": port,
                "region": region,
                "trip_type_raw": trip_raw,
                "trip_length": tl,
                "trip_length_days": tld,
                "anglers": anglers,
                "landed_json": json.dumps(landed, separators=(",", ":"), sort_keys=True),
                "released_json": json.dumps(released, separators=(",", ":"), sort_keys=True) if released else None,
                "counts_raw": counts,
                "source_url": source_url,
                "scraped_at": scraped_at,
                "_unknowns": unknowns,
            })
    no_counts = not out and bool(_NO_COUNTS.search(html))
    return out, no_counts


# --- Storage --------------------------------------------------------------------

_FIELDS = ("date", "boat", "boat_slug", "landing", "landing_slug", "city", "port", "region",
           "trip_type_raw", "trip_length", "trip_length_days", "anglers",
           "landed_json", "released_json", "counts_raw", "source_url", "scraped_at")


def insert_trips(conn: sqlite3.Connection, trips: list[dict], today: date | None = None) -> int:
    """Idempotent insert. Days older than RECENT_DAYS are insert-only; recent
    days update counts on conflict (boats revise totals the next morning)."""
    ensure_schema(conn)
    today = today or pacific_today()
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    cols = ",".join(_FIELDS)
    ph = ",".join("?" * len(_FIELDS))
    sql_ignore = f"INSERT OR IGNORE INTO norcal_trips ({cols}) VALUES ({ph})"
    sql_upsert = (f"INSERT INTO norcal_trips ({cols}) VALUES ({ph}) "
                  "ON CONFLICT(date, boat_slug, landing, trip_type_raw, anglers) DO UPDATE SET "
                  "landed_json=excluded.landed_json, released_json=excluded.released_json, "
                  "counts_raw=excluded.counts_raw, scraped_at=excluded.scraped_at")
    n = 0
    unknown_rows = []
    for t in trips:
        vals = tuple(t[f] for f in _FIELDS)
        cur = conn.execute(sql_upsert if t["date"] >= cutoff else sql_ignore, vals)
        n += cur.rowcount if cur.rowcount > 0 else 0
        for name, cnt in t.get("_unknowns", ()):
            unknown_rows.append((name, cnt, t["date"], t["boat"], t["landing"]))
    if unknown_rows:
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO unknown_species (species_name, count, date, boat, landing)"
                " VALUES (?,?,?,?,?)", unknown_rows)
        except sqlite3.OperationalError:
            pass  # bare test DBs without the shared table
    return n


def log_fetch(conn: sqlite3.Connection, d: date, status: int | None, rows: int,
              no_counts: bool, error: str | None = None) -> None:
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO norcal_fetch_log (date, fetched_at, status, rows, no_counts, error) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET fetched_at=excluded.fetched_at, "
        "status=excluded.status, rows=excluded.rows, no_counts=excluded.no_counts, error=excluded.error",
        (d.isoformat(), datetime.now(timezone.utc).isoformat(timespec="seconds"),
         status, rows, int(no_counts), error))


def scrape_days(conn: sqlite3.Connection, days: list[date], fetcher: Fetcher | None = None,
                today: date | None = None) -> dict:
    """Fetch, parse and store each day. Raises SourceBlocked immediately."""
    fetcher = fetcher or Fetcher()
    stats = {"days": 0, "inserted": 0, "rows": 0, "no_count_days": 0, "cached": 0, "errors": 0}
    for d in days:
        try:
            html, cached = fetcher.get_day(d, today=today)
        except SourceBlocked:
            log_fetch(conn, d, None, 0, False, "blocked")
            conn.commit()
            raise
        except requests.RequestException as e:
            log.warning("norcal %s: %s", d, e)
            log_fetch(conn, d, getattr(getattr(e, "response", None), "status_code", None), 0, False, str(e)[:200])
            stats["errors"] += 1
            continue
        if html is None:
            continue
        trips, no_counts = parse_day(html, d)
        stats["days"] += 1
        stats["cached"] += int(cached)
        stats["rows"] += len(trips)
        stats["no_count_days"] += int(no_counts)
        stats["inserted"] += insert_trips(conn, trips, today=today)
        log_fetch(conn, d, 200, len(trips), no_counts)
        conn.commit()
    return stats


# --- Backfill seed ------------------------------------------------------------
# The 2019+ backfill runs once, off to the side (scripts/backfill_sfbay.py), and
# is shipped as a gzipped JSON-lines file. The daily job loads it insert-only on
# its next run, so tracker.db (committed hourly by CI) is never hand-merged.

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "sfbay_backfill.jsonl.gz"


def export_seed(conn: sqlite3.Connection, path: Path) -> tuple[int, int]:
    import gzip
    path.parent.mkdir(parents=True, exist_ok=True)
    n_t = n_f = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in conn.execute(f"SELECT {','.join(_FIELDS)} FROM norcal_trips ORDER BY date, id"):
            f.write(json.dumps({"t": dict(zip(_FIELDS, row))}, separators=(",", ":")) + "\n")
            n_t += 1
        for row in conn.execute("SELECT date, fetched_at, status, rows, no_counts, error FROM norcal_fetch_log"
                                " WHERE status = 200 ORDER BY date"):
            f.write(json.dumps({"f": row}, separators=(",", ":")) + "\n")
            n_f += 1
    return n_t, n_f


def load_seed(conn: sqlite3.Connection, path: Path = SEED_PATH) -> int | None:
    """Insert-only load of the backfill seed, once per seed file content.
    Returns rows inserted, or None if there is no seed / it was already loaded."""
    import gzip
    import hashlib
    if not path.exists():
        return None
    ensure_schema(conn)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    marker = f"seed:{digest}"
    if conn.execute("SELECT 1 FROM norcal_fetch_log WHERE date = ?", (marker,)).fetchone():
        return None
    cols = ",".join(_FIELDS)
    sql_t = f"INSERT OR IGNORE INTO norcal_trips ({cols}) VALUES ({','.join('?' * len(_FIELDS))})"
    sql_f = ("INSERT OR IGNORE INTO norcal_fetch_log (date, fetched_at, status, rows, no_counts, error)"
             " VALUES (?,?,?,?,?,?)")
    n = 0
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if "t" in rec:
                n += conn.execute(sql_t, tuple(rec["t"][k] for k in _FIELDS)).rowcount
            else:
                conn.execute(sql_f, tuple(rec["f"]))
    # Marker row: status NULL / error 'seed', so the health rules ignore it.
    conn.execute("INSERT INTO norcal_fetch_log (date, fetched_at, status, rows, no_counts, error)"
                 " VALUES (?,?,NULL,?,0,'seed')",
                 (marker, datetime.now(timezone.utc).isoformat(timespec="seconds"), n))
    conn.commit()
    return n


def run_daily(conn: sqlite3.Connection, min_hours_between: float = 6.0) -> dict | None:
    """Daily/hourly hook: refresh today and yesterday at most every
    `min_hours_between` hours (about 8 requests a day)."""
    ensure_schema(conn)
    # A recorded block stops the feed until the owner reviews and clears it.
    if conn.execute("SELECT 1 FROM norcal_fetch_log WHERE error = 'blocked' LIMIT 1").fetchone():
        log.error("norcal: source previously blocked us; not fetching (owner must clear)")
        return None
    today = pacific_today()
    row = conn.execute("SELECT MAX(fetched_at) FROM norcal_fetch_log WHERE status = 200").fetchone()
    if row and row[0]:
        last = datetime.fromisoformat(row[0])
        if datetime.now(timezone.utc) - last < timedelta(hours=min_hours_between):
            return None
    return scrape_days(conn, [today - timedelta(days=1), today], today=today)
