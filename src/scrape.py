"""HTTP scrapers + HTML parsers for the 4 San Diego landings.

3 of the 4 landings (H&M, Fisherman's, Seaforth) share fishcounts.com as a backend
with an identical 4-column table structure — they only differ in CSS class prefix
(HM / FL / SF). Point Loma hosts its own /fishcounts.php with the same logical
4-column shape under different class names. So we use one generic table-shaped
parser for everything, identifying fish-count tables by their column headers
rather than by class.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

import requests
from bs4 import BeautifulSoup, Tag

from . import parse as P
from .moon import moon_info

log = logging.getLogger(__name__)

# Real-browser UA — H&M's primary domain rejects scripted clients.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")


@dataclass(frozen=True)
class LandingSource:
    name: str             # Canonical landing name written into DB
    url: str              # Fish-count page URL
    referer: str | None   # Optional Referer header (needed for fishcounts.com iframes)
    region: str = 'san_diego'


SOURCES: tuple[LandingSource, ...] = (
    LandingSource(
        name="H&M Landing",
        url="https://www.fishcounts.com/hmlanding/fishcounts.php",
        referer="https://www.hmlanding.com/",
    ),
    LandingSource(
        name="Fisherman's Landing",
        url="https://www.fishcounts.com/fishermanslanding/fishcounts.php",
        referer="https://www.fishermanslanding.com/",
    ),
    LandingSource(
        name="Seaforth Sportfishing",
        url="https://www.fishcounts.com/seaforth/fishcounts.php",
        referer="https://www.seaforthlanding.com/",
    ),
    LandingSource(
        name="Point Loma Sportfishing",
        url="https://www.pointlomasportfishing.com/fishcounts.php",
        referer=None,
    ),
    LandingSource(
        name="Oceanside Sea Center",
        url="https://www.fishcounts.com/oceanside/fishcounts.php",
        referer=None,
    ),
    # OC/LA landings — socalfishreports.com / fishcounts.com
    LandingSource(
        name="Channel Islands Sportfishing",
        url="https://socalfishreports.com/landings/channel_islands_sportfishing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Ventura Harbor Sportfishing",
        url="https://socalfishreports.com/landings/ventura_harbor_sportfishing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="22nd Street Landing",
        url="https://socalfishreports.com/landings/22nd_street_landing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Long Beach Sportfishing",
        url="https://socalfishreports.com/landings/long_beach_sportfishing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Marina Del Rey Sportfishing",
        url="https://socalfishreports.com/landings/marina_del_rey_sportfishing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Redondo Beach Sportfishing",
        url="https://socalfishreports.com/landings/redondo_beach_sportfishing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="LA Waterfront Sportfishing",
        url="https://socalfishreports.com/landings/la_waterfront_cruises_&_sportfishing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Pierpoint Landing",
        url="https://socalfishreports.com/landings/pierpoint_landing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Newport Landing",
        url="https://socalfishreports.com/landings/newport_landing.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Davey's Locker",
        url="https://socalfishreports.com/landings/daveys_locker.php",
        referer=None,
        region="oc_la",
    ),
    LandingSource(
        name="Dana Wharf Sportfishing",
        url="https://socalfishreports.com/landings/dana_wharf_sportfishing.php",
        referer=None,
        region="oc_la",
    ),
)


# Substrings that mark a "dock total" / summary row we want to skip.
_SKIP_FIRST_CELL = ("dock total", "boats", "anglers", "trips")


def _fetch(src: LandingSource, timeout: float = 30.0) -> str:
    headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
    if src.referer:
        headers["Referer"] = src.referer
    r = requests.get(src.url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def _is_fishcount_table(table: Tag) -> bool:
    """A table is a fish-count table iff it has a header row containing both
    'Boat' and 'Fish Count' cells."""
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True).lower() for c in tr.find_all(["td", "th"])]
        if "boat" in cells and any("fish count" in c for c in cells):
            return True
    return False


def _row_is_data(cells: list[str]) -> bool:
    """A data row has 4 cells, a non-empty boat name, no summary keyword,
    and an integer-shaped anglers cell."""
    if len(cells) != 4:
        return False
    boat = cells[0].strip()
    if not boat:
        return False
    if any(k in boat.lower() for k in _SKIP_FIRST_CELL):
        return False
    anglers_text = cells[2].strip()
    if not anglers_text:
        return False
    # Anglers cell must be a number (possibly followed by text like "Anglers").
    return any(ch.isdigit() for ch in anglers_text)


def _is_osc_table(table: Tag) -> bool:
    """Oceanside Sea Center uses OSCFishCountHeader class instead of standard headers."""
    return bool(table.find("tr", class_="OSCFishCountHeader"))


def _extract_osc_rows(table: Tag) -> tuple[list[dict], date | None]:
    """Parse Oceanside Sea Center's table: Date | Vessel+TripType | Anglers | Fish Count.

    OSC embeds the date per-row as m/d/yyyy and combines boat+trip_type in one cell
    separated by a <br> tag — different from the standard fishcounts.com format."""
    rows_out: list[dict] = []
    page_date: date | None = None
    for tr in table.find_all("tr"):
        if tr.get("class") and "OSCFishCountHeader" in tr.get("class", []):
            continue
        tds = tr.find_all("td")
        if len(tds) != 4:
            continue
        date_text = tds[0].get_text(strip=True)
        try:
            d = datetime.strptime(date_text, "%m/%d/%Y").date()
        except ValueError:
            continue
        # Vessel cell: <b>Boat Name</b><br>Trip Type — use separator to split around <br>
        b_tag = tds[1].find("b")
        boat = b_tag.get_text(strip=True) if b_tag else tds[1].get_text(" ", strip=True)
        full_cell = tds[1].get_text(" ", strip=True)
        trip_type_raw = full_cell.replace(boat, "", 1).strip()
        anglers_text = tds[2].get_text(strip=True)
        fish_count_text = tds[3].get_text(" ", strip=True)
        if not any(ch.isdigit() for ch in anglers_text):
            continue
        if page_date is None or d > page_date:
            page_date = d
        rows_out.append({
            "date": d,
            "boat": boat,
            "trip_type_raw": trip_type_raw,
            "anglers_text": anglers_text,
            "fish_count_text": fish_count_text,
        })
    return rows_out, page_date


def _extract_rows(html: str) -> tuple[list[dict], date | None]:
    """Pull (date, boat, trip_type, anglers, fish_count) rows out of any
    fish-count tables on the page.

    Date attribution: cells of class *FishCountTitle / *FishCountBreak /
    scale-title carry the report date. Rows below such a header inherit that
    date until the next one. If no date marker is found, returns None for
    the page date (caller will fall back to "today" or skip)."""
    soup = BeautifulSoup(html, "lxml")
    rows_out: list[dict] = []
    page_date: date | None = None
    current_date: date | None = None

    for table in soup.find_all("table"):
        # Oceanside Sea Center uses a different table format.
        if _is_osc_table(table):
            osc_rows, osc_date = _extract_osc_rows(table)
            rows_out.extend(osc_rows)
            if osc_date and (page_date is None or osc_date > page_date):
                page_date = osc_date
            continue

        if not _is_fishcount_table(table):
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            cell_texts = [t.get_text(" ", strip=True) for t in tds]

            # Date separator: a single-cell row (colspan=4) with a parseable date.
            if len(tds) == 1 or any(int(td.get("colspan") or 1) > 1 for td in tds):
                joined = " ".join(cell_texts)
                d = P.parse_date(joined)
                if d:
                    current_date = d
                    if page_date is None or d > page_date:
                        page_date = d
                    continue

            if not _row_is_data(cell_texts):
                continue

            rows_out.append({
                "date": current_date,
                "boat": cell_texts[0].strip(),
                "trip_type_raw": cell_texts[1].strip(),
                "anglers_text": cell_texts[2].strip(),
                "fish_count_text": cell_texts[3].strip(),
            })
    return rows_out, page_date


def parse_page(html: str, landing: str, source_url: str,
               target_date: date | None = None,
               region: str = 'san_diego') -> list[dict]:
    """Convert a fish-count page into trip dicts ready for DB insert.

    Trips shorter than 3/4 day are excluded. Trips without a recognizable trip
    length, anglers count, or report date are skipped (with a log warning).

    If `target_date` is set, only rows tagged with that date are kept; otherwise
    all dated rows are kept (useful for backfilling a fresh DB from a multi-day
    page like H&M's).
    """
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw_rows, _ = _extract_rows(html)
    out: list[dict] = []
    for r in raw_rows:
        if r["date"] is None:
            log.debug("skip: no date  %r", r)
            continue
        if target_date is not None and r["date"] != target_date:
            continue
        length_bucket, length_days = P.parse_trip_length(r["trip_type_raw"])
        if length_bucket is None or length_days is None:
            log.warning("skip: unparsable trip length %r on %s (%s)",
                        r["trip_type_raw"], r["date"], landing)
            continue
        anglers = P.parse_anglers(r["anglers_text"])
        if not anglers or anglers <= 0:
            log.warning("skip: bad anglers %r for %s on %s",
                        r["anglers_text"], r["boat"], r["date"])
            continue
        tracked, other = P.parse_fish_counts(r["fish_count_text"])
        col_counts, other_fish, unknowns = P.extract_extended_species(other)
        is_half_day = 1 if length_days < P.MIN_TRIP_DAYS else 0
        metrics = P.trophy_metrics(tracked, anglers, length_days)
        m = moon_info(datetime.combine(r["date"], datetime.min.time(), tzinfo=timezone.utc))
        out.append({
            "date": r["date"].isoformat(),
            "boat": r["boat"],
            "landing": landing,
            "trip_type_raw": r["trip_type_raw"],
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
            "moon_phase": m.phase,
            "moon_illum": m.illum,
            "days_from_new": m.days_from_new,
            "days_from_full": m.days_from_full,
            "scraped_at": scraped_at,
            "source_url": source_url,
            **col_counts,
            "other_fish": other_fish,
            "is_half_day": is_half_day,
            "region": region,
            "full_catch": P.build_full_catch(tracked, other),
            "_unknowns": unknowns,
        })
    return out


def scrape_landing(src: LandingSource, target_date: date | None = None,
                   ) -> tuple[list[dict], date | None, str]:
    """Fetch + parse one landing. Returns (trips, page_date, raw_html)."""
    html = _fetch(src)
    trips = parse_page(html, src.name, src.url, target_date=target_date, region=src.region)
    _, page_date = _extract_rows(html)
    return trips, page_date, html


def scrape_all(sources: Iterable[LandingSource] = SOURCES,
               target_date: date | None = None) -> list[tuple[LandingSource, list[dict], date | None, str | None]]:
    """Scrape every landing. Each tuple is (source, trips, page_date, error_or_None)."""
    results = []
    for src in sources:
        try:
            trips, page_date, _ = scrape_landing(src, target_date=target_date)
            results.append((src, trips, page_date, None))
        except Exception as e:
            log.exception("scrape failed: %s", src.name)
            results.append((src, [], None, f"{type(e).__name__}: {e}"))
    return results


def backfill_full_catch(db_path: str = "tracker.db", batch: int = 500) -> int:
    """Populate full_catch for all rows that have NULL full_catch.

    Reconstructs the value from the existing tracked-species columns and
    other_species_json — no re-scraping required.
    Returns the number of rows updated.
    """
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(db_path)
    conn.row_factory = _sqlite3.Row
    rows = conn.execute("""
        SELECT id, bluefin, yellowfin, yellowtail, dorado, skipjack, bigeye, albacore,
               other_species_json
        FROM trips WHERE full_catch IS NULL
    """).fetchall()
    updated = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        params = []
        for row in chunk:
            tracked = {
                "Bluefin":    row["bluefin"],    "Yellowfin": row["yellowfin"],
                "Yellowtail": row["yellowtail"], "Dorado":    row["dorado"],
                "Skipjack":   row["skipjack"],   "Bigeye":    row["bigeye"],
                "Albacore":   row["albacore"],
            }
            fc = P.build_full_catch_from_db(tracked, row["other_species_json"])
            params.append((fc, row["id"]))
        conn.executemany("UPDATE trips SET full_catch=? WHERE id=?", params)
        conn.commit()
        updated += len(chunk)
        print(f"  backfill_full_catch: {updated}/{len(rows)} rows done")
    conn.close()
    print(f"backfill_full_catch: complete — {updated} rows updated")
    return updated
