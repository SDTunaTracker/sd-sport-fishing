"""Daily-run launcher invoked from Task Scheduler.

Lives at the project root so it can be invoked as a plain script (rather than
via `python -m src.main`), letting Task Scheduler run it without needing to
know about working directories or the src package.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
