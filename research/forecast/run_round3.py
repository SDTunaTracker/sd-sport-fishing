"""Round 3: predictability ceiling, night-before lead, ensemble, calibration and
breakdowns (month, trip length, region, year, species)."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from harness import HERE, SPECIES, auc, calib_table, folds, metrics
from run_round2 import BASE, MOM_PCT, MOM_RAW, load2, run

warnings.filterwarnings("ignore")
FEATS = BASE + MOM_RAW + MOM_PCT


def ceiling(d):
    """Upper bound for any 'day-level' forecast (conditions/bite of the day):
    score each trip by the leave-one-out mean pct of the OTHER boats from the same
    landing x trip-length bucket returning the same day. A perfect knowledge of
    'how the bite was that day' can't beat this by much; the rest is boat/crew/luck."""
    te = d[d.yr >= 2018].copy()
    g = te.groupby(["date", "landing", "tlb"]).pct
    s, n = g.transform("sum"), g.transform("size")
    te["loo"] = (s - te.pct) / (n - 1)
    x = te[n > 1]
    g2 = te.groupby(["date", "region", "seg"]).pct
    s2, n2 = g2.transform("sum"), g2.transform("size")
    te["loo_r"] = (s2 - te.pct) / (n2 - 1)
    x2 = te[n2 > 1]
    return {"ceiling_auc_same_landing_tl_day": auc(x.above, x.loo), "n1": len(x),
            "ceiling_auc_same_region_seg_day": auc(x2.above, x2.loo_r), "n2": len(x2)}


def main():
    rows, oof = [], {}
    for L in (0, 1, 3, 7, 14):
        d = load2(L)
        if L == 1:
            c = ceiling(d); print("CEILING", c, flush=True)
            pd.Series(c).to_csv(HERE / "data" / "ceiling.csv")
        prl, pal = run(d, FEATS, "lin")
        prg, pag = run(d, FEATS, "gb")
        pre = (prl + prg) / 2; pae = (pal + pag) / 2
        te = (d.yr >= 2018).to_numpy()
        for nm, pr, pa in [("lin_pctmom", prl, pal), ("gb_pctmom", prg, pag), ("ens_lin+gb", pre, pae)]:
            m = metrics(d.y[te], pr[te], d.clim0[te], pa[te], d.above[te])
            rows.append({"lead": L, "model": nm, **m})
            print(L, nm, " ".join(f"{k}={v:.4f}" for k, v in m.items()
                                  if k in ("mae", "rmse", "spearman", "auc", "bss", "dir_acc_p", "majority")), flush=True)
        o = d[["id", "date", "dep", "yr", "month", "boat", "landing", "region", "tlb", "seg", "y", "clim0", "above", "pct"]
              + [f"y_{s}" for s in SPECIES] + [f"pct_{s}" for s in SPECIES]].assign(pred=pre, p_above=pae, lead=L)
        o.to_pickle(HERE / "data" / f"oof_ens_lead{L}.pkl")
        oof[L] = o[te]
        pd.DataFrame(rows).to_csv(HERE / "data" / "round3_results.csv", index=False)

    # breakdowns for ensemble
    out = []
    for L, o in oof.items():
        for by in ["month", "tlb", "region", "yr", "seg"]:
            for k, g in o.groupby(by):
                if len(g) < 150:
                    continue
                out.append({"lead": L, "by": by, "key": k, "n": len(g), "auc": auc(g.above, g.p_above),
                            "brier": np.mean((g.p_above - g.above) ** 2),
                            "brier_base": np.mean((g.above.mean() - g.above) ** 2),
                            "base_rate": g.above.mean(), "mean_p": g.p_above.mean(),
                            "mae": np.mean(np.abs(g.y - g.pred)), "mae_clim": np.mean(np.abs(g.y - g.clim0))})
        cal = calib_table(o.p_above, o.above)
        cal.to_csv(HERE / "data" / f"calib_lead{L}.csv")
        if L in (0, 1, 7):
            print("CALIB lead", L); print(cal.round(3).to_string())
    bd = pd.DataFrame(out); bd.to_csv(HERE / "data" / "round3_breakdowns.csv", index=False)

    # species: does the same model's P(above) also rank per-species outcomes? and a species-specific refit
    sp_rows = []
    for L in (0, 1, 7):
        d = load2(L)
        for s in SPECIES:
            ds = d[d[f"pct_{s}"].notna()].reset_index(drop=True).copy()
            ds["above"] = (ds[f"pct_{s}"] > 0.5).astype(float)
            ds["y"] = ds[f"y_{s}"]
            # species only meaningful where it is normally caught: comparable trips' share of nonzero
            # (rule computed on pre-2018 seasons only, so the row filter itself does not peek at test years)
            share = ds[ds.yr < 2018].groupby(["landing", "tlb", "month"]).above.mean().rename("share")
            ds = ds.join(share, on=["landing", "tlb", "month"])
            ds = ds[ds.share > 0.15].reset_index(drop=True)
            feats = FEATS + [f"fp_rs7_{s}", f"fp_rs14_{s}"]
            pr, pa = run(ds, feats, "gb")
            te = (ds.yr >= 2018).to_numpy()
            m = metrics(ds.y[te], pr[te], ds.y[te] * 0 + ds.y[~te].mean(), pa[te], ds.above[te])
            sp_rows.append({"lead": L, "species": s, **m})
            print("SPECIES", L, s, f"n={m['n']} base={m['base_rate_above']:.3f} auc={m['auc']:.4f} bss={m['bss']:.4f} acc={m['dir_acc_p']:.4f}", flush=True)
    pd.DataFrame(sp_rows).to_csv(HERE / "data" / "round3_species.csv", index=False)


if __name__ == "__main__":
    main()
