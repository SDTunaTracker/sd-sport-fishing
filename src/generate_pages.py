"""Generate pre-rendered static HTML pages for boats, landings, and species.

Each generated page:
  - Has SEO meta tags baked into the HTML (no JS needed by crawlers)
  - Contains pre-rendered stats/content in #seo-static. It is hidden while the
    SPA loads, and shown again if the SPA can't start. Googlebot is the main
    case: it fetches only the first 2 MB of each resource, so data.js (~21 MB)
    is truncated and window.SD is never defined.
  - Loads the full SPA so users get the interactive experience
  - Is written to web/sd/{boat,landing,species}/<name>/index.html so CF Pages
    serves it directly at the trailing-slash URL, which is the canonical form
    (the no-slash form 308-redirects to it)

generate_all_pages() returns the list of pages written. export.py builds
sitemap.xml from that list, so the sitemap and the pages can't drift apart.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote as url_quote

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Brand + domain: keep in sync with web/seo.js and web/index.html.
# See docs/seo/DOMAIN_MIGRATION.md before changing SITE_URL.
SITE_URL = "https://thetunatracker.com"
SITE_NAME = "Tunatracker"

# Pages backed by fewer trips than this are still generated (the app links to
# them) but are marked noindex and left out of the sitemap as thin content.
MIN_TRIPS_INDEX = 5
SPECIES_RECENT_DAYS = 14
TODAY_DAYS = 3        # report dates shown on /sd/today (counts post through the day)

SD_LANDINGS: dict[str, str] = {
    "H&M Landing":            "hm-landing",
    "Fisherman's Landing":    "fishermans-landing",
    "Seaforth Sportfishing":  "seaforth",
    "Point Loma Sportfishing":"point-loma",
    "Oceanside Sea Center":   "oceanside",
}
# SQL filter for San Diego landings. Only boats whose trips are at these landings
# get a generated page, so every boat link on a generated page stays inside it.
_SD_IN = "landing IN (" + ",".join("'" + l.replace("'", "''") + "'" for l in SD_LANDINGS) + ")"

TROPHY_SPECIES: list[tuple[str, str, str]] = [
    # (db_column, display_name, url_slug)
    ("bluefin",    "Bluefin Tuna", "bluefin-tuna"),
    ("yellowfin",  "Yellowfin Tuna", "yellowfin-tuna"),
    ("yellowtail", "Yellowtail", "yellowtail"),
    ("dorado",     "Dorado", "dorado"),
]

_MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Inserted right after the data.js <script>. If data.js didn't load or parse,
# keep the prerendered content visible and hide #root, so the app's error box
# doesn't replace it. Normal visitors never hit this branch.
_SD_FALLBACK_SCRIPT = (
    "\n<script>if(!window.SD){var s=document.getElementById('seo-static'),"
    "r=document.getElementById('root');if(s)s.style.display='';"
    "if(r)r.style.display='none';}</script>"
)


def _safe_dir(name: str) -> str:
    """Remove chars that are problematic as directory names on any OS."""
    bad = r'/\:*?"<>|'
    return "".join(c for c in name if c not in bad)


def page_url(kind: str, name: str) -> str:
    """Site-relative canonical URL of a generated page (always a trailing slash)."""
    return f"/sd/{kind}/{url_quote(_safe_dir(name))}/"


# ── Index.html parser ─────────────────────────────────────────────────────────

def _parse_index(index_html: str) -> dict:
    """Extract shared parts from index.html for inclusion in generated pages."""
    # styles.css version
    styles_m = re.search(r'href="styles\.css\?v=([^"]+)"', index_html)
    styles_ver = styles_m.group(1) if styles_m else "1"
    # design-system.css loads after styles.css and overrides it; the generated
    # pages need it too or they render in the old palette until the app mounts.
    ds_m = re.search(r'href="design-system\.css\?v=([^"]+)"', index_html)
    ds_ver = ds_m.group(1) if ds_m else "1"

    # Clerk SDK script tag from head
    clerk_m = re.search(r'<script\s[^>]*clerk[^>]*(?:/>|>.*?</script>)', index_html, re.S | re.I)
    clerk_sdk = clerk_m.group(0) if clerk_m else ""

    # VESSEL_WORKER_URL inline script
    vessel_m = re.search(r'<script>window\.VESSEL_WORKER_URL[^<]+</script>', index_html)
    vessel_script = vessel_m.group(0) if vessel_m else "<script>window.VESSEL_WORKER_URL = '';</script>"

    # Google Analytics tag and web fonts from <head>. Without these, visits that
    # land on a generated page aren't counted and the fallback text renders in
    # system fonts.
    gtag_m = re.search(
        r'<script async src="https://www\.googletagmanager\.com/gtag/js[^"]*"></script>\s*'
        r'<script>.*?</script>', index_html, re.S)
    gtag = gtag_m.group(0) if gtag_m else ""
    if not gtag:
        log.warning("generate_pages: Google tag not found in index.html")
    fonts = "\n".join(re.findall(r'<link [^>]*href="https://fonts\.(?:googleapis|gstatic)\.com[^>]*>',
                                 index_html))

    # All script tags from React CDN onward (to end of body)
    react_start = index_html.find('<script src="https://unpkg.com/react@')
    body_end = index_html.rfind('</body>')
    body_scripts = index_html[react_start:body_end].strip() if react_start != -1 else ""
    body_scripts, n = re.subn(
        r'(<script src="data\.js[^"]*"></script>)',
        lambda m: m.group(1) + _SD_FALLBACK_SCRIPT,
        body_scripts, count=1,
    )
    if not n:
        log.warning("generate_pages: data.js <script> not found; no-JS fallback not injected")

    return dict(
        styles_ver=styles_ver,
        ds_ver=ds_ver,
        clerk_sdk=clerk_sdk,
        vessel_script=vessel_script,
        body_scripts=body_scripts,
        gtag=gtag,
        fonts=fonts,
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

def _boat_stats(conn: sqlite3.Connection, boat: str) -> dict | None:
    """Return stats dict or None if no usable trip data."""
    rows = conn.execute("""
        SELECT trophy_count, trophy_per_angler_per_day,
               bluefin, yellowfin, yellowtail, dorado, date, anglers,
               landing, trip_length, full_catch
        FROM trips WHERE boat = ? AND trophy_count IS NOT NULL
        ORDER BY date DESC, id DESC
    """, (boat,)).fetchall()
    if not rows:
        return None
    total = len(rows)
    wins  = sum(1 for r in rows if (r["trophy_count"] or 0) > 0)
    tpads = [r["trophy_per_angler_per_day"] for r in rows
             if r["trophy_per_angler_per_day"] and r["trophy_per_angler_per_day"] > 0]
    species = {
        "Bluefin":    sum(r["bluefin"]    or 0 for r in rows),
        "Yellowfin":  sum(r["yellowfin"]  or 0 for r in rows),
        "Yellowtail": sum(r["yellowtail"] or 0 for r in rows),
        "Dorado":     sum(r["dorado"]     or 0 for r in rows),
    }
    dates = [r["date"][:4] for r in rows if r["date"]]
    years = sorted(set(dates))
    lengths = Counter(r["trip_length"] for r in rows if r["trip_length"])
    # Best months: mean trophy fish/angler/day over all trips (zeros included)
    # in that calendar month, across all years; only months with >= 5 trips.
    by_month: dict[int, list[float]] = {}
    for r in rows:
        if r["date"] and r["trophy_per_angler_per_day"] is not None:
            by_month.setdefault(int(r["date"][5:7]), []).append(r["trophy_per_angler_per_day"])
    best_months = sorted(
        ((m, sum(v) / len(v), len(v)) for m, v in by_month.items() if len(v) >= 5),
        key=lambda x: -x[1],
    )[:3]
    return dict(
        total=total,
        wins=wins,
        win_rate=round(wins / total * 100, 1),
        avg_tpad=round(sum(tpads) / len(tpads), 2) if tpads else 0,
        species=species,
        first_year=min(years, default=""),
        last_year=max(years, default=""),
        recent=_dedupe_repeats([dict(r) for r in rows[:40]])[:10],
        last_date=rows[0]["date"],
        landing=rows[0]["landing"],   # landing of the most recent trip
        trip_lengths=lengths.most_common(),
        best_months=best_months,
    )


_CATCH_KEY = ("boat", "trip_length", "anglers", "bluefin", "yellowfin", "yellowtail", "dorado")


def _dedupe_repeats(rows: list[dict]) -> list[dict]:
    """Drop rows that repeat the previous kept row's catch a few days earlier.

    Landings often re-post a multi-day trip's count on several consecutive
    dates. Rows are newest first; a row identical on boat, trip length,
    anglers and trophy counts within 4 days of the last kept identical row is
    treated as the same trip. Display only; stats are not affected.
    """
    kept: list[dict] = []
    last_seen: dict[tuple, date] = {}
    for r in rows:
        key = tuple(r.get(k) for k in _CATCH_KEY)
        d = date.fromisoformat(r["date"][:10])
        prev = last_seen.get(key)
        last_seen[key] = d
        if prev is not None and (prev - d).days <= 4 and (r.get("trophy_count") or 0) > 0:
            continue
        kept.append(r)
    return kept


def _landing_boats(all_stats: dict[str, dict], landing: str) -> list[dict]:
    """Return boat stats for a landing: ranked boats first, then small samples.

    A boat belongs to the landing it fished from most recently.
    """
    result = [{"boat": b, **s} for b, s in sorted(all_stats.items()) if s["landing"] == landing]
    result.sort(key=lambda x: (x["total"] < MIN_TRIPS_INDEX, -x["win_rate"], -x["avg_tpad"]))
    return result


def _recent_sd_trips(conn: sqlite3.Connection, days: int, where: str = "1=1") -> tuple[str | None, list[dict]]:
    """SD trips in the `days` days up to the latest SD trip date, newest first.

    Returns (latest_date, rows). Repeated multi-day counts are collapsed.
    """
    last = conn.execute(f"SELECT MAX(date) FROM trips WHERE {_SD_IN}").fetchone()[0]
    if not last:
        return None, []
    start = (date.fromisoformat(last[:10]) - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(f"""
        SELECT date, boat, landing, trip_length, anglers, bluefin, yellowfin, yellowtail,
               dorado, trophy_count, full_catch
        FROM trips WHERE {_SD_IN} AND date>=? AND trophy_count IS NOT NULL AND ({where})
        ORDER BY date DESC, trophy_count DESC, boat
    """, (start,))
    return last[:10], _dedupe_repeats([dict(r) for r in rows])


def _landing_recent(conn: sqlite3.Connection, landing: str, days: int = 7) -> list[dict]:
    """Trips at a landing in the `days` days up to (and including) its latest trip date."""
    last = conn.execute("SELECT MAX(date) FROM trips WHERE landing=?", (landing,)).fetchone()[0]
    if not last:
        return []
    start = (date.fromisoformat(last) - timedelta(days=days - 1)).isoformat()
    return _dedupe_repeats([dict(r) for r in conn.execute("""
        SELECT date, boat, trip_length, anglers, bluefin, yellowfin, yellowtail, dorado,
               trophy_count, full_catch
        FROM trips WHERE landing=? AND date>=? AND trophy_count IS NOT NULL
        ORDER BY date DESC, trophy_count DESC
    """, (landing, start))])


def _species_stats(conn: sqlite3.Connection, col: str) -> dict:
    """Return stats dict for a trophy species column."""
    top = conn.execute(f"""
        SELECT boat, landing, COUNT(*) as trips,
               ROUND(AVG(CASE WHEN trophy_per_angler_per_day>0
                               THEN trophy_per_angler_per_day END), 2) as avg_tpad
        FROM trips
        WHERE {col}>0 AND trophy_per_angler_per_day IS NOT NULL AND {_SD_IN}
        GROUP BY boat, landing
        HAVING trips>=5
        ORDER BY avg_tpad DESC
        LIMIT 10
    """).fetchall()
    cutoff = str(date.today().year - 5)
    monthly = conn.execute(f"""
        SELECT CAST(SUBSTR(date, 6, 2) AS INTEGER) as month,
               ROUND(AVG(trophy_per_angler_per_day), 2) as avg_tpad,
               COUNT(*) as trips
        FROM trips
        WHERE {col}>0 AND date>=? AND trophy_per_angler_per_day>0 AND {_SD_IN}
        GROUP BY month
        ORDER BY month
    """, (cutoff,)).fetchall()
    total_trips = conn.execute(
        f"SELECT COUNT(*) FROM trips WHERE {col}>0 AND {_SD_IN}"
    ).fetchone()[0]
    last_date = conn.execute(f"SELECT MAX(date) FROM trips WHERE {col}>0 AND {_SD_IN}").fetchone()[0]
    _, recent = _recent_sd_trips(conn, SPECIES_RECENT_DAYS, f"{col}>0")
    recent.sort(key=lambda r: (r["date"], r[col] or 0), reverse=True)
    return {
        "top_boats": [dict(r) for r in top],
        "monthly":   [dict(r) for r in monthly],
        "total_trips": total_trips,
        "last_date": last_date,
        "recent": recent,
        "recent_fish": sum(r[col] or 0 for r in recent),
    }


# ── Static-only page template (species, trip lengths) ─────────────────────────
# Mirrors web/privacy/index.html (design-system tokens, Fraunces/Inter/DM Mono,
# header.top brand bar, simple footer). Styling agreed with the UX session.

_STATIC_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600'
    '&family=DM+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,600;9..144,700'
    '&display=swap" rel="stylesheet">\n'
)

_STATIC_CSS = """<style>
  /* Tokens mirror web/design-system.css (cream / pine / orange). */
  :root {
    --bg: #FBFAF6; --surface: #FFFFFF; --ink: #17332C; --ink-2: #2D4A42;
    --muted: #5A6E66; --faint: #8C978F; --line: #EAE6DC; --band: #F4F1E9;
    --pine: #17332C; --accent: #CF6A3C; --accent-ink: #B0542A;
    --focus: 0 0 0 3px rgba(207,106,60,.22);
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; background: var(--bg); color: var(--ink-2);
         font: 16px/1.6 Inter, system-ui, sans-serif; }
  a { color: var(--accent-ink); text-underline-offset: 3px; }
  a:focus-visible { outline: none; box-shadow: var(--focus); border-radius: 4px; }
  .top { background: var(--surface); border-bottom: 1px solid var(--line); }
  .top-inner { max-width: 1120px; margin: 0 auto; padding: 0 16px; height: 64px;
               display: flex; align-items: center; gap: 24px; }
  .brand { display: inline-flex; align-items: center; gap: 8px; font: 700 19px/1 Fraunces, Georgia, serif;
           color: var(--ink); text-decoration: none; flex-shrink: 0; }
  .brand svg { color: #CF6A3C; flex-shrink: 0; display: block; }
  .nav { display: flex; gap: 20px; margin-left: 8px; }
  .nav a { font: 500 14px/1 Inter, sans-serif; color: var(--ink-2); text-decoration: none;
           padding: 22px 0 20px; border-bottom: 2px solid transparent; }
  .nav a:hover { color: var(--ink); }
  .nav a[aria-current] { color: var(--ink); border-bottom-color: var(--accent); }
  .btn { display: inline-flex; align-items: center; justify-content: center; height: 44px;
         padding: 0 18px; border-radius: 10px; font: 600 15px/1 Inter, sans-serif;
         text-decoration: none; white-space: nowrap; }
  .btn-primary { background: var(--pine); color: #fff; }
  .btn-primary:hover { background: #1F4A3F; }
  .btn-secondary { background: var(--surface); color: var(--ink); border: 1px solid var(--line); }
  .top .btn { height: 40px; margin-left: auto; font-size: 14px; }
  main { max-width: 760px; margin: 0 auto; padding: 32px 16px 64px; }
  main nav[aria-label="Breadcrumb"] ol { list-style: none; padding: 0; margin: 0 0 16px; display: flex;
           flex-wrap: wrap; gap: 6px; font: 500 11px/1.4 'DM Mono', ui-monospace, monospace;
           letter-spacing: .1em; text-transform: uppercase; color: var(--faint); }
  main nav[aria-label="Breadcrumb"] li + li::before { content: "›"; margin-right: 6px; }
  main nav[aria-label="Breadcrumb"] a { color: var(--faint); text-decoration: none; }
  main nav[aria-label="Breadcrumb"] a:hover { color: var(--ink); }
  h1 { font: 700 34px/1.1 Fraunces, Georgia, serif; color: var(--ink); margin: 0 0 12px;
       letter-spacing: -.01em; }
  .lede { font-size: 18px; line-height: 1.55; color: var(--ink-2); margin: 0 0 28px; }
  h2 { font: 600 22px/1.25 Fraunces, Georgia, serif; color: var(--ink); margin: 40px 0 10px; }
  h3 { font: 600 16px/1.3 Inter, sans-serif; color: var(--ink); margin: 24px 0 6px; }
  p { margin: 0 0 12px; }
  .tw { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 8px 0 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  .cap { font-size: 14px; line-height: 1.5; color: var(--muted); margin: 6px 0 2px; }
  th { text-align: left; font: 500 10.5px/1.2 'DM Mono', ui-monospace, monospace; letter-spacing: .1em;
       text-transform: uppercase; color: var(--faint); padding: 10px 12px 10px 0;
       border-bottom: 1px solid var(--line); white-space: nowrap; }
  td { padding: 11px 12px 11px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
  th.num, td.num { text-align: right; }
  td.num { font: 400 14px/1.6 'DM Mono', ui-monospace, monospace; color: var(--ink);
           white-space: nowrap; }
  th:last-child, td:last-child { padding-right: 0; }
  td:first-child { white-space: nowrap; color: var(--ink); }
  .cta { background: var(--band); border-radius: 14px; padding: 20px; margin: 40px 0 0; }
  .cta p { font-size: 17px; color: var(--ink); margin: 0 0 14px; }
  .cta-actions { display: flex; flex-wrap: wrap; gap: 10px; }
  footer { border-top: 1px solid var(--line); }
  .foot-inner { max-width: 760px; margin: 0 auto; padding: 20px 16px 32px; font-size: 14px; color: var(--muted);
                display: flex; flex-wrap: wrap; gap: 8px 20px; justify-content: space-between; }
  .foot-inner nav { display: flex; flex-wrap: wrap; gap: 8px 16px; }
  .ls { display: none; }
  @media (max-width: 480px) {
    .lf, .lc { display: none; }
    .ls { display: inline; }
    th, td { padding-right: 8px; }
    th { letter-spacing: .05em; }
    td.num { font-size: 13.5px; }
    td:not(.num):not(:first-child) { overflow-wrap: anywhere; }
  }
  @media (max-width: 760px) {
    .nav { display: none; }
    h1 { font-size: 28px; }
    .lede { font-size: 17px; }
  }
</style>
"""

# Brand mark, same as web/privacy/index.html. Name comes from SITE_NAME.
_BRAND_SVG = (
    '<svg width="26" height="26" viewBox="0 0 64 64" fill="currentColor" aria-hidden="true">'
    '<path d="M22 30.6 C28 30.4 32 29.6 35 28.6 C37 19 45 10 59 4 C52 12 47.5 22 47 32 '
    'C47.5 42 52 52 59 60 C45 54 37 45 35 35.4 C32 34.4 28 33.6 22 33.4 Z"/>'
    '<rect x="3" y="35" width="4.5" height="7" rx="1.2"/><rect x="9.5" y="30" width="4.5" '
    'height="12" rx="1.2"/><rect x="16" y="25" width="4.5" height="17" rx="1.2"/></svg>'
)

# "Pick my trip" (/sd/pick, web/trip-picker.js). ?type= opens the picker on a
# trip type for the next 7 days (full, overnight, 1.5, multi = 2-3.5 day,
# long = 4+ day); ?q= takes a preset id. Keyed by trip-length or species slug.
_PICK_URL = {
    "full-day": "/sd/pick?type=full",
    "overnight": "/sd/pick?type=overnight",
    "1-5-day": "/sd/pick?type=1.5",
    "2-day": "/sd/pick?type=multi",
    "2-5-day": "/sd/pick?type=multi",
    "3-day": "/sd/pick?type=multi",
    "yellowtail": "/sd/pick?q=yellowtail",
}

_NAV_LINKS = [("Fish Counts", "/sd/today"), ("Boats", "/sd/boats"),
              ("Analytics", "/sd/analytics/overview"), ("Trip Planner", "/sd/tripplanner")]


def _static_header(current: str = "") -> str:
    cur = ' aria-current="page"'
    links = "".join(
        f'<a href="{href}"{cur if label == current else ""}>{label}</a>'
        for label, href in _NAV_LINKS)
    return (f'<header class="top"><div class="top-inner">'
            f'<a class="brand" href="/">{_BRAND_SVG}{SITE_NAME}</a>'
            f'<nav class="nav" aria-label="Site">{links}</nav>'
            f'<a class="btn btn-primary" href="/sd/today">Today\'s counts →</a>'
            f'</div></header>')


def _static_footer() -> str:
    links = "".join(f'<a href="{href}">{label}</a>' for label, href in _NAV_LINKS)
    return (f'<footer><div class="foot-inner"><span>© {date.today().year} {SITE_NAME}</span>'
            f'<nav aria-label="Footer">{links}<a href="/privacy/">Privacy</a></nav></div></footer>')


def _cta(pitch: str, buttons: list[tuple[str, str]]) -> str:
    btns = "".join(
        f'<a class="btn {"btn-primary" if i == 0 else "btn-secondary"}" href="{href}">{_esc(label)}</a>'
        for i, (label, href) in enumerate(buttons))
    return f'<aside class="cta"><p>{_esc(pitch)}</p><div class="cta-actions">{btns}</div></aside>'


_NUM_CELL = re.compile(r"<td>(-?[\d,]+(?:\.\d+)?%?)</td>")


def _style_static(html: str) -> str:
    """Table wrappers, numeric columns and the lede paragraph for static pages."""
    def one_table(m: re.Match) -> str:
        t = _NUM_CELL.sub(r'<td class="num">\1</td>', m.group(0))
        # Right-align a header cell when its column holds numbers in the first row.
        first = re.search(r"<tbody>\s*<tr>(.*?)</tr>", t, re.S)
        if first:
            cells = re.findall(r'<td(?: class="([^"]*)")?>', first.group(1))
            heads = list(re.finditer(r'<th(?: class="([^"]*)")?>', t))
            for i in reversed(range(min(len(cells), len(heads)))):
                if "num" in cells[i].split():
                    h = heads[i]
                    cls = " ".join(filter(None, ["num", h.group(1)]))
                    t = t[:h.start()] + f'<th class="{cls}">' + t[h.end():]
        # Caption above the scroll box, so it doesn't scroll sideways with the table.
        cap = re.search(r"\s*<caption>(.*?)</caption>", t, re.S)
        if cap:
            t = t[:cap.start()] + t[cap.end():]
            return f'<p class="cap">{cap.group(1).strip()}</p><div class="tw">{t}</div>'
        return f'<div class="tw">{t}</div>'
    html = re.sub(r"<table>.*?</table>", one_table, html, flags=re.S)
    return re.sub(r"(</h1>\s*)<p>", r'\1<p class="lede">', html, count=1)


# ── Shared HTML head/body helpers ─────────────────────────────────────────────

def _head(title: str, desc: str, canonical: str, og: dict, json_ld,
          shared: dict, noindex: bool = False, app: bool = True) -> str:
    """Build the <head> block for a generated page.

    json_ld: a dict, a list of dicts, or None.
    """
    og_image = og.get("image", f"{SITE_URL}/og-image.png")
    og_title = og.get("title", title)
    og_desc  = og.get("description", desc)
    canonical_full = f"{SITE_URL}{canonical}"

    ld_list = json_ld if isinstance(json_ld, list) else ([json_ld] if json_ld else [])
    ld_block = "".join(
        '<script type="application/ld+json">\n'
        + json.dumps(ld, indent=2).replace("</", "<\\/")
        + "\n</script>\n"
        for ld in ld_list
    )
    robots = '<meta name="robots" content="noindex, follow">\n' if noindex else ""
    # Static-only pages (app=False) skip the SPA's CSS and scripts.
    app_assets = (
        '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css">\n'
        '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css" crossorigin="anonymous">\n'
        '<link rel="stylesheet" href="lib/leaflet-velocity/leaflet-velocity.css">\n'
    ) if app else ""
    app_scripts = f"{shared['vessel_script']}\n{shared['clerk_sdk']}\n" if app else ""
    page_css = (
        f"{shared.get('fonts', '')}\n{app_assets}"
        f'<link rel="stylesheet" href="styles.css?v={shared["styles_ver"]}">\n'
        f'<link rel="stylesheet" href="design-system.css?v={shared["ds_ver"]}">\n'
    ) if app else _STATIC_FONTS + _STATIC_CSS

    # data-prerendered tells web/seo.js not to overwrite this head on first load.
    return f"""<!doctype html>
<html lang="en" data-prerendered="1">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#17332C">
<base href="/">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(desc)}">
{robots}<link rel="canonical" href="{canonical_full}">
<meta property="og:type"        content="website">
<meta property="og:site_name"   content="{SITE_NAME}">
<meta property="og:title"       content="{_esc(og_title)}">
<meta property="og:description" content="{_esc(og_desc)}">
<meta property="og:image"       content="{og_image}">
<meta property="og:url"         content="{canonical_full}">
<meta name="twitter:card"        content="summary_large_image">
<meta name="twitter:title"       content="{_esc(og_title)}">
<meta name="twitter:description" content="{_esc(og_desc)}">
<meta name="twitter:image"       content="{og_image}">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
{ld_block}{shared.get('gtag', '')}
{page_css}{app_scripts}</head>"""


def _esc(s: str) -> str:
    """Escape HTML attribute special chars."""
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _body_wrap(seo_content: str, shared: dict, app: bool = True, cta: str = "") -> str:
    """Build the <body> block.

    app=False is for routes the SPA has no view for (species, trip lengths):
    the app would redirect those visitors to /sd/today, so they get the static
    page with a plain site nav instead, and the SPA isn't loaded.
    """
    if not app:
        return f"""
<body>
{_static_header()}
<main id="seo-static">
{_style_static(seo_content)}
{cta}
</main>
{_static_footer()}
</body>
</html>"""
    return f"""
<body>
<div id="seo-static">
{seo_content}
</div>
<div id="root"></div>
<script>(function(){{var s=document.getElementById('seo-static');if(s)s.style.display='none';}})();</script>
{shared['body_scripts']}
</body>
</html>"""


def _breadcrumb(items: list[tuple[str, str]]) -> str:
    """items = [(label, href), ...], last item has no link."""
    lis = []
    for i, (label, href) in enumerate(items):
        if href:
            lis.append(f"<li><a href=\"{href}\">{_esc(label)}</a></li>")
        else:
            lis.append(f"<li>{_esc(label)}</li>")
    return f'<nav aria-label="Breadcrumb"><ol>{"".join(lis)}</ol></nav>'


def _breadcrumb_ld(items: list[tuple[str, str]]) -> dict:
    """BreadcrumbList JSON-LD matching _breadcrumb(). The last item is the current page."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": label,
             **({"item": f"{SITE_URL}{href}"} if href else {})}
            for i, (label, href) in enumerate(items, 1)
        ],
    }


_LANDING_SHORT = {
    "H&M Landing": "H&M", "Fisherman's Landing": "Fisherman's",
    "Seaforth Sportfishing": "Seaforth", "Point Loma Sportfishing": "Point Loma",
    "Oceanside Sea Center": "Oceanside",
}


def _landing_cell(landing: str) -> str:
    """Full landing name, swapped for a short one on phones (static pages' CSS)."""
    short = _LANDING_SHORT.get(landing)
    if not short:
        return _esc(landing)
    return f'<span class="lf">{_esc(landing)}</span><span class="ls">{_esc(short)}</span>'


def _f2(x) -> str:
    """Two decimals, so DM Mono number columns line up."""
    return f"{x:.2f}" if isinstance(x, (int, float)) else ""


def _dates_in_one_year(rows: list[dict]) -> str | None:
    years = {r["date"][:4] for r in rows}
    return years.pop() if len(years) == 1 else None


def _table_date(iso: str, short: bool) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{_MONTH_NAMES[d.month]} {d.day}" if short else _fmt_date(iso)


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{_MONTH_NAMES[d.month]} {d.day}, {d.year}"


def _trip_len_link(tl: str) -> str:
    slug = {t: sl for t, _, sl in TRIP_LENGTHS}.get(tl)
    return f'<a href="/sd/trips/{slug}/">{_esc(tl)}</a>' if slug else _esc(tl)


def _catch_str(r: dict) -> str:
    """Every species landed (full_catch JSON), else the four trophy columns."""
    try:
        full = json.loads(r.get("full_catch") or "{}")
    except (TypeError, ValueError):
        full = {}
    if isinstance(full, dict) and full:
        return ", ".join(f"{n} {sp.lower()}" for sp, n in full.items() if n)
    parts = [f"{r[k]} {k}" for k in ("bluefin", "yellowfin", "yellowtail", "dorado") if r.get(k)]
    return ", ".join(parts) if parts else "no trophy fish"


# ── Boat page ─────────────────────────────────────────────────────────────────

def _boat_page_html(boat: str, landing: str, stats: dict,
                    profile: dict | None, review: dict | None,
                    shared: dict, siblings: list[str] | None = None) -> str:
    landing_slug = SD_LANDINGS.get(landing, "")
    canonical    = page_url("boat", boat)
    last         = _fmt_date(stats["last_date"])
    title  = f"{boat} Fish Report & Counts — {landing} | {SITE_NAME}"
    desc   = (
        f"{boat} ({landing}) latest fish counts, last trip {last}. "
        f"{stats['total']} trips since {stats['first_year']}: {stats['win_rate']}% "
        f"landed trophy fish, avg {stats['avg_tpad']} per angler per day."
    )

    # OG image
    og_image = f"{SITE_URL}/og-image.png"
    if profile and profile.get("photo_url"):
        raw = profile["photo_url"]
        og_image = raw if raw.startswith("http") else f"{SITE_URL}/{raw.lstrip('/')}"

    crumbs = [(SITE_NAME, "/"), ("Boats", "/sd/boats")]
    if landing_slug:
        crumbs.append((landing, f"/sd/landing/{landing_slug}/"))
    crumbs.append((boat, ""))

    # JSON-LD: breadcrumbs always. LocalBusiness only with >= 3 first-party
    # reviews, since the rating is the only part that earns a rich result.
    json_ld: list[dict] = [_breadcrumb_ld(crumbs)]
    if review and review.get("count", 0) >= 3:
        json_ld.append({
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": boat,
            "description": desc,
            "url": f"{SITE_URL}{canonical}",
            "image": og_image,
            "address": {
                "@type": "PostalAddress", "addressLocality": "San Diego",
                "addressRegion": "CA", "addressCountry": "US",
            },
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": round(review["avg"], 1),
                "reviewCount": review["count"],
                "bestRating": 5, "worstRating": 1,
            },
        })

    # Species section
    species_rows = [(k, v) for k, v in stats["species"].items() if v > 0]
    species_section = ""
    if species_rows:
        lis = "".join(f"<li>{name}: {count:,} landed</li>" for name, count in species_rows)
        species_section = f"<section><h2>Species Breakdown</h2><ul>{lis}</ul></section>"

    recent_rows = "".join(
        f"<tr><td>{_fmt_date(r['date'])}</td><td>{_esc(r['trip_length'] or '')}</td>"
        f"<td>{r['anglers'] or ''}</td><td>{_esc(_catch_str(r))}</td></tr>\n"
        for r in stats["recent"]
    )
    recent_section = f"""<section>
<h2>Latest {_esc(boat)} fish counts</h2>
<table>
  <caption>Last {len(stats['recent'])} reported trips (fish landed; released fish not counted)</caption>
  <thead><tr><th>Date</th><th>Trip</th><th>Anglers</th><th>Catch</th></tr></thead>
  <tbody>
{recent_rows}  </tbody>
</table>
</section>""" if recent_rows else ""

    lengths_section = ""
    if stats["trip_lengths"]:
        lengths_section = "<section><h2>Trips run</h2><ul>" + "".join(
            f"<li>{_trip_len_link(tl)}: {n} trips</li>" for tl, n in stats["trip_lengths"][:6]
        ) + "</ul></section>"

    months_section = ""
    if stats["best_months"]:
        months_section = (
            "<section><h2>Best months</h2><p>Highest average trophy fish per angler "
            "per day, all years combined:</p><ul>" + "".join(
                f"<li>{_MONTH_NAMES[m]}: {avg:.2f} ({n} trips)</li>"
                for m, avg, n in stats["best_months"]
            ) + "</ul></section>"
        )

    landing_link = (
        f'<p><a href="/sd/landing/{landing_slug}/">More boats at {_esc(landing)} →</a></p>'
        if landing_slug else ""
    )
    siblings_section = ""
    if siblings:
        siblings_section = (
            f"<section><h2>Other boats at {_esc(landing)}</h2><ul>" + "".join(
                f'<li><a href="{page_url("boat", b)}">{_esc(b)}</a></li>' for b in siblings
            ) + "</ul></section>"
        )

    seo_content = f"""<article>
{_breadcrumb(crumbs)}
<h1>{_esc(boat)}</h1>
<p>{_esc(boat)} is a sportfishing boat at {_esc(landing)} in San Diego, CA.
   Its most recent reported trip was {last}.
   Across {stats['total']} trips from {stats['first_year']} to {stats['last_year']},
   {stats['win_rate']}% landed at least one trophy fish (bluefin, yellowfin,
   yellowtail or dorado), averaging {stats['avg_tpad']} per angler per day.</p>
{recent_section}
<table>
  <caption>Performance Summary</caption>
  <tbody>
    <tr><th scope="row">Win Rate</th><td>{stats['win_rate']}%</td></tr>
    <tr><th scope="row">Avg Fish/Angler/Day</th><td>{stats['avg_tpad']}</td></tr>
    <tr><th scope="row">Total Trips in Database</th><td>{stats['total']}</td></tr>
    <tr><th scope="row">Data Range</th><td>{stats['first_year']}–{stats['last_year']}</td></tr>
  </tbody>
</table>
{species_section}
{lengths_section}
{months_section}
{siblings_section}
{landing_link}
</article>"""

    head = _head(title, desc, canonical,
                 {"title": title, "description": desc, "image": og_image},
                 json_ld, shared, noindex=stats["total"] < MIN_TRIPS_INDEX)
    return head + _body_wrap(seo_content, shared)


# ── Landing page ──────────────────────────────────────────────────────────────

def _landing_page_html(landing: str, slug: str, boats: list[dict],
                       recent: list[dict], shared: dict) -> str:
    canonical = f"/sd/landing/{slug}/"
    n = len(boats)
    title = f"{landing} Fish Counts — Fleet & Boat Stats | {SITE_NAME}"
    desc  = (
        f"{landing} fish counts for the last 7 days, plus all {n} boats ranked by "
        f"catch history. San Diego sportfishing data, updated daily."
    )

    crumbs = [(SITE_NAME, "/"), ("Boats", "/sd/boats"), (landing, "")]
    json_ld = [_breadcrumb_ld(crumbs), {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": desc,
        "url": f"{SITE_URL}{canonical}",
        "about": {"@type": "Place", "name": landing,
                  "address": {"@type": "PostalAddress", "addressLocality": "San Diego",
                              "addressRegion": "CA", "addressCountry": "US"}},
    }]

    recent_rows = "".join(
        f"<tr><td>{_fmt_date(r['date'])}</td>"
        f"<td><a href=\"{page_url('boat', r['boat'])}\">{_esc(r['boat'])}</a></td>"
        f"<td>{_esc(r['trip_length'] or '')}</td><td>{r['anglers'] or ''}</td>"
        f"<td>{_esc(_catch_str(r))}</td></tr>\n"
        for r in recent
    )
    recent_section = f"""<section>
<h2>{_esc(landing)} fish counts: last 7 days</h2>
<table>
  <caption>{len(recent)} trips reported, fish landed</caption>
  <thead><tr><th>Date</th><th>Boat</th><th>Trip</th><th>Anglers</th><th>Catch</th></tr></thead>
  <tbody>
{recent_rows}  </tbody>
</table>
</section>""" if recent_rows else ""

    rows_html = ""
    for b in boats:
        rows_html += (
            f"<tr>"
            f"<td><a href=\"{page_url('boat', b['boat'])}\">{_esc(b['boat'])}</a></td>"
            f"<td>{b['win_rate']}%</td>"
            f"<td>{b['avg_tpad']}</td>"
            f"<td>{b['total']}</td>"
            f"</tr>\n"
        )

    seo_content = f"""<article>
{_breadcrumb(crumbs)}
<h1>{_esc(landing)}</h1>
<p>Fish counts and boat stats for {_esc(landing)} in San Diego, CA.
   Boats with at least {MIN_TRIPS_INDEX} trips are ranked by how often they land
   trophy fish; boats with fewer trips are listed after them.</p>
{recent_section}
<h2>Fleet performance</h2>
<table>
  <caption>Fleet Performance at {_esc(landing)}</caption>
  <thead>
    <tr>
      <th>Boat</th>
      <th>Win Rate</th>
      <th>Avg Fish/Angler/Day</th>
      <th>Trips in DB</th>
    </tr>
  </thead>
  <tbody>
{rows_html}  </tbody>
</table>
</article>"""

    head = _head(title, desc, canonical,
                 {"title": title, "description": desc},
                 json_ld, shared)
    return head + _body_wrap(seo_content, shared)


# ── Species page ──────────────────────────────────────────────────────────────

def _species_page_html(name: str, slug: str, col: str, stats: dict,
                       shared: dict) -> str:
    canonical = f"/sd/species/{slug}/"
    title = f"San Diego {name} Fishing — Best Boats & Season | {SITE_NAME}"
    desc  = (
        f"Which San Diego sportfishing boats catch the most {name}. "
        f"Historical performance data, seasonal calendar, and top boats by "
        f"average fish per angler."
    )

    crumbs = [(SITE_NAME, "/"), (f"{name} Fishing", "")]
    json_ld = [_breadcrumb_ld(crumbs), {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": desc,
        "url": f"{SITE_URL}{canonical}",
    }]

    # Top boats table
    top_rows = ""
    for i, b in enumerate(stats["top_boats"], 1):
        top_rows += (
            f"<tr>"
            f"<td>{i}</td>"
            f"<td><a href=\"{page_url('boat', b['boat'])}\">{_esc(b['boat'])}</a></td>"
            f"<td class=\"lc\">{_landing_cell(b.get('landing', ''))}</td>"
            f"<td>{_f2(b.get('avg_tpad'))}</td>"
            f"<td>{b.get('trips', '')}</td>"
            f"</tr>\n"
        )

    top_table = ""
    if top_rows:
        top_table = f"""<section>
<h2>Top Boats for {_esc(name)}</h2>
<table>
  <caption>Top 10 boats by average {_esc(name)} per angler per day (min 5 trips)</caption>
  <thead>
    <tr><th>#</th><th>Boat</th><th class="lc">Landing</th><th>Per angler/day</th><th>Trips</th></tr>
  </thead>
  <tbody>
{top_rows}  </tbody>
</table>
</section>"""

    # Monthly calendar table
    monthly_rows = ""
    for m in stats["monthly"]:
        month_num = m["month"]
        mname = _MONTH_NAMES[month_num] if 1 <= month_num <= 12 else str(month_num)
        monthly_rows += (
            f"<tr>"
            f"<td>{mname}</td>"
            f"<td>{_f2(m.get('avg_tpad'))}</td>"
            f"<td>{m.get('trips', '')}</td>"
            f"</tr>\n"
        )

    monthly_table = ""
    if monthly_rows:
        monthly_table = f"""<section>
<h2>Seasonal Catch Calendar</h2>
<table>
  <caption>Average {_esc(name)} per angler per day by month (last 5 years)</caption>
  <thead>
    <tr><th>Month</th><th>Per angler/day</th><th>Trips</th></tr>
  </thead>
  <tbody>
{monthly_rows}  </tbody>
</table>
</section>"""

    recent = stats.get("recent") or []
    recent_section = ""
    if recent:
        shown = recent[:25]
        year = _dates_in_one_year(shown)
        rows = "".join(
            f"<tr><td>{_table_date(r['date'], bool(year))}</td>"
            f"<td><a href=\"{page_url('boat', r['boat'])}\">{_esc(r['boat'])}</a></td>"
            f"<td class=\"lc\">{_landing_cell(r['landing'])}</td><td>{_esc(r['trip_length'] or '')}</td>"
            f"<td>{r['anglers'] or ''}</td><td>{r[col]}</td></tr>\n"
            for r in shown
        )
        recent_section = f"""<section>
<h2>{_esc(name)} caught in San Diego: last {SPECIES_RECENT_DAYS} days</h2>
<p>{stats['recent_fish']:,} {_esc(name.lower())} landed on {len(recent)} trips.</p>
<table>
  <caption>{len(shown)} most recent trips with {_esc(name.lower())}{", " + year if year else ""}</caption>
  <thead><tr><th>Date</th><th>Boat</th><th class="lc">Landing</th><th>Trip</th><th>Anglers</th><th>Landed</th></tr></thead>
  <tbody>
{rows}  </tbody>
</table>
</section>"""
    else:
        recent_section = (f"<p>No {_esc(name.lower())} reported by San Diego boats in the last "
                          f"{SPECIES_RECENT_DAYS} days.</p>")

    seo_content = f"""<article>
{_breadcrumb(crumbs)}
<h1>San Diego {_esc(name)} Fishing</h1>
<p>Analysis of {_esc(name)} catches across all San Diego sportfishing landings.
   Based on {stats['total_trips']:,} recorded trips with {_esc(name.lower())} in the catch.</p>
{recent_section}
{top_table}
{monthly_table}
</article>"""

    head = _head(title, desc, canonical,
                 {"title": title, "description": desc},
                 json_ld, shared, app=False)
    plan = (f"Find a {name.lower()} trip", _PICK_URL[slug]) if slug in _PICK_URL \
        else ("Plan a trip", "/sd/tripplanner")
    cta = _cta(f"Who's catching {name.lower()} right now, and where can you go?", [
        (f"See today's {name.lower()} counts", "/sd/today"), plan])
    return head + _body_wrap(seo_content, shared, app=False, cta=cta)


# ── /sd/today and /sd/boats ───────────────────────────────────────────────────
# Written as web/sd/today.html and web/sd/boats.html. CF Pages serves x.html at
# /x, so the canonical stays slash-less, matching the app and web/seo.js. The
# title and description mirror CONFIG.today / CONFIG.boats in web/seo.js.

_LANDING_ORDER = list(SD_LANDINGS)


def _landing_link(landing: str, short: bool = False) -> str:
    slug = SD_LANDINGS.get(landing)
    text = _landing_cell(landing) if short else _esc(landing)
    return f'<a href="/sd/landing/{slug}/">{text}</a>' if slug else text


def _landing_rank(landing: str) -> int:
    return _LANDING_ORDER.index(landing) if landing in _LANDING_ORDER else 99


def _today_page_html(latest: str, trips: list[dict], shared: dict) -> str:
    canonical = "/sd/today"
    title = f"Today's San Diego Fish Counts — Live Sportfishing Report | {SITE_NAME}"
    desc = ("Today's fish counts from H&M, Fisherman's, Seaforth, Point Loma, and Oceanside "
            "landings, checked hourly: bluefin, yellowfin, yellowtail and dorado by boat.")
    crumbs = [(SITE_NAME, "/"), ("Fish Counts", "")]
    json_ld = [_breadcrumb_ld(crumbs), {
        "@context": "https://schema.org", "@type": "WebPage", "name": title,
        "description": desc, "url": f"{SITE_URL}{canonical}", "dateModified": latest,
    }]

    totals = {k: sum(r[k] or 0 for r in trips) for k in ("bluefin", "yellowfin", "yellowtail", "dorado")}
    total_str = ", ".join(f"{v:,} {k}" for k, v in totals.items() if v) or "no trophy fish"

    by_date: dict[str, list[dict]] = {}
    for r in trips:
        by_date.setdefault(r["date"][:10], []).append(r)
    day_sections = []
    for d in sorted(by_date, reverse=True):
        day = by_date[d]
        parts = [f"<section>\n<h2>San Diego fish counts for {_fmt_date(d)}</h2>"]
        for landing in sorted({r["landing"] for r in day}, key=_landing_rank):
            rows = "".join(
                f"<tr><td><a href=\"{page_url('boat', r['boat'])}\">{_esc(r['boat'])}</a></td>"
                f"<td>{_esc(r['trip_length'] or '')}</td><td>{r['anglers'] or ''}</td>"
                f"<td>{_esc(_catch_str(r))}</td></tr>\n"
                for r in day if r["landing"] == landing
            )
            parts.append(f"""<h3>{_landing_link(landing)}</h3>
<table>
  <thead><tr><th>Boat</th><th>Trip</th><th>Anglers</th><th>Catch</th></tr></thead>
  <tbody>
{rows}  </tbody>
</table>""")
        parts.append("</section>")
        day_sections.append("\n".join(parts))
    days_html = "\n".join(day_sections) or "<p>No trips reported in the last few days.</p>"

    landing_links = " · ".join(
        f'<a href="/sd/landing/{slug}/">{_esc(l)}</a>' for l, slug in SD_LANDINGS.items())
    species_links = " · ".join(
        f'<a href="/sd/species/{slug}/">{_esc(n)}</a>' for _, n, slug in TROPHY_SPECIES)

    seo_content = f"""<article>
{_breadcrumb(crumbs)}
<h1>San Diego Fish Counts</h1>
<p>The latest fish counts from San Diego sportfishing boats, updated hourly from each
   landing's posted counts. Most recent report: {_fmt_date(latest)}.
   Over the last {TODAY_DAYS} days, {len(trips)} trips landed {_esc(total_str)}.
   The catch column lists every species landed; released fish are not counted.</p>
{days_html}
<section><h2>Fish counts by landing</h2><p>{landing_links}</p></section>
<section><h2>Fish counts by species</h2><p>{species_links}</p></section>
<section><h2>Fish counts by trip length</h2><p>{_trip_links()}</p></section>
<p><a href="/sd/boats">All San Diego sportfishing boats →</a></p>
</article>"""
    head = _head(title, desc, canonical, {"title": title, "description": desc}, json_ld, shared)
    return head + _body_wrap(seo_content, shared)


def _boats_page_html(all_stats: dict[str, dict], shared: dict) -> str:
    canonical = "/sd/boats"
    title = f"San Diego Sportfishing Boats Directory | {SITE_NAME}"
    desc = ("Browse every San Diego sportfishing boat with photos, reviews, win rates, and "
            "catch records across H&M, Fisherman's, Seaforth, Point Loma, and Oceanside.")
    crumbs = [(SITE_NAME, "/"), ("Boats", "")]
    json_ld = [_breadcrumb_ld(crumbs), {
        "@context": "https://schema.org", "@type": "CollectionPage", "name": title,
        "description": desc, "url": f"{SITE_URL}{canonical}",
    }]
    sections = []
    for landing in _LANDING_ORDER:
        boats = sorted((b, s) for b, s in all_stats.items() if s["landing"] == landing)
        if not boats:
            continue
        rows = "".join(
            f"<tr><td><a href=\"{page_url('boat', b)}\">{_esc(b)}</a></td>"
            f"<td>{_fmt_date(s['last_date'])}</td><td>{s['total']}</td>"
            f"<td>{s['win_rate']}%</td><td>{s['avg_tpad']}</td></tr>\n"
            for b, s in boats
        )
        sections.append(f"""<section>
<h2>{_landing_link(landing)} boats</h2>
<table>
  <thead><tr><th>Boat</th><th>Last trip</th><th>Trips</th><th>Win Rate</th><th>Avg Fish/Angler/Day</th></tr></thead>
  <tbody>
{rows}  </tbody>
</table>
</section>""")
    sections_html = "\n".join(sections)
    seo_content = f"""<article>
{_breadcrumb(crumbs)}
<h1>San Diego Sportfishing Boats</h1>
<p>{len(all_stats)} sportfishing boats from San Diego's landings, grouped by the landing
   each boat fished from most recently. Win rate is the share of trips that landed at
   least one trophy fish (bluefin, yellowfin, yellowtail or dorado).</p>
{sections_html}
<p><a href="/sd/today">Latest San Diego fish counts →</a></p>
</article>"""
    head = _head(title, desc, canonical, {"title": title, "description": desc}, json_ld, shared)
    return head + _body_wrap(seo_content, shared)


# ── Trip-length pages: /sd/trips/<slug>/ ──────────────────────────────────────
# One page per common trip length ("1.5 day trip San Diego" etc.). Historical
# numbers only; nothing here predicts future fishing.

TRIP_LENGTHS: list[tuple[str, str, str]] = [
    # (trip_length value in the DB, display name, url slug)
    ("Full Day",  "Full Day",  "full-day"),
    ("Overnight", "Overnight", "overnight"),
    ("1.5 Day",   "1.5 Day",   "1-5-day"),
    ("2 Day",     "2 Day",     "2-day"),
    ("2.5 Day",   "2.5 Day",   "2-5-day"),
    ("3 Day",     "3 Day",     "3-day"),
]
TRIP_RECENT_DAYS = 14
TRIP_BOAT_YEARS = 3       # top-boats window
TRIP_BOAT_MIN = 10        # trips in that window to be listed


def _trip_stats(conn: sqlite3.Connection, tl: str) -> dict | None:
    total, first, last = conn.execute(
        f"SELECT COUNT(*), MIN(date), MAX(date) FROM trips "
        f"WHERE {_SD_IN} AND trip_length=? AND trophy_count IS NOT NULL", (tl,)).fetchone()
    if not total:
        return None
    since = (date.fromisoformat(last[:10]) - timedelta(days=365 * TRIP_BOAT_YEARS)).isoformat()
    # Mean over all trips (zeros included) so the numbers aren't inflated.
    boats = [dict(r) for r in conn.execute(f"""
        SELECT boat, COUNT(*) AS trips,
               ROUND(AVG(trophy_per_angler), 2) AS per_angler,
               ROUND(100.0 * SUM(trophy_count > 0) / COUNT(*), 1) AS win_rate
        FROM trips
        WHERE {_SD_IN} AND trip_length=? AND date>=? AND trophy_per_angler IS NOT NULL
        GROUP BY boat HAVING trips>=?
        ORDER BY per_angler DESC LIMIT 15
    """, (tl, since, TRIP_BOAT_MIN))]
    cutoff = str(date.fromisoformat(last[:10]).year - 5)
    monthly = [dict(r) for r in conn.execute(f"""
        SELECT CAST(SUBSTR(date, 6, 2) AS INTEGER) AS month, COUNT(*) AS trips,
               ROUND(AVG(trophy_per_angler), 2) AS per_angler,
               ROUND(100.0 * SUM(trophy_count > 0) / COUNT(*), 1) AS win_rate
        FROM trips
        WHERE {_SD_IN} AND trip_length=? AND date>=? AND trophy_per_angler IS NOT NULL
        GROUP BY month ORDER BY month
    """, (tl, cutoff))]
    _, recent = _recent_sd_trips(conn, TRIP_RECENT_DAYS, "trip_length=" + _sql_str(tl))
    return dict(total=total, first_year=first[:4], last_date=last[:10], boats=boats,
                monthly=monthly, recent=recent, since=since)


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _trip_links(current: str = "") -> str:
    return " · ".join(
        (_esc(name) if slug == current else f'<a href="/sd/trips/{slug}/">{_esc(name)}</a>')
        for _, name, slug in TRIP_LENGTHS)


def _trip_page_html(name: str, slug: str, st: dict, shared: dict) -> str:
    canonical = f"/sd/trips/{slug}/"
    lower = name.lower()
    title = f"{name} Fishing Trips in San Diego — Boats, Catch & Best Months | {SITE_NAME}"
    desc = (f"San Diego {lower} sportfishing trips: recent fish counts, which boats run "
            f"{lower} trips and what they caught, and catch by month. "
            f"{st['total']:,} trips since {st['first_year']}.")
    crumbs = [(SITE_NAME, "/"), (f"{name} Trips", "")]
    json_ld = [_breadcrumb_ld(crumbs), {
        "@context": "https://schema.org", "@type": "WebPage", "name": title,
        "description": desc, "url": f"{SITE_URL}{canonical}", "dateModified": st["last_date"],
    }]

    recent = st["recent"]
    if recent:
        shown = recent[:25]
        year = _dates_in_one_year(shown)
        rows = "".join(
            f"<tr><td>{_table_date(r['date'], bool(year))}</td>"
            f"<td><a href=\"{page_url('boat', r['boat'])}\">{_esc(r['boat'])}</a></td>"
            f"<td>{_landing_link(r['landing'], short=True)}</td><td>{r['anglers'] or ''}</td>"
            f"<td>{_esc(_catch_str(r))}</td></tr>\n"
            for r in shown)
        recent_section = f"""<section>
<h2>{_esc(name)} fish counts: last {TRIP_RECENT_DAYS} days</h2>
<table>
  <caption>{len(shown)} most recent {_esc(lower)} trips from San Diego landings{", " + year if year else ""}</caption>
  <thead><tr><th>Date</th><th>Boat</th><th>Landing</th><th>Anglers</th><th>Catch</th></tr></thead>
  <tbody>
{rows}  </tbody>
</table>
</section>"""
    else:
        recent_section = (f"<p>No {_esc(lower)} trips reported in the last "
                          f"{TRIP_RECENT_DAYS} days.</p>")

    boats_section = ""
    if st["boats"]:
        rows = "".join(
            f"<tr><td><a href=\"{page_url('boat', b['boat'])}\">{_esc(b['boat'])}</a></td>"
            f"<td>{b['trips']}</td><td>{_f2(b['per_angler'])}</td><td>{b['win_rate']:.1f}%</td></tr>\n"
            for b in st["boats"])
        boats_section = f"""<section>
<h2>Boats that run {_esc(lower)} trips</h2>
<table>
  <caption>Last {TRIP_BOAT_YEARS} years, boats with at least {TRIP_BOAT_MIN} {_esc(lower)} trips,
    by average trophy fish (bluefin, yellowfin, yellowtail, dorado) per angler per trip.
    Trophy % is the share of trips that landed at least one.</caption>
  <thead><tr><th>Boat</th><th>Trips</th><th>Per angler</th><th>Trophy %</th></tr></thead>
  <tbody>
{rows}  </tbody>
</table>
</section>"""

    month_section = ""
    if st["monthly"]:
        rows = "".join(
            f"<tr><td>{_MONTH_NAMES[m['month']]}</td><td>{m['trips']}</td>"
            f"<td>{_f2(m['per_angler'])}</td><td>{m['win_rate']:.1f}%</td></tr>\n"
            for m in st["monthly"] if 1 <= m["month"] <= 12)
        month_section = f"""<section>
<h2>{_esc(name)} catch by month</h2>
<table>
  <caption>All San Diego {_esc(lower)} trips, last 5 years: trophy fish per angler per trip,
    and the share of trips that landed any. Past seasons, not a forecast.</caption>
  <thead><tr><th>Month</th><th>Trips</th><th>Per angler</th><th>Trophy %</th></tr></thead>
  <tbody>
{rows}  </tbody>
</table>
</section>"""

    seo_content = f"""<article>
{_breadcrumb(crumbs)}
<h1>{_esc(name)} Fishing Trips in San Diego</h1>
<p>Fish counts and boat history for {_esc(lower)} sportfishing trips from San Diego's
   landings: {st['total']:,} trips reported since {st['first_year']}, the most recent on
   {_fmt_date(st['last_date'])}. Catch is fish landed; released fish are not counted.</p>
{recent_section}
{boats_section}
{month_section}
<section><h2>Other trip lengths</h2><p>{_trip_links(slug)}</p></section>
<p><a href="/sd/today">Latest San Diego fish counts →</a></p>
</article>"""
    head = _head(title, desc, canonical, {"title": title, "description": desc}, json_ld, shared, app=False)
    cta = _cta(f"Which upcoming {lower} trip looks best? Pick my trip compares them for you.", [
        (f"Find the best {lower} trip", _PICK_URL.get(slug, "/sd/pick")),
        ("Today's counts", "/sd/today")])
    return head + _body_wrap(seo_content, shared, app=False, cta=cta)


# ── Entry point ───────────────────────────────────────────────────────────────

def _write(web_dir, rel: str, html: str) -> None:
    out = Path(web_dir) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


_PRUNE_KINDS = ("boat", "landing", "species", "trips")


def _prune_stale(web_dir, pages: list[dict]) -> list[str]:
    """Delete generated pages under web/sd/<kind>/ that this run didn't write.

    Otherwise a page whose boat was renamed or lost its trips stays online
    forever with frozen numbers. Safety: a kind is only pruned when this run
    wrote at least one page of it, and more than 3 deletions must be under a
    quarter of the pages written, so a failed or partial run can't wipe the site.
    """
    from urllib.parse import unquote
    written: dict[str, set[str]] = {k: set() for k in _PRUNE_KINDS}
    for p in pages:
        parts = p["url"].strip("/").split("/")          # sd, kind, name
        if len(parts) == 3 and parts[1] in written:
            written[parts[1]].add(unquote(parts[2]))
    removed: list[str] = []
    for kind, names in written.items():
        root = Path(web_dir) / "sd" / kind
        if not names or not root.is_dir():
            continue
        stale = [d for d in root.iterdir()
                 if d.is_dir() and d.name not in names and (d / "index.html").is_file()]
        if len(stale) > 3 and len(stale) * 4 > len(names):
            log.warning("generate_pages: not pruning %d stale %s pages (too many)", len(stale), kind)
            continue
        for d in stale:
            (d / "index.html").unlink()
            if not any(d.iterdir()):
                d.rmdir()
            removed.append(f"/sd/{kind}/{d.name}/")
    if removed:
        log.info("generate_pages: removed stale pages %s", removed)
    return removed


def generate_all_pages(conn: sqlite3.Connection, web_dir, index_path) -> list[dict]:
    """Generate all static pages. Called from export.py.

    Returns [{"url": site-relative URL, "lastmod": ISO date, "index": bool}, ...]
    for every page written; export.py turns it into sitemap.xml.
    """
    conn.row_factory = sqlite3.Row
    index_html = Path(index_path).read_text(encoding="utf-8")
    shared = _parse_index(index_html)

    # Read boat profiles for photos
    profiles: dict[str, dict] = {}
    try:
        for r in conn.execute("SELECT boat, photo_url FROM boat_profiles"):
            profiles[r["boat"]] = dict(r)
    except Exception:
        pass

    # Read reviews
    reviews: dict[str, dict] = {}
    try:
        for r in conn.execute("""
            SELECT boat, AVG(overall) as avg, COUNT(*) as cnt
            FROM reviews GROUP BY boat HAVING cnt >= 3
        """):
            reviews[r["boat"]] = {"avg": r["avg"], "count": r["cnt"]}
    except Exception:
        pass

    n_boats = n_landings = n_species = 0
    pages: list[dict] = []

    # ── Boat pages ────────────────────────────────────────────────────────────
    sd_boats = conn.execute(f"SELECT DISTINCT boat FROM trips WHERE {_SD_IN} ORDER BY boat").fetchall()
    all_stats: dict[str, dict] = {}
    for row in sd_boats:
        try:
            st = _boat_stats(conn, row["boat"])
        except Exception as e:
            log.warning("Boat stats failed for %r: %s", row["boat"], e)
            continue
        if st:
            all_stats[row["boat"]] = st
    # Boats now fishing outside San Diego (e.g. Pride, now at 22nd Street) keep
    # their page for the SD history, but aren't listed in the SD fleet views.
    sd_stats = {b: s for b, s in all_stats.items() if s["landing"] in SD_LANDINGS}

    by_recency = sorted(sd_stats.items(), key=lambda kv: kv[1]["last_date"], reverse=True)
    for boat, stats in all_stats.items():
        try:
            siblings = [b for b, s in by_recency
                        if s["landing"] == stats["landing"] and b != boat
                        and s["total"] >= MIN_TRIPS_INDEX][:12]
            html = _boat_page_html(boat, stats["landing"], stats, profiles.get(boat),
                                   reviews.get(boat), shared, siblings)
            out = Path(web_dir) / "sd" / "boat" / _safe_dir(boat) / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            n_boats += 1
            pages.append({"url": page_url("boat", boat), "lastmod": stats["last_date"],
                          "index": stats["total"] >= MIN_TRIPS_INDEX})
        except Exception as e:
            log.warning("Boat page failed for %r: %s", boat, e)

    # ── Landing pages ─────────────────────────────────────────────────────────
    for landing, slug in SD_LANDINGS.items():
        try:
            boats = _landing_boats(all_stats, landing)
            if not boats:
                continue
            recent = _landing_recent(conn, landing)
            html = _landing_page_html(landing, slug, boats, recent, shared)
            out = Path(web_dir) / "sd" / "landing" / slug / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            n_landings += 1
            pages.append({"url": f"/sd/landing/{slug}/",
                          "lastmod": max(b["last_date"] for b in boats), "index": True})
        except Exception as e:
            log.warning("Landing page failed for %r: %s", landing, e)

    # ── Species pages ─────────────────────────────────────────────────────────
    for col, name, slug in TROPHY_SPECIES:
        try:
            stats = _species_stats(conn, col)
            html = _species_page_html(name, slug, col, stats, shared)
            out = Path(web_dir) / "sd" / "species" / slug / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            n_species += 1
            pages.append({"url": f"/sd/species/{slug}/", "lastmod": stats["last_date"],
                          "index": True})
        except Exception as e:
            log.warning("Species page failed for %r: %s", name, e)

    # ── Trip-length pages ─────────────────────────────────────────────────────
    for tl, name, slug in TRIP_LENGTHS:
        try:
            st = _trip_stats(conn, tl)
            if not st:
                continue
            _write(web_dir, f"sd/trips/{slug}/index.html", _trip_page_html(name, slug, st, shared))
            pages.append({"url": f"/sd/trips/{slug}/", "lastmod": st["last_date"],
                          "index": st["total"] >= MIN_TRIPS_INDEX})
        except Exception as e:
            log.warning("Trip page failed for %r: %s", tl, e)

    # ── /sd/today and /sd/boats ───────────────────────────────────────────────
    try:
        latest, recent = _recent_sd_trips(conn, TODAY_DAYS)
        if latest:
            _write(web_dir, "sd/today.html", _today_page_html(latest, recent, shared))
            pages.append({"url": "/sd/today", "lastmod": latest, "index": True})
        if sd_stats:
            _write(web_dir, "sd/boats.html", _boats_page_html(sd_stats, shared))
            pages.append({"url": "/sd/boats", "index": True,
                          "lastmod": max(s["last_date"] for s in sd_stats.values())})
    except Exception as e:
        log.warning("Today/boats page failed: %s", e)

    _prune_stale(web_dir, pages)
    log.info("generate_pages: %d boats, %d landings, %d species", n_boats, n_landings, n_species)
    return pages
