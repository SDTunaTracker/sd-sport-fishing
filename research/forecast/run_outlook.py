"""Surfline-style FLEET OUTLOOK: one rating per (region, trip-length bucket, departure date).

Target  : cell mean pct (how the trips that ran that day did vs normal), weighted by trips.
Rating  : poor < 0.35 <= fair < 0.5 <= good < 0.65 <= great   (on the forecast mean pct)
Forecast: fleet-only features (no boat identity) known at issue = dep - L.
Folds   : monthly, train on reports < month start - 15d. Scored 2019-01 .. 2026-11.

Reports
  * skill vs persistence (decayed fleet pct, the "it's good right now" forecast) and vs 0.5
  * noise ceiling: best possible correlation given only ~2-4 trips per cell
  * within-window: for each issue date, can it rank the next 14 days?
  * "book this weekend?" test: does a GREAT forecast at lead 3-7 pick better days?
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor as HGR
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from harness import HERE
from run_round5 import SEASON, START, load5

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FLEET = ([f"fp_{g}{w}" for g in ("lt", "l", "rs", "r") for w in (3, 7, 14, 30)]
         + [f"fd_rs_h{h}" for h in (2, 5, 15)] + [f"fd_lt_h{h}" for h in (2, 5, 15)] + ["fd_rt_h5"]
         + ["fp_lt7_n", "fp_rs7_n"])
CAL = ["doy_s", "doy_c", "tl_num", "sat", "sun", "fri"]
CUTS = [0.35, 0.5, 0.65]
NAMES = ["poor", "fair", "good", "great"]


def cells(L):
    d = load5(L)
    d = d[d.pct.notna()].copy()
    d["tl_num"] = d.tl
    dow = d.dep.dt.day_of_week
    d["sat"], d["sun"], d["fri"] = (dow == 5).astype(float), (dow == 6).astype(float), (dow == 4).astype(float)
    # landing-level fleet features differ inside a region cell -> average them
    feats = FLEET + SEASON + CAL
    g = d.groupby(["region", "tlb", "dep"])
    c = g[feats].mean()
    c["p"] = g.pct.mean(); c["n"] = g.size(); c["above"] = g.above.mean()
    c["date"] = g.date.max()
    c["pvar"] = g.pct.var()
    c = c.reset_index()
    return c, feats


def folds(c):
    for ms in pd.date_range(START, c.dep.max(), freq="MS"):
        cut = ms - pd.Timedelta(days=15)
        te = c.index[(c.dep >= ms) & (c.dep < ms + pd.offsets.MonthBegin(1))]
        if len(te):
            yield c.index[c.date < cut], te


def fit(c, feats):
    pred = np.full(len(c), np.nan)
    X = c[feats]
    for tr, te in folds(c):
        w = c.n[tr]
        r = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), Ridge(alpha=30))
        a = r.fit(X.loc[tr], c.p[tr], ridge__sample_weight=w).predict(X.loc[te])
        g = HGR(learning_rate=0.03, max_iter=300, max_depth=3, min_samples_leaf=100, l2_regularization=5, random_state=0)
        b = g.fit(X.loc[tr], c.p[tr], sample_weight=w).predict(X.loc[te])
        pred[te] = (a + b) / 2
    return pred


def rate(x):
    return np.digitize(x, CUTS)


def wcorr(a, b, w):
    a, b, w = map(np.asarray, (a, b, w))
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / np.sqrt(np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w))


def main(leads=(1, 3, 7, 14)):
    rows, lines = [], []
    for L in leads:
        c, feats = cells(L)
        c["fc"] = fit(c, feats)
        c["persist"] = c.fd_rt_h5.fillna(c.fd_rs_h5).fillna(0.5)
        e = c[(c.dep >= START) & c.fc.notna()].copy()
        e.to_pickle(HERE / "data" / f"outlook_lead{L}.pkl")
        # noise ceiling: var of the cell mean that is true signal
        within = np.nanmean(e.pvar) if e.pvar.notna().any() else 0.08
        noise = np.average(within / e.n, weights=e.n)
        tot = np.average((e.p - np.average(e.p, weights=e.n)) ** 2, weights=e.n)
        ceil = np.sqrt(max(0, 1 - noise / tot))
        r_fc, r_ps = wcorr(e.fc, e.p, e.n), wcorr(e.persist, e.p, e.n)
        mae = lambda f: np.average(np.abs(e.p - f), weights=e.n)
        hit = np.mean(rate(e.fc) == rate(e.p))
        # within-window ranking across the next days (issue date = dep - L; compare cells with same tlb
        # across dep dates issued on the SAME issue date only makes sense for a fixed-lead table: use
        # the 7 departures dep..dep+6 seen at lead L -> approximate with weekly blocks)
        e["blk"] = (e.dep - pd.Timestamp("2015-01-05")).dt.days // 7
        ww = []
        for _, g in e[e.region == "san_diego"].groupby(["tlb", "blk"]):
            if len(g) >= 4 and g.fc.nunique() > 1:
                ww.append(spearmanr(g.fc, g.p).statistic)
        great = e[(rate(e.fc) == 3)]
        poor = e[(rate(e.fc) == 0)]
        rows.append(dict(lead=L, cells=len(e), r_forecast=r_fc, r_persist=r_ps, r_ceiling=ceil,
                         mae_fc=mae(e.fc), mae_persist=mae(e.persist), mae_half=mae(0.5),
                         rating_hit=hit, within_week_rank=np.nanmean(ww), n_weeks=len(ww),
                         great_n=len(great), great_beat=np.average(great.above, weights=great.n) if len(great) else np.nan,
                         poor_n=len(poor), poor_beat=np.average(poor.above, weights=poor.n) if len(poor) else np.nan,
                         all_beat=np.average(e.above, weights=e.n)))
        print(rows[-1], flush=True)
        tab = pd.crosstab(pd.Categorical(np.array(NAMES)[rate(e.fc)], NAMES),
                          pd.Categorical(np.array(NAMES)[rate(e.p)], NAMES), values=e.n, aggfunc="sum",
                          normalize="index").round(2)
        lines += [f"\nLead {L}: forecast rating (rows) vs what happened (cols), trip-weighted share", tab.to_string()]
    r = pd.DataFrame(rows)
    r.to_csv(HERE / "data" / "outlook_results.csv", index=False)
    print(r.round(3).to_string()); print("\n".join(lines))


if __name__ == "__main__":
    main(tuple(int(x) for x in sys.argv[1].split(",")) if len(sys.argv) > 1 else (1, 3, 7, 14))
