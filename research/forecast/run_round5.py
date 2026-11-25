"""Round 5: in-season retraining, recency weighting, season-level ("hot year") features,
boat seasonality. All offline; the shadow model r4-ens-v1 stays frozen.

Folds
  yearly : as rounds 1-4 (train on reports < Jan 1 - 15d, test the year)
  monthly: train on reports < month start - 15d, test departures in that month
           (closer to the live shadow, which retrains every day)
Scored on departures 2019-01-01 .. 2026-11, same rows for every variant.
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd

import build_round2 as B2
from harness import HERE, auc, metrics
from run_round2 import BASE, CAT, MOM_PCT, MOM_RAW, gb, lin_cls, lin_reg, load2
from run_round4 import NEW, add_feats, decayed_fleet

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
F4 = BASE + MOM_RAW + MOM_PCT + NEW
START = pd.Timestamp("2019-01-01")


def boat_season(d, issue, win=30):
    """Boat's mean pct on prior-YEAR trips within +-win days of this departure's day of year."""
    out = np.full(len(d), np.nan); cnt = np.zeros(len(d))
    ok = d.pct.notna().to_numpy()
    for _, idx in d.groupby(["boat", "landing"]).indices.items():
        dates = d.date.to_numpy()[idx]; doy = d.dep.dt.dayofyear.to_numpy()[idx]
        yr = d.dep.dt.year.to_numpy()[idx]; pc = d.pct.to_numpy()[idx]; okk = ok[idx]
        iss = issue.to_numpy()[idx]
        for j in range(len(idx)):
            dd = np.abs(doy - doy[j]); dd = np.minimum(dd, 365 - dd)
            m = okk & (yr < yr[j]) & (dd <= win) & (dates < iss[j])
            if m.any():
                out[idx[j]] = pc[m].mean(); cnt[idx[j]] = m.sum()
    return out, cnt


def season_feats(d, L):
    issue = d.dep - pd.Timedelta(days=L)
    last = issue - pd.Timedelta(days=1)
    for hl in (30, 60):
        decayed_fleet(d, ["region"], last, hl, f"fd_r_h{hl}")
        decayed_fleet(d, ["region", "seg"], last, hl, f"fd_rs_h{hl}")
    for keys, nm in [(["region"], "r"), (["region", "seg"], "rs")]:
        cs = B2.grouped_cumsum(d, keys, "pct")
        for w in (60, 90):
            d[f"fp_{nm}{w}"], _ = B2.window_mean(d, keys, cs, last, w)
    # year-to-date fleet pct (region), via the 365-day cumsum differenced at Jan 1
    cs = B2.grouped_cumsum(d, ["region"], "pct")
    ytd = np.full(len(d), np.nan)
    e = B2.DAYS.get_indexer(last)
    jan = B2.DAYS.get_indexer(pd.to_datetime(issue.dt.year.astype(str) + "-01-01") - pd.Timedelta(days=1))
    for i, r in enumerate(d.region):
        if (r,) in cs and e[i] >= 0:
            sm, n = cs[(r,)]
            c = n[e[i]] - (n[jan[i]] if jan[i] >= 0 else 0)
            if c >= 20:
                ytd[i] = (sm[e[i]] - (sm[jan[i]] if jan[i] >= 0 else 0)) / c
    d["fp_r_ytd"] = ytd
    d["bseas"], d["bseas_n"] = boat_season(d, issue)
    return d


SEASON = ["fd_r_h30", "fd_r_h60", "fd_rs_h30", "fd_rs_h60", "fp_r60", "fp_r90", "fp_rs60", "fp_rs90", "fp_r_ytd"]
BSEAS = ["bseas", "bseas_n"]


def load5(L):
    p = HERE / "data" / f"ds5_lead{L}.pkl"
    if p.exists():
        return pd.read_pickle(p)
    d = season_feats(add_feats(load2(L), L), L)
    d.to_pickle(p)
    return d


def folds(d, kind):
    if kind == "yearly":
        for Y in range(START.year, 2027):
            cut = pd.Timestamp(f"{Y}-01-01") - pd.Timedelta(days=15)
            yield d.index[d.date < cut], d.index[d.dep.dt.year == Y], cut
    else:
        for ms in pd.date_range(START, d.dep.max(), freq="MS"):
            cut = ms - pd.Timedelta(days=15)
            te = d.index[(d.dep >= ms) & (d.dep < ms + pd.offsets.MonthBegin(1))]
            if len(te):
                yield d.index[d.date < cut], te, cut


def fit_ens(tr, te, feats, w=None, parts=("lin", "gb")):
    Xtr, Xte = tr[feats + CAT].copy(), te[feats + CAT].copy()
    pa, pr = [], []
    if "lin" in parts:
        kw = {} if w is None else {"logisticregression__sample_weight": w}
        pa.append(lin_cls(feats).fit(Xtr, tr.above, **kw).predict_proba(Xte)[:, 1])
        kw = {} if w is None else {"ridge__sample_weight": w}
        pr.append(np.maximum(0, lin_reg(feats).fit(Xtr, tr.y, **kw).predict(Xte)))
    if "gb" in parts:
        for c in CAT:
            cats = pd.Categorical(pd.concat([Xtr[c], Xte[c]])).categories
            Xtr[c] = pd.Categorical(Xtr[c], categories=cats); Xte[c] = pd.Categorical(Xte[c], categories=cats)
        pa.append(gb(feats, True).fit(Xtr, tr.above, sample_weight=w).predict_proba(Xte)[:, 1])
        pr.append(np.maximum(0, gb(feats, False).fit(Xtr, tr.y, sample_weight=w).predict(Xte)))
    return np.mean(pa, 0), np.mean(pr, 0)


def run(d, feats, fold="yearly", hl_years=None, parts=("lin", "gb")):
    pa = np.full(len(d), np.nan); pr = np.full(len(d), np.nan)
    for tr, te, cut in folds(d, fold):
        w = None
        if hl_years:
            w = 0.5 ** ((cut - d.date[tr]).dt.days.to_numpy() / (365.25 * hl_years))
        a, r = fit_ens(d.loc[tr], d.loc[te], feats, w, parts)
        pa[te] = a; pr[te] = r
    return pa, pr


def score(d, pa, pr, mask):
    m = metrics(d.y[mask], pr[mask], d.clim0[mask], pa[mask], d.above[mask])
    m["bias"] = float(np.mean(pa[mask] - d.above[mask]))
    return m


EXPS = {
    "A0_r4_yearly": dict(feats=F4),
    "A1_r4_monthly": dict(feats=F4, fold="monthly"),
    "A2_r4_monthly_hl3": dict(feats=F4, fold="monthly", hl_years=3),
    "A3_r4_monthly_hl1.5": dict(feats=F4, fold="monthly", hl_years=1.5),
    "B1_+season_monthly": dict(feats=F4 + SEASON, fold="monthly"),
    "B2_+bseas_monthly": dict(feats=F4 + BSEAS, fold="monthly"),
    "B3_+season+bseas_monthly": dict(feats=F4 + SEASON + BSEAS, fold="monthly"),
    "B4_+season+bseas_monthly_hl3": dict(feats=F4 + SEASON + BSEAS, fold="monthly", hl_years=3),
}


def main(leads=(0, 1, 3, 7, 14), only=None):
    out = HERE / "data" / ("round6_results.csv" if "C1_+dow_monthly" in EXPS else "round5_results.csv")
    rows = []
    for L in leads:
        d = load5(L)
        ev = (d.dep >= START).to_numpy()
        e26 = (d.dep.dt.year == 2026).to_numpy()
        for nm, kw in EXPS.items():
            if only and nm not in only:
                continue
            pa, pr = run(d, **kw)
            for scope, mk in (("2019-26", ev), ("2026", e26)):
                m = score(d, pa, pr, mk)
                rows.append({"lead": L, "model": nm, "scope": scope, **m})
            m = rows[-2]
            print(f"L{L} {nm:28s} auc={m['auc']:.4f} bss={m['bss']:.4f} mae={m['mae']:.4f} "
                  f"sp={m['spearman']:.4f} bias={m['bias']:+.3f} | 2026 auc={rows[-1]['auc']:.4f} "
                  f"bss={rows[-1]['bss']:.4f} bias={rows[-1]['bias']:+.3f}", flush=True)
            d[["id", "dep", "boat", "region", "tlb", "month", "above", "y", "clim0"]].assign(
                p_above=pa, pred=pr).to_pickle(HERE / "data" / f"oof5_{nm}_lead{L}.pkl")
            pd.DataFrame(rows).to_csv(out, index=False)


if __name__ == "__main__":
    main(leads=tuple(int(x) for x in sys.argv[1].split(",")) if len(sys.argv) > 1 else (0, 1, 3, 7, 14))
