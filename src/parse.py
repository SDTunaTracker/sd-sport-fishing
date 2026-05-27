"""Parsers for trip length, species names, fish-count strings, and report dates.

Kept dependency-free so it's trivially unit-testable.
"""
from __future__ import annotations

import json
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
    "Full Day":  0.75,
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
    # Check fractional-day labels BEFORE the numbered-day loop.
    # "1/2 day" contains "2 day" and "3/4 day" contains "4 day" — both would be
    # mis-parsed by the loop below because "/" isn't excluded by the lookbehind.
    if re.search(r"\b1/2\s*day\b|\bhalf\s*day\b", s):
        return "Half Day", 0.5
    if re.search(r"\b3/4\s*day\b", s):
        return "Full Day", 0.75
    if re.search(r"\btwilight\b", s):
        return "Twilight", 0.25
    for n_label, days in [
        ("1.5", 1.5), ("2.5", 2.5),
        ("7", 7.0), ("6", 6.0), ("5", 5.0), ("4", 4.0), ("3", 3.0), ("2", 2.0),
    ]:
        if re.search(rf"(?<![\d.]){re.escape(n_label)}\s*day\b", s):
            return f"{n_label} Day", days
    if re.search(r"\bovernight\b", s):
        return "Overnight", 1.0
    if re.search(r"\bfull\s*day\b", s):
        return "Full Day", 0.75
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
    "dolphinfish": "Dorado",
    "skipjack tuna": "Skipjack",
    "skipjack": "Skipjack",
    "bigeye tuna": "Bigeye",
    "bigeye": "Bigeye",
    "albacore tuna": "Albacore",
    "albacore": "Albacore",
}

# Extended species aliases for the 10 new DB columns.
_EXTENDED_ALIASES: dict[str, str] = {
    # Rockfish (many sub-species; wildcard also applied in normalize_species)
    "rockfish": "Rockfish",
    "red rockfish": "Rockfish",
    "black rockfish": "Rockfish",
    "vermilion rockfish": "Rockfish",
    "bocaccio": "Rockfish",
    "chilipepper": "Rockfish",
    "chilipepper rockfish": "Rockfish",
    "copper rockfish": "Rockfish",
    "canary rockfish": "Rockfish",
    "widow rockfish": "Rockfish",
    "greenspotted rockfish": "Rockfish",
    "china rockfish": "Rockfish",
    "blue rockfish": "Rockfish",
    # Sheephead
    "sheephead": "Sheephead",
    "california sheephead": "Sheephead",
    # Bass
    "calico bass": "Calico Bass",
    "calico": "Calico Bass",
    "kelp bass": "Calico Bass",
    "sand bass": "Sand Bass",
    "barred sand bass": "Sand Bass",
    "spotted sand bass": "Sand Bass",
    # Halibut
    "halibut": "Halibut",
    "california halibut": "Halibut",
    "pacific halibut": "Halibut",
    # Lingcod
    "lingcod": "Lingcod",
    # Whitefish
    "whitefish": "Whitefish",
    "ocean whitefish": "Whitefish",
    # Bonito
    "bonito": "Bonito",
    "pacific bonito": "Bonito",
    # Barracuda
    "barracuda": "Barracuda",
    "california barracuda": "Barracuda",
    "pacific barracuda": "Barracuda",
}

# Maps canonical extended-species name -> DB column name.
EXTENDED_SPECIES_COLUMNS: dict[str, str] = {
    "Rockfish":    "rockfish",
    "Sheephead":   "sheephead",
    "Calico Bass": "calico_bass",
    "Sand Bass":   "sand_bass",
    "Halibut":     "halibut",
    "Lingcod":     "lingcod",
    "Whitefish":   "whitefish",
    "Bonito":      "bonito",
    "Barracuda":   "barracuda",
}


def normalize_species(raw: str) -> str:
    """Return canonical name for one of the 7 tracked species, one of the 9
    extended species, or the original string trimmed of trailing 'Released'
    markers for everything else."""
    s = raw.strip()
    s_clean = re.sub(r"\s*\bReleased\b\s*$", "", s, flags=re.I).strip()
    # Strip parenthetical size/weight qualifiers appended by some landings,
    # e.g. "Bluefin Tuna (up to 100 pounds)" → "Bluefin Tuna".
    s_clean = re.sub(r"\s*\(.*?\)\s*$", "", s_clean).strip()
    s_lower = s_clean.lower()
    canon = _SPECIES_ALIASES.get(s_lower) or _EXTENDED_ALIASES.get(s_lower)
    if canon is not None:
        return canon
    # Catch rockfish sub-species not in the explicit alias table (e.g.
    # "Starry Rockfish", "Flag Rockfish") rather than letting them all land
    # in other_fish as unknowns.
    if re.search(r"\brockfish\b", s_clean, re.I):
        return "Rockfish"
    return s_clean


def extract_extended_species(
    other: dict[str, int],
) -> tuple[dict[str, int], int, list[tuple[str, int]]]:
    """Split the 'other' dict from parse_fish_counts into:
      col_counts  – {db_column: total} for the 9 extended tracked species
      other_fish  – sum of counts for truly unrecognized species
      unknowns    – [(raw_name, count)] for unrecognized species (for logging)

    Released variants of the 7 core TRACKED_SPECIES appear in 'other' under
    their raw names (e.g. "Bluefin Released") — they are silently skipped here
    since they're already handled by the tracked columns.
    """
    col_counts = {col: 0 for col in EXTENDED_SPECIES_COLUMNS.values()}
    other_fish = 0
    unknowns: list[tuple[str, int]] = []
    for raw, count in other.items():
        canon = normalize_species(raw)
        if canon in EXTENDED_SPECIES_COLUMNS:
            col_counts[EXTENDED_SPECIES_COLUMNS[canon]] += count
        elif canon in TRACKED_SPECIES:
            pass  # released trophy-fish variant already counted in tracked columns
        else:
            other_fish += count
            unknowns.append((raw, count))
    return col_counts, other_fish, unknowns


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


def metric_days(trip_length_days: float) -> float:
    """Days divisor for per-day metric: round down to nearest whole day, min 1.
    e.g. 0.75→1, 1.0→1, 1.5→1, 2.0→2, 2.5→2, 3.0→3 ..."""
    return max(1.0, float(int(trip_length_days)))


def trophy_metrics(species: dict[str, int], anglers: int, trip_days: float) -> TrophyMetrics:
    total = sum(species.get(sp, 0) for sp in TROPHY_SPECIES)
    per_angler = (total / anglers) if anglers > 0 else 0.0
    per_apd = (per_angler / metric_days(trip_days)) if trip_days > 0 else 0.0
    return TrophyMetrics(total, per_angler, per_apd)


# --- Full catch summary --------------------------------------------------

def build_full_catch(tracked: dict[str, int], other: dict[str, int]) -> str | None:
    """Build a compact JSON string of all landed species for the full_catch column.

    Includes the 7 tracked species (landed only) plus other species with
    canonical names. Released-only variants in `other` are excluded.
    Returns None if no species were caught.
    """
    result: dict[str, int] = {}
    for sp, cnt in tracked.items():
        if cnt > 0:
            result[sp] = cnt
    for raw, cnt in other.items():
        if cnt <= 0:
            continue
        if re.search(r"\bReleased\b", raw, re.I):
            continue
        canon = normalize_species(raw)
        result[canon] = result.get(canon, 0) + cnt
    return json.dumps(result, separators=(',', ':')) if result else None


def build_full_catch_from_db(
    tracked_cols: dict[str, int],
    other_species_json: str | None,
) -> str | None:
    """Reconstruct full_catch from already-stored DB columns (for backfill).

    `tracked_cols` is a dict keyed by canonical species name (Bluefin, etc.).
    `other_species_json` is the raw JSON string from the DB column.
    """
    other: dict[str, int] = {}
    if other_species_json:
        try:
            other = json.loads(other_species_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return build_full_catch(tracked_cols, other)
