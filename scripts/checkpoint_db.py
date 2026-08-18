"""Force WAL checkpoint to merge WAL into main db file."""
import sqlite3
conn = sqlite3.connect('tracker.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
total = sqlite3.connect('tracker.db').execute('SELECT COUNT(*) FROM trips').fetchone()[0]
oc_la = sqlite3.connect('tracker.db').execute("SELECT COUNT(*) FROM trips WHERE region='oc_la'").fetchone()[0]
print(f'Checkpoint done. Total trips: {total} (OC/LA: {oc_la})')
import os
print(f'DB size: {os.path.getsize("tracker.db"):,} bytes')
print(f'WAL size: {os.path.getsize("tracker.db-wal") if os.path.exists("tracker.db-wal") else 0:,} bytes')
