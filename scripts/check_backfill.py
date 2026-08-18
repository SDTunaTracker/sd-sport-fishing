import sqlite3, os
c = sqlite3.connect('tracker.db')

print('=== OC/LA by landing ===')
for r in c.execute("""
    SELECT region, landing, COUNT(*) as trips, MIN(date) as earliest, MAX(date) as latest, COUNT(DISTINCT boat) as unique_boats
    FROM trips WHERE region = 'oc_la'
    GROUP BY landing ORDER BY trips DESC
"""):
    print(r)

print()
total = c.execute("SELECT COUNT(*) FROM trips WHERE region='oc_la'").fetchone()[0]
print(f'Total OC/LA trips: {total}')

print()
print(f'DB file size: {os.path.getsize("tracker.db"):,} bytes')
