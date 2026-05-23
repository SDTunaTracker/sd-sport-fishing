"""Data quality checks for tracker.db. Run with:
    .venv\Scripts\python.exe scripts\check_data_quality.py
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "tracker.db"
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

issues = []

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# 1. Half-day trips mis-parsed as 2 Day
section("1. Half-day trips stored as '2 Day' (parse bug)")
rows = c.execute("""
    SELECT date, boat, landing, trip_type_raw, trip_length, anglers, trophy_count
    FROM trips
    WHERE trip_length = '2 Day'
      AND (LOWER(trip_type_raw) LIKE '%1/2%' OR LOWER(trip_type_raw) LIKE '%half%')
    ORDER BY date DESC
""").fetchall()
if rows:
    print(f"  Found {len(rows)} bad rows:")
    for r in rows[:20]:
        print(f"  {r['date']} | {r['boat']} | {r['trip_type_raw']!r} -> stored as {r['trip_length']!r}")
    issues.append(f"{len(rows)} half-day trips mis-stored as '2 Day'")
else:
    print("  OK — none found")

# 2. Trip_length / trip_length_days mismatches
section("2. trip_length vs trip_length_days mismatches")
EXPECTED = {
    "3/4 Day": 0.75, "Full Day": 1.0, "Overnight": 1.0,
    "1.5 Day": 1.5, "2 Day": 2.0, "2.5 Day": 2.5,
    "3 Day": 3.0, "4 Day": 4.0, "5 Day": 5.0,
    "6 Day": 6.0, "7 Day": 7.0, "Long Range": 10.0,
}
rows = c.execute("SELECT DISTINCT trip_length, trip_length_days FROM trips ORDER BY trip_length_days").fetchall()
bad = []
for r in rows:
    exp = EXPECTED.get(r["trip_length"])
    if exp and abs(r["trip_length_days"] - exp) > 0.01:
        bad.append(r)
if bad:
    for r in bad:
        print(f"  {r['trip_length']!r} has days={r['trip_length_days']} (expected {EXPECTED.get(r['trip_length'])})")
    issues.append(f"{len(bad)} trip_length/days mismatches")
else:
    print("  OK — all consistent")

# 3. Trips with 0 or negative anglers
section("3. Trips with 0 or missing anglers")
rows = c.execute("SELECT COUNT(*) as n FROM trips WHERE anglers <= 0").fetchone()
if rows["n"]:
    print(f"  Found {rows['n']} trips with anglers <= 0")
    issues.append(f"{rows['n']} trips with invalid angler count")
else:
    print("  OK — none found")

# 4. Suspiciously high trophy counts (>200 per trip)
section("4. Suspiciously high trophy counts (>200 fish)")
rows = c.execute("""
    SELECT date, boat, landing, trip_length, anglers, trophy_count,
           ROUND(trophy_per_angler, 2) as tpa
    FROM trips WHERE trophy_count > 200
    ORDER BY trophy_count DESC LIMIT 20
""").fetchall()
if rows:
    print(f"  Found {len(rows)} trips with >200 trophy fish:")
    for r in rows:
        print(f"  {r['date']} | {r['boat']} | {r['trip_length']} | {r['anglers']} anglers | {r['trophy_count']} fish | {r['tpa']} tpa")
else:
    print("  OK — none found")

# 5. Suspiciously high trophy per angler (>30 tpa/day)
section("5. Spike trips: trophy_per_angler_per_day > 30")
rows = c.execute("""
    SELECT date, boat, landing, trip_length, anglers, trophy_count,
           ROUND(trophy_per_angler_per_day, 2) as tpad
    FROM trips WHERE trophy_per_angler_per_day > 30
    ORDER BY trophy_per_angler_per_day DESC LIMIT 20
""").fetchall()
if rows:
    print(f"  Found {len(rows)} trips with tpa/day > 30:")
    for r in rows:
        print(f"  {r['date']} | {r['boat']} | {r['trip_length']} | {r['anglers']} anglers | {r['trophy_count']} fish | {r['tpad']} tpa/day")
else:
    print("  OK — none found")

# 6. Unexpected trip_length values (not in approved list)
section("6. Unapproved trip_length values in DB")
APPROVED = {"3/4 Day","Full Day","Overnight","1.5 Day","2 Day","2.5 Day",
            "3 Day","4 Day","5 Day","6 Day","7 Day","Long Range"}
rows = c.execute("SELECT DISTINCT trip_length, COUNT(*) as n FROM trips GROUP BY trip_length ORDER BY trip_length").fetchall()
bad = [r for r in rows if r["trip_length"] not in APPROVED]
if bad:
    for r in bad:
        print(f"  {r['trip_length']!r} — {r['n']} rows")
    issues.append(f"{len(bad)} unapproved trip_length values")
else:
    print("  OK — all trip lengths are approved values")

# 7. Unexpected landing names
section("7. Unexpected landing names")
APPROVED_LANDINGS = {"H&M Landing","Fisherman's Landing","Point Loma Sportfishing","Seaforth Sportfishing"}
rows = c.execute("SELECT DISTINCT landing, COUNT(*) as n FROM trips GROUP BY landing").fetchall()
bad = [r for r in rows if r["landing"] not in APPROVED_LANDINGS]
if bad:
    for r in bad:
        print(f"  {r['landing']!r} — {r['n']} rows")
    issues.append(f"{len(bad)} unexpected landing names")
else:
    print("  OK — all landings are approved")

# 8. Duplicate rows (same date/boat/landing/trip_length/anglers)
section("8. Duplicate rows")
rows = c.execute("""
    SELECT date, boat, landing, trip_length, anglers, COUNT(*) as n
    FROM trips
    GROUP BY date, boat, landing, trip_length, anglers
    HAVING n > 1
""").fetchall()
if rows:
    print(f"  Found {len(rows)} duplicate groups:")
    for r in rows[:10]:
        print(f"  {r['date']} | {r['boat']} | {r['trip_length']} | {r['anglers']} anglers")
    issues.append(f"{len(rows)} duplicate row groups")
else:
    print("  OK — no duplicates")

# Summary
section("SUMMARY")
total = c.execute("SELECT COUNT(*) as n FROM trips").fetchone()["n"]
print(f"  Total trips in DB: {total:,}")
if issues:
    print(f"  Issues found ({len(issues)}):")
    for i in issues:
        print(f"    - {i}")
else:
    print("  No issues found.")

c.close()
