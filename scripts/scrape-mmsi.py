"""
Automated MMSI lookup for SD sportfishing boats via VesselFinder.

For each boat with a null MMSI, searches VesselFinder by name, then fetches
the detail page for each candidate to verify flag, type, and port.  Scores
each match against multiple signals and writes results to:

  data/boat-mmsi-auto.json    (confidence >= 75 -- safe to import)
  data/boat-mmsi-review.json  (confidence 50-74 -- human review needed)

Usage:
    .venv/Scripts/python.exe scripts/scrape-mmsi.py
    .venv/Scripts/python.exe scripts/scrape-mmsi.py --test     # validate known boats
    .venv/Scripts/python.exe scripts/scrape-mmsi.py --dry-run  # print, don't save
    .venv/Scripts/python.exe scripts/scrape-mmsi.py --boat "San Diego"

Requires: requests, beautifulsoup4
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
except ImportError:
    pass

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: pip install requests beautifulsoup4")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MMSI_FILE   = ROOT / 'data' / 'boat-mmsi.json'
AUTO_FILE   = ROOT / 'data' / 'boat-mmsi-auto.json'
REVIEW_FILE = ROOT / 'data' / 'boat-mmsi-review.json'
CACHE_FILE  = ROOT / 'data' / '.mmsi-search-cache.json'

HEADERS = {
    'User-Agent':      ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/124.0 Safari/537.36'),
    'Accept':          'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

RATE_LIMIT = 3.5  # seconds between HTTP requests
HIGH_CONF  = 75
MED_CONF   = 50

# US vessels use Maritime Identification Digits 338, 366-369
US_MMSI_RE = re.compile(r'^(338|366|367|368|369)\d{6}$')

SOCAL_PORTS    = ['san diego', 'mission bay', 'oceanside', 'long beach',
                  'newport', 'dana point', 'ensenada', 'san pedro', 'california']
FISHING_TAGS   = ['fishing', 'sportfish', 'charter']
PASSENGER_TAGS = ['passenger', 'pleasure']  # sportfishing boats often appear as "Pleasure craft"
LANDING_NAMES  = ["fisherman's", 'seaforth', 'h&m', 'point loma', 'hm landing']

# Typical length range for SD sportfishing boats (roughly 40-160 ft -> 12-50 m)
MIN_LEN_M = 12
MAX_LEN_M = 50

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def fuzzy(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

def normalize(name: str) -> str:
    """Strip vessel-type prefixes and parenthetical suffixes."""
    name = re.sub(r'\s*\([^)]{1,6}\)', '', name)
    for pat in [r'\bSPORTFISHING\b', r'\bSPORT FISHING\b', r'\bF/V\b',
                r'\bM/V\b', r'\bS/V\b', r'\bMV\b', r'\bFV\b', r'\bTHE\b']:
        name = re.sub(pat, '', name, flags=re.IGNORECASE)
    return ' '.join(name.split())

def is_valid_mmsi(s: str) -> bool:
    return bool(re.fullmatch(r'\d{9}', s))

def cache_key(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:14]

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}

def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding='utf-8')

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_last_req: float = 0.0

def get(url: str, params: dict | None = None) -> requests.Response | None:
    global _last_req
    wait = RATE_LIMIT - (time.time() - _last_req)
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        _last_req = time.time()
        if r.status_code == 429:
            print("    [429 rate-limited] sleeping 90s ...")
            time.sleep(90)
            return None
        if r.status_code in (403, 503):
            print(f"    [{r.status_code}] blocked: {url[:70]}")
            return None
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        print(f"    [error] {type(e).__name__}: {e}")
        return None

# ---------------------------------------------------------------------------
# VesselFinder search
# ---------------------------------------------------------------------------

def search_vf(boat_name: str, cache: dict) -> list[dict]:
    """
    Search VesselFinder /vessels?name=NAME.
    Returns candidates with mmsi, vessel_name, vessel_type, size_m.
    Only includes entries whose detail URL contains a valid 9-digit MMSI.
    """
    key = 'vf_search:' + cache_key(boat_name)
    if key in cache:
        return cache[key]

    r = get('https://www.vesselfinder.com/vessels', params={'name': boat_name})
    if not r:
        cache[key] = []
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    candidates: list[dict] = []
    seen: set[str] = set()

    table = soup.find('table')
    if not table:
        cache[key] = []
        return []

    for row in table.find_all('tr'):
        link = row.find('a', href=re.compile(r'/vessels/details/\d+'))
        if not link:
            continue

        mmsi = link['href'].split('/')[-1]
        if not is_valid_mmsi(mmsi) or mmsi in seen:
            continue
        seen.add(mmsi)

        cells = row.find_all('td')
        if not cells:
            continue

        # First cell packs name + type: "PACIFIC QUEENFishing vessel"
        first = cells[0].get_text(strip=True)
        vessel_type = ''
        vessel_name = first
        for tag in (FISHING_TAGS + PASSENGER_TAGS +
                    ['Cargo', 'Tanker', 'Tug', 'Pleasure craft', 'Other']):
            idx = first.lower().find(tag.lower())
            if idx > 0:
                vessel_name = first[:idx].strip()
                vessel_type = first[idx:].strip()
                break

        # Size column "30 / 7" -> length 30 m
        size_m = None
        if len(cells) >= 5:
            m = re.match(r'(\d+)\s*/\s*\d+', cells[4].get_text(strip=True))
            if m:
                size_m = int(m.group(1))

        candidates.append({
            'mmsi':        mmsi,
            'vessel_name': vessel_name,
            'vessel_type': vessel_type,
            'size_m':      size_m,
            'source':      'vesselfinder',
        })

    cache[key] = candidates
    return candidates


def fetch_vf_details(mmsi: str, cache: dict) -> dict:
    """
    Fetch the VesselFinder vessel detail page for richer signals.
    Returns: vessel_name, vessel_type, us_flag, socal, fishing, landing.
    """
    key = 'vf_detail:' + mmsi
    if key in cache:
        return cache[key]

    r = get(f'https://www.vesselfinder.com/vessels/details/{mmsi}')
    if not r:
        cache[key] = {}
        return {}

    soup      = BeautifulSoup(r.text, 'html.parser')
    lower     = soup.get_text(' ', strip=True).lower()
    d: dict   = {}

    # Title format: "PACIFIC QUEEN, Fishing vessel - Details and current position - MMSI ..."
    title_el = soup.find('title')
    if title_el:
        raw = title_el.get_text(strip=True)
        d['vessel_name'] = raw.split(',')[0].strip()
        type_m = re.search(r',\s*([^-]+?)\s*-\s*Details', raw)
        d['vessel_type'] = type_m.group(1).strip() if type_m else ''

    d['us_flag'] = 'united states' in lower or 'flag united states' in lower
    d['socal']   = any(p in lower for p in SOCAL_PORTS)
    d['fishing'] = any(w in lower for w in FISHING_TAGS)
    d['landing'] = any(ln in lower for ln in LANDING_NAMES)

    cache[key] = d
    return d

# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def score_candidate(
    search_result: dict,
    boat_name: str,
    details: dict,
) -> tuple[int, list[str]]:
    score   = 0
    reasons: list[str] = []

    # -- Name match --
    vessel_name = (
        details.get('vessel_name') or
        search_result.get('vessel_name') or ''
    ).strip()

    if vessel_name:
        sim = fuzzy(normalize(vessel_name), normalize(boat_name))
        if sim >= 0.97:
            score += 30; reasons.append(f'exact name match ({vessel_name!r})')
        elif sim >= 0.90:
            score += 20; reasons.append(f'strong name match {sim:.0%} ({vessel_name!r})')
        elif sim >= 0.80:
            score += 12; reasons.append(f'partial name match {sim:.0%} ({vessel_name!r})')
        elif sim >= 0.70:
            score +=  5; reasons.append(f'weak name match {sim:.0%} ({vessel_name!r})')
        else:
            score -= 15; reasons.append(f'poor name match {sim:.0%} ({vessel_name!r}) -- penalised')
    else:
        reasons.append('no vessel name extracted')

    # -- Vessel type --
    vtype = (details.get('vessel_type') or search_result.get('vessel_type') or '').lower()
    if any(t in vtype for t in FISHING_TAGS):
        score += 15; reasons.append(f'vessel type: {vtype!r}')
    elif any(t in vtype for t in PASSENGER_TAGS):
        score +=  8; reasons.append(f'vessel type: {vtype!r} (passenger -- some sportfishers use this)')
    elif vtype:
        reasons.append(f'vessel type: {vtype!r} (not fishing/passenger)')

    # -- US MMSI prefix --
    mmsi = search_result['mmsi']
    if US_MMSI_RE.match(mmsi):
        score += 15; reasons.append(f'US MMSI prefix ({mmsi[:3]}...)')
    else:
        reasons.append(f'non-US MMSI prefix ({mmsi[:3]}...)')

    # -- US flag from detail page --
    if details.get('us_flag'):
        score += 5; reasons.append('US flag confirmed on detail page')

    # -- SoCal port --
    if details.get('socal'):
        score += 20; reasons.append('SoCal port/location on detail page')

    # -- Landing name --
    if details.get('landing'):
        score +=  5; reasons.append('SD landing name found in description')

    # -- Size sanity --
    size_m = search_result.get('size_m')
    if size_m is not None:
        if MIN_LEN_M <= size_m <= MAX_LEN_M:
            score += 5; reasons.append(f'vessel size {size_m}m (typical for SD sportfisher)')
        else:
            score -= 5; reasons.append(f'vessel size {size_m}m (outside typical 12-50m range)')

    return score, reasons

# ---------------------------------------------------------------------------
# Per-boat lookup
# ---------------------------------------------------------------------------

def lookup_boat(boat_name: str, cache: dict) -> tuple[dict | None, int, list[str]]:
    print(f"\n  {boat_name!r}")

    candidates: list[dict] = []

    # Strategy 1: exact name
    candidates = search_vf(boat_name, cache)

    # Strategy 2: strip parenthetical ("Patriot (SD)" -> "Patriot")
    clean = re.sub(r'\s*\([^)]+\)', '', boat_name).strip()
    if not candidates and clean != boat_name:
        candidates = search_vf(clean, cache)

    # Strategy 3: first word only
    words = boat_name.split()
    if not candidates and len(words) > 1:
        candidates = search_vf(words[0], cache)

    # Strategy 4: F/V prefix
    if not candidates:
        candidates = search_vf(f'F/V {boat_name}', cache)

    if not candidates:
        print("    no candidates found on VesselFinder")
        return None, 0, ['no search results']

    print(f"    {len(candidates)} candidate(s) -- fetching detail pages ...")

    # Score each candidate after fetching its detail page
    scored: list[tuple[dict, int, list[str]]] = []
    for cand in candidates:
        details     = fetch_vf_details(cand['mmsi'], cache)
        sc, reasons = score_candidate(cand, boat_name, details)
        scored.append((cand, sc, reasons))

    scored.sort(key=lambda x: -x[1])
    best_cand, best_score, best_reasons = scored[0]

    verdict = (
        'HIGH OK' if best_score >= HIGH_CONF else
        'REVIEW'  if best_score >= MED_CONF  else
        'skip'
    )
    print(f"    MMSI {best_cand['mmsi']}  score={best_score}  [{verdict}]")
    for r in best_reasons:
        print(f"      * {r}")
    if len(scored) > 1:
        runner = scored[1]
        print(f"    runner-up: MMSI {runner[0]['mmsi']} score={runner[1]}")

    return best_cand, best_score, best_reasons

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Automated MMSI lookup via VesselFinder')
    parser.add_argument('--dry-run',  action='store_true',
                        help='Print results without saving files')
    parser.add_argument('--test',     action='store_true',
                        help='Validate on Pacific Queen, Polaris Supreme, Tribute')
    parser.add_argument('--boat',     metavar='NAME', default=None,
                        help='Look up a single boat by name')
    parser.add_argument('--no-cache', action='store_true',
                        help='Ignore cached results and re-fetch everything')
    args = parser.parse_args()

    cache = {} if args.no_cache else load_cache()

    with open(MMSI_FILE, encoding='utf-8') as f:
        current_mmsi: dict = json.load(f)

    if args.test:
        targets = ['Pacific Queen', 'Polaris Supreme', 'Tribute']
        print("TEST MODE -- validating against known MMSIs")
        print("  Pacific Queen   -> expected 367186270")
        print("  Polaris Supreme -> expected 367543000")
        print("  Tribute         -> expected 338555612")
    elif args.boat:
        targets = [args.boat]
    else:
        targets = [
            name for name, mmsi in current_mmsi.items()
            if not name.startswith('_') and mmsi is None
        ]

    print(f"\nSD Sport Fishing -- MMSI Auto-Discovery (VesselFinder)")
    print("=" * 60)
    print(f"Boats to look up : {len(targets)}")
    print(f"Rate limit       : {RATE_LIMIT}s per request")
    print(f"Auto threshold   : >={HIGH_CONF}")
    print(f"Review threshold : {MED_CONF}-{HIGH_CONF - 1}")
    print("=" * 60)

    auto_matches:   dict[str, dict] = {}
    review_matches: dict[str, dict] = {}
    not_found:      list[str]       = []

    for boat_name in targets:
        cand, score, reasons = lookup_boat(boat_name, cache)
        save_cache(cache)

        if cand and score >= HIGH_CONF:
            auto_matches[boat_name] = {
                'mmsi':         cand['mmsi'],
                'matched_name': cand.get('vessel_name', ''),
                'confidence':   score,
                'reasons':      reasons,
            }
        elif cand and score >= MED_CONF:
            review_matches[boat_name] = {
                'mmsi':         cand['mmsi'],
                'matched_name': cand.get('vessel_name', ''),
                'confidence':   score,
                'reasons':      reasons,
            }
        else:
            not_found.append(boat_name)

    # --- Summary ---
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)

    print(f"\nHigh confidence (>={HIGH_CONF}) -- {len(auto_matches)} boat(s):")
    for name, m in auto_matches.items():
        print(f"  {name:30s}  MMSI {m['mmsi']}  ({m['confidence']} pts)")

    print(f"\nNeeds review ({MED_CONF}-{HIGH_CONF - 1}) -- {len(review_matches)} boat(s):")
    for name, m in review_matches.items():
        print(f"  {name:30s}  MMSI {m['mmsi']}  ({m['confidence']} pts)")

    print(f"\nNot found (<{MED_CONF}) -- {len(not_found)} boat(s):")
    for name in not_found:
        print(f"  {name}")

    if args.test:
        print("\nValidation:")
        # Polaris Supreme (367543000) is not on VesselFinder -- "not found" is acceptable.
        # A FAIL means we found the WRONG MMSI, not that we failed to find it at all.
        expected = {
            'Pacific Queen':   ('367186270', True),   # (expected_mmsi, must_find)
            'Polaris Supreme': ('367543000', False),  # not on VesselFinder -- ok to miss
            'Tribute':         ('338555612', True),
        }
        all_ok = True
        for name, (exp, must_find) in expected.items():
            found = (auto_matches.get(name) or review_matches.get(name) or {}).get('mmsi')
            if found is None and not must_find:
                print(f"  [OK] {name}: not found (expected -- not on VesselFinder)")
            elif found == exp:
                bucket = 'auto' if name in auto_matches else 'review'
                print(f"  [OK] {name}: {exp} ({bucket})")
            else:
                all_ok = False
                print(f"  [FAIL] {name}: expected {exp}, got {found}")
        print(f"\n  {'PASS' if all_ok else 'FAIL'} -- {'confidence scoring validated' if all_ok else 'check scoring logic'}")

    if not args.dry_run:
        (ROOT / 'data').mkdir(exist_ok=True)
        if auto_matches:
            AUTO_FILE.write_text(json.dumps(auto_matches, indent=2), encoding='utf-8')
            print(f"\nSaved: {AUTO_FILE.relative_to(ROOT)}")
        if review_matches:
            REVIEW_FILE.write_text(json.dumps(review_matches, indent=2), encoding='utf-8')
            print(f"Saved: {REVIEW_FILE.relative_to(ROOT)}")
        if auto_matches or review_matches:
            print("\nNext steps:")
            print("  1. Spot-check auto matches on vesselfinder.com")
            print("  2. Manually verify review matches")
            print("  3. Copy confirmed MMSIs into data/boat-mmsi.json")
            print("  4. .venv/Scripts/python.exe scripts/import-mmsi.py data/boat-mmsi.json")
    else:
        print("\n[dry-run] No files written.")


if __name__ == '__main__':
    main()
