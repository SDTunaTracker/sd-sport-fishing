"""Set trip_length_days = 0.75 for all Full Day trips (SD 'Full Day' = 6-hour / 3/4-day trip).
Recalculates trophy_per_angler and trophy_per_angler_per_day using the rounded-day
divisor (max(1, floor(0.75)) = 1) to stay consistent with the default metric method.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "tracker.db"
c = sqlite3.connect(DB)

rows = c.execute("""
    SELECT id, trophy_count, anglers
    FROM trips
    WHERE trip_length = 'Full Day'
""").fetchall()

print(f"Found {len(rows):,} Full Day rows to update.")

updates = []
for row_id, trophy_count, anglers in rows:
    tpa  = trophy_count / anglers if anglers else 0.0
    tpad = tpa / 1.0  # rounded divisor: max(1, floor(0.75)) = 1
    updates.append((tpad, row_id))

c.executemany(
    "UPDATE trips SET trip_length_days = 0.75, trophy_per_angler_per_day = ? WHERE id = ?",
    updates,
)
c.commit()
print(f"Updated {len(updates):,} rows: trip_length_days = 0.75.")
c.close()
