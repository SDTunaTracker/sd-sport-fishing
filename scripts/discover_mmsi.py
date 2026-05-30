"""
Connects to AISStream.io and listens for ALL vessels in the SoCal bounding box.
Fuzzy-matches vessel names against the boat database to suggest MMSI mappings.

Usage:
    .venv/Scripts/python.exe scripts/discover_mmsi.py --duration 300

    --duration  Seconds to listen (default 300 = 5 min). Run longer to catch
                more boats. Active SD fleet typically shows within 30 min.
    --output    Path to save results (default: data/vessel_mmsi.json)
    --dry-run   Print matches without updating the file

Requires:
    pip install websockets python-dotenv
    AISSTREAM_API_KEY in .env

Output format written to data/vessel_mmsi.json:
    { "vessels": { "338123456": { "name": "Pacific Queen", "landing": "..." } } }
"""

import asyncio
import json
import sqlite3
import sys
import os
import difflib
import argparse
from pathlib import Path
from datetime import datetime

# -- Bootstrap path ------------------------------------------------------------
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
    print("ERROR: websockets not installed. Run: .venv/Scripts/pip.exe install websockets")
    sys.exit(1)

# -- Config --------------------------------------------------------------------
API_KEY   = os.getenv('AISSTREAM_API_KEY', '')
SOCAL_BOX = [[31.0, -121.0], [35.0, -117.0]]
DB_PATH   = ROOT / 'tracker.db'
OUT_PATH  = ROOT / 'data' / 'vessel_mmsi.json'

MATCH_THRESHOLD = 0.85  # fuzzy ratio minimum

# -- Load known boat names from DB --------------------------------------------

def load_db_boats():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT DISTINCT boat, landing FROM trips
        WHERE date >= date('now', '-90 days')
        ORDER BY boat
    """).fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows]


def normalize(name):
    """Strip common suffixes / filler words for better fuzzy match."""
    n = name.upper().strip()
    for drop in ['SPORTFISHING', 'SPORT FISHING', 'F/V', 'M/V', 'S/V', 'MV', 'FV']:
        n = n.replace(drop, '')
    return n.strip()


def best_match(ais_name, db_boats):
    """Returns (boat, landing, score) for the best DB match, or None."""
    ais_norm = normalize(ais_name)
    best_score, best_boat = 0, None
    for boat, landing in db_boats:
        db_norm = normalize(boat)
        score = difflib.SequenceMatcher(None, ais_norm, db_norm).ratio()
        if score > best_score:
            best_score = score
            best_boat = (boat, landing)
    if best_score >= MATCH_THRESHOLD and best_boat:
        return best_boat[0], best_boat[1], best_score
    return None


# -- AIS listener --------------------------------------------------------------

async def listen(duration: int, db_boats: list) -> dict:
    """
    Returns: { mmsi_str: {name, landing, ais_name, score, lat, lng} }
    """
    if not API_KEY:
        print("ERROR: AISSTREAM_API_KEY not set in .env")
        sys.exit(1)

    found   = {}   # mmsi → best match info
    seen    = set()
    uri     = 'wss://stream.aisstream.io/v0/stream'

    print(f"\n  Listening for {duration}s (Ctrl-C to stop early)...")
    print(f"  Matching against {len(db_boats)} boats from DB\n")

    deadline = asyncio.get_event_loop().time() + duration

    async with websockets.connect(uri, ping_interval=30) as ws:
        await ws.send(json.dumps({
            "APIKey":           API_KEY,
            "BoundingBoxes":    [SOCAL_BOX],
            "FilterMessageTypes": [
                "PositionReport",
                "StandardClassBPositionReport",
                "ShipStaticData",
            ],
        }))

        async for raw in ws:
            if asyncio.get_event_loop().time() > deadline:
                break

            try:
                data = json.loads(raw)
                meta = data.get('MetaData', {})
                mmsi = str(meta.get('MMSI', '')).strip()
                ais_name = (
                    meta.get('ShipName') or
                    (data.get('Message', {})
                        .get('ShipStaticData', {})
                        .get('Name', ''))
                ).strip()

                if not mmsi or not ais_name or ais_name in ('', '@@@@@@@@@@@@@@@@@@@@'):
                    continue
                if mmsi in seen:
                    continue
                seen.add(mmsi)

                match = best_match(ais_name, db_boats)
                if match:
                    boat, landing, score = match
                    found[mmsi] = {
                        'name':     boat,
                        'landing':  landing,
                        'ais_name': ais_name,
                        'score':    round(score, 3),
                        'lat':      meta.get('latitude'),
                        'lng':      meta.get('longitude'),
                    }
                    print(f"  MATCH  {mmsi}  AIS:{ais_name!r:30s}  DB:{boat!r}  ({score:.0%})")
            except Exception:
                pass

    return found


# -- Update vessel_mmsi.json ---------------------------------------------------

def update_mmsi_file(matches: dict, dry_run: bool, out_path: Path):
    current = json.loads(out_path.read_text()) if out_path.exists() else {}
    vessels = current.get('vessels', {})

    added, skipped = 0, 0
    for mmsi, info in matches.items():
        if mmsi in vessels:
            skipped += 1
            continue
        vessels[mmsi] = {'name': info['name'], 'landing': info['landing']}
        added += 1

    current['vessels'] = vessels
    from datetime import timezone
    current['_last_discover_run'] = datetime.now(timezone.utc).isoformat()
    current['_vessel_count'] = len(vessels)

    print(f"\n  Added {added} new vessel(s), skipped {skipped} already present.")
    print(f"  Total vessels mapped: {len(vessels)}")

    if dry_run:
        print("\n  [dry-run] Would write:\n")
        print(json.dumps(current, indent=2)[:2000])
    else:
        out_path.write_text(json.dumps(current, indent=2))
        print(f"\n  Saved: {out_path}")
        print("\n  Next step: copy 'vessels' dict into VESSEL_MMSI_JSON secret:")
        print(f"  wrangler secret put VESSEL_MMSI_JSON --name vessel-tracker")


# -- Main ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Discover MMSI numbers for SD sportfishing boats')
    parser.add_argument('--duration', type=int, default=300, help='Seconds to listen (default 300)')
    parser.add_argument('--output',   type=Path, default=OUT_PATH, help='Output JSON file path')
    parser.add_argument('--dry-run',  action='store_true', help='Print without updating file')
    args = parser.parse_args()

    db_boats = load_db_boats()
    print("SD Sport Fishing - MMSI Discovery")
    print("-" * 50)
    print(f"Loaded {len(db_boats)} active boats from tracker.db")

    matches = asyncio.run(listen(args.duration, db_boats))

    print("\n" + "-" * 50)
    print(f"Found {len(matches)} match(es) in {args.duration}s window\n")

    if matches:
        update_mmsi_file(matches, args.dry_run, args.output)
    else:
        print("  No matches found. Try a longer --duration or check AISSTREAM_API_KEY.")


if __name__ == '__main__':
    main()
