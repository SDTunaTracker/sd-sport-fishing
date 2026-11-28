"""Race-leg conditions score for prone paddleboarding (pure functions, no I/O).

A transparent rule of thumb, not a fitted model. Each leg starts at 3 (Good)
and moves with:
  wind   (vs the leg's direction of travel; gusts count 30% of their excess)
         tailwind (downwind) adds up to +1, side wind and headwind subtract,
         headwind faster than side wind; light wind (< 6 kt, gusts < 12 kt)
         stays at 3.
  swell  (ocean legs only, CDIP MOP nearshore Hs): with you is a small plus
         (bumps to ride), against or across you a minus, big swell a minus.
  current (legs with a NOAA current station): along-course component.
The race call is 0.7 × the distance-weighted mean + 0.3 × the worst leg,
minus a little for cold water.
Scale 0–4: Great ≥ 3.5, Good ≥ 2.5, Fair ≥ 1.5, Poor ≥ 0.5, else Hard.
"""
from __future__ import annotations

import math

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
LEVELS = ((3.5, "Great"), (2.5, "Good"), (1.5, "Fair"), (0.5, "Poor"), (-1e9, "Hard"))
LIGHT_KT = 6.0
LIGHT_GUST_KT = 12.0
REL_WORD = {"tail": "downwind", "head": "headwind", "cross": "side wind", "light": "light wind"}


def compass(d: float | None) -> str:
    return "" if d is None else COMPASS[round((d % 360) / 22.5) % 16]


def angdiff(a: float, b: float) -> float:
    """Signed smallest difference a − b in degrees, −180..180."""
    return (a - b + 540) % 360 - 180


def label(score: float) -> str:
    return next(name for lim, name in LEVELS if score >= lim)


def clamp(x: float, lo: float = 0.0, hi: float = 4.0) -> float:
    return max(lo, min(hi, x))


def effective_wind(kt: float, gust: float | None) -> float:
    return kt + 0.3 * max(0.0, (gust or kt) - kt)


def wind_rel(wind_from: float, bearing: float) -> float:
    """Angle between where the wind blows TO and the paddler's heading (0 = dead downwind)."""
    return abs(angdiff((wind_from + 180) % 360, bearing))


def wind_part(kt: float, gust: float | None, wind_from: float, bearing: float, ocean: bool) -> tuple[float, str]:
    """(score change, relation) for one leg. relation: tail | cross | head | light."""
    w = effective_wind(kt, gust)
    rel = wind_rel(wind_from, bearing)
    if kt < LIGHT_KT and (gust or kt) < LIGHT_GUST_KT:
        return 0.0, "light"
    along = w * math.cos(math.radians(rel))          # + tailwind, − headwind
    across = abs(w * math.sin(math.radians(rel)))
    d = clamp((along - 5) / 8, 0, 1)                  # tailwind: +1 by ~13 kt
    d -= max(0.0, -along - 3) / 4                     # headwind: −1 per 4 kt past 3
    d -= max(0.0, across - 6) / 5                     # side wind: −1 per 5 kt past 6
    if ocean and (gust or 0) >= 25:
        d -= 0.5
    kind = "tail" if rel <= 45 else "head" if rel >= 135 else "cross"
    return d, kind


def swell_part(hs_ft: float | None, tp_s: float | None, dp_from: float | None, bearing: float) -> tuple[float, str | None]:
    """(score change, relation) for an ocean leg. relation: with | against | side | None."""
    if hs_ft is None or dp_from is None:
        return 0.0, None
    rel = abs(angdiff((dp_from + 180) % 360, bearing))
    kind = "with" if rel <= 50 else "against" if rel >= 130 else "side"
    over = max(0.0, hs_ft - 2)
    if kind == "with":
        d = min(0.5, 0.15 * over) if (tp_s or 0) >= 7 else 0.0
    elif kind == "against":
        d = -min(1.0, 0.25 * over)
    else:
        d = -min(0.5, 0.1 * over)
    if hs_ft >= 6:
        d -= 1.0
    return d, (kind if over > 0 else None)


def current_part(along_kt: float | None) -> float:
    """Along-course current (+ with you): ±0.5 per knot, capped at ±1."""
    return 0.0 if along_kt is None else max(-1.0, min(1.0, 0.5 * along_kt))


def water_part(f: float | None) -> float:
    if f is None:
        return 0.0
    return -0.5 if f < 56 else -0.25 if f < 59 else 0.0


def leg_score(wind: tuple[float, float | None, float] | None, bearing: float, ocean: bool,
              swell: tuple[float, float, float] | None = None, current_kt: float | None = None) -> dict:
    """wind = (kt, gust kt, from deg); swell = (Hs ft, Tp s, Dp from deg)."""
    out = {"score": None, "label": None}
    if wind is None:
        return out
    kt, gust, wfrom = wind
    s = 3.0
    dw, rel = wind_part(kt, gust, wfrom, bearing, ocean)
    s += dw
    out.update(windRel=rel)
    if ocean and swell:
        ds, srel = swell_part(swell[0], swell[1], swell[2], bearing)
        s += ds
        out.update(swellRel=srel)
    if current_kt is not None:
        s += current_part(current_kt)
        out.update(currentRel="with" if current_kt > 0.2 else "against" if current_kt < -0.2 else "slack")
    out["score"] = round(clamp(s), 2)
    out["label"] = label(out["score"])
    return out


def overall(legs: list[dict], water_f: float | None = None) -> dict:
    """Race call from scored legs (each with score, miles)."""
    sc = [l for l in legs if l.get("score") is not None]
    if not sc:
        return {"score": None, "label": None, "reason": "No forecast yet."}
    tot = sum(l["miles"] for l in sc) or 1.0
    mean = sum(l["score"] * l["miles"] for l in sc) / tot
    s = clamp(0.7 * mean + 0.3 * min(l["score"] for l in sc) + water_part(water_f))
    return {"score": round(s, 2), "label": label(s), "reason": reason(sc, water_f)}


def mean_wind(legs: list[dict]) -> tuple[float, float] | None:
    """Distance-weighted vector-mean wind (kt, from deg) over the legs."""
    x = y = n = 0.0
    for l in legs:
        if l.get("windKt") is None or l.get("windFrom") is None:
            continue
        r = math.radians(l["windFrom"])
        x += l["miles"] * l["windKt"] * math.sin(r)
        y += l["miles"] * l["windKt"] * math.cos(r)
        n += l["miles"]
    if not n:
        return None
    sp = sum(l["windKt"] * l["miles"] for l in legs if l.get("windKt") is not None) / n
    return sp, (math.degrees(math.atan2(x, y)) + 360) % 360


def reason(legs: list[dict], water_f: float | None = None) -> str:
    """Plain one-liner, e.g. "NW 12 kt → downwind on the ocean leg, headwind into the bay"."""
    mw = mean_wind(legs)
    if not mw:
        return "No wind forecast yet."
    # merge consecutive legs with the same name, then runs with the same wind relation
    groups: list[dict] = []
    for l in legs:
        rel = l.get("windRel")
        if groups and groups[-1]["leg"] == l["leg"]:
            g = groups[-1]
            g["miles"] += l["miles"]
            g["rels"][rel] = g["rels"].get(rel, 0) + l["miles"]
        else:
            groups.append({"leg": l["leg"], "miles": l["miles"], "rels": {rel: l["miles"]}})
    for g in groups:
        g["rel"] = max(g["rels"], key=g["rels"].get)
    if all(g["rel"] == "light" for g in groups):
        text = f"Light wind ({compass(mw[1])} {round(mw[0])} kt) all race"
    else:
        runs: list[dict] = []
        for g in groups:
            if runs and runs[-1]["rel"] == g["rel"]:
                runs[-1]["miles"] += g["miles"]
            else:
                runs.append({"rel": g["rel"], "leg": g["leg"], "miles": g["miles"]})
        keep = sorted(sorted(runs, key=lambda r: -r["miles"])[:3], key=runs.index)
        text = f"{compass(mw[1])} {round(mw[0])} kt → " + ", ".join(
            f"{REL_WORD[r['rel']]} {r['leg']}" for r in keep)
    extra = []
    big = [l for l in legs if (l.get("swellFt") or 0) >= 4]
    if big:
        b = max(big, key=lambda l: l["swellFt"])
        extra.append(f"{round(b['swellFt'])} ft swell {b['leg']}")
    cur = [l for l in legs if l.get("currentKt") is not None and abs(l["currentKt"]) >= 0.5]
    if cur:
        c = max(cur, key=lambda l: abs(l["currentKt"]))
        extra.append(f"{'current with you' if c['currentKt'] > 0 else 'current against you'} {c['leg']}")
    if water_f is not None and water_f < 59:
        extra.append(f"cold water ({round(water_f)}°F)")
    return text + ("; " + "; ".join(extra) if extra else "")
