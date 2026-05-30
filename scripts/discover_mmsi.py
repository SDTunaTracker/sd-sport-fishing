"""
Connects to AISStream.io and listens for ALL vessels in the SoCal bounding box.
Fuzzy-matches vessel names against the boat list to suggest MMSI mappings.

Works both locally (loads boats from tracker.db) and in CI (loads from
data/boat-mmsi.json when the DB is unavailable).

Usage:
    # Local — 5 min quick test
    .venv/Scripts/python.exe scripts/discover_mmsi.py --duration 300

    # CI / long run — append sessions to ais-discoveries.json
    python scripts/discover_mmsi.py --duration 7200 \
        --output data/ais-discoveries.json --append

    --duration      Seconds to listen (default 300)
    --output        Output JSON file (default: data/vessel_mmsi.json)
    --append        Merge this session into existing file (CI mode)
    --boats-file    JSON file with known boat names (fallback when no DB)
    --dry-run       Print matches without writing any files

Requires: websockets, python-dotenv
Env var:  AISSTREAM_API_KEY
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import signal
import sqlite3
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
except ImportError:
    pass

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed.  pip install websockets")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY         = os.getenv('AISSTREAM_API_KEY', '')
SOCAL_BOX       = [[31.0, -121.0], [35.0, -117.0]]
DB_PATH         = ROOT / 'tracker.db'
DEFAULT_OUT     = ROOT / 'data' / 'vessel_mmsi.json'
BOATS_FILE      = ROOT / 'data' / 'boat-mmsi.json'
MATCH_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# SIGTERM handler — GitHub Actions sends SIGTERM on job timeout
# ---------------------------------------------------------------------------

_shutdown = False

def _handle_sigterm(*_):
    global _shutdown
    _shutdown = True
    print("\n  [SIGTERM received] finishing gracefully ...")

signal.signal(signal.SIGTERM, _handle_sigterm)

# ---------------------------------------------------------------------------
# Boat list loading
# ---------------------------------------------------------------------------

def load_db_boats() -> list[tuple[str, str]]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT DISTINCT boat, landing FROM trips
        WHERE date >= date('now', '-90 days')
        ORDER BY boat
    """).fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows]


def load_json_boats(path: Path) -> list[tuple[str, str]]:
    """Load boat names from boat-mmsi.json (used in CI where DB is absent)."""
    data  = json.loads(path.read_text(encoding='utf-8'))
    boats = []
    for name, mmsi in data.items():
        if name.startswith('_'):
            continue
        # Use a generic landing placeholder — landing isn't needed for matching
        boats.append((name, 'San Diego'))
    return boats


def load_boats(boats_file: Path | None = None) -> list[tuple[str, str]]:
    if DB_PATH.exists():
        try:
            boats = load_db_boats()
            if boats:
                return boats
        except Exception as e:
            print(f"  [warn] DB load failed ({e}), falling back to JSON")

    src = boats_file or BOATS_FILE
    if src.exists():
        boats = load_json_boats(src)
        print(f"  Loaded {len(boats)} boats from {src.name}")
        return boats

    print("  [warn] No boat source found — matching disabled, will record all vessels")
    return []

# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def normalize(name: str) -> str:
    n = name.upper().strip()
    for drop in ['SPORTFISHING', 'SPORT FISHING', 'F/V', 'M/V', 'S/V', 'MV', 'FV']:
        n = n.replace(drop, '')
    return n.strip()


def best_match(ais_name: str, db_boats: list) -> tuple[str, str, float] | None:
    ais_norm  = normalize(ais_name)
    best_score, best_boat = 0.0, None
    for boat, landing in db_boats:
        score = difflib.SequenceMatcher(None, ais_norm, normalize(boat)).ratio()
        if score > best_score:
            best_score = score
            best_boat  = (boat, landing)
    if best_score >= MATCH_THRESHOLD and best_boat:
        return best_boat[0], best_boat[1], best_score
    return None

# ---------------------------------------------------------------------------
# AIS listener
# ---------------------------------------------------------------------------

async def listen(duration: int, db_boats: list) -> dict:
    """
    Listen to AISStream for `duration` seconds.

    Returns {
      'matches':      {mmsi: {name, landing, ais_name, score, lat, lng}},
      'all_vessels':  {mmsi: {ais_name, lat, lng, reports, first_seen, last_seen}},
      'total_messages': int,
    }
    """
    global _shutdown

    if not API_KEY:
        print("ERROR: AISSTREAM_API_KEY not set")
        sys.exit(1)

    matches:     dict[str, dict] = {}
    all_vessels: dict[str, dict] = {}
    seen_names:  set[str]        = set()
    total_msgs   = 0
    uri          = 'wss://stream.aisstream.io/v0/stream'

    print(f"\n  Listening for {duration}s (Ctrl-C or SIGTERM to stop early)...")
    if db_boats:
        print(f"  Matching against {len(db_boats)} boats\n")
    else:
        print("  Recording all vessels (no boat list for matching)\n")

    loop     = asyncio.get_event_loop()
    deadline = loop.time() + duration

    async with websockets.connect(uri, ping_interval=30) as ws:
        await ws.send(json.dumps({
            "APIKey":             API_KEY,
            "BoundingBoxes":      [SOCAL_BOX],
            "FilterMessageTypes": [
                "PositionReport",
                "StandardClassBPositionReport",
                "ShipStaticData",
            ],
        }))

        async for raw in ws:
            if _shutdown or loop.time() > deadline:
                break

            total_msgs += 1
            try:
                data     = json.loads(raw)
                meta     = data.get('MetaData', {})
                mmsi     = str(meta.get('MMSI', '')).strip()
                ais_name = (
                    meta.get('ShipName') or
                    data.get('Message', {}).get('ShipStaticData', {}).get('Name', '')
                ).strip()
                lat = meta.get('latitude')
                lng = meta.get('longitude')

                if not mmsi:
                    continue

                now_iso = datetime.now(timezone.utc).isoformat()

                # Track all vessels seen (even without a name)
                if mmsi not in all_vessels:
                    all_vessels[mmsi] = {
                        'ais_name':   ais_name or '',
                        'lat':        lat,
                        'lng':        lng,
                        'reports':    1,
                        'first_seen': now_iso,
                        'last_seen':  now_iso,
                    }
                else:
                    v = all_vessels[mmsi]
                    v['reports']  += 1
                    v['last_seen'] = now_iso
                    if lat:
                        v['lat'] = lat
                    if lng:
                        v['lng'] = lng
                    if ais_name and not v['ais_name']:
                        v['ais_name'] = ais_name

                # Only try matching once per unique MMSI+name pair
                if not ais_name or ais_name == '@@@@@@@@@@@@@@@@@@@@':
                    continue
                pair_key = f"{mmsi}:{ais_name}"
                if pair_key in seen_names:
                    continue
                seen_names.add(pair_key)

                if not db_boats:
                    continue

                m = best_match(ais_name, db_boats)
                if m:
                    boat, landing, score = m
                    matches[mmsi] = {
                        'name':     boat,
                        'landing':  landing,
                        'ais_name': ais_name,
                        'score':    round(score, 3),
                        'lat':      lat,
                        'lng':      lng,
                    }
                    # Tag in all_vessels
                    all_vessels[mmsi]['matched_our_boat'] = boat
                    print(f"  MATCH  {mmsi}  AIS:{ais_name!r:30s}  DB:{boat!r}  ({score:.0%})")

            except Exception:
                pass

    return {
        'matches':        matches,
        'all_vessels':    all_vessels,
        'total_messages': total_msgs,
    }

# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def update_vessel_mmsi(matches: dict, dry_run: bool, out_path: Path) -> None:
    """Update the legacy vessel_mmsi.json (used by local import-mmsi workflow)."""
    current = json.loads(out_path.read_text(encoding='utf-8')) if out_path.exists() else {}
    vessels = current.get('vessels', {})

    added, skipped = 0, 0
    for mmsi, info in matches.items():
        if mmsi in vessels:
            skipped += 1
            continue
        vessels[mmsi] = {'name': info['name'], 'landing': info['landing']}
        added += 1

    current['vessels']             = vessels
    current['_last_discover_run']  = datetime.now(timezone.utc).isoformat()
    current['_vessel_count']       = len(vessels)

    print(f"\n  Added {added} new vessel(s), skipped {skipped} already present.")
    print(f"  Total vessels mapped: {len(vessels)}")

    if dry_run:
        print("\n  [dry-run] vessel_mmsi.json not written")
    else:
        out_path.write_text(json.dumps(current, indent=2), encoding='utf-8')
        print(f"  Saved: {out_path}")


def update_discoveries(
    result: dict,
    duration: int,
    dry_run: bool,
    out_path: Path,
    append: bool,
) -> None:
    """
    Write (or append) to ais-discoveries.json with full session detail.
    This is the CI output format — richer than vessel_mmsi.json.
    """
    now = datetime.now(timezone.utc).isoformat()

    if append and out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding='utf-8'))
        except Exception:
            existing = {}
    else:
        existing = {}

    sessions = existing.get('_sessions', [])
    matched_list = [
        {'mmsi': mmsi, 'name': info['name']}
        for mmsi, info in result['matches'].items()
    ]
    sessions.append({
        'started':               now,
        'duration_seconds':      duration,
        'total_messages':        result['total_messages'],
        'unique_mmsis_seen':     len(result['all_vessels']),
        'matched_known_boats':   matched_list,
    })

    # Merge all_observed_vessels (keep existing, update reports + last_seen)
    all_obs: dict = existing.get('all_observed_vessels', {})
    for mmsi, v in result['all_vessels'].items():
        if mmsi in all_obs:
            all_obs[mmsi]['reports']  += v['reports']
            all_obs[mmsi]['last_seen'] = v['last_seen']
            if v.get('ais_name') and not all_obs[mmsi].get('ais_name'):
                all_obs[mmsi]['ais_name'] = v['ais_name']
            if v.get('matched_our_boat'):
                all_obs[mmsi]['matched_our_boat'] = v['matched_our_boat']
        else:
            all_obs[mmsi] = dict(v)

    output = {
        '_updated':             now,
        '_sessions':            sessions,
        'all_observed_vessels': all_obs,
    }

    match_count = len(result['matches'])
    print(f"\n  Session: {len(result['all_vessels'])} unique vessels, "
          f"{match_count} matched our boats")
    print(f"  Total sessions on record: {len(sessions)}")

    if dry_run:
        print("  [dry-run] ais-discoveries.json not written")
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, indent=2), encoding='utf-8')
        print(f"  Saved: {out_path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description='Discover MMSI numbers via AISStream')
    parser.add_argument('--duration',   type=int,  default=300,          help='Seconds to listen (default 300)')
    parser.add_argument('--output',     type=Path, default=DEFAULT_OUT,  help='Output JSON file path')
    parser.add_argument('--append',     action='store_true',              help='Merge session into existing file (CI mode)')
    parser.add_argument('--boats-file', type=Path, default=None,          help='JSON file with known boat names (CI fallback)')
    parser.add_argument('--dry-run',    action='store_true',              help='Print without writing files')
    args = parser.parse_args()

    db_boats = load_boats(args.boats_file)

    print("SD Sport Fishing - MMSI Discovery")
    print("-" * 50)
    print(f"Loaded {len(db_boats)} boats for matching")

    result = asyncio.run(listen(args.duration, db_boats))

    print("\n" + "-" * 50)
    print(f"Found {len(result['matches'])} match(es) in {args.duration}s window "
          f"({len(result['all_vessels'])} unique vessels total)\n")

    # Decide output mode based on filename
    is_discoveries = 'discoveries' in args.output.name
    default_mmsi   = ROOT / 'data' / 'vessel_mmsi.json'

    if is_discoveries or args.append:
        # CI mode: write rich ais-discoveries.json
        update_discoveries(result, args.duration, args.dry_run, args.output, args.append)
        # Also keep vessel_mmsi.json up to date if we have matches
        if result['matches'] and not args.dry_run:
            update_vessel_mmsi(result['matches'], dry_run=False, out_path=default_mmsi)
    else:
        # Local mode: update vessel_mmsi.json (legacy behaviour)
        if result['matches']:
            update_vessel_mmsi(result['matches'], args.dry_run, args.output)
        else:
            print("  No matches found. Try a longer --duration or check AISSTREAM_API_KEY.")


if __name__ == '__main__':
    main()
