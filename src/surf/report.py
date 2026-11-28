"""Surftracker's daily written surf and paddle report, made from our own data.

    python -m src.surf.report            # refresh web/api/v1/surf_report.json if due
    python -m src.surf.report --force    # always rewrite
    python -m src.surf.report --template # deterministic writer only (no API call)

Pipeline:
  1. facts(): every number the report may use, precomputed from surf.json and
     surf_spots.json (breaking face heights, sets, wind, tide, water temp,
     swell, sun) plus the NWS notes and alerts. Rounded and in local time.
  2. Writer: Claude (small model, strict system prompt, JSON output) when
     ANTHROPIC_API_KEY is set, else the template writer below.
  3. check(): every height, wind speed, temperature, period, degree, clock
     time, weekday and compass direction in the text must come from the facts.
     A failed Claude draft is retried once with the problems listed, then we
     fall back to the template. A report therefore always publishes.

Style rules (own words, no third-party text): shared notes surf-writer-style.md.
All surf heights are breaking face height. Swell heights only appear labelled
as swell (buoy readings). NWS text is public domain and quoted as NWS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "web" / "api" / "v1"
SURF, SPOTS, OUT = API / "surf.json", API / "surf_spots.json", API / "surf_report.json"
LA = ZoneInfo("America/Los_Angeles")

MODEL = os.environ.get("SURF_REPORT_MODEL") or "claude-haiku-5-5"
REFRESH_H = 3            # rewrite at most every 3 h unless the picture changes
OUTLOOK_DAYS = 5

# Five report regions, north to south, by latitude (finer than the page's 4 areas:
# North County is split at Ponto so Encinitas/Cardiff gets its own line).
REGIONS = (
    (33.085, "North County"),          # Oceanside, Carlsbad
    (32.975, "Encinitas/Cardiff"),     # Leucadia, Swamis, Cardiff
    (32.81, "Del Mar/La Jolla"),       # Solana, Del Mar, Torrey, Blacks, La Jolla
    (32.70, "PB/OB/Mission"),          # Mission Beach, PB, OB, Sunset Cliffs
    (-90.0, "Coronado/IB"),            # Coronado, Silver Strand, Imperial Beach
)
REGION_NAMES = [r[1] for r in REGIONS]
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
BUOY_NAMES = {"191": "Point Loma South", "220": "Mission Bay West", "201": "Scripps Nearshore",
              "262": "Leucadia Nearshore", "264": "Red Beach Nearshore"}
SWELL_BUOYS = ("191", "220")       # the more exposed buoys, for the swell reading
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
RATING_ORDER = ["FLAT", "POOR", "POOR–FAIR", "FAIR", "FAIR–GOOD", "GOOD", "EPIC"]


# ── small helpers ───────────────────────────────────────────────────────────

def _t(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def clock(dt: datetime, exact: bool = False) -> str:
    """'7 AM', '10 AM', 'noon', '6:42 AM' (local)."""
    d = dt.astimezone(LA)
    if not exact or d.minute == 0:
        if not exact and d.minute >= 30:
            d = d + timedelta(minutes=60 - d.minute)
        if d.hour == 12:
            return "noon"
        if d.hour == 0:
            return "midnight"
        return f"{d.hour % 12 or 12} {'AM' if d.hour < 12 else 'PM'}"
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def compass(deg: float | None) -> str | None:
    return None if deg is None else COMPASS[round((deg % 360) / 22.5) % 16]


def circ_mean(degs: list[float]) -> float | None:
    import math
    if not degs:
        return None
    s = sum(math.sin(math.radians(d)) for d in degs)
    c = sum(math.cos(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(s, c)) % 360


def nearest_rank(vals: list[float], q: float) -> float:
    """A percentile that is always one of the input values (never interpolated)."""
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def region_of(lat: float) -> str:
    return next(name for lim, name in REGIONS if lat > lim)


def rating_max(labels: list[str]) -> str | None:
    ok = [l for l in labels if l in RATING_ORDER]
    return max(ok, key=RATING_ORDER.index) if ok else None


def wetsuit(f: int | None) -> str | None:
    if f is None:
        return None
    return ("4/3 fullsuit" if f <= 60 else "3/2 fullsuit" if f <= 65
            else "springsuit or 2 mm" if f <= 70 else "trunks or a top")


BANDS = ((1, "flat"), (2, "ankle to knee"), (3, "knee to waist"), (4, "waist to chest"),
         (5, "chest to shoulder"), (6, "head high"), (8, "overhead"))
BODY_WORDS = re.compile(r"\b(ankle|knee|waist|chest|shoulder|head[- ]high|overhead|double overhead|"
                        r"well overhead)\b", re.I)


def body_band(lo: float, hi: float) -> str:
    """Same bands as the page (sfBand), on the middle of the range."""
    m = (lo + hi) / 2
    return next((b for lim, b in BANDS if m < lim), "well overhead")


def _mode(xs: list[str]) -> str | None:
    xs = [x for x in xs if x]
    return max(set(xs), key=xs.count) if xs else None


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.info("surf report: %s unreadable: %s", path.name, e)
        return None


# ── 1. facts ────────────────────────────────────────────────────────────────

def _spots(surf: dict, spots: dict | None, now: datetime) -> list[dict]:
    out, seen = [], set()
    for b in surf.get("breaks", []):
        seen.add(b["id"])
        out.append(dict(b, main=True, region=region_of(b["lat"])))
    if spots and spots.get("generatedAt"):
        age_h = (now - _t(spots["generatedAt"])).total_seconds() / 3600
        if age_h <= float(spots.get("staleAfterHours", 30)):
            for b in spots.get("spots", []):
                if b["id"] not in seen:
                    out.append(dict(b, main=False, region=region_of(b["lat"])))
    return out


def _sun_for(surf: dict, day) -> dict:
    return next((s for s in surf.get("sun") or [] if s.get("date") == day.isoformat()), {})


def _daylight(hours: list[dict], day, sun: dict, after: datetime | None) -> list[dict]:
    lo = _t(sun["firstLight"]) if sun.get("firstLight") else None
    hi = _t(sun.get("sunset") or sun["lastLight"]) if sun.get("lastLight") else None
    res = []
    for h in hours:
        t = _t(h["t"])
        if t.astimezone(LA).date() != day:
            continue
        if after and t < after - timedelta(minutes=90):
            continue
        if lo and hi:
            if not (lo - timedelta(minutes=60) <= t <= hi):
                continue
        elif not 6 <= t.astimezone(LA).hour <= 17:
            continue
        res.append(h)
    return res


def _wind(steps: list[dict]) -> dict | None:
    w = [h for h in steps if h.get("windKt") is not None]
    if not w:
        return None
    kts = [round(h["windKt"]) for h in w]
    gusts = [round(h["windGustKt"]) for h in w if h.get("windGustKt") is not None]
    out = {"kt": [min(kts), max(kts)], "from": compass(circ_mean([h["windFrom"] for h in w if h.get("windFrom") is not None])),
           "type": _mode([h.get("windType") for h in w])}
    if gusts and max(gusts) >= max(kts) + 5:
        out["gustKt"] = max(gusts)
    return out


def _spot_day(b: dict, day, sun: dict, after: datetime | None) -> dict | None:
    st = _daylight(b.get("hours") or [], day, sun, after)
    if not st:
        return None
    big = max(st, key=lambda h: (h["faceFt"][1], h.get("setsFt") or 0))
    best = max(st, key=lambda h: h.get("score") or 0)
    sets = max((h.get("setsFt") or 0) for h in st)
    return {"spot": b, "steps": st, "faceFt": list(big["faceFt"]),
            "setsFt": sets if sets > big["faceFt"][1] else None,
            "best": best, "rating": best.get("label"),
            "am": [h for h in st if _t(h["t"]).astimezone(LA).hour < 12],
            "pm": [h for h in st if _t(h["t"]).astimezone(LA).hour >= 12]}


def _size(days: list[dict]) -> dict:
    """County or region size: typical range plus the biggest sets and where."""
    lo = int(nearest_rank([d["faceFt"][0] for d in days], 0.5))
    hi = int(nearest_rank([d["faceFt"][1] for d in days], 0.5))
    hi = max(hi, lo)
    top = max(days, key=lambda d: (d["faceFt"][1], d["faceFt"][0]))
    out = {"typicalFaceFt": [lo, hi], "feel": body_band(lo, hi),
           "biggestFaceFt": top["faceFt"], "biggestAt": top["spot"]["name"]}
    withsets = [d for d in days if d["setsFt"]]
    if withsets:                    # main breaks carry setsFt (H1/10, as NWS "sets to")
        s = max(withsets, key=lambda d: d["setsFt"])
        if s["setsFt"] > max(hi, top["faceFt"][1]):
            out["biggestSetsFt"], out["setsAt"] = s["setsFt"], s["spot"]["name"]
    return out


def _best_spots(days: list[dict], n: int = 3) -> list[dict]:
    ranked = sorted(days, key=lambda d: (d["best"].get("score") or 0, d["spot"]["main"]), reverse=True)
    out = []
    for d in ranked[:n]:
        h = d["best"]
        e = {"name": d["spot"]["name"], "region": d["spot"]["region"], "faceFt": list(h["faceFt"]),
             "rating": h.get("label"), "around": clock(_t(h["t"])), "wind": h.get("windType")}
        if h.get("setsFt") and h["setsFt"] > h["faceFt"][1]:
            e["setsFt"] = h["setsFt"]
        out.append(e)
    return out


def _swell(main_days: list[dict], surf: dict, now: datetime, use_buoy: bool) -> dict:
    tps = [h["tpS"] for d in main_days for h in d["steps"] if h.get("tpS")]
    dps = [h["dpDeg"] for d in main_days for h in d["steps"] if h.get("dpDeg") is not None]
    out = {"periodS": int(round(median(tps))) if tps else None,
           "fromDir": compass(circ_mean(dps)), "note": "model swell period and direction at the beaches"}
    if use_buoy:
        for st in SWELL_BUOYS:
            b = (surf.get("buoys") or {}).get(st)
            if b and b.get("hsFt") and b.get("t") and now - _t(b["t"]) < timedelta(hours=6):
                out["buoy"] = {"name": f"{BUOY_NAMES.get(st, st)} buoy", "swellFt": round(b["hsFt"], 1),
                               "periodS": int(round(b["tpS"])) if b.get("tpS") else None,
                               "fromDir": compass(b.get("dpDeg")), "fromDeg": b.get("dpDeg"),
                               "note": "open-water swell height, not surf height"}
                break
    out["kind"] = ("long-period" if (out["periodS"] or 0) >= 14 else
                   "mid-period" if (out["periodS"] or 0) >= 10 else "short-period")
    return out


def _tides(surf: dict, start: datetime, end: datetime) -> list[dict]:
    out = []
    for x in (surf.get("tides") or {}).get("hilo") or []:
        t = _t(x["t"])
        if start <= t <= end:
            out.append({"type": "high" if x["type"] == "H" else "low", "time": clock(t, exact=True),
                        "day": WEEKDAYS[t.astimezone(LA).weekday()], "ft": round(x["ft"], 1)})
    return out


def _tide_trend(surf: dict, day, after: datetime | None) -> dict:
    """{'morning': 'rising (on the push)', 'afternoon': 'falling (on the drop)', ...}
    for the parts of the day still ahead; 'turning' when a high or low falls inside."""
    hilo = sorted(((_t(x["t"]), x["type"]) for x in (surf.get("tides") or {}).get("hilo") or []))
    out = {}
    for name, h0, h1 in (("morning", 6, 12), ("afternoon", 12, 17)):
        a = datetime.combine(day, datetime.min.time(), LA) + timedelta(hours=h0)
        b = datetime.combine(day, datetime.min.time(), LA) + timedelta(hours=h1)
        if after and b <= after:
            continue
        a = max(a, after) if after else a
        inside = [k for tt, k in hilo if a < tt < b]
        nxt = next((k for tt, k in hilo if tt >= a), None)
        if inside:
            out[name] = ("rising, then falling (on the drop) after the high" if inside[0] == "H"
                         else "falling, then rising (on the push) after the low")
        elif nxt:
            out[name] = "rising (on the push)" if nxt == "H" else "falling (on the drop)"
    return out


def _conf(days: list[dict]) -> str:
    c = [h.get("conf") for d in days for h in d["steps"]]
    return _mode(c) or "medium"


def facts(surf: dict, spots: dict | None = None, now: datetime | None = None) -> dict:
    """Everything the writer may say, as plain numbers and words."""
    now = now or datetime.now(timezone.utc)
    loc = now.astimezone(LA)
    allspots = _spots(surf, spots, now)
    day = loc.date()
    sun = _sun_for(surf, day)
    after_dark = bool(sun.get("lastLight")) and now > _t(sun["lastLight"]) - timedelta(minutes=30)
    if after_dark:
        day = day + timedelta(days=1)
        sun = _sun_for(surf, day)
    after = None if after_dark else now
    sd = [x for x in (_spot_day(b, day, sun, after) for b in allspots) if x]
    if not sd:                                     # nothing left of today: report tomorrow
        day = day + timedelta(days=1)
        sun, after = _sun_for(surf, day), None
        sd = [x for x in (_spot_day(b, day, sun, None) for b in allspots) if x]
    main = [d for d in sd if d["spot"]["main"]] or sd
    part = ("tomorrow" if day != loc.date() else
            "morning" if loc.hour < 11 else "afternoon" if loc.hour < 16 else "evening")

    f: dict = {
        "issued": f"{WEEKDAYS[loc.weekday()]} {clock(now, exact=True)}",
        "reportDay": WEEKDAYS[day.weekday()], "covers": part,
        "spotsCounted": len(sd),
        "today": {},
        "regions": [],
        "outlook": [],
        "rules": "All surf heights are breaking face height at the beach.",
    }
    if not sd:
        f["today"] = {"noData": True}
        return f

    t = f["today"]
    t["size"] = _size(sd)
    t["rating"] = rating_max([d["rating"] for d in main])
    t["bestSpots"] = _best_spots(sd)
    t["swell"] = _swell(main, surf, now, use_buoy=not after_dark and day == loc.date())
    am = [h for d in main for h in d["am"]]
    pm = [h for d in main for h in d["pm"]]
    t["wind"] = {k: v for k, v in (("morning", _wind(am)), ("afternoon", _wind(pm))) if v}
    # Tides: from now through tomorrow noon.
    tide_from = now if day == loc.date() else datetime.combine(day, datetime.min.time(), LA)
    tide_to = datetime.combine(day + timedelta(days=1), datetime.min.time(), LA) + timedelta(hours=12)
    t["tides"] = _tides(surf, tide_from, tide_to)
    trend = _tide_trend(surf, day, after)
    if trend:
        t["tideTrend"] = trend
    wt = surf.get("waterTemp")
    if wt and wt.get("f") is not None and now - _t(wt["t"]) < timedelta(hours=24):
        t["waterTempF"] = int(wt["f"])
        t["waterAt"] = f"{BUOY_NAMES.get(str(wt.get('station')), 'nearshore')} buoy"
        t["wetsuit"] = wetsuit(int(wt["f"]))
    if sun.get("firstLight"):
        t["firstLight"] = clock(_t(sun["firstLight"]), exact=True)
    if sun.get("sunset"):
        t["sunset"] = clock(_t(sun["sunset"]), exact=True)
    t["confidence"] = _conf(main)

    # Regions
    for name in REGION_NAMES:
        r = [d for d in sd if d["spot"]["region"] == name]
        if not r:
            continue
        e = {"region": name, "spots": len(r), **_size(r),
             "rating": rating_max([d["rating"] for d in r]),
             "best": _best_spots(r, 1)[0]}
        w = _wind([h for d in r for h in d["am"]])
        if w:
            e["morningWind"] = w
        f["regions"].append(e)

    # Paddle: county wind (median of the main breaks) per daylight time step, looking
    # into tomorrow morning when the report is written in the afternoon; the wind
    # "rises to" only counts after the calm window. Plus the smallest beach.
    by_t: dict[str, list[dict]] = {}
    for d in main:
        for h in d["steps"]:
            if h.get("windKt") is not None:
                by_t.setdefault(h["t"], []).append(h)
    if part in ("afternoon", "evening"):
        nday = day + timedelta(days=1)
        nsun = _sun_for(surf, nday)
        for b in allspots:
            x = _spot_day(b, nday, nsun, None) if b["main"] else None
            for h in (x["am"] if x else []):
                if h.get("windKt") is not None:
                    by_t.setdefault(h["t"], []).append(h)
    series = []
    for ts, hs in sorted(by_t.items(), key=lambda kv: _t(kv[0])):
        series.append({"t": _t(ts), "kt": round(median([h["windKt"] for h in hs])),
                       "from": compass(circ_mean([h["windFrom"] for h in hs if h.get("windFrom") is not None]))})
    if series:
        def when(x):
            return {"around": clock(x["t"]), "day": WEEKDAYS[x["t"].astimezone(LA).weekday()]}
        calm = min(series, key=lambda x: (x["kt"], x["t"]))
        later = [x for x in series if x["t"] > calm["t"] and x["t"].astimezone(LA).date() == calm["t"].astimezone(LA).date()]
        beaches = [x for x in sd if x["spot"].get("type") in ("beach", "shores")] or sd
        small = min(beaches, key=lambda x: (x["faceFt"][1], x["setsFt"] or 0))
        f["paddle"] = {"calmest": {**when(calm), "kt": calm["kt"], "from": calm["from"]},
                       "smallestBeach": {"name": small["spot"]["name"], "region": small["spot"]["region"],
                                         "faceFt": small["faceFt"]},
                       "oceanOk": small["faceFt"][1] <= 2 and calm["kt"] <= 8}
        if later:
            w = max(later, key=lambda x: x["kt"])
            if w["kt"] >= calm["kt"] + 4:
                f["paddle"]["windRisesTo"] = {**when(w), "kt": w["kt"], "from": w["from"]}

    # Outlook, day by day
    prev = main
    for i in range(1, OUTLOOK_DAYS + 1):
        dday = day + timedelta(days=i)
        dsun = _sun_for(surf, dday)
        dd = [x for x in (_spot_day(b, dday, dsun, None) for b in allspots) if x]
        dmain = [x for x in dd if x["spot"]["main"]] or dd
        if not dmain:
            break
        mid = median([(x["faceFt"][0] + x["faceFt"][1]) / 2 for x in dmain])
        pmid = median([(x["faceFt"][0] + x["faceFt"][1]) / 2 for x in prev])
        trend = "building" if mid > pmid * 1.15 + 0.2 else "easing" if mid < pmid * 0.85 - 0.2 else "steady"
        sw = _swell(dmain, surf, now, use_buoy=False)
        psw = _swell(prev, surf, now, use_buoy=False)
        e = {"day": WEEKDAYS[dday.weekday()], **_size(dd), "rating": rating_max([x["rating"] for x in dmain]),
             "trend": trend, "swell": {k: sw[k] for k in ("periodS", "fromDir", "kind")},
             "bestRegion": max(REGION_NAMES, key=lambda n: max([x["best"].get("score") or 0 for x in dd
                                                                 if x["spot"]["region"] == n] or [-1])),
             "confidence": _conf(dmain)}
        if sw["periodS"] and psw["periodS"] and sw["periodS"] - psw["periodS"] >= 3:
            e["newSwell"] = True
        w_am = _wind([h for x in dmain for h in x["am"]])
        w_pm = _wind([h for x in dmain for h in x["pm"]])
        if w_am:
            e["morningWind"] = w_am
        if w_pm:
            e["afternoonWind"] = w_pm
        f["outlook"].append(e)
        prev = dmain

    # NWS (public domain): active alerts, surf zone headline, forecaster notes.
    nws: dict = {}
    alerts = []
    for a in surf.get("nwsAlerts") or []:
        if a.get("until") and _t(a["until"]) < now:
            continue
        e = {"event": a.get("event")}
        if a.get("until"):
            u = _t(a["until"])
            e["until"] = f"{WEEKDAYS[u.astimezone(LA).weekday()]} {clock(u)}"
        alerts.append(e)
    if isinstance(surf.get("nwsAlerts"), list):      # fetched OK: an empty list means none
        nws["alerts"] = alerts
    srf = surf.get("nws") or {}
    if srf.get("periods"):
        p = srf["periods"][0]
        nws["ripRisk"] = p.get("ripRisk")
    notes = surf.get("nwsNotes") or {}
    if notes.get("paragraphs") and notes.get("issued") and now - _t(notes["issued"]) < timedelta(hours=36):
        nws["forecasterNotes"] = notes["paragraphs"]
        ni = _t(notes["issued"])
        nws["notesIssued"] = f"{WEEKDAYS[ni.astimezone(LA).weekday()]} {clock(ni, exact=True)}"
    if nws:
        f["nws"] = nws
    cav = []
    if t["confidence"] != "high":
        cav.append("Model confidence today is " + t["confidence"] + ".")
    if any(e["confidence"] == "low" for e in f["outlook"]):
        cav.append("Days 5 and beyond are low confidence.")
    if t["size"]["typicalFaceFt"][1] < 6:
        cav.append("Small-day heights are not yet verified against observations; "
                   "they run about 20% above NWS surf forecasts.")
    if cav:
        f["caveats"] = cav
    return f


# ── 2a. template writer (deterministic fallback) ────────────────────────────

def _rng(r: list) -> str:
    return f"{r[0]} ft" if r[0] == r[1] else f"{r[0]}–{r[1]} ft"


def _sz(s: dict, key="typicalFaceFt") -> str:
    r = s[key]
    if r[1] <= 1:
        return "flat to 1 ft" if r[1] == 1 else "flat"
    return _rng(r)


def _windtxt(w: dict | None) -> str:
    if not w:
        return "wind data missing"
    kt = w["kt"]
    k = f"{kt[0]} kt" if kt[0] == kt[1] else f"{kt[0]}–{kt[1]} kt"
    if w.get("type") == "glassy":
        s = f"glassy ({k})"
    elif w.get("type"):
        s = f"{w['type']} {w['from']} {k}" if w.get("from") else f"{w['type']} {k}"
    else:
        s = f"{w.get('from') or ''} {k}".strip()
    if w.get("gustKt"):
        s += f", gusts {w['gustKt']} kt"
    return s


def _title(lbl: str | None) -> str:
    return (lbl or "").lower().replace("–", "-").title().replace("-", "–")


def template(f: dict) -> dict:
    t = f.get("today") or {}
    if t.get("noData"):
        return {"headline": "Forecast data unavailable",
                "today": "The surf model has no data for today yet. Check back after the next update.",
                "outlook": "", "regions": [], "paddle": ""}
    when = "Tomorrow" if f["covers"] == "tomorrow" else "Today" if f["covers"] == "morning" else "Rest of today"
    s = t["size"]
    sets = f", sets to {s['biggestSetsFt']} ft at {s['setsAt']}" if s.get("biggestSetsFt") else ""
    sw = t["swell"]
    swell = f"{sw['kind'].capitalize()} {sw['fromDir']} swell" if sw.get("fromDir") else f"{sw['kind'].capitalize()} swell"
    if sw.get("periodS"):
        swell += f" at {sw['periodS']} s"
    b = sw.get("buoy")
    if b and b.get("periodS"):
        swell += f"; the {b['name']} reads {b['swellFt']} ft of swell at {b['periodS']} s"
    parts = [f"{when}: {_sz(s)} at most spots{sets}, {_title(t['rating'])} at best."]
    best = t.get("bestSpots") or []
    if best:
        bb = best[0]
        parts.append(f"Best bet: {bb['name']} around {bb['around']}, {_rng(bb['faceFt'])}.")
    parts.append(swell + ".")
    w = t.get("wind", {})
    if w:
        bits = []
        if w.get("morning"):
            bits.append(f"morning {_windtxt(w['morning'])}")
        if w.get("afternoon"):
            bits.append(f"afternoon {_windtxt(w['afternoon'])}")
        parts.append("Wind: " + "; ".join(bits) + ".")
    tides = t.get("tides") or []
    if tides:
        parts.append("Tide: " + ", ".join(f"{x['type']} {x['ft']} ft at {x['time']}"
                                          + ("" if x["day"] == f["reportDay"] else f" {x['day']}")
                                          for x in tides[:3]) + ".")
    if t.get("waterTempF") is not None:
        parts.append(f"Water {t['waterTempF']}°F ({t['wetsuit']}).")
    nws = f.get("nws") or {}
    if nws.get("alerts"):
        a = nws["alerts"][0]
        parts.append(f"NWS {a['event']}" + (f" until {a['until']}." if a.get("until") else "."))
    if nws.get("ripRisk") in ("High", "Moderate"):
        parts.append(f"NWS rip current risk: {nws['ripRisk'].lower()}.")
    if t.get("confidence") == "low":
        parts.append("Model confidence is low.")

    out_lines = []
    for e in f.get("outlook", [])[:OUTLOOK_DAYS]:
        hedge = {"high": "", "medium": " (looks like)", "low": " (early read)"}[e["confidence"]]
        trend = {"building": "building", "easing": "easing", "steady": "holding"}[e["trend"]]
        txt = f"{e['day']}: {trend}, {_sz(e)}"
        if e.get("biggestSetsFt"):
            txt += f", sets to {e['biggestSetsFt']} ft"
        sw2 = e["swell"]
        if sw2.get("periodS"):
            txt += f", {sw2['periodS']} s {sw2.get('fromDir') or ''}".rstrip()
        if e.get("morningWind"):
            txt += f"; AM wind {_windtxt(e['morningWind'])}"
        out_lines.append(txt + hedge + ".")
    head = f"{_sz(s)}{', sets to ' + str(s['biggestSetsFt']) + ' ft' if s.get('biggestSetsFt') else ''}, {_title(t['rating'])}"
    regions = []
    for r in f.get("regions", []):
        bb = r["best"]
        line = f"{_sz(r)}"
        if r.get("biggestSetsFt"):
            line += f", sets to {r['biggestSetsFt']} ft"
        line += f"; best at {bb['name']} around {bb['around']}"
        if r.get("morningWind"):
            line += f", morning wind {_windtxt(r['morningWind'])}"
        regions.append({"region": r["region"], "line": line + "."})
    p = f.get("paddle")
    paddle = ""
    if p:
        c, w2 = p["calmest"], p.get("windRisesTo")
        def at(x):
            return f"around {x['around']}" + ("" if x["day"] == f["reportDay"] else f" {x['day']}")
        paddle = f"Lightest wind {c['kt']} kt {at(c)}"
        if w2:
            paddle += f", rising to {w2['kt']} kt {at(w2)}"
        paddle += (f". Smallest surf: {p['smallestBeach']['name']} "
                   f"({_sz({'typicalFaceFt': p['smallestBeach']['faceFt']})}).")
        paddle += (" Ocean paddling looks reasonable early." if p["oceanOk"]
                   else " Ocean launches need care through the surf; the bays and harbours are the easier paddle.")
    return {"headline": head, "today": " ".join(parts), "outlook": " ".join(out_lines),
            "regions": regions, "paddle": paddle}


# ── 2b. Claude writer ───────────────────────────────────────────────────────

SYSTEM = """You write Surftracker's daily surf and paddle report for San Diego County, in the voice of a calm, experienced local forecaster. Your readers surf and stand-up paddle. You write only from the FACTS JSON you are given.

Hard rules:
1. Every number, clock time, weekday and compass direction you write must appear in FACTS (you may round a decimal to a whole number). Do not compute new numbers, averages, dates or conversions. Never use mph or metres.
2. Surf heights are breaking face height. Copy height ranges exactly as given (typicalFaceFt, faceFt or biggestFaceFt), e.g. "3–5 ft". Write "sets to X ft" only with a setsFt or biggestSetsFt value; if there is none, don't mention sets. A biggestFaceFt range is the biggest spot's range, not sets. NWS numbers may be used only in a sentence that credits the NWS. Only call something "swell" when FACTS label it swell (the buoy reading or the swell period/direction). Never present a swell height as surf size.
3. Never claim to have seen conditions. There are no observations here, only the model forecast and NWS text. Don't write "reports say", "lines are stacking", "we saw", etc.
4. Hedge with the given confidence: high = plain statements; medium = "should", "looks like"; low = "early read", "could". If caveats are present, reflect them briefly.
5. The Today text must cover, in 70–110 words: size and quality first (the first two sentences are shown alone on phones, so make them the answer: how big, how good, best spot and time), then swell (direction and period), wind by time of day, tide times, and water temperature with the wetsuit hint. Mention any NWS alert in one short clause credited to the NWS (the page already shows it as a banner).
6. Outlook: one short sentence per day in FACTS.outlook, using the weekday names, trend words (building, holding, easing), size, sets, period and morning wind. 40–90 words.
7. Region lines: one sentence each (max 25 words) for exactly the regions in FACTS.regions, with size, sets if given, and the best spot and time.
8. Paddle: one or two sentences for SUP paddlers: the calmest wind window (paddle.calmest is when to go; don't advise another time), when the wind comes up (only if paddle.windRisesTo is given), and whether an ocean launch is sensible (oceanOk, smallest beach) or to stick to the bays and harbours.
9. Plain, casual, local. No hype, no exclamation marks, no emoji, no brand or forecaster names, no dates. Use genre terms correctly: glassy, light, textured, choppy, blown out, offshore, onshore, on the push (rising tide), on the drop (falling tide), long-period, combo.
10. Headline: under 10 words, the size and the call (e.g. "Solid west swell, clean early").
11. Sizes in FACTS.outlook and typicalFaceFt are county-wide "most spots" ranges: never attach them to one spot. Body-size words (waist, chest, head high, overhead...) only as given in a "feel" field. Tide direction only from today.tideTrend ("on the push" = rising, "on the drop" = falling). Mention NWS alerts only if FACTS.nws.alerts lists them; say there are none only if FACTS.nws.alerts is an empty list. Don't characterise wave quality beyond FACTS (no "soft", "punchy", "hollow").
12. NWS forecaster notes were issued at FACTS.nws.notesIssued; skip anything in them that is already past (e.g. "this morning" when it is now afternoon).

Style: write like a person, not a data dump. Say "most spots run 3–6 ft" for typicalFaceFt and "the biggest is Ab's at 6–9 ft" for biggestFaceFt; don't repeat the words "typically" or "biggest faces" in every sentence. Ratings in lower case ("fair to good"). For the buoy say e.g. "the Point Loma South buoy has 7.3 ft of open-ocean swell at 14 s". Use "s" for seconds. Name a spot and a time when you give a best bet. Skip a fact rather than force it in awkwardly.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "today": {"type": "string"},
        "outlook": {"type": "string"},
        "regions": {"type": "array", "items": {
            "type": "object",
            "properties": {"region": {"type": "string", "enum": REGION_NAMES}, "line": {"type": "string"}},
            "required": ["region", "line"], "additionalProperties": False}},
        "paddle": {"type": "string"},
    },
    "required": ["headline", "today", "outlook", "regions", "paddle"],
    "additionalProperties": False,
}


def _client():
    import anthropic
    return anthropic.Anthropic(timeout=90.0, max_retries=2)


def claude_draft(f: dict, client=None, feedback: list[str] | None = None) -> tuple[dict | None, dict]:
    """One Claude call. Returns (report or None, usage)."""
    import anthropic
    client = client or _client()
    user = "FACTS:\n" + json.dumps(f, ensure_ascii=False, indent=1)
    if feedback:
        user += ("\n\nYour previous draft failed the fact check. Fix these and change nothing else:\n- "
                 + "\n- ".join(feedback[:12]))
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=4000, system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIConnectionError as e:
        log.warning("surf report: Claude unreachable: %s", e)
        return None, {}
    except anthropic.RateLimitError as e:
        log.warning("surf report: Claude rate limited: %s", e)
        return None, {}
    except anthropic.APIStatusError as e:
        log.warning("surf report: Claude error %s: %s", e.status_code, e.message)
        return None, {}
    u = getattr(resp, "usage", None)
    usage = {"in": getattr(u, "input_tokens", 0) or 0, "out": getattr(u, "output_tokens", 0) or 0}
    if resp.stop_reason != "end_turn":
        log.warning("surf report: Claude stopped with %s", resp.stop_reason)
        return None, usage
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text), usage
    except json.JSONDecodeError:
        log.warning("surf report: Claude returned non-JSON")
        return None, usage


# ── 3. fact check ───────────────────────────────────────────────────────────

LONG_DIRS = {"north": "N", "north-northeast": "NNE", "northeast": "NE", "east-northeast": "ENE",
             "east": "E", "east-southeast": "ESE", "southeast": "SE", "south-southeast": "SSE",
             "south": "S", "south-southwest": "SSW", "southwest": "SW", "west-southwest": "WSW",
             "west": "W", "west-northwest": "WNW", "northwest": "NW", "north-northwest": "NNW",
             "westerly": "W", "northwesterly": "NW", "southwesterly": "SW", "southerly": "S",
             "northerly": "N", "easterly": "E", "northeasterly": "NE", "southeasterly": "SE"}
BANNED = re.compile(r"surfline|stormsurf|magicseaweed|swellnet|surf-forecast|swellinfo|surf captain|"
                    r"\bwe saw\b|\breports? (?:say|from|of)\b|lifeguards? (?:say|report)|on the cams?\b|"
                    r"\bmph\b|\bmetres?\b|\bmeters?\b|!|[\U0001F300-\U0001FAFF]", re.I)
NUM = r"[-−]?\d+(?:\.\d+)?"
TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?)\s*(AM|PM|a\.m\.|p\.m\.)", re.I)
QTY_RE = re.compile(rf"({NUM})(?:\s*(?:–|-|to)\s*({NUM}))?\s*(ft|feet|foot|kt|knots?|°F|°|degrees|F\b|s\b|sec\b|seconds?)?",
                    re.I)


SURF_AS_SWELL = re.compile(r"((?:[-−]?\d+(?:\.\d+)?\s*(?:–|-|to)\s*)?[-−]?\d+(?:\.\d+)?)\s*(?:ft|feet|foot)"
                           r"\s+(?:of\s+)?(?:(?!(?:on|from|with|in|off|and|as|under|by)\b)[\w-]+\s+){0,3}swell", re.I)
FACE_KEYS = ("faceFt", "typicalFaceFt", "biggestFaceFt")
SETS_PRE = re.compile(r"sets?\s+(?:(?:up\s+)?to|of|near|reaching|around)?\s*$", re.I)


def _allowed(f: dict) -> dict[str, set]:
    a = {"pairs": set(), "sets": set(), "kpairs": set(), "surf": set(), "tide": set(), "swell": set(), "kt": set(), "temp": set(), "sec": set(),
         "deg": set(), "times": set(), "dirs": set(), "days": set(), "nws": set(), "count": set(), "npairs": set(), "names": set()}

    def walk(o, key=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in FACE_KEYS and isinstance(v, list) and len(v) == 2:
                    a["pairs"].add((float(v[0]), float(v[1])))
                if k == "kt" and isinstance(v, list) and len(v) == 2:
                    a["kpairs"].add((float(v[0]), float(v[1])))
                if k == "forecasterNotes":
                    for p in v:
                        for m in re.finditer(rf"({NUM})\s*(?:-|–|to)\s*({NUM})", p):
                            a["npairs"].add((float(m.group(1)), float(m.group(2))))
                        for m in re.finditer(NUM, p):
                            a["nws"].add(abs(float(m.group().replace("−", "-"))))
                    continue
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, bool) or o is None:
            return
        elif isinstance(o, (int, float)):
            k = key
            if k in FACE_KEYS:
                a["surf"].add(float(o))
            elif k in ("setsFt", "biggestSetsFt"):
                a["sets"].add(float(o))
            elif k == "ft":
                a["tide"].add(abs(float(o)))
            elif k == "swellFt":
                a["swell"].add(float(o))
            elif k in ("kt", "gustKt"):
                a["kt"].add(float(o))
            elif k == "waterTempF":
                a["temp"].add(float(o))
            elif k == "periodS":
                a["sec"].add(float(o))
            elif k == "fromDeg":
                a["deg"].add(float(o))
            elif k in ("spots", "spotsCounted"):
                a["count"].add(float(o))
        elif isinstance(o, str):
            if key in ("name", "biggestAt", "setsAt", "waterAt"):
                a["names"].add(o)
            for m in TIME_RE.finditer(o):
                a["times"].add(_norm_time(m.group(1), m.group(2)))
            if o in COMPASS:
                a["dirs"].add(o)
            for d in WEEKDAYS:
                if d in o:
                    a["days"].add(d)
            if key == "event" or key == "until":
                for m in re.finditer(NUM, o):
                    a["nws"].add(float(m.group()))
    walk(f)
    a["surf"] |= a["sets"]
    for k in ("surf", "tide", "swell"):   # allow rounding of decimals
        a[k] |= {float(round(x)) for x in a[k]} | {round(x, 1) for x in a[k]}
    a["nws"] |= {float(round(x)) for x in a["nws"]}
    return a


def _norm_time(hm: str, ap: str) -> str:
    ap = "AM" if ap.lower().startswith("a") else "PM"
    h, _, m = hm.partition(":")
    return f"{int(h)}:{m} {ap}" if m and m != "00" else f"{int(h)} {ap}"


def _dir_ok(code: str, allowed: set) -> bool:
    if code in allowed:
        return True
    i = COMPASS.index(code)
    return any(abs((COMPASS.index(x) - i + 8) % 16 - 8) <= 1 for x in allowed)


def check(rep: dict, f: dict) -> list[str]:
    """Problems with a draft; empty list when every fact matches FACTS."""
    probs: list[str] = []
    if not isinstance(rep, dict):
        return ["not an object"]
    a = _allowed(f)
    a["times"] |= {"noon", "midnight"}
    for key in ("headline", "today", "outlook", "paddle"):
        if not isinstance(rep.get(key), str):
            probs.append(f"missing {key}")
    regs = rep.get("regions") if isinstance(rep.get("regions"), list) else []
    want = {r["region"] for r in f.get("regions", [])}
    got = {r.get("region") for r in regs if isinstance(r, dict)}
    if want != got:
        probs.append(f"regions must be exactly {sorted(want)}")
    if probs:
        return probs
    t = rep["today"].lower()
    if not f.get("today", {}).get("noData"):
        for need, pat in (("tide", r"tide"), ("wind", r"wind|glassy|offshore|onshore"),
                          ("swell", r"swell"), ("water temperature", r"water|°f")):
            if need == "water temperature" and "waterTempF" not in f["today"]:
                continue
            if not re.search(pat, t):
                probs.append(f"today must mention {need}")
        if f.get("paddle") and len(rep["paddle"].strip()) < 20:
            probs.append("paddle line missing")
    if len(rep["today"].split()) > 140:
        probs.append("today is too long (keep it to 70–110 words)")
    if len(rep["outlook"].split()) > 120:
        probs.append("outlook is too long")
    texts = [("headline", rep["headline"]), ("today", rep["today"]), ("outlook", rep["outlook"]),
             ("paddle", rep["paddle"])] + [(f"region {r.get('region')}", r.get("line") or "") for r in regs]
    tide_words = " ".join((f.get("today") or {}).get("tideTrend", {}).values())
    bands = json.dumps(f).lower()
    rating_epic = any("EPIC" == (x or "") for x in re.findall(r'"rating": "([^"]+)"', json.dumps(f)))
    for where, txt in texts:
        m = BANNED.search(txt)
        if m:
            probs.append(f"{where}: banned wording '{m.group()}'")
        if re.search(r"\bepic\b", txt, re.I) and not rating_epic:
            probs.append(f"{where}: 'epic' not supported by the ratings")
        if re.search(r"on the push|incoming tide|rising tide|tide (?:is )?rising", txt, re.I) and \
                "rising" not in tide_words:
            probs.append(f"{where}: rising tide / 'on the push' is not in FACTS.today.tideTrend")
        if re.search(r"on the drop|outgoing tide|falling tide|dropping tide|tide (?:is )?(?:falling|dropping)", txt, re.I) and \
                "falling" not in tide_words:
            probs.append(f"{where}: falling tide / 'on the drop' is not in FACTS.today.tideTrend")
        if re.search(r"\bno (?:active )?(?:NWS )?(?:alerts|advisories|warnings|statements)\b", txt, re.I) and \
                (f.get("nws") or {}).get("alerts") != []:
            probs.append(f"{where}: 'no alerts' is only allowed when FACTS.nws.alerts is an empty list")
        for m in BODY_WORDS.finditer(txt):
            if m.group().lower().replace("-", " ") not in bands:
                probs.append(f"{where}: body size '{m.group()}' is not in FACTS (use the 'feel' band given)")
        for sent in re.split(r"(?<=[.;])\s+", txt):
            probs += _check_sentence(sent, a, where)
    # Scoped: an outlook sentence naming one day uses that day's ranges and sets;
    # a region line uses its own region's.
    days = {e["day"]: e for e in f.get("outlook", [])}
    for sent in re.split(r"(?<=[.;])\s+", rep["outlook"]):
        named = [d for d in days if re.search(rf"\b{d}\b", sent)]
        if len(named) == 1:
            probs += _scoped(sent, days[named[0]], f"outlook {named[0]}")
    regs_f = {r["region"]: r for r in f.get("regions", [])}
    for r in regs:
        if r.get("region") in regs_f:
            probs += _scoped(r.get("line") or "", regs_f[r["region"]], f"region {r['region']}")
    return probs


def _scoped(sent: str, entry: dict, where: str) -> list[str]:
    a = _allowed(entry)
    probs = []
    for m in QTY_RE.finditer(sent):
        unit = (m.group(3) or "").lower()
        if unit not in ("ft", "feet", "foot"):
            continue
        nums = [abs(float(x.replace("−", "-"))) for x in (m.group(1), m.group(2)) if x]
        sets_ctx = bool(SETS_PRE.search(sent[max(0, m.start() - 16):m.start()]))
        if m.group(2) and (nums[0], nums[1]) not in a["pairs"]:
            probs.append(f"{where}: range '{m.group().strip()}' is not this {where.split()[0]}'s range in FACTS")
        elif sets_ctx and nums[0] not in a["sets"]:
            probs.append(f"{where}: 'sets to {nums[0]:g} ft' is not this {where.split()[0]}'s sets value")
    return probs


def _check_sentence(sent: str, a: dict, where: str) -> list[str]:
    probs = []
    s = sent
    nws_ok = bool(re.search(r"\bNWS\b|National Weather Service", s))
    for m in TIME_RE.finditer(s):
        tm = _norm_time(m.group(1), m.group(2))
        if tm not in a["times"]:
            probs.append(f"{where}: time '{m.group().strip()}' is not in FACTS")
    s = TIME_RE.sub(" ", s)
    for d in WEEKDAYS:
        if re.search(rf"\b{d}\b", s) and d not in a["days"]:
            probs.append(f"{where}: weekday {d} is not in FACTS")
    for name in sorted(set(REGION_NAMES) | a["names"] | {n + " buoy" for n in BUOY_NAMES.values()}
                       | {"North County", "Point Loma", "South Bay"}, key=len, reverse=True):
        s = s.replace(name, " ")
    s = re.sub(r"\b\w+-facing\b", " ", s)
    s = re.sub(r"\b(3/2|4/3|2 mm|[0-9]/[0-9])\b", " ", s)   # wetsuit thickness
    for word, code in LONG_DIRS.items():
        for m in re.finditer(rf"\b{word}\b", s, re.I):
            if not _dir_ok(code, a["dirs"]):
                probs.append(f"{where}: direction '{m.group()}' is not in FACTS")
    for m in re.finditer(r"\b(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW)\b", s):
        if not _dir_ok(m.group(), a["dirs"]):
            probs.append(f"{where}: direction '{m.group()}' is not in FACTS")
    for m in SURF_AS_SWELL.finditer(s):
        vals = [abs(float(x.replace("−", "-"))) for x in re.findall(NUM, m.group(1))]
        if not all(v in a["swell"] for v in vals):
            probs.append(f"{where}: '{m.group().strip()}' calls a surf height swell; surf heights are "
                         "breaking face height, write the swell as period and direction only")
    swellish = bool(re.search(r"swell|buoy", s, re.I))
    tideish = bool(re.search(r"tide|high|low", s, re.I))
    for m in QTY_RE.finditer(s):
        nums = [abs(float(x.replace("−", "-"))) for x in (m.group(1), m.group(2)) if x]
        unit = (m.group(3) or "").lower()
        pre = s[max(0, m.start() - 9):m.start()].lower()
        sets_ctx = bool(SETS_PRE.search(s[max(0, m.start() - 16):m.start()]))
        if not unit and sets_ctx:
            unit = "ft"
        if unit in ("ft", "feet", "foot") and not (swellish and all(v in a["swell"] for v in nums)):
            if sets_ctx and not m.group(2):
                if nums[0] not in a["sets"] and not (nws_ok and nums[0] in a["nws"]):
                    probs.append(f"{where}: 'sets to {nums[0]:g} ft' is not a sets value in FACTS "
                                 "(sets come only from setsFt/biggestSetsFt; leave sets out if none)")
                continue
            if m.group(2):
                pair = (nums[0], nums[1])
                if pair not in a["pairs"] and not (nws_ok and pair in a["npairs"]) and not (
                        tideish and all(v in a["tide"] for v in nums)):
                    probs.append(f"{where}: range '{m.group().strip()}' is not a height range in FACTS")
                continue
        if (unit.startswith("kt") or unit.startswith("knot")) and m.group(2):
            if (nums[0], nums[1]) not in a["kpairs"] and not all(v in a["kt"] for v in nums):
                probs.append(f"{where}: wind range '{m.group().strip()}' is not in FACTS")
            continue
        for v in nums:
            ok = False
            if unit in ("ft", "feet", "foot"):
                ok = (v in a["surf"] or (tideish and v in a["tide"]) or (swellish and v in a["swell"])
                      or (nws_ok and v in a["nws"]))
                if not ok and v in a["swell"]:
                    probs.append(f"{where}: {v:g} ft is a swell height; label it swell/buoy, never as surf")
                    continue
                if not ok and v in a["tide"]:
                    ok = True       # tide heights in a sentence that names highs/lows loosely
            elif unit.startswith("kt") or unit.startswith("knot"):
                ok = v in a["kt"] or (nws_ok and v in a["nws"])
            elif unit in ("°f", "f"):
                ok = v in a["temp"] or (nws_ok and v in a["nws"])
            elif unit in ("°", "degrees"):
                ok = v in a["deg"] or (nws_ok and v in a["nws"]) or v in a["temp"]
            elif unit in ("s", "sec", "second", "seconds"):
                ok = v in a["sec"] or (nws_ok and v in a["nws"])
            else:
                allnums = set().union(*(a[k] for k in ("surf", "tide", "swell", "kt", "temp", "sec", "deg",
                                                       "nws", "count")))
                ok = v in allnums or v in (1, 2, 3, 4, 5) and bool(re.search(r"day", s, re.I))
            if not ok:
                probs.append(f"{where}: '{m.group().strip()}' is not in FACTS")
    return probs


# ── assembly ────────────────────────────────────────────────────────────────

def write_report(f: dict, use_claude: bool = True, client=None) -> dict:
    engine, rep, usage, tries, problems = "template", None, {"in": 0, "out": 0}, 0, []
    if use_claude and (client or os.environ.get("ANTHROPIC_API_KEY")) and not f["today"].get("noData"):
        fb = None
        for _ in range(2):
            tries += 1
            try:
                draft, u = claude_draft(f, client=client, feedback=fb)
            except Exception as e:  # noqa: BLE001 — any SDK/import problem: use the template
                log.warning("surf report: Claude call failed: %s", e)
                draft, u = None, {}
            usage = {k: usage[k] + u.get(k, 0) for k in usage}
            if draft is None:
                problems = ["no usable draft"]
                break
            problems = check(draft, f)
            if not problems:
                rep, engine = draft, MODEL
                break
            log.info("surf report: draft failed fact check: %s", problems)
            fb = problems
    if rep is None:
        rep = template(f)
        tp = check(rep, f)
        if tp:
            log.warning("surf report: template failed its own check: %s", tp)
    order = {n: i for i, n in enumerate(REGION_NAMES)}
    rep["regions"] = sorted(rep["regions"], key=lambda r: order.get(r["region"], 9))
    return {"engine": engine, "tries": tries, "usage": usage,
            "rejected": problems if engine == "template" and tries else [], **rep}


def _key(f: dict) -> str:
    """What changes the story: day covered, size, sets, rating, alerts."""
    t = f.get("today") or {}
    k = [f.get("reportDay"), f.get("covers"), (t.get("size") or {}).get("typicalFaceFt"),
         (t.get("size") or {}).get("biggestSetsFt"), t.get("rating"),
         [a.get("event") for a in (f.get("nws") or {}).get("alerts", [])]]
    return hashlib.sha1(json.dumps(k).encode()).hexdigest()[:12]


def build(now: datetime | None = None, use_claude: bool = True, client=None,
          surf: dict | None = None, spots: dict | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    surf = surf if surf is not None else load_json(SURF)
    if not surf:
        return None
    spots = spots if spots is not None else load_json(SPOTS)
    f = facts(surf, spots, now)
    r = write_report(f, use_claude=use_claude, client=client)
    return {"generatedAt": now.isoformat(timespec="minutes"), "dataAt": surf.get("generatedAt"),
            "staleAfterHours": 8, "key": _key(f), "reportDay": f["reportDay"], "covers": f["covers"],
            "note": "Written automatically from Surftracker's forecast and NWS data. "
                    "Surf heights are breaking face height.",
            **r, "facts": f}


def due(prev: dict | None, surf: dict | None, now: datetime) -> bool:
    if not prev or not surf:
        return True
    try:
        age_h = (now - _t(prev["generatedAt"])).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return True
    if age_h >= prev.get("staleAfterHours", 8) - 1:
        return True                                   # never let the page hide it
    try:
        f = facts(surf, load_json(SPOTS), now)
    except Exception:  # noqa: BLE001
        return True
    if _key(f) != prev.get("key"):
        return True                                   # day, size, sets, rating or alerts changed
    overnight = now.astimezone(LA).hour >= 21 or now.astimezone(LA).hour < 4
    return age_h >= REFRESH_H and not overnight


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--template", action="store_true", help="skip Claude")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    prev = load_json(args.out)
    if not args.force and not due(prev, load_json(SURF), now):
        print("surf_report.json: up to date")
        return 0
    use = not args.template and os.environ.get("SURF_REPORT_LLM", "1") != "0"
    rep = build(now, use_claude=use)
    if not rep:
        print("surf_report.json: no surf.json, nothing written")
        return 0
    args.out.write_text(json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"surf_report.json: {rep['engine']} ({rep['tries']} Claude tries, "
          f"{rep['usage']['in']} in / {rep['usage']['out']} out tokens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
