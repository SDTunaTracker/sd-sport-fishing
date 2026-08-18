"""Full rebuild of daily_segment_stats from scratch.

Deletes all rows then calls src.db.update_daily_segment_stats. Used between
wire-up steps to ensure dss reflects the current db.py logic.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import update_daily_segment_stats

DB = ROOT / "tracker.db"


def rebuild() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("DELETE FROM daily_segment_stats")
    con.commit()
    n = update_daily_segment_stats(con)
    con.commit()

    ins = con.execute("SELECT COUNT(*) FROM daily_segment_stats WHERE segment='inshore'").fetchone()[0]
    off = con.execute("SELECT COUNT(*) FROM daily_segment_stats WHERE segment='offshore'").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM daily_segment_stats").fetchone()[0]
    print(f"rebuilt daily_segment_stats: total={tot:,}  inshore={ins:,}  offshore={off:,}")
    con.close()
    return n


if __name__ == "__main__":
    rebuild()
