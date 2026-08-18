import sqlite3
conn = sqlite3.connect("tracker.db")
d1 = conn.execute("DELETE FROM boat_profiles WHERE photo_url LIKE '%shadow.png'").rowcount
d2 = conn.execute("DELETE FROM boat_profiles WHERE photo_url LIKE '%legend-5-24-26%'").rowcount
d3 = conn.execute("DELETE FROM boat_profiles WHERE boat NOT IN (SELECT DISTINCT boat FROM trips)").rowcount
conn.commit()
remaining = conn.execute("SELECT COUNT(*) FROM boat_profiles").fetchone()[0]
print(f"Deleted shadow: {d1}, fish-photo: {d2}, non-boats: {d3}")
print(f"Remaining profiles: {remaining}")
rows = conn.execute("SELECT boat, landing, photo_url FROM boat_profiles ORDER BY landing, boat").fetchall()
for r in rows:
    print(f"  {r[1][:4]} | {r[0]:<30} {r[2].split('/')[-1][:50]}")
conn.close()
