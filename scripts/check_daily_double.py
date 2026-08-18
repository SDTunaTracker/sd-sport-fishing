"""Check Daily Double trips in the DB."""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "tracker.db"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

rows = c.execute("""
    SELECT id, date, boat, landing, trip_type_raw, trip_length, trip_length_days,
           anglers, trophy_count, ROUND(trophy_per_angler_per_day, 2) as tpad
    FROM trips
    WHERE LOWER(boat) LIKE '%daily double%'
    ORDER BY date
""").fetchall()

print(f"Found {len(rows)} Daily Double trips:\n")
for r in rows:
    print(f"  id={r['id']} | {r['date']} | {r['trip_length']} ({r['trip_length_days']}d) | "
          f"{r['anglers']} anglers | {r['trophy_count']} fish | {r['tpad']} tpa/day")
    print(f"    raw: {r['trip_type_raw']!r}")
c.close()
