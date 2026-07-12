"""Six-pack (USCG uninspected passenger vessel, ≤6 anglers) exclusion list.

Single source of truth. Read here, exported to the frontend via
`window.SD.SIXPACK_BOATS` in export.py. Every downstream consumer — the
Analytics universe filter, the verify script, any future config UI — MUST
read from `SIXPACK_BOATS` below rather than hard-coding names.

The list is derived programmatically from forecast/sixpack_candidates.csv
(built by scripts/sixpack_analysis.py from the live trips table):

  - Every row classified HIGH_CONFIDENCE_SIXPACK (max_anglers <= 6, ≥10 trips)
  - PLUS `_MANUAL_ADDITIONS` — human-verified six-packs the classifier missed.

That yields 21 boats. If the CSV is regenerated later, this module picks up
the new HIGH_CONFIDENCE set automatically; the manual-additions list is the
only piece that lives in code and must be updated by hand.

Matching contract for downstream code:
  Case-insensitive AND whitespace-trimmed on both sides. The DB carries
  casing dupes (e.g. Mardiosa vs MarDiosa) that would slip past exact-case
  matching. Use `normalize()` on both the boat name and the exclusion set.
"""
from __future__ import annotations

import csv
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CSV = _HERE.parent / "forecast" / "sixpack_candidates.csv"

_HIGH_CLASS = "HIGH_CONFIDENCE_SIXPACK"

# Boats the classifier did NOT auto-flag as HIGH_CONFIDENCE_SIXPACK but that
# human review has confirmed as private six-pack charters. Add here (verbatim
# stored name) when you confirm a new one.
#
# - Lucky B Sportfishing: classified REVIEW_BORDERLINE (max_anglers=8). User
#   promoted 2026-07-12 — max=8 is data noise/rare full-boat, actually a 6-pack.
# - El Gato Dos: classified OPEN_PARTY (max_anglers=22, 858 trips). User
#   confirmed 2026-07-12 — private charter regardless of the 22-angler outliers,
#   which are almost certainly scraper artifacts or co-op charter mis-counts.
_MANUAL_ADDITIONS: tuple[str, ...] = (
    "Lucky B Sportfishing",
    "El Gato Dos",
)


def load_sixpack_boats() -> list[str]:
    """Return the canonical exclusion list — exact stored name strings."""
    if not _CSV.exists():
        raise FileNotFoundError(
            f"{_CSV} not found. Run scripts/sixpack_analysis.py first."
        )
    high_conf: list[str] = []
    with _CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["classification"] == _HIGH_CLASS:
                high_conf.append(row["boat"])
    # CSV rows come pre-sorted by trip_count desc within class. Append the
    # manual additions at the end so the canonical order is stable.
    result = list(high_conf)
    for name in _MANUAL_ADDITIONS:
        if name not in result:
            result.append(name)
    return result


def normalize(name: str) -> str:
    """Match key: case-insensitive, whitespace-trimmed on both ends."""
    return name.strip().lower() if name else ""


def normalized_set(names: list[str] | tuple[str, ...] | None = None) -> set[str]:
    """Build a normalized lookup set. Defaults to the canonical SIXPACK_BOATS."""
    return {normalize(n) for n in (names if names is not None else SIXPACK_BOATS)}


SIXPACK_BOATS: list[str] = load_sixpack_boats()
