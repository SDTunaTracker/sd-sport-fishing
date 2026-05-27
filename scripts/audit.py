import sqlite3

conn = sqlite3.connect('tracker.db')
conn.row_factory = sqlite3.Row

print('=== 1A: Data by region/landing ===')
rows = conn.execute('''
SELECT region, landing, COUNT(*) as trips, MIN(date) as earliest, MAX(date) as latest, COUNT(DISTINCT boat) as boats
FROM trips GROUP BY region, landing ORDER BY region, trips DESC
''').fetchall()
for r in rows:
    print(f'  {r["region"]:12} | {r["landing"]:35} | trips={r["trips"]:5} | {r["earliest"]} to {r["latest"]} | boats={r["boats"]}')

print()
print('=== 1B: Scraped today/yesterday ===')
rows = conn.execute('''
SELECT landing, region, COUNT(*) as trips, MAX(date) as latest_date
FROM trips WHERE date >= date('now', '-1 day')
GROUP BY landing, region ORDER BY region, landing
''').fetchall()
for r in rows:
    print(f'  {r["region"]:12} | {r["landing"]:35} | trips={r["trips"]:4} | latest={r["latest_date"]}')
if not rows:
    print('  (no rows)')

print()
print('=== 1C: Scrape log recent runs ===')
rows = conn.execute('''
SELECT landing, started_at as timestamp, status, trips_kept as trips_added, error
FROM scrape_log ORDER BY started_at DESC LIMIT 30
''').fetchall()
for r in rows:
    err = (r["error"] or '')[:60]
    print(f'  {r["timestamp"]} | {r["landing"]:35} | {r["status"]:4} | added={r["trips_added"]} | {err}')
if not rows:
    print('  (no rows)')

print()
print('=== 1D: SD boats with < 5 trips ===')
rows = conn.execute('''
SELECT boat, landing, COUNT(*) as trips FROM trips
WHERE region = 'san_diego' GROUP BY boat, landing HAVING trips < 5 ORDER BY trips ASC
''').fetchall()
for r in rows:
    print(f'  {r["trips"]:3} | {r["boat"]:35} | {r["landing"]}')
if not rows:
    print('  (none)')

print()
print('=== 1D: OC/LA boats with < 5 trips ===')
rows = conn.execute('''
SELECT boat, landing, COUNT(*) as trips FROM trips
WHERE region = 'oc_la' GROUP BY boat, landing HAVING trips < 5 ORDER BY trips ASC
''').fetchall()
for r in rows:
    print(f'  {r["trips"]:3} | {r["boat"]:35} | {r["landing"]}')
if not rows:
    print('  (none)')

print()
print('=== 1E: OC/LA landings with NO data ===')
rows = conn.execute("""
SELECT l.name as landing FROM (
  SELECT '22nd Street Landing' as name
  UNION SELECT 'Dana Wharf Sportfishing'
  UNION SELECT 'Davey''s Locker'
  UNION SELECT 'Newport Landing'
  UNION SELECT 'Long Beach Sportfishing'
  UNION SELECT 'Channel Islands Sportfishing'
  UNION SELECT 'Marina Del Rey Sportfishing'
  UNION SELECT 'Redondo Beach Sportfishing'
  UNION SELECT 'Ventura Harbor Sportfishing'
  UNION SELECT 'Oceanside Sea Center'
) l LEFT JOIN trips t ON t.landing = l.name
WHERE t.landing IS NULL GROUP BY l.name
""").fetchall()
for r in rows:
    print(f'  MISSING: {r["landing"]}')
if not rows:
    print('  (all have data)')

conn.close()
