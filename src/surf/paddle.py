"""Paddle mode for Surftracker: stand-up paddling conditions at San Diego spots.

Writes web/api/v1/paddle_spots.json. For each paddle spot, hour by hour:
wind (speed, gust, direction; ECMWF via forecast.wind_hourly, unchanged), tide
(NOAA predictions: San Diego Bay 9410170 for bay spots, La Jolla 9410230
elsewhere), and for open-coast spots the surf at the matching surf spot
(read from surf.json / surf_spots.json, written earlier in the same run).

The paddle rating is a transparent rule of thumb, not a fitted or verified
model: wind (sustained and gusts; offshore wind at an open beach is flagged
because it pushes paddlers out to sea), surf to launch through (coast spots),
and a falling tide near a harbour or lagoon mouth (strong outgoing flow).
No tidal-current data is used yet; water temperature is shown as comfort and
wetsuit advice on the page, not scored.

Run:  python -m src.surf.paddle
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

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
    ("crown-point", "Crown Point Shores (Mission Bay)", 32.7853, -117.2320, "bay", LA_JOLLA, None, False, None),
    ("de-anza-cove", "De Anza Cove (Mission Bay)", 32.7953, -117.2125, "bay", LA_JOLLA, None, False, None),
    ("fiesta-island", "Fiesta Island (Mission Bay)", 32.7785, -117.2213, "bay", LA_JOLLA, None, False, None),
    ("bonita-cove", "Bonita Cove (Mission Bay)", 32.7689, -117.2481, "bay", LA_JOLLA, None, True,
     "Near the Mission Bay entrance channel: outgoing tide and boat wakes."),
    ("shelter-island-paddle", "Shelter Island", 32.7113, -117.2300, "bay", SD_BAY, None, True,
     "Busy boat channel; stay on the shore side."),
    ("la-playa", "La Playa (bay side of Point Loma)", 32.7111, -117.2370, "bay", SD_BAY, None, True,
     "Near the bay entrance: outgoing tide and boat traffic."),
    ("glorietta-bay", "Glorietta Bay (Coronado)", 32.6753, -117.1691, "bay", SD_BAY, None, False, None),
]

GOOD, OK, HARD = 2, 1, 0
LEVEL = {GOOD: "Good", OK: "OK", HARD: "Hard"}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _dir(d: float | None) -> str:
    return "" if d is None else COMPASS[round((d % 360) / 22.5) % 16]


def _angdiff(a: float, b: float) -> float:
    return (a - b + 540) % 360 - 180


def _get_json(url: str, params: dict, attempts: int = 3) -> dict:
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, timeout=40)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def tide_station(station: str, start: datetime, days: int = 7) -> tuple[dict[int, float], list[dict]]:
    """NOAA CO-OPS predictions for one station (forecast.tides() is fixed to La Jolla)."""
    base = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    common = {"product": "predictions", "application": "Tunatracker", "station": station,
              "begin_date": start.strftime("%Y%m%d"), "range": 24 * (days + 1), "datum": "MLLW",
              "time_zone": "gmt", "units": "english", "format": "json"}
    parse = lambda t: datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    hourly = {int(parse(p["t"]).timestamp()): float(p["v"])
              for p in _get_json(base, {**common, "interval": "h"}).get("predictions", [])}
    hilo = [{"t": parse(p["t"]).isoformat(timespec="minutes"), "ft": round(float(p["v"]), 1), "type": p.get("type")}
            for p in _get_json(base, {**common, "interval": "hilo"}).get("predictions", [])]
    return hourly, hilo


# ── the rule of thumb ────────────────────────────────────────────────────
def rate_hour(kind: str, wind: tuple | None, tide_ft: float | None, tide_next: float | None,
              surf: dict | None, normal: float | None, mouth: bool) -> dict:
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
    if mouth and tide_ft is not None and tide_next is not None and tide_next - tide_ft <= -0.6:
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
    from .extras import sun_days

    now = now or datetime.now(timezone.utc)
    cfgs = [{"id": s[0], "name": s[1], "lat": s[2], "lon": s[3]} for s in PADDLE_SPOTS]
    try:
        winds = F.wind_hourly(cfgs)
    except Exception as e:  # noqa: BLE001
        log.warning("paddle wind failed: %s", e)
        winds = [{} for _ in cfgs]
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    tides = {}
    for st in (LA_JOLLA, SD_BAY):
        try:
            tides[st] = tide_station(st, start)
        except Exception as e:  # noqa: BLE001
            log.warning("paddle tides %s failed: %s", st, e)
            tides[st] = ({}, [])
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
            r = rate_hour(kind, wind, th.get(ep), th.get(ep + 3600), surf, normal, mouth)
            h = {"t": C.to_iso(ep), "windKt": round(wind[0]) if wind else None,
                 "windFrom": round(wind[1]) if wind else None,
                 "windGustKt": round(wind[2]) if wind and wind[2] is not None else None,
                 "tideFt": round(th[ep], 2) if ep in th else None, **r}
            if surf:
                h.update(faceFt=surf["faceFt"], hsM=surf.get("hsM"), tpS=surf.get("tpS"), dpDeg=surf.get("dpDeg"))
            hours.append(h)
        spot = {"id": sid, "name": name, "lat": lat, "lon": lon, "kind": kind, "mouth": mouth,
                "tideStation": st, "surfRef": ref_id if ref else None, "shoreNormal": normal,
                "hours": hours, "best": best_windows(hours, sun)}
        if note:
            spot["note"] = note
        spots.append(spot)
    return {
        "generatedAt": now.isoformat(timespec="minutes"), "staleAfterHours": 30, "label": "Rule of thumb",
        "about": "Paddle rating: a rule of thumb from wind and gusts, surf to launch through (open beaches) and a "
                 "falling tide near harbour or lagoon mouths. Not verified against paddler reports. No tidal-current "
                 "data yet.",
        "sources": "Wind: ECMWF via Open-Meteo. Tides: NOAA CO-OPS 9410230 La Jolla, 9410170 San Diego Bay. "
                   "Surf: Surftracker model (CDIP MOP). Spot positions: © OpenStreetMap contributors (ODbL).",
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
