"""Scrape boat photos from landing websites and store locally.

Downloads photos to web/images/boats/ and upserts records into boat_profiles.

Usage:
    python -m src.scrape_boat_photos              # all landings
    python -m src.scrape_boat_photos --landing hm
    python -m src.scrape_boat_photos --landing seaforth
    python -m src.scrape_boat_photos --landing fishermans
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT    = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
IMG_DIR = ROOT / "web" / "images" / "boats"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

_BG_URL_RE = re.compile(r"background-image\s*:\s*url\(['\"]?([^'\")\s]+)['\"]?\)", re.I)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _extract_bg_url(style: str) -> str | None:
    m = _BG_URL_RE.search(style or "")
    return m.group(1) if m else None


def _make_absolute(url: str, page_url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        p = urlparse(page_url)
        return f"{p.scheme}://{p.netloc}{url}"
    if not url.startswith("http"):
        p = urlparse(page_url)
        return f"{p.scheme}://{p.netloc}/{url.lstrip('/')}"
    return url


def _safe_filename(boat_name: str) -> str:
    return (boat_name.lower()
            .replace(" ", "_")
            .replace("&", "and")
            .replace("'", "")
            .replace("/", "_")
            .replace(".", "")
            .strip("_"))


def download_boat_photo(boat_name: str, photo_url: str) -> str | None:
    """Download a boat photo to web/images/boats/. Returns relative path or None."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(boat_name)
    ext  = os.path.splitext(urlparse(photo_url).path)[1]
    if not ext or len(ext) > 5:
        ext = ".jpg"
    local_path = IMG_DIR / f"{safe}{ext}"
    try:
        r = requests.get(photo_url, headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        local_path.write_bytes(r.content)
        return f"images/boats/{safe}{ext}"
    except Exception as e:
        print(f"    Download failed for {boat_name}: {e}")
        return None


def _upsert_profile(conn: sqlite3.Connection, boat: str, landing: str,
                    local_path: str, source_url: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("""
        INSERT INTO boat_profiles (boat, landing, photo_url, source_url, scraped_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(boat, landing) DO UPDATE SET
            photo_url  = excluded.photo_url,
            source_url = excluded.source_url,
            scraped_at = excluded.scraped_at
    """, (boat, landing, local_path, source_url, now))


def _match_boat(conn: sqlite3.Connection, boat_name: str, landing: str) -> str | None:
    """Return the exact boat name from trips table, or None."""
    row = conn.execute(
        "SELECT DISTINCT boat FROM trips WHERE landing = ? AND boat = ?",
        (landing, boat_name)
    ).fetchone()
    if row:
        return row["boat"]
    row = conn.execute(
        "SELECT DISTINCT boat FROM trips WHERE landing = ? AND LOWER(boat) = LOWER(?)",
        (landing, boat_name)
    ).fetchone()
    return row["boat"] if row else None


# ── H&M Landing ──────────────────────────────────────────────────────────────

def scrape_hm_fleet() -> list[dict]:
    """Scrape H&M charter fleet page. Photos are CSS background-images on div.boat-list-header."""
    url  = "https://www.hmlanding.com/charter-fleet"
    html = requests.get(url, headers={"User-Agent": UA}, timeout=30).text
    soup = BeautifulSoup(html, "lxml")
    boats = []
    for card in soup.select("li.grid-item"):
        name_el = card.select_one("h2 a")
        if not name_el:
            continue
        boat_name = name_el.get_text(strip=True)
        header    = card.select_one("div.boat-list-header")
        if not header:
            continue
        img_url = _extract_bg_url(header.get("style", ""))
        if not img_url:
            continue
        img_url    = _make_absolute(img_url, url)
        href       = name_el.get("href") or ""
        detail_url = _make_absolute(href, url) if href else url
        boats.append({"name": boat_name, "photo_url": img_url, "detail_url": detail_url})
    return boats


def update_boat_photos_hm(conn: sqlite3.Connection) -> tuple[int, int, int]:
    boats = scrape_hm_fleet()
    print(f"  Found {len(boats)} boats on H&M fleet page")
    updated = failed = skipped = 0
    for boat in boats:
        matched = _match_boat(conn, boat["name"], "H&M Landing")
        if not matched:
            print(f"    SKIP '{boat['name']}' not in trips")
            skipped += 1
            continue
        local = download_boat_photo(matched, boat["photo_url"])
        if not local:
            failed += 1
            continue
        _upsert_profile(conn, matched, "H&M Landing", local, boat["detail_url"])
        print(f"    OK {matched}")
        updated += 1
    return updated, failed, skipped


# ── Seaforth Sportfishing ─────────────────────────────────────────────────────

def scrape_seaforth_fleet() -> list[dict]:
    """Scrape Seaforth fleet.php. Photos are CSS background-images on div.feature-img."""
    url  = "https://www.seaforthlanding.com/fleet.php"
    html = requests.get(url, headers={"User-Agent": UA}, timeout=30).text
    soup = BeautifulSoup(html, "lxml")
    boats = []
    for card in soup.select("div.feature-col"):
        name_el = card.select_one("h3.feature-title")
        if not name_el:
            continue
        boat_name = name_el.get_text(strip=True)
        img_div   = card.select_one("div.feature-img")
        if not img_div:
            continue
        img_url = _extract_bg_url(img_div.get("style", ""))
        if not img_url:
            continue
        img_url    = _make_absolute(img_url, url)
        link       = card.select_one("a[href]")
        detail_url = _make_absolute(link["href"], url) if link else url
        boats.append({"name": boat_name, "photo_url": img_url, "detail_url": detail_url})
    return boats


def update_boat_photos_seaforth(conn: sqlite3.Connection) -> tuple[int, int, int]:
    boats = scrape_seaforth_fleet()
    print(f"  Found {len(boats)} boats on Seaforth fleet page")
    updated = failed = skipped = 0
    for boat in boats:
        matched = _match_boat(conn, boat["name"], "Seaforth Sportfishing")
        if not matched:
            print(f"    SKIP '{boat['name']}' not in trips")
            skipped += 1
            continue
        local = download_boat_photo(matched, boat["photo_url"])
        if not local:
            failed += 1
            continue
        _upsert_profile(conn, matched, "Seaforth Sportfishing", local, boat["detail_url"])
        print(f"    OK {matched}")
        updated += 1
    return updated, failed, skipped


# ── Fisherman's Landing ───────────────────────────────────────────────────────

def _fl_slugs(boat_name: str) -> list[str]:
    base = re.sub(r"[^a-z0-9\s]", "", boat_name.lower()).strip()
    return list(dict.fromkeys([
        re.sub(r"\s+", "-", base),   # pacific-queen
        re.sub(r"\s+", "", base),     # pacificqueen
        re.sub(r"\s+", "_", base),    # pacific_queen
    ]))


def _try_fl_boat_page(boat_name: str) -> dict | None:
    """Try individual FL boat pages at /boats/{slug}.php. Returns {photo_url, detail_url} or None."""
    base = "https://www.fishermanslanding.com"
    for slug in _fl_slugs(boat_name):
        url = f"{base}/boats/{slug}.php"
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
            if r.status_code != 200:
                continue
            if "not found" in r.text[:2000].lower():
                continue
            soup    = BeautifulSoup(r.text, "lxml")
            img_div = soup.select_one("div.feature-img")
            if img_div:
                img_url = _extract_bg_url(img_div.get("style", ""))
                if img_url:
                    return {"photo_url": _make_absolute(img_url, url), "detail_url": url}
            # Fallback: first non-logo img tag
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if not src or any(s in src.lower() for s in ("logo", "icon", "nav", "header", "button")):
                    continue
                return {"photo_url": _make_absolute(src, url), "detail_url": url}
        except Exception:
            continue
    return None


def _scrape_fl_homepage() -> dict[str, dict]:
    """Scrape FL homepage for featured boat cards. Returns {boat_name_lower: {photo_url, detail_url}}."""
    url = "https://www.fishermanslanding.com/"
    try:
        html = requests.get(url, headers={"User-Agent": UA}, timeout=30).text
    except Exception:
        return {}
    soup  = BeautifulSoup(html, "lxml")
    found = {}
    for card in soup.select("div.feature-col"):
        name_el = card.select_one("h3.feature-title")
        if not name_el:
            continue
        boat_name = name_el.get_text(strip=True)
        img_div   = card.select_one("div.feature-img")
        if not img_div:
            continue
        img_url = _extract_bg_url(img_div.get("style", ""))
        if not img_url:
            continue
        img_url    = _make_absolute(img_url, url)
        link       = card.select_one("a[href]")
        detail_url = _make_absolute(link["href"], url) if link else url
        found[boat_name.lower()] = {"photo_url": img_url, "detail_url": detail_url}
    return found


def update_boat_photos_fishermans(conn: sqlite3.Connection) -> tuple[int, int, int]:
    db_boats = conn.execute(
        "SELECT DISTINCT boat FROM trips WHERE landing = \"Fisherman's Landing\""
    ).fetchall()
    print(f"  Checking {len(db_boats)} FL boats")

    homepage = _scrape_fl_homepage()
    print(f"  Found {len(homepage)} boat(s) on FL homepage")

    updated = failed = skipped = 0
    for row in db_boats:
        boat_name = row["boat"]
        result    = homepage.get(boat_name.lower())
        if not result:
            result = _try_fl_boat_page(boat_name)
            time.sleep(1)
        if not result:
            print(f"    SKIP {boat_name} — no photo found")
            skipped += 1
            continue
        local = download_boat_photo(boat_name, result["photo_url"])
        if not local:
            failed += 1
            continue
        _upsert_profile(conn, boat_name, "Fisherman's Landing", local, result["detail_url"])
        print(f"    OK {boat_name}")
        updated += 1

    return updated, failed, skipped


# ── Combined runner ───────────────────────────────────────────────────────────

def update_all_boat_photos(conn: sqlite3.Connection) -> None:
    for label, fn in [
        ("H&M Landing",          update_boat_photos_hm),
        ("Seaforth Sportfishing", update_boat_photos_seaforth),
        ("Fisherman's Landing",   update_boat_photos_fishermans),
    ]:
        print(f"\n=== {label} ===")
        try:
            u, f, s = fn(conn)
            print(f"  => updated={u}  failed={f}  skipped={s}")
        except Exception as e:
            print(f"  ERROR: {e}")
    conn.commit()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--landing", choices=["hm", "seaforth", "fishermans", "all"], default="all")
    args = p.parse_args(argv)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        if args.landing == "hm":
            print("=== H&M Landing ===")
            u, f, s = update_boat_photos_hm(conn)
            print(f"=> updated={u}  failed={f}  skipped={s}")
        elif args.landing == "seaforth":
            print("=== Seaforth Sportfishing ===")
            u, f, s = update_boat_photos_seaforth(conn)
            print(f"=> updated={u}  failed={f}  skipped={s}")
        elif args.landing == "fishermans":
            print("=== Fisherman's Landing ===")
            u, f, s = update_boat_photos_fishermans(conn)
            print(f"=> updated={u}  failed={f}  skipped={s}")
        else:
            update_all_boat_photos(conn)
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
