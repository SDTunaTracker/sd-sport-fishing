"""Score the CURRENT production model (src/forecast.py score_segment) on the same
walk-forward test set, fed with the same as-of-issue (persistence) conditions.

Generous to the baseline: its monthly_score and fitted weights were built from
the whole history (in-sample). Read-only use of src/ and the snapshot DB.
"""
from __future__ import annotations

import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge

from harness import HERE, folds, load, metrics

warnings.filterwarnings("ignore")
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from src import forecast as F  # noqa: E402


def nz(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def main():
    conn = sqlite3.connect(f"file:{HERE / 'data' / 'tracker_snapshot.db'}?mode=ro", uri=True)
    monthly = {(m, s): F._monthly_score(conn, m, s) for m in range(1, 13) for s in ("inshore", "offshore")}
    rows = []
    for L in (1, 3, 7, 14):
        d = load(L)
        d["segment"] = np.where(d.tl <= 1.0, "inshore", "offshore")
        keys = d[["dep", "segment"]].drop_duplicates()
        first = d.groupby(["dep", "segment"]).first()
        sc = {}
        for (dep, seg), r in first.iterrows():
            cond = {
                "month": dep.month,
                "sst_nearshore": nz(r.c_sst_nearshore), "sst_offshore": nz(r.c_sst_offshore),
                "sst_anomaly": nz(r.c_sst_anomaly), "sst_gradient": nz(r.c_sst_gradient),
                "wind_speed": nz(r.c_wind_speed),
                "wind_is_offshore": None if pd.isna(r.c_wind_is_offshore) else bool(r.c_wind_is_offshore),
                "wind_is_upwelling": None if pd.isna(r.c_wind_is_upwelling) else bool(r.c_wind_is_upwelling),
                "swell_height": nz(r.c_swell_height),
                "moon_illum": int(round(r.moon_illum * 100)),
                "upwelling_index": nz(r.c_upw_lag),
                "monthly_score": monthly[(dep.month, seg)],
            }
            try:
                sc[(dep, seg)] = F.score_segment(seg, cond, days_out=min(L, 7))["overall_score"]
            except Exception as e:  # pragma: no cover
                sc[(dep, seg)] = np.nan
        d["score"] = [sc.get((a, b), np.nan) for a, b in zip(d.dep, d.segment)]
        te_all = d.yr >= 2018
        # (a) raw score as a ranking signal; (b) per-fold calibrated to fish/angler/day and P(above)
        pred = np.full(len(d), np.nan); p = np.full(len(d), np.nan)
        pred2 = np.full(len(d), np.nan); p2 = np.full(len(d), np.nan)
        X = d[["score"]].fillna(5.5)
        X2 = pd.concat([X, d[["clim0"]]], axis=1)
        for Y, tr, te in folds(d):
            pred[te] = np.maximum(0, Ridge().fit(X.loc[tr], d.y[tr]).predict(X.loc[te]))
            p[te] = LogisticRegression().fit(X.loc[tr], d.above[tr]).predict_proba(X.loc[te])[:, 1]
            pred2[te] = np.maximum(0, Ridge().fit(X2.loc[tr], d.y[tr]).predict(X2.loc[te]))
            p2[te] = LogisticRegression().fit(X2.loc[tr], d.above[tr]).predict_proba(X2.loc[te])[:, 1]
        for nm, a, b in [("existing_score_calibrated", pred, p), ("existing_score+clim", pred2, p2)]:
            m = metrics(d.y[te_all], a[te_all], d.clim0[te_all], b[te_all], d.above[te_all])
            m["spearman_raw_score"] = d.score[te_all].corr(d.y[te_all], method="spearman")
            rows.append({"lead": L, "model": nm, **m})
            print(L, nm, {k: round(v, 4) for k, v in m.items()})
    pd.DataFrame(rows).to_csv(HERE / "data" / "baseline_existing.csv", index=False)


if __name__ == "__main__":
    main()
