"""Round 7: SAN DIEGO TUNA per angler per fishing day (user target, 2026-11-25), leads 1/3/7.

tuna = bluefin + yellowfin + bigeye + albacore (skipjack excluded); tpad = tuna / (anglers x trip days).
Targets: tpad (regression, Poisson), good = tpad >= 1 (classification).
Unit: per trip, plus the fleet-day outlook (SD x trip-length bucket x fishing day, angler-day weighted).
Folds: monthly, train on reports < month start - 15d. Report 2019-26; selection decisions use 2019-22 only.

Feature groups (ablation, each vs the tuna-momentum baseline):
  CAL   : trip length, day of year, weekday
  TCLIM : tuna climatology by trip type x day-of-year (+-15 d), prior years only
  TMOM  : fleet tuna rate, time-decayed (half-life 2/5/15/30 d) at tlb / seg / all-SD; share of trips with tuna;
          days since a >=1/angler-day trip; boat's own tuna history (as of issue)
  PMOM  : the r4 percentile momentum (general bite, all trophy species)
  COND  : point SST/wind/swell/upwelling known at issue, MUR fronts/warm water, ENSO/PDO, moon
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier as HGC, HistGradientBoostingRegressor as HGR
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from harness import HERE, auc
from run_round2 import MOM_PCT, PT_COND
from run_round4 import NEW
from run_round5 import load5

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DAYS = pd.date_range("2014-12-01", "2027-12-31")
START = pd.Timestamp("2019-01-01")
TUNA = ["bluefin", "yellowfin", "bigeye", "albacore"]


def decayed_rate(d, keys, num, den, last, hl):
    """time-decayed sum(num)/sum(den) over trips REPORTED <= last, per group."""
    out = np.full(len(d), np.nan)
    a = np.exp(-np.log(2) / hl)
    ok = d[d[num].notna()]
    groups = ok.groupby(keys) if keys else [((), ok)]
    for k, g in groups:
        s = g.groupby("date")[[num, den]].sum().reindex(DAYS, fill_value=0)
        nn, dd = np.zeros(len(DAYS)), np.zeros(len(DAYS)); x = y = 0.0
        for i, (u, v) in enumerate(zip(s[num].to_numpy(), s[den].to_numpy())):
            x = x * a + u; y = y * a + v; nn[i] = x; dd[i] = y
        m = np.ones(len(d), bool)
        kk = k if isinstance(k, tuple) else (k,)
        for col, v in zip(keys, kk):
            m &= (d[col] == v).to_numpy()
        e = DAYS.get_indexer(last[m])
        with np.errstate(invalid="ignore", divide="ignore"):
            out[m] = np.where(dd[e] > 0.5, nn[e] / dd[e], np.nan)
    return out


def boat_tuna(d, issue):
    b = d[d.tpad.notna()][["boat", "landing", "date", "tpad"]].sort_values("date").copy()
    g = b.groupby(["boat", "landing"]).tpad
    b["bt_ewm3"] = g.transform(lambda x: x.ewm(span=3).mean())
    b["bt_exp"] = g.transform(lambda x: x.expanding().mean())
    b["bt_n"] = g.cumcount() + 1
    b = b.groupby(["boat", "landing", "date"]).last().reset_index().rename(columns={"date": "key"}).sort_values("key")
    q = d[["boat", "landing"]].copy(); q["key"] = issue.values; q["i"] = np.arange(len(d)); q = q.sort_values("key")
    m = pd.merge_asof(q, b[["boat", "landing", "key", "bt_ewm3", "bt_exp", "bt_n"]], on="key",
                      by=["boat", "landing"], allow_exact_matches=False)
    return m.set_index("i").sort_index()[["bt_ewm3", "bt_exp", "bt_n"]].reset_index(drop=True)


def tuna_clim(d):
    """mean tpad of prior-year trips, same tlb, departure doy within +-15 (circular)."""
    out = np.full(len(d), np.nan)
    doy = d.dep.dt.dayofyear.clip(upper=365).to_numpy() - 1; yr = d.dep.dt.year.to_numpy()
    for tlb in d.tlb.unique():
        mt = (d.tlb == tlb).to_numpy()
        for Y in np.unique(yr[mt]):
            h = mt & (yr < Y) & d.tpad.notna().to_numpy()
            if h.sum() < 30:
                continue
            s = np.bincount(doy[h], weights=d.tuna.to_numpy()[h], minlength=365)
            a = np.bincount(doy[h], weights=d.ad.to_numpy()[h], minlength=365)
            k = np.ones(31)
            ss = np.convolve(np.r_[s[-15:], s, s[:15]], k, "valid"); aa = np.convolve(np.r_[a[-15:], a, a[:15]], k, "valid")
            rows = mt & (yr == Y)
            with np.errstate(invalid="ignore", divide="ignore"):
                out[rows] = np.where(aa[doy[rows]] > 0, ss[doy[rows]] / aa[doy[rows]], np.nan)
    return out


def build(L):
    p = HERE / "data" / f"dst_lead{L}.pkl"
    if p.exists():
        return pd.read_pickle(p)
    d = load5(L)
    d = d[d.region == "san_diego"].reset_index(drop=True).copy()
    d["tuna"] = d[TUNA].sum(axis=1)
    d["tpad"] = d.tuna / d.ad
    d["tuna_any"] = (d.tuna > 0).astype(float)
    d["good"] = (d.tpad >= 1).astype(float)
    issue = d.dep - pd.Timedelta(days=L); last = issue - pd.Timedelta(days=1)
    for hl in (2, 5, 15, 30):
        d[f"ft_tlb_h{hl}"] = decayed_rate(d, ["tlb"], "tuna", "ad", last, hl)
        d[f"ft_seg_h{hl}"] = decayed_rate(d, ["seg"], "tuna", "ad", last, hl)
        d[f"ft_all_h{hl}"] = decayed_rate(d, [], "tuna", "ad", last, hl)
    d["one"] = 1.0
    for hl in (5, 15):
        d[f"fany_tlb_h{hl}"] = decayed_rate(d, ["tlb"], "tuna_any", "one", last, hl)
        d[f"fgood_tlb_h{hl}"] = decayed_rate(d, ["tlb"], "good", "one", last, hl)
    # days since any SD trip of the same segment reported >= 1 tuna/angler-day
    good_dates = d[d.good == 1].groupby("seg").date.apply(lambda s: np.sort(s.unique()))
    ds = np.full(len(d), np.nan)
    for seg, gd in good_dates.items():
        m = (d.seg == seg).to_numpy()
        lv = last[m].to_numpy()
        j = np.searchsorted(gd, lv, side="right") - 1
        ds[m] = np.where(j >= 0, (lv - gd[np.maximum(j, 0)]) / np.timedelta64(1, "D"), np.nan)
    d["days_since_good"] = np.minimum(ds, 365)
    d = pd.concat([d, boat_tuna(d, issue)], axis=1)
    d["tclim"] = tuna_clim(d)
    dow = d.dep.dt.day_of_week
    for k, nm in ((4, "fri"), (5, "sat"), (6, "sun")):
        d[nm] = (dow == k).astype(float)
    d["tlb_n"] = d.tl
    d.to_pickle(p)
    return d


CAL = ["tlb_n", "doy_s", "doy_c", "fri", "sat", "sun"]
TCLIM = ["tclim"]
TMOM = ([f"ft_{g}_h{h}" for g in ("tlb", "seg", "all") for h in (2, 5, 15, 30)]
        + [f"fany_tlb_h{h}" for h in (5, 15)] + [f"fgood_tlb_h{h}" for h in (5, 15)]
        + ["days_since_good", "bt_ewm3", "bt_exp", "bt_n"])
PMOM = MOM_PCT + NEW


def cond_cols(d):
    return PT_COND + [c for c in d.columns if c.startswith("m_")] + ["oni", "pdo", "moon_illum"]


def folds(d):
    for ms in pd.date_range(START, d.dep.max(), freq="MS"):
        cut = ms - pd.Timedelta(days=15)
        te = d.index[(d.dep >= ms) & (d.dep < ms + pd.offsets.MonthBegin(1))]
        if len(te):
            yield d.index[d.date < cut], te


def fit(d, feats):
    reg = np.full(len(d), np.nan); cls = np.full(len(d), np.nan)
    X = d[feats]
    kw = dict(learning_rate=0.03, max_iter=300, max_depth=4, min_samples_leaf=150, l2_regularization=5.0, random_state=0)
    for tr, te in folds(d):
        w = d.ad[tr]
        r1 = HGR(loss="poisson", **kw).fit(X.loc[tr], d.tpad[tr], sample_weight=w).predict(X.loc[te])
        lr = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), Ridge(alpha=10))
        r2 = np.expm1(lr.fit(X.loc[tr], np.log1p(d.tpad[tr]), ridge__sample_weight=w).predict(X.loc[te])).clip(0)
        reg[te] = (r1 + r2) / 2
        c1 = HGC(**kw).fit(X.loc[tr], d.good[tr]).predict_proba(X.loc[te])[:, 1]
        lc = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), LogisticRegression(C=0.1, max_iter=2000))
        c2 = lc.fit(X.loc[tr], d.good[tr]).predict_proba(X.loc[te])[:, 1]
        cls[te] = (c1 + c2) / 2
    return reg, cls


def wcorr(a, b, w):
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / np.sqrt(np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w))


def evaluate(d, reg, cls, mask):
    x = d[mask]; r = reg[mask]; c = cls[mask]
    # fleet-day outlook: aggregate trips that ran (angler-day weighted)
    f = x.assign(pr=r * x.ad, pc=c).groupby(["tlb", "dep"]).agg(t=("tuna", "sum"), ad=("ad", "sum"), pr=("pr", "sum"),
                                                                  g=("good", "mean"), pc=("pc", "mean"), n=("tuna", "size"))
    f["obs"] = f.t / f.ad; f["fc"] = f.pr / f.ad
    return dict(n=int(mask.sum()), mae=np.average(np.abs(x.tpad - r), weights=x.ad),
                spearman=pd.Series(r).corr(pd.Series(x.tpad.to_numpy()), method="spearman"),
                auc_good=auc(x.good, c), brier_good=np.mean((c - x.good) ** 2),
                base_good=x.good.mean(), fleet_r=wcorr(f.fc, f.obs, f.ad), fleet_mae=np.average(np.abs(f.fc - f.obs), weights=f.ad),
                fleet_auc_good=auc(f.g >= 0.5, f.pc))


def main(leads=(1, 3, 7)):
    rows = []
    for L in leads:
        d = build(L)
        cond = cond_cols(d)
        ev = (d.dep >= START).to_numpy()
        # baselines: persistence = decayed fleet tuna rate for the trip type (h5); climatology = tclim
        for nm, col in (("persist_ft_tlb_h5", "ft_tlb_h5"), ("climatology", "tclim")):
            r = d[col].fillna(d[col].median()).to_numpy()
            c = d[f"fgood_tlb_h5" if nm.startswith("persist") else "tclim"].fillna(0).to_numpy()
            rows.append(dict(lead=L, model=nm, **evaluate(d, r, c, ev)))
            print(L, nm, {k: round(v, 4) for k, v in rows[-1].items() if isinstance(v, float)}, flush=True)
        exps = {"M1_cal+tclim": CAL + TCLIM, "M2_+tuna_mom": CAL + TCLIM + TMOM,
                "M3_+pct_mom": CAL + TCLIM + TMOM + PMOM, "M4_+conditions": CAL + TCLIM + TMOM + PMOM + cond}
        for nm, f in exps.items():
            reg, cls = fit(d, f)
            rows.append(dict(lead=L, model=nm, **evaluate(d, reg, cls, ev)))
            print(L, nm, {k: round(v, 4) for k, v in rows[-1].items() if isinstance(v, float)}, flush=True)
            d[["id", "dep", "date", "boat", "tlb", "tpad", "good", "ad", "tuna"]].assign(reg=reg, cls=cls).to_pickle(
                HERE / "data" / f"ooft_{nm}_lead{L}.pkl")
            pd.DataFrame(rows).to_csv(HERE / "data" / "round7_tuna.csv", index=False)


if __name__ == "__main__":
    main(tuple(int(x) for x in sys.argv[1].split(",")) if len(sys.argv) > 1 else (1, 3, 7))
