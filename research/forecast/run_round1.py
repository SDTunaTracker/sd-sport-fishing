"""Round 1: baselines, LightGBM, input-group ablations, oracle-weather bound."""
from __future__ import annotations

import json
import sys
import warnings

from sklearn.ensemble import HistGradientBoostingRegressor as HGR, HistGradientBoostingClassifier as HGC
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, LogisticRegression

from harness import HERE, SPECIES, folds, load, metrics

warnings.filterwarnings("ignore")

CAT = ["landing", "region", "tlb"]
G = {
    "base": CAT + ["tl", "doy_s", "doy_c", "month", "dow", "clim_boat", "clim_boat_n",
                   "clim_land", "clim_reg", "clim0"] + [f"clim_land_{s}" for s in SPECIES],
    "fleet": None, "boat": ["b_ewm3", "b_last", "b_days_since"],
    "sst": None, "wind": ["c_wind_speed", "c_wind_direction_deg", "c_wind_is_upwelling",
                          "c_wind_is_offshore", "c_wind7"],
    "swell": ["c_swell_height", "c_swell_period", "c_swell7"],
    "pressure": ["c_pressure", "c_pressure_trend"],
    "upwelling": ["c_upw_lag", "c_upw30_lag"],
    "moon": ["moon_phase", "moon_illum", "moon_s", "moon_c"],
}
ORACLE = ["orc_wind_speed", "orc_wind_direction_deg", "orc_swell_height", "orc_swell_period",
          "orc_pressure_trend", "orc_sst_offshore", "orc_sst_9mile", "orc_sst_anomaly"]


def groups(d):
    g = dict(G)
    g["fleet"] = [c for c in d.columns if c.startswith(("fown", "fother", "fsdoff", "mom_ratio"))]
    g["sst"] = [c for c in d.columns if c.startswith("c_sst")]
    return g


P_REG = dict(loss="poisson", learning_rate=0.04, max_iter=400, max_leaf_nodes=31,
             min_samples_leaf=60, l2_regularization=1.0, categorical_features="from_dtype", random_state=0)
P_CLS = dict(loss="log_loss", learning_rate=0.04, max_iter=300, max_leaf_nodes=31,
             min_samples_leaf=60, l2_regularization=1.0, categorical_features="from_dtype", random_state=0)


def prep(d, feats):
    X = d[feats].copy()
    for c in CAT:
        if c in X:
            X[c] = X[c].astype("category")
    return X


def run_lgb(d, feats, cls=True):
    pr = np.full(len(d), np.nan); pa = np.full(len(d), np.nan)
    X = prep(d, feats)
    for Y, tr, te in folds(d):
        m = HGR(**P_REG).fit(X.loc[tr], d.y[tr])
        pr[te] = m.predict(X.loc[te])
        if cls:
            mc = HGC(**P_CLS).fit(X.loc[tr], d.above[tr])
            pa[te] = mc.predict_proba(X.loc[te])[:, 1]
    return pr, pa, m


def baselines(d):
    out = {}
    out["clim0"] = d.clim0.to_numpy()
    out["persist_boat"] = d.b_ewm3.fillna(d.clim0).to_numpy()
    out["persist_fleet7"] = d.fown7_tpad.fillna(d.clim0).to_numpy()
    # ridge blend of clim + momentum (simple, linear) fitted per fold
    f = ["clim0", "fown7_tpad", "fown14_tpad", "b_ewm3", "clim_land"]
    X = d[f].fillna(d.clim0.to_frame().values.repeat(len(f), 1).mean()).copy()
    for c in f:
        X[c] = d[c].fillna(d.clim0)
    lin = np.full(len(d), np.nan); lp = np.full(len(d), np.nan)
    for Y, tr, te in folds(d):
        r = Ridge(alpha=1.0).fit(X.loc[tr], d.y[tr]); lin[te] = np.maximum(0, r.predict(X.loc[te]))
        lg = LogisticRegression(C=1.0, max_iter=500).fit(X.loc[tr], d.above[tr])
        lp[te] = lg.predict_proba(X.loc[te])[:, 1]
    out["ridge_clim_mom"] = lin
    return out, lp


def evaluate(d, pred, p=None):
    te = d.yr >= 2018
    return metrics(d.y[te], pred[te], d.clim0[te], None if p is None else p[te], d.above[te])


def main(leads=(1, 3, 7, 14), ablate_leads=(1, 7)):
    res = []
    for L in leads:
        d = load(L)
        g = groups(d)
        b, lp = baselines(d)
        for name, pred in b.items():
            r = evaluate(d, pred, lp if name == "ridge_clim_mom" else None)
            res.append({"lead": L, "model": name, **r}); print(L, name, {k: round(v, 4) for k, v in r.items()})
        allf = [c for k in g for c in g[k]]
        pr, pa, m = run_lgb(d, allf)
        r = evaluate(d, pr, pa); res.append({"lead": L, "model": "lgb_all", **r})
        print(L, "lgb_all", {k: round(v, 4) for k, v in r.items()})
        d[["id", "date", "dep", "boat", "landing", "region", "tlb", "seg", "y", "clim0", "above"]].assign(
            pred=pr, p_above=pa).to_pickle(HERE / "data" / f"oof_lgb_all_lead{L}.pkl")
        if L in ablate_leads:
            for k in g:
                if k == "base":
                    continue
                f = [c for c in allf if c not in g[k]]
                pr2, pa2, _ = run_lgb(d, f)
                r = evaluate(d, pr2, pa2); res.append({"lead": L, "model": f"lgb_minus_{k}", **r})
                print(L, f"minus_{k}", {kk: round(v, 4) for kk, v in r.items()})
            # base only, base+fleet+boat (momentum only)
            for nm, f in [("lgb_base_only", g["base"]),
                          ("lgb_base_mom", g["base"] + g["fleet"] + g["boat"]),
                          ("lgb_all_plus_oracle_wx", allf + ORACLE)]:
                pr2, pa2, _ = run_lgb(d, f)
                r = evaluate(d, pr2, pa2); res.append({"lead": L, "model": nm, **r})
                print(L, nm, {kk: round(v, 4) for kk, v in r.items()})
        pd.DataFrame(res).to_csv(HERE / "data" / "round1_results.csv", index=False)


if __name__ == "__main__":
    main()
