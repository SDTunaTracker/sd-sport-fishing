"""Recalculate trophy_per_angler_per_day for all rows using the rounded-day
methodology: divide by max(1, floor(trip_length_days)) so that 1.5-day trips
count as 1 day, 2.5-day as 2 days, etc.

Also reclassifies any remaining '3/4 Day' rows as 'Full Day' (1.0 days).
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "tracker.db"
c = sqlite3.connect(DB)

# 1. Reclassify leftover 3/4 Day rows.
three_qtr_rows = c.execute(
    "SELECT id, date, boat, landing, anglers FROM trips WHERE trip_length = '3/4 Day'"
).fetchall()

deleted = 0
updated = 0
for row_id, dt, boat, landing, anglers in three_qtr_rows:
    # Check if a Full Day row already exists for the same trip slot.
    conflict = c.execute("""
        SELECT id FROM trips
        WHERE date=? AND boat=? AND landing=? AND trip_length='Full Day' AND anglers=?
    """, (dt, boat, landing, anglers)).fetchone()
    if conflict:
        # Duplicate would result — drop the 3/4 Day row.
        c.execute("DELETE FROM trips WHERE id=?", (row_id,))
        deleted += 1
    else:
        c.execute("""
            UPDATE trips SET trip_length='Full Day', trip_length_days=1.0
            WHERE id=?
        """, (row_id,))
        updated += 1

if three_qtr_rows:
    print(f"3/4 Day rows: {updated} reclassified to 'Full Day', {deleted} dropped (duplicate Full Day existed).")
else:
    print("No '3/4 Day' rows found (already clean).")

# 2. Recalculate trophy_per_angler_per_day using rounded-day divisor.
rows = c.execute(
    "SELECT id, trophy_count, anglers, trip_length_days FROM trips"
).fetchall()

updates = []
for row_id, trophy_count, anglers, trip_length_days in rows:
    divisor = max(1.0, float(int(trip_length_days))) if trip_length_days else 1.0
    tpa = trophy_count / anglers if anglers else 0.0
    tpad = tpa / divisor
    updates.append((tpa, tpad, row_id))

c.executemany(
    "UPDATE trips SET trophy_per_angler = ?, trophy_per_angler_per_day = ? WHERE id = ?",
    updates,
)
c.commit()
print(f"Recalculated metrics for {len(updates):,} rows.")
print(f"Total trips in DB: {c.execute('SELECT COUNT(*) FROM trips').fetchone()[0]:,}")
c.close()
