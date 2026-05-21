"""Parsers for trip length, species names, fish-count strings, and report dates.

Kept dependency-free so it's trivially unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# --- Trip length ---------------------------------------------------------

# Canonical bucket -> length in days. Sub-3/4-day buckets are listed so we can
# IDENTIFY them as half-day (in order to exclude), not include them.
TRIP_LENGTHS_DAYS = {
    "Twilight":  0.25,
    "Half Day":  0.5,
    "3/4 Day":   0.75,
    "Full Day":  1.0,
    "Overnight": 1.0,
    "1.5 Day":   1.5,
    "2 Day":     2.0,
    "2.5 Day":   2.5,
    "3 Day":     3.0,
    "4 Day":     4.0,
    "5 Day":     5.0,
    "6 Day":     6.0,
    "7 Day":     7.0,
    "Long Range": 8.0,   # nominal — long-range trips can be 8-23 days
}

# Trips at least this long are kept. User policy: 3/4 day and longer.
MIN_TRIP_DAYS = 0.75


def parse_trip_length(raw: str) -> tuple[str | None, float | None]:
    """Map a raw trip-type label like 'Full Day Coronado Islands' to a canonical
    bucket name + numeric day-length. Returns (None, None) if unrecognized."""
    if not raw:
        return None, None
    s = raw.strip().lower()
    # Order matters: check longer/more-specific patterns first. Decimal lengths
    # (1.5, 2.5) MUST be checked before integers because a naive \b5\b matches
    # the "5" inside "1.5". The (?<![\d.]) lookbehind also blocks partial hits.
    if re.search(r"\blong\s*range\b", s):
        return "Long Range", TRIP_LENGTHS_DAYS["Long Range"]
    for n_label, days in [
        ("1.5", 1.5), ("2.5", 2.5),
        ("7", 7.0), ("6", 6.0), ("5", 5.0), ("4", 4.0), ("3", 3.0), ("2", 2.0),
    ]:
        if re.search(rf"(?<![\d.]){re.escape(n_label)}\s*day\b", s):
            return f"{n_label} Day", days
    if re.search(r"\bovernight\b", s):
        return "Overnight", 1.0
    if re.search(r"\b3/4\s*day\b", s):
        return "3/4 Day", 0.75
    if re.search(r"\bfull\s*day\b", s):
        return "Full Day", 1.0
    if re.search(r"\b1/2\s*day\b|\bhalf\s*day\b", s):
        return "Half Day", 0.5
    if re.search(r"\btwilight\b", s):
        return "Twilight", 0.25
    return None, None


# --- Species normalization -----------------------------------------------

# Canonical species we explicitly track (7).
TRACKED_SPECIES = ("Bluefin", "Yellowfin", "Yellowtail", "Dorado",
                   "Skipjack", "Bigeye", "Albacore")

# Trophy species per user spec.
TROPHY_SPECIES = ("Bluefin", "Yellowfin", "Yellowtail", "Dorado")

# Raw-name -> canonical. Lowercased on lookup.
_SPECIES_ALIASES = {
    "bluefin tuna": "Bluefin",
    "bluefin": "Bluefin",
    "yellowfin tuna": "Yellowfin",
    "yellowfin": "Yellowfin",
    "yellowtail": "Yellowtail",
    "california yellowtail": "Yellowtail",
    "dorado": "Dorado",
    "mahi": "Dorado",
    "mahi-mahi": "Dorado",
    "mahimahi": "Dorado",
    "skipjack tuna": "Skipjack",
    "skipjack": "Skipjack",
    "bigeye tuna": "Bigeye",
    "bigeye": "Bigeye",
    "albacore tuna": "Albacore",
    "albacore": "Albacore",
}


def normalize_species(raw: str) -> str:
    """Return canonical name for one of the 7 tracked species, or the original
    string trimmed of trailing 'Released' markers for everything else."""
    s = raw.strip()
    s_clean = re.sub(r"\s*\bReleased\b\s*$", "", s, flags=re.I).strip()
    return _SPECIES_ALIASES.get(s_clean.lower(), s_clean)


# --- Fish-count tokenization ---------------------------------------------

# Match "<count> <species name>" tokens. Species name runs until the next comma.
_TOK_RE = re.compile(r"(\d[\d,]*)\s+([^,]+?)(?=,|$)")


def parse_fish_counts(text: str) -> tuple[dict[str, int], dict[str, int]]:
    """Parse a fish-count string like '100 Bluefin Tuna, 6 Calico Bass Released, 14 Yellowtail'.

    Returns (tracked, other):
      tracked: {canonical_name: count} for the 7 tracked species
      other:   {raw_name: count}       for everything else (rockfish, bass, etc.)

    'Released' counts are skipped from tracked species (they're catch-and-release,
    not landed trophy fish) but kept under their raw name in `other` for completeness.
    """
    tracked: dict[str, int] = {sp: 0 for sp in TRACKED_SPECIES}
    other: dict[str, int] = {}
    if not text:
        return tracked, other
    for m in _TOK_RE.finditer(text):
        count = int(m.group(1).replace(",", ""))
        raw = m.group(2).strip()
        is_released = bool(re.search(r"\bReleased\b", raw, re.I))
        canon = normalize_species(raw)
        if canon in tracked:
            if is_released:
                # Track released variants under their raw name only.
                other[raw] = other.get(raw, 0) + count
            else:
                tracked[canon] += count
        else:
            other[raw] = other.get(raw, 0) + count
    return tracked, other


# --- Date parsing --------------------------------------------------------

_DATE_RE = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r")\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})\b",
    re.I,
)
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"], start=1)}


def parse_date(text: str) -> date | None:
    """Extract a date from text like 'Fish Counts for May 19th, 2026' or
    'Tuesday May 19th, 2026'. Returns None if no match."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    mo = _MONTHS[m.group(1).lower()]
    return date(int(m.group(3)), mo, int(m.group(2)))


# --- Anglers parsing -----------------------------------------------------

def parse_anglers(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d[\d,]*)", text)
    return int(m.group(1).replace(",", "")) if m else None


# --- Derived trophy metrics ----------------------------------------------

@dataclass
class TrophyMetrics:
    trophy_count: int
    trophy_per_angler: float
    trophy_per_angler_per_day: float


def trophy_metrics(species: dict[str, int], anglers: int, trip_days: float) -> TrophyMetrics:
    total = sum(species.get(sp, 0) for sp in TROPHY_SPECIES)
    per_angler = (total / anglers) if anglers > 0 else 0.0
    per_apd = (per_angler / trip_days) if trip_days > 0 else 0.0
    return TrophyMetrics(total, per_angler, per_apd)
