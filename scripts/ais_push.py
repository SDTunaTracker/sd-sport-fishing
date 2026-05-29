"""
Windows Task Scheduler companion to the vessel-tracker CF Worker.

Connects to AISStream.io for DURATION seconds, collects position reports for
known vessels, then PUTs the results to the CF Worker KV via the /vessels
endpoint.  Also writes web/ais_positions.json for local dev testing.

Scheduled via Task Scheduler every 5 minutes:
    scripts/install_vessel_task.ps1

Required .env keys:
    AISSTREAM_API_KEY      AISStream.io key
    VESSEL_WORKER_URL      https://vessel-tracker.ACCOUNT.workers.dev
    VESSEL_WORKER_TOKEN    Matches AUTH_TOKEN secret in CF Worker

Usage (manual test):
    .venv/Scripts/python.exe scripts/ais_push.py --duration 45
"""

import asyncio
import json
import sys
import os
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone

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
    print("ERROR: run: .venv/Scripts/pip.exe install websockets")
    sys.exit(1)

API_KEY      = os.getenv('AISSTREAM_API_KEY', '')
WORKER_URL   = os.getenv('VESSEL_WORKER_URL', '').rstrip('/')
WORKER_TOKEN = os.getenv('VESSEL_WORKER_TOKEN', '')
MMSI_PATH    = ROOT / 'data' / 'vessel_mmsi.json'
OUT_JSON     = ROOT / 'web' / 'ais_positions.json'
SOCAL_BOX    = [[31.0, -121.0], [35.0, -117.0]]

MAX_TRAIL    = 12   # positions to keep in trail array


def load_known_mmsi():
    if not MMSI_PATH.exists():
        return {}
    data = json.loads(MMSI_PATH.read_text())
    return data.get('vessels', {})


def load_existing_positions():
    if OUT_JSON.exists():
        try:
            return {p['mmsi']: p for p in json.loads(OUT_JSON.read_text())}
        except Exception:
            pass
    return {}


async def collect(duration: int, known: dict) -> list:
    if not API_KEY:
        print("ERROR: AISSTREAM_API_KEY not set"); return []
    if not known:
        print("ERROR: no MMSI entries in data/vessel_mmsi.json — run discover_mmsi.py first"); return []

    positions = {}
    print(f"  Listening to AISStream for {duration}s ({len(known)} tracked vessels)…")

    deadline = asyncio.get_event_loop().time() + duration

    async with websockets.connect('wss://stream.aisstream.io/v0/stream', ping_interval=30) as ws:
        await ws.send(json.dumps({
            "APIKey":             API_KEY,
            "BoundingBoxes":      [SOCAL_BOX],
            "FiltersShipMMSI":    list(known.keys()),
            "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"],
        }))

        async for raw in ws:
            if asyncio.get_event_loop().time() > deadline:
                break
            try:
                data   = json.loads(raw)
                meta   = data.get('MetaData', {})
                mmsi   = str(meta.get('MMSI', '')).strip()
                if not mmsi or mmsi not in known:
                    continue
                msg = (data.get('Message', {})
                       .get('PositionReport') or
                       data.get('Message', {})
                       .get('StandardClassBPositionReport') or {})
                sog = msg.get('Sog', 0)
                cog = msg.get('Cog', 0)
                positions[mmsi] = {
                    'mmsi':       mmsi,
                    'name':       known[mmsi]['name'],
                    'landing':    known[mmsi]['landing'],
                    'lat':        meta.get('latitude'),
                    'lng':        meta.get('longitude'),
                    'sog':        sog,
                    'cog':        cog,
                    'heading':    msg.get('TrueHeading', cog),
                    'updated_at': meta.get('time_utc', datetime.now(timezone.utc).isoformat()),
                }
                print(f"  {positions[mmsi]['name']:25s} {positions[mmsi]['lat']:.4f},{positions[mmsi]['lng']:.4f}  {sog:.1f}kt")
            except Exception:
                pass

    return list(positions.values())


def merge_trail(new_positions: list, existing: dict) -> list:
    result = []
    for pos in new_positions:
        prev  = existing.get(pos['mmsi'], {})
        trail = list(prev.get('trail', []))
        if prev.get('lat') is not None:
            trail.append({'lat': prev['lat'], 'lng': prev['lng'],
                          't': prev.get('updated_at', ''), 'sog': prev.get('sog', 0)})
        pos['trail'] = trail[-MAX_TRAIL:]
        result.append(pos)
    return result


def push_to_worker(positions: list):
    if not WORKER_URL or not WORKER_TOKEN:
        print("  VESSEL_WORKER_URL / VESSEL_WORKER_TOKEN not set — skipping push")
        return
    try:
        r = requests.put(
            f"{WORKER_URL}/vessels",
            json=positions,
            headers={'X-Auth-Token': WORKER_TOKEN, 'Content-Type': 'application/json'},
            timeout=15,
        )
        print(f"  Pushed to Worker → {r.status_code}")
    except Exception as e:
        print(f"  Worker push failed: {e}")


def write_local(positions: list):
    OUT_JSON.write_text(json.dumps(positions, indent=2))
    print(f"  Written → {OUT_JSON}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=45)
    args = parser.parse_args()

    known    = load_known_mmsi()
    existing = load_existing_positions()

    new_pos  = asyncio.run(collect(args.duration, known))
    merged   = merge_trail(new_pos, existing)

    if merged:
        write_local(merged)
        push_to_worker(merged)
        print(f"\n  Done — {len(merged)} vessel(s) updated")
    else:
        print("  No positions collected (boats may be docked or not broadcasting)")


if __name__ == '__main__':
    main()
