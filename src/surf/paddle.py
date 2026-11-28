"""Paddle mode for Surftracker: stand-up paddling conditions at San Diego spots.

Writes web/api/v1/paddle_spots.json. For each paddle spot, hour by hour:
wind (speed, gust, direction; ECMWF via forecast.wind_hourly, unchanged), tide
(forecast.tides: San Diego Bay 9410170 for bay spots, La Jolla 9410230
elsewhere), NOAA tidal current predictions at the San Diego Bay Entrance
(forecast.currents, PCT0031) for the spots near it, the latest CDIP water
temperature (extras.water_temp), and for open-coast spots the surf at the
matching surf spot (surf.json / surf_spots.json, written earlier in the run).

The paddle rating is a transparent rule of thumb, not a fitted or verified
model: wind (sustained and gusts; offshore wind at an open beach is flagged
because it pushes paddlers out to sea), surf to launch through (coast spots),
predicted tidal current at the bay entrance (Shelter Island, La Playa), and a
falling tide near other harbour or lagoon mouths. Water temperature is comfort
and wetsuit advice on the page, not scored.

Run:  python -m src.surf.paddle
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import cdip as C

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "api" / "v1" / "paddle_spots.json"
SURF = ROOT / "web" / "api" / "v1" / "surf.json"
SURF_SPOTS = ROOT / "web" / "api" / "v1" / "surf_spots.json"

LA_JOLLA, SD_BAY = "9410230", "9410170"
TIDE_NAMES = {LA_JOLLA: "La Jolla", SD_BAY: "San Diego Bay"}

# id, name, lat, lon, kind (bay|harbour|lagoon|coast), tide station, surf spot id (coast), mouth?, note
# Positions: © OpenStreetMap contributors (ODbL), via Nominatim.
PADDLE_SPOTS = [
    ("oceanside-harbor-inside", "Oceanside Harbor (inside)", 33.2078, -117.3950, "harbour", LA_JOLLA, None, True,
     "Paddle inside the breakwater; boat traffic in the channel."),
    ("agua-hedionda", "Agua Hedionda Lagoon", 33.1429, -117.3277, "lagoon", LA_JOLLA, None, True,
     "Outer lagoon by the inlet runs fast on a falling tide; the inner lagoon is calmer."),
    ("carlsbad-paddle", "Carlsbad State Beach", 33.1508, -117.3485, "coast", LA_JOLLA, "carlsbad-state-beach", False, None),
    ("la-jolla-shores-paddle", "La Jolla Shores", 32.8577, -117.2564, "coast", LA_JOLLA, "la-jolla-shores", False,
     "Launch at Kellogg Park; the caves and Cove are a common out-and-back."),
    ("la-jolla-cove-paddle", "La Jolla Cove", 32.8504, -117.2730, "coast", LA_JOLLA, "la-jolla-cove", False,
     "Ecological reserve; stay clear of the cliffs when there is swell."),
    ("crown-point", "Crown Point Shores (Mission Bay)", 32.7853, -117.2320, "bay", SD_BAY, None, False, None),
    ("de-anza-cove", "De Anza Cove (Mission Bay)", 32.7953, -117.2125, "bay", SD_BAY, None, False, None),
    ("fiesta-island", "Fiesta Island (Mission Bay)", 32.7785, -117.2213, "bay", SD_BAY, None, False, None),
    ("bonita-cove", "Bonita Cove (Mission Bay)", 32.7689, -117.2481, "bay", SD_BAY, None, True,
     "Near the Mission Bay entrance channel: outgoing tide and boat wakes."),
    ("shelter-island-paddle", "Shelter Island", 32.7113, -117.2300, "bay", SD_BAY, None, True,
     "Busy boat channel; stay on the shore side."),
    ("la-playa", "La Playa (bay side of Point Loma)", 32.7111, -117.2370, "bay", SD_BAY, None, True,
     "Near the bay entrance: outgoing tide and boat traffic."),
    ("glorietta-bay", "Glorietta Bay (Coronado)", 32.6753, -117.1691, "bay", SD_BAY, None, False, None),
]

# NOAA tidal current predictions, San Diego Bay Entrance: scored where it matters,
# shown as indicative at Glorietta Bay; none exists for Mission Bay.
CURRENT_STATION = "PCT0031"
CURRENT_SCORED = {"shelter-island-paddle", "la-playa"}
CURRENT_SHOWN = CURRENT_SCORED | {"glorietta-bay"}

GOOD, OK, HARD = 2, 1, 0
LEVEL = {GOOD: "Good", OK: "OK", HARD: "Hard"}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _dir(d: float | None) -> str:
    return "" if d is None else COMPASS[round((d % 360) / 22.5) % 16]


def _angdiff(a: float, b: float) -> float:
    return (a - b + 540) % 360 - 180


def current_at(events: list[dict], ep: int) -> dict | None:
    """Predicted current at an hour, eased between NOAA max/slack events.
    {"kt", "type": flood|ebb|slack, "towardDeg"}; None outside the events."""
    ev = sorted(((datetime.fromisoformat(e["t"]).timestamp(), e) for e in events), key=lambda x: x[0])
    signed = lambda e: e["kt"] if e["type"] == "flood" else -e["kt"] if e["type"] == "ebb" else 0.0
    for (t0, e0), (t1, e1) in zip(ev, ev[1:]):
        if t0 <= ep <= t1:
            f = (ep - t0) / max(1.0, t1 - t0)
            v = signed(e0) + (signed(e1) - signed(e0)) * (1 - math.cos(math.pi * f)) / 2
            kind = "slack" if abs(v) < 0.2 else "flood" if v > 0 else "ebb"
            src = next((e for e in (e1, e0) if e["type"] == kind), None)
            return {"kt": round(abs(v), 1), "type": kind, "towardDeg": src.get("towardDeg") if src else None}
    return None


# ── the rule of thumb ────────────────────────────────────────────────────
def rate_hour(kind: str, wind: tuple | None, tide_ft: float | None, tide_next: float | None,
              surf: dict | None, normal: float | None, mouth: bool, current: dict | None = None) -> dict:
    """One hour's paddle rating: {"level": 0-2 | None, "label", "reason"}."""
    if not wind or wind[0] is None or wind[1] is None:
        return {"level": None, "label": None, "reason": "No wind forecast for this hour."}
    kt, wfrom, gust = wind
    eff = max(kt, 0.7 * gust) if gust is not None else kt
    coast = kind == "coast"
    good_max, ok_max = (6, 11) if coast else (8, 13)
    wl = GOOD if eff <= good_max else OK if eff <= ok_max else HARD
    gtxt = f", gusts {round(gust)}" if gust is not None and gust >= kt + 4 else ""
    wtxt = f"{_dir(wfrom)} {round(kt)} kt{gtxt}"
    issues = []   # (level, text)
    if coast and normal is not None:
        offshore = abs(_angdiff(wfrom, normal + 180)) <= 60
        onshore = abs(_angdiff(wfrom, normal)) <= 60
        if offshore and eff > 8:
            wl = HARD
            issues.append((HARD, f"{wtxt} offshore: it can push you out to sea"))
        elif wl < GOOD:
            issues.append((wl, f"{wtxt} {'onshore, choppy' if onshore else 'cross-shore, choppy'}"))
    elif wl < GOOD:
        issues.append((wl, f"{wtxt}, {'choppy' if wl == OK else 'rough, hard going'}"))
    level = wl
    if coast and surf and surf.get("faceFt"):
        hi = surf["faceFt"][1]
        sl = GOOD if hi <= 2 else OK if hi <= 3 else HARD
        if sl < GOOD:
            issues.append((sl, f"{surf['faceFt'][0]}–{hi} ft surf to launch through"))
        level = min(level, sl)
    if current is not None:
        kt = current["kt"]
        if current["type"] == "ebb" and kt >= 2.0:
            level = HARD
            issues.append((HARD, f"ebb current about {kt} kt"))
        elif (current["type"] == "ebb" and kt >= 1.0) or (current["type"] == "flood" and kt >= 1.5):
            level = min(level, OK)
            issues.append((OK, f"{current['type']} current about {kt} kt"))
    elif mouth and tide_ft is not None and tide_next is not None and tide_next - tide_ft <= -0.6:
        level = min(level, OK)   # an ebb alone makes it harder going, not "Hard"
        issues.append((OK, "strong outgoing tide near the mouth"))
    if issues:
        issues.sort(key=lambda x: x[0])
        reason = "; ".join(t for _, t in issues)
    else:
        calm = "flat water" if not coast else "small surf" if surf else "light conditions"
        reason = f"Light wind ({wtxt}), {calm}"
    return {"level": level, "label": LEVEL[level], "reason": reason[0].upper() + reason[1:] + "."}


def best_windows(hours: list[dict], sun: list[dict]) -> list[dict]:
    """Per local day (sun entries): the longest daylight run at that day's best level."""
    out = []
    for d in sun:
        a, b = d.get("sunrise"), d.get("sunset")
        if not a or not b:
            continue
        lo, hi = datetime.fromisoformat(a), datetime.fromisoformat(b)
        day = [h for h in hours if h.get("level") is not None and lo <= datetime.fromisoformat(h["t"]) <= hi]
        if not day:
            continue
        top = max(h["level"] for h in day)
        runs, cur = [], []
        for h in day:
            if h["level"] == top:
                cur.append(h)
            elif cur:
                runs.append(cur); cur = []
        if cur:
            runs.append(cur)
        run = max(runs, key=len)
        end = datetime.fromisoformat(run[-1]["t"]) + timedelta(hours=1)
        w = {"date": d["date"], "from": run[0]["t"], "to": C.to_iso(min(end, hi).timestamp()),
             "level": top, "label": LEVEL[top], "reason": run[0]["reason"]}
        later = [h for h in day if datetime.fromisoformat(h["t"]) > end]
        if later and min(h["level"] for h in later) < top:
            w["worseAfter"] = run[-1]["t"]
        out.append(w)
    return out


def _surf_refs() -> dict[str, dict]:
    refs = {}
    for path, key in ((SURF, "breaks"), (SURF_SPOTS, "spots")):
        try:
            for b in json.loads(path.read_text(encoding="utf-8")).get(key, []):
                refs[b["id"]] = b
        except (OSError, ValueError) as e:
            log.warning("paddle: could not read %s: %s", path.name, e)
    return refs


def _nearest_surf(ref: dict | None, ep: int) -> dict | None:
    if not ref:
        return None
    best = min(ref["hours"], key=lambda h: abs(datetime.fromisoformat(h["t"]).timestamp() - ep), default=None)
    if best and abs(datetime.fromisoformat(best["t"]).timestamp() - ep) <= 2 * 3600:
        return best
    return None


def build(now: datetime | None = None) -> dict:
    from . import forecast as F
    from .extras import sun_days, water_temp

    now = now or datetime.now(timezone.utc)
    cfgs = [{"id": s[0], "name": s[1], "lat": s[2], "lon": s[3]} for s in PADDLE_SPOTS]
    try:
        winds = F.wind_hourly(cfgs)
    except Exception as e:  # noqa: BLE001
        log.warning("paddle wind failed: %s", e)
        winds = [{} for _ in cfgs]
    winds, wind_note = F.with_wind_fallback(cfgs, winds, OUT, key="spots")
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    tides = {}
    for st in (LA_JOLLA, SD_BAY):
        try:
            tides[st] = F.tides(start, station=st)
        except Exception as e:  # noqa: BLE001
            log.warning("paddle tides %s failed: %s", st, e)
            tides[st] = ({}, [])
    try:
        cur_events = F.currents(start, station=CURRENT_STATION)
    except Exception as e:  # noqa: BLE001
        log.warning("paddle currents failed: %s", e)
        cur_events = []
    try:
        wt = water_temp(now)
    except Exception as e:  # noqa: BLE001
        log.warning("paddle water temp failed: %s", e)
        wt = None
    refs = _surf_refs()
    sun = sun_days(now - timedelta(days=1))
    t0 = int(now.replace(minute=0, second=0, microsecond=0).timestamp()) - 3600
    t1 = t0 + 7 * 24 * 3600
    spots = []
    for (sid, name, lat, lon, kind, st, ref_id, mouth, note), w in zip(PADDLE_SPOTS, winds):
        ref = refs.get(ref_id) if ref_id else None
        normal = ref.get("shoreNormal") if ref else None
        th = tides[st][0]
        hours = []
        for ep in range(t0, t1, 3600):
            wind = w.get(ep)
            surf = _nearest_surf(ref, ep)
            cur = current_at(cur_events, ep) if sid in CURRENT_SHOWN else None
            r = rate_hour(kind, wind, th.get(ep), th.get(ep + 3600), surf, normal, mouth,
                          cur if sid in CURRENT_SCORED else None)
            h = {"t": C.to_iso(ep), "windKt": round(wind[0]) if wind else None,
                 "windFrom": round(wind[1]) if wind else None,
                 "windGustKt": round(wind[2]) if wind and wind[2] is not None else None,
                 "tideFt": round(th[ep], 2) if ep in th else None, **r}
            if cur:
                h["current"] = cur
            if surf:
                h.update(faceFt=surf["faceFt"], hsM=surf.get("hsM"), tpS=surf.get("tpS"), dpDeg=surf.get("dpDeg"))
            hours.append(h)
        spot = {"id": sid, "name": name, "lat": lat, "lon": lon, "kind": kind, "mouth": mouth,
                "tideStation": st, "surfRef": ref_id if ref else None, "shoreNormal": normal,
                "currentStation": CURRENT_STATION if sid in CURRENT_SHOWN else None,
                "currentScored": sid in CURRENT_SCORED,
                "hours": hours, "best": best_windows(hours, sun)}
        if note:
            spot["note"] = note
        spots.append(spot)
    return {
        "generatedAt": now.isoformat(timespec="minutes"), "staleAfterHours": 30, "label": "Rule of thumb",
        "windNote": wind_note, "waterTemp": wt,
        "sources": "Wind: ECMWF via Open-Meteo. Tides and currents: NOAA CO-OPS predictions. Water: CDIP. "
                   "Surf: Surftracker model. Spot positions: © OpenStreetMap contributors.",
        "currentStationName": "San Diego Bay Entrance",
        "tides": {st: {"name": TIDE_NAMES[st], "hourly": [[C.to_iso(t), round(v, 2)] for t, v in sorted(tides[st][0].items())],
                       "hilo": tides[st][1]} for st in tides},
        "sun": sun,
        "spots": spots,
    }


def write(path: Path = OUT) -> int:
    data = build()
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(data["spots"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        n = write()
        log.info("paddle_spots.json: %d spots", n)
    except Exception as e:  # noqa: BLE001
        log.warning("paddle build failed: %s", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
