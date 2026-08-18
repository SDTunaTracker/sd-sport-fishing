import sqlite3
conn = sqlite3.connect("tracker.db")
conn.row_factory = sqlite3.Row
matched = conn.execute(
    "SELECT bp.landing, bp.boat, bp.photo_url IS NOT NULL as has_photo, length(bp.description) as desc_len "
    "FROM boat_profiles bp "
    "WHERE bp.boat IN (SELECT DISTINCT boat FROM trips) "
    "ORDER BY bp.landing, bp.boat"
).fetchall()
print(f"Profiles matching real trip boats: {len(matched)}")
for r in matched:
    print(f"  [{r['landing'][:4]}] {r['boat']:<30} photo={r['has_photo']}  desc={r['desc_len'] or 0}ch")
conn.close()
