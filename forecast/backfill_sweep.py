"""Sweep driver for the Marine Cadastre monthly loader.

Loops forecast/backfill_marine_cadastre.py across a --years x --months grid,
most-recent first. Each month runs in its own subprocess so a single-month
crash doesn't sink the whole sweep, and each subprocess is idempotent (the
loader uses INSERT OR IGNORE against UNIQUE(mmsi,timestamp)), so
--start YYYY-MM will safely re-run any month that was mid-flight.

Typical usage (in a real terminal, not through Claude):
    py forecast/backfill_sweep.py --years 2020-2025 --months 3-10
    py forecast/backfill_sweep.py --years 2018-2018 --months 8      # scout one month
    py forecast/backfill_sweep.py --years 2020-2025 --months 3-10 \\
        --start 2023-06                                             # resume after crash
    py forecast/backfill_sweep.py --years 2020-2025 --months 3-10 --dry-run

For overnight runs, redirect output:
    py forecast/backfill_sweep.py --years 2020-2025 --months 3-10 > sweep.log 2>&1

Do NOT start this while scripts/ais_push.py (or another loader) is writing
to tracker.db -- SQLite serialises writers even in WAL mode. The scheduled
5-minute AISStream ingest is fine; it holds the write lock for <45 s per run.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
DB_PATH  = ROOT / "tracker.db"
LOADER   = ROOT / "forecast" / "backfill_marine_cadastre.py"
VENV_PY  = ROOT / ".venv" / "Scripts" / "python.exe"


def parse_range(spec: str, low: int, high: int, label: str) -> tuple[int, int]:
    """Accept 'N', 'N-M', clamp to [low, high]."""
    s = spec.strip()
    if "-" in s:
        lo_s, hi_s = s.split("-", 1)
        lo, hi = int(lo_s), int(hi_s)
    else:
        lo = hi = int(s)
    if lo > hi:
        raise ValueError(f"{label} range low > high: {spec}")
    if lo < low or hi > high:
        raise ValueError(f"{label} range {spec} outside {low}..{high}")
    return lo, hi


def build_plan(year_lo: int, year_hi: int,
               month_lo: int, month_hi: int) -> list[tuple[int, int]]:
    """Year-desc, month-desc: newest month first, so if the sweep is
    interrupted the highest-value data is already banked."""
    plan: list[tuple[int, int]] = []
    for y in range(year_hi, year_lo - 1, -1):
        for m in range(month_hi, month_lo - 1, -1):
            plan.append((y, m))
    return plan


def apply_start(plan: list[tuple[int, int]],
                start_ym: str) -> list[tuple[int, int]]:
    if not start_ym:
        return plan
    y_s, m_s = start_ym.split("-", 1)
    key = (int(y_s), int(m_s))
    for i, entry in enumerate(plan):
        if entry == key:
            return plan[i:]
    raise ValueError(f"--start {start_ym} not in the planned range")


def row_counts() -> tuple[int, int]:
    """Return (total_positions, marine_cadastre_positions)."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        # If the positions table doesn't exist yet (fresh clone), report zeros
        # rather than crash -- the loader's first run will create it.
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='positions'"
        ).fetchone()
        if not exists:
            return 0, 0
        total = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        mc = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE source='marine_cadastre'"
        ).fetchone()[0]
        return total, mc
    finally:
        conn.close()


def fmt_hms(secs: float) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--years",  required=True,
                    help="Year range, e.g. '2020-2025' or '2018'")
    ap.add_argument("--months", required=True,
                    help="Month range, e.g. '3-10' or '8'")
    ap.add_argument("--start",  default="",
                    help="Resume from YYYY-MM (must be inside the planned range)")
    ap.add_argument("--skip",   default="",
                    help="Comma-separated YYYY-MM months to skip "
                         "(useful when a month is already loaded and you'd "
                         "rather not spend bandwidth re-checking dedup)")
    ap.add_argument("--mmsi-file", default="",
                    help="Passed through to the loader (default: 14 curated boats)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan without invoking the loader")
    args = ap.parse_args()

    try:
        y_lo, y_hi = parse_range(args.years,  2015, 2030, "years")
        m_lo, m_hi = parse_range(args.months, 1,    12,   "months")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    plan = build_plan(y_lo, y_hi, m_lo, m_hi)
    try:
        plan = apply_start(plan, args.start)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    skip_set: set[tuple[int, int]] = set()
    for tok in [t.strip() for t in args.skip.split(",") if t.strip()]:
        try:
            ys, ms = tok.split("-", 1)
            skip_set.add((int(ys), int(ms)))
        except ValueError:
            print(f"ERROR: --skip token '{tok}' is not YYYY-MM", file=sys.stderr)
            return 2
    if skip_set:
        plan = [ym for ym in plan if ym not in skip_set]

    if not LOADER.exists():
        print(f"ERROR: loader not found at {LOADER}", file=sys.stderr)
        return 2
    if not VENV_PY.exists():
        print(f"ERROR: venv python not found at {VENV_PY}", file=sys.stderr)
        print("  Sweep needs the venv Python (has zstandard installed).",
              file=sys.stderr)
        return 2

    mmsi_file = args.mmsi_file or "data/boat-mmsi.json"
    print(f"Sweep plan  : {len(plan)} months, newest first")
    print(f"MMSI file   : {mmsi_file}")
    print(f"Loader      : {LOADER.relative_to(ROOT)}")
    print(f"Venv python : {VENV_PY.relative_to(ROOT)}")
    print()
    for i, (y, m) in enumerate(plan, 1):
        print(f"  {i:>3}. {y}-{m:02d}")
    print()

    if args.dry_run:
        print("--dry-run: not invoking loader")
        return 0

    start_total, start_mc = row_counts()
    print(f"positions before sweep: total={start_total:,}  marine_cadastre={start_mc:,}")
    print("=" * 68)
    print()

    sweep_start = time.time()
    failures: list[tuple[int, int, int]] = []   # (year, month, exit_code)
    completed = 0

    try:
        for i, (y, m) in enumerate(plan, 1):
            month_start = time.time()
            pre_mc = row_counts()[1]

            print(f"[{i}/{len(plan)}] {y}-{m:02d}  starting  "
                  f"(elapsed: {fmt_hms(time.time() - sweep_start)})", flush=True)
            cmd = [str(VENV_PY), str(LOADER), "--year", str(y), "--month", str(m)]
            if args.mmsi_file:
                cmd += ["--mmsi-file", args.mmsi_file]

            try:
                rc = subprocess.call(cmd)
            except KeyboardInterrupt:
                print(f"[{i}/{len(plan)}] {y}-{m:02d}  interrupted", flush=True)
                raise

            post_mc = row_counts()[1]
            delta = post_mc - pre_mc
            dt = time.time() - month_start
            status = "OK" if rc == 0 else f"FAIL rc={rc}"
            print(f"[{i}/{len(plan)}] {y}-{m:02d}  {status}  "
                  f"+{delta:,} rows  ({fmt_hms(dt)})", flush=True)

            if rc != 0:
                failures.append((y, m, rc))
            else:
                completed += 1

            # Rolling ETA based on months attempted so far.
            avg = (time.time() - sweep_start) / i
            remaining = (len(plan) - i) * avg
            print(f"       avg/month {fmt_hms(avg)}   ETA remaining: "
                  f"{fmt_hms(remaining)}", flush=True)
            print()
    except KeyboardInterrupt:
        print("\nSWEEP INTERRUPTED (Ctrl-C). Progress so far is committed;")
        print("re-run with --start YYYY-MM to resume from any month.")

    end_total, end_mc = row_counts()
    total_dt = time.time() - sweep_start

    print("=" * 68)
    print("SWEEP DONE")
    print("=" * 68)
    print(f"months attempted    : {completed + len(failures)} / {len(plan)}")
    print(f"months succeeded    : {completed}")
    print(f"months failed       : {len(failures)}")
    for y, m, rc in failures:
        print(f"                       {y}-{m:02d}  rc={rc}")
    print(f"positions before    : total={start_total:,}  mc={start_mc:,}")
    print(f"positions after     : total={end_total:,}  mc={end_mc:,}")
    print(f"delta               : +{end_total - start_total:,}  "
          f"(+{end_mc - start_mc:,} marine_cadastre)")
    print(f"total wall time     : {fmt_hms(total_dt)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
