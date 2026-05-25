"""One-time backfill of historical fish counts from per-boat pages.

For each landing we know the URL pattern for per-boat fish-count history pages:

  Fisherman's Landing  -> https://www.fishcounts.com/fishermanslanding/<slug>.php
  Point Loma          -> https://www.pointlomasportfishing.com/fleet/<slug>.php
  Seaforth            -> https://www.fishcounts.com/seaforth/<slug>.php
  H&M Landing         -> (no public history source we can parse — skipped)

Each page exposes the previous ~10 trips. Inserted into the same `trips`
table the daily scrape writes to, with INSERT OR IGNORE so re-running is safe
and duplicates with already-scraped days are de-duped automatically.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

from . import db
from . import parse as P
from .moon import moon_info
from .scrape import UA

log = logging.getLogger(__name__)


def _slug(boat: str) -> str:
    """Boat name -> URL slug used by fishcounts.com and pointlomasportfishing.
    Lowercase + drop everything that isn't a letter or digit."""
    return re.sub(r"[^a-z0-9]+", "", boat.lower())


# Per-landing primary URL builders. The primary source is preferred because it
# usually has more reliable boat-name -> slug mappings.
URL_BUILDERS = {
    "Fisherman's Landing":      lambda slug: f"https://www.fishcounts.com/fishermanslanding/{slug}.php",
    "Seaforth Sportfishing":    lambda slug: f"https://www.fishcounts.com/seaforth/{slug}.php",
    "Point Loma Sportfishing":  lambda slug: f"https://www.pointlomasportfishing.com/fleet/{slug}.php",
}

# sportfishingreport.com hosts per-boat history for ~every SD sportfisher across
# all four landings. Used as the H&M fallback (their boat pages are Angular SPAs
# with no static history) and as a secondary for any other boat that returns 0
# rows from its primary source.
SPORTFISHING_REPORT = lambda slug: f"https://www.sportfishingreport.com/charter_boats/{slug}.php"

# Some boat names need an explicit slug override (e.g., when the URL uses a
# shortened form that the standard `_slug()` wouldn't produce).
SLUG_OVERRIDES: dict[str, str] = {
    # name -> exact slug to use on sportfishingreport.com
}


_DATE_RE = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")


@dataclass
class HistRow:
    date: str            # ISO YYYY-MM-DD
    trip_type_raw: str
    anglers: int
    fish_count_text: str


def _parse_anglers(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d[\d,]*)", text)
    return int(m.group(1).replace(",", "")) if m else None


def _iso_from_mdy(text: str) -> str | None:
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    month, day, year = m.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def parse_fishcounts_history(html: str) -> list[HistRow]:
    """Parse the per-boat history table on fishcounts.com (FL + SF).

    Structure (4 cells per row):
      <td><strong>MM-DD-YYYY</strong></td>
      <td>Trip Type</td>
      <td>N Anglers</td>
      <td>Fish count text</td>
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[HistRow] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 4:
            continue
        cells = [t.get_text(" ", strip=True) for t in tds]
        d = _iso_from_mdy(cells[0])
        if not d:
            continue
        anglers = _parse_anglers(cells[2])
        if not anglers:
            continue
        out.append(HistRow(
            date=d,
            trip_type_raw=cells[1],
            anglers=anglers,
            fish_count_text=cells[3],
        ))
    return out


def parse_pointloma_fleet_history(html: str) -> list[HistRow]:
    """Parse the 'Recent Fish Counts' table on Point Loma boat pages.

    Structure: 2 cells per <tr>. Date in first cell <strong>. Trip type +
    anglers + fish count live in nested col-sm-N divs in the second cell.
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[HistRow] = []

    # Find the table whose title contains "Recent ... Fish Counts" (anchors on
    # a scale-title row), then only iterate <tr>s inside that table.
    target = None
    for table in soup.find_all("table"):
        title = table.find("td", class_="scale-title")
        if title and re.search(r"Recent .+ Fish Counts", title.get_text()):
            target = table
            break
    if target is None:
        return out

    for tr in target.find_all("tr"):
        tds = tr.find_all("td", class_="scale-data")
        if len(tds) != 2:
            continue
        d = _iso_from_mdy(tds[0].get_text(strip=True))
        if not d:
            continue
        # tds[1] has nested divs for trip type, anglers, fish count.
        divs = tds[1].find_all("div", class_=re.compile(r"col-sm-"))
        if len(divs) < 3:
            continue
        trip_type = divs[0].get_text(" ", strip=True)
        anglers_text = divs[1].get_text(" ", strip=True)
        # Find the fish-count div (class fcdata) or fall back to the 3rd col.
        fcdata = tds[1].find("div", class_=re.compile(r"\bfcdata\b"))
        fish_text = fcdata.get_text(" ", strip=True) if fcdata else divs[2].get_text(" ", strip=True)
        anglers = _parse_anglers(anglers_text)
        if not anglers:
            continue
        out.append(HistRow(
            date=d, trip_type_raw=trip_type, anglers=anglers, fish_count_text=fish_text,
        ))
    return out


def _row_to_trip(r: HistRow, *, boat: str, landing: str, source_url: str) -> dict | None:
    length_bucket, length_days = P.parse_trip_length(r.trip_type_raw)
    if length_bucket is None or length_days is None:
        return None
    tracked, other = P.parse_fish_counts(r.fish_count_text)
    col_counts, other_fish, unknowns = P.extract_extended_species(other)
    is_half_day = 1 if length_days < P.MIN_TRIP_DAYS else 0
    metrics = P.trophy_metrics(tracked, r.anglers, length_days)
    dt = datetime.fromisoformat(r.date).replace(tzinfo=timezone.utc)
    m = moon_info(dt)
    return {
        "date": r.date,
        "boat": boat,
        "landing": landing,
        "trip_type_raw": r.trip_type_raw,
        "trip_length": length_bucket,
        "trip_length_days": length_days,
        "anglers": r.anglers,
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
        "moon_phase": m.phase,
        "moon_illum": m.illum,
        "days_from_new": m.days_from_new,
        "days_from_full": m.days_from_full,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": source_url,
        **col_counts,
        "other_fish": other_fish,
        "is_half_day": is_half_day,
        "_unknowns": unknowns,
    }


def backfill_boat(boat: str, landing: str, session: requests.Session) -> tuple[int, str | None]:
    """Fetch + parse one boat's history page. Returns (rows_found, error_or_None)."""
    builder = URL_BUILDERS.get(landing)
    if not builder:
        return 0, f"no backfill source configured for {landing}"
    slug = _slug(boat)
    url = builder(slug)
    try:
        r = session.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=20)
    except requests.RequestException as e:
        return 0, f"{type(e).__name__}: {e}"
    if r.status_code == 404:
        return 0, f"404 at {url}"
    if r.status_code != 200:
        return 0, f"HTTP {r.status_code} at {url}"
    if landing == "Point Loma Sportfishing":
        rows = parse_pointloma_fleet_history(r.text)
    else:
        rows = parse_fishcounts_history(r.text)
    return len(rows), None if rows else f"no rows parsed at {url}"


def _fetch_and_parse(url: str, parser_kind: str,
                      session: requests.Session) -> list[HistRow]:
    """Fetch one URL and run the appropriate parser. Returns [] on any failure."""
    try:
        r = session.get(url, headers={"User-Agent": UA}, timeout=20)
    except Exception as e:
        log.warning("fetch failed %s: %s", url, e)
        return []
    if r.status_code != 200:
        log.info("HTTP %s at %s", r.status_code, url)
        return []
    if parser_kind == "pointloma_style":
        return parse_pointloma_fleet_history(r.text)
    elif parser_kind == "fishcounts_table":
        return parse_fishcounts_history(r.text)
    return []


def _sources_for(landing: str, boat: str) -> list[tuple[str, str]]:
    """Build the ordered list of (url, parser_kind) sources to try for a boat.
    First success with non-empty results wins; otherwise we try the next."""
    out = []
    slug = SLUG_OVERRIDES.get(boat) or _slug(boat)
    primary = URL_BUILDERS.get(landing)
    if primary:
        kind = "pointloma_style" if landing == "Point Loma Sportfishing" else "fishcounts_table"
        out.append((primary(slug), kind))
    # sportfishingreport.com uses Point Loma's HTML shape and covers ~every boat,
    # so it's the universal fallback (and only source for H&M Landing).
    out.append((SPORTFISHING_REPORT(slug), "pointloma_style"))
    return out


def run_backfill(db_path: Path) -> None:
    session = requests.Session()
    with db.connect(db_path) as conn:
        boats = conn.execute(
            "SELECT DISTINCT boat, landing FROM trips ORDER BY landing, boat"
        ).fetchall()
        total_seen = 0
        total_inserted = 0
        for row in boats:
            boat, landing = row["boat"], row["landing"]
            # Pull from every source we know about (not just the first hit) —
            # different sources expose different windows of history, and the DB's
            # UNIQUE constraint dedupes any overlap.
            by_key: dict[tuple, dict] = {}
            sources_used: list[str] = []
            for url, kind in _sources_for(landing, boat):
                rows = _fetch_and_parse(url, kind, session)
                if rows:
                    sources_used.append("primary" if "sportfishingreport" not in url else "sfr")
                    for hr in rows:
                        t = _row_to_trip(hr, boat=boat, landing=landing, source_url=url)
                        if not t:
                            continue
                        # Local dedupe matches the DB UNIQUE: (date, boat, landing, trip_length, anglers)
                        key = (t["date"], t["boat"], t["landing"], t["trip_length"], t["anglers"])
                        by_key.setdefault(key, t)
                time.sleep(0.3)
            if not by_key:
                print(f"  {landing:25s} {boat:25s} no rows found at any source")
                continue
            trips = list(by_key.values())
            inserted = db.insert_trips(conn, trips)
            total_seen += len(trips)
            total_inserted += inserted
            print(f"  {landing:25s} {boat:25s} parsed={len(trips):3d}  inserted={inserted:3d}  src={'+'.join(sources_used)}")
            time.sleep(0.3)
        print()
        print(f"Backfill complete: parsed {total_seen} historical trips, inserted {total_inserted} new rows.")
