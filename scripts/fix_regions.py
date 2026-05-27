import sqlite3

conn = sqlite3.connect('tracker.db')

before = conn.execute("SELECT region, COUNT(*) FROM trips GROUP BY region ORDER BY region").fetchall()
print("Before:")
for region, count in before:
    print(f"  {region}: {count}")

conn.execute("UPDATE trips SET region = 'oc_la' WHERE region IN ('los_angeles','orange_county','ventura')")
conn.commit()

after = conn.execute("SELECT region, COUNT(*) FROM trips GROUP BY region ORDER BY region").fetchall()
print("\nAfter:")
for region, count in after:
    print(f"  {region}: {count}")

conn.close()
print("\nDone.")
