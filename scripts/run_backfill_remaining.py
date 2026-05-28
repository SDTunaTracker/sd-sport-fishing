"""Run 976-tuna backfill for the 3 landings not yet completed."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.scrape_ocla import run_backfill

DB = Path(__file__).parents[1] / "tracker.db"

run_backfill(
    DB,
    target_names=["Newport Landing", "Davey's Locker", "Dana Wharf Sportfishing"],
    start_year=2015,
    use_selenium=True,
)
