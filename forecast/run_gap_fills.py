"""One-shot runner to re-fill known gaps from the 2020-2025 sweep.

Two categories:
  * Whole months (2025-07 lost to a DB lock; 2022-06 lost 24/30 days to
    network drops) -- re-run without --days for a clean whole-month pass.
  * Targeted day-lists for months where a handful of days dropped -- uses
    the new --days flag on the loader to avoid downloading 30 days when
    we only need 3-14 of them.

The loader now has 3-try exponential backoff on transient network errors,
so most of the ChunkedEncodingErrors that cost us days on the sweep should
self-heal here. INSERT OR IGNORE ensures we don't create duplicates on
days that were already loaded.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
LOADER   = ROOT / "forecast" / "backfill_marine_cadastre.py"
VENV_PY  = ROOT / ".venv" / "Scripts" / "python.exe"

# (year, month, days_spec or None for the whole month)
GAPS: list[tuple[int, int, str | None]] = [
    (2025, 7,  None),                                    # DB lock, all 31 days
    (2022, 6,  None),                                    # 24 of 30 days failed
    (2020, 3,  "03,04,05"),
    (2020, 5,  "03,04,05,13,14,15,17,22,23,24,25"),
    (2020, 6,  "13,20,21,25,29,30"),
    (2021, 8,  "18-31"),
    (2022, 7,  "14-21,25-27,29-31"),
]


def main() -> int:
    print(f"Gap-fill plan: {len(GAPS)} entries")
    for i, (y, m, d) in enumerate(GAPS, 1):
        tag = f"days={d}" if d else "whole month"
        print(f"  {i}. {y}-{m:02d}  {tag}")
    print()

    t0 = time.time()
    failures: list[tuple[int, int, int]] = []
    for i, (y, m, days) in enumerate(GAPS, 1):
        cmd = [str(VENV_PY), str(LOADER), "--year", str(y), "--month", str(m)]
        if days:
            cmd += ["--days", days]
        label = f"{y}-{m:02d}" + (f" days={days}" if days else " whole month")
        elapsed = time.time() - t0
        print(f"\n[{i}/{len(GAPS)}] {label}  (elapsed: {elapsed/60:.1f} min)",
              flush=True)
        rc = subprocess.call(cmd)
        if rc != 0:
            failures.append((y, m, rc))
            print(f"[{i}/{len(GAPS)}] FAIL rc={rc}", flush=True)
        else:
            print(f"[{i}/{len(GAPS)}] OK", flush=True)

    total = time.time() - t0
    print()
    print("=" * 60)
    print("GAP-FILLS DONE")
    print("=" * 60)
    print(f"attempted     : {len(GAPS)}")
    print(f"succeeded     : {len(GAPS) - len(failures)}")
    print(f"failed        : {len(failures)}")
    for y, m, rc in failures:
        print(f"                 {y}-{m:02d}  rc={rc}")
    print(f"total wall time: {total/60:.1f} min")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
