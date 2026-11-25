"""Daily completeness check across every feed in tracker.db.

Run directly for a report:

    .venv\\Scripts\\python.exe -m src.completeness          # exit 1 if any problem

check() returns a list of Problem records. main.py calls it at the end of
every run, writes logs/completeness.json, and hands the problems to
src.alerts so a broken feed reaches the owner instead of a log file.
tests/test_feed_freshness.py fails on the same rules.

Thresholds are "max age of the newest row" in days, set from each source's
real publishing lag (MUR SST 3-6 days, NOAA upwelling index ~30 days).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
APP_JSON = ROOT / "web" / "api" / "v1" / "app.json"   # mobile-app export (src/export.py)
APP_JSON_MAX_AGE = timedelta(hours=26)

CORE_LANDINGS = (
    "H&M Landing",
    "Fisherman's Landing",
    "Seaforth Sportfishing",
    "Point Loma Sportfishing",
)

SST_LOCATIONS = {"Nearshore": 2, "9-Mile Bank": 7, "60-Mile Bank": 7, "Cortez Bank": 7}

# table -> (date column, max age in days)
FEEDS: dict[str, tuple[str, int]] = {
    "historical_conditions": ("date", 3),
    "upwelling_obs": ("date", 40),
    "daily_segment_stats": ("date", 3),
    "forecast_scores": ("date", 1),
    "forecast_accuracy_log": ("date", 5),
}

OCLA_CONDITIONS_MAX_AGE = 7

# Feeds whose upstream source is gone. Reported once in the docs, never alerted.
ABANDONED = {
    "ocean_currents": "PFEG ERDDAP HYCOM datasets end 2018-11; used only by the 2014-2018 backtest",
    "reddit_reports": "retired by owner 2026-11-24 (reddit.com JSON returns HTTP 403 since 2026-05-27)",
}


# A site that answers with a CAPTCHA / bot check is left alone this long.
BLOCK_COOLDOWN = timedelta(hours=12)
_BLOCK_MARKERS = ("ScheduleBlockedError", "captcha", "bot challenge", "error code 338",
                  "code 338", "HTTP 403", "403 Client Error")

_BLOCKS_DDL = """CREATE TABLE IF NOT EXISTS source_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,          -- landing name
    host TEXT,                     -- machine that got blocked (laptop vs CI IPs differ)
    blocked_at TEXT NOT NULL,      -- UTC ISO
    detail TEXT
)"""


def is_block_error(err: str | None) -> bool:
    low = (err or "").lower()
    return any(m.lower() in low for m in _BLOCK_MARKERS)


def record_block(conn: sqlite3.Connection, source: str, detail: str) -> None:
    import socket
    conn.execute(_BLOCKS_DDL)
    conn.execute("INSERT INTO source_blocks (source, host, blocked_at, detail) VALUES (?,?,?,?)",
                 (source, socket.gethostname(),
                  datetime.now(timezone.utc).isoformat(timespec="seconds"), detail[:500]))


def active_block(conn: sqlite3.Connection, source: str,
                 now: datetime | None = None) -> str | None:
    """blocked_at of this machine's latest block of `source` if still cooling down."""
    import socket
    now = now or datetime.now(timezone.utc)
    try:
        row = conn.execute(
            "SELECT MAX(blocked_at) FROM source_blocks WHERE source=? AND host=?",
            (source, socket.gethostname())).fetchone()
    except sqlite3.OperationalError:
        return None
    if row and row[0] and now - datetime.fromisoformat(row[0]) < BLOCK_COOLDOWN:
        return row[0]
    return None


@dataclass
class Problem:
    key: str            # stable id used for alert de-duplication
    feed: str
    severity: str       # "critical" (core data broken) | "blocked" (CAPTCHA) | "warning"
    detail: str


def _max_date(conn, table: str, col: str, where: str = "", args: tuple = ()) -> date | None:
    row = conn.execute(f"SELECT MAX({col}) FROM {table} {where}", args).fetchone()
    return date.fromisoformat(row[0][:10]) if row and row[0] else None


def _age(d: date | None, today: date) -> int | None:
    return None if d is None else (today - d).days


def check(conn: sqlite3.Connection, today: date | None = None,
          run_status: dict | None = None, now: datetime | None = None,
          app_json: Path | None = None) -> list[Problem]:
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    probs: list[Problem] = []

    # 1. Core landing scrapes — last successful scrape per landing.
    for ln in CORE_LANDINGS:
        row = conn.execute(
            "SELECT MAX(started_at) FROM scrape_log WHERE landing=? AND status='ok'", (ln,)
        ).fetchone()
        last = datetime.fromisoformat(row[0]) if row and row[0] else None
        if last is None or now - last > timedelta(hours=26):
            probs.append(Problem(f"scrape:{ln}", "trips", "critical",
                                 f"{ln}: no successful scrape since {last or 'ever'}"))

    # 2. Trip coverage — any day in the last 14 with zero San Diego trips.
    sd = ",".join("?" * len(CORE_LANDINGS))
    days_with = {r[0] for r in conn.execute(
        f"SELECT DISTINCT date FROM trips WHERE landing IN ({sd}) AND date >= ?",
        (*CORE_LANDINGS, (today - timedelta(days=14)).isoformat()),
    )}
    missing = [(today - timedelta(days=i)).isoformat() for i in range(2, 15)
               if (today - timedelta(days=i)).isoformat() not in days_with]
    if missing:
        probs.append(Problem("trips:gap", "trips", "warning",
                             f"no San Diego trips stored for {', '.join(sorted(missing))}"))

    # 3. SST per location.
    for loc, max_age in SST_LOCATIONS.items():
        a = _age(_max_date(conn, "ocean_temps", "date", "WHERE location=?", (loc,)), today)
        if a is None or a > max_age:
            probs.append(Problem(f"sst:{loc}", "ocean_temps", "warning",
                                 f"{loc} SST newest row is {a} days old (limit {max_age})"))
    gaps = conn.execute(
        """WITH RECURSIVE d(x) AS (SELECT date(?, '-30 day') UNION ALL
                                   SELECT date(x, '+1 day') FROM d WHERE x < date(?, '-7 day'))
           SELECT COUNT(*) FROM d WHERE (SELECT COUNT(*) FROM ocean_temps o WHERE o.date = d.x) < 4""",
        (today.isoformat(), today.isoformat()),
    ).fetchone()[0]
    if gaps:
        probs.append(Problem("sst:gaps", "ocean_temps", "warning",
                             f"{gaps} day(s) in the last 30 have SST for fewer than 4 locations"))

    # 4. Conditions and derived tables.
    for table, (col, max_age) in FEEDS.items():
        a = _age(_max_date(conn, table, col), today)
        if a is None or a > max_age:
            probs.append(Problem(f"feed:{table}", table, "warning",
                                 f"{table} newest row is {a} days old (limit {max_age})"))

    # 5. Schedules — every schedule source refreshed in the last 48h.
    from .schedule import SOURCES as SCHED_SOURCES
    for ln in [s.name for s in SCHED_SOURCES]:
        last = last_schedule_refresh(conn, ln)
        if last is None or now - last > timedelta(hours=48):
            probs.append(Problem(f"schedule:{ln}", "scheduled_trips", "warning",
                                 f"{ln} schedule last refreshed {last or 'never'}"))

    # 5a. OC/LA conditions (src.ocla_conditions). OC/LA scrape health and
    # region-silence rules live with the OC/LA launch (REGIONAL_LANDINGS).
    try:
        for loc, d in conn.execute(
                "SELECT location, MAX(date) FROM ocla_conditions WHERE sst_celsius IS NOT NULL"
                " GROUP BY location"):
            a = _age(date.fromisoformat(d), today)
            if a > OCLA_CONDITIONS_MAX_AGE:
                probs.append(Problem(f"ocla_conditions:{loc}", "ocla_conditions", "warning",
                                     f"OC/LA SST for {loc} newest row is {a} days old"
                                     f" (limit {OCLA_CONDITIONS_MAX_AGE})"))
    except sqlite3.OperationalError:
        pass

    # 5b. Sites blocking us with a CAPTCHA — its own alert type, not a code bug.
    try:
        for src, host, at, detail in conn.execute(
            "SELECT source, host, MAX(blocked_at), detail FROM source_blocks"
            " WHERE blocked_at >= ? GROUP BY source, host",
            ((now - timedelta(hours=24)).isoformat(),),
        ):
            probs.append(Problem(f"blocked:{src}", "scheduled_trips", "blocked",
                                 f"{src} is serving a CAPTCHA / bot check to {host} (last {at}); "
                                 f"not a code bug; scraping paused {BLOCK_COOLDOWN.seconds // 3600}h"))
    except sqlite3.OperationalError:
        pass

    # 6. Scheduled jobs actually ran (heartbeat written by main.py).
    if run_status is not None:
        for mode, max_h in (("full", 30), ("hourly", 3)):
            st = run_status.get(mode) or {}
            fin = st.get("finished_at")
            last = datetime.fromisoformat(fin) if fin else None
            if last is None or now - last > timedelta(hours=max_h):
                probs.append(Problem(f"job:{mode}", "scheduler", "critical",
                                     f"{mode} run has not completed since {last or 'never'}"))
            elif st.get("exit_code"):
                probs.append(Problem(f"job:{mode}:exit", "scheduler", "critical",
                                     f"last {mode} run exited {st['exit_code']}: {st.get('reason', '')}"))

    # 7. Mobile-app export written recently (only when a path is given).
    if app_json is not None:
        gen = None
        try:
            gen = json.loads(app_json.read_text(encoding="utf-8")).get("generatedAt")
            last = datetime.fromisoformat(gen.replace("Z", "+00:00")) if gen else None
        except (OSError, ValueError, AttributeError):
            last = None
        if last is None or now - last > APP_JSON_MAX_AGE:
            probs.append(Problem("export:app.json", "app.json", "warning",
                                 f"api/v1/app.json last generated {gen or 'never'}"))
    return probs


_SCHED_REFRESH_DDL = """CREATE TABLE IF NOT EXISTS schedule_refresh (
    landing TEXT PRIMARY KEY,
    refreshed_at TEXT NOT NULL     -- UTC ISO of the last successful schedule scrape
)"""


def mark_schedule_refresh(conn: sqlite3.Connection, landing: str) -> None:
    """Record a successful schedule scrape, even one that found no trips."""
    conn.execute(_SCHED_REFRESH_DDL)
    conn.execute("INSERT OR REPLACE INTO schedule_refresh (landing, refreshed_at) VALUES (?,?)",
                 (landing, datetime.now(timezone.utc).isoformat(timespec="seconds")))


def last_schedule_refresh(conn: sqlite3.Connection, landing: str) -> datetime | None:
    """Latest of schedule_refresh and the landing's newest scheduled_trips row."""
    vals = []
    try:
        vals.append(conn.execute("SELECT refreshed_at FROM schedule_refresh WHERE landing=?",
                                 (landing,)).fetchone())
    except sqlite3.OperationalError:
        pass
    vals.append(conn.execute("SELECT MAX(scraped_at) FROM scheduled_trips WHERE landing=?",
                             (landing,)).fetchone())
    ts = [datetime.fromisoformat(v[0]) for v in vals if v and v[0]]
    return max(ts) if ts else None


_JOB_RUNS_DDL = """CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,            -- 'full' | 'hourly'
    host TEXT,                     -- machine that ran it (laptop vs CI)
    finished_at TEXT NOT NULL,     -- UTC ISO
    exit_code INTEGER NOT NULL,
    reason TEXT
)"""


def load_run_status(conn: sqlite3.Connection) -> dict:
    """Latest job_runs row per mode, any host: {mode: {...}}.

    Stored in tracker.db (not logs/) so CI runs, which start from a fresh
    checkout, still see when the last full/hourly run happened.
    """
    try:
        rows = conn.execute(
            "SELECT mode, host, finished_at, exit_code, reason FROM job_runs j"
            " WHERE id = (SELECT MAX(id) FROM job_runs WHERE mode = j.mode)"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: {"host": r[1], "finished_at": r[2], "exit_code": r[3], "reason": r[4]}
            for r in rows}


def write_run_status(conn: sqlite3.Connection, mode: str, exit_code: int,
                     reason: str = "") -> None:
    import socket
    conn.execute(_JOB_RUNS_DDL)
    conn.execute(
        "INSERT INTO job_runs (mode, host, finished_at, exit_code, reason) VALUES (?,?,?,?,?)",
        (mode, socket.gethostname(), datetime.now(timezone.utc).isoformat(timespec="seconds"),
         exit_code, reason),
    )


def write_report(probs: list[Problem], path: Path = ROOT / "logs" / "completeness.json") -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": not probs, "problems": [asdict(p) for p in probs],
        "abandoned": ABANDONED,
    }, indent=2), encoding="utf-8")


def main() -> int:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    probs = check(conn, run_status=load_run_status(conn))
    for p in probs:
        print(f"[{p.severity:8s}] {p.feed:22s} {p.detail}")
    print("OK: every feed is current." if not probs else f"{len(probs)} problem(s).")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
