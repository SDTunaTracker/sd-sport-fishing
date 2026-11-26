"""Remove released fish from the extended species columns (calico_bass, etc.).

Until Nov 2026, parse.extract_extended_species counted "N <species> Released"
as N landed fish. This rewrites a cell only when its stored value equals
exactly landed + released recomputed from other_species_json, so a column
filled some other way (text reports, older parsers) is never touched.
Re-running is a no-op.

    .venv\\Scripts\\python.exe scripts\\fix_released_counts.py [--db PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import parse as P  # noqa: E402

_REL = re.compile(r"\bReleased\b", re.I)


def _old_extract(other: dict[str, int]) -> tuple[dict[str, int], int]:
    """The pre-fix behaviour: released entries counted like landed ones."""
    cols = {c: 0 for c in P.EXTENDED_SPECIES_COLUMNS.values()}
    other_fish = 0
    for raw, n in other.items():
        canon = P.normalize_species(raw)
        if canon in P.EXTENDED_SPECIES_COLUMNS:
            cols[P.EXTENDED_SPECIES_COLUMNS[canon]] += n
        elif canon not in P.TRACKED_SPECIES:
            other_fish += n
    return cols, other_fish


def fix(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    cols = list(P.EXTENDED_SPECIES_COLUMNS.values())
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT id, region, other_species_json, other_fish, {', '.join(cols)} FROM trips"
        " WHERE other_species_json LIKE '%eleased%'").fetchall()
    report = {"rows": 0, "by_region": {}, "removed": {c: 0 for c in cols + ['other_fish']}}
    for r in rows:
        other = json.loads(r["other_species_json"] or "{}")
        if not any(_REL.search(k) for k in other):
            continue
        new_cols, new_other, _ = P.extract_extended_species(other)
        old_cols, old_other = _old_extract(other)
        sets = {}
        for c in cols:
            if old_cols[c] != new_cols[c] and (r[c] or 0) == old_cols[c]:
                sets[c] = new_cols[c]
        if old_other != new_other and (r["other_fish"] or 0) == old_other:
            sets["other_fish"] = new_other
        if not sets:
            continue
        report["rows"] += 1
        reg = r["region"] or "san_diego"
        report["by_region"][reg] = report["by_region"].get(reg, 0) + 1
        for c, v in sets.items():
            report["removed"][c] += (r[c] or 0) - v
        if not dry_run:
            conn.execute(f"UPDATE trips SET {', '.join(f'{c}=?' for c in sets)} WHERE id=?",
                         (*sets.values(), r["id"]))
    if not dry_run:
        conn.commit()
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "tracker.db")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rep = fix(sqlite3.connect(a.db), a.dry_run)
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
