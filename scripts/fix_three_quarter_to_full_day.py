"""Reclassify all '3/4 Day' rows as 'Full Day' (trip_length_days = 1.0)."""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "tracker.db"
c = sqlite3.connect(DB)

rows = c.execute("""
    SELECT id, trophy_count, anglers
    FROM trips
    WHERE trip_length = '3/4 Day'
""").fetchall()

print(f"Found {len(rows)} rows to reclassify.")

for row_id, trophy_count, anglers in rows:
    days = 1.0
    tpa = trophy_count / anglers if anglers else 0
    tpad = tpa / days
    c.execute("""
        UPDATE trips
        SET trip_length = 'Full Day',
            trip_length_days = 1.0,
            trophy_per_angler = ?,
            trophy_per_angler_per_day = ?
        WHERE id = ?
    """, (tpa, tpad, row_id))

c.commit()
print(f"Done. {len(rows)} rows updated to 'Full Day'.")
c.close()
