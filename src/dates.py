"""Pacific-time date helpers.

CI runs the scraper on UTC hosts (GitHub Actions ubuntu-latest). Calling
date.today() after ~5pm Pacific returns *tomorrow's* date because UTC has
already rolled over — which then becomes the report date stamped on
freshly-scraped boats, and the date the "Today" filter compares against.

All date-of-business logic should route through pacific_today() so the
fishing day matches what landings post and what San Diego anglers see.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_today() -> date:
    """Calendar date in America/Los_Angeles (PDT/PST auto-handled)."""
    return datetime.now(PACIFIC).date()


def pacific_now() -> datetime:
    """Timezone-aware datetime in America/Los_Angeles."""
    return datetime.now(PACIFIC)


def to_pacific_iso(value: datetime | str | None) -> str | None:
    """ISO 8601 in America/Los_Angeles with an explicit, DST-aware offset,
    e.g. "2026-11-27T20:00:00-08:00".

    Naive values are taken as Pacific wall-clock time (what the
    fishingreservations.net pages print); aware values are converted.
    Strings are parsed first; a trailing "Z" means UTC.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=PACIFIC)
    return value.astimezone(PACIFIC).isoformat(timespec="seconds")


def to_pacific_date(ts: datetime) -> date:
    """Convert any timezone-aware datetime to its Pacific calendar date."""
    if ts.tzinfo is None:
        raise ValueError("naive datetime — caller must supply tzinfo")
    return ts.astimezone(PACIFIC).date()
