import sqlite3

c = sqlite3.connect('tracker.db')

tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', [t[0] for t in tables])
print()

try:
    cols = c.execute('PRAGMA table_info(scrape_log)').fetchall()
    print('scrape_log columns:', [(col[1], col[2]) for col in cols])
    rows = c.execute('SELECT * FROM scrape_log ORDER BY rowid DESC LIMIT 50').fetchall()
    print(f'\nLast {len(rows)} scrape_log rows:')
    headers = [col[1] for col in cols]
    print('  ' + ' | '.join(headers))
    for r in rows:
        print(' ', ' | '.join(str(x) for x in r))
except Exception as e:
    print('scrape_log error:', e)

# Also show most recent trip per landing
print()
try:
    rows = c.execute('''
        SELECT landing, MAX(date) as last_date, COUNT(*) as total_trips
        FROM trips
        GROUP BY landing
        ORDER BY last_date DESC
    ''').fetchall()
    print('Most recent trip date per landing:')
    for r in rows:
        print(' ', r)
except Exception as e:
    print('trips query error:', e)
