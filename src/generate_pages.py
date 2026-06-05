"""Generate pre-rendered static HTML pages for boats, landings, and species.

Each generated page:
  - Has SEO meta tags baked into the HTML (no JS needed by crawlers)
  - Contains visible pre-rendered stats/content for crawlers in #seo-static
  - Loads the full SPA so users get the interactive experience
  - Is written to web/sd/{boat,landing,species}/.../ so CF Pages serves it directly
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote as url_quote

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SD_LANDINGS: dict[str, str] = {
    "H&M Landing":            "hm-landing",
    "Fisherman's Landing":    "fishermans-landing",
    "Seaforth Sportfishing":  "seaforth",
    "Point Loma Sportfishing":"point-loma",
    "Oceanside Sea Center":   "oceanside",
}

TROPHY_SPECIES: list[tuple[str, str, str]] = [
    # (db_column, display_name, url_slug)
    ("bluefin",    "Bluefin Tuna", "bluefin-tuna"),
    ("yellowfin",  "Yellowfin Tuna", "yellowfin-tuna"),
    ("yellowtail", "Yellowtail", "yellowtail"),
    ("dorado",     "Dorado", "dorado"),
]


def _safe_dir(name: str) -> str:
    """Remove chars that are problematic as directory names on any OS."""
    bad = r'/\:*?"<>|'
    return "".join(c for c in name if c not in bad)


# ── Index.html parser ─────────────────────────────────────────────────────────

def _parse_index(index_html: str) -> dict:
    """Extract shared parts from index.html for inclusion in generated pages."""
    # styles.css version
    styles_m = re.search(r'href="styles\.css\?v=([^"]+)"', index_html)
    styles_ver = styles_m.group(1) if styles_m else "1"

    # Clerk SDK script tag from head
    clerk_m = re.search(r'<script\s[^>]*clerk[^>]*(?:/>|>.*?</script>)', index_html, re.S | re.I)
    clerk_sdk = clerk_m.group(0) if clerk_m else ""

    # VESSEL_WORKER_URL inline script
    vessel_m = re.search(r'<script>window\.VESSEL_WORKER_URL[^<]+</script>', index_html)
    vessel_script = vessel_m.group(0) if vessel_m else "<script>window.VESSEL_WORKER_URL = '';</script>"

    # All script tags from React CDN onward (to end of body)
    react_start = index_html.find('<script src="https://unpkg.com/react@')
    body_end = index_html.rfind('</body>')
    body_scripts = index_html[react_start:body_end].strip() if react_start != -1 else ""

    return dict(
        styles_ver=styles_ver,
        clerk_sdk=clerk_sdk,
        vessel_script=vessel_script,
        body_scripts=body_scripts,
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

def _boat_stats(conn: sqlite3.Connection, boat: str) -> dict | None:
    """Return stats dict or None if no usable trip data."""
    rows = conn.execute("""
        SELECT trophy_count, trophy_per_angler_per_day,
               bluefin, yellowfin, yellowtail, dorado, date, anglers
        FROM trips WHERE boat = ? AND trophy_count IS NOT NULL
        ORDER BY date DESC
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
    return dict(
        total=total,
        wins=wins,
        win_rate=round(wins / total * 100, 1),
        avg_tpad=round(sum(tpads) / len(tpads), 2) if tpads else 0,
        species=species,
        first_year=min(years, default=""),
        last_year=max(years, default=""),
        recent=[dict(r) for r in rows[:5]],
    )


def _landing_boats(conn: sqlite3.Connection, landing: str) -> list[dict]:
    """Return list of boat stats dicts for a landing, sorted by performance."""
    boats = conn.execute(
        "SELECT DISTINCT boat FROM trips WHERE landing=? ORDER BY boat",
        (landing,)
    ).fetchall()
    result = []
    for row in boats:
        s = _boat_stats(conn, row["boat"])
        if s:
            result.append({"boat": row["boat"], **s})
    result.sort(key=lambda x: (-x["win_rate"], -x["avg_tpad"]))
    return result


def _species_stats(conn: sqlite3.Connection, col: str) -> dict:
    """Return stats dict for a trophy species column."""
    top = conn.execute(f"""
        SELECT boat, landing, COUNT(*) as trips,
               ROUND(AVG(CASE WHEN trophy_per_angler_per_day>0
                               THEN trophy_per_angler_per_day END), 2) as avg_tpad
        FROM trips
        WHERE {col}>0 AND trophy_per_angler_per_day IS NOT NULL
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
        WHERE {col}>0 AND date>=? AND trophy_per_angler_per_day>0
        GROUP BY month
        ORDER BY month
    """, (cutoff,)).fetchall()
    total_trips = conn.execute(
        f"SELECT COUNT(*) FROM trips WHERE {col}>0"
    ).fetchone()[0]
    return {
        "top_boats": [dict(r) for r in top],
        "monthly":   [dict(r) for r in monthly],
        "total_trips": total_trips,
    }


# ── Shared HTML head/body helpers ─────────────────────────────────────────────

_MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _head(title: str, desc: str, canonical: str, og: dict, json_ld: dict | None,
          shared: dict) -> str:
    """Build the <head> block for a generated page."""
    og_image = og.get("image", "https://thetunatracker.com/logo.png")
    og_title = og.get("title", title)
    og_desc  = og.get("description", desc)
    canonical_full = f"https://thetunatracker.com{canonical}"

    ld_block = ""
    if json_ld:
        import json
        ld_block = (
            f'<script type="application/ld+json">\n'
            f'{json.dumps(json_ld, indent=2)}\n'
            f'</script>\n'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0ea5e9">
<base href="/">
<title>{title}</title>
<meta name="description" content="{_esc(desc)}">
<link rel="canonical" href="{canonical_full}">
<meta property="og:type"        content="website">
<meta property="og:site_name"   content="The Tuna Tracker">
<meta property="og:title"       content="{_esc(og_title)}">
<meta property="og:description" content="{_esc(og_desc)}">
<meta property="og:image"       content="{og_image}">
<meta property="og:url"         content="{canonical_full}">
<meta name="twitter:card"        content="summary_large_image">
<meta name="twitter:title"       content="{_esc(og_title)}">
<meta name="twitter:description" content="{_esc(og_desc)}">
<meta name="twitter:image"       content="{og_image}">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="logo.png">
<link rel="apple-touch-icon" href="logo.png">
{ld_block}<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css" crossorigin="anonymous">
<link rel="stylesheet" href="lib/leaflet-velocity/leaflet-velocity.css">
<link rel="stylesheet" href="styles.css?v={shared['styles_ver']}">
{shared['vessel_script']}
{shared['clerk_sdk']}
</head>"""


def _esc(s: str) -> str:
    """Escape HTML attribute special chars."""
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _body_wrap(seo_content: str, shared: dict) -> str:
    """Build the <body> block."""
    return f"""
<body>
<div id="seo-static" aria-hidden="true">
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


# ── Boat page ─────────────────────────────────────────────────────────────────

def _boat_page_html(boat: str, landing: str, stats: dict,
                    profile: dict | None, review: dict | None,
                    shared: dict) -> str:
    landing_slug = SD_LANDINGS.get(landing, "")
    canonical    = f"/sd/boat/{url_quote(boat)}"
    title  = f"{boat} — {landing} Fish Counts & Win Rate | Tuna Tracker"
    desc   = (
        f"{boat} has a {stats['win_rate']}% win rate and averages "
        f"{stats['avg_tpad']} trophy fish per angler. View {stats['total']} trips, "
        f"catch history, and upcoming schedule at {landing} in San Diego."
    )

    # OG image
    og_image = "https://thetunatracker.com/logo.png"
    if profile and profile.get("photo_url"):
        raw = profile["photo_url"]
        og_image = raw if raw.startswith("http") else f"https://thetunatracker.com/{raw.lstrip('/')}"

    # JSON-LD
    json_ld: dict | None = None
    if review and review.get("count", 0) >= 3:
        json_ld = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": boat,
            "description": desc,
            "url": f"https://thetunatracker.com{canonical}",
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": round(review["avg"], 1),
                "reviewCount": review["count"],
            },
        }
    else:
        json_ld = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": boat,
            "description": desc,
            "url": f"https://thetunatracker.com{canonical}",
        }

    # Species section
    species_rows = [(k, v) for k, v in stats["species"].items() if v > 0]
    species_section = ""
    if species_rows:
        lis = "".join(f"<li>{name}: {count:,} landed</li>" for name, count in species_rows)
        species_section = f"<section><h2>Species Breakdown</h2><ul>{lis}</ul></section>"

    landing_link = (
        f'<p><a href="/sd/landing/{landing_slug}">More boats at {_esc(landing)} →</a></p>'
        if landing_slug else ""
    )

    crumb = _breadcrumb([
        ("Tuna Tracker", "/"),
        ("Boats", "/sd/boats"),
        (boat, ""),
    ])

    seo_content = f"""<article>
{crumb}
<h1>{_esc(boat)}</h1>
<p>{_esc(boat)} is a sportfishing vessel at {_esc(landing)} in San Diego, CA.
   Based on {stats['total']} trips from {stats['first_year']} to {stats['last_year']},
   the boat has a {stats['win_rate']}% trophy fish win rate
   and averages {stats['avg_tpad']} fish per angler per day.</p>
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
{landing_link}
</article>"""

    head = _head(title, desc, canonical,
                 {"title": title, "description": desc, "image": og_image},
                 json_ld, shared)
    return head + _body_wrap(seo_content, shared)


# ── Landing page ──────────────────────────────────────────────────────────────

def _landing_page_html(landing: str, slug: str, boats: list[dict],
                       shared: dict) -> str:
    canonical = f"/sd/landing/{slug}"
    n = len(boats)
    title = f"{landing} — Fleet, Fish Counts & Boat Stats | Tuna Tracker"
    desc  = (
        f"All {n} boats at {landing} with win rates, catch history, and performance data. "
        f"San Diego sportfishing from {landing}."
    )

    json_ld = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": landing,
        "description": desc,
        "url": f"https://thetunatracker.com{canonical}",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "San Diego",
            "addressRegion": "CA",
            "addressCountry": "US",
        },
    }

    crumb = _breadcrumb([
        ("Tuna Tracker", "/"),
        ("Boats", "/sd/boats"),
        (landing, ""),
    ])

    rows_html = ""
    for b in boats:
        href = f"/sd/boat/{url_quote(b['boat'])}"
        rows_html += (
            f"<tr>"
            f"<td><a href=\"{href}\">{_esc(b['boat'])}</a></td>"
            f"<td>{b['win_rate']}%</td>"
            f"<td>{b['avg_tpad']}</td>"
            f"<td>{b['total']}</td>"
            f"</tr>\n"
        )

    seo_content = f"""<article>
{crumb}
<h1>{_esc(landing)}</h1>
<p>All {n} sportfishing boats at {_esc(landing)} in San Diego, CA,
   ranked by trophy fish win rate.</p>
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
    canonical = f"/sd/species/{slug}"
    title = f"San Diego {name} Fishing — Best Boats & Season | Tuna Tracker"
    desc  = (
        f"Which San Diego sportfishing boats catch the most {name}. "
        f"Historical performance data, seasonal calendar, and top boats by "
        f"average fish per angler."
    )

    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": desc,
        "url": f"https://thetunatracker.com{canonical}",
    }

    crumb = _breadcrumb([
        ("Tuna Tracker", "/"),
        (f"{name} Fishing", ""),
    ])

    # Top boats table
    top_rows = ""
    for i, b in enumerate(stats["top_boats"], 1):
        href = f"/sd/boat/{url_quote(b['boat'])}"
        top_rows += (
            f"<tr>"
            f"<td>{i}</td>"
            f"<td><a href=\"{href}\">{_esc(b['boat'])}</a></td>"
            f"<td>{_esc(b.get('landing', ''))}</td>"
            f"<td>{b.get('avg_tpad', '')}</td>"
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
    <tr><th>#</th><th>Boat</th><th>Landing</th><th>Avg Fish/Angler/Day</th><th>Trips</th></tr>
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
            f"<td>{m.get('avg_tpad', '')}</td>"
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
    <tr><th>Month</th><th>Avg Fish/Angler/Day</th><th>Trips</th></tr>
  </thead>
  <tbody>
{monthly_rows}  </tbody>
</table>
</section>"""

    seo_content = f"""<article>
{crumb}
<h1>San Diego {_esc(name)} Fishing</h1>
<p>Analysis of {_esc(name)} catches across all San Diego sportfishing landings.
   Based on {stats['total_trips']:,} recorded trips with {_esc(name.lower())} in the catch.</p>
{top_table}
{monthly_table}
</article>"""

    head = _head(title, desc, canonical,
                 {"title": title, "description": desc},
                 json_ld, shared)
    return head + _body_wrap(seo_content, shared)


# ── Entry point ───────────────────────────────────────────────────────────────

def generate_all_pages(conn: sqlite3.Connection, web_dir, index_path) -> None:
    """Generate all static pages. Called from export.py."""
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

    # ── Boat pages ────────────────────────────────────────────────────────────
    sd_boats = conn.execute("""
        SELECT DISTINCT boat, landing FROM trips
        WHERE landing IN ('H&M Landing', 'Fisherman''s Landing',
                          'Seaforth Sportfishing', 'Point Loma Sportfishing',
                          'Oceanside Sea Center')
        ORDER BY boat
    """).fetchall()
    seen_boats: set[str] = set()
    for row in sd_boats:
        boat, landing = row["boat"], row["landing"]
        if boat in seen_boats:
            continue
        seen_boats.add(boat)
        try:
            stats = _boat_stats(conn, boat)
            if not stats:
                continue
            html = _boat_page_html(boat, landing, stats, profiles.get(boat), reviews.get(boat), shared)
            out = Path(web_dir) / "sd" / "boat" / _safe_dir(boat) / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            n_boats += 1
        except Exception as e:
            log.warning("Boat page failed for %r: %s", boat, e)

    # ── Landing pages ─────────────────────────────────────────────────────────
    for landing, slug in SD_LANDINGS.items():
        try:
            boats = _landing_boats(conn, landing)
            if not boats:
                continue
            html = _landing_page_html(landing, slug, boats, shared)
            out = Path(web_dir) / "sd" / "landing" / slug / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            n_landings += 1
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
        except Exception as e:
            log.warning("Species page failed for %r: %s", name, e)

    log.info("generate_pages: %d boats, %d landings, %d species", n_boats, n_landings, n_species)
