"""Daily FACTOR REPORT CARD for San Diego tuna (user request 2026-11-25).

For each daily factor on the FISHING DAY (actual conditions = best case for a perfect forecast):
  raw   : Spearman(factor, fleet tuna per angler-day) over SD trip-type x fishing-day cells
  season: same, tuna season only (Jun-Nov)
  partial: after removing what we already know (trip type, season climatology, recent fleet tuna
           rate as of the day before, boat-mix) from BOTH sides, rank correlation of the residuals
  effect: adjusted tuna rate in the factor's top vs bottom fifth (ratio)
CI: 14-day block bootstrap (cells are autocorrelated). Multiple testing: Benjamini-Hochberg q.
Fishing day alignment: `dep` = first fishing day (counts are dated by return day; LOG E8h).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import rankdata

import build_dataset as BD
from harness import HERE
from run_tuna import build

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
rng = np.random.default_rng(0)


def moon(days):
    jd = days.to_julian_date().to_numpy()
    age = (jd - 2451550.1) % 29.530588853
    illum = (1 - np.cos(2 * np.pi * age / 29.530588853)) / 2
    return pd.DataFrame({"moon_illum": illum, "days_from_full": np.abs(age - 14.77),
                         "days_from_new": np.minimum(age, 29.53 - age)}, index=days)


def tides(days):
    rows = []
    for f in sorted((HERE / "data/ext/tides").glob("hilo_*.json")):
        rows += json.loads(f.read_text())["predictions"]
    t = pd.DataFrame(rows); t["t"] = pd.to_datetime(t.t); t["v"] = t.v.astype(float); t = t.set_index("t").sort_index()
    day = t.groupby(t.index.normalize()).v.agg(["max", "min"])
    out = pd.DataFrame(index=days)
    out["tide_range"] = (day["max"] - day["min"]).reindex(days)
    # tidal movement during fishing hours 05-12: interpolate hourly, sum |change|
    hr = t.v.resample("1h").interpolate("cubic") if False else t.v.resample("1h").mean().interpolate("time")
    am = hr.between_time("05:00", "12:00")
    out["tide_move_am"] = am.diff().abs().groupby(am.index.normalize()).sum().reindex(days)
    hh = t[t.type == "H"].groupby(t[t.type == "H"].index.normalize()).v.max()
    out["high_tide_ft"] = hh.reindex(days)
    return out


def conditions(days):
    c = sqlite3.connect(f"file:{(HERE / 'data/tracker_snapshot.db').as_posix()}?mode=ro", uri=True)
    h = BD.conditions(c)
    raw = pd.read_sql("select date, current_speed_knots, current_is_favorable, eddy_detected from historical_conditions", c)
    c.close()
    raw["date"] = pd.to_datetime(raw.date); raw = raw.groupby("date").mean(numeric_only=True)
    h = h.join(raw, how="left")
    h["wind_change_3d"] = h.wind_speed - h.wind_speed.shift(1).rolling(3).mean()
    h["pressure_change_24h"] = h.pressure - h.pressure.shift(1)
    h["swell_change_3d"] = h.swell_height - h.swell_height.shift(1).rolling(3).mean()
    h["sst_change_3d"] = h.sst_offshore - h.sst_offshore.shift(3)
    h["wind_dir_sin"] = np.sin(np.deg2rad(h.wind_direction_deg)); h["wind_dir_cos"] = np.cos(np.deg2rad(h.wind_direction_deg))
    keep = ["wind_speed", "wind_change_3d", "wind_dir_sin", "wind_dir_cos", "wind_is_upwelling", "wind_is_offshore",
            "swell_height", "swell_period", "swell_change_3d", "pressure", "pressure_trend", "pressure_change_24h",
            "sst_offshore", "sst_9mile", "sst_nearshore", "sst_anomaly", "sst_gradient", "sst_warming_trend",
            "sst_offshore_d7", "sst_offshore_d30", "sst_change_3d", "upw", "upw30",
            "current_speed_knots", "current_is_favorable", "eddy_detected"]
    out = h[keep].reindex(days)
    mur = pd.read_pickle(HERE / "data/ext/mur_daily.pkl")
    mur.columns = [f"mur_{c}" for c in mur.columns]
    return out.join(mur.reindex(days))


GROUPS = {"wind": "Wind & weather", "swell": "Swell", "pressure": "Pressure", "sst": "Sea temperature", "mur": "Satellite SST / fronts",
          "upw": "Upwelling", "current": "Currents", "eddy": "Currents", "moon": "Moon", "days": "Moon", "tide": "Tides", "high": "Tides"}


def main():
    d = build(1)  # SD trips with tuna target and lead-1 knowable features
    cells = d.groupby(["tlb", "dep"]).agg(tuna=("tuna", "sum"), ad=("ad", "sum"), n=("tuna", "size"),
                                          tclim=("tclim", "mean"), mom=("ft_tlb_h5", "mean"), mom15=("ft_tlb_h15", "mean"),
                                          boat=("bt_exp", "mean")).reset_index()
    cells = cells[(cells.ad >= 10) & cells.tclim.notna() & cells.mom.notna()].copy()
    cells["obs"] = cells.tuna / cells.ad
    cells["ly"] = np.log1p(cells.obs)
    days = pd.DatetimeIndex(sorted(cells.dep.unique()))
    F = conditions(days).join(moon(days)).join(tides(days))
    cells = cells.join(F, on="dep")
    cells["doy"] = cells.dep.dt.dayofyear
    # what we already know: trip type, seasonal climatology, recent fleet rate, boat mix
    def design(x):
        X = pd.get_dummies(x.tlb, prefix="t", dtype=float)
        for c in ("tclim", "mom", "mom15", "boat"):
            X[c] = np.log1p(x[c].fillna(x[c].median()))
        for k in (1, 2):
            X[f"s{k}"] = np.sin(2 * np.pi * k * x.doy / 365.25); X[f"c{k}"] = np.cos(2 * np.pi * k * x.doy / 365.25)
        X["one"] = 1.0
        return X.to_numpy()

    def resid(y, X, w):
        W = np.sqrt(w)[:, None]
        b = np.linalg.lstsq(X * W, y * W[:, 0], rcond=None)[0]
        return y - X @ b

    rows = []
    for f in F.columns:
        x = cells[cells[f].notna()].reset_index(drop=True)
        if len(x) < 300 or x[f].nunique() < 3:
            continue
        X = design(x); w = x.ad.to_numpy()
        ry = resid(x.ly.to_numpy(), X, w)
        rx = resid(rankdata(x[f]).astype(float), X, w)
        blk = ((x.dep - pd.Timestamp("2015-01-05")).dt.days // 14).to_numpy(); ub = np.unique(blk)
        idx = {u: np.where(blk == u)[0] for u in ub}

        def stats(ii):
            raw = np.corrcoef(rankdata(x[f].to_numpy()[ii]), rankdata(x.ly.to_numpy()[ii]))[0, 1]
            par = np.corrcoef(rankdata(rx[ii]), rankdata(ry[ii]))[0, 1]
            return raw, par
        raw, par = stats(np.arange(len(x)))
        bs = np.array([stats(np.concatenate([idx[u] for u in rng.choice(ub, len(ub))])) for _ in range(400)])
        se = bs[:, 1].std()
        p = 2 * min((bs[:, 1] <= 0).mean(), (bs[:, 1] >= 0).mean()) if se > 0 else 1.0
        sea = x[x.dep.dt.month.between(6, 11)]
        raw_sea = np.corrcoef(rankdata(sea[f]), rankdata(sea.ly))[0, 1] if len(sea) > 100 else np.nan
        q = pd.qcut(rx, 5, labels=False, duplicates="drop")
        eff = np.exp(np.average(ry[q == q.max()], weights=w[q == q.max()]) - np.average(ry[q == q.min()], weights=w[q == q.min()]))
        g = next((v for k, v in GROUPS.items() if f.startswith(k)), "Other")
        rows.append(dict(group=g, factor=f, cells=len(x), years=f"{x.dep.dt.year.min()}–{x.dep.dt.year.max()}",
                         raw_r=raw, raw_r_season=raw_sea, partial_r=par, ci_lo=np.percentile(bs[:, 1], 2.5),
                         ci_hi=np.percentile(bs[:, 1], 97.5), p=max(p, 1 / 400), top_vs_bottom_fifth=eff))
        print(f"{f:28s} raw {raw:+.3f} season {raw_sea:+.3f} partial {par:+.3f} [{rows[-1]['ci_lo']:+.3f},{rows[-1]['ci_hi']:+.3f}] eff x{eff:.2f}", flush=True)
    r = pd.DataFrame(rows).sort_values("p")
    m = len(r); r["q_BH"] = (r.p * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    r = r.sort_values(["group", "partial_r"])
    r.to_csv(HERE / "data" / "factor_report_card.csv", index=False)
    print(r.round(3).to_string())


if __name__ == "__main__":
    main()
