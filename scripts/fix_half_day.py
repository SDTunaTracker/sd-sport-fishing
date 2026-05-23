"""Delete half-day trips mis-stored as '2 Day' due to parse bug."""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "tracker.db"
c = sqlite3.connect(DB)

deleted = c.execute("""
    DELETE FROM trips
    WHERE trip_length = '2 Day'
      AND (LOWER(trip_type_raw) LIKE '%1/2%' OR LOWER(trip_type_raw) LIKE '%half%')
""").rowcount

c.commit()
print(f"Deleted {deleted} bad rows")
print(f"Remaining trips: {c.execute('SELECT COUNT(*) FROM trips').fetchone()[0]:,}")
c.close()
