"""Hourly scrape health check: per-run assertions, coverage cross-check, alerting.

Called at the end of each main.py run() — after export() so data.js freshness
can be verified.  Exits non-zero (via the returned exit code) on any failure.

Phase 1 — per-run assertions
  · All 5 SD landings have a scrape_log row for THIS run with status='ok'
  · trips_seen is sane (≥20% of 14-day median, when median>3 and after 08:00)
  · data.js mtime is newer than run_start_iso

Phase 2 — coverage cross-check
  · Re-fetch each SD landing's fish-count page; extract table boat names
  · Scan main_url/news_url narrative pages for boat names with fish-count text
  · Diff against DB trips for today → log CAPTURE GAPss (page-visible, not in DB)

Phase 3 — alerting
  · GitHub Issues API when GH_TOKEN env var is set
  · Fallback: append to logs/health_alerts.log
  · Write logs/health.json for the site frontend to read
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
HEALTH_JSON = ROOT / "logs" / "health.json"
ALERT_LOG   = ROOT / "logs" / "health_alerts.log"

# SD-only sources — the five we assert on every run.
SD_LANDING_NAMES = frozenset({
    "H&M Landing",
    "Fisherman's Landing",
    "Seaforth Sportfishing",
    "Point Loma Sportfishing",
    "Oceanside Sea Center",
})

# After this hour (local) we start expecting today's data to be present.
_REPORTING_HOUR_THRESHOLD = 8

# trips_seen must be at least this fraction of the 14-day median to pass the
# sanity check (only applied when median > 3 and it's past reporting hours).
_SEEN_RATIO_MIN = 0.20

# GitHub Issues API endpoint — set GH_REPO=owner/repo to enable.
_GH_API = "https://api.github.com/repos/{repo}/issues"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

# Fish-count keywords that indicate a text block mentions a real catch report.
_FISH_KEYWORDS = re.compile(
    r'\b(\d+)\s+(bluefin|yellowfin|yellowtail|dorado|albacore|skipjack|bigeye|tuna|limits?)\b',
    re.I,
)

# Patterns that mean a "boat name" is actually a species or boilerplate.
_BOAT_BLACKLIST = frozenset({
    "bluefin", "yellowfin", "yellowtail", "dorado", "skipjack",
    "albacore", "bigeye", "tuna", "limits",
})

# Date-like pattern: matches "5/30/2026", "06/07/2026", "Date", etc.
_DATE_RE = re.compile(r'^\d{1,2}/\d{1,2}/\d{4}$|^Date$', re.I)
# Summary rows: "N Boats", "Dock Total", etc.
_SUMMARY_ROW_RE = re.compile(r'^\d+\s+Boats?$|^Dock\s+Total$|^Boats?$|^Anglers?$|^Trips?$', re.I)


# ---------------------------------------------------------------------------
# Phase 1 — per-run assertions
# ---------------------------------------------------------------------------

def _check_scrape_log(
    conn: sqlite3.Connection,
    run_start_iso: str,
) -> list[dict]:
    """Return a failure dict for each SD landing missing an ok row since run_start."""
    failures: list[dict] = []
    today = date.today().isoformat()
    for name in sorted(SD_LANDING_NAMES):
        row = conn.execute(
            """
            SELECT id, trips_seen, trips_kept, error
            FROM scrape_log
            WHERE landing = ?
              AND status = 'ok'
              AND started_at >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (name, run_start_iso),
        ).fetchone()
        if row is None:
            # Also check if there's an error row (vs just missing entirely)
            err_row = conn.execute(
                """
                SELECT error FROM scrape_log
                WHERE landing = ? AND started_at >= ?
                ORDER BY id DESC LIMIT 1
                """,
                (name, run_start_iso),
            ).fetchone()
            detail = err_row["error"] if err_row else "no scrape_log row found"
            failures.append({
                "type": "missing_ok_scrape",
                "landing": name,
                "detail": detail,
            })
    return failures


def _check_trips_seen(
    conn: sqlite3.Connection,
    run_start_iso: str,
) -> list[dict]:
    """Warn if any landing's trips_seen is far below its 14-day median."""
    failures: list[dict] = []
    _hour = datetime.now().hour
    if _hour < _REPORTING_HOUR_THRESHOLD:
        return []  # Too early — landings may not have posted yet

    for name in sorted(SD_LANDING_NAMES):
        cur_row = conn.execute(
            """
            SELECT trips_seen FROM scrape_log
            WHERE landing = ? AND status = 'ok' AND started_at >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (name, run_start_iso),
        ).fetchone()
        if cur_row is None:
            continue  # Already caught by _check_scrape_log

        seen = cur_row["trips_seen"] or 0

        # 14-day median from previous ok runs (exclude today to avoid circularity).
        hist = conn.execute(
            """
            SELECT trips_seen FROM scrape_log
            WHERE landing = ? AND status = 'ok'
              AND started_at < ?
            ORDER BY started_at DESC LIMIT 14
            """,
            (name, run_start_iso),
        ).fetchall()
        if not hist:
            continue
        vals = sorted(r["trips_seen"] or 0 for r in hist)
        median = vals[len(vals) // 2]
        if median <= 3:
            continue  # Insufficient baseline; skip this landing

        if seen < median * _SEEN_RATIO_MIN:
            failures.append({
                "type": "low_trips_seen",
                "landing": name,
                "seen": seen,
                "median_14d": median,
                "detail": f"seen={seen} is <{_SEEN_RATIO_MIN:.0%} of 14-day median {median}",
            })
    return failures


def _check_data_js_fresh(data_js_path: Path, run_start_iso: str) -> list[dict]:
    """Check that data.js was updated after this run started."""
    if not data_js_path.exists():
        return [{"type": "data_js_missing", "detail": str(data_js_path)}]
    mtime = datetime.fromtimestamp(data_js_path.stat().st_mtime, tz=timezone.utc)
    run_start_dt = datetime.fromisoformat(run_start_iso)
    if run_start_dt.tzinfo is None:
        run_start_dt = run_start_dt.replace(tzinfo=timezone.utc)
    if mtime < run_start_dt:
        return [{
            "type": "data_js_stale",
            "detail": f"data.js mtime {mtime.isoformat()} < run_start {run_start_iso}",
        }]
    return []


# ---------------------------------------------------------------------------
# Phase 2 — coverage cross-check
# ---------------------------------------------------------------------------

def _fetch(url: str, timeout: float = 20.0) -> str | None:
    """Fetch a URL, returning None on error."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        log.debug("health fetch failed %s: %s", url, exc)
        return None


def _table_boats(html: str) -> set[str]:
    """Extract boat names from a fish-count HTML table (structured rows)."""
    soup = BeautifulSoup(html, "lxml")
    names: set[str] = set()
    for table in soup.find_all("table"):
        # Identify fish-count tables by their header row.
        header_cells = [
            c.get_text(strip=True).lower()
            for tr in table.find_all("tr")[:2]
            for c in tr.find_all(["td", "th"])
        ]
        if "boat" not in header_cells and not any("fish count" in h for h in header_cells):
            continue
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            boat = cells[0].strip()
            if not boat:
                continue
            if boat.lower() in ("boat", ""):
                continue
            if _DATE_RE.match(boat) or _SUMMARY_ROW_RE.match(boat):
                continue
            if boat.lower() not in _BOAT_BLACKLIST:
                names.add(boat)
    return names


def _narrative_boats(html: str, all_boat_names: list[str]) -> dict[str, str]:
    """Find known boat names in narrative pages that also have fish-count text nearby.

    Returns {boat_name: text_snippet}.
    """
    if not all_boat_names:
        return {}

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    boats_sorted = sorted(
        (b for b in all_boat_names if b.lower() not in _BOAT_BLACKLIST),
        key=len, reverse=True,
    )
    boat_re = re.compile(
        r'(?:The\s+)?(?P<boat>' + '|'.join(re.escape(b) for b in boats_sorted) + r')\b',
        re.I,
    )

    found: dict[str, str] = {}
    for m in boat_re.finditer(text):
        boat = m.group("boat")
        window = text[max(0, m.start() - 60): m.end() + 350]
        if _FISH_KEYWORDS.search(window):
            if boat not in found:
                found[boat] = window[:200].strip()
    return found


def _db_boats_today(conn: sqlite3.Connection, today_iso: str) -> set[str]:
    """All boat names in DB trips for today."""
    rows = conn.execute(
        "SELECT DISTINCT boat FROM trips WHERE date = ?", (today_iso,)
    ).fetchall()
    return {r["boat"] for r in rows}


def _all_known_boats(conn: sqlite3.Connection) -> list[str]:
    """All historically-seen boat names from DB."""
    rows = conn.execute("SELECT DISTINCT boat FROM trips").fetchall()
    return [r["boat"] for r in rows]


def _resolve_boat(raw: str, known: set[str]) -> str | None:
    """Return the canonical boat name if raw (or a significant word of it) is in known."""
    if raw in known:
        return raw
    raw_lower = raw.lower()
    for k in known:
        if k.lower() == raw_lower:
            return k
    # Partial match: significant first word (≥5 chars)
    first = next((w for w in raw.split() if len(w) >= 5), "")
    if first:
        for k in known:
            if first.lower() in k.lower():
                return k
    return None


def _coverage_gaps(
    conn: sqlite3.Connection,
    sd_sources,   # Iterable[LandingSource]
) -> list[dict]:
    """Phase 2: fetch pages, compare against DB, return gap records."""
    today_iso = date.today().isoformat()
    db_boats  = _db_boats_today(conn, today_iso)
    all_known = _all_known_boats(conn)
    known_set = set(all_known)

    gaps: list[dict] = []
    for src in sd_sources:
        # Structured table boats from the fish-count page.
        html = _fetch(src.url)
        page_boats: set[str] = set()
        if html:
            page_boats |= _table_boats(html)

        # Narrative boats from main/news pages.
        narr_boats: dict[str, str] = {}
        for url in [src.main_url, src.news_url]:
            if not url:
                continue
            narr_html = _fetch(url)
            if narr_html:
                found = _narrative_boats(narr_html, all_known)
                for boat, snippet in found.items():
                    narr_boats.setdefault(boat, snippet)

        # Combine: anything page-visible but not in today's DB.
        all_page: dict[str, str] = {}  # boat -> snippet/source
        for b in page_boats:
            all_page[b] = f"table row on {src.url}"
        for b, snippet in narr_boats.items():
            if b not in all_page:
                all_page[b] = snippet

        for raw_boat, snippet in all_page.items():
            canonical = _resolve_boat(raw_boat, known_set)
            check_name = canonical or raw_boat
            if check_name not in db_boats:
                # Also verify it's actually a known boat or looks like a boat name.
                if canonical is None and raw_boat.lower() in _BOAT_BLACKLIST:
                    continue
                gaps.append({
                    "type": "capture_gap",
                    "landing": src.name,
                    "boat_raw": raw_boat,
                    "boat_canonical": canonical,
                    "snippet": snippet[:120],
                    "detail": f"Boat '{check_name}' visible on page but missing from today's DB trips",
                })

    return gaps


# ---------------------------------------------------------------------------
# Phase 3 — alerting + health record
# ---------------------------------------------------------------------------

def _open_github_issue(title: str, body: str) -> bool:
    """File a GitHub issue; returns True on success."""
    token = os.environ.get("GH_TOKEN", "")
    repo  = os.environ.get("GH_REPO", "")
    if not token or not repo:
        return False
    url = _GH_API.format(repo=repo)
    try:
        r = requests.post(
            url,
            json={"title": title, "body": body, "labels": ["scrape-health"]},
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        )
        r.raise_for_status()
        log.info("GitHub issue filed: %s", r.json().get("html_url"))
        return True
    except Exception as exc:
        log.warning("GitHub issue failed: %s", exc)
        return False


def _alert(failures: list[dict], gaps: list[dict]) -> None:
    """Send alert via GitHub Issues or fallback log."""
    if not failures and not gaps:
        return

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = [f"Scrape health check failed at {now_iso}", ""]

    if failures:
        lines.append("## Assertion failures")
        for f in failures:
            landing = f.get('landing', 'system')
            lines.append(f"- [{landing}] {f['type']}: {f.get('detail', '')}")
        lines.append("")

    if gaps:
        lines.append("## Coverage gaps (boats on page, missing from DB)")
        for g in gaps:
            name = g["boat_canonical"] or g["boat_raw"]
            lines.append(f"- [{g['landing']}] {name}: {g.get('snippet', '')[:80]}")
        lines.append("")

    body = "\n".join(lines)
    title = (
        f"Scrape health: {len(failures)} assertion(s) failed, "
        f"{len(gaps)} coverage gap(s) — {now_iso[:10]}"
    )

    if not _open_github_issue(title, body):
        ALERT_LOG.parent.mkdir(exist_ok=True)
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n{title}\n{body}\n")
        log.warning("Health alert written to %s", ALERT_LOG)


def _write_health_json(
    failures: list[dict],
    gaps: list[dict],
    run_start_iso: str,
    checked_at: str,
) -> None:
    """Write logs/health.json for the frontend to read via window.SD.HEALTH."""
    HEALTH_JSON.parent.mkdir(exist_ok=True)
    record: dict[str, Any] = {
        "checkedAt": checked_at,
        "runStart": run_start_iso,
        "ok": not failures and not gaps,
        "failures": failures,
        "coverageGaps": gaps,
        "summary": (
            "ok" if not failures and not gaps
            else f"{len(failures)} failure(s), {len(gaps)} gap(s)"
        ),
    }
    HEALTH_JSON.write_text(json.dumps(record, indent=2), encoding="utf-8")
    log.info("health.json written: ok=%s", record["ok"])


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_health_check(
    conn: sqlite3.Connection,
    run_start_iso: str,
    sd_sources,     # Iterable[LandingSource] — only SD ones; caller filters
    data_js_path: Path,
) -> int:
    """Run all three phases.  Returns 0 (ok) or 1 (failures/gaps found)."""
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log.info("Health check started (run_start=%s)", run_start_iso)

    # Phase 1
    failures: list[dict] = []
    failures += _check_scrape_log(conn, run_start_iso)
    failures += _check_trips_seen(conn, run_start_iso)
    failures += _check_data_js_fresh(data_js_path, run_start_iso)

    for f in failures:
        log.warning("HEALTH FAILURE: %s", f)

    # Phase 2
    gaps: list[dict] = []
    try:
        gaps = _coverage_gaps(conn, sd_sources)
        for g in gaps:
            log.warning("CAPTURE GAP [%s] %s — %s",
                        g["landing"], g.get("boat_canonical") or g["boat_raw"],
                        g.get("snippet", "")[:80])
    except Exception as exc:
        log.warning("Coverage cross-check failed (non-fatal): %s", exc)
        failures.append({"type": "coverage_check_error", "landing": "all", "detail": str(exc)})

    # Phase 3
    _write_health_json(failures, gaps, run_start_iso, checked_at)
    _alert(failures, gaps)

    if failures or gaps:
        log.warning(
            "Health check FAILED: %d assertion failure(s), %d coverage gap(s)",
            len(failures), len(gaps),
        )
        return 1

    log.info("Health check PASSED")
    return 0
