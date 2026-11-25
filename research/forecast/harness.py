"""Walk-forward evaluation harness (research only).

Folds: for each test year Y, train on trips whose REPORT date is at least
15 days before Jan 1 of Y (so every training label was public before any
test-year forecast could be issued at lead <= 14), test on departures in Y.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
TEST_YEARS = list(range(2018, 2027))
SPECIES = ["bluefin", "yellowfin", "yellowtail", "dorado"]


def load(lead: int) -> pd.DataFrame:
    d = pd.read_pickle(HERE / "data" / f"ds_lead{lead}.pkl")
    # shrunk climatology: boat-level pulled toward landing-level, landing toward region
    k = 20.0
    cl = d.clim_land.where(d.clim_land.notna(), d.clim_reg)
    nb = d.clim_boat_n.fillna(0)
    cb = d.clim_boat.fillna(cl)
    d["clim0"] = (nb * cb + k * cl) / (nb + k)
    # "above normal" = trip beat the median of comparable past trips
    # (same landing x trip length x +/-15 days, prior years only).
    d["above"] = (d.pct > 0.5).astype(float)
    d["above_mean"] = (d.y > d.clim0).astype(float)
    d["yr"] = d.dep.dt.year
    return d[d.clim0.notna() & d.pct.notna()].reset_index(drop=True)


def folds(d: pd.DataFrame):
    for Y in TEST_YEARS:
        cut = pd.Timestamp(f"{Y}-01-01") - pd.Timedelta(days=15)
        tr = d.index[d.date < cut]
        te = d.index[d.yr == Y]
        if len(te):
            yield Y, tr, te


def metrics(y, pred, clim, p_above=None, above=None) -> dict:
    y, pred, clim = map(np.asarray, (y, pred, clim))
    above_mean = y > clim
    above = above_mean if above is None else np.asarray(above).astype(bool)
    m = {
        "n": len(y),
        "mae": np.mean(np.abs(y - pred)),
        "rmse": np.sqrt(np.mean((y - pred) ** 2)),
        "spearman": pd.Series(pred).corr(pd.Series(y), method="spearman"),
        # direction: does the model say above/below this trip's normal correctly
        # regression direction: predicted vs actual above this trip's climatological MEAN
        "dir_acc_mean": np.mean((pred > clim) == above_mean),
        "majority_mean": max(above_mean.mean(), 1 - above_mean.mean()),
        "base_rate_above": above.mean(),
    }
    if p_above is not None:
        p = np.clip(np.asarray(p_above), 1e-4, 1 - 1e-4)
        m["brier"] = np.mean((p - above) ** 2)
        m["brier_clim"] = np.mean((above.mean() - above) ** 2)  # in-sample base rate (generous)
        m["dir_acc_p"] = np.mean((p > 0.5) == above)
        m["majority"] = max(above.mean(), 1 - above.mean())
        m["bss"] = 1 - m["brier"] / m["brier_clim"]
        m["auc"] = auc(above, p)
    return m


def auc(lbl, score):
    lbl = np.asarray(lbl).astype(bool)
    r = pd.Series(score).rank().to_numpy()
    n1 = lbl.sum(); n0 = len(lbl) - n1
    if n1 == 0 or n0 == 0:
        return np.nan
    return (r[lbl].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def calib_table(p, above, bins=10) -> pd.DataFrame:
    df = pd.DataFrame({"p": p, "a": np.asarray(above).astype(float)})
    df["bin"] = pd.cut(df.p, np.linspace(0, 1, bins + 1), include_lowest=True)
    return df.groupby("bin", observed=True).agg(n=("a", "size"), pred=("p", "mean"), obs=("a", "mean"))
