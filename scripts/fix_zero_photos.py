import sqlite3, os

conn = sqlite3.connect("tracker.db")
rows = conn.execute(
    "SELECT id, boat, landing, photo_url FROM boat_profiles WHERE photo_url LIKE 'images/boats/%'"
).fetchall()

zero_ids = []
for row_id, boat, landing, photo_url in rows:
    path = "web/" + photo_url
    size = os.path.getsize(path) if os.path.exists(path) else -1
    if size == 0:
        zero_ids.append(row_id)
        print(f"ZERO: {boat} ({landing}) -> {photo_url}")
    else:
        print(f"  OK: {boat} ({landing}) -> {size} bytes")

if zero_ids:
    print(f"\nClearing {len(zero_ids)} zero-byte entries from DB...")
    conn.execute(
        f"UPDATE boat_profiles SET photo_url = NULL WHERE id IN ({','.join(str(i) for i in zero_ids)})"
    )
    conn.commit()
    print("Done.")

conn.close()

# Delete zero-byte files from disk
import glob
for path in glob.glob("web/images/boats/*.jpg"):
    if os.path.getsize(path) == 0:
        os.remove(path)
        print(f"Deleted: {path}")
