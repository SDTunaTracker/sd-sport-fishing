"""NWS San Diego surf commentary for Surftracker (public domain, shown verbatim).

1. Forecaster notes: the .BEACHES section of the latest SGX Area Forecast
   Discussion (AFD), about 6 issuances a day. Heights in it are breaking surf.
2. Surf alerts: active Beach Hazards Statement, High Surf Advisory/Warning,
   Rip Current Statement and Coastal Flood products for the San Diego County
   coastal zone.

NWS text is public domain ("Source: National Weather Service San Diego").
We quote it as issued, never edit it, and don't use the NWS logo.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

from . import cdip as C

API = "https://api.weather.gov"
AFD_PAGE = "https://forecast.weather.gov/product.php?site=SGX&issuedby=SGX&product=AFD"
SOURCE = "National Weather Service San Diego"
COAST_ZONES = ("CAZ043",)                    # San Diego County Coastal Areas
SURF_EVENTS = {                              # event -> level (sort order and colour)
    "High Surf Warning": "warning", "Coastal Flood Warning": "warning",
    "High Surf Advisory": "advisory", "Coastal Flood Advisory": "advisory",
    "Coastal Flood Watch": "watch",
    "Beach Hazards Statement": "statement", "Rip Current Statement": "statement",
    "Coastal Flood Statement": "statement",
}
LEVEL_ORDER = {"warning": 0, "advisory": 1, "watch": 2, "statement": 3}
_HEADER = re.compile(r"^\.([A-Z][A-Z0-9 /&-]*?)\.\.\.", re.M)


def _get(url: str, params: dict | None = None, accept: str = "application/geo+json") -> dict:
    last = None
    for _ in range(3):
        try:
            r = requests.get(url, params=params, timeout=30,
                             headers={"User-Agent": C.UA, "Accept": accept})
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def afd_section(text: str, name: str = "BEACHES") -> list[str] | None:
    """Paragraphs of one AFD section (e.g. '.BEACHES...'), hard line wraps joined.

    The section runs to the next '&&' line or the next '.NAME...' header,
    whichever comes first, so section order doesn't matter. None if absent.
    """
    if not text:
        return None
    m = re.search(rf"^\.{re.escape(name)}\.\.\.[ \t]*(.*)$", text, re.M)
    if not m:
        return None
    rest = text[m.start(1):]
    ends = [len(rest)]
    amp = re.search(r"^&&\s*$", rest, re.M)
    if amp:
        ends.append(amp.start())
    nxt = _HEADER.search(rest, 1)
    if nxt:
        ends.append(nxt.start())
    body = rest[:min(ends)]
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body)]
    paras = [p for p in paras if p]
    return paras or None


def forecaster_notes(max_products: int = 6) -> dict | None:
    """Latest AFD that has a .BEACHES section (short updates can omit it)."""
    lst = _get(f"{API}/products/types/AFD/locations/SGX", accept="application/ld+json")
    for item in (lst.get("@graph") or [])[:max_products]:
        p = _get(f"{API}/products/{item['id']}", accept="application/ld+json")
        paras = afd_section(p.get("productText", ""))
        if paras:
            return {"source": SOURCE, "product": "Area Forecast Discussion", "section": "Beaches",
                    "issued": p.get("issuanceTime") or item.get("issuanceTime"),
                    "paragraphs": paras, "url": AFD_PAGE}
    return None


def _reflow(text: str | None) -> str | None:
    """Join NWS hard line wraps; keep blank-line paragraph breaks. Words unchanged."""
    if not text:
        return None
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text.strip())]
    return "\n\n".join(p for p in paras if p) or None


def parse_alerts(geojson: dict, now: datetime | None = None) -> list[dict]:
    """Surf and coastal alerts from an api.weather.gov alerts response, most severe first."""
    now = now or datetime.now(timezone.utc)
    out, seen = [], set()
    for f in geojson.get("features") or []:
        p = f.get("properties") or {}
        ev = p.get("event") or ""
        level = SURF_EVENTS.get(ev)
        if not level or p.get("status", "Actual") != "Actual" or p.get("messageType") == "Cancel":
            continue
        until = p.get("ends") or p.get("expires")
        if until:
            try:
                if datetime.fromisoformat(until) <= now:
                    continue
            except ValueError:
                pass
        key = (ev, until)
        if key in seen:
            continue
        seen.add(key)
        out.append({"event": ev, "level": level, "severity": p.get("severity"),
                    "headline": (p.get("parameters") or {}).get("NWSheadline", [None])[0] or p.get("headline"),
                    "onset": p.get("onset") or p.get("effective"), "until": until,
                    "description": _reflow(p.get("description")) or "",
                    "instruction": _reflow(p.get("instruction")),
                    "area": p.get("areaDesc"), "source": SOURCE})
    out.sort(key=lambda a: (LEVEL_ORDER[a["level"]], a["until"] or ""))
    return out


def surf_alerts(zones=COAST_ZONES) -> list[dict]:
    return parse_alerts(_get(f"{API}/alerts/active", params={"zone": ",".join(zones)}))
