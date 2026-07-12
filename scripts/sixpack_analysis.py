"""Read-only classification of boats as six-pack (USCG uninspected passenger
vessel, legally capped at 6 paying passengers) vs open party boats.

Discriminator is the MAX angler count across a boat's trips: a six-pack
physically can't exceed 6; an open party boat's seasonal max is well above 6.

Reads: tracker.db (opened read-only via ?mode=ro).
Writes: forecast/sixpack_candidates.csv only.
Does not touch analytics, frontend, tables, or scraped data.
"""
from __future__ import annotations

import csv
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "tracker.db"
CSV_OUT = ROOT / "forecast" / "sixpack_candidates.csv"

sys.path.insert(0, str(ROOT))
from src.dates import to_pacific_date, PACIFIC  # noqa: E402

# User-supplied seed list. "El Gato Dos Freeman 34" is not a single stored
# name, so split defensively and flag both interpretations for the user.
SEEDS = [
    "Lucky B Sportfishing",
    "Got Bait",
    "El Gato Dos Freeman 34",  # not present as a single boat — validated below
    "El Gato Dos",              # present — 858 trips
    "Freeman 34",               # present — 12 trips
    "Nautilus",
]


def p90(values: list[int]) -> float:
    """90th percentile using inclusive method (statistics.quantiles)."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    cuts = statistics.quantiles(values, n=10, method="inclusive")
    return round(cuts[8], 2)  # 9th cut point = p90


def pacific_date_from_stored(s: str) -> date | None:
    """The `date` column in trips is already a Pacific calendar date string
    (the scraper writes pacific_today()). Parse it directly. For scraped_at
    fields (UTC iso), we would use to_pacific_date — this project stores the
    fishing date already-Pacific, so no re-derivation is needed here."""
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def scraped_at_to_pacific(s: str) -> date | None:
    """Verify to_pacific_date works on scraped_at (tz-aware ISO)."""
    try:
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return to_pacific_date(ts)
    except (ValueError, TypeError):
        return None


def load_stats() -> dict[str, dict]:
    """Group trips by boat, computing angler stats and Pacific date range."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # anglers per boat + dates
    by_boat: dict[str, dict] = defaultdict(
        lambda: {"anglers": [], "dates": [], "landings": set()}
    )
    for row in conn.execute(
        "SELECT boat, anglers, date, landing FROM trips"
    ):
        boat = row["boat"]
        by_boat[boat]["anglers"].append(int(row["anglers"]))
        d = pacific_date_from_stored(row["date"])
        if d:
            by_boat[boat]["dates"].append(d)
        by_boat[boat]["landings"].add(row["landing"])
    conn.close()

    out = {}
    for boat, data in by_boat.items():
        a = data["anglers"]
        d = data["dates"]
        out[boat] = {
            "boat": boat,
            "trip_count": len(a),
            "min": min(a),
            "mean": round(statistics.mean(a), 2),
            "median": round(statistics.median(a), 1),
            "p90": p90(a),
            "max": max(a),
            "first_date": min(d).isoformat() if d else "?",
            "last_date":  max(d).isoformat() if d else "?",
            "landings": ", ".join(sorted(data["landings"])),
        }
    return out


def classify(stats: dict) -> str:
    mx, tc, p = stats["max"], stats["trip_count"], stats["p90"]
    if mx <= 6 and tc >= 10:
        return "HIGH_CONFIDENCE_SIXPACK"
    if mx <= 6 and tc < 10:
        return "REVIEW_SMALL_SAMPLE"
    if p <= 6 and 7 <= mx <= 10:
        return "REVIEW_BORDERLINE"
    return "OPEN_PARTY"


# Column widths for the report table
COL = {"boat": 30, "trips": 6, "mean": 7, "p90": 6, "max": 5, "range": 25}


def fmt_row(s: dict) -> str:
    return (
        f"  {s['boat']:<{COL['boat']}}  "
        f"{s['trip_count']:>{COL['trips']}}  "
        f"{s['mean']:>{COL['mean']}}  "
        f"{s['p90']:>{COL['p90']}}  "
        f"{s['max']:>{COL['max']}}  "
        f"{s['first_date']} -> {s['last_date']}"
    )


def fmt_header() -> str:
    return (
        f"  {'boat':<{COL['boat']}}  "
        f"{'trips':>{COL['trips']}}  "
        f"{'mean':>{COL['mean']}}  "
        f"{'p90':>{COL['p90']}}  "
        f"{'max':>{COL['max']}}  "
        f"date range"
    )


def main() -> int:
    if not DB.exists():
        print(f"ERROR: tracker.db not found at {DB}", file=sys.stderr)
        return 1

    print("=" * 78)
    print("SIX-PACK CANDIDATE ANALYSIS  (read-only)")
    print(f"DB: {DB}")
    print(f"pacific_now: {datetime.now(PACIFIC).isoformat(timespec='seconds')}")
    print("=" * 78)
    print()

    stats = load_stats()
    print(f"Total distinct boats in tracker.db: {len(stats)}")
    print(f"Total trips: {sum(s['trip_count'] for s in stats.values())}")
    print()

    # --Step 1: Seed validation --──────────────────────────────────────
    print("=" * 78)
    print("STEP 1 — SEED VALIDATION")
    print("=" * 78)
    print()
    print("Note on 'El Gato Dos Freeman 34':")
    print("  This string does NOT exist as a stored boat name. It looks like two")
    print("  boats concatenated. Validating both 'El Gato Dos' and 'Freeman 34'")
    print("  as separate seed candidates so the user can choose which is intended.")
    print()
    print(fmt_header())
    print("  " + "-" * 76)
    seed_stats = []
    for seed in SEEDS:
        s = stats.get(seed)
        if s is None:
            print(f"  {seed:<{COL['boat']}}  *** NOT FOUND in trips table ***")
            continue
        seed_stats.append(s)
        print(fmt_row(s))
    print()
    over_ceiling = [s for s in seed_stats if s["max"] > 6]
    if over_ceiling:
        print("!" * 78)
        print("!! LOUD FLAG: the following seed boats have max_anglers > 6.")
        print("!! Either the seed is wrong or the name-match is picking up an unrelated")
        print("!! open-party boat sharing this name. RESOLVE BEFORE TRUSTING THE REST.")
        print("!" * 78)
        for s in over_ceiling:
            print(f"  {s['boat']!r}: max={s['max']}  trips={s['trip_count']}  "
                  f"landings=[{s['landings']}]")
        print("!" * 78)
    else:
        print("OK: every seed has max_anglers <= 6.")
    print()

    # --Step 2: Score every boat (loaded above) --──────────────────────
    # --Step 3: Classify --─────────────────────────────────────────────
    for s in stats.values():
        s["classification"] = classify(s)

    # --Print HIGH CONFIDENCE + REVIEW sets --──────────────────────────
    order = {
        "HIGH_CONFIDENCE_SIXPACK": 0,
        "REVIEW_SMALL_SAMPLE": 1,
        "REVIEW_BORDERLINE": 2,
        "OPEN_PARTY": 3,
    }
    print("=" * 78)
    print("STEP 3 — CLASSIFICATION SUMMARY")
    print("=" * 78)
    print()
    counts: dict[str, int] = defaultdict(int)
    for s in stats.values():
        counts[s["classification"]] += 1
    for cls in sorted(counts, key=lambda c: order[c]):
        print(f"  {cls:<28} {counts[cls]:>4}")
    print()

    for cls in ["HIGH_CONFIDENCE_SIXPACK", "REVIEW_SMALL_SAMPLE",
                "REVIEW_BORDERLINE"]:
        rows = [s for s in stats.values() if s["classification"] == cls]
        rows.sort(key=lambda s: (-s["trip_count"], s["boat"]))
        print(f"--{cls} ({len(rows)} boats) --")
        if not rows:
            print("  (none)")
            print()
            continue
        print(fmt_header())
        print("  " + "-" * 76)
        for s in rows:
            print(fmt_row(s))
        print()

    # --Write CSV --────────────────────────────────────────────────────
    CSV_OUT.parent.mkdir(exist_ok=True)
    fields = [
        "boat", "classification", "trip_count", "min_anglers", "mean_anglers",
        "median_anglers", "p90_anglers", "max_anglers", "first_date_pacific",
        "last_date_pacific", "landings",
    ]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in sorted(
            stats.values(),
            key=lambda x: (order[x["classification"]], -x["trip_count"], x["boat"]),
        ):
            w.writerow({
                "boat": s["boat"],
                "classification": s["classification"],
                "trip_count": s["trip_count"],
                "min_anglers": s["min"],
                "mean_anglers": s["mean"],
                "median_anglers": s["median"],
                "p90_anglers": s["p90"],
                "max_anglers": s["max"],
                "first_date_pacific": s["first_date"],
                "last_date_pacific": s["last_date"],
                "landings": s["landings"],
            })
    print(f"CSV written: {CSV_OUT}  ({len(stats)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
