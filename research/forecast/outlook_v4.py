"""Outlook v4: honest model selection + uncertainty.
Choose ridge alpha on departures 2019-2022 only; report 2023-2026 (held out from the choice).
CI on (r_model - r_persist) by block bootstrap over 14-day blocks (cells are autocorrelated)."""
import sys, warnings, numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import run_outlook as RO
from run_round5 import START
warnings.filterwarnings("ignore"); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LEAN = ["fd_rt_h5", "fd_lt_h5", "fd_lt_h15", "fd_rs_h2", "fd_rs_h5", "fd_rs_h15", "fd_r_h30", "fd_r_h60", "fp_r_ytd", "sat", "sun", "doy_s", "doy_c"]
ALPHAS = [10, 100, 300, 1000, 3000, 10000, 30000]
rng = np.random.default_rng(0)
rows = []
for L in map(int, sys.argv[1].split(",")):
    c, _ = RO.cells(L)
    c["persist"] = c.fd_rt_h5.fillna(c.fd_rs_h5).fillna(0.5)
    preds = {}
    for a in ALPHAS:
        p = np.full(len(c), np.nan)
        for tr, te in RO.folds(c):
            m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=a))
            p[te] = m.fit(c.loc[tr, LEAN], c.p[tr], ridge__sample_weight=c.n[tr]).predict(c.loc[te, LEAN])
        preds[a] = p
    sel = ((c.dep >= START) & (c.dep < "2023-01-01")).to_numpy()
    hold = (c.dep >= "2023-01-01").to_numpy()
    rsel = {a: RO.wcorr(preds[a][sel], c.p[sel], c.n[sel]) for a in ALPHAS}
    best = max(rsel, key=rsel.get)
    e = c[hold].assign(fc=preds[best][hold])
    e["blk"] = (e.dep - pd.Timestamp("2015-01-05")).dt.days // 14
    blocks = e.blk.unique(); diffs = []
    for _ in range(1000):
        b = rng.choice(blocks, len(blocks)); s = pd.concat([e[e.blk == x] for x in b[:]]) if False else e.set_index("blk").loc[b].reset_index()
        diffs.append(RO.wcorr(s.fc, s.p, s.n) - RO.wcorr(s.persist, s.p, s.n))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    g = e[RO.rate(e.fc) == 3]; pz = e[RO.rate(e.fc) == 0]
    rows.append(dict(lead=L, alpha_chosen_on_2019_22=best, r_model=RO.wcorr(e.fc, e.p, e.n), r_persist=RO.wcorr(e.persist, e.p, e.n),
                     gain=RO.wcorr(e.fc, e.p, e.n) - RO.wcorr(e.persist, e.p, e.n), ci_lo=lo, ci_hi=hi,
                     great_days=len(g), great_beat=np.average(g.above, weights=g.n) if len(g) else np.nan,
                     poor_days=len(pz), poor_beat=np.average(pz.above, weights=pz.n) if len(pz) else np.nan,
                     base=np.average(e.above, weights=e.n)))
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
pd.DataFrame(rows).to_csv(RO.HERE / "data" / "outlook_v4_holdout.csv", index=False)
