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
from pathlib import Path
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
            # Landing pages show today's active trips at the top with no date
            # header (the current day is implicit). Fall back to target_date if
            # explicitly set, otherwise assume today.
            r["date"] = target_date if target_date is not None else date.today()
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
                   known_boats: list[str] | None = None,
                   ) -> tuple[list[dict], date | None, str]:
    """Fetch + parse one landing. Returns (trips, page_date, raw_html).

    known_boats: all historically-seen boat names from the DB — passed in from
    main.py so that multi-day boats not in today's structured table can still be
    matched in narrative reports.
    """
    html = _fetch(src)
    _, page_date = _extract_rows(html)
    trips = parse_page(html, src.name, src.url, target_date=target_date, region=src.region)

    if src.main_url or src.news_url:
        # Verb-agnostic, boat-anchored harvest: fills blank structured trips
        # and creates provisional records for boats not in today's table.
        new_from_narrative = _harvest_narrative_reports(
            src, trips, known_boats or [], target_date,
        )
        trips.extend(new_from_narrative)
        try:
            n = _apply_calledin_reports(src, trips, [t['boat'] for t in trips], target_date)
            if n:
                log.info("calledin_reports: filled %d trip(s) at %s", n, src.name)
        except Exception as exc:
            log.warning("calledin_reports failed at %s: %s", src.name, exc)

    _write_last_success(src.name)
    return trips, page_date, html


def scrape_all(sources: Iterable[LandingSource] = SOURCES,
               target_date: date | None = None,
               known_boats: list[str] | None = None,
               ) -> list[tuple[LandingSource, list[dict], date | None, str | None]]:
    """Scrape every landing. Each tuple is (source, trips, page_date, error_or_None)."""
    results = []
    for src in sources:
        try:
            trips, page_date, _ = scrape_landing(
                src, target_date=target_date, known_boats=known_boats,
            )
            results.append((src, trips, page_date, None))
        except Exception as e:
            log.exception("scrape failed: %s", src.name)
            results.append((src, [], None, f"{type(e).__name__}: {e}"))
    return results


def _build_species_re() -> re.Pattern:
    """Build species-matching regex from all parse.py aliases, longest-first.

    Longest-first prevents 'Tuna' from short-circuiting 'Yellowfin Tuna'.
    Any alias added to parse._SPECIES_ALIASES or _EXTENDED_ALIASES is
    automatically included here without touching this file.
    """
    all_aliases = list(P._SPECIES_ALIASES.keys()) + list(P._EXTENDED_ALIASES.keys())
    parts = sorted(set(all_aliases), key=len, reverse=True)
    return re.compile(
        r'(?<!\d)(\d+)\s+(?:mixed\s+)?(' + '|'.join(re.escape(a) for a in parts) + r')\b',
        re.I,
    )


_TEXT_SPECIES_RE = _build_species_re()

# Species names that must never be treated as boat names.  These end up in the
# historical DB after a misparse and would otherwise self-reinforce on every run.
_BOAT_NAME_BLACKLIST = frozenset({
    'Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado', 'Skipjack', 'Albacore', 'Bigeye',
})


def _extract_pairs(text: str) -> tuple[dict, dict, list[tuple[str, int]]]:
    """Harvest (count, species) pairs from free-form text.

    Returns (tracked_counts, other_counts, unknowns).
    A pair counts only when a digit sequence is *immediately* followed by a
    known species token — so "tomorrow 6/2", "3 Day", "spots available" produce
    nothing.  'Released' variants are skipped.
    """
    tracked: dict[str, int] = {sp: 0 for sp in P.TRACKED_SPECIES}
    other:   dict[str, int] = {}
    unknown: list[tuple[str, int]] = []

    for m in _TEXT_SPECIES_RE.finditer(text):
        after = text[m.end(): m.end() + 12].strip().lower()
        if after.startswith('released'):
            continue
        cnt   = int(m.group(1))
        canon = P.normalize_species(m.group(2))
        if canon in tracked:
            tracked[canon] = max(tracked[canon], cnt)
        elif canon in P.EXTENDED_SPECIES_COLUMNS:
            other[canon] = max(other.get(canon, 0), cnt)
        else:
            unknown.append((m.group(2).strip(), cnt))

    return tracked, other, unknown


_PROSE_TRIP_RE = re.compile(
    r'\b(long\s+range|overnight|(?:1\.5|2\.5|[2-7])\s+day|full\s+day)\b',
    re.I,
)


def _trip_length_from_prose(text: str) -> tuple[str | None, float | None, str]:
    """Return (bucket, days, raw_phrase) for the first trip-length phrase in text."""
    m = _PROSE_TRIP_RE.search(text)
    if not m:
        return None, None, ''
    raw = m.group(0)
    bucket, days = P.parse_trip_length(raw)
    return bucket, days, raw


# Boats known to run only one trip type.  Used as a fallback when the boat's
# own text window contains no explicit trip-length phrase.
BOAT_TRIP_LENGTH_DEFAULTS: dict[str, tuple[str, float, str]] = {
    'lucky b sportfishing': ('Full Day', 0.75, 'Full Day'),
}

# ---------------------------------------------------------------------------
# Called-in / returned-with text report parser
# ---------------------------------------------------------------------------

# Strip "UPDATE 10:30AM:", "AM UPDATE:", bare "UPDATE:" from block start.
_BLOCK_PREFIX_RE = re.compile(
    r'^(?:'
    r'(?:UPDATE\s+)?\d{1,2}:\d{2}\s*(?:AM|PM)\s*[:\-]\s*'
    r'|UPDATE\s*[:\-]\s*'
    r'|(?:AM|PM)\s+UPDATE\s*[:\-]\s*'
    r')',
    re.I,
)

# Trailing " AM" / " PM" qualifier at end of a boat-name string.
_AM_PM_SUFFIX_RE = re.compile(r'\s+(AM|PM)\s*$', re.I)

# "The " prefix to strip from boat-name candidates.
_THE_PREFIX_RE = re.compile(r'^the\s+', re.I)

# (pattern, template_type) pairs tried in order per block.
_REPORT_TEMPLATES: list[tuple[re.Pattern, str]] = [
    # "Dolphin AM called in – 22 Bluefin Tuna, 5 Yellowtail"
    (re.compile(
        r'(?P<boat_am>[A-Za-z][A-Za-z0-9 \-\']{1,44}?)'
        r'\s+(?:called?\s+in|phoned?\s+in|check(?:ing|ed)?\s+in|reporting\s+in)'
        r'\s*[–\-:—]?\s*(?:with\s+)?'
        r'(?P<counts>[^\n]{5,280})',
        re.I,
    ), 'calledin'),
    # "Dolphin PM returned with 18 Bluefin Tuna, 3 Dorado"
    (re.compile(
        r'(?P<boat_am>[A-Za-z][A-Za-z0-9 \-\']{1,44}?)'
        r'\s+returned\s+(?:to\s+(?:the\s+)?dock\s+)?(?:home\s+)?with\s+'
        r'(?P<counts>[^\n]{5,280})',
        re.I,
    ), 'returned'),
    # "Caught aboard the Dolphin AM: 12 Yellowtail, 20 mixed Rockfish"
    (re.compile(
        r'caught\s+(?:aboard\s+)?(?:the\s+)?'
        r'(?P<boat_am>[A-Za-z][A-Za-z0-9 \-\']{1,44}?)'
        r'\s*[:–\-—]\s*'
        r'(?P<counts>[^\n]{5,280})',
        re.I,
    ), 'caught'),
]


def _split_boat_am_pm(
    raw: str,
    known_boats: list[str] | None,
) -> tuple[str, str | None]:
    """Return (boat_name, 'AM'|'PM'|None) from a raw match like 'Dolphin AM'.

    Strips leading 'The', extracts trailing AM/PM, then fuzzy-matches against
    known_boats if provided. Falls back to the cleaned string as-is (low confidence).
    """
    import difflib as _dl
    s = _THE_PREFIX_RE.sub('', raw.strip())
    am_pm: str | None = None
    m = _AM_PM_SUFFIX_RE.search(s)
    if m:
        am_pm = m.group(1).upper()
        s = s[:m.start()].strip()
    if not s:
        return raw.strip(), am_pm

    if known_boats:
        s_lower = s.lower()
        # Exact match
        for boat in known_boats:
            if s_lower == boat.lower():
                return boat, am_pm
        # Structured table may store "Dolphin AM" as the boat name — strip qualifier
        for boat in known_boats:
            base = _AM_PM_SUFFIX_RE.sub('', boat).strip()
            if s_lower == base.lower():
                return base, am_pm
        # Fuzzy match against base names
        bases = list({_AM_PM_SUFFIX_RE.sub('', b).strip() for b in known_boats})
        hits = _dl.get_close_matches(s, bases, n=1, cutoff=0.75)
        if hits:
            return hits[0], am_pm

    return s, am_pm  # low-confidence: use as-is


def parse_text_reports(
    blocks: list[str],
    landing: str,
    target_date: 'date | None',
    known_boats: list[str] | None = None,
) -> list[dict]:
    """Parse called-in / returned-with narrative blocks into partial trip dicts.

    Each block is tried against three templates in order: calledin, returned,
    caught. The first template that matches AND yields at least one recognisable
    species count produces one trip record. Dedup is by (date, boat, trip_length).

    Anglers defaults to 1 when not found in text — caller should merge with the
    corresponding structured trip (which has the real angler count) before insert.
    """
    scraped_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    today = target_date or date.today()
    out: list[dict] = []
    seen: set[tuple] = set()

    for raw_block in blocks:
        block = _BLOCK_PREFIX_RE.sub('', raw_block.strip())

        for pattern, tmpl in _REPORT_TEMPLATES:
            m = pattern.search(block)
            if not m:
                continue

            counts_raw = m.group('counts').strip()
            tracked = {sp: 0 for sp in P.TRACKED_SPECIES}
            other: dict[str, int] = {}
            found_any = False

            for sm in _TEXT_SPECIES_RE.finditer(counts_raw):
                after = counts_raw[sm.end(): sm.end() + 12].strip().lower()
                if after.startswith('released'):
                    continue
                cnt = int(sm.group(1))
                canon = P.normalize_species(sm.group(2))
                if canon in tracked:
                    tracked[canon] = max(tracked[canon], cnt)
                    found_any = True
                elif canon in P.EXTENDED_SPECIES_COLUMNS:
                    other[canon] = max(other.get(canon, 0), cnt)
                    found_any = True

            if not found_any:
                continue  # no species recognised — try next template

            boat_name, am_pm = _split_boat_am_pm(m.group('boat_am').strip(), known_boats)

            if am_pm == 'AM':
                trip_length, tl_days, tl_raw = 'Half Day AM', 0.5, 'Half Day AM'
            elif am_pm == 'PM':
                trip_length, tl_days, tl_raw = 'Half Day PM', 0.5, 'Half Day PM'
            else:
                trip_length, tl_days, tl_raw = 'Full Day', 0.75, 'Full Day'

            block_date = P.parse_date(block) or today
            dedup_key = (block_date.isoformat(), boat_name.lower(), trip_length)
            if dedup_key in seen:
                break
            seen.add(dedup_key)

            ang_m = re.search(r'(\d+)\s+anglers?\b', counts_raw, re.I)
            anglers = int(ang_m.group(1)) if ang_m else 1

            col_counts, other_fish, unknowns = P.extract_extended_species(other)
            is_preliminary = 0 if tmpl == 'returned' else 1
            metrics = P.trophy_metrics(tracked, max(anglers, 1), tl_days)
            moon = moon_info(datetime.combine(
                block_date, datetime.min.time(), tzinfo=timezone.utc))

            out.append({
                'date':                     block_date.isoformat(),
                'boat':                     boat_name,
                'landing':                  landing,
                'trip_type_raw':            tl_raw,
                'trip_length':              trip_length,
                'trip_length_days':         tl_days,
                'anglers':                  anglers,
                'bluefin':                  tracked['Bluefin'],
                'yellowfin':                tracked['Yellowfin'],
                'yellowtail':               tracked['Yellowtail'],
                'dorado':                   tracked['Dorado'],
                'skipjack':                 tracked['Skipjack'],
                'bigeye':                   tracked['Bigeye'],
                'albacore':                 tracked['Albacore'],
                'trophy_count':             metrics.trophy_count,
                'trophy_per_angler':        metrics.trophy_per_angler,
                'trophy_per_angler_per_day': metrics.trophy_per_angler_per_day,
                'other_species_json':       json.dumps(other),
                'moon_phase':               moon.phase,
                'moon_illum':               moon.illum,
                'days_from_new':            moon.days_from_new,
                'days_from_full':           moon.days_from_full,
                'scraped_at':               scraped_at,
                'source_url':               '',
                **col_counts,
                'other_fish':               other_fish,
                'is_half_day':              1 if tl_days < P.MIN_TRIP_DAYS else 0,
                'region':                   'san_diego',
                'full_catch':               P.build_full_catch(tracked, other),
                'source':  f'text_calledin_{"final" if not is_preliminary else "preliminary"}',
                'is_preliminary':           is_preliminary,
                'written_text':             raw_block[:500],
                'reported_at':              scraped_at,
                '_unknowns':                unknowns,
            })
            break  # first matching template wins

    return out


_LAST_SUCCESS_PATH = Path(__file__).resolve().parents[1] / 'logs' / 'last_success.json'


def _write_last_success(landing: str) -> None:
    _LAST_SUCCESS_PATH.parent.mkdir(exist_ok=True)
    try:
        data = json.loads(_LAST_SUCCESS_PATH.read_text(encoding='utf-8')) \
               if _LAST_SUCCESS_PATH.exists() else {}
    except Exception:
        data = {}
    data[landing] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        _LAST_SUCCESS_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception as exc:
        log.debug('last_success.json write failed: %s', exc)


def _apply_calledin_reports(
    src: LandingSource,
    trips: list[dict],
    known_boats: list[str],
    target_date: 'date | None',
) -> int:
    """Scan landing news pages for called-in reports; fill zero-count structured trips.

    Returns the number of trips updated. Only updates trips whose trophy_count is
    still 0 after the structured-table parse — richer text data wins over zeros,
    but won't override a structured trip that already has real fish counts.
    """
    urls = [u for u in [src.main_url, src.news_url] if u]
    if not urls:
        return 0

    all_blocks: list[str] = []
    for url in urls:
        html = _fetch_optional(url)
        if html:
            all_blocks.extend(_extract_text_blocks(html))

    if not all_blocks:
        return 0

    text_trips = parse_text_reports(all_blocks, src.name, target_date, known_boats)
    if not text_trips:
        return 0

    # Index structured trips by (normalised_boat_base, trip_length) so that
    # "Dolphin AM" in the table matches "Dolphin"+"Half Day AM" from the text.
    def _norm_key(boat: str, tl: str) -> tuple[str, str]:
        base = _AM_PM_SUFFIX_RE.sub('', boat).strip().lower()
        if boat.upper().endswith(' AM'):
            tl = 'Half Day AM'
        elif boat.upper().endswith(' PM'):
            tl = 'Half Day PM'
        return base, tl

    trip_map: dict[tuple, dict] = {}
    for t in trips:
        trip_map[_norm_key(t['boat'], t['trip_length'])] = t

    filled = 0
    for tt in text_trips:
        key = (tt['boat'].lower(), tt['trip_length'])
        existing = trip_map.get(key)
        if existing is None:
            continue  # boat not in today's structured table — skip
        if existing.get('trophy_count', 0) > 0:
            continue  # structured data already has real counts
        for sp in P.TRACKED_SPECIES:
            existing[sp.lower()] = tt[sp.lower()] if sp.lower() in tt else tt.get(sp, 0)
        existing['trophy_count']             = tt['trophy_count']
        existing['trophy_per_angler']        = tt['trophy_per_angler']
        existing['trophy_per_angler_per_day'] = tt['trophy_per_angler_per_day']
        existing['full_catch']               = tt['full_catch']
        existing['source']                   = tt['source']
        existing['is_preliminary']           = tt['is_preliminary']
        existing['written_text']             = tt.get('written_text')
        existing['reported_at']              = tt.get('reported_at')
        log.info('calledin_fill [%s]: %s %s — %s',
                 src.name, tt['boat'], tt['trip_length'],
                 (tt.get('written_text') or '')[:60])
        filled += 1

    return filled


_FINAL_KEYWORDS = [
    'returned', 'returned home', 'docked', 'back at the dock',
    'wrapped up', 'wrap up', 'final count', 'final totals',
    'at the dock', 'tied up', 'now unloading', 'unloading',
    'back down to', 'back in port', 'back to the dock',
]

_PRELIMINARY_KEYWORDS = [
    'called in', 'phoned in', 'radio report', 'still fishing',
    'currently fishing', 'on the water', 'mid-trip',
    'morning report', 'check in', 'checking in', 'midday report',
    'reporting in', 'out on the water',
    'checked in', 'checked in from', 'switching gears', 'stay tuned',
    'still on the water', 'heading back', 'still out',
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


def _extract_boat_counts_from_text(
    text: str,
    boat_name: str,
    hard_stop: int | None = None,
) -> dict | None:
    """Find boat_name in text and extract species counts from surrounding context.

    Returns {'tracked': {...}, 'other': {...}, 'text': str} or None if the boat
    isn't mentioned or no species counts are found near the mention.

    hard_stop — absolute index in *text* where the window must end (used to
    prevent counts from the immediately-following boat bleeding in).
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

    # Extract a window: 80 chars before the name mention, up to 400 chars after,
    # but never past hard_stop (the next boat-name mention in the same block).
    window_end = idx + 400
    if hard_stop is not None:
        window_end = min(window_end, hard_stop)
    window = text[max(0, idx - 80): window_end]

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


def _harvest_narrative_reports(
    src: LandingSource,
    trips: list[dict],
    all_boat_names: list[str],
    target_date: 'date | None',
) -> list[dict]:
    """Verb-agnostic, boat-anchored harvest of narrative landing reports.

    A text block is a catch report when it:
      (a) names a known boat (from all_boat_names ∪ today's structured trips), and
      (b) contains ≥1 '<number> <known-species>' pairs.
    Verb phrases are ignored entirely — only boat name + number-species pairs matter.

    Two outcomes per matched block:
      Fill  — boat in today's structured trips with trophy_count=0 and
              source='fish_count_page': fill species counts in-place, preserving
              the real anglers value from the structured row.
      New   — boat not in today's structured trips: return a provisional trip
              record (anglers=0, is_preliminary=1) for insertion.

    Unrecognised '<number> <Word>' catches are logged at INFO so the species
    alias tables can grow from real misses rather than silently dropping data.
    """
    if not (src.main_url or src.news_url):
        return []

    today      = target_date or date.today()
    scraped_at = datetime.now(timezone.utc).isoformat(timespec='seconds')

    # Index today's structured trips by lowercase boat name for O(1) lookup.
    structured: dict[str, dict] = {t['boat'].lower(): t for t in trips}

    # Merge historical boat list with today's boats so boats that just started
    # appearing (not yet in the DB) can still be matched.
    combined = list({*all_boat_names, *(t['boat'] for t in trips)})
    if not combined:
        return []
    boats_sorted = sorted(
        (b for b in combined if b not in _BOAT_NAME_BLACKLIST),
        key=len, reverse=True,
    )
    boat_canon: dict[str, str] = {b.lower(): b for b in boats_sorted}

    # Optional leading "The "; named group captures only the boat name itself.
    boat_re = re.compile(
        r'(?:The\s+)?(?P<boat>' +
        '|'.join(re.escape(b) for b in boats_sorted) +
        r')\b',
        re.I,
    )

    # Fetch text blocks from all landing supplementary pages.
    blocks: list[str] = []
    for url in [u for u in [src.main_url, src.news_url] if u]:
        html = _fetch_optional(url)
        if html:
            blocks.extend(_extract_text_blocks(html))
    if not blocks:
        return []

    new_trips: list[dict] = []
    seen_new:  set[str]   = set()   # boat keys already emitted as new records

    for block in blocks:
        m = boat_re.search(block)
        if not m:
            continue

        raw_boat  = m.group('boat')
        boat_key  = raw_boat.lower()
        boat_name = boat_canon.get(boat_key, raw_boat)

        # Truncate the extraction window at the next boat-name mention so that
        # counts from a subsequent boat in the same block can't bleed in.
        next_boat_m = boat_re.search(block, m.end())
        hard_stop = next_boat_m.start() if next_boat_m else None

        # Extract counts from a window anchored to the boat-name mention only.
        boat_result = _extract_boat_counts_from_text(block, boat_name, hard_stop=hard_stop)
        if boat_result is None:
            continue
        tracked = boat_result['tracked']
        other   = boat_result['other']
        window  = boat_result['text']

        # Unknowns: re-scan the same window for logging continuity.
        _, _, unknowns = _extract_pairs(window)
        for sp_raw, cnt in unknowns:
            log.info('unknown species [%s / %s]: "%s" ×%d — add to parse._EXTENDED_ALIASES if real',
                     src.name, boat_name, sp_raw, cnt)

        tl_bucket, tl_days, tl_raw = _trip_length_from_prose(window)
        if tl_bucket is None and boat_key in BOAT_TRIP_LENGTH_DEFAULTS:
            tl_bucket, tl_days, tl_raw = BOAT_TRIP_LENGTH_DEFAULTS[boat_key]
        status         = classify_report_status(block)
        is_preliminary = 1 if status == 'preliminary' else 0

        # ── Fill: boat is in today's structured table with no catch yet ──────
        existing = structured.get(boat_key)
        if existing is not None:
            if (existing.get('trophy_count', 0) == 0
                    and existing.get('source') == 'fish_count_page'):
                for sp in P.TRACKED_SPECIES:
                    existing[sp.lower()] = tracked.get(sp, 0)
                metrics = P.trophy_metrics(
                    tracked,
                    max(existing['anglers'], 1),
                    existing['trip_length_days'],
                )
                existing['trophy_count']               = metrics.trophy_count
                existing['trophy_per_angler']          = metrics.trophy_per_angler
                existing['trophy_per_angler_per_day']  = metrics.trophy_per_angler_per_day
                existing['full_catch']                 = P.build_full_catch(tracked, other)
                existing['source']                     = 'text_fallback'
                existing['is_preliminary']             = is_preliminary
                existing['written_text']               = block[:500]
                existing['reported_at']                = scraped_at
                existing.setdefault('_unknowns', []).extend(unknowns)
                log.info('text_fallback fill [%s] %s — %s', src.name, boat_name, block[:80])
            continue   # whether filled or not, don't emit a new-trip record

        # ── New: boat not in today's structured trips ─────────────────────────
        if boat_key in seen_new:
            continue
        seen_new.add(boat_key)

        if tl_bucket is None:
            tl_bucket, tl_days, tl_raw = 'Full Day', 0.75, 'Full Day'

        col_counts, other_fish, _ = P.extract_extended_species(other)
        trophy_total = sum(tracked.get(sp, 0) for sp in P.TROPHY_SPECIES)
        moon = moon_info(datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))

        new_trips.append({
            'date':                      today.isoformat(),
            'boat':                      boat_name,
            'landing':                   src.name,
            'trip_type_raw':             tl_raw,
            'trip_length':               tl_bucket,
            'trip_length_days':          tl_days,
            'anglers':                   0,            # unknown — excluded from TPA
            'bluefin':                   tracked.get('Bluefin',    0),
            'yellowfin':                 tracked.get('Yellowfin',  0),
            'yellowtail':                tracked.get('Yellowtail', 0),
            'dorado':                    tracked.get('Dorado',     0),
            'skipjack':                  tracked.get('Skipjack',   0),
            'bigeye':                    tracked.get('Bigeye',     0),
            'albacore':                  tracked.get('Albacore',   0),
            'trophy_count':              trophy_total,
            'trophy_per_angler':         0.0,
            'trophy_per_angler_per_day': 0.0,
            'other_species_json':        json.dumps({k: v for k, v in other.items() if v}),
            'moon_phase':                moon.phase,
            'moon_illum':                moon.illum,
            'days_from_new':             moon.days_from_new,
            'days_from_full':            moon.days_from_full,
            'scraped_at':                scraped_at,
            'source_url':                '',
            **col_counts,
            'other_fish':                other_fish,
            'is_half_day':               1 if tl_days < P.MIN_TRIP_DAYS else 0,
            'region':                    src.region,
            'full_catch':                P.build_full_catch(tracked, other),
            'source':                    'text_fallback',
            'is_preliminary':            1,            # always; anglers unknown until structured row arrives
            'written_text':              block[:500],
            'reported_at':               scraped_at,
            '_unknowns':                 unknowns,
        })
        log.info('text_fallback new [%s] %s trip=%s status=%s — %s',
                 src.name, boat_name, tl_bucket, status, block[:80])

    return new_trips


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
