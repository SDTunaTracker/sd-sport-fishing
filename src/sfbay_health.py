"""Data-health rules for the SF Bay Area feed (norcalfishreports.com).

Kept out of src/completeness.py so the OC/LA branch and this one don't edit
the same file. main.py appends these problems to completeness.check().

Tuned for no-trip days: the source says so explicitly (a no-count day serves
"Dock Totals - <last day with counts>"), and scrape_norcal stores that as
no_counts=1. Bad weather, a closed season, or winter can mean a week or more
of no-count days, and that is not an outage.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from .completeness import Problem

FETCH_MAX_AGE = timedelta(hours=30)
QUIET_DAYS_IN_SEASON = 7          # Apr–Oct: a week of no counts is worth a look
IN_SEASON_MONTHS = range(4, 11)


def check(conn: sqlite3.Connection, today: date | None = None,
          now: datetime | None = None) -> list[Problem]:
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    try:
        rows = conn.execute(
            "SELECT date, fetched_at, status, rows, no_counts, error FROM norcal_fetch_log"
            " ORDER BY date").fetchall()
    except sqlite3.OperationalError:
        return []          # feed not set up on this DB yet
    if not rows:
        return []
    probs: list[Problem] = []

    blocked = [r for r in rows if (r[5] or "") == "blocked"]
    if blocked:
        probs.append(Problem("sfbay:blocked", "norcal_trips", "blocked",
                             f"norcalfishreports.com refused or posted a notice on {blocked[-1][1]}. "
                             "SF Bay scraping is stopped; the owner must review before clearing it "
                             "(DELETE FROM norcal_fetch_log WHERE error='blocked')."))

    ok = [r for r in rows if r[2] == 200]
    last_ok = max((datetime.fromisoformat(r[1]) for r in ok), default=None)
    if last_ok is None or now - last_ok > FETCH_MAX_AGE:
        probs.append(Problem("sfbay:fetch", "norcal_trips", "warning",
                             f"SF Bay: no successful fetch since {last_ok or 'ever'}"))

    since = (today - timedelta(days=3)).isoformat()
    empty = [r[0] for r in ok if r[0] >= since and not r[3] and not r[4]]
    if empty:
        probs.append(Problem("sfbay:parse", "norcal_trips", "warning",
                             f"SF Bay page parsed to 0 rows without a no-counts marker on "
                             f"{', '.join(empty)} (page layout change?)"))

    if today.month in IN_SEASON_MONTHS:
        recent = [r for r in ok if r[0] >= (today - timedelta(days=QUIET_DAYS_IN_SEASON)).isoformat()
                  and r[0] < today.isoformat()]
        try:
            n_trips = conn.execute(
                "SELECT COUNT(*) FROM norcal_trips WHERE region='sf_bay' AND date >= ?",
                ((today - timedelta(days=QUIET_DAYS_IN_SEASON)).isoformat(),)).fetchone()[0]
        except sqlite3.OperationalError:
            n_trips = 0
        if len(recent) >= QUIET_DAYS_IN_SEASON - 1 and n_trips == 0:
            probs.append(Problem("sfbay:quiet", "norcal_trips", "warning",
                                 f"SF Bay: no trips posted in {QUIET_DAYS_IN_SEASON} days in season "
                                 "(weather closure, or the source changed?)"))
    return probs
