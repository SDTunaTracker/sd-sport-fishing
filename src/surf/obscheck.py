"""Score surf height (breaking face height) and rating against people's observations.

Standing rule: surf height means breaking face height at the beach, and
accuracy is judged against observed breaking surf. This harness is ready
for the City of San Diego lifeguard records (Surf Height, Surf Form) and
any other observation log in the same CSV shape:

    date,time,location,surf_lo_ft,surf_hi_ft,surf_form,source
    2025-09-14,08:00,La Jolla Shores,2,3,Fair,lifeguard

`time` (local, 24 h) is optional (08:00 is assumed: lifeguard morning
reports). `surf_form` (Good/Fair/Poor) and `source` are optional.

For each observation it recomputes OUR face height the way production does
(Battjes–Janssen profile × E8 spectral ratio × break cal, forecast.py), but
from the MOP nowcast/hindcast at that break and hour, so it scores the surf
step itself, not forecast lead time. It reports:
  - bias, RMSE, within 1 ft and within 1.5 ft, by height band, break, period band
  - an observer-scale fit (reported = a + b·ours) fit on the earliest 2/3 of
    dates and scored on the last 1/3, against a naive baseline (c × Hs10 fit
    the same way); adopt it only if it beats both on the held-out third
  - rating vs Surf Form: Spearman, confusion, share of "Good" we call >= 3

    python -m src.surf.obscheck path/to/records.csv [--out data/surf_verify/obscheck.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import cdip as C
from .breaks import BREAKS, BY_ID
from .physics import M_TO_FT, bj_profile, break_spectrum, break_wave, spectral_hs

PT = ZoneInfo("America/Los_Angeles")
# Lifeguard station / beach names -> our break ids (lower-case substring match).
LOCATIONS = {
    "oceanside harbor": "oceanside-harbor", "harbor beach": "oceanside-harbor",
    "oceanside": "oceanside-pier", "swami": "swamis", "moonlight": "swamis", "encinitas": "swamis",
    "cardiff": "cardiff-reef", "black": "blacks", "torrey": "blacks", "scripps": "scripps-pier",
    "la jolla shores": "la-jolla-shores", "shores": "la-jolla-shores", "windansea": "windansea",
    "la jolla": "windansea", "pacific beach": "pacific-beach", "crystal pier": "pacific-beach",
    "mission beach": "pacific-beach", "ocean beach": "ocean-beach", "sunset cliffs": "sunset-cliffs",
    "imperial beach": "imperial-beach",
}
FORMS = {"poor": 0, "fair": 1, "good": 2}
HEIGHT_BANDS = ((0, 2), (2, 4), (4, 6), (6, 100))
PERIOD_BANDS = ((0, 11), (11, 14), (14, 17), (17, 30))


def break_for(location: str) -> str | None:
    loc = location.strip().lower()
    if loc in BY_ID:
        return loc
    for key in sorted(LOCATIONS, key=len, reverse=True):
        if key in loc:
            return LOCATIONS[key]
    return None


def load_records(path: Path) -> list[dict]:
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            brk = break_for(r.get("location", ""))
            try:
                lo, hi = float(r["surf_lo_ft"]), float(r.get("surf_hi_ft") or r["surf_lo_ft"])
            except (KeyError, ValueError):
                continue
            if brk is None:
                continue
            tm = (r.get("time") or "08:00").strip() or "08:00"
            t = datetime.fromisoformat(f"{r['date'].strip()}T{tm}").replace(tzinfo=PT).astimezone(timezone.utc)
            form = (r.get("surf_form") or "").strip().lower()
            out.append({"t": t, "break": brk, "lo": lo, "hi": hi, "mid": (lo + hi) / 2,
                        "form": FORMS.get(form), "source": (r.get("source") or "").strip()})
    return out


def _spectrum_at(url: str, t: float) -> tuple[list, list, list, list] | None:
    times = C.parse_ascii(C._get(f"{url}.ascii?waveTime", 86400)).get("waveTime", [])
    if not times:
        return None
    i = min(range(len(times)), key=lambda k: abs(times[k] - t))
    if abs(times[i] - t) > 5400:
        return None
    meta = C.parse_ascii(C._get(f"{url}.ascii?waveFrequency,waveBandwidth", 7 * 86400))
    nf = len(meta["waveFrequency"]) - 1
    txt = C._get(f"{url}.ascii?waveEnergyDensity[{i}:1:{i}][0:1:{nf}],waveMeanDirection[{i}:1:{i}][0:1:{nf}],"
                 f"waveHs[{i}:1:{i}],waveTp[{i}:1:{i}],waveDp[{i}:1:{i}]", 30 * 86400)
    e, d = C.parse_grid(txt, "waveEnergyDensity"), C.parse_grid(txt, "waveMeanDirection")
    sc = C.parse_ascii(txt)
    if not e or not sc.get("waveHs"):
        return None
    return meta["waveFrequency"], meta["waveBandwidth"], (e[0], d[0]), (sc["waveHs"][0], sc["waveTp"][0], sc["waveDp"][0])


def our_face(brk: str, t: datetime) -> dict | None:
    """Production face height (ft, unscaled mid) from the MOP nowcast/hindcast at that hour."""
    from .forecast import SLOPE, mop_meta, nws_scale
    b = BY_ID[brk]
    normal, h1 = mop_meta(b["mop"])
    got = None
    for kind in ("nowcast", "hindcast"):
        try:
            got = _spectrum_at(C.mop_url(b["mop"], kind), t.timestamp())
        except Exception:  # noqa: BLE001
            got = None
        if got:
            break
    if not got:
        return None
    freqs, dfs, (E, D), (hs, tp, dp) = got
    m = spectral_hs(freqs, dfs, E)
    mono, _, _ = break_wave(hs, tp, dp, normal, h1, b["gamma"])
    e8 = 1.0
    if m > 0.05 and mono > 0 and hs < b["gamma"] * h1:
        hb_s, _ = break_spectrum(freqs, dfs, E, D, normal, h1, b["gamma"])
        e8 = hs * (hb_s / m) / mono
    hb = bj_profile(hs, tp, h1, SLOPE[b["type"]], dp, normal)[0] * e8
    h_ft = hb * b["cal"] * M_TO_FT
    h_ft *= nws_scale(h_ft)
    return {"ft": h_ft, "hs10Ft": hs * M_TO_FT, "tp": tp, "dp": dp}


def _stats(pairs: list[tuple[float, float]]) -> dict:
    if not pairs:
        return {"n": 0}
    e = [p - o for p, o in pairs]
    n = len(e)
    return {"n": n, "biasFt": round(sum(e) / n, 2), "rmseFt": round(math.sqrt(sum(x * x for x in e) / n), 2),
            "within1Ft": round(sum(abs(x) <= 1 for x in e) / n, 3),
            "within1_5Ft": round(sum(abs(x) <= 1.5 for x in e) / n, 3)}


def _ols(x: list[float], y: list[float]) -> tuple[float, float]:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx if sxx > 0 else 1.0
    return my - b * mx, b


def _ratio_fit(x: list[float], y: list[float]) -> float:
    d = sum(a * a for a in x)
    return sum(a * c for a, c in zip(x, y)) / d if d > 0 else 1.0


def _spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None

    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 3) if den else None


def evaluate(rows: list[dict]) -> dict:
    """rows: records joined with ours = {'ft','hs10Ft','tp'} and optional 'score' (0-5 rating)."""
    rows = [r for r in rows if r.get("ours")]
    rows.sort(key=lambda r: r["t"])
    out: dict = {"n": len(rows), "overall": _stats([(r["ours"]["ft"], r["mid"]) for r in rows])}
    out["byHeight"] = {f"{lo}-{hi} ft": _stats([(r["ours"]["ft"], r["mid"]) for r in rows if lo <= r["mid"] < hi])
                       for lo, hi in HEIGHT_BANDS}
    out["byPeriod"] = {f"{lo}-{hi} s": _stats([(r["ours"]["ft"], r["mid"]) for r in rows if lo <= r["ours"]["tp"] < hi])
                       for lo, hi in PERIOD_BANDS}
    out["byBreak"] = {b["id"]: _stats([(r["ours"]["ft"], r["mid"]) for r in rows if r["break"] == b["id"]])
                      for b in BREAKS if any(r["break"] == b["id"] for r in rows)}
    # Held-out observer-scale test: fit on the earliest 2/3 of dates, score the last 1/3.
    if len(rows) >= 30:
        cut = rows[int(len(rows) * 2 / 3)]["t"]
        tr, te = [r for r in rows if r["t"] < cut], [r for r in rows if r["t"] >= cut]
        a, b = _ols([r["ours"]["ft"] for r in tr], [r["mid"] for r in tr])
        c = _ratio_fit([r["ours"]["hs10Ft"] for r in tr], [r["mid"] for r in tr])
        out["heldOut"] = {
            "trainN": len(tr), "testN": len(te), "split": cut.isoformat(timespec="minutes"),
            "fit": {"a": round(a, 2), "b": round(b, 3), "naiveC": round(c, 3)},
            "current": _stats([(r["ours"]["ft"], r["mid"]) for r in te]),
            "observerScale": _stats([(a + b * r["ours"]["ft"], r["mid"]) for r in te]),
            "naiveHs10": _stats([(c * r["ours"]["hs10Ft"], r["mid"]) for r in te]),
        }
    rated = [r for r in rows if r.get("form") is not None and r.get("score") is not None]
    if rated:
        conf = {f"{k}": {} for k in FORMS}
        for r in rated:
            k = next(n for n, v in FORMS.items() if v == r["form"])
            band = "0-2" if r["score"] < 2 else "2-3" if r["score"] < 3 else "3+"
            conf[k][band] = conf[k].get(band, 0) + 1
        good = [r for r in rated if r["form"] == 2]
        out["rating"] = {"n": len(rated), "spearman": _spearman([r["score"] for r in rated], [r["form"] for r in rated]),
                         "confusion": conf,
                         "goodCalled3Plus": round(sum(r["score"] >= 3 for r in good) / len(good), 3) if good else None}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/surf_verify/obscheck.json"))
    a = ap.parse_args(argv)
    recs = load_records(a.csv)
    for r in recs:
        r["ours"] = our_face(r["break"], r["t"])
    res = evaluate(recs)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
