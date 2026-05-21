"""One-time backfill: pull each boat's historical fish counts into tracker.db.

Usage:
    python run_backfill.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.backfill import run_backfill  # noqa: E402
from src.main import DB_PATH, _setup_logging  # noqa: E402

if __name__ == "__main__":
    _setup_logging(verbose=False)
    run_backfill(DB_PATH)
