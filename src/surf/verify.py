"""Verification harness: CDIP MOP vs CDIP buoy observations, with baselines.

Truth: CDIP buoys (Hs, Tp, Dp; flag 1 only), averaged to hourly and smoothed
over 3 h (long-period swell is noisy in 1 h records; Crosby et al. 2016).

Model: MOP predicted AT the buoy site (MOP_validation BP{site}_{kind}.nc):
  nowcast   MOP driven by observed offshore buoys (lead 0: the transformation skill)
  ecmwf_fc  ECMWF-forced forecast; the archive is one spliced hourly series,
  forecast  WW3-forced forecast;   i.e. short lead (latest run per hour, lead
                                   not stored). Lead-resolved skill comes from
                                   our own run archive (src/surf/runs.py).

Baselines:
  persistence_L  obs(t - L) as the forecast for obs(t), L = 3..72 h
  shoal          offshore buoy (CDIP 067 San Nicolas Island) Hs, linearly
                 shoaled to the site depth, no refraction or island sheltering
                 (the naive "no MOP" baseline from the design note)

Split (fixed, time-ordered; never tune on TEST):
  TRAIN 2022-04-01 .. 2025-03-31     TEST 2025-04-01 .. now

    python -m src.surf.verify            # full report -> data/surf_verify/latest.json + stdout markdown
    python -m src.surf.verify --sites 201,153
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import cdip as C
from .physics import shoal_hs

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "surf_verify"

START = datetime(2022, 4, 1, tzinfo=timezone.utc)
SPLIT = pd.Timestamp("2025-04-01", tz="UTC")
# San Diego nearshore and offshore validation buoys (CDIP station ids).
SITES = {
    "264": "Red Beach Nearshore", "045": "Oceanside Offshore", "262": "Leucadia Nearshore",
    "153": "Del Mar Nearshore", "100": "Torrey Pines Outer", "201": "Scripps Nearshore",
    "220": "Mission Bay West", "191": "Point Loma South",
}
NEARSHORE = {"264", "262", "153", "201"}
OFFSHORE_REF = "067"          # San Nicolas Island, open ocean
LAGS = (3, 6, 12, 24, 48, 72)
VARS = ["waveHs", "waveTp", "waveDp", "waveFlagPrimary"]


def _frame(d: dict) -> pd.DataFrame:
    if not d.get("waveTime"):
        return pd.DataFrame(columns=["hs", "tp", "dp"])
    df = pd.DataFrame({"hs": d["waveHs"], "tp": d["waveTp"], "dp": d["waveDp"],
                       "flag": d["waveFlagPrimary"]},
                      index=pd.to_datetime(d["waveTime"], unit="s", utc=True))
    df = df[df["flag"] == 1].drop(columns="flag")
    df = df[(df["hs"] > 0) & (df["hs"] < 20)]
    return df[~df.index.duplicated()]


def _hourly(df: pd.DataFrame, smooth_h: int = 3) -> pd.DataFrame:
    """Hourly means (direction via unit vectors), then a centered rolling mean."""
    if df.empty:
        return df
    rad = np.deg2rad(df["dp"])
    tmp = pd.DataFrame({"hs": df["hs"], "tp": df["tp"], "u": np.sin(rad), "v": np.cos(rad)})
    h = tmp.resample("1h").mean()
    if smooth_h > 1:
        h = h.rolling(smooth_h, center=True, min_periods=1).mean()
    h["dp"] = (np.rad2deg(np.arctan2(h["u"], h["v"])) + 360) % 360
    return h[["hs", "tp", "dp"]].dropna()


def load_obs(station: str, smooth_h: int = 3) -> pd.DataFrame:
    parts = []
    for url in C.buoy_urls(station):
        try:
            parts.append(_frame(C.series(url, VARS, since=START, max_age_s=12 * 3600)))
        except FileNotFoundError:
            pass
    df = pd.concat(parts).sort_index() if parts else pd.DataFrame(columns=["hs", "tp", "dp"])
    return _hourly(df[~df.index.duplicated(keep="last")], smooth_h)


def load_model(site: str, kind: str) -> pd.DataFrame:
    try:
        d = C.series(C.validation_url(site, kind), VARS, since=START, max_age_s=12 * 3600)
    except FileNotFoundError:
        return pd.DataFrame(columns=["hs", "tp", "dp"])
    return _hourly(_frame(d), smooth_h=1)


def site_depth(station: str) -> float | None:
    """Buoy water depth (m) from the realtime file's metaWaterDepth scalar."""
    import re
    txt = C._get(C.buoy_urls(station)[-1] + ".ascii?metaWaterDepth", 7 * 86400)
    m = re.search(r"^metaWaterDepth, ([\d.]+)", txt, re.M)
    return float(m.group(1)) if m and float(m.group(1)) > 0 else None


# ── metrics ─────────────────────────────────────────────────────────────────

def _angdiff(a, b):
    return (np.asarray(a) - np.asarray(b) + 180) % 360 - 180


def metrics(f: pd.Series, o: pd.Series, circular: bool = False) -> dict:
    j = pd.concat([f.rename("f"), o.rename("o")], axis=1).dropna()
    n = len(j)
    if n < 24:
        return {"n": n}
    e = _angdiff(j["f"], j["o"]) if circular else (j["f"] - j["o"]).to_numpy()
    out = {"n": n, "bias": float(np.mean(e)), "rmse": float(np.sqrt(np.mean(e ** 2))),
           "mae": float(np.mean(np.abs(e)))}
    if not circular:
        out["si"] = float(np.std(e) / np.mean(j["o"])) if np.mean(j["o"]) else None
        out["r"] = float(np.corrcoef(j["f"], j["o"])[0, 1])
    return out


def skill(mse_f: float, mse_ref: float) -> float | None:
    return None if not mse_ref else 1 - mse_f / mse_ref


def _split(df):
    return df[df.index < SPLIT], df[df.index >= SPLIT]


def evaluate_site(station: str, offshore: pd.DataFrame | None, smooth_h: int = 3) -> dict:
    obs = load_obs(station, smooth_h)
    res: dict = {"station": station, "name": SITES.get(station, station), "nObs": len(obs)}
    if obs.empty:
        return res
    cands: dict[str, pd.DataFrame] = {k: load_model(station, k) for k in ("nowcast", "ecmwf_fc", "forecast")}
    for L in LAGS:
        p = obs.copy()
        p.index = p.index + pd.Timedelta(hours=L)
        cands[f"persist_{L}h"] = p
    depth = site_depth(station)
    res["depth_m"] = depth
    if offshore is not None and not offshore.empty and depth:
        sh = offshore.copy()
        sh["hs"] = [shoal_hs(h, t, depth) for h, t in zip(sh["hs"], sh["tp"])]
        cands["shoal_067"] = sh
    for part, o in zip(("train", "test"), _split(obs)):
        block = {}
        for name, f in cands.items():
            if f.empty:
                continue
            fo = f.reindex(o.index)
            block[name] = {"hs": metrics(fo["hs"], o["hs"]), "tp": metrics(fo["tp"], o["tp"]),
                           "dp": metrics(fo["dp"], o["dp"], circular=True)}
        # Skill vs persistence (same timestamps) for Hs.
        for name, m in block.items():
            for L in LAGS:
                ref = block.get(f"persist_{L}h", {}).get("hs", {})
                if "rmse" in m["hs"] and ref.get("rmse"):
                    m["hs"][f"ss_vs_p{L}"] = skill(m["hs"]["rmse"] ** 2, ref["rmse"] ** 2)
        res[part] = block
    return res


def run(sites: list[str], smooth_h: int = 3) -> dict:
    off = load_obs(OFFSHORE_REF, smooth_h)
    out = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "split": str(SPLIT.date()), "smoothH": smooth_h, "offshoreRef": OFFSHORE_REF,
           "sites": [evaluate_site(s, off, smooth_h) for s in sites]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "latest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def _f(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def markdown(res: dict, part: str = "test", models=("nowcast", "ecmwf_fc", "forecast", "shoal_067",
                                                     "persist_6h", "persist_24h")) -> str:
    rows = ["| Site | Model | n | Hs bias m | Hs RMSE m | Hs SI | Hs r | SS vs persist 24h | Tp RMSE s | Dp RMSE ° |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for s in res["sites"]:
        blk = s.get(part, {})
        for m in models:
            if m not in blk:
                continue
            hs, tp, dp = blk[m]["hs"], blk[m]["tp"], blk[m]["dp"]
            rows.append(f"| {s['station']} {s['name']} | {m} | {hs.get('n', 0)} | {_f(hs.get('bias'))} | "
                        f"{_f(hs.get('rmse'))} | {_f(hs.get('si'))} | {_f(hs.get('r'))} | "
                        f"{_f(hs.get('ss_vs_p24'))} | {_f(tp.get('rmse'), 1)} | {_f(dp.get('rmse'), 0)} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", default=",".join(SITES))
    ap.add_argument("--smooth", type=int, default=3)
    ap.add_argument("--part", default="test", choices=("train", "test"))
    a = ap.parse_args(argv)
    res = run(a.sites.split(","), a.smooth)
    print(markdown(res, a.part))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
