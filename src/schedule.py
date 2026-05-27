"""Open-party schedule scrapers for the 4 SD landings.

Three of the four landings (Fisherman's, Point Loma, Seaforth) publish their
schedules through fishingreservations.net with identical HTML structure
(.scale-break date dividers + .trip-depart / .trip-return / .trip-load /
.trip-price / .trip-spots cells). H&M Landing serves its data as a JSONP
endpoint at /xolacache backed by Xola.

Trips that are sold out (open_spots == 0) and trips shorter than 3/4 day are
filtered out at ingest, matching the fish-count side.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Literal

import requests
from bs4 import BeautifulSoup

from . import parse as P

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")


@dataclass(frozen=True)
class ScheduleSource:
    name: str
    url: str
    kind: Literal["fishingreservations", "xola_jsonp"]
    referer: str | None = None


SOURCES: tuple[ScheduleSource, ...] = (
    ScheduleSource(
        name="H&M Landing",
        url="https://www.hmlanding.com/xolacache",
        kind="xola_jsonp",
        referer="https://www.hmlanding.com/trips/",
    ),
    ScheduleSource(
        name="Fisherman's Landing",
        url="https://www.fishermanslanding.com/openparty.php",
        kind="fishingreservations",
    ),
    ScheduleSource(
        name="Point Loma Sportfishing",
        url="https://pointloma.fishingreservations.net/sales",
        kind="fishingreservations",
    ),
    ScheduleSource(
        name="Seaforth Sportfishing",
        url="https://seaforth.fishingreservations.net/sales",
        kind="fishingreservations",
    ),
)


def _fetch(src: ScheduleSource, *, params: dict | None = None, timeout: float = 30.0) -> str:
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if src.referer:
        headers["Referer"] = src.referer
    r = requests.get(src.url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    return r.text


# --- fishingreservations.net parser (used by FL, PL, SF) ----------------

# Departure / return shown as "Fri. 5-22-26 10:00 AM" or "5-22-2026 5:30 AM".
_DT_RE = re.compile(
    r"(?:(?:Sun|Mon|Tue|Wed|Thu|Fri|Sat)\.?\s+)?"
    r"(\d{1,2})-(\d{1,2})-(\d{2,4})\s+"
    r"(\d{1,2}):(\d{2})\s*(AM|PM)",
    re.I,
)


def _parse_datetime(text: str) -> datetime | None:
    m = _DT_RE.search(text or "")
    if not m:
        return None
    month, day, year, hh, mm, ampm = m.groups()
    yr = int(year)
    if yr < 100:
        yr += 2000
    hh = int(hh) % 12
    if ampm.upper() == "PM":
        hh += 12
    return datetime(yr, int(month), int(day), hh, int(mm))


_MEALS_RE = re.compile(
    r'meals?\s+included|meal\s+plan|galley\s+included|food\s+included',
    re.I,
)

_MEAL_VALUES: dict[str, int] = {
    'Overnight':  40,
    '1.5 Day':    65,
    '2 Day':      100,
    '2.5 Day':    130,
    '3 Day':      160,
    '4 Day':      210,
    '5 Day':      260,
    '6 Day':      310,
    '7 Day':      360,
    'Full Day':   0,
    '3/4 Day':    0,
}


def _detect_meals(
    note: str | None,
    whats_included: str | None,
    trip_length: str,
    price: float | None,
) -> tuple[int, int, float | None]:
    """Return (meals_included, meals_value, effective_price)."""
    combined = f"{note or ''} {whats_included or ''}".strip()
    if _MEALS_RE.search(combined):
        val = _MEAL_VALUES.get(trip_length, 0)
        eff = (price - val) if price is not None else None
        return 1, val, eff
    return 0, 0, price


_STATUS_RE = re.compile(
    r'DEFINITE\s+GO|DEF(?:INITE)?\.?\s+GO|WILL\s+RUN\s+WITH\s+\d+|GOING\s+FOR\s+SURE|CANCEL(?:LED|ED)',
    re.I,
)
_TARGET_RE = re.compile(r'[Tt]argeting\s+([^.!]{3,80})', re.I)
_INCLUDED_RE = re.compile(r'[Pp]rice\s+includes?\s+([^.!]{3,120})', re.I)


def _parse_trip_status(text: str) -> str | None:
    if not text:
        return None
    m = _STATUS_RE.search(text)
    if not m:
        return None
    t = m.group(0).upper()
    if re.search(r'CANCEL', t):
        return 'Cancelled'
    return 'Definite Go'


def _parse_target_species(text: str) -> str | None:
    m = _TARGET_RE.search(text or '')
    if not m:
        return None
    return m.group(1).strip().rstrip('.,;').strip()


def _parse_whats_included(text: str) -> str | None:
    m = _INCLUDED_RE.search(text or '')
    if not m:
        return None
    return m.group(1).strip().rstrip('.,;').strip()


def _parse_money(text: str) -> float | None:
    m = re.search(r"\$([\d,]+\.?\d*)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def _parse_int_or_none(text: str) -> int | None:
    if not text:
        return None
    if re.search(r"full|sold\s*out", text, re.I):
        return 0
    m = re.search(r"(\d[\d,]*)", text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_fishingreservations(html: str, landing: str, source_url: str) -> list[dict]:
    """Parse the schedule layout shared by FL/PL/SF.

    Trip data is split across two structural patterns:
      - Point Loma: <td class="trip-name"><strong>Boat</strong><br>Length</td>
                    + sibling <td> holding the depart/return/price divs.
      - Seaforth & FL: <div class="trip-info"><strong>Boat</strong><br>Length</div>
                       inside the same td as the depart/return/price divs.

    Both anchor each trip with `data-trip-id` on a td or a /user.php?trip_id link.
    Rowspan duplicates each trip-id across 2-3 rows, so we dedupe by trip-id.
    """
    soup = BeautifulSoup(html, "lxml")
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out: list[dict] = []
    seen: set[str] = set()

    # Pre-pass: collect trip-comments text keyed by trip_id.
    # The comments row shares the same data-trip-id as the main trip row,
    # so we scan all td[data-trip-id] for a .trip-comments child.
    comments_by_id: dict[str, str] = {}
    for td in soup.find_all("td", attrs={"data-trip-id": True}):
        c = td.find("div", class_=re.compile(r"\btrip-comments\b"))
        if c:
            txt = " ".join(c.get_text(" ", strip=True).split())
            if txt:
                comments_by_id[td["data-trip-id"]] = txt

    # Walk every row; first occurrence of each trip-id wins.
    for tr in soup.find_all("tr"):
        # Find the trip ID — from data-trip-id on a td, or from a trip_id= anchor.
        trip_id = None
        td_with_id = tr.find("td", attrs={"data-trip-id": True})
        if td_with_id:
            trip_id = td_with_id.get("data-trip-id")
        if not trip_id:
            a = tr.find("a", href=re.compile(r"trip_id=(\d+)"))
            if a:
                m = re.search(r"trip_id=(\d+)", a["href"])
                trip_id = m.group(1) if m else None
        if not trip_id or trip_id in seen:
            continue

        # Boat + trip type live in a container that has a <strong> + trailing text.
        # On PL it's <td class="trip-name">; on SF/FL it's <div class="trip-info">.
        info_node = (
            tr.find("td", class_=re.compile(r"\btrip-name\b"))
            or tr.find("div", class_=re.compile(r"\btrip-info\b"))
        )
        if not info_node:
            continue
        boat_tag = info_node.find("strong")
        if not boat_tag:
            continue
        boat = boat_tag.get_text(strip=True)
        # Trip type = info_node text minus the boat name, normalised.
        info_text = info_node.get_text(" ", strip=True)
        trip_type_raw = re.sub(r"\s+", " ", info_text.replace(boat, "", 1)).strip()
        if not boat or not trip_type_raw:
            continue

        def find_div(cls: str) -> str:
            d = tr.find("div", class_=re.compile(rf"\b{cls}\b"))
            return d.get_text(" ", strip=True) if d else ""

        depart_txt = find_div("trip-depart")
        return_txt = find_div("trip-return")
        load_txt = find_div("trip-load")
        price_txt = find_div("trip-price")
        spots_txt = find_div("trip-spots")

        depart_at = _parse_datetime(depart_txt)
        return_at = _parse_datetime(return_txt)
        if depart_at is None:
            continue

        length_bucket, length_days = P.parse_trip_length(trip_type_raw)
        if length_bucket is None or length_days is None or length_days < P.MIN_TRIP_DAYS:
            seen.add(trip_id)  # mark seen so dupe rows don't re-attempt
            continue

        open_spots = _parse_int_or_none(spots_txt)
        if open_spots is None or open_spots <= 0:
            seen.add(trip_id)
            continue

        seen.add(trip_id)
        raw_note      = comments_by_id.get(str(trip_id), "")
        price         = _parse_money(price_txt)
        whats_inc     = _parse_whats_included(raw_note)
        meals_inc, meals_val, eff_price = _detect_meals(raw_note, whats_inc, length_bucket, price)
        out.append({
            "landing": landing,
            "boat": boat,
            "trip_type_raw": trip_type_raw,
            "trip_length": length_bucket,
            "trip_length_days": length_days,
            "departure_at": depart_at.isoformat(),
            "return_at": return_at.isoformat() if return_at else None,
            "price": price,
            "capacity": _parse_int_or_none(load_txt),
            "open_spots": open_spots,
            "reserved_spots": None,
            "note": raw_note or None,
            "trip_status": _parse_trip_status(raw_note),
            "target_species": _parse_target_species(raw_note),
            "whats_included": whats_inc,
            "meals_included": meals_inc,
            "meals_value": meals_val,
            "effective_price": eff_price,
            "source_id": str(trip_id),
            "source_url": source_url,
            "scraped_at": scraped_at,
        })
    return out


# --- H&M Landing xolacache (JSONP) ---------------------------------------

_JSONP_RE = re.compile(r"^[^{]*?(\{.*\})\s*\)\s*;?\s*$", re.S)


def _strip_jsonp(text: str) -> dict:
    m = _JSONP_RE.search(text.strip())
    if not m:
        raise ValueError("xolacache: could not extract JSON from JSONP wrapper")
    return json.loads(m.group(1))


# Experience names are "<Boat> - <Trip Length> - <Description>" or
# "<Boat> - <Trip Length>". We split on " - " and look at the first two.
def _split_experience_name(name: str) -> tuple[str | None, str | None]:
    if not name:
        return None, None
    parts = [p.strip() for p in re.split(r"\s+-\s+", name) if p.strip()]
    if not parts:
        return None, None
    boat = parts[0]
    trip_type = parts[1] if len(parts) > 1 else ""
    return boat, trip_type


def parse_xola_jsonp(text: str, landing: str, source_url: str) -> list[dict]:
    data = _strip_jsonp(text)
    trips = data.get("trips") or []
    exps = data.get("experiences") or {}
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = date.today()
    out: list[dict] = []

    for t in trips:
        exp_id = t.get("expId")
        exp = exps.get(exp_id) or {}
        boat, trip_type_raw = _split_experience_name(exp.get("name", ""))
        if not boat or not trip_type_raw:
            continue
        length_bucket, length_days = P.parse_trip_length(trip_type_raw)
        if length_bucket is None or length_days is None or length_days < P.MIN_TRIP_DAYS:
            continue
        open_spots = t.get("open_spots")
        if open_spots is None or open_spots <= 0:
            continue
        # Trip date — Xola gives ISO 8601 with TZ; parse into datetime.
        dt_str = t.get("datetime") or t.get("date")
        try:
            dep = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except Exception:
            log.warning("bad datetime in xolacache: %r", dt_str)
            continue
        if dep.date() < today:
            continue  # past trip; H&M's endpoint returns 12 months of history+future
        return_at = (dep + timedelta(days=length_days)).isoformat() if length_days else None
        # exp.catalog.items can carry max-load info; not always reliable, so leave null.
        raw_note  = t.get("note") or ""
        price     = float(t["price"]) if t.get("price") is not None else None
        whats_inc = _parse_whats_included(raw_note)
        meals_inc, meals_val, eff_price = _detect_meals(raw_note, whats_inc, length_bucket, price)
        out.append({
            "landing": landing,
            "boat": boat,
            "trip_type_raw": trip_type_raw,
            "trip_length": length_bucket,
            "trip_length_days": length_days,
            "departure_at": dep.isoformat(),
            "return_at": return_at,
            "price": price,
            "capacity": None,
            "open_spots": int(open_spots),
            "reserved_spots": int(t["reserved_spots"]) if t.get("reserved_spots") is not None else None,
            "note": raw_note or None,
            "trip_status": _parse_trip_status(raw_note),
            "target_species": _parse_target_species(raw_note),
            "whats_included": whats_inc,
            "meals_included": meals_inc,
            "meals_value": meals_val,
            "effective_price": eff_price,
            "source_id": str(exp_id) + "@" + dep.isoformat(),
            "source_url": source_url,
            "scraped_at": scraped_at,
        })
    return out


# --- Orchestration -------------------------------------------------------

def scrape_schedule(src: ScheduleSource) -> list[dict]:
    if src.kind == "xola_jsonp":
        body = _fetch(src, params={"callback": "cb", "nocache": "1"})
        return parse_xola_jsonp(body, src.name, src.url)
    elif src.kind == "fishingreservations":
        html = _fetch(src)
        return parse_fishingreservations(html, src.name, src.url)
    else:
        raise ValueError(f"unknown schedule kind: {src.kind}")


def scrape_all_schedules() -> list[tuple[ScheduleSource, list[dict], str | None]]:
    results = []
    for src in SOURCES:
        try:
            trips = scrape_schedule(src)
            results.append((src, trips, None))
        except Exception as e:
            log.exception("schedule scrape failed: %s", src.name)
            results.append((src, [], f"{type(e).__name__}: {e}"))
    return results
