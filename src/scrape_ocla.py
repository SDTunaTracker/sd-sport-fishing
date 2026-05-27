"""Historical backfill and daily scrape for OC/LA + Oceanside via 976-tuna.com.

976-tuna.com has monthly fish-count pages going back to 2003 at:
  https://www.976-tuna.com/landing/{id}/{slug}/counts?m={month}&y={year}

Page structure:
  <h2>Sun May 24th 2026</h2>           <- date header
  <div class="row card m-2 mb-3">...</div>  <- one trip card per report
  (repeat)

Each card's h5 reads: "The {Boat} with {N} anglers on a {TripType} caught {FishText}."
Some boats run two trips per day; those appear as two sentences in one card.

Usage:
    # Full historical backfill (2015-present):
    python -m src.scrape_ocla --backfill --start-year 2015

    # Scrape just the current month (for cron / daily top-up):
    python -m src.scrape_ocla --today
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import db
from . import parse as P
from .moon import moon_info
from .scrape import UA

log = logging.getLogger(__name__)

BASE = "https://www.976-tuna.com"

# (canonical_name, id, slug, region)
LANDINGS: list[tuple[str, int, str, str]] = [
    ("Oceanside Sea Center",         40, "oceanside-sea-center",                "san_diego"),
    ("22nd Street Landing",          14, "san-pedro-22nd-street-sportfishing",  "oc_la"),
    ("Long Beach Sportfishing",      12, "long-beach-sportfishing",             "oc_la"),
    ("LA Waterfront Sportfishing",   13, "la-waterfront-sportfishing",          "oc_la"),
    ("Marina Del Rey Sportfishing",  16, "marina-del-rey",                      "oc_la"),
    ("Redondo Beach Sportfishing",   15, "redondo-beach-sportfishing",          "oc_la"),
    ("Pierpoint Landing",            10, "pierpoint-landing",                   "oc_la"),
    ("Channel Islands Sportfishing", 18, "channel-islands-sportfishing",        "oc_la"),
    ("Ventura Harbor Sportfishing",  36, "ventura-sportfishing",                "oc_la"),
    ("Newport Landing",               9, "newport-landing",                     "oc_la"),
    ("Davey's Locker",                8, "daveys-locker",                       "oc_la"),
    ("Dana Wharf Sportfishing",       7, "dana-wharf",                          "oc_la"),
]

_LANDING_REGION = {l[0]: l[3] for l in LANDINGS}

# Date header: "Sun May 24th 2026" / "Mon Jan 3rd 2022"
_DATE_RE = re.compile(
    r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+'
    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+'
    r'(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})',
    re.I,
)
_MONTH = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
          'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}


def _parse_date(text: str) -> date | None:
    m = _DATE_RE.search(text or '')
    if not m:
        return None
    mon_str, day_str, yr_str = m.groups()
    mon = _MONTH.get(mon_str[:3].lower())
    if not mon:
        return None
    try:
        return date(int(yr_str), mon, int(day_str))
    except ValueError:
        return None


# Normalize 976-tuna trip-type strings to P.parse_trip_length expectations
def _norm_trip(raw: str) -> str:
    raw = raw.strip()
    subs = [
        (r'\bFull-Day\b',        'Full Day'),
        (r'\b1-Day\s+Overnight\b', 'Overnight'),
        (r'\b(\d+)-Day\b',       r'\1 Day'),
        (r'\b1/2-Day\b',         '1/2 Day'),
        (r'\b3/4-Day\b',         '3/4 Day'),
        (r'\bHalf-Day\b',        '1/2 Day'),
    ]
    for pat, rep in subs:
        raw = re.sub(pat, rep, raw, flags=re.I)
    return raw.strip()


# Matches each "The Boat with N anglers on a TripType caught FishText" sentence.
# Anchored end: stops at ". The " (next trip in same card) or end-of-card.
_TRIP_RE = re.compile(
    r'The\s+(.+?)\s+with\s+(\d+)\s+anglers?\s+on\s+(?:an?\s+)?(.+?)\s+caught\s+(.+?)'
    r'(?=\.\s+The\s+|\Z)',
    re.I | re.S,
)


def parse_page(html: str, landing: str, source_url: str) -> list[dict]:
    """Return trip dicts from one 976-tuna monthly page for `landing`."""
    soup = BeautifulSoup(html, 'lxml')
    scraped_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    region = _LANDING_REGION.get(landing, 'oc_la')
    out: list[dict] = []
    current_date: date | None = None

    # Walk h2 (date headers) and card divs in document order.
    for el in soup.find_all(lambda tag: (
        tag.name == 'h2' or
        (tag.name == 'div' and
         {'row', 'card', 'm-2', 'mb-3'}.issubset(set(tag.get('class', []))))
    )):
        if el.name == 'h2':
            d = _parse_date(el.get_text(strip=True))
            if d:
                current_date = d
            continue

        if current_date is None:
            continue

        # Collapse whitespace; strip trailing news/audio sections.
        card_text = ' '.join(el.get_text(' ').split())
        card_text = re.split(r'\s+(?:News|Audio)\s+Reports?\s+', card_text, flags=re.I)[0]

        for m in _TRIP_RE.finditer(card_text):
            boat_raw, anglers_raw, trip_raw, fish_raw = m.groups()
            boat = boat_raw.strip()
            anglers = int(anglers_raw)
            trip_type_raw = _norm_trip(trip_raw.strip())
            fish_text = fish_raw.strip().rstrip('.,')

            length_bucket, length_days = P.parse_trip_length(trip_type_raw)
            if length_bucket is None or length_days is None:
                log.debug("skip %r trip=%r on %s", boat, trip_type_raw, current_date)
                continue

            tracked, other = P.parse_fish_counts(fish_text)
            col_counts, other_fish, unknowns = P.extract_extended_species(other)
            is_half_day = 1 if length_days < P.MIN_TRIP_DAYS else 0
            metrics = P.trophy_metrics(tracked, anglers, length_days)
            dt = datetime.combine(current_date, datetime.min.time(), tzinfo=timezone.utc)
            moon = moon_info(dt)

            out.append({
                "date": current_date.isoformat(),
                "boat": boat,
                "landing": landing,
                "trip_type_raw": trip_type_raw,
                "trip_length": length_bucket,
                "trip_length_days": length_days,
                "anglers": anglers,
                "bluefin":    tracked["Bluefin"],
                "yellowfin":  tracked["Yellowfin"],
                "yellowtail": tracked["Yellowtail"],
                "dorado":     tracked["Dorado"],
                "skipjack":   tracked["Skipjack"],
                "bigeye":     tracked["Bigeye"],
                "albacore":   tracked["Albacore"],
                "trophy_count": metrics.trophy_count,
                "trophy_per_angler": metrics.trophy_per_angler,
                "trophy_per_angler_per_day": metrics.trophy_per_angler_per_day,
                "other_species_json": json.dumps(other),
                "moon_phase": moon.phase,
                "moon_illum": moon.illum,
                "days_from_new": moon.days_from_new,
                "days_from_full": moon.days_from_full,
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


def scrape_landing_month(
    name: str, landing_id: int, slug: str,
    year: int, month: int,
    session: requests.Session,
) -> tuple[list[dict], str | None]:
    """Fetch and parse one month for one landing. Returns (trips, error_or_None)."""
    url = f"{BASE}/landing/{landing_id}/{slug}/counts?m={month}&y={year}"
    try:
        r = session.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=25)
        r.raise_for_status()
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    trips = parse_page(r.text, name, url)
    return trips, None


def _sb_wait_stable(sb, max_wait: int = 15) -> str:
    """Wait for page to load then return HTML.

    Two exit conditions:
    1. Date header found in HTML — content is ready, return immediately.
    2. Page is small (<10KB) and stable for 3s — genuinely empty month.
    Falls back to whatever is in the DOM after max_wait seconds.
    """
    prev_len = 0
    small_stable = 0
    for _ in range(max_wait):
        html = sb.execute_script("return document.documentElement.outerHTML")
        # Fast path: real trip data has day-of-week date headers
        if _DATE_RE.search(html):
            return html
        curr_len = len(html)
        # Small stable page = Livewire loaded but found no data for this month
        if 0 < curr_len < 10_000 and curr_len == prev_len:
            small_stable += 1
            if small_stable >= 3:
                return html
        else:
            small_stable = 0
        prev_len = curr_len
        time.sleep(1)
    return sb.execute_script("return document.documentElement.outerHTML")


def _backfill_loop(
    db_path: Path,
    targets: list,
    start_year: int,
    end_year: int,
    delay: float,
    fetch_fn,
) -> None:
    grand_total = 0
    for name, lid, slug, _region in targets:
        print(f"\n{'='*60}")
        print(f"Landing: {name}  (id={lid})")
        landing_total = 0
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                today = date.today()
                if year > today.year or (year == today.year and month > today.month):
                    continue
                url = f"{BASE}/landing/{lid}/{slug}/counts?m={month}&y={year}"
                try:
                    html = fetch_fn(url)
                except Exception as e:
                    log.warning("  %d-%02d  error: %s", year, month, e)
                    time.sleep(delay)
                    continue
                trips = parse_page(html, name, url)
                if trips:
                    with db.connect(db_path) as conn:
                        inserted = db.insert_trips(conn, trips)
                    landing_total += inserted
                    print(f"  {year}-{month:02d}  found={len(trips):3d}  inserted={inserted:3d}")
                else:
                    print(f"  {year}-{month:02d}  (no data)")
                time.sleep(delay)
        print(f"  -> {name}: {landing_total} rows inserted total")
        grand_total += landing_total
    print(f"\nBackfill complete — {grand_total} total new rows inserted.")


def run_backfill(
    db_path: Path,
    target_names: list[str] | None = None,
    start_year: int = 2015,
    end_year: int | None = None,
    delay: float = 1.0,
    use_selenium: bool = False,
) -> None:
    """Scrape 976-tuna.com month-by-month for each landing and insert into DB.

    Pass use_selenium=True to use seleniumbase UC mode (bypasses Cloudflare Turnstile).
    A Chrome window will open and stay open for the duration of the backfill.
    """
    if end_year is None:
        end_year = date.today().year

    targets = [(n, i, s, r) for (n, i, s, r) in LANDINGS
               if target_names is None or n in target_names]
    if not targets:
        print("No matching landings.")
        return

    if use_selenium:
        try:
            from seleniumbase import SB
        except ImportError:
            print("seleniumbase not installed. Run: pip install seleniumbase")
            return

        print("Opening Chrome browser (Cloudflare UC bypass)...")
        print("Keep the Chrome window open until backfill completes.\n")

        sb_ctx = SB(uc=True, headless=False, test=False)
        sb = sb_ctx.__enter__()

        def fetch_fn(url: str) -> str:
            sb.open(url)
            return _sb_wait_stable(sb)

        try:
            _backfill_loop(db_path, targets, start_year, end_year, delay, fetch_fn)
        finally:
            sb_ctx.__exit__(None, None, None)
    else:
        session = requests.Session()

        def fetch_fn(url: str) -> str:
            r = session.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=25)
            r.raise_for_status()
            return r.text

        _backfill_loop(db_path, targets, start_year, end_year, delay, fetch_fn)


def run_today(db_path: Path, delay: float = 1.0) -> None:
    """Scrape the current month for all landings — used as a daily top-up."""
    today = date.today()
    session = requests.Session()
    total = 0
    for name, lid, slug, _region in LANDINGS:
        trips, err = scrape_landing_month(name, lid, slug, today.year, today.month, session)
        if err:
            print(f"  {name}: ERROR {err}")
        elif trips:
            with db.connect(db_path) as conn:
                inserted = db.insert_trips(conn, trips)
            total += inserted
            print(f"  {name}: found={len(trips)}  inserted={inserted}")
        else:
            print(f"  {name}: (no data)")
        time.sleep(delay)
    print(f"Today run complete — {total} rows inserted.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="976-tuna.com scraper for OC/LA landings")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--backfill", action="store_true", help="Full historical backfill")
    mode.add_argument("--today", action="store_true", help="Scrape current month only")
    parser.add_argument("--landing", action="append", metavar="NAME",
                        help="Restrict to specific landing(s); repeat for multiple")
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year",   type=int, default=None)
    parser.add_argument("--delay",      type=float, default=1.0, help="Seconds between requests")
    parser.add_argument("--db",         default="tracker.db")
    parser.add_argument("--selenium",   action="store_true",
                        help="Use seleniumbase UC mode to bypass Cloudflare Turnstile (backfill only)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.backfill:
        run_backfill(db_path, target_names=args.landing,
                     start_year=args.start_year, end_year=args.end_year,
                     delay=args.delay, use_selenium=args.selenium)
    else:
        run_today(db_path, delay=args.delay)
