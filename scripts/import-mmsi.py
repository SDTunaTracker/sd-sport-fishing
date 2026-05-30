import sqlite3
import json
import sys

def import_mmsi_from_json(json_path):
    with open(json_path) as f:
        data = json.load(f)

    db = sqlite3.connect('tracker.db')
    cursor = db.cursor()

    updated = 0
    skipped = 0

    for boat_name, mmsi in data.items():
        if boat_name.startswith('_'):
            continue  # skip comments
        if not mmsi or len(str(mmsi)) != 9:
            print(f"  SKIP: {boat_name} "
                  f"(invalid MMSI: {mmsi})")
            skipped += 1
            continue

        cursor.execute("""
            UPDATE boats
            SET mmsi = ?, ais_verified = 0
            WHERE name = ?
        """, (str(mmsi), boat_name))

        if cursor.rowcount > 0:
            print(f"  OK:   {boat_name:30s} "
                  f"MMSI {mmsi}")
            updated += 1
        else:
            print(f"  MISS: {boat_name} "
                  f"(not in boats table)")
            skipped += 1

    db.commit()
    print()
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")

if __name__ == '__main__':
    json_path = sys.argv[1] if len(sys.argv) > 1 \
        else 'data/boat-mmsi.json'
    import_mmsi_from_json(json_path)
