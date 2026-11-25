"""Warn loudly in run.log if the live tracker.db the shadow reads has gone stale
(e.g. after tracker.db moved to R2 and the laptop copy stopped updating). Read-only."""
import datetime as dt, sqlite3
from pathlib import Path
LIVE = Path(r"C:/Users/Jenelle/Projects/sd-sport-fishing/tracker.db")
con = sqlite3.connect(f"file:{LIVE.as_posix()}?mode=ro", uri=True)
last = con.execute("select max(date) from trips where region='san_diego'").fetchone()[0]; con.close()
age = (dt.date.today() - dt.date.fromisoformat(last)).days
flag = "STALE-DATA WARNING" if age > 2 else "fresh"
print(f"tracker.db freshness: newest SD trip {last} ({age} d old) -> {flag}")
if age > 2:
    print("  Shadow forecasts are being made from old data. Refresh the laptop copy (scripts/db.ps1 pull) once R2 is live.")
