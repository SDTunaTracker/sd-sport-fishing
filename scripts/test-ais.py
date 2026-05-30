import asyncio
import websockets
import json
import os
import sqlite3
from collections import defaultdict

API_KEY = os.environ.get('AISSTREAM_API_KEY')
if not API_KEY:
    print("ERROR: Set AISSTREAM_API_KEY env var")
    print("  $env:AISSTREAM_API_KEY = 'your-key-here'")
    exit(1)

# SoCal bounding box
BBOX = [[31.0, -121.0], [35.0, -117.0]]

# Load known MMSI list
db = sqlite3.connect('tracker.db')
cursor = db.cursor()
cursor.execute("SELECT mmsi, name FROM boats WHERE mmsi IS NOT NULL")
known_mmsi = {row[0]: row[1] for row in cursor.fetchall()}

print(f"Loaded {len(known_mmsi)} known sportfishing boat MMSIs")
print()

vessels_seen = defaultdict(int)
matches = []

async def connect_ais_stream():
    async with websockets.connect(
        'wss://stream.aisstream.io/v0/stream'
    ) as websocket:
        subscribe = {
            "APIKey": API_KEY,
            "BoundingBoxes": [BBOX],
            "FilterMessageTypes": ["PositionReport"]
        }
        await websocket.send(json.dumps(subscribe))
        print("Subscribed. Listening for 60 seconds...")
        print()

        loop = asyncio.get_event_loop()
        start_time = loop.time()
        timeout = 60

        while True:
            elapsed = loop.time() - start_time
            if elapsed > timeout:
                break

            try:
                message = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=timeout - elapsed
                )
                data = json.loads(message)

                if data.get('MessageType') == 'PositionReport':
                    report = data['Message']['PositionReport']
                    mmsi = str(report['UserID'])
                    vessels_seen[mmsi] += 1

                    if mmsi in known_mmsi:
                        matches.append({
                            'mmsi': mmsi,
                            'name': known_mmsi[mmsi],
                            'lat': report['Latitude'],
                            'lng': report['Longitude'],
                            'speed': report.get('Sog', 0),
                            'heading': report.get('Cog', 0),
                        })
                        print(f"  KNOWN BOAT: {known_mmsi[mmsi]} ({mmsi}) at "
                              f"{report['Latitude']:.4f}, {report['Longitude']:.4f} "
                              f"@ {report.get('Sog', 0)} kt")
            except asyncio.TimeoutError:
                break

asyncio.run(connect_ais_stream())

print()
print("=" * 60)
print("REPORT — 60 second AIS test")
print("=" * 60)
print(f"Total unique vessels seen:         {len(vessels_seen)}")
print(f"Total position reports received:   {sum(vessels_seen.values())}")
print(f"Known SD sportfishers matched:     {len(matches)}")
print()
if matches:
    print("Matched boats:")
    for m in matches[:10]:
        print(f"  - {m['name']}")
else:
    print("No matches yet — either:")
    print("  - MMSI database is empty (expected on first run)")
    print("  - SD sportfishers had AIS off during test window")
    print("  - Try running again when boats are at sea (~8am-5pm)")

print()
print("Top 10 most-reported vessels (by message count):")
sorted_vessels = sorted(vessels_seen.items(), key=lambda x: x[1], reverse=True)[:10]
for mmsi, count in sorted_vessels:
    name = known_mmsi.get(mmsi, "Unknown")
    print(f"  {mmsi}  {count:4d} reports  {name}")
