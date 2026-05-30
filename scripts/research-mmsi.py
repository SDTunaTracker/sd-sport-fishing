import sqlite3
import json
from pathlib import Path

def list_active_boats():
    db = sqlite3.connect('tracker.db')
    cursor = db.cursor()

    cursor.execute("""
      SELECT
        boat,
        landing,
        COUNT(*) as trip_count,
        MAX(date) as last_trip
      FROM trips
      WHERE date >= date('now', '-90 days')
      AND landing IN (
        'H&M Landing',
        'Fisherman''s Landing',
        'Seaforth Sportfishing',
        'Point Loma Sportfishing',
        'Oceanside Sea Center'
      )
      GROUP BY boat, landing
      ORDER BY landing, trip_count DESC
    """)

    boats = cursor.fetchall()

    print("=" * 70)
    print("ACTIVE SD SPORTFISHING BOATS — MMSI LOOKUP CHECKLIST")
    print("=" * 70)
    print()
    print("Look up each boat on:")
    print("  https://www.marinetraffic.com/en/ais/home/")
    print("  https://www.vesselfinder.com/")
    print()
    print("Search: '[boat name] San Diego'")
    print("Copy the MMSI (9-digit number)")
    print()

    current_landing = None
    for boat, landing, count, last_trip in boats:
        if landing != current_landing:
            print()
            print(f"--- {landing} ---")
            current_landing = landing
        print(f"  [ ] {boat:35s} "
              f"({count:3d} trips, last: {last_trip})  "
              f"MMSI: _________")

    print()
    print(f"Total active boats: {len(boats)}")
    print()
    print("Save MMSI numbers to:")
    print("  data/boat-mmsi.json")
    print()
    print("Format:")
    print(json.dumps({
        "Pacific Queen": "367123456",
        "Polaris Supreme": "367234567",
        "_comment": "9-digit MMSI per boat"
    }, indent=2))

if __name__ == '__main__':
    list_active_boats()
