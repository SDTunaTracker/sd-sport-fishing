"""Race-day conditions for upcoming paddle races -> web/api/v1/paddle_race_forecast.json.

For each race in paddle_races.json dated within the wind forecast range
(~7 days), and each distance with a course file, every leg is scored at the
time paddlers are expected on it: start time + distance to the middle of the
leg at a typical prone pace (race or distance `paceMph`, default 4.5 mph).
See score.py for the rule. If the race has `startFlexible`, every start from
06:00 to 14:00 (30 min steps) is scored and the best window is reported.

Inputs, all through src/surf (imported, not copied):
  wind     ECMWF IFS 0.25° hourly via Open-Meteo (forecast.wind_hourly), at each leg's midpoint
  current  NOAA CO-OPS current predictions (forecast.currents), e.g. PCT0031 Bay Entrance
  swell    CDIP MOP ECMWF-forced nearshore Hs/Tp/Dp at the MOP point nearest each ocean leg
  water    CDIP buoy SST (extras.water_temp), San Diego County races only

Run:  python -m src.paddle.forecast
      python -m src.paddle.forecast --as-if the-loop-2025=2026-11-29   (local preview only)
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..surf import forecast as SF
from ..surf.extras import water_temp
from ..surf.spots import mop_table, nearest_mop
from . import course as CO
from . import score as S

log = logging.getLogger(__name__)

OUT = CO.ROOT / "web" / "api" / "v1" / "paddle_race_forecast.json"
TZ = ZoneInfo("America/Los_Angeles")
HORIZON_DAYS = 7          # forecast.wind_hourly fetches 7 days
DEFAULT_START = "08:00"
DEFAULT_PACE = 4.5
FLEX_FROM, FLEX_TO, FLEX_STEP = 6.0, 14.0, 0.5
FT = 3.281


SST_NEAR_KM = 80          # the SST buoys (CDIP 201 Scripps, 220 Mission Bay) speak for San Diego County only
SST_AT = (32.93, -117.27)


def near_sst_buoy(race: dict) -> bool:
    loc = race.get("location") or {}
    if loc.get("lat") is None or loc.get("lon") is None:
        return False
    return CO.distance_mi(loc["lat"], loc["lon"], *SST_AT) * 1.609 <= SST_NEAR_KM


# ── time helpers ────────────────────────────────────────────────────────────

def start_utc(day: str, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(date.fromisoformat(day), time(h, m), TZ).astimezone(timezone.utc)


def nearest_hour(series: dict[int, tuple], t: datetime, max_gap_h: float = 1.5):
    if not series:
        return None
    ep = int(t.timestamp())
    k = min(series, key=lambda e: abs(e - ep))
    return series[k] if abs(k - ep) <= max_gap_h * 3600 else None


def current_at(events: list[dict], t: datetime) -> tuple[float, float] | None:
    """(speed kt >= 0, toward deg) at t, from NOAA max/slack events.

    Signed speed (flood +, ebb −) is cosine-interpolated between consecutive
    events; the direction is the flood or ebb direction of the nearest such event.
    """
    if not events:
        return None
    ev = sorted(({**e, "dt": datetime.fromisoformat(e["t"])} for e in events), key=lambda e: e["dt"])
    signed = lambda e: e["kt"] if e["type"] == "flood" else -e["kt"] if e["type"] == "ebb" else 0.0
    for a, b in zip(ev, ev[1:]):
        if a["dt"] <= t <= b["dt"]:
            f = (t - a["dt"]).total_seconds() / max(1.0, (b["dt"] - a["dt"]).total_seconds())
            v = signed(a) + (signed(b) - signed(a)) * (1 - math.cos(math.pi * f)) / 2
            kind = "flood" if v > 0 else "ebb"
            same = [e for e in ev if e["type"] == kind and e.get("towardDeg") is not None]
            if not same or abs(v) < 1e-6:
                return 0.0, 0.0
            near = min(same, key=lambda e: abs((e["dt"] - t).total_seconds()))
            return abs(v), float(near["towardDeg"])
    return None


# ── one course, one start ───────────────────────────────────────────────────

def score_course(legs: list[dict], t0: datetime, pace: float, wind: list[dict], swell: list,
                 currents: dict[str, list[dict]], water_f: float | None) -> dict:
    out = []
    for l, w, sw in zip(legs, wind, swell):
        eta = t0 + timedelta(hours=(l["startMi"] + l["miles"] / 2) / pace)
        wv = nearest_hour(w, eta)
        sv = nearest_hour(sw, eta, 3.1) if sw else None
        swell_ft = None
        if sv:
            swell_ft = sv[0] * FT
            sv = (swell_ft, sv[1], sv[2])
        cur_kt = None
        if l.get("current"):
            c = current_at(currents.get(l["current"], []), eta)
            if c:
                cur_kt = c[0] * l["currentFactor"] * math.cos(math.radians(S.angdiff(c[1], l["bearing"])))
        sc = S.leg_score(None if wv is None else (wv[0], wv[2], wv[1]), l["bearing"], l["water"] == "ocean",
                         sv, cur_kt)
        out.append({
            "i": l["i"], "leg": l["leg"], "from": l["from"], "to": l["to"], "water": l["water"],
            "bearing": l["bearing"], "miles": l["miles"],
            "eta": eta.isoformat(timespec="minutes"),
            "windKt": None if wv is None else round(wv[0], 1),
            "windFrom": None if wv is None else round(wv[1]),
            "gustKt": None if wv is None or wv[2] is None else round(wv[2], 1),
            "swellFt": None if swell_ft is None else round(swell_ft, 1),
            "swellS": None if not sv else round(sv[1], 1),
            "swellFrom": None if not sv else round(sv[2]),
            "currentKt": None if cur_kt is None else round(cur_kt, 2),
            **sc,
        })
    return {"legs": out, **S.overall(out, water_f)}


def best_start(legs, day, pace, wind, swell, currents, water_f) -> dict | None:
    tries = []
    h = FLEX_FROM
    while h <= FLEX_TO + 1e-9:
        hhmm = f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"
        r = score_course(legs, start_utc(day, hhmm), pace, wind, swell, currents, water_f)
        if r["score"] is not None and all(l["score"] is not None for l in r["legs"]):
            tries.append((hhmm, r["score"]))
        h += FLEX_STEP
    if not tries:
        return None
    top = max(s for _, s in tries)
    i = next(n for n, (_, s) in enumerate(tries) if s == top)
    a = b = i
    while a > 0 and tries[a - 1][1] >= top - 0.25:
        a -= 1
    while b < len(tries) - 1 and tries[b + 1][1] >= top - 0.25:
        b += 1
    return {"from": tries[a][0], "to": tries[b][0], "best": tries[i][0], "score": top, "label": S.label(top),
            "byStart": [{"start": t, "score": s} for t, s in tries]}


# ── build ───────────────────────────────────────────────────────────────────

def upcoming(races: list[dict], today: date, as_if: dict[str, str]) -> list[tuple[dict, str, bool]]:
    out = []
    for r in races:
        day, preview = r.get("date"), False
        if r["id"] in as_if:
            day, preview = as_if[r["id"]], True
        if not day:
            continue
        d = date.fromisoformat(day)
        if today <= d <= today + timedelta(days=HORIZON_DAYS):
            out.append((r, day, preview))
    return out


def build(now: datetime | None = None, as_if: dict[str, str] | None = None,
          races_path: Path = CO.RACES, courses: Path = CO.COURSES) -> dict:
    now = now or datetime.now(timezone.utc)
    doc = json.loads(races_path.read_text(encoding="utf-8"))
    defaults = doc.get("defaults") or {}
    today = now.astimezone(TZ).date()
    todo = []   # (race, distance, day, preview, legs)
    for race, day, preview in upcoming(doc.get("races", []), today, as_if or {}):
        for dist in race.get("distances", []):
            if not dist.get("courseId"):
                continue
            try:
                legs = CO.legs(CO.load(dist["courseId"], courses))
            except Exception as e:  # noqa: BLE001
                log.warning("course %s: %s", dist["courseId"], e)
                continue
            todo.append((race, dist, day, preview, legs))
    payload = {"generatedAt": now.isoformat(timespec="minutes"), "horizonDays": HORIZON_DAYS,
               "sources": {"wind": "ECMWF IFS 0.25° via Open-Meteo", "current": "NOAA CO-OPS predictions",
                           "swell": "CDIP MOP (ECMWF-forced), nearshore", "water": "CDIP buoy SST"},
               "races": {}}
    if not todo:
        return payload

    # wind at every leg midpoint, one request
    pts = [{"lat": l["midLat"], "lon": l["midLon"]} for *_, legs in todo for l in legs]
    try:
        flat = SF.wind_hourly(pts)
    except Exception as e:  # noqa: BLE001
        log.warning("paddle wind failed: %s", e)
        flat = [{} for _ in pts]
    winds, k = [], 0
    for *_, legs in todo:
        winds.append(flat[k:k + len(legs)])
        k += len(legs)

    # swell at the nearest MOP point for ocean legs (cached per point)
    table, mop_cache, swells = mop_table(), {}, []
    for *_, legs in todo:
        row = []
        for l in legs:
            if l["water"] != "ocean":
                row.append(None)
                continue
            p, km = nearest_mop(l["midLat"], l["midLon"], table)
            if km > 5:
                row.append(None)
                continue
            if p["id"] not in mop_cache:
                try:
                    mop_cache[p["id"]] = SF.mop_series(p["id"], "ecmwf_fc", now - timedelta(hours=6))
                except Exception as e:  # noqa: BLE001
                    log.warning("MOP %s failed: %s", p["id"], e)
                    mop_cache[p["id"]] = {}
            row.append(mop_cache[p["id"]])
        swells.append(row)

    stations = {l["current"] for *_, legs in todo for l in legs if l.get("current")}
    currents = {}
    for st in stations:
        try:
            currents[st] = SF.currents(now - timedelta(days=1), days=HORIZON_DAYS + 2, station=st)
        except Exception as e:  # noqa: BLE001
            log.warning("current %s failed: %s", st, e)
    wt = None
    if any(near_sst_buoy(race) for race, *_ in todo):
        try:
            wt = water_temp(now)
        except Exception as e:  # noqa: BLE001
            log.warning("water temp failed: %s", e)
    payload["waterTemp"] = wt

    for (race, dist, day, preview, legs), wind, swell in zip(todo, winds, swells):
        pace = float(dist.get("paceMph") or race.get("paceMph") or defaults.get("paceMph") or DEFAULT_PACE)
        hhmm = dist.get("startLocal") or race.get("startLocal")
        water_f = wt["f"] if wt and near_sst_buoy(race) else None
        r = score_course(legs, start_utc(day, hhmm or DEFAULT_START), pace, wind, swell, currents, water_f)
        entry = {"date": day, "start": hhmm or DEFAULT_START, "startAssumed": not hhmm, "paceMph": pace,
                 "preview": preview, "waterF": water_f, **r}
        if race.get("startFlexible"):
            entry["bestStart"] = best_start(legs, day, pace, wind, swell, currents, water_f)
        payload["races"].setdefault(race["id"], {})[dist["id"]] = entry
    return payload


def write(path: Path = OUT, **kw) -> int:
    payload = build(**kw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return sum(len(v) for v in payload["races"].values())


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as-if", action="append", default=[], metavar="RACE=YYYY-MM-DD",
                    help="score a race as if it were on this date (local preview; never commit the output)")
    a = ap.parse_args(argv)
    as_if = dict(x.split("=", 1) for x in a.as_if)
    n = write(as_if=as_if)
    print(f"paddle_race_forecast.json: {n} race course(s) in range")
    return 0


if __name__ == "__main__":
    sys.exit(main())
