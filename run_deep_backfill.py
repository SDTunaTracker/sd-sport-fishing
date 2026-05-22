"""Deep historical backfill from sandiegofishreports.com.

Walks dates backward from today until either the hard floor (default
2010-01-01) is reached or N consecutive empty days indicate the archive end.
Roughly 30-60 minutes for the full historical sweep at the default throttle.

Usage:
    python run_deep_backfill.py                  # full sweep
    python run_deep_backfill.py --start 2024-12-31 --stop 2024-01-01
    python run_deep_backfill.py --throttle 0.2   # faster (be polite)
"""
import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.deep_backfill import run_deep_backfill  # noqa: E402
from src.main import DB_PATH, _setup_logging      # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=None,
                   help="ISO start date (default: today). Walks backward from here.")
    p.add_argument("--stop", type=date.fromisoformat, default=date(2010, 1, 1),
                   help="ISO hard floor (default: 2010-01-01). Won't go past this.")
    p.add_argument("--throttle", type=float, default=0.3,
                   help="Seconds between requests (default 0.3).")
    p.add_argument("--max-empty-streak", type=int, default=180,
                   help="Stop after this many consecutive days with zero trips (default 180).")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    _setup_logging(verbose=args.verbose)
    run_deep_backfill(
        DB_PATH,
        start=args.start,
        stop=args.stop,
        throttle=args.throttle,
        max_empty_streak=args.max_empty_streak,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
