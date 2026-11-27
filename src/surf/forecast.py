"""San Diego surf forecast -> web/api/v1/surf.json (a MODEL forecast).

Per break (src/surf/breaks.py), every 3 h for ~6 days:
  1. MOP at the break's point: ECMWF-forced (primary) and WW3-forced, blended
     with per-site scale factors from calibration.json (experiment E3,
     verified on held-out buoy data; see surf-accuracy-log.md). Past the
     ECMWF horizon, WW3 alone (scaled), flagged low confidence.
  2. Smooth Hs/Tp over ~12 h (5 steps) before the breaking step.
  3. Breaking step: each band of the MOP spectrum shoaled + refracted with
     its own frequency and direction from the MOP depth (~10 m) until
     Hm0 >= γ·h (physics.break_spectrum, experiment E8); bulk Hs/Tp
     (physics.break_wave) only without a spectrum. Round 4: breaking height
     is the Battjes–Janssen random-wave max Hs (E12) × the spectral/bulk
     ratio (E8); face range 0.85–1.15 × that (no scale, round 6), in feet.
     Komar–Gaughan is reported as a cross-check.
  4. Wind: Open-Meteo hourly 10 m wind, ECMWF IFS 0.25° (round 7: best of four
     models against the Scripps Pier anemometer); `gfs_seamless` as fallback.
  5. Tide: NOAA CO-OPS 9410230 La Jolla, hourly predictions + highs/lows.
  6. Rating 0–5 (methods note §5), capped at the break's potential and at
     FAIR–GOOD (3.74): a model can't call GOOD or EPIC without an observation.
Plus NWS Surf Zone Forecast (SRFSGX, San Diego County CAZ043) verbatim: rip
current risk, surf height, headlines.

Never claim accuracy beyond the buoy-verified numbers in the payload's
"verification" block. Face height and rating are unverified model estimates
until surf observations exist.

    python -m src.surf.forecast            # write web/api/v1/surf.json
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import cdip as C
from .breaks import BREAKS
from .extras import enrich
from .physics import (M_TO_FT, bj_profile, break_spectrum, break_wave, deep_water_height,
                      komar_gaughan, spectral_hs)

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "api" / "v1" / "surf.json"
CAL = json.loads(Path(__file__).with_name("calibration.json").read_text(encoding="utf-8"))
UA = C.UA
TIDE_STATION = "9410230"
# Face range around the breaking-wave height H (E9: no 1.27 "sets" multiplier
# on the top; sets are mentioned in words instead).
RANGE = (0.85, 1.15)
# Breaking: Battjes–Janssen random-wave energy balance on a plane slope (E12),
# slope by break type [D], scaled by the E8 spectral/bulk ratio.
SLOPE = {"beach": 1 / 50, "reef": 1 / 30, "shores": 1 / 50}
# No height scale (round 6). Round 5 scaled small days down to the NWS Surf
# Zone Forecast scale; the Scripps Pier pressure sensor (CDIP 073, ~6.5 m,
# 1,538 small mornings) showed that scaled heights fell BELOW the measured
# pre-breaking Hs on 88% of days, so NWS's small-day numbers are conservative,
# not truth. Unscaled heights match lifeguard high-surf reports (0.99) and sit
# 1.13x the pier Hs on small days (rank correlation 0.94).
def nws_scale(h_ft: float) -> float:
    return 1.0
MODEL_CEILING = 3.74         # top of FAIR–GOOD
STEP_H = 3
SMOOTH_STEPS = 5             # ≈ 12 h centered at 3-hourly steps

# Held-out (TEST 2025-04..2025-11) Hs scores at the buoys, from surf-accuracy-log.md
# round 1. Short-lead only; lead-resolved scores come from src/surf/runs.py.
VERIFICATION = {
    "what": "Wave height (Hs) at the CDIP buoys, MOP blend vs buoy observations",
    "testPeriod": "2025-04-01 to 2026-11-26 (held out; never used for tuning)",
    "hsRmseM": {"rawEcmwf": 0.136, "blend": 0.126},
    "beats": ["24 h persistence at all 8 buoys", "plain shoaling without island sheltering (RMSE ~1 m)"],
    "notVerified": "Face height and rating: no surf observations yet. Treat them as model estimates.",
    "scale": "On small days our heights run about 20% above NWS surf forecasts; the Scripps Pier "
             "wave sensor supports ours.",
    "observed": "Big days: 56 lifeguard and official high-surf reports (NWS storm reports, 2016–2026) "
                "matched our heights (median ratio 0.99; we reached at least 80% of the reported size "
                "on 93%). Small days: our heights track the Scripps Pier wave sensor (CDIP 073) "
                "closely over 1,538 small mornings (rank correlation 0.94). Small-day face heights "
                "are not yet checked against people's observations.",
    "leadNote": "Scores are short-lead. Skill by forecast day is being collected.",
    "wind": "Wind model chosen against the Scripps Pier anemometer (NOAA LJPC1): over 2026 "
            "mornings it got the wind type (glassy, offshore, cross or onshore) right about two "
            "times in three, with a typical speed error of 2.6 kt. Wind at other breaks is not "
            "checked.",
}

LABELS = ((0.5, "FLAT"), (1.5, "POOR"), (2.25, "POOR–FAIR"), (3.0, "FAIR"), (3.75, "FAIR–GOOD"),
          (4.5, "GOOD"), (99, "EPIC"))
HEIGHT_TRAP = {"beach": (1.5, 3, 6, 10), "reef": (2, 4, 8, 12), "shores": (1, 2, 4, 6)}
# Range widening by lead [D]: none for days 0–2, then ±10%, then ±20%.
LEAD_SI = ((48, 0.0), (120, 0.10), (10 ** 6, 0.20))


def _get_json(url, params=None, timeout=40, attempts=3):
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers={"User-Agent": UA, "Accept": "application/json"},
                             timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            import time
            time.sleep(4 * (i + 1))
    raise last


def _angdiff(a: float, b: float) -> float:
    return (a - b + 180) % 360 - 180


# ── inputs ──────────────────────────────────────────────────────────────────

def mop_meta(point: str) -> tuple[float, float]:
    txt = C._get(C.mop_url(point, "ecmwf_fc") + ".ascii?metaShoreNormal,metaWaterDepth", 7 * 86400)
    n = re.search(r"^metaShoreNormal, ([-\d.]+)", txt, re.M)
    d = re.search(r"^metaWaterDepth, ([-\d.]+)", txt, re.M)
    return float(n.group(1)), float(d.group(1))


def mop_series(point: str, kind: str, since: datetime) -> dict[int, tuple[float, float, float]]:
    d = C.series(C.mop_url(point, kind), ["waveHs", "waveTp", "waveDp", "waveFlagPrimary"],
                 since=since, max_age_s=1800)
    return {int(t): (hs, tp, dp) for t, hs, tp, dp, fl in
            zip(d["waveTime"], d["waveHs"], d["waveTp"], d["waveDp"], d["waveFlagPrimary"])
            if fl == 1 and 0 < hs < 20}


# Round 7 (B5-1): vs NDBC LJPC1, TEST 2026 dawn hours, ECMWF IFS 0.25° got the
# rating's wind category right 66% of the time vs 55% for gfs_seamless (chosen on
# 2025 TRAIN, better in 22 of 23 months). Fallback keeps the page up if it fails.
WIND_MODELS = ("ecmwf_ifs025", "gfs_seamless")


def wind_hourly(breaks: list[dict]) -> list[dict[int, tuple[float, float, float]]]:
    """Per break {epoch hour: (speed kt, from deg, gust kt)} from Open-Meteo."""
    last = None
    for model in WIND_MODELS:
        try:
            out = _wind_hourly(breaks, model)
            if any(out):
                return out
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("surf wind %s failed: %s", model, e)
    if last:
        raise last
    return [{} for _ in breaks]


def _wind_hourly(breaks: list[dict], model: str) -> list[dict[int, tuple[float, float, float]]]:
    js = _get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": ",".join(str(b["lat"]) for b in breaks),
        "longitude": ",".join(str(b["lon"]) for b in breaks),
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kn", "timezone": "GMT", "forecast_days": 7, "past_days": 1,
        "models": model,
    })
    js = js if isinstance(js, list) else [js]
    out = []
    for loc in js:
        h = loc.get("hourly", {})
        m = {}
        for t, s, d, g in zip(h.get("time", []), h.get("wind_speed_10m", []),
                              h.get("wind_direction_10m", []), h.get("wind_gusts_10m", [])):
            if s is None or d is None:
                continue
            ep = int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp())
            m[ep] = (float(s), float(d), float(g) if g is not None else None)
        out.append(m)
    return out


def tides(start: datetime, days: int = 7) -> tuple[dict[int, float], list[dict]]:
    base = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    common = {"product": "predictions", "application": "Tunatracker", "station": TIDE_STATION,
              "begin_date": start.strftime("%Y%m%d"), "range": 24 * (days + 1), "datum": "MLLW",
              "time_zone": "gmt", "units": "english", "format": "json"}
    hourly = {}
    for p in _get_json(base, {**common, "interval": "h"}).get("predictions", []):
        ep = int(datetime.strptime(p["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())
        hourly[ep] = float(p["v"])
    hilo = [{"t": datetime.strptime(p["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
             .isoformat(timespec="minutes"), "ft": round(float(p["v"]), 1), "type": p.get("type")}
            for p in _get_json(base, {**common, "interval": "hilo"}).get("predictions", [])]
    return hourly, hilo


def nws_surf_zone() -> dict | None:
    """Latest NWS Surf Zone Forecast, San Diego County Coastal Areas (CAZ043)."""
    lst = _get_json("https://api.weather.gov/products/types/SRF/locations/SGX")
    pid = (lst.get("@graph") or [{}])[0].get("id")
    if not pid:
        return None
    p = _get_json(f"https://api.weather.gov/products/{pid}")
    return parse_srf(p.get("productText", ""), p.get("issuanceTime"))


def parse_srf(text: str, issued: str | None = None) -> dict | None:
    i = text.find("San Diego County Coastal Areas")
    if i < 0:
        return None
    block = text[i:text.find("$$", i) if "$$" in text[i:] else len(text)]
    heads = [h.strip(". ").capitalize() for h in re.findall(r"^\.\.\.(.+?)\.\.\.\s*$", block, re.M)]
    periods = []
    for m in re.finditer(r"^\.([A-Z][A-Z ]+?)\.\.\.\s*$(.*?)(?=^\.[A-Z][A-Z ]+?\.\.\.\s*$|^&&|\Z)",
                         block, re.M | re.S):
        body = m.group(2)

        def field(name):
            f = re.search(rf"^{name}[^.]*\.+\s*(.+?)(?=^\S[^\n]*\.{{3,}}|\Z)", body, re.M | re.S)
            return re.sub(r"\s+", " ", f.group(1)).strip().rstrip(".") if f else None
        periods.append({"name": m.group(1).title(), "ripRisk": field("Rip Current Risk"),
                        "surf": field("Surf Height"), "water": field("Water Temperature"),
                        "remarks": field("Remarks")})
    return {"source": "NWS San Diego Surf Zone Forecast", "zone": "CAZ043", "issued": issued,
            "headlines": heads, "periods": periods}


def buoy_now(station: str) -> dict | None:
    d = C.series(C.buoy_urls(station)[-1], ["waveHs", "waveTp", "waveDp", "waveFlagPrimary"],
                 since=datetime.now(timezone.utc) - timedelta(hours=3), max_age_s=1200)
    ok = [(t, h, p, dd) for t, h, p, dd, f in zip(d["waveTime"], d["waveHs"], d["waveTp"],
                                                   d["waveDp"], d["waveFlagPrimary"]) if f == 1]
    if not ok:
        return None
    t, h, p, dd = ok[-1]
    return {"station": station, "t": C.to_iso(t), "hsFt": round(h * M_TO_FT, 1),
            "tpS": round(p, 1), "dpDeg": round(dd)}


# ── rating ──────────────────────────────────────────────────────────────────

def _trap(x, a, b, c, d):
    if x <= a or x >= d:
        return 0.0
    if x < b:
        return (x - a) / (b - a)
    if x <= c:
        return 1.0
    return (d - x) / (d - c)


def wind_score(speed: float | None, wfrom: float | None, normal: float) -> tuple[float, str]:
    if speed is None or wfrom is None:
        return 0.7, "unknown"
    if speed < 4:
        return 1.0, "glassy"
    rel = abs(_angdiff(wfrom, normal + 180))     # 0 = straight offshore
    if rel <= 45:
        return (1.0 if speed <= 15 else 0.7 if speed <= 25 else 0.4), "offshore"
    if rel < 135:
        return max(0.1, 1.0 - 0.08 * max(0.0, speed - 8)), "cross"
    on = speed * math.cos(math.radians(180 - rel))
    if on < 6:
        return 0.8, "light onshore"
    if on < 8:
        return 0.6, "bumpy"
    if on < 12:
        return 0.3, "onshore"
    return 0.1, "blown out"


def tide_score(ft: float | None, window: tuple[float, float]) -> float:
    if ft is None:
        return 0.7
    lo, hi = window
    if lo <= ft <= hi:
        return 1.0
    off = lo - ft if ft < lo else ft - hi
    return max(0.0, 1 - off / 1.5)


def rate(face_mid_ft: float, tp: float, dp: float, wind: tuple, tide_ft: float | None, b: dict,
         normal: float) -> dict:
    sh = _trap(face_mid_ft, *HEIGHT_TRAP[b["type"]])
    sw, wtype = wind_score(wind[0], wind[1], normal)
    st = tide_score(tide_ft, b["tide"])
    sp = min(1.0, max(0.0, (tp - 6) / 7)) if tp else 0.0
    lo, hi = b["swell"]
    c, half = (lo + hi) / 2, (hi - lo) / 2
    dd = abs(_angdiff(dp, c)) if dp is not None else 999
    sd = math.cos(math.pi / 2 * dd / half) if dd < half else 0.0
    score = 5 * math.sqrt(sh) * (0.4 * sw + 0.2 * st + 0.2 * sp + 0.2 * sd) if sh > 0 else 0.0
    score = min(score, b.get("potential", 5.0), MODEL_CEILING)
    label = next(l for t, l in LABELS if score < t)
    out = {"score": round(score, 1), "label": label, "windType": wtype}
    if sw <= 0.3 and sh > 0:
        out["faded"] = True
    return out


def body_band(ft: float) -> str:
    for lim, band in ((1, "flat"), (2, "ankle–knee"), (3, "knee–waist"), (4, "waist–chest"),
                      (5, "chest–shoulder"), (6, "head high"), (8, "overhead")):
        if ft < lim:
            return band
    return "well overhead"


# ── assembly ────────────────────────────────────────────────────────────────

def _smooth(vals: list[float | None], n: int) -> list[float | None]:
    out, k = [], n // 2
    for i in range(len(vals)):
        w = [v for v in vals[max(0, i - k):i + k + 1] if v is not None]
        out.append(sum(w) / len(w) if w else None)
    return out


def breaking_ratios(point: str, kind: str, since: datetime, normal: float, h1: float,
                    gamma: float) -> dict[int, float]:
    """{time: Hb / Hm0} from the MOP spectrum (E8: each band shoaled and
    refracted with its own frequency and direction). Applied to the
    bias-corrected Hs, so the correction and the breaking step stay separate."""
    s = C.spectra(C.mop_url(point, kind), since=since)
    out = {}
    for i, t in enumerate(s.get("waveTime", [])):
        if i >= len(s["waveEnergyDensity"]) or (s["waveFlagPrimary"] and s["waveFlagPrimary"][i] != 1):
            continue
        E, D = s["waveEnergyDensity"][i], s["waveMeanDirection"][i]
        m = spectral_hs(s["waveFrequency"], s["waveBandwidth"], E)
        if m <= 0.05:
            continue
        hb, _ = break_spectrum(s["waveFrequency"], s["waveBandwidth"], E, D, normal, h1, gamma)
        out[int(t)] = hb / m
    return out


def break_forecast(b: dict, wind: dict, tide_h: dict, now: datetime) -> dict:
    normal, h1 = mop_meta(b["mop"])
    since = now - timedelta(hours=3)
    ec, ww = mop_series(b["mop"], "ecmwf_fc", since), mop_series(b["mop"], "forecast", since)
    cal = CAL["sites"].get(b["buoy"], {"a_ec": 1.0, "a_ww": 1.25, "w_ec": 1.0})
    ratios: dict[int, float] = {}
    for kind in ("forecast", "ecmwf_fc"):            # ECMWF wins where both exist
        try:
            ratios.update(breaking_ratios(b["mop"], kind, since, normal, h1, b["gamma"]))
        except Exception as e:  # noqa: BLE001 — fall back to the bulk step
            log.info("surf spectrum %s %s failed: %s", b["mop"], kind, e)
    steps = sorted(set(ec) | set(ww))
    hs_l, tp_l, dp_l, src_l, dis_l = [], [], [], [], []
    for t in steps:
        e, w = ec.get(t), ww.get(t)
        if e and w:
            hs = cal["w_ec"] * cal["a_ec"] * e[0] + (1 - cal["w_ec"]) * cal["a_ww"] * w[0]
            tp, dp, src = e[1], e[2], "blend"
            dis = abs(cal["a_ec"] * e[0] - cal["a_ww"] * w[0]) / max(0.1, hs) > 0.3
        elif e:
            hs, tp, dp, src, dis = cal["a_ec"] * e[0], e[1], e[2], "ecmwf", False
        else:
            hs, tp, dp, src, dis = cal["a_ww"] * w[0], w[1], w[2], "ww3", False
        hs_l.append(hs), tp_l.append(tp), dp_l.append(dp), src_l.append(src), dis_l.append(dis)
    hs_s, tp_s = _smooth(hs_l, SMOOTH_STEPS), _smooth(tp_l, SMOOTH_STEPS)
    hours = []
    for i, t in enumerate(steps):
        hs, tp, dp = hs_s[i], tp_s[i], dp_l[i]
        mono, _, _ = break_wave(hs, tp, dp, normal, h1, b["gamma"])
        r = ratios.get(t)
        e8 = (hs * r / mono) if (r is not None and mono > 0 and hs < b["gamma"] * h1) else 1.0
        hb = bj_profile(hs, tp, h1, SLOPE[b["type"]], dp, normal)[0] * e8   # E12 × E8
        lead = (t - now.timestamp()) / 3600
        si = next(v for lim, v in LEAD_SI if lead < lim)
        h_ft = hb * b["cal"] * M_TO_FT
        h_ft *= nws_scale(h_ft)
        lo_ft = h_ft * RANGE[0] * (1 - si)
        hi_ft = h_ft * RANGE[1] * (1 + si)
        hour = t - t % 3600
        wnd = wind.get(hour, (None, None, None))
        tide_ft = tide_h.get(hour)
        r = rate((lo_ft + hi_ft) / 2, tp, dp, wnd, tide_ft, b, normal)
        kg = komar_gaughan(deep_water_height(hs, tp, h1), tp) if hb > 0 else 0.0
        row = {
            "t": C.to_iso(t),
            "faceFt": [max(0, math.floor(lo_ft)), max(0, math.ceil(hi_ft))],
            "hsM": round(hs, 2), "tpS": round(tp, 1), "dpDeg": round(dp),
            "hbM": round(hb, 2), "kgM": round(kg, 2),
            "windKt": None if wnd[0] is None else round(wnd[0]),
            "windFrom": None if wnd[1] is None else round(wnd[1]),
            "tideFt": None if tide_ft is None else round(tide_ft, 1),
            "conf": "high" if lead < 48 else "medium" if lead < 120 else "low", **r,
        }
        if src_l[i] != "blend":
            row["src"] = src_l[i]
        if dis_l[i]:
            row["modelsDisagree"] = True
        hours.append(row)
    return {"id": b["id"], "name": b["name"], "lat": b["lat"], "lon": b["lon"], "type": b["type"],
            "mop": b["mop"], "shoreNormal": round(normal, 1), "mopDepthM": round(h1, 1),
            "buoy": b["buoy"], "hours": hours}


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        winds = wind_hourly(BREAKS)
    except Exception as e:  # noqa: BLE001
        log.warning("surf wind failed: %s", e)
        winds = [{} for _ in BREAKS]
    try:
        tide_h, hilo = tides(now - timedelta(days=1))
    except Exception as e:  # noqa: BLE001
        log.warning("surf tides failed: %s", e)
        tide_h, hilo = {}, []
    breaks = []
    for b, w in zip(BREAKS, winds):
        try:
            breaks.append(break_forecast(b, w, tide_h, now))
        except Exception as e:  # noqa: BLE001
            log.warning("surf break %s failed: %s", b["id"], e)
    try:
        srf = nws_surf_zone()
    except Exception as e:  # noqa: BLE001
        log.warning("NWS SRF failed: %s", e)
        srf = None
    buoys = {}
    for s in sorted({b["buoy"] for b in BREAKS}):
        try:
            buoys[s] = buoy_now(s)
        except Exception:  # noqa: BLE001
            buoys[s] = None
    return enrich({
        "generatedAt": now.isoformat(timespec="minutes"), "staleAfterHours": 12,
        "label": "Model forecast",
        "method": "CDIP MOP nearshore wave model (ECMWF and WW3 forced, blended and bias-corrected at the "
                  "buoys), then a random-wave shoaling and breaking model (Battjes–Janssen) from the "
                  "model's 10 m point to the beach, using each swell's own period and direction. "
                  "Wind: ECMWF IFS via Open-Meteo. "
                  "Tide: NOAA La Jolla 9410230.",
        "credits": [C.CREDIT, "Wind: Open-Meteo.com (CC BY 4.0), ECMWF IFS open data (CC BY 4.0)",
                    "Tides: NOAA CO-OPS", "Surf Zone Forecast: National Weather Service San Diego"],
        "verification": VERIFICATION, "breaks": breaks,
        "tides": {"station": TIDE_STATION, "name": "La Jolla", "hilo": hilo},
        "nws": srf, "buoys": buoys,
    }, tide_h, now)   # extras.py: display-only fields


def write(path: Path = OUT) -> int:
    payload = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return len(payload["breaks"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"surf.json: {write()} breaks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
