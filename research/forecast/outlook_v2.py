"""Outlook v2: lean models to beat persistence at leads 3-14 (overfit check)."""
import sys, warnings, numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from run_outlook import cells, folds, wcorr, rate
from run_round5 import START
from harness import HERE
warnings.filterwarnings("ignore"); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
VARS = {
 "lean": ["fd_rt_h5", "fd_rs_h2", "fd_rs_h5", "fd_rs_h15", "fd_r_h30", "fd_r_h60", "fp_r_ytd", "sat", "sun"],
 "lean+lt": ["fd_rt_h5", "fd_lt_h5", "fd_lt_h15", "fd_rs_h2", "fd_rs_h5", "fd_rs_h15", "fd_r_h30", "fd_r_h60", "fp_r_ytd", "sat", "sun", "doy_s", "doy_c"],
}
rows = []
for L in map(int, sys.argv[1].split(",")):
    c, _ = cells(L)
    c["persist"] = c.fd_rt_h5.fillna(c.fd_rs_h5).fillna(0.5)
    for nm, f in VARS.items():
        for a in (10, 300, 3000):
            pred = np.full(len(c), np.nan)
            for tr, te in folds(c):
                m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=a))
                pred[te] = m.fit(c.loc[tr, f], c.p[tr], ridge__sample_weight=c.n[tr]).predict(c.loc[te, f])
            e = c[(c.dep >= START)].assign(fc=pred[(c.dep >= START).to_numpy()])
            g, pz = e[rate(e.fc) == 3], e[rate(e.fc) == 0]
            rows.append(dict(lead=L, model=nm, alpha=a, r=wcorr(e.fc, e.p, e.n), r_persist=wcorr(e.persist, e.p, e.n),
                             mae=np.average(np.abs(e.p - e.fc), weights=e.n), mae_p=np.average(np.abs(e.p - e.persist), weights=e.n),
                             great_n=len(g), great_beat=np.average(g.above, weights=g.n) if len(g) else np.nan,
                             poor_n=len(pz), poor_beat=np.average(pz.above, weights=pz.n) if len(pz) else np.nan))
            print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
pd.DataFrame(rows).to_csv(HERE / "data" / f"outlook_v2_{sys.argv[1].replace(',', '-')}.csv", index=False)
