"""Research-only: append today's scheduled_trips (open spots / capacity) to a local history so
booking velocity (H3) can be backtested later. Reads the live DB read-only; writes only here."""
import datetime as dt, sqlite3
from pathlib import Path
import pandas as pd
HERE = Path(__file__).parent
LIVE = Path(r"C:/Users/Jenelle/Projects/sd-sport-fishing/tracker.db")
con = sqlite3.connect(f"file:{LIVE.as_posix()}?mode=ro", uri=True)
s = pd.read_sql("select landing, boat, trip_type_raw, trip_length, trip_length_days, departure_at, return_at, "
                "price, capacity, open_spots, reserved_spots, trip_status, scraped_at from scheduled_trips", con)
con.close()
s.insert(0, "snapshot_utc", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
out = HERE / "schedule_snapshots.csv"
s.to_csv(out, mode="a", header=not out.exists(), index=False)
print(f"schedule snapshot: {len(s)} rows -> {out.name}")
