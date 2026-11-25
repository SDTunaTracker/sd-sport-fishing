"""Round 2: percentile momentum, regularised linear vs boosting, MUR / ENSO tests."""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier as HGC, HistGradientBoostingRegressor as HGR
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import harness
from harness import HERE, SPECIES, folds, metrics

warnings.filterwarnings("ignore")


def load2(L):
    d = pd.read_pickle(HERE / "data" / f"ds2_lead{L}.pkl")
    k = 20.0
    cl = d.clim_land.where(d.clim_land.notna(), d.clim_reg)
    nb = d.clim_boat_n.fillna(0)
    d["clim0"] = (nb * d.clim_boat.fillna(cl) + k * cl) / (nb + k)
    d["above"] = (d.pct > 0.5).astype(float)
    d["yr"] = d.dep.dt.year
    return d[d.clim0.notna() & d.pct.notna()].reset_index(drop=True)


CAT = ["landing", "tlb"]
BASE = ["tl", "doy_s", "doy_c", "clim0", "clim_land", "clim_boat_n"]
MOM_RAW = ["fown7_tpad", "fown14_tpad", "b_ewm3", "b_days_since"]
MOM_PCT = (["bp_last", "bp_ewm3", "bp_ewm8", "bp_ntrips"]
           + [f"fp_{g}{w}" for g in ("lt", "l", "rs", "r") for w in (3, 7, 14, 30)])
MOM_SP = [f"fp_rs{w}_{s}" for w in (7, 14) for s in SPECIES]
ACT = ["fp_lt7_n", "fp_rs7_n", "fown7_n"]
MUR = None  # filled from columns
IDX = ["oni", "pdo"]
PT_COND = ["c_sst_offshore", "c_sst_9mile", "c_sst_anomaly", "c_sst_offshore_d7", "c_sst_offshore_d30",
           "c_wind7", "c_swell7", "c_upw30_lag"]


def lin_cls(num, C=0.1):
    pre = ColumnTransformer([("n", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), num),
                             ("c", OneHotEncoder(handle_unknown="ignore", min_frequency=50), CAT)])
    return make_pipeline(pre, LogisticRegression(C=C, max_iter=2000))


def lin_reg(num, a=10.0):
    pre = ColumnTransformer([("n", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()), num),
                             ("c", OneHotEncoder(handle_unknown="ignore", min_frequency=50), CAT)])
    return make_pipeline(pre, Ridge(alpha=a))


def gb(num, cls=True):
    kw = dict(learning_rate=0.03, max_iter=250, max_depth=4, min_samples_leaf=200, l2_regularization=5.0,
              categorical_features="from_dtype", random_state=0)
    return HGC(**kw) if cls else HGR(loss="poisson", **kw)


def run(d, num, kind="lin", C=0.1):
    pr = np.full(len(d), np.nan); pa = np.full(len(d), np.nan)
    X = d[num + CAT].copy()
    if kind == "gb":
        for c in CAT:
            X[c] = X[c].astype("category")
    for Y, tr, te in folds(d):
        if kind == "lin":
            mc, mr = lin_cls(num, C), lin_reg(num)
        else:
            mc, mr = gb(num, True), gb(num, False)
        pa[te] = mc.fit(X.loc[tr], d.above[tr]).predict_proba(X.loc[te])[:, 1]
        pr[te] = np.maximum(0, mr.fit(X.loc[tr], d.y[tr]).predict(X.loc[te]))
    return pr, pa


def ev(d, pr, pa):
    te = d.yr >= 2018
    return metrics(d.y[te], pr[te], d.clim0[te], pa[te], d.above[te])


def main(leads=(1, 3, 7, 14)):
    rows = []
    for L in leads:
        d = load2(L)
        mur = [c for c in d.columns if c.startswith("m_")]
        exps = {
            "R0_lin_raw_mom": (BASE + MOM_RAW, "lin"),
            "R1_lin_pct_mom": (BASE + MOM_RAW + MOM_PCT, "lin"),
            "R1b_lin_pct_mom_sp_act": (BASE + MOM_RAW + MOM_PCT + MOM_SP + ACT, "lin"),
            "R2_gb_pct_mom_sp_act": (BASE + MOM_RAW + MOM_PCT + MOM_SP + ACT, "gb"),
            "R3_lin_+mur": (BASE + MOM_RAW + MOM_PCT + MOM_SP + ACT + mur, "lin"),
            "R3g_gb_+mur": (BASE + MOM_RAW + MOM_PCT + MOM_SP + ACT + mur, "gb"),
            "R4_lin_+enso_pdo": (BASE + MOM_RAW + MOM_PCT + MOM_SP + ACT + IDX, "lin"),
            "R5_lin_+point_cond": (BASE + MOM_RAW + MOM_PCT + MOM_SP + ACT + PT_COND, "lin"),
            "R6_lin_cond_only_no_mom": (BASE + PT_COND + mur + IDX, "lin"),
            "R6g_gb_cond_only_no_mom": (BASE + PT_COND + mur + IDX, "gb"),
            "R7_gb_everything": (BASE + MOM_RAW + MOM_PCT + MOM_SP + ACT + mur + IDX + PT_COND, "gb"),
        }
        if L in (3, 14):  # keep the long ones to the key comparisons
            exps = {k: v for k, v in exps.items() if k in ("R0_lin_raw_mom", "R1b_lin_pct_mom_sp_act",
                                                          "R2_gb_pct_mom_sp_act", "R3_lin_+mur", "R6_lin_cond_only_no_mom",
                                                          "R7_gb_everything")}
        for name, (num, kind) in exps.items():
            pr, pa = run(d, num, kind)
            m = ev(d, pr, pa)
            rows.append({"lead": L, "model": name, **m})
            print(L, name, " ".join(f"{k}={v:.4f}" for k, v in m.items() if k in ("mae", "spearman", "auc", "bss", "dir_acc_p")), flush=True)
            if name == "R1b_lin_pct_mom_sp_act":
                d[["id", "date", "dep", "boat", "landing", "region", "tlb", "seg", "month", "y", "clim0", "above", "pct"]
                  + [f"y_{s}" for s in SPECIES]].assign(pred=pr, p_above=pa).to_pickle(HERE / "data" / f"oof_R1b_lead{L}.pkl")
        pd.DataFrame(rows).to_csv(HERE / "data" / "round2_results.csv", index=False)


if __name__ == "__main__":
    main()
