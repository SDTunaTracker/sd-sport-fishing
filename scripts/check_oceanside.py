import sqlite3
c = sqlite3.connect('tracker.db')
print("Oceanside trip lengths:")
for r in c.execute("""
    SELECT trip_length, COUNT(*) as n
    FROM trips WHERE landing = 'Oceanside Sea Center'
    GROUP BY trip_length ORDER BY n DESC
"""):
    print(f"  {r[0]}: {r[1]}")
print()
print("Sample Oceanside trips:")
for r in c.execute("""
    SELECT date, boat, trip_length, anglers, trophy_count, trophy_per_angler_per_day
    FROM trips WHERE landing = 'Oceanside Sea Center'
    ORDER BY date DESC LIMIT 10
"""):
    print(f"  {r[0]}  {r[1]:20s}  {r[2]:12s}  {r[3]}ang  trophy={r[4]}  tpa={r[5]:.2f}")
