"""NorCal (SF Bay Area) species, regulations, trip targets and the limit-rate metric.

Pure functions, no I/O, so they are easy to unit test.

Owner decisions (2026-11-25, docs/sfbay/LAUNCH_PLAN.md):
  * Region = the core 5 ports: Emeryville, Berkeley, Sausalito, San Francisco,
    Half Moon Bay (Pillar Point). Other NorCal ports are stored as
    `norcal_other` and are not shown.
  * Six-packs are stored but excluded from leaderboards.
  * The headline metric is the **limit rate by target**: each trip's target is
    inferred from its label and catch, and the trip is scored as fish per angler
    as a share of the bag limit for that target, capped at 100%.

Bag limits change. BAG_LIMITS is the single place to edit them, and each entry
names its source. Check it against the current CDFW ocean sport fishing
regulations before launch (go/no-go item in the launch plan).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

# --- Region boundaries -------------------------------------------------------

REGION_SF_BAY = "sf_bay"
REGION_NORCAL_OTHER = "norcal_other"

# City text as printed on norcalfishreports.com ("Emeryville, CA") -> port.
# Only these five ports are in the SF Bay region (owner decision).
SF_BAY_PORTS: dict[str, str] = {
    "emeryville": "Emeryville",
    "berkeley": "Berkeley",
    "sausalito": "Sausalito",
    "san francisco": "San Francisco",
    "half moon bay": "Half Moon Bay",
    # Pillar Point Harbor is in Princeton / El Granada, at Half Moon Bay.
    "princeton": "Half Moon Bay",
    "princeton by the sea": "Half Moon Bay",
    "el granada": "Half Moon Bay",
    "pillar point": "Half Moon Bay",
}


def port_for_city(city: str | None) -> tuple[str | None, str]:
    """Return (port, region) for a city cell like 'Half Moon Bay, CA'."""
    if not city:
        return None, REGION_NORCAL_OTHER
    c = city.split(",")[0].strip().lower().replace("-", " ")
    c = re.sub(r"\s+", " ", c)
    port = SF_BAY_PORTS.get(c)
    if port:
        return port, REGION_SF_BAY
    return city.split(",")[0].strip() or None, REGION_NORCAL_OTHER


# --- Species -----------------------------------------------------------------

# Canonical NorCal species. Anything else keeps its cleaned raw name and is
# logged to unknown_species so it can be added here.
_ALIASES: dict[str, str] = {
    # Salmon
    "king salmon": "King Salmon",
    "chinook salmon": "King Salmon",
    "chinoook salmon": "King Salmon",   # typo seen on 2026-07-18
    "chinook": "King Salmon",
    "salmon": "King Salmon",
    "king": "King Salmon",
    "coho salmon": "Coho Salmon",
    "silver salmon": "Coho Salmon",
    # Rockfish / cabezon / greenling (the "RCG complex", one combined bag)
    "rockfish": "Rockfish",
    "rock cod": "Rockfish",
    "rockcod": "Rockfish",
    "bocaccio": "Rockfish",
    "chilipepper": "Rockfish",
    "cabezon": "Cabezon",
    "greenling": "Greenling",
    "kelp greenling": "Greenling",
    # Lingcod
    "lingcod": "Lingcod",
    "ling cod": "Lingcod",
    # Halibut
    "halibut": "California Halibut",
    "california halibut": "California Halibut",
    "pacific halibut": "Pacific Halibut",
    # Bay species
    "striped bass": "Striped Bass",
    "striper": "Striped Bass",
    "stripers": "Striped Bass",
    "white sturgeon": "White Sturgeon",
    "sturgeon": "White Sturgeon",
    "green sturgeon": "Green Sturgeon",
    "leopard shark": "Leopard Shark",
    "starry flounder": "Starry Flounder",
    "sanddab": "Sanddab",
    "sanddabs": "Sanddab",
    "sand dabs": "Sanddab",
    "pacific sanddab": "Sanddab",
    "petrale sole": "Petrale Sole",
    "jacksmelt": "Jacksmelt",
    # Crab
    "dungeness crab": "Dungeness Crab",
    "dungeness": "Dungeness Crab",
    "crab": "Dungeness Crab",
    "rock crab": "Rock Crab",
    "red rock crab": "Rock Crab",
    # Offshore
    "albacore": "Albacore",
    "albacore tuna": "Albacore",
    "bluefin tuna": "Bluefin",
    "bluefin": "Bluefin",
    "pacific bluefin tuna": "Bluefin",
    "yellowtail": "Yellowtail",
    "white seabass": "White Sea Bass",
    "white sea bass": "White Sea Bass",
    "mako shark": "Mako Shark",
    "thresher shark": "Thresher Shark",
    # Seen in the 2019-2026 samples; no bag limit target, kept as "other".
    "bonito": "Bonito",
    "pacific bonito": "Bonito",
    "mackerel": "Mackerel",
    "pacific mackerel": "Mackerel",
    "sand sole": "Sand Sole",
}


# --- Trip length -------------------------------------------------------------

def trip_length(raw: str | None) -> tuple[str, float]:
    """NorCal labels are loose ('Full Day', 'Crab Combo', 'Bay', '7 Hour',
    'Salmon Trolling California Ocean'). Returns (bucket, days) and never
    fails: unknown labels are treated as a full day, since that is what nearly
    every NorCal open-party trip is."""
    from . import parse as P
    s = (raw or "").lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hour|hr)", s)
    if m:
        hours = float(m.group(1))
        return ("Half Day" if hours <= 6 else "Full Day"), (0.5 if hours <= 6 else 0.75)
    if re.search(r"\b1/4\s*day\b", s):
        return "Half Day", 0.25
    bucket, days = P.parse_trip_length(raw or "")
    if bucket:
        return bucket, days
    return "Full Day", 0.75


def is_half_day(days: float | None) -> bool:
    return days is not None and days < 0.75

KNOWN_SPECIES: frozenset[str] = frozenset(_ALIASES.values())


def normalize_species(raw: str) -> tuple[str, bool]:
    """'2 King Salmon (up to 16 pounds)' name part -> ('King Salmon', released?)."""
    s = raw.strip()
    released = bool(re.search(r"\breleased\b", s, re.I))
    s = re.sub(r"\s*\breleased\b\s*", " ", s, flags=re.I)
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    key = s.lower()
    if key in _ALIASES:
        return _ALIASES[key], released
    if re.search(r"\brockfish\b|\brock ?cod\b", key):
        return "Rockfish", released
    if re.search(r"\bsalmon\b", key):
        return "King Salmon" if "coho" not in key and "silver" not in key else "Coho Salmon", released
    if re.search(r"\bcrab\b", key):
        return ("Dungeness Crab" if "rock" not in key else "Rock Crab"), released
    return s, released


_TOK_RE = re.compile(r"(\d[\d,]*)\s+([^,]+?)(?=,|$)")


def parse_counts(text: str) -> tuple[dict[str, int], dict[str, int], list[tuple[str, int]]]:
    """Parse a dock-totals cell into (landed, released, unknowns).

    landed/released map canonical species -> count. unknowns lists
    (name, count) for species not in KNOWN_SPECIES (landed or released).
    """
    landed: dict[str, int] = {}
    released: dict[str, int] = {}
    unknowns: list[tuple[str, int]] = []
    if not text:
        return landed, released, unknowns
    for m in _TOK_RE.finditer(text):
        n = int(m.group(1).replace(",", ""))
        name, rel = normalize_species(m.group(2))
        bucket = released if rel else landed
        bucket[name] = bucket.get(name, 0) + n
        if name not in KNOWN_SPECIES:
            unknowns.append((name, n))
    return landed, released, unknowns


# --- Regulations (bag limits per angler per day) ------------------------------

# Target groups and the species that count toward each group's bag limit.
GROUP_SPECIES: dict[str, tuple[str, ...]] = {
    "rcg":       ("Rockfish", "Cabezon", "Greenling"),
    "lingcod":   ("Lingcod",),
    "salmon":    ("King Salmon",),
    "halibut":   ("California Halibut",),
    "striper":   ("Striped Bass",),
    "sturgeon":  ("White Sturgeon",),
    "crab":      ("Dungeness Crab",),
    "albacore":  ("Albacore",),
    "bluefin":   ("Bluefin",),
}

# Bag limit per angler. None = no harvest allowed (catch and release only), so
# the target is ranked by fish per angler instead of a limit rate.
# Checked 2026-11-26 against CDFW's 2026 Ocean Sport Fishing Regulations
# (last updated July 17, 2026) and the Groundfish Summary page (June 23, 2026).
# Re-check each year when the new booklet is out.
BAG_LIMITS: dict[str, dict] = {
    "rcg":      {"limit": 10,   "note": "RCG complex: rockfish, cabezon, greenling combined (CDFW ocean regs)"},
    "lingcod":  {"limit": 2,    "note": "CDFW ocean regs"},
    "salmon":   {"limit": 2,    "note": "Ocean king salmon, in season only (season set yearly by PFMC/CDFW)"},
    "halibut":  {"limit": 2,    "note": "California halibut north of Pt. Sur (T14 CCR 28.15; 5 south of Pt. Sur)"},
    "striper":  {"limit": 2,    "note": "Striped bass, statewide"},
    "sturgeon": {"limit": None, "note": "White sturgeon: harvest closed since 2024 (catch and release)"},
    "crab":     {"limit": 10,   "note": "Dungeness crab, from a CPFV"},
    "albacore": {"limit": 25,   "note": "Albacore north of Pt. Conception"},
    "bluefin":  {"limit": 2,    "note": "Pacific bluefin tuna"},
}

# Public trip targets (what a boat was fishing for). Each maps to the groups
# whose limit rate scores it; a combo averages its groups.
TARGETS: dict[str, dict] = {
    "rockfish":   {"label": "Rockfish & Lingcod", "groups": ("rcg",)},
    "salmon":     {"label": "Salmon",             "groups": ("salmon",)},
    "halibut":    {"label": "Halibut",            "groups": ("halibut",)},
    "striper":    {"label": "Striped Bass",       "groups": ("striper",)},
    "bay_mixed":  {"label": "Halibut & Stripers", "groups": ("halibut", "striper")},
    "sturgeon":   {"label": "Sturgeon",           "groups": ("sturgeon",)},
    "crab_combo": {"label": "Crab & Rockfish",    "groups": ("crab", "rcg")},
    "crab":       {"label": "Crab",               "groups": ("crab",)},
    "albacore":   {"label": "Albacore",           "groups": ("albacore",)},
    "bluefin":    {"label": "Bluefin",            "groups": ("bluefin",)},
    "unknown":    {"label": "Unclassified",       "groups": ()},
}

_GROUP_TO_TARGET = {
    "rcg": "rockfish", "lingcod": "rockfish", "salmon": "salmon", "halibut": "halibut",
    "striper": "striper", "sturgeon": "sturgeon", "crab": "crab",
    "albacore": "albacore", "bluefin": "bluefin",
}

# Trip-label hints override catch-based inference ("Full Day Crab Combo").
_LABEL_HINTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"crab\s*(?:&|and|/)?\s*(?:rock|combo)|combo", re.I), "crab_combo"),
    (re.compile(r"\bcrab", re.I), "crab"),
    (re.compile(r"salmon", re.I), "salmon"),
    (re.compile(r"sturgeon", re.I), "sturgeon"),
    (re.compile(r"albacore|tuna", re.I), "albacore"),
    (re.compile(r"halibut\s*(?:&|and|/)\s*striper|striper\s*(?:&|and|/)\s*halibut", re.I), "bay_mixed"),
    (re.compile(r"halibut", re.I), "halibut"),
    (re.compile(r"striper|striped", re.I), "striper"),
    (re.compile(r"rock\s*(?:fish|cod)|bottom|ling", re.I), "rockfish"),
)


def group_counts(landed: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for g, species in GROUP_SPECIES.items():
        n = sum(landed.get(s, 0) for s in species)
        if n:
            out[g] = n
    return out


def _group_rate(group: str, n: int, anglers: int) -> float | None:
    lim = BAG_LIMITS[group]["limit"]
    if not lim or anglers <= 0:
        return None
    return min(1.0, n / (anglers * lim))


def infer_target(trip_label: str | None, landed: dict[str, int], anglers: int) -> str:
    """Best guess at what the trip fished for. 'unknown' when nothing was caught
    and the label gives no hint (export.py then borrows the boat's recent target)."""
    label = trip_label or ""
    for pat, target in _LABEL_HINTS:
        if pat.search(label):
            if target == "crab_combo" and not landed.get("Dungeness Crab") and landed:
                break  # 'combo' label but no crab: fall through to catch-based
            return target
    groups = group_counts(landed)
    if not groups:
        return "unknown"
    # Crab plus a real rockfish catch = combo trip.
    crab_r = _group_rate("crab", groups.get("crab", 0), anglers) or 0
    rcg_r = _group_rate("rcg", groups.get("rcg", 0), anglers) or 0
    if crab_r >= 0.2 and rcg_r >= 0.2:
        return "crab_combo"
    # Halibut and stripers together on a Bay drift.
    hal_r = _group_rate("halibut", groups.get("halibut", 0), anglers) or 0
    str_r = _group_rate("striper", groups.get("striper", 0), anglers) or 0
    if hal_r >= 0.15 and str_r >= 0.15:
        return "bay_mixed"

    def score(g: str) -> float:
        r = _group_rate(g, groups[g], anglers)
        if r is None:  # catch-and-release species: use fish per angler
            return min(1.0, groups[g] / max(anglers, 1))
        return r

    best = max(groups, key=score)
    return _GROUP_TO_TARGET[best]


def limit_rate(target: str, landed: dict[str, int], anglers: int) -> float | None:
    """Share of the bag limit landed per angler for the trip's target (0..1).
    None for targets with no harvest limit (sturgeon) or 'unknown'."""
    groups = TARGETS.get(target, TARGETS["unknown"])["groups"]
    if not groups or anglers <= 0:
        return None
    gc = group_counts(landed)
    rates = [_group_rate(g, gc.get(g, 0), anglers) for g in groups]
    rates = [r for r in rates if r is not None]
    if not rates:
        return None
    return sum(rates) / len(rates)


def fill_unknown_targets(trips: list[dict], window_days: int = 14) -> None:
    """For skunked trips (no catch, no label hint) borrow the boat's most common
    target within +/- window_days, so zeros count against the right target.
    Mutates trips in place: expects keys 'date' (ISO), 'boat', 'target'."""
    from datetime import date as _d
    by_boat: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for t in trips:
        if t["target"] != "unknown":
            by_boat[t["boat"]].append((_d.fromisoformat(t["date"]).toordinal(), t["target"]))
    for t in trips:
        if t["target"] != "unknown":
            continue
        day = _d.fromisoformat(t["date"]).toordinal()
        near = Counter(tg for d, tg in by_boat.get(t["boat"], ()) if abs(d - day) <= window_days)
        if near:
            t["target"] = near.most_common(1)[0][0]
            t["target_borrowed"] = True


# --- Six-packs -----------------------------------------------------------------

SIXPACK_MAX_ANGLERS = 6
SIXPACK_MIN_TRIPS = 3

# Human-verified overrides (boat slug -> True six-pack / False open-party).
SIXPACK_OVERRIDES: dict[str, bool] = {}


def classify_sixpacks(trips: Iterable[dict]) -> dict[str, bool]:
    """Boat slug -> is six-pack. A boat is a six-pack when it never carried more
    than 6 anglers across at least 3 trips (the SD rule in sixpack_boats.py).
    Boats with fewer trips are classified by their max so far."""
    mx: dict[str, int] = {}
    n: Counter = Counter()
    for t in trips:
        k = t["boat_slug"]
        mx[k] = max(mx.get(k, 0), t["anglers"])
        n[k] += 1
    out = {k: v <= SIXPACK_MAX_ANGLERS for k, v in mx.items()}
    out.update(SIXPACK_OVERRIDES)
    return out


# --- Seasonality / slow season -------------------------------------------------

# Rough calendar used for copy and the slow-season state (months 1-12).
# Salmon dates are set yearly. Treat as defaults, checked against the regs.
SEASONS: dict[str, dict] = {
    "rockfish":   {"months": [4, 5, 6, 7, 8, 9, 10, 11, 12], "note": "Groundfish season, typically Apr–Dec (depth limits vary)"},
    "salmon":     {"months": [5, 6, 7, 8, 9, 10], "note": "Ocean salmon season is set each spring; closed 2023–2025"},
    "halibut":    {"months": [4, 5, 6, 7, 8, 9], "note": "Bay halibut drifts, spring to fall"},
    "striper":    {"months": [4, 5, 6, 7, 8, 9, 10], "note": "Bay and coast stripers"},
    "crab_combo": {"months": [11, 12], "note": "Dungeness opener early Nov through the end of groundfish season"},
    "crab":       {"months": [11, 12, 1, 2, 3, 4, 5, 6], "note": "Dungeness season Nov–Jun (delays for whales/domoic acid)"},
    "sturgeon":   {"months": [1, 2, 3, 11, 12], "note": "Winter Bay sturgeon (catch and release)"},
    "albacore":   {"months": [8, 9, 10], "note": "When warm water comes within range"},
}

# Fewer than this many open-party trips in the last 7 days = "slow season" UI.
SLOW_SEASON_TRIPS_7D = 10
