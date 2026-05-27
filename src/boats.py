"""One-time scraper for boat profile pages from SD landing websites.

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
from datetime import datetime, timezone
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
}

LANDING_BASES = {
    "H&M Landing":           "https://www.hmlanding.com",
    "Fisherman's Landing":   "https://www.fishermanslanding.com",
    "Seaforth Sportfishing": "https://www.seaforthsportfishing.com",
    "Point Loma Sportfishing": "https://www.pointlomasportfishing.com",
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


def _find_specs(soup: BeautifulSoup) -> tuple[int | None, int | None, int | None]:
    """Returns (year_built, length_ft, passenger_capacity)."""
    year_built = length_ft = capacity = None
    full_text = soup.get_text(" ")

    m = re.search(r"\b(19|20)\d{2}\b", full_text)
    if m:
        y = int(m.group())
        if 1960 <= y <= 2030:
            year_built = y

    m = re.search(r"(\d{2,3})\s*(?:ft\.?|feet|foot)\b", full_text, re.I)
    if m:
        length_ft = int(m.group(1))

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
    profiles: list[dict] = []
    seen_urls: set[str] = set()
    matched_boats: set[str] = set()

    fleet_soup = _fetch(fleet_url)
    if fleet_soup:
        # Find all intra-site links that look like individual boat pages
        link_pattern = re.compile(r"/(boat|fleet|vessel)/|/boats?/[^/]+/?$", re.I)
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
    for boat in known_boats:
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

    return profiles


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
            "SELECT DISTINCT boat, landing FROM trips WHERE is_half_day=0 ORDER BY landing, boat"
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
