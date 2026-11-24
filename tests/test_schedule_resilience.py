"""A blocked or failed schedule source must not wipe that landing's schedule."""
import sqlite3

import pytest

from src import db, schedule
from src.schedule import ScheduleBlockedError, ScheduleSource

SRC = ScheduleSource(name="Seaforth Sportfishing",
                     url="https://seaforth.fishingreservations.net/sales",
                     kind="fishingreservations")

CHALLENGE = "<html><body><h1>Please verify you are human</h1></body></html>"
SCHEDULE_P1 = '<html><body>Page 1 of 2 <a href="/user.php?trip_id=1">x</a></body></html>'


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(schedule.time, "sleep", lambda s: None)


def test_challenge_page_raises_instead_of_returning_zero(monkeypatch):
    monkeypatch.setattr(schedule, "_fetch", lambda src, params=None, timeout=30.0: CHALLENGE)
    with pytest.raises(ScheduleBlockedError):
        schedule._fetch_fishingreservations_all_pages(SRC)


def test_challenge_then_recovers_on_retry(monkeypatch):
    calls = iter([CHALLENGE, SCHEDULE_P1, SCHEDULE_P1])
    monkeypatch.setattr(schedule, "_fetch", lambda src, params=None, timeout=30.0: next(calls))
    pages = schedule._fetch_fishingreservations_all_pages(SRC)
    assert len(pages) == 2


def test_block_on_a_later_page_fails_the_whole_landing(monkeypatch):
    calls = iter([SCHEDULE_P1, CHALLENGE])
    monkeypatch.setattr(schedule, "_fetch", lambda src, params=None, timeout=30.0: next(calls))
    with pytest.raises(ScheduleBlockedError):
        schedule._fetch_fishingreservations_all_pages(SRC)


def test_empty_but_real_schedule_page_is_not_blocked():
    assert schedule._looks_like_schedule("<p>Page 1 of 1</p><p>No trips</p>")


def _trip(landing, sid):
    return {k: None for k in db.SCHEDULED_FIELDS} | {"landing": landing, "boat": "B", "source_id": sid}


def test_replace_only_touches_named_landings():
    conn = sqlite3.connect(":memory:")
    cols = ",".join(f"{c}" for c in db.SCHEDULED_FIELDS)
    conn.execute(f"CREATE TABLE scheduled_trips ({cols})")
    db.replace_scheduled_trips(conn, [_trip("Seaforth Sportfishing", "s1"), _trip("H&M Landing", "h1")])
    # Seaforth failed this run: only H&M is refreshed.
    db.replace_scheduled_trips(conn, [_trip("H&M Landing", "h2")], landings=["H&M Landing"])
    rows = sorted(r[0] for r in conn.execute("SELECT source_id FROM scheduled_trips"))
    assert rows == ["h2", "s1"]
