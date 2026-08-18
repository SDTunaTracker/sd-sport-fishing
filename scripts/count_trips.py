import sqlite3
c = sqlite3.connect('tracker.db')
total = c.execute('SELECT COUNT(*) FROM trips').fetchone()[0]
oc_la = c.execute("SELECT COUNT(*) FROM trips WHERE region != 'san_diego'").fetchone()[0]
sd = c.execute("SELECT COUNT(*) FROM trips WHERE region = 'san_diego'").fetchone()[0]
print(f'Total trips: {total:,}')
print(f'San Diego:   {sd:,}')
print(f'OC/LA:       {oc_la:,}')
print()
rows = c.execute("SELECT landing, COUNT(*) as n FROM trips WHERE region != 'san_diego' GROUP BY landing ORDER BY n DESC").fetchall()
for name, n in rows:
    print(f'  {name:35s} {n:>5,}')
