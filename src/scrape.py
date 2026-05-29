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
import re
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
    main_url: str | None = None   # Landing homepage — scanned for written reports
    news_url: str | None = None   # News/blog page if separate from main


SOURCES: tuple[LandingSource, ...] = (
    LandingSource(
        name="H&M Landing",
        url="https://www.fishcounts.com/hmlanding/fishcounts.php",
        referer="https://www.hmlanding.com/",
        main_url="https://www.hmlanding.com/",
        news_url="https://www.hmlanding.com/fish-report/",
    ),
    LandingSource(
        name="Fisherman's Landing",
        url="https://www.fishcounts.com/fishermanslanding/fishcounts.php",
        referer="https://www.fishermanslanding.com/",
        main_url="https://www.fishermanslanding.com/",
        news_url="https://www.fishermanslanding.com/fish-reports/",
    ),
    LandingSource(
        name="Seaforth Sportfishing",
        url="https://www.fishcounts.com/seaforth/fishcounts.php",
        referer="https://www.seaforthlanding.com/",
        main_url="https://www.seaforthlanding.com/",
        news_url="https://www.seaforthlanding.com/fish-reports/",
    ),
    LandingSource(
        name="Point Loma Sportfishing",
        url="https://www.pointlomasportfishing.com/fishcounts.php",
        referer=None,
        main_url="https://www.pointlomasportfishing.com/",
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
            "source": "fish_count_page",
            "is_preliminary": 0,
            "written_text": None,
            "reported_at": None,
        })
    return out


def scrape_landing(src: LandingSource, target_date: date | None = None,
                   ) -> tuple[list[dict], date | None, str]:
    """Fetch + parse one landing. Returns (trips, page_date, raw_html)."""
    html = _fetch(src)
    raw_rows, page_date = _extract_rows(html)
    trips = parse_page(html, src.name, src.url, target_date=target_date, region=src.region)

    # Identify boats whose fish-count cell was blank in the structured table.
    blank_boats: set[str] = set()
    for r in raw_rows:
        if not r["fish_count_text"].strip():
            if target_date is None or r["date"] == target_date:
                blank_boats.add(r["boat"].strip())

    if blank_boats and (src.main_url or src.news_url):
        log.debug("text_fallback: %d blank-count boat(s) at %s — scanning written updates",
                  len(blank_boats), src.name)
        _apply_text_fallback(src, trips, blank_boats, target_date)

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


# Matches "<count> <species>" in free-form written reports.
# Handles "12 bluefin tuna", "12 bluefin", "5 yellowtail", etc.
_TEXT_SPECIES_RE = re.compile(
    r'(\d+)\s+'
    r'(bluefin(?:\s+tuna)?|yellowfin(?:\s+tuna)?|yellowtail|'
    r'dorado|mahi(?:-?mahi)?|'
    r'albacore(?:\s+tuna)?|skipjack(?:\s+tuna)?|bigeye(?:\s+tuna)?|'
    r'calico(?:\s+bass)?|halibut|rockfish|white\s+sea\s+bass|sheephead|'
    r'bonito|barracuda|lingcod)',
    re.I,
)

_FINAL_KEYWORDS = [
    'returned', 'returned home', 'docked', 'back at the dock',
    'wrapped up', 'wrap up', 'final count', 'final totals',
    'at the dock', 'tied up', 'now unloading', 'unloading',
]

_PRELIMINARY_KEYWORDS = [
    'called in', 'phoned in', 'radio report', 'still fishing',
    'currently fishing', 'on the water', 'mid-trip',
    'morning report', 'check in', 'checking in', 'midday report',
    'reporting in', 'out on the water',
]


def classify_report_status(text: str) -> str:
    """Return 'final' or 'preliminary' for a written landing report."""
    lower = text.lower()
    for kw in _PRELIMINARY_KEYWORDS:
        if kw in lower:
            return 'preliminary'
    for kw in _FINAL_KEYWORDS:
        if kw in lower:
            return 'final'
    return 'preliminary'   # default safe — don't publish unconfirmed counts


def _fetch_optional(url: str, timeout: float = 20.0) -> str | None:
    """Fetch a URL, returning None on any error (used for supplementary pages)."""
    headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        log.debug("optional fetch failed %s: %s", url, exc)
        return None


def _extract_text_blocks(html: str) -> list[str]:
    """Pull paragraph/div text blocks from a landing page, filtering boilerplate."""
    soup = BeautifulSoup(html, "lxml")
    blocks: list[str] = []
    for tag in soup.find_all(["p", "div", "li", "article"]):
        text = tag.get_text(" ", strip=True)
        if len(text) < 40 or len(text) > 2000:
            continue
        if any(skip in text.lower() for skip in ("©", "privacy policy", "javascript", "cookie")):
            continue
        blocks.append(text)
    return blocks


def _looks_like_fish_report(text: str) -> bool:
    """Quick heuristic: does this block look like a boat fish report?"""
    lower = text.lower()
    has_boat_keyword = any(kw in lower for kw in (
        'limits', 'limits of', 'anglers', 'limits of tuna',
        'bluefin', 'yellowfin', 'yellowtail', 'dorado',
        'albacore', 'limits of fish',
    ))
    has_status_keyword = any(kw in lower for kw in
                             _FINAL_KEYWORDS + _PRELIMINARY_KEYWORDS)
    return has_boat_keyword or has_status_keyword


def _extract_boat_counts_from_text(text: str, boat_name: str) -> dict | None:
    """Find boat_name in text and extract species counts from surrounding context.

    Returns {'tracked': {...}, 'other': {...}, 'text': str} or None if the boat
    isn't mentioned or no species counts are found near the mention.
    """
    text_lower = text.lower()
    boat_lower = boat_name.lower()

    idx = text_lower.find(boat_lower)
    if idx == -1:
        # Try matching the first significant word (≥5 chars) of the boat name.
        first = next((w for w in boat_lower.split() if len(w) >= 5), "")
        if first:
            idx = text_lower.find(first)
    if idx == -1:
        return None

    # Extract a window: 80 chars before the name mention, 400 chars after.
    window = text[max(0, idx - 80): idx + 400]

    tracked = {sp: 0 for sp in P.TRACKED_SPECIES}
    other: dict[str, int] = {}
    found_any = False

    for m in _TEXT_SPECIES_RE.finditer(window):
        after = window[m.end(): m.end() + 12].strip().lower()
        if after.startswith("released"):
            continue
        count = int(m.group(1))
        raw_species = m.group(2)
        canon = P.normalize_species(raw_species)
        if canon in tracked:
            tracked[canon] = max(tracked[canon], count)
            found_any = True
        elif canon in P.EXTENDED_SPECIES_COLUMNS:
            other[canon] = other.get(canon, 0) + count
            found_any = True

    if not found_any:
        return None

    return {"tracked": tracked, "other": other, "text": window.strip()}


def _apply_text_fallback(src: LandingSource, trips: list[dict],
                         blank_boats: set[str],
                         target_date: date | None) -> None:
    """Fill blank fish-count trips from written text on the landing's supplementary pages.

    Mutates trip dicts in-place: updates species counts, recalculates trophy metrics,
    and sets source='text_fallback' / is_preliminary / written_text.
    """
    urls = [u for u in [src.main_url, src.news_url] if u]
    if not urls:
        return

    combined_text = ""
    for url in urls:
        html = _fetch_optional(url)
        if html:
            blocks = _extract_text_blocks(html)
            combined_text += "\n".join(blocks) + "\n"

    if not combined_text:
        return

    for trip in trips:
        if trip["boat"] not in blank_boats:
            continue
        result = _extract_boat_counts_from_text(combined_text, trip["boat"])
        if not result:
            continue

        for sp in P.TRACKED_SPECIES:
            trip[sp.lower()] = result["tracked"].get(sp, 0)

        tracked = result["tracked"]
        metrics = P.trophy_metrics(tracked, trip["anglers"], trip["trip_length_days"])
        trip["trophy_count"] = metrics.trophy_count
        trip["trophy_per_angler"] = metrics.trophy_per_angler
        trip["trophy_per_angler_per_day"] = metrics.trophy_per_angler_per_day
        trip["full_catch"] = P.build_full_catch(tracked, result["other"])

        status = classify_report_status(result["text"])
        trip["source"] = "text_preliminary" if status == "preliminary" else "text_final"
        trip["is_preliminary"] = 1 if status == "preliminary" else 0
        trip["written_text"] = result["text"][:1000]
        trip["reported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        log.info("text_fallback [%s]: %s %s — %s",
                 status, src.name, trip["boat"], result["text"][:80])


def scan_written_updates(src: LandingSource,
                         target_date: date | None = None) -> list[dict]:
    """Scan a landing's homepage and news page for written fish reports.

    Returns a list of provisional trip dicts with source='written_update_final' or
    'written_update_preliminary'. These supplement the structured fish-count table
    when boats report in before the official count page is updated.

    Each returned dict has only the fields we can reliably extract from free text:
    date, landing, source, is_preliminary, written_text, scraped_at. The caller
    should store them separately (not via insert_trips) until reconciled.
    """
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = target_date or date.today()
    reports: list[dict] = []

    urls = [u for u in [src.main_url, src.news_url] if u]
    if not urls:
        return reports

    for url in urls:
        html = _fetch_optional(url)
        if not html:
            continue
        blocks = _extract_text_blocks(html)
        for block in blocks:
            if not _looks_like_fish_report(block):
                continue
            # Try to find a date reference in the block; default to today.
            block_date = P.parse_date(block) or today
            if target_date and block_date != target_date:
                continue
            status = classify_report_status(block)
            source_val = (f'written_update_{status}')
            reports.append({
                "date": block_date.isoformat(),
                "landing": src.name,
                "source": source_val,
                "is_preliminary": 1 if status == 'preliminary' else 0,
                "written_text": block[:1000],
                "scraped_at": scraped_at,
            })
            log.info("written update [%s] %s — %s", status, src.name, block[:80])

    return reports


def reconcile_daily_counts(db_path: str = "tracker.db") -> dict:
    """Compare written_update trips against structured fish-count entries for today.

    Structured fish-count page entries are the source of truth. Any written_update
    row that has a matching structured row gets deleted. Unmatched written_update
    rows are flagged with needs_review=1.

    Returns a summary dict: {matched, flagged}.
    """
    import sqlite3 as _sqlite3
    today = date.today().isoformat()
    conn = _sqlite3.connect(db_path)
    conn.row_factory = _sqlite3.Row
    matched = 0
    flagged = 0
    try:
        written = conn.execute("""
            SELECT id, boat, trip_length, landing, source
            FROM trips
            WHERE date = ?
              AND source IN (
                'text_preliminary', 'text_final', 'text_fallback',
                'written_update_final', 'written_update_preliminary'
              )
        """, (today,)).fetchall()

        for w in written:
            structured = conn.execute("""
                SELECT id FROM trips
                WHERE date = ?
                  AND boat = ?
                  AND trip_length = ?
                  AND landing = ?
                  AND source = 'fish_count_page'
            """, (today, w["boat"], w["trip_length"], w["landing"])).fetchone()

            if structured:
                conn.execute("DELETE FROM trips WHERE id = ?", (w["id"],))
                matched += 1
                log.info("reconcile: removed text entry (structured exists) — %s %s",
                         w["landing"], w["boat"])
            else:
                conn.execute("UPDATE trips SET needs_review = 1 WHERE id = ?", (w["id"],))
                flagged += 1

        conn.commit()
    finally:
        conn.close()

    log.info("reconcile_daily_counts: %d matched+removed, %d flagged for review", matched, flagged)
    return {"matched": matched, "flagged": flagged}


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
