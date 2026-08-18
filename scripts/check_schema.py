from pathlib import Path
from src import db

DB_PATH = Path("tracker.db")
with db.connect(DB_PATH) as conn:
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name LIKE 'forecast%'").fetchall()
    for r in rows:
        print("TABLE:", r["name"])
        print(r["sql"])
        print()
