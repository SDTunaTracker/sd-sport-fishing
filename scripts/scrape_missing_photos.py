"""
One-off: scrape boat photos for H&M Landing and Point Loma Sportfishing
using their confirmed page structures.

Run from project root:
    .venv\Scripts\python.exe scripts\scrape_missing_photos.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json, time, logging, re
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
from bs4 import BeautifulSoup
urllib3.disable_warnings()

from src.db import connect

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / 'tracker.db'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36'}


def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, verify=False)
        r.raise_for_status()
        return BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        log.warning('  Fetch failed %s: %s', url, e)
        return None


# ── H&M Landing ───────────────────────────────────────────────────────────────
# Pages at hmlanding.com/boat/{slug}
# Photos are wp-content/uploads images; skip the sitewide catch-report image.

SITEWIDE_SKIP = ['legend-5-24-26']  # fragments that identify the sitewide image

HM_BOATS = [
    ('Daiwa Pacific',        'daiwa-pacific'),
    ('Excalibur',            'excalibur'),
    ('Grande',               'grande'),
    ('Horizon',              'horizon'),
    ('Legend',               'legend'),
    ('Little G',             'little-g'),
    ('Malihini',             'malihini'),
    ('Nautilus',             'nautilus'),
    ('Ocean Odyssey',        'ocean-odyssey'),
    ('Old Glory',            'old-glory'),
    ('Patriot (SD)',         'patriot'),
    ('Premier',              'premier'),
    ('Producer',             'producer'),
    ('Ranger 85',            'ranger-85'),
    ('Red Rooster III',      'red-rooster-iii'),
    ('Reel Champion',        'reel-champion'),
    ('Relentless',           'relentless'),
    ('Sea Adventure 80',     'sea-adventure-80'),
    ('Spirit of Adventure',  'spirit-of-adventure'),
    ('Top Gun 80',           'top-gun-80'),
    ('Tradition',            'tradition'),
    ('Vendetta 2',           'vendetta2'),
]

def _hm_photo(soup):
    for img in soup.find_all('img'):
        src = (img.get('src') or '').strip()
        if not src:
            continue
        if 'wp-content/uploads' not in src:
            continue
        if any(skip in src for skip in SITEWIDE_SKIP):
            continue
        if any(x in src.lower() for x in ['logo', 'icon', 'sprite']):
            continue
        # swap 250x250 thumbnail for full size if available
        src = re.sub(r'-\d+x\d+(\.\w+)$', r'\1', src)
        return src
    return None


def scrape_hm(conn):
    existing = {r[0] for r in conn.execute(
        "SELECT boat FROM boat_profiles WHERE landing='H&M Landing' AND photo_url IS NOT NULL AND photo_url != ''"
    ).fetchall()}

    saved = 0
    for boat, slug in HM_BOATS:
        if boat in existing:
            log.info('  [skip] %s (already has photo)', boat)
            continue
        url = f'https://www.hmlanding.com/boat/{slug}'
        soup = fetch(url)
        if not soup:
            log.info('  [miss] %s — page not found', boat)
            time.sleep(0.4)
            continue
        photo = _hm_photo(soup)
        if not photo:
            log.info('  [miss] %s — no photo on page', boat)
            time.sleep(0.4)
            continue

        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO boat_profiles (boat, landing, photo_url, source_url, scraped_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(boat, landing) DO UPDATE SET
                photo_url  = excluded.photo_url,
                source_url = excluded.source_url,
                scraped_at = excluded.scraped_at
        """, (boat, 'H&M Landing', photo, url, now))
        conn.commit()
        log.info('  [save] %s -> %s', boat, photo)
        saved += 1
        time.sleep(0.4)

    return saved


# ── Point Loma Sportfishing ───────────────────────────────────────────────────
# Pages at pointlomasportfishing.com/fleet/{slug}.php
# Photos are at /media/boats/ path.

PLOMA_BOATS = [
    ('American Angler', 'americanangler'),
    ('Daily Double',    'dailydouble'),
    ('Game Changer',    'gamechanger'),
    ('Independence',    'independence'),
    ('Intrepid',        'intrepid'),
    ('Mission Belle',   'missionbelle'),
    ('New Lo-An',       'newloan'),
    ('Point Loma',      'pointloma'),
    ('Sauerfish',       'sauerfish'),
    ('Success',         'success'),
    ('Vagabond',        'vagabond'),
]
PLOMA_BASE = 'https://www.pointlomasportfishing.com'


def _ploma_photo(soup):
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if '/media/boats/' in src:
            return PLOMA_BASE + src if src.startswith('/') else src
    return None


def scrape_pointloma(conn):
    existing = {r[0] for r in conn.execute(
        "SELECT boat FROM boat_profiles WHERE landing='Point Loma Sportfishing' AND photo_url IS NOT NULL AND photo_url != ''"
    ).fetchall()}

    saved = 0
    for boat, slug in PLOMA_BOATS:
        if boat in existing:
            log.info('  [skip] %s (already has photo)', boat)
            continue
        url = f'{PLOMA_BASE}/fleet/{slug}.php'
        soup = fetch(url)
        if not soup:
            log.info('  [miss] %s — page not found', boat)
            time.sleep(0.4)
            continue
        photo = _ploma_photo(soup)
        if not photo:
            log.info('  [miss] %s — no photo on page', boat)
            time.sleep(0.4)
            continue

        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO boat_profiles (boat, landing, photo_url, source_url, scraped_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(boat, landing) DO UPDATE SET
                photo_url  = excluded.photo_url,
                source_url = excluded.source_url,
                scraped_at = excluded.scraped_at
        """, (boat, 'Point Loma Sportfishing', photo, url, now))
        conn.commit()
        log.info('  [save] %s -> %s', boat, photo)
        saved += 1
        time.sleep(0.4)

    return saved


def main():
    with connect(DB_PATH) as conn:
        log.info('H&M Landing:')
        hm = scrape_hm(conn)

        log.info('\nPoint Loma Sportfishing:')
        pl = scrape_pointloma(conn)

    log.info('\nDone. H&M: %d saved, Point Loma: %d saved', hm, pl)

    # Summary
    with connect(DB_PATH) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM boat_profiles WHERE photo_url IS NOT NULL AND photo_url != ''"
        ).fetchone()[0]
        log.info('Total boats with photos in DB: %d', total)


if __name__ == '__main__':
    main()
