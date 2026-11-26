"""One-time scraper for boat profile pages from SD and OC/LA landing websites.

Scrapes photos, descriptions, captains, and specs from each landing's fleet
page and stores results in the boat_profiles table.

Usage:
    python -m src.boats scrape [--force] [--landing LANDING] [--boat BOAT]
    python -m src.boats list
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .db import connect

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / "tracker.db"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Landing fleet page URLs (direct boat list pages, not fishcounts.com)
FLEET_URLS = {
    "H&M Landing":           "https://www.hmlanding.com/boats/",
    "Fisherman's Landing":   "https://www.fishermanslanding.com/boats/",
    "Seaforth Sportfishing": "https://www.seaforthsportfishing.com/fleet/",
    "Point Loma Sportfishing": "https://www.pointlomasportfishing.com/fleet/",
    # OC/LA
    "22nd Street Landing": "https://www.22ndstreet.com/fleet.php",
    "Pierpoint Landing": "https://www.pierpoint.net/fleet.php",
    "Redondo Beach Sportfishing": "https://www.redondosportfishing.com/fleet.php",
    "Ventura Harbor Sportfishing": "https://www.venturasportfishing.com/fleet.php",
    "Dana Wharf Sportfishing": "https://danawharf.com/our-boats/",
    "Channel Islands Sportfishing": "https://www.channelislandssportfishing.com/charter-boats/",
    "Marina Del Rey Sportfishing": "http://www.marinadelreysportfishing.com/the-boats/",
}

OCLA_LANDINGS = {
    "22nd Street Landing", "Pierpoint Landing", "Redondo Beach Sportfishing",
    "Ventura Harbor Sportfishing", "Dana Wharf Sportfishing",
    "Channel Islands Sportfishing", "Marina Del Rey Sportfishing",
}

LANDING_BASES = {
    "H&M Landing":           "https://www.hmlanding.com",
    "Fisherman's Landing":   "https://www.fishermanslanding.com",
    "Seaforth Sportfishing": "https://www.seaforthsportfishing.com",
    "Point Loma Sportfishing": "https://www.pointlomasportfishing.com",
    # OC/LA
    "22nd Street Landing": "https://www.22ndstreet.com",
    "Pierpoint Landing": "https://www.pierpoint.net",
    "Redondo Beach Sportfishing": "https://www.redondosportfishing.com",
    "Ventura Harbor Sportfishing": "https://www.venturasportfishing.com",
    "Dana Wharf Sportfishing": "https://danawharf.com",
    "Channel Islands Sportfishing": "https://www.channelislandssportfishing.com",
    "Marina Del Rey Sportfishing": "http://www.marinadelreysportfishing.com",
}


def _fetch(url: str, timeout: int = 15) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.debug("Fetch failed for %s: %s", url, e)
        return None


def _abs_url(base: str, src: str | None) -> str | None:
    if not src:
        return None
    src = src.strip()
    if src.startswith("http"):
        return src
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        from urllib.parse import urlparse
        p = urlparse(base)
        return f"{p.scheme}://{p.netloc}{src}"
    from urllib.parse import urljoin
    return urljoin(base, src)


def _text(tag) -> str:
    if not tag:
        return ""
    return " ".join(tag.get_text(" ", strip=True).split())


def _parse_int(s: str) -> int | None:
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else None


def _find_photo(soup: BeautifulSoup, page_url: str) -> str | None:
    """Find the best boat photo on the page."""
    # 1. Semantic selectors first
    for sel in [
        ".boat-photo img", ".hero-image img", ".boat-hero img",
        ".boat-image img", ".featured-image img", ".wp-post-image",
        "img.boat-photo", ".fleet-photo img", "#boat-photo",
        ".hero img", "header img",
    ]:
        tag = soup.select_one(sel)
        if tag:
            src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src") or tag.get("data-original")
            url = _abs_url(page_url, src)
            if url:
                return url

    # 2. Largest declared-size img that looks like a boat photo
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        low = src.lower()
        if any(x in low for x in ["logo", "icon", "sprite", "banner", "bg", "background"]):
            continue
        w = img.get("width") or "0"
        try:
            if int(str(w).replace("px", "")) > 300:
                return _abs_url(page_url, src)
        except ValueError:
            pass

    # 3. First real-looking photo
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        low = src.lower()
        if any(x in low for x in ["logo", "icon", "sprite"]):
            continue
        if any(ext in low for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return _abs_url(page_url, src)

    return None


def _find_description(soup: BeautifulSoup) -> str | None:
    for sel in [
        ".boat-description", ".about-boat", ".boat-about", ".description",
        ".entry-content p", "article .content p", ".boat-info p",
        ".page-content p", "main p",
    ]:
        tag = soup.select_one(sel)
        if tag:
            t = _text(tag)
            if len(t) > 50:
                return t[:600]
    return None


def _find_captains(soup: BeautifulSoup) -> list[str]:
    captains = []

    # Semantic selectors
    for sel in [
        ".captain-name", ".captain h3", ".captain h4",
        ".captains li", "[class*='captain'] h3", "[class*='captain'] h4",
        ".crew h3", ".crew h4", ".crew-member h4",
    ]:
        for tag in soup.select(sel):
            name = _text(tag)
            if name and len(name) < 60:
                captains.append(name)

    if captains:
        return list(dict.fromkeys(captains))  # dedupe, preserve order

    # Text heuristic — look for "Captain: X" or "Captains: X, Y"
    for tag in soup.find_all(["p", "li", "span", "div", "td"]):
        t = _text(tag)
        m = re.search(
            r"[Cc]aptains?\s*:?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:[,/&]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)*)",
            t,
        )
        if m:
            raw = m.group(1)
            captains = [c.strip() for c in re.split(r"[,/&]", raw) if c.strip()]
            break

    return captains


# A year counts as year_built only next to "built" / "year built" / "year:".
# Landing pages are full of other years ("Summer 2026 Charter Rates").
_YEAR_BUILT_RES = (
    re.compile(r"\b(?:built|launched|constructed)\b[^.\d]{0,40}?\b((?:19|20)\d{2})\b", re.I),
    re.compile(r"\byear(?:\s+built)?\s*[:\-]\s*((?:19|20)\d{2})\b", re.I),
    re.compile(r"\byear\s+built\s+((?:19|20)\d{2})\b", re.I),
)
_FT = r"(?:ft\.?|feet|foot|')"
# Length overall first ("88 feet in overall length", "LOA: 88'"). The spec
# line "85 ft. x 22 ft." is often the registered length, so it's a fallback.
_LOA_RES = (
    re.compile(rf"(\d{{2,3}})\s*{_FT}\s*(?:in\s+)?(?:overall|LOA\b|length\s+overall)", re.I),
    re.compile(rf"(?:\bLOA\b|length\s+overall|overall\s+length)\s*[:\-]?\s*(?:of\s+)?(\d{{2,3}})\s*{_FT}", re.I),
    re.compile(rf"(\d{{2,3}})\s*{_FT}\s*(?:in\s+length|long)\b", re.I),
)
# Spec line "85 x 22 Feet" / "85 ft. x 22 ft.": length is the first number.
_SPEC_RE = re.compile(rf"\b(\d{{2,3}})\s*(?:ft\.?|')?\s*x\s*\d{{1,3}}\s*{_FT}", re.I)
_ANY_FT_RE = re.compile(r"(\d{2,3})\s*(?:ft\.?|feet|foot)(?![a-z])", re.I)


def find_year_built(text: str, today: date | None = None) -> int | None:
    """Year next to "built"/"year", in 1900..last year; otherwise None."""
    last_year = (today or date.today()).year - 1
    for rx in _YEAR_BUILT_RES:
        for m in rx.finditer(text):
            y = int(m.group(1))
            if 1900 <= y <= last_year:
                return y
    return None


def find_length_ft(text: str) -> int | None:
    """Length overall when the page states it, else the first "N ft" figure."""
    for rx in (*_LOA_RES, _SPEC_RE, _ANY_FT_RE):
        for m in rx.finditer(text):
            v = int(m.group(1))
            if 15 <= v <= 250:
                return v
    return None


def _find_specs(soup: BeautifulSoup) -> tuple[int | None, int | None, int | None]:
    """Returns (year_built, length_ft, passenger_capacity)."""
    capacity = None
    full_text = re.sub(r"\s+", " ", soup.get_text(" "))
    year_built = find_year_built(full_text)
    length_ft = find_length_ft(full_text)

    m = re.search(r"(\d+)\s*(?:passengers?|anglers?|persons?)\b", full_text, re.I)
    if m:
        v = int(m.group(1))
        if 5 <= v <= 200:
            capacity = v

    return year_built, length_ft, capacity


def _parse_boat_page(soup: BeautifulSoup, page_url: str, boat_name: str, landing: str) -> dict | None:
    photo = _find_photo(soup, page_url)
    description = _find_description(soup)
    captains = _find_captains(soup)
    year_built, length_ft, capacity = _find_specs(soup)

    if not photo and not description and not captains:
        return None

    return {
        "boat": boat_name,
        "landing": landing,
        "photo_url": photo,
        "description": description,
        "captains": json.dumps(captains) if captains else None,
        "year_built": year_built,
        "length_ft": length_ft,
        "passenger_capacity": capacity,
        "fishing_areas": None,
        "tackle_notes": None,
        "amenities": None,
        "source_url": page_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def _scrape_landing(landing: str, known_boats: list[str]) -> list[dict]:
    """Scrape boat profiles for one landing. Returns list of profile dicts."""
    base = LANDING_BASES[landing]
    fleet_url = FLEET_URLS[landing]
    # OC/LA fleet pages link to every page on the site; only follow boat
    # pages and only save names that match a boat in the fish counts.
    strict = landing in OCLA_LANDINGS
    profiles: list[dict] = []
    seen_urls: set[str] = set()
    matched_boats: set[str] = set()

    fleet_soup = _fetch(fleet_url)
    if fleet_soup:
        # Find all intra-site links that look like individual boat pages
        # SD sites use /boats/<slug>/; OC/LA sites on the fishingreservations
        # CMS use boat.php?b=<slug>, Dana Wharf /our-boats/<slug>/.
        link_pattern = re.compile(
            r"/(boat|fleet|vessel)/|/boats?/[^/]+/?$|boat\.php\?b=|/(our|the|charter)-boats/[^/]+/?$", re.I)
        candidate_links = []
        for a in fleet_soup.find_all("a", href=True):
            href = a["href"]
            abs_href = _abs_url(fleet_url, href)
            if not abs_href:
                continue
            if abs_href == fleet_url or abs_href == fleet_url.rstrip("/"):
                continue
            if base not in abs_href:
                continue
            if abs_href in seen_urls:
                continue
            if strict and not link_pattern.search(abs_href):
                continue
            seen_urls.add(abs_href)
            candidate_links.append(abs_href)

        for link in candidate_links:
            detail = _fetch(link)
            if not detail:
                continue
            h1 = detail.find("h1")
            name = _text(h1) if h1 else None
            if not name:
                continue
            if strict:
                # Keep only pages that are about a boat this landing runs, and
                # store it under the name the fish counts use.
                key = _norm_name(name)
                hit = next((b for b in known_boats
                            if _norm_name(b) and (_norm_name(b) == key or _norm_name(b) in key)), None)
                if hit is None:
                    continue
                name = hit
            p = _parse_boat_page(detail, link, name, landing)
            if p:
                profiles.append(p)
                matched_boats.add(name.lower())

    # Fallback: try slug-based URLs for known boats not yet matched
    slug_templates = [
        lambda b: f"{base}/boats/{_slug(b)}/",
        lambda b: f"{base}/boats/{_slug(b)}.php",
        lambda b: f"{base}/fleet/{_slug(b)}/",
        lambda b: f"{base}/{_slug(b)}/",
    ]
    for boat in ([] if strict else known_boats):  # guessed URLs hit catch-all pages on OC/LA sites
        if boat.lower() in matched_boats:
            continue
        for tmpl in slug_templates:
            url = tmpl(boat)
            detail = _fetch(url)
            if not detail:
                continue
            p = _parse_boat_page(detail, url, boat, landing)
            if p:
                profiles.append(p)
                matched_boats.add(boat.lower())
                break

    if strict and len(profiles) >= 3:
        # A value shared by every boat came from site chrome, not the boat page
        # (Dana Wharf: captain "Cruises", capacity 6 on every boat).
        for field in ("captains", "passenger_capacity", "length_ft", "year_built"):
            vals = {json.dumps(pr.get(field)) for pr in profiles}
            if len(vals) == 1:
                for pr in profiles:
                    pr[field] = None
    return profiles


def _norm_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9]+", "", name.lower())
    return re.sub(r"^the", "", n)


def _slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r"['\"]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _upsert_profile(conn, profile: dict) -> None:
    conn.execute("""
        INSERT INTO boat_profiles
            (boat, landing, photo_url, description, captains, year_built,
             length_ft, passenger_capacity, fishing_areas, tackle_notes,
             amenities, source_url, scraped_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(boat, landing) DO UPDATE SET
            photo_url          = excluded.photo_url,
            description        = excluded.description,
            captains           = excluded.captains,
            year_built         = excluded.year_built,
            length_ft          = excluded.length_ft,
            passenger_capacity = excluded.passenger_capacity,
            source_url         = excluded.source_url,
            scraped_at         = excluded.scraped_at
    """, (
        profile["boat"], profile["landing"], profile["photo_url"],
        profile["description"], profile["captains"], profile["year_built"],
        profile["length_ft"], profile["passenger_capacity"],
        profile["fishing_areas"], profile["tackle_notes"], profile["amenities"],
        profile["source_url"], profile["scraped_at"],
    ))


def scrape_all(
    force: bool = False,
    landing_filter: str | None = None,
    boat_filter: str | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT DISTINCT boat, landing FROM trips"
            " WHERE is_half_day=0 OR region='oc_la' ORDER BY landing, boat"
        ).fetchall()
        by_landing: dict[str, list[str]] = {}
        for r in rows:
            by_landing.setdefault(r["landing"], []).append(r["boat"])

        for landing in FLEET_URLS:
            if landing_filter and landing_filter.lower() not in landing.lower():
                continue
            known = by_landing.get(landing, [])
            if boat_filter:
                known = [b for b in known if boat_filter.lower() in b.lower()]
            if not force:
                already = {r["boat"] for r in conn.execute(
                    "SELECT boat FROM boat_profiles WHERE landing=?", (landing,)
                ).fetchall()}
                known = [b for b in known if b not in already]

            log.info("Scraping %s (%d known boats)...", landing, len(known))
            try:
                profiles = _scrape_landing(landing, known)
            except Exception as e:
                log.error("Scraper for %s failed: %s", landing, e)
                profiles = []

            saved = 0
            for p in profiles:
                if boat_filter and boat_filter.lower() not in p["boat"].lower():
                    continue
                try:
                    _upsert_profile(conn, p)
                    saved += 1
                    log.info("  Saved: %s @ %s (photo=%s)", p["boat"], landing, bool(p["photo_url"]))
                except Exception as e:
                    log.warning("  Failed to save %s: %s", p["boat"], e)
            counts[landing] = saved

    return counts


def _cmd_list() -> None:
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT landing, boat, photo_url IS NOT NULL AS has_photo,"
            " captains IS NOT NULL AS has_captains, scraped_at"
            " FROM boat_profiles ORDER BY landing, boat"
        ).fetchall()
    if not rows:
        print("No boat profiles in database yet. Run: python -m src.boats scrape")
        return
    print(f"{'Landing':<28} {'Boat':<28} {'Photo':>5}  {'Capts':>5}  Scraped")
    print("-" * 80)
    for r in rows:
        at = (r["scraped_at"] or "")[:10]
        print(f"{r['landing']:<28} {r['boat']:<28} {'✓' if r['has_photo'] else '—':>5}  "
              f"{'✓' if r['has_captains'] else '—':>5}  {at}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scrape boat profile pages from landing websites")
    sub = parser.add_subparsers(dest="cmd")

    sp = sub.add_parser("scrape", help="Scrape boat profiles (run once or with --force)")
    sp.add_argument("--force", action="store_true", help="Re-scrape boats already in DB")
    sp.add_argument("--landing", help="Limit to one landing (partial name match)")
    sp.add_argument("--boat",    help="Limit to one boat (partial name match)")
    sp.add_argument("--verbose", "-v", action="store_true")

    sub.add_parser("list", help="List boat profiles currently in the database")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    # Suppress noisy SSL warnings from verify=False
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if args.cmd == "scrape":
        counts = scrape_all(
            force=args.force,
            landing_filter=args.landing,
            boat_filter=args.boat,
        )
        total = sum(counts.values())
        for landing, n in sorted(counts.items()):
            print(f"  {landing}: {n} profiles saved")
        print(f"Total: {total}")
    elif args.cmd == "list":
        _cmd_list()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
