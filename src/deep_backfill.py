"""Recover fish counts from the fishreports network's per-date archives.

Two archive sites share one HTML layout and keep every day back to ~2010:

    https://www.sandiegofishreports.com/dock_totals/boats.php?date=YYYY-MM-DD
        H&M, Fisherman's, Seaforth, Point Loma, Oceanside Sea Center
    https://www.socalfishreports.com/dock_totals/boats.php?date=YYYY-MM-DD
        the OC / LA / Ventura landings

Each row is ``<td><b>Boat</b> <a href="/landings/x.php">Landing</a></td>
<td>N Anglers <br> Trip Type</td> <td>fish counts</td>``. These are the same
dock totals the landing pages publish (same backend), so rows are tagged
``source='fish_count_page'`` and keep the archive URL in ``source_url``.

Two entry points:

* ``recover_range(conn, start, end)`` — gap filler. Inserts an archive row only
  when no structured row exists for that (date, boat, landing), so it never
  overwrites or duplicates what the live scrape already captured. Used by the
  daily run as a rolling window and by ``scripts/recover_gaps.py``.
* ``run_deep_backfill(...)`` — the original walk-backwards historical sweep.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from . import db
from . import parse as P
from .moon import moon_info
from .scrape import SOURCES, UA

log = logging.getLogger(__name__)

SDFR_URL = "https://www.sandiegofishreports.com/dock_totals/boats.php"
SOCAL_URL = "https://www.socalfishreports.com/dock_totals/boats.php"
ARCHIVES: tuple[tuple[str, str], ...] = (
    ("san_diego", SDFR_URL),
    ("oc_la", SOCAL_URL),
)

# Kept for backwards compatibility with run_deep_backfill callers.
APPROVED_LANDINGS: tuple[str, ...] = (
    "H&M Landing",
    "Fisherman's Landing",
    "Point Loma Sportfishing",
    "Seaforth Sportfishing",
)

_ANGLERS_RE = re.compile(r"(\d[\d,]*)\s*Anglers", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


@dataclass(frozen=True)
class _Landing:
    name: str
    region: str


def _landing_index() -> tuple[dict[str, _Landing], dict[str, _Landing]]:
    """(by normalized name, by /landings/<slug>.php basename) for every source."""
    by_name: dict[str, _Landing] = {}
    by_slug: dict[str, _Landing] = {}
    for s in SOURCES:
        ln = _Landing(s.name, s.region)
        by_name[_norm(s.name)] = ln
        m = re.search(r"/landings/([^/?#]+)\.php", s.url)
        if m:
            by_slug[m.group(1).lower()] = ln
    return by_name, by_slug


_BY_NAME, _BY_SLUG = _landing_index()


def _resolve_landing(link_text: str, href: str) -> _Landing | None:
    m = re.search(r"/landings/([^/?#]+)\.php", href or "")
    if m and m.group(1).lower() in _BY_SLUG:
        return _BY_SLUG[m.group(1).lower()]
    return _BY_NAME.get(_norm(link_text))


def _build_trip(*, report_date: str, boat: str, landing: _Landing,
                trip_type_raw: str, anglers: int, fish_text: str,
                source_url: str, scraped_at: str) -> dict | None:
    """Same dict shape src.scrape.parse_page produces (all TRIP_FIELDS)."""
    length_bucket, length_days = P.parse_trip_length(trip_type_raw)
    if length_bucket is None or length_days is None:
        return None
    tracked, other = P.parse_fish_counts(fish_text)
    col_counts, other_fish, unknowns = P.extract_extended_species(other)
    metrics = P.trophy_metrics(tracked, anglers, length_days)
    m = moon_info(datetime.fromisoformat(report_date).replace(tzinfo=timezone.utc))
    return {
        "date": report_date,
        "boat": boat,
        "landing": landing.name,
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
        "moon_phase": m.phase,
        "moon_illum": m.illum,
        "days_from_new": m.days_from_new,
        "days_from_full": m.days_from_full,
        "scraped_at": scraped_at,
        "source_url": source_url,
        **col_counts,
        "other_fish": other_fish,
        "is_half_day": 1 if length_days < P.MIN_TRIP_DAYS else 0,
        "region": landing.region,
        "full_catch": P.build_full_catch(tracked, other),
        "_unknowns": unknowns,
        "source": "fish_count_page",
        "is_preliminary": 0,
        "written_text": None,
        "reported_at": None,
    }


def parse_archive_day(html: str, report_date: str, base_url: str = SDFR_URL,
                      landings: set[str] | None = None) -> list[dict]:
    """Parse one archive ``?date=`` page into trip dicts for db.insert_trips.

    Only rows whose landing maps to a tracked SOURCES landing are kept
    (optionally narrowed further by ``landings``). Half-day rows are kept with
    is_half_day=1, matching the live scraper.
    """
    soup = BeautifulSoup(html, "lxml")
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_url = f"{base_url}?date={report_date}"
    out: list[dict] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        boat_tag = tds[0].find("b")
        link = tds[0].find("a", href=re.compile(r"/landings/"))
        if not boat_tag or not link:
            continue
        boat = boat_tag.get_text(strip=True)
        landing = _resolve_landing(link.get_text(strip=True), link.get("href", ""))
        if not boat or landing is None:
            continue
        if landings is not None and landing.name not in landings:
            continue
        details = tds[1].get_text(" ", strip=True)
        m = _ANGLERS_RE.search(details)
        if not m:
            continue
        anglers = int(m.group(1).replace(",", ""))
        if anglers <= 0:
            continue
        trip_type_raw = _ANGLERS_RE.sub("", details).strip()
        if not trip_type_raw:
            continue
        t = _build_trip(
            report_date=report_date, boat=boat, landing=landing,
            trip_type_raw=trip_type_raw, anglers=anglers,
            fish_text=tds[2].get_text(" ", strip=True),
            source_url=source_url, scraped_at=scraped_at,
        )
        if t is not None:
            out.append(t)
    return out


def parse_sdfr_day(html: str, report_date: str) -> list[dict]:
    """Legacy name: SD archive page, four core landings only."""
    return parse_archive_day(html, report_date, SDFR_URL, set(APPROVED_LANDINGS))


def fetch_archive_day(session: requests.Session, base_url: str, d: date,
                      timeout: float = 30.0, attempts: int = 3) -> str:
    """GET one archive day with retry/backoff on network errors and 5xx."""
    from . import polite
    from .net import get_with_retry
    url = f"{base_url}?date={d.isoformat()}"
    polite.wait_turn(url)
    r = get_with_retry(url, session=session, headers=polite.headers(url, {"User-Agent": UA}),
                       timeout=timeout, attempts=attempts, backoff=30.0)
    if not _looks_like_archive(r.text):
        raise ArchiveBlockedError(f"{base_url}: date page has no boat table (likely a bot check)")
    return r.text


class ArchiveBlockedError(RuntimeError):
    """The archive answered, but not with a dock-totals page (CAPTCHA / block)."""


def _looks_like_archive(html: str) -> bool:
    return "/landings/" in html or "dock_totals" in html


ARCHIVE_SOURCE = "fish-report archive"  # source_blocks key for the date archives


def _is_block(e: Exception) -> bool:
    if isinstance(e, ArchiveBlockedError):
        return True
    resp = getattr(e, "response", None)
    return resp is not None and resp.status_code in (401, 403, 429)


def recover_range(conn, start: date, end: date, *, throttle: float = 0.0,
                  archives: tuple[tuple[str, str], ...] = ARCHIVES,
                  session: requests.Session | None = None) -> dict:
    """Fill missing trips for [start, end] from the date archives.

    A row is inserted only when the DB has no structured row for the same
    (date, lower(boat), landing) with either the same trip_length or the same
    angler count. The angler match catches older rows stored as generic
    "Half Day" where the parser now says "Half Day AM"/"PM". Narrative/text_fallback rows for that key are
    replaced by insert_trips' structured-row purge.

    Returns {"inserted": n, "by_day": {date: {landing: n}}, "errors": [...]}.
    """
    session = session or requests.Session()
    report: dict = {"inserted": 0, "seen": 0, "by_day": {}, "errors": []}
    from . import completeness
    blk = completeness.active_block(conn, ARCHIVE_SOURCE)
    if blk:
        report["blocked"] = f"archive blocked at {blk}; cooling down"
        return report
    d = start
    while d <= end:
        ds = d.isoformat()
        have: set[tuple] = set()
        for r in conn.execute(
            "SELECT boat, landing, trip_length, anglers FROM trips"
            " WHERE date=? AND source='fish_count_page'", (ds,),
        ):
            have.add(("tl", r[0].lower(), r[1], r[2]))
            have.add(("ang", r[0].lower(), r[1], r[3]))
        for region, base in archives:
            try:
                html = fetch_archive_day(session, base, d)
            except Exception as e:  # noqa: BLE001 — report and keep going
                report["errors"].append(f"{ds} {base}: {type(e).__name__}: {e}")
                if _is_block(e):
                    # Owner's rule: a block means stop, never work around it.
                    from . import completeness
                    completeness.record_block(conn, ARCHIVE_SOURCE, f"{base}: {e}")
                    conn.commit()
                    report["blocked"] = f"{type(e).__name__}: {e}"
                    return report
                continue
            trips = parse_archive_day(html, ds, base)
            report["seen"] += len(trips)
            new = [t for t in trips
                   if ("tl", t["boat"].lower(), t["landing"], t["trip_length"]) not in have
                   and ("ang", t["boat"].lower(), t["landing"], t["anglers"]) not in have]
            if new:
                n = db.insert_trips(conn, new)
                report["inserted"] += n
                for t in new:
                    have.add(("tl", t["boat"].lower(), t["landing"], t["trip_length"]))
                    have.add(("ang", t["boat"].lower(), t["landing"], t["anglers"]))
                    day = report["by_day"].setdefault(ds, {})
                    day[t["landing"]] = day.get(t["landing"], 0) + 1
            time.sleep(throttle)
        conn.commit()  # per day, so a concurrent scheduled run is never locked out long
        d += timedelta(days=1)
    return report


def run_deep_backfill(
    db_path: Path,
    *,
    start: date | None = None,
    stop: date = date(2010, 1, 1),
    throttle: float = 0.3,
    max_empty_streak: int = 180,
    commit_every: int = 30,
) -> None:
    """Walk dates backward from `start` (default today) toward `stop` over the
    SD archive, INSERT OR IGNORE for the four core landings. Commits every
    `commit_every` days so a crash mid-run doesn't lose everything scraped."""
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
            try:
                html = fetch_archive_day(session, SDFR_URL, cur, timeout=20)
            except Exception as e:
                log.warning("fetch %s failed: %s", cur, e)
                cur -= timedelta(days=1)
                empty_streak += 1
                time.sleep(throttle)
                continue
            try:
                trips = parse_sdfr_day(html, cur.isoformat())
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
