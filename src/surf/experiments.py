"""One-change-at-a-time accuracy experiments on MOP Hs at the buoy sites.

Every experiment fits on TRAIN only (2022-04-01 .. 2025-03-31) and is scored
on TEST (2025-04-01 .. now) against the raw MOP-ECMWF control. A change is
kept only if TEST RMSE improves at most sites (and on the pooled mean).
Results are appended to the shared surf-accuracy-log.md by hand, with the
numbers printed here.

    python -m src.surf.experiments            # all experiments
    python -m src.surf.experiments E1 E2
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import verify as V

CACHE = Path(V.OUT_DIR) / "aligned.pkl"


def aligned(sites=tuple(V.SITES)) -> dict[str, pd.DataFrame]:
    """{site: hourly frame with obs_hs/tp/dp, ec_*, ww_*, nc_*} (cached)."""
    if CACHE.exists():
        return pd.read_pickle(CACHE)
    out = {}
    for s in sites:
        o = V.load_obs(s)
        cols = {"obs": o}
        for k, tag in (("ecmwf_fc", "ec"), ("forecast", "ww"), ("nowcast", "nc")):
            cols[tag] = V.load_model(s, k)
        df = pd.concat({tag: f for tag, f in cols.items()}, axis=1)
        df.columns = [f"{a}_{b}" for a, b in df.columns]
        out[s] = df.dropna(subset=["obs_hs", "ec_hs"])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, CACHE)
    return out


def rmse(f, o):
    e = np.asarray(f) - np.asarray(o)
    e = e[~np.isnan(e)]
    return float(np.sqrt(np.mean(e ** 2))) if len(e) else float("nan")


def split(df):
    return df[df.index < V.SPLIT], df[df.index >= V.SPLIT]


def run_exp(name, desc, fit_predict, data):
    """fit_predict(train_df, test_df) -> test predictions (Series)."""
    rows, base_all, new_all = [], [], []
    for s, df in data.items():
        tr, te = split(df)
        if len(tr) < 500 or len(te) < 200:
            continue
        pred = fit_predict(tr, te)
        b, n = rmse(te["ec_hs"], te["obs_hs"]), rmse(pred, te["obs_hs"])
        rows.append((s, b, n))
        base_all.append(b)
        new_all.append(n)
    better = sum(1 for _, b, n in rows if n < b - 1e-4)
    print(f"\n## {name}: {desc}")
    print("| site | control RMSE | new RMSE | change |")
    print("|---|---|---|---|")
    for s, b, n in rows:
        print(f"| {s} {V.SITES[s]} | {b:.3f} | {n:.3f} | {100 * (n - b) / b:+.1f}% |")
    mb, mn = np.mean(base_all), np.mean(new_all)
    keep = better > len(rows) / 2 and mn < mb
    print(f"| **mean** | {mb:.3f} | {mn:.3f} | {100 * (mn - mb) / mb:+.1f}% |")
    print(f"Better at {better}/{len(rows)} sites -> {'KEEP' if keep else 'REJECT'}")
    return keep, mb, mn


# ── experiments ─────────────────────────────────────────────────────────────

def e1_scale(tr, te):
    """Per-site multiplicative bias correction: obs ≈ a·ec (least squares through 0)."""
    a = float((tr["ec_hs"] * tr["obs_hs"]).sum() / (tr["ec_hs"] ** 2).sum())
    return te["ec_hs"] * a


def e2_linear(tr, te):
    """Per-site linear correction obs ≈ a + b·ec."""
    b, a = np.polyfit(tr["ec_hs"], tr["obs_hs"], 1)
    return a + b * te["ec_hs"]


def e3_blend(tr, te):
    """ECMWF/WW3 blend, both scale-corrected on train, weight fit on train."""
    t = tr.dropna(subset=["ww_hs"])
    a_ec = float((t["ec_hs"] * t["obs_hs"]).sum() / (t["ec_hs"] ** 2).sum())
    a_ww = float((t["ww_hs"] * t["obs_hs"]).sum() / (t["ww_hs"] ** 2).sum())
    best_w, best = 1.0, 1e9
    for w in np.linspace(0, 1, 21):
        r = rmse(w * a_ec * t["ec_hs"] + (1 - w) * a_ww * t["ww_hs"], t["obs_hs"])
        if r < best:
            best, best_w = r, w
    ww = te["ww_hs"].fillna(te["ec_hs"] * a_ec / a_ww)
    return best_w * a_ec * te["ec_hs"] + (1 - best_w) * a_ww * ww


def e4_season(tr, te):
    """Per-site, per-season (DJF/MAM/JJA/SON) multiplicative correction."""
    def season(idx):
        return ((idx.month % 12) // 3)
    out = pd.Series(index=te.index, dtype=float)
    glob = float((tr["ec_hs"] * tr["obs_hs"]).sum() / (tr["ec_hs"] ** 2).sum())
    for q in range(4):
        t = tr[season(tr.index) == q]
        a = float((t["ec_hs"] * t["obs_hs"]).sum() / (t["ec_hs"] ** 2).sum()) if len(t) > 200 else glob
        m = season(te.index) == q
        out[m] = te["ec_hs"][m] * a
    return out


def e5_quantile(tr, te):
    """Per-site quantile mapping of ec_hs onto the train obs distribution."""
    qs = np.linspace(0.01, 0.99, 99)
    xq, yq = np.quantile(tr["ec_hs"], qs), np.quantile(tr["obs_hs"], qs)
    return pd.Series(np.interp(te["ec_hs"], xq, yq), index=te.index)


def e6_smooth(tr, te):
    """Light time smoothing of the forecast (3 h centered)."""
    a = float((tr["ec_hs"] * tr["obs_hs"]).sum() / (tr["ec_hs"] ** 2).sum())
    return (te["ec_hs"] * a).rolling(3, center=True, min_periods=1).mean()


EXPERIMENTS = {
    "E1": ("per-site multiplicative bias correction (on top of raw ECMWF)", e1_scale),
    "E2": ("per-site linear correction a + b·Hs", e2_linear),
    "E3": ("ECMWF/WW3 blend, each scale-corrected, weight fit on train", e3_blend),
    "E4": ("per-site, per-season multiplicative correction", e4_season),
    "E5": ("per-site quantile mapping", e5_quantile),
    "E6": ("E1 + 3 h smoothing of the forecast", e6_smooth),
}


def main(argv=None) -> int:
    names = (argv if argv is not None else sys.argv[1:]) or list(EXPERIMENTS)
    data = aligned()
    for n in names:
        desc, fn = EXPERIMENTS[n]
        run_exp(n, desc, fn, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def fit_production(path: Path = Path(__file__).with_name("calibration.json")) -> dict:
    """Refit the adopted correction (E3) on ALL data for production.

    Writes {site: {a_ec, a_ww, w_ec}} plus the TEST scores that justified it.
    Reported accuracy stays the TEST numbers in surf-accuracy-log.md.
    """
    import json
    data = aligned()
    out = {"method": "E3: w*a_ec*Hs_ecmwf + (1-w)*a_ww*Hs_ww3, per CDIP validation site",
           "fitOn": "2022-04-01..latest (all data, after TEST acceptance)", "sites": {}}
    for s, df in data.items():
        t = df.dropna(subset=["ww_hs"])
        a_ec = float((t["ec_hs"] * t["obs_hs"]).sum() / (t["ec_hs"] ** 2).sum())
        a_ww = float((t["ww_hs"] * t["obs_hs"]).sum() / (t["ww_hs"] ** 2).sum())
        best = (1e9, 1.0)
        for w in np.linspace(0, 1, 21):
            best = min(best, (rmse(w * a_ec * t["ec_hs"] + (1 - w) * a_ww * t["ww_hs"], t["obs_hs"]), w))
        out["sites"][s] = {"a_ec": round(a_ec, 4), "a_ww": round(a_ww, 4), "w_ec": round(float(best[1]), 2)}
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out
