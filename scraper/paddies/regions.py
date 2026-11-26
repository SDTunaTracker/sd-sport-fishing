"""
Region tags for BloodyDecks items, matching the site's regions (web/regions.js):
  "san_diego" | "oc_la" | "both" | None (can't tell)

Evidence, combined as a union:
  * the boat's landing (web/regions.js SD_LANDINGS / OCLA_LANDINGS)
  * the places mentioned, by where they are (region_for_point)
  * place keywords in the thread title (Catalina, Palos Verdes, Point Loma...)
  * the forum itself, only as a fallback (Long Range / Baja = San Diego fleet)

An SD boat fishing Catalina is "both": the trip belongs to SD, the spot to OC/LA,
and the owner wants Catalina reports on the OC/LA page.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGIONS_JS = ROOT / "web" / "regions.js"

SD, OCLA, BOTH = "san_diego", "oc_la", "both"

# Fallback if web/regions.js can't be read (kept in sync by a test).
_FALLBACK = {
    SD: ["H&M Landing", "Fisherman's Landing", "Seaforth Sportfishing", "Point Loma Sportfishing",
         "Oceanside Sea Center"],
    OCLA: ["22nd Street Landing", "Long Beach Sportfishing", "LA Waterfront Sportfishing",
           "Marina Del Rey Sportfishing", "Redondo Beach Sportfishing", "Pierpoint Landing",
           "Channel Islands Sportfishing", "Hooks Landing", "Ventura Harbor Sportfishing",
           "Newport Landing", "Davey's Locker", "Dana Wharf Sportfishing"],
}

# Feeds whose posts are San Diego fleet by default (long range leaves from SD).
FEED_DEFAULT = {"bd-long-range": SD, "bd-baja": SD}

OCLA_WORDS = re.compile(
    r"\b(catalina|avalon|isthmus|two harbors|san clemente island|sci\b|dana point|dana wharf|"
    r"davey'?s locker|newport|huntington|palos verdes|\bpv\b|horseshoe|14 mile|lasuen|"
    r"redondo|marina del rey|mdr\b|long beach|san pedro|22nd street|pierpoint|santa monica|"
    r"malibu|laguna|ventura|oxnard|channel islands|anacapa|santa cruz island|santa rosa island|"
    r"san miguel|santa barbara island|san nicolas|rocky point|point vicente|seal beach)\b", re.I)
SD_WORDS = re.compile(
    r"\b(point loma|pt\.? loma|la jolla|coronado|coronados|9 mile|nine mile|mission bay|"
    r"imperial beach|\bib\b|h&m|fisherman'?s landing|seaforth|oceanside|carlsbad|del mar|"
    r"ensenada|colonet|san quintin|cedros|guadalupe|benitos|alijos|long range)\b", re.I)


@lru_cache(maxsize=1)
def landing_regions() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        js = REGIONS_JS.read_text(encoding="utf-8")
        for var, region in (("SD_LANDINGS", SD), ("OCLA_LANDINGS", OCLA)):
            m = re.search(var + r"\s*=\s*\[(.*?)\]", js, re.S)
            for name in re.findall(r'"([^"]+)"', m.group(1) if m else ""):
                out[name] = region
    except OSError:
        pass
    if not out:
        out = {n: r for r, names in _FALLBACK.items() for n in names}
    return out


def region_for_landing(landing: str | None) -> str | None:
    return landing_regions().get(landing or "")


def region_for_point(lat: float | None, lon: float | None) -> str | None:
    """Where a spot is. North of ~Dana Point / Catalina = OC/LA; the Oceanside to
    Dana Point stretch and San Clemente Island are fished by both fleets."""
    if lat is None or lon is None:
        return None
    if 32.70 <= lat <= 33.10 and -118.70 <= lon <= -118.25:   # San Clemente Island
        return BOTH
    if lat >= 33.35:
        return OCLA
    if lat >= 33.00:
        return BOTH
    return SD


def combine(regions) -> str | None:
    got = set()
    for r in regions:
        if r == BOTH:
            got |= {SD, OCLA}
        elif r:
            got.add(r)
    if got == {SD, OCLA}:
        return BOTH
    return next(iter(got)) if got else None


def region_for_text(text: str | None) -> str | None:
    if not text:
        return None
    o, s = bool(OCLA_WORDS.search(text)), bool(SD_WORDS.search(text))
    return BOTH if (o and s) else OCLA if o else SD if s else None


def item_region(*, landings=(), places=(), title: str | None = None,
                feed_id: str | None = None) -> str | None:
    """Region for one item. `places` are gazetteer dicts (with lat/lon)."""
    ev = [region_for_landing(l) for l in landings]
    ev += [region_for_point(p.get("lat"), p.get("lon")) for p in places if p]
    r = combine(ev)
    if r is None:
        r = region_for_text(title)
    if r is None:
        r = FEED_DEFAULT.get(feed_id or "")
    return r


def in_region(item_region_value: str | None, region: str) -> bool:
    return item_region_value == region or item_region_value == BOTH
