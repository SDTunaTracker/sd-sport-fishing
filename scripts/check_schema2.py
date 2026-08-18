from src import db
from pathlib import Path

with db.connect(Path("tracker.db")) as conn:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'forecast%'").fetchall()
    for r in rows:
        print("TABLE:", r[0])
    cols = conn.execute("PRAGMA table_info(forecast_scores)").fetchall()
    print("forecast_scores columns:", [c[1] for c in cols])
