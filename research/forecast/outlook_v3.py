"""Outlook v3: does satellite SST (MUR) / ENSO break the persistence ceiling at long leads?"""
import sys, warnings, numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import run_outlook as RO
from run_round5 import START, load5
warnings.filterwarnings("ignore"); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LEAN = ["fd_rt_h5", "fd_lt_h5", "fd_lt_h15", "fd_rs_h2", "fd_rs_h5", "fd_rs_h15", "fd_r_h30", "fd_r_h60", "fp_r_ytd", "sat", "sun", "doy_s", "doy_c"]
for L in map(int, sys.argv[1].split(",")):
    mur = [c for c in load5(L).columns if c.startswith("m_")]
    RO.CAL = RO.CAL + mur + ["oni", "pdo"]
    c, _ = RO.cells(L)
    # SST change over the lead window is unknowable; use change over the last 14 days known at issue
    for nm, f in {"lean": LEAN, "lean+mur": LEAN + mur, "lean+mur+enso": LEAN + mur + ["oni", "pdo"]}.items():
        for a in (3000, 10000):
            pred = np.full(len(c), np.nan)
            for tr, te in RO.folds(c):
                m = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), Ridge(alpha=a))
                pred[te] = m.fit(c.loc[tr, f], c.p[tr], ridge__sample_weight=c.n[tr]).predict(c.loc[te, f])
            k = (c.dep >= START).to_numpy(); e = c[k].assign(fc=pred[k])
            print(L, nm, a, "r=%.4f" % RO.wcorr(e.fc, e.p, e.n), "mae=%.4f" % np.average(np.abs(e.p - e.fc), weights=e.n), flush=True)
    RO.CAL = RO.CAL[:6]
