import sqlite3
c = sqlite3.connect("tracker.db")
print("OC/LA trips by landing:")
for r in c.execute("""
    SELECT landing, COUNT(*) as n, MIN(date) as earliest, MAX(date) as latest
    FROM trips WHERE region = 'oc_la'
    GROUP BY landing ORDER BY n DESC
"""):
    print(f"  {r[0]:35s} n={r[1]:4d}  {r[2]} to {r[3]}")
print()
print("OC/LA trips by year:")
for r in c.execute("""
    SELECT substr(date,1,4) as yr, COUNT(*) as n
    FROM trips WHERE region = 'oc_la'
    GROUP BY yr ORDER BY yr
"""):
    print(f"  {r[0]}: {r[1]}")
print()
print("OC/LA total:", c.execute("SELECT COUNT(*) FROM trips WHERE region='oc_la'").fetchone()[0])
print("SD total:", c.execute("SELECT COUNT(*) FROM trips WHERE region='san_diego'").fetchone()[0])
