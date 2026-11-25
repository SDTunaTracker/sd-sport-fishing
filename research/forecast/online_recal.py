"""Online level correction: shift each forecast's logit by the mean residual (above - p) of trips
REPORTED in the window [issue-W, issue-1] (all public at issue). Region-level. Leak-free."""
import sys, numpy as np, pandas as pd
from harness import HERE, auc
from run_round5 import load5
L = int(sys.argv[1]); nm = sys.argv[2] if len(sys.argv) > 2 else "A1_r4_monthly"
o = pd.read_pickle(HERE / "data" / f"oof5_{nm}_lead{L}.pkl")
d = load5(L)[["id", "date"]]; o = o.merge(d, on="id")
o = o[o.p_above.notna()].reset_index(drop=True)
o["issue"] = o.dep - pd.Timedelta(days=L)
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))
o["lres"] = o.above - o.p_above
days = pd.date_range("2018-01-01", "2027-01-31")
res = {}
for W in (14, 30, 60):
    for k in (2.0, 4.0):
        adj = np.zeros(len(o))
        for r, g in o.groupby("region"):
            s = g.groupby("date").lres.agg(["sum", "size"]).reindex(days, fill_value=0).cumsum()
            e = days.get_indexer(g.issue - pd.Timedelta(days=1)); b = days.get_indexer(g.issue - pd.Timedelta(days=W + 1))
            sm = s["sum"].to_numpy(); n = s["size"].to_numpy()
            ss = sm[e] - np.where(b >= 0, sm[b], 0); nn = n[e] - np.where(b >= 0, n[b], 0)
            mres = np.where(nn >= 20, ss / np.maximum(nn, 1), 0)
            adj[g.index] = k * mres  # residual in prob units ~ k * logit units (p(1-p)~0.25 -> k=4)
        o[f"p_{W}_{k}"] = 1 / (1 + np.exp(-(lg(o.p_above) + adj)))
ev = o.dep >= "2019-01-01"
for scope, m in (("2019-26", ev), ("2026", o.dep.dt.year == 2026)):
    x = o[m]
    base = (auc(x.above, x.p_above), np.mean((x.p_above - x.above) ** 2), np.mean(x.p_above - x.above))
    print(f"{scope} raw: auc {base[0]:.4f} brier {base[1]:.5f} bias {base[2]:+.3f}")
    for c in [c for c in o.columns if c.startswith("p_") and c.count("_") == 2]:
        print(f"{scope} {c}: auc {auc(x.above, x[c]):.4f} brier {np.mean((x[c] - x.above) ** 2):.5f} bias {np.mean(x[c] - x.above):+.3f}")

# honest selection: choose (W,k) on 2019-22, evaluate 2023-26 with paired 14-day block bootstrap
cands = [c for c in o.columns if c.startswith("p_") and c.count("_") == 2]
sel = (o.dep >= "2019-01-01") & (o.dep < "2023-01-01"); hold = o.dep >= "2023-01-01"
best = min(cands, key=lambda c: np.mean((o[c][sel] - o.above[sel]) ** 2))
x = o[hold].reset_index(drop=True)
blk = ((x.dep - pd.Timestamp("2015-01-05")).dt.days // 14).to_numpy(); ub = np.unique(blk)
idx = {u: np.where(blk == u)[0] for u in ub}; rng = np.random.default_rng(0); da, db = [], []
for _ in range(1000):
    ii = np.concatenate([idx[u] for u in rng.choice(ub, len(ub))]); lab = x.above.to_numpy()[ii]
    da.append(auc(lab, x[best].to_numpy()[ii]) - auc(lab, x.p_above.to_numpy()[ii]))
    db.append(np.mean((x[best].to_numpy()[ii] - lab) ** 2) - np.mean((x.p_above.to_numpy()[ii] - lab) ** 2))
print(f"HOLDOUT 2023-26, chosen on 2019-22: {best}  dAUC {auc(x.above, x[best]) - auc(x.above, x.p_above):+.4f} "
      f"[{np.percentile(da,2.5):+.4f},{np.percentile(da,97.5):+.4f}]  dBrier {np.mean((x[best]-x.above)**2)-np.mean((x.p_above-x.above)**2):+.5f} "
      f"[{np.percentile(db,2.5):+.5f},{np.percentile(db,97.5):+.5f}]  bias raw {np.mean(x.p_above-x.above):+.3f} -> {np.mean(x[best]-x.above):+.3f}")
