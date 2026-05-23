"""Fix trips where '3/4 Day' raw label was mis-stored as '4 Day' due to parse bug."""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "tracker.db"
c = sqlite3.connect(DB)

# Find all affected rows
rows = c.execute("""
    SELECT id, trophy_count, anglers
    FROM trips
    WHERE trip_length = '4 Day'
      AND LOWER(trip_type_raw) LIKE '%3/4%'
""").fetchall()

print(f"Found {len(rows)} rows to fix.")

# Update each row: correct trip_length, trip_length_days, and recalculate metrics.
for row_id, trophy_count, anglers in rows:
    days = 0.75
    tpa = trophy_count / anglers if anglers else 0
    tpad = tpa / days
    c.execute("""
        UPDATE trips
        SET trip_length = '3/4 Day',
            trip_length_days = 0.75,
            trophy_per_angler = ?,
            trophy_per_angler_per_day = ?
        WHERE id = ?
    """, (tpa, tpad, row_id))

c.commit()
print(f"Fixed {len(rows)} rows.")
print(f"Total trips in DB: {c.execute('SELECT COUNT(*) FROM trips').fetchone()[0]:,}")
c.close()
