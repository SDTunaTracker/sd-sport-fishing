"""Round 4: boat-skill + time-decayed fleet momentum + bookings test + isotonic
recalibration. Builds ds4 features on the fly from ds2."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from harness import HERE, SPECIES, auc, folds, metrics
from run_round2 import BASE, MOM_PCT, MOM_RAW, load2, run

warnings.filterwarnings("ignore")
DAYS = pd.date_range("2014-12-01", "2027-12-31")


def asof_boat(d, issue, col_src, keys, name_prefix, spans=(3,), expanding=False):
    b = d[d.pct.notna()][keys + ["date", "pct"]].sort_values("date").copy()
    g = b.groupby(keys).pct
    cols = []
    for s in spans:
        b[f"{name_prefix}_ewm{s}"] = g.transform(lambda x: x.ewm(span=s).mean()); cols.append(f"{name_prefix}_ewm{s}")
    if expanding:
        b[f"{name_prefix}_exp"] = g.transform(lambda x: x.expanding().mean()); cols.append(f"{name_prefix}_exp")
        b[f"{name_prefix}_n"] = g.cumcount() + 1; cols.append(f"{name_prefix}_n")
    b = b.groupby(keys + ["date"]).last().reset_index().rename(columns={"date": "key"}).sort_values("key")
    q = d[keys].copy(); q["key"] = issue.values; q["i"] = np.arange(len(d)); q = q.sort_values("key")
    m = pd.merge_asof(q, b[keys + ["key"] + cols], on="key", by=keys, allow_exact_matches=False)
    return m.set_index("i").sort_index()[cols].reset_index(drop=True)


def decayed_fleet(d, keys, last, halflife, nm):
    """Exponentially time-decayed mean pct of the group's trips reported <= last."""
    out = np.full(len(d), np.nan)
    ok = d[d.pct.notna()]
    lam = np.log(2) / halflife
    for k, g in ok.groupby(keys):
        s = g.groupby("date").pct.agg(["sum", "size"]).reindex(DAYS, fill_value=0)
        num = np.zeros(len(DAYS)); den = np.zeros(len(DAYS)); a = np.exp(-lam)
        ns, nn = 0.0, 0.0
        for i, (x, c) in enumerate(zip(s["sum"].to_numpy(), s["size"].to_numpy())):
            ns = ns * a + x; nn = nn * a + c; num[i] = ns; den[i] = nn
        kk = k if isinstance(k, tuple) else (k,)
        m = np.ones(len(d), bool)
        for col, v in zip(keys, kk):
            m &= (d[col] == v).to_numpy()
        e = DAYS.get_indexer(last[m])
        with np.errstate(invalid="ignore", divide="ignore"):
            out[m] = np.where(den[e] > 0.3, num[e] / den[e], np.nan)
    d[nm] = out


def add_feats(d, L):
    issue = d.dep - pd.Timedelta(days=L)
    last = issue - pd.Timedelta(days=1)
    x = asof_boat(d, issue, "pct", ["boat", "landing"], "bs", spans=(), expanding=True)
    y = asof_boat(d, issue, "pct", ["boat", "landing", "tlb"], "btl", spans=(3,), expanding=True)
    d = pd.concat([d.reset_index(drop=True), x, y], axis=1)
    for hl in (2, 5, 15):
        decayed_fleet(d, ["region", "seg"], last, hl, f"fd_rs_h{hl}")
        decayed_fleet(d, ["landing", "tlb"], last, hl, f"fd_lt_h{hl}")
    decayed_fleet(d, ["region", "tlb"], last, 5, "fd_rt_h5")
    return d


NEW = ["bs_exp", "bs_n", "btl_ewm3", "btl_exp", "btl_n"] + [f"fd_rs_h{h}" for h in (2, 5, 15)] + \
      [f"fd_lt_h{h}" for h in (2, 5, 15)] + ["fd_rt_h5"]
F3 = BASE + MOM_RAW + MOM_PCT


def ens(d, feats):
    a = run(d, feats, "lin"); b = run(d, feats, "gb")
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def iso_recal(d, p):
    """Recalibrate each test year with isotonic fit on earlier years' OOF predictions."""
    q = p.copy()
    for Y in range(2019, 2027):
        tr = (d.yr < Y) & (d.yr >= 2018); te = d.yr == Y
        if tr.sum() > 1000 and te.any():
            q[te] = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99).fit(p[tr], d.above[tr]).predict(p[te])
    return q


def main():
    rows = []
    for L in (0, 1, 3, 7, 14):
        d = add_feats(load2(L), L)
        te = (d.yr >= 2018).to_numpy()
        te2 = (d.yr >= 2019).to_numpy()  # recalibration needs a prior OOF year
        res = {}
        for nm, f in [("ens_F3", F3), ("ens_F3+boatskill+decay", F3 + NEW)] + (
                [("ens_F3+new+anglers(bookings)", F3 + NEW + ["anglers"])] if L == 0 else []):
            pr, pa = ens(d, f); res[nm] = (pr, pa)
            m = metrics(d.y[te2], pr[te2], d.clim0[te2], pa[te2], d.above[te2])
            rows.append({"lead": L, "model": nm, **m})
            print(L, nm, " ".join(f"{k}={v:.4f}" for k, v in m.items() if k in ("mae", "spearman", "auc", "bss", "dir_acc_p")), flush=True)
        pr, pa = res["ens_F3+boatskill+decay"]
        pc = iso_recal(d, pa)
        m = metrics(d.y[te2], pr[te2], d.clim0[te2], pc[te2], d.above[te2])
        rows.append({"lead": L, "model": "ens_F3+new_isotonic", **m})
        print(L, "ens_F3+new_isotonic", " ".join(f"{k}={v:.4f}" for k, v in m.items() if k in ("auc", "bss", "dir_acc_p")), flush=True)
        d[["id", "date", "dep", "yr", "month", "boat", "landing", "region", "tlb", "seg", "y", "clim0", "above", "pct"]].assign(
            pred=pr, p_raw=pa, p_above=pc, lead=L).to_pickle(HERE / "data" / f"oof_best_lead{L}.pkl")
        pd.DataFrame(rows).to_csv(HERE / "data" / "round4_results.csv", index=False)


if __name__ == "__main__":
    main()
