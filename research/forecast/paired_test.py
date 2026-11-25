"""Paired block-bootstrap of AUC/Brier differences between two OOF prediction files (same rows)."""
import sys, numpy as np, pandas as pd
from harness import HERE, auc
rng = np.random.default_rng(0)
def load(nm, L): return pd.read_pickle(HERE / "data" / f"oof5_{nm}_lead{L}.pkl")
def test(a, b, L, start="2019-01-01", B=1000):
    x, y = load(a, L), load(b, L); k = (x.dep >= start).to_numpy() & x.p_above.notna().to_numpy() & y.p_above.notna().to_numpy()
    x, y = x[k].reset_index(drop=True), y[k].reset_index(drop=True)
    blk = ((x.dep - pd.Timestamp("2015-01-05")).dt.days // 14).to_numpy(); ub = np.unique(blk)
    idx = {u: np.where(blk == u)[0] for u in ub}
    da, db = [], []
    for _ in range(B):
        ii = np.concatenate([idx[u] for u in rng.choice(ub, len(ub))])
        lab = x.above.to_numpy()[ii]
        da.append(auc(lab, y.p_above.to_numpy()[ii]) - auc(lab, x.p_above.to_numpy()[ii]))
        db.append(np.mean((y.p_above.to_numpy()[ii] - lab) ** 2) - np.mean((x.p_above.to_numpy()[ii] - lab) ** 2))
    pt = auc(x.above, y.p_above) - auc(x.above, x.p_above)
    pb = np.mean((y.p_above - y.above) ** 2) - np.mean((x.p_above - x.above) ** 2)
    print(f"L{L} {b} vs {a}: dAUC {pt:+.4f} [{np.percentile(da,2.5):+.4f},{np.percentile(da,97.5):+.4f}]  "
          f"dBrier {pb:+.5f} [{np.percentile(db,2.5):+.5f},{np.percentile(db,97.5):+.5f}] (neg = better)", flush=True)
if __name__ == "__main__":
    L = int(sys.argv[1])
    for a, b in [("A0_r4_yearly", "A1_r4_monthly"), ("A0_r4_yearly", "A2_r4_monthly_hl3"), ("A1_r4_monthly", "A2_r4_monthly_hl3"),
                 ("A1_r4_monthly", "B1_+season_monthly")]:
        test(a, b, L)
        test(a, b, L, start="2026-01-01", B=500)
