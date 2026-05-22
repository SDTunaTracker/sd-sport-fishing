"""Deep historical backfill from sandiegofishreports.com.

That site exposes a per-date archive at:
    https://www.sandiegofishreports.com/dock_totals/boats.php?date=YYYY-MM-DD

Each page lists every reporting boat for that day across every SD landing,
grouped under landing-named panels. Their archive goes back to ~2010, so this
gives us *years* of history beyond what any per-boat page exposes.

The runner walks dates backward from `start` until either:
  * the hard floor is reached (default 2010-01-01), or
  * `max_empty_streak` consecutive days return zero qualifying trips
    (heuristic that we've gone past the useful data).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import db
from . import parse as P
from .moon import moon_info
from .scrape import UA

log = logging.getLogger(__name__)

SDFR_URL = "https://www.sandiegofishreports.com/dock_totals/boats.php"

# Only ingest rows for boats reporting under these four landings.
APPROVED_LANDINGS: tuple[str, ...] = (
    "H&M Landing",
    "Fisherman's Landing",
    "Point Loma Sportfishing",
    "Seaforth Sportfishing",
)

_ANGLERS_RE = re.compile(r"(\d[\d,]*)\s*Anglers", re.I)


def _landing_for_panel(h2_text: str) -> str | None:
    """Return our canonical landing name if this panel's heading matches one
    of the four approved landings."""
    if not h2_text:
        return None
    low = h2_text.lower()
    for ln in APPROVED_LANDINGS:
        if ln.lower() in low:
            return ln
    return None


def parse_sdfr_day(html: str, report_date: str) -> list[dict]:
    """Parse one SDFR `?date=...` page into trip dicts ready for db.insert_trips.

    `report_date` is the ISO date this page represents (YYYY-MM-DD).
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    moon_for_day = moon_info(
        datetime.fromisoformat(report_date).replace(tzinfo=timezone.utc)
    )

    for panel in soup.find_all("div", class_=re.compile(r"\bpanel\b")):
        h2 = panel.find("h2")
        if not h2:
            continue
        landing = _landing_for_panel(h2.get_text(strip=True))
        if not landing:
            continue
        table = panel.find("table")
        if not table:
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) != 3:
                continue

            boat_tag = tds[0].find("b")
            if not boat_tag:
                continue
            boat = boat_tag.get_text(strip=True)
            if not boat:
                continue

            details_text = tds[1].get_text(" ", strip=True)
            m = _ANGLERS_RE.search(details_text)
            if not m:
                continue
            anglers = int(m.group(1).replace(",", ""))
            if anglers <= 0:
                continue
            trip_type_raw = _ANGLERS_RE.sub("", details_text).strip()
            if not trip_type_raw:
                continue

            length_bucket, length_days = P.parse_trip_length(trip_type_raw)
            if length_bucket is None or length_days is None:
                continue
            if length_days < P.MIN_TRIP_DAYS:
                continue  # skip half-day / twilight

            fish_text = tds[2].get_text(" ", strip=True)
            tracked, other = P.parse_fish_counts(fish_text)
            metrics = P.trophy_metrics(tracked, anglers, length_days)

            out.append({
                "date": report_date,
                "boat": boat,
                "landing": landing,
                "trip_type_raw": trip_type_raw,
                "trip_length": length_bucket,
                "trip_length_days": length_days,
                "anglers": anglers,
                "bluefin": tracked["Bluefin"],
                "yellowfin": tracked["Yellowfin"],
                "yellowtail": tracked["Yellowtail"],
                "dorado": tracked["Dorado"],
                "skipjack": tracked["Skipjack"],
                "bigeye": tracked["Bigeye"],
                "albacore": tracked["Albacore"],
                "trophy_count": metrics.trophy_count,
                "trophy_per_angler": metrics.trophy_per_angler,
                "trophy_per_angler_per_day": metrics.trophy_per_angler_per_day,
                "other_species_json": json.dumps(other),
                "moon_phase": moon_for_day.phase,
                "moon_illum": moon_for_day.illum,
                "days_from_new": moon_for_day.days_from_new,
                "days_from_full": moon_for_day.days_from_full,
                "scraped_at": scraped_at,
                "source_url": f"{SDFR_URL}?date={report_date}",
            })
    return out


def run_deep_backfill(
    db_path: Path,
    *,
    start: date | None = None,
    stop: date = date(2010, 1, 1),
    throttle: float = 0.3,
    max_empty_streak: int = 180,
    commit_every: int = 30,
) -> None:
    """Walk dates backward from `start` (default today) toward `stop`.
    Commits to the DB every `commit_every` days so a crash mid-run doesn't lose
    everything already scraped."""
    if start is None:
        start = date.today()
    session = requests.Session()
    cur = start
    empty_streak = 0
    total_inserted = 0
    total_seen = 0
    scanned = 0
    since_commit = 0

    with db.connect(db_path) as conn:
        while True:
            if cur < stop:
                print(f"Reached hard floor {stop.isoformat()}, halting.")
                break
            if empty_streak >= max_empty_streak:
                print(f"{max_empty_streak} consecutive empty days; assuming archive end. Halting.")
                break

            url = f"{SDFR_URL}?date={cur.isoformat()}"
            try:
                r = session.get(url, headers={"User-Agent": UA}, timeout=20)
            except Exception as e:
                log.warning("fetch %s failed: %s", url, e)
                cur -= timedelta(days=1)
                time.sleep(throttle)
                continue

            if r.status_code != 200:
                log.info("HTTP %s at %s", r.status_code, url)
                cur -= timedelta(days=1)
                empty_streak += 1
                time.sleep(throttle)
                continue

            try:
                trips = parse_sdfr_day(r.text, cur.isoformat())
            except Exception:
                log.exception("parse failed for %s", cur.isoformat())
                trips = []

            inserted = db.insert_trips(conn, trips) if trips else 0
            total_seen += len(trips)
            total_inserted += inserted
            scanned += 1
            since_commit += 1
            empty_streak = 0 if trips else empty_streak + 1

            if since_commit >= commit_every:
                conn.commit()
                print(f"  {cur.isoformat()}  scanned={scanned:5d}  total_inserted={total_inserted:5d}")
                since_commit = 0

            cur -= timedelta(days=1)
            time.sleep(throttle)

        conn.commit()

    print()
    print(f"Deep backfill complete. Scanned {scanned} dates back to {(cur + timedelta(days=1)).isoformat()}.")
    print(f"Parsed {total_seen} qualifying trips, inserted {total_inserted} NEW rows (rest were dups).")
