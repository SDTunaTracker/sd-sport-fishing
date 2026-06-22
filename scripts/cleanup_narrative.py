"""One-time narrative-row cleanup for the last N days.

Deletes:
  1. Narrative rows (source != 'fish_count_page') whose (date, boat, landing,
     trip_length normalized) collides with an existing structured row —
     enforcing the new structured-wins precedence on already-stored data.
  2. Narrative rows with anglers <= 0 — these are parse artifacts the new
     harvester would never produce.

Reports counts and previews. Default lookback is 3 days (matches the user-
specified cleanup window); pass an int to override. Pass --dry-run to
preview without deleting.

Note: some zero-angler rows contain real catch data that the OLD harvester
failed to parse anglers from (the new harvester would have caught them).
Deleting them is data loss for trips that have no structured-page sibling.
This is intentional per the strictness rule: narrative-only trips without
proven angler counts are treated as parse artifacts.

Usage:
    python -m scripts.cleanup_narrative                # last 3 days, apply
    python -m scripts.cleanup_narrative 7              # last 7 days, apply
    python -m scripts.cleanup_narrative --dry-run      # preview only
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dates import pacific_today

DB_PATH = ROOT / "tracker.db"


def _norm_tl(s: str | None) -> str:
    return ' '.join((s or '').lower().split()).replace(' / ', '/')


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    args = [a for a in argv[1:] if a != "--dry-run"]
    lookback_days = int(args[0]) if args else 3

    since = (pacific_today() - timedelta(days=lookback_days)).isoformat()
    print(f"Cleanup window: {since} → {pacific_today().isoformat()}  ({lookback_days} days)")
    print(f"DB:             {DB_PATH}")
    print(f"Mode:           {'DRY-RUN (no deletes)' if dry_run else 'APPLY'}")
    print()

    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row

    # ── 1) structured-wins conflicts ─────────────────────────────────────────
    print("── Scanning for narrative rows blocked by structured-wins ──")
    structured_keys: set[tuple] = set()
    for r in con.execute(
        "SELECT date, lower(boat), lower(landing), trip_length FROM trips "
        "WHERE source = 'fish_count_page' AND date >= ?",
        (since,),
    ):
        structured_keys.add((r[0], r[1], r[2], _norm_tl(r[3])))

    narratives = con.execute(
        "SELECT id, date, boat, landing, trip_length, anglers, source, "
        "trophy_count, written_text FROM trips "
        "WHERE source != 'fish_count_page' AND date >= ?",
        (since,),
    ).fetchall()
    print(f"  narrative rows in window: {len(narratives)}")
    print(f"  structured keys loaded:   {len(structured_keys)}")

    to_delete_structured: list[sqlite3.Row] = []
    for n in narratives:
        key = (n["date"], (n["boat"] or "").lower(),
               (n["landing"] or "").lower(), _norm_tl(n["trip_length"]))
        if key in structured_keys:
            to_delete_structured.append(n)

    print(f"  blocked by structured-wins: {len(to_delete_structured)}")
    if to_delete_structured:
        print("  preview (first 12):")
        for n in to_delete_structured[:12]:
            print(f"    id={n['id']:<7d} {n['date']} {n['landing']:<25s} {n['boat']:<20s} "
                  f"{n['trip_length']:<12s} src={n['source']} trophy={n['trophy_count']}")
        if len(to_delete_structured) > 12:
            print(f"    ... and {len(to_delete_structured) - 12} more")

    print()

    # ── 2) narrative rows with anglers <= 0 ──────────────────────────────────
    print("── Scanning for narrative rows with anglers <= 0 ──")
    zero_ang = con.execute(
        "SELECT id, date, boat, landing, trip_length, anglers, source, "
        "trophy_count, written_text FROM trips "
        "WHERE source != 'fish_count_page' AND date >= ? AND (anglers IS NULL OR anglers <= 0)",
        (since,),
    ).fetchall()
    # Remove ones already in to_delete_structured to avoid double-deleting
    already = {n["id"] for n in to_delete_structured}
    zero_ang_unique = [n for n in zero_ang if n["id"] not in already]
    print(f"  found anglers<=0: {len(zero_ang)} (unique-from-above: {len(zero_ang_unique)})")
    if zero_ang_unique:
        print("  preview (first 12):")
        for n in zero_ang_unique[:12]:
            print(f"    id={n['id']:<7d} {n['date']} {n['landing']:<25s} {n['boat']:<20s} "
                  f"{n['trip_length']:<12s} src={n['source']} trophy={n['trophy_count']}")
            if n['written_text']:
                txt = n['written_text'].replace('\n', ' ')[:120]
                print(f"             txt: {txt}")
        if len(zero_ang_unique) > 12:
            print(f"    ... and {len(zero_ang_unique) - 12} more")

    # ── Apply ────────────────────────────────────────────────────────────────
    total_unique = len(to_delete_structured) + len(zero_ang_unique)
    print()
    print(f"Total unique rows to delete: {total_unique}")

    if dry_run:
        print("(dry-run — nothing deleted)")
        return 0

    if not total_unique:
        print("Nothing to delete.")
        return 0

    ids = [n["id"] for n in to_delete_structured] + [n["id"] for n in zero_ang_unique]
    placeholders = ",".join("?" * len(ids))
    deleted = con.execute(
        f"DELETE FROM trips WHERE id IN ({placeholders})", ids,
    ).rowcount
    con.commit()
    print(f"Deleted {deleted} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
