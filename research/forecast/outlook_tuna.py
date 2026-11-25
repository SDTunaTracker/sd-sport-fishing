"""SD TUNA fleet outlook, leads 1..7 (Surfline-style daily product prototype). Research only.

Cell = trip-length bucket x FISHING day (`dep`). Target: fleet tuna per angler-day (sum tuna / sum angler-days)
and share of trips with >= 1 tuna/angler-day ("good trip"). Issue date = dep - L; features use trips REPORTED
<= issue - 1 only. Monthly walk-forward (train on reports < month start - 15 d), scored 2019-26.

  python outlook_tuna.py backtest      # skill per lead vs persistence / climatology  -> data/outlook_tuna_bt.csv
  python outlook_tuna.py forecast      # live 7-day outlook from today                -> data/outlook_tuna_live.json
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor as HGR
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import build_dataset as BD
from harness import HERE

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DAYS = pd.date_range("2014-12-01", "2027-12-31")
TUNA = ["bluefin", "yellowfin", "bigeye", "albacore"]
TLBS = ["0.75", "1.0", "1.5", "2.0", "2.5+"]
LABEL = {"0.75": "Full day", "1.0": "Overnight", "1.5": "1.5 day", "2.0": "2 day", "2.5+": "2.5–3 day"}
START = pd.Timestamp("2019-01-01")
HL = (2, 5, 15, 30)


def trips(db: str) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    t = BD.load_trips(con); con.close()
    t = t[t.region == "san_diego"].copy()
    t["tuna"] = t[TUNA].sum(axis=1); t["tpad"] = t.tuna / t.ad
    t["good"] = (t.tpad >= 1).astype(float); t["one"] = 1.0
    return t


def decayed(t, mask, num, den, hl):
    """daily series (by report date) of decayed sum(num)/sum(den)."""
    a = np.exp(-np.log(2) / hl)
    s = t[mask].groupby("date")[[num, den]].sum().reindex(DAYS, fill_value=0)
    n = np.zeros(len(DAYS)); d = np.zeros(len(DAYS)); x = y = 0.0
    for i, (u, v) in enumerate(zip(s[num].to_numpy(), s[den].to_numpy())):
        x = x * a + u; y = y * a + v; n[i] = x; d[i] = y
    with np.errstate(invalid="ignore", divide="ignore"):
        return pd.Series(np.where(d > 0.5, n / d, np.nan), index=DAYS), pd.Series(d, index=DAYS)


def series(t):
    S = {}
    seg = np.where(t.tl <= 1.0, "in", "off")
    for tlb in TLBS:
        m = (t.tlb == tlb).to_numpy()
        for hl in HL:
            S[f"ft_{tlb}_h{hl}"], S[f"w_{tlb}_h{hl}"] = decayed(t, m, "tuna", "ad", hl)
        for hl in (5, 15):
            S[f"fg_{tlb}_h{hl}"], _ = decayed(t, m, "good", "one", hl)
    for sg in ("in", "off"):
        for hl in (5, 15):
            S[f"fs_{sg}_h{hl}"], _ = decayed(t, seg == sg, "tuna", "ad", hl)
    for hl in (5, 15, 30):
        S[f"fa_h{hl}"], _ = decayed(t, np.ones(len(t), bool), "tuna", "ad", hl)
    # last good (>=1/angler-day) report, any offshore trip
    gd = np.sort(t[(t.good == 1)].date.unique())
    j = np.searchsorted(gd, DAYS.values, side="right") - 1
    S["days_since_good"] = pd.Series(np.where(j >= 0, (DAYS.values - gd[np.maximum(j, 0)]) / np.timedelta64(1, "D"), 365), index=DAYS).clip(upper=365)
    return S


def clim(t, tlb, dep_doy, before_year):
    h = t[(t.tlb == tlb) & (t.dep.dt.year < before_year)]
    if len(h) < 30:
        return np.nan, np.nan
    dd = np.abs(h.dep.dt.dayofyear - dep_doy); dd = np.minimum(dd, 365 - dd)
    w = h[dd <= 15]
    return (w.tuna.sum() / w.ad.sum() if w.ad.sum() > 0 else np.nan), (w.good.mean() if len(w) else np.nan)


def features(S, t, tlb, dep, L, clim_cache):
    last = dep - pd.Timedelta(days=L + 1)
    f = {"lead": L, "tl": {"0.75": .75, "1.0": 1, "1.5": 1.5, "2.0": 2, "2.5+": 2.75}[tlb],
         "doy_s": np.sin(2 * np.pi * dep.dayofyear / 365.25), "doy_c": np.cos(2 * np.pi * dep.dayofyear / 365.25),
         "sat": float(dep.dayofweek == 5), "sun": float(dep.dayofweek == 6), "fri": float(dep.dayofweek == 4)}
    for hl in HL:
        f[f"ft_h{hl}"] = S[f"ft_{tlb}_h{hl}"].get(last, np.nan); f[f"w_h{hl}"] = S[f"w_{tlb}_h{hl}"].get(last, 0)
    for hl in (5, 15):
        f[f"fg_h{hl}"] = S[f"fg_{tlb}_h{hl}"].get(last, np.nan)
    sg = "in" if tlb in ("0.75", "1.0") else "off"
    for hl in (5, 15):
        f[f"fs_h{hl}"] = S[f"fs_{sg}_h{hl}"].get(last, np.nan)
    for hl in (5, 15, 30):
        f[f"fa_h{hl}"] = S[f"fa_h{hl}"].get(last, np.nan)
    f["days_since_good"] = S["days_since_good"].get(last, 365)
    k = (tlb, dep.dayofyear, dep.year)
    if k not in clim_cache:
        clim_cache[k] = clim(t, tlb, dep.dayofyear, dep.year)
    f["tclim"], f["gclim"] = clim_cache[k]
    return f


FEATS = None


def table(t, L):
    S = series(t)
    c = t.groupby(["tlb", "dep"]).agg(tuna=("tuna", "sum"), ad=("ad", "sum"), good=("good", "mean"), n=("tuna", "size"),
                                      date=("date", "max")).reset_index()
    c["rate"] = c.tuna / c.ad
    cache = {}
    F = pd.DataFrame([features(S, t, r.tlb, r.dep, L, cache) for r in c.itertuples()])
    return pd.concat([c, F], axis=1), S, cache


def models():
    kw = dict(learning_rate=0.03, max_iter=300, max_depth=3, min_samples_leaf=80, l2_regularization=5.0, random_state=0)
    lin = lambda: make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(), Ridge(alpha=30))
    return kw, lin


def fit_predict(tr, te, feats):
    kw, lin = models()
    X, Y = tr[feats], te[feats]
    r = (HGR(loss="poisson", **kw).fit(X, tr.rate, sample_weight=tr.ad).predict(Y)
         + np.expm1(lin().fit(X, np.log1p(tr.rate), ridge__sample_weight=tr.ad).predict(Y)).clip(0)) / 2
    g = (HGR(**kw).fit(X, tr.good, sample_weight=tr.n).predict(Y)
         + lin().fit(X, tr.good, ridge__sample_weight=tr.n).predict(Y)) / 2
    return r, np.clip(g, 0.01, 0.99)


def wcorr(a, b, w):
    ma, mb = np.average(a, weights=w), np.average(b, weights=w)
    return np.average((a - ma) * (b - mb), weights=w) / np.sqrt(np.average((a - ma) ** 2, weights=w) * np.average((b - mb) ** 2, weights=w))


def backtest(db):
    t = trips(db); rows = []; resid = {}
    for L in range(1, 8):
        c, _, _ = table(t, L)
        feats = [x for x in c.columns if x not in ("tlb", "dep", "tuna", "ad", "good", "n", "date", "rate", "lead")]
        c["pr"] = np.nan; c["pg"] = np.nan
        for ms in pd.date_range(START, c.dep.max(), freq="MS"):
            cut = ms - pd.Timedelta(days=15)
            te = (c.dep >= ms) & (c.dep < ms + pd.offsets.MonthBegin(1)); tr = c.date < cut
            if te.any():
                c.loc[te, "pr"], c.loc[te, "pg"] = fit_predict(c[tr], c[te], feats)
        e = c[(c.dep >= START) & c.pr.notna()].copy()
        e["persist"] = e.ft_h5.fillna(e.tclim).fillna(0)
        sel, hold = e.dep < "2023-01-01", e.dep >= "2023-01-01"
        lr = np.log1p(e.rate) - np.log1p(e.pr)
        resid[L] = {tlb: np.percentile(lr[(e.tlb == tlb) & sel], [10, 25, 75, 90]).tolist() for tlb in TLBS}
        row = dict(lead=L, cells=len(e))
        for nm, m in (("all", np.ones(len(e), bool)), ("hold23_26", hold.to_numpy())):
            x = e[m]
            row[f"r_model_{nm}"] = wcorr(x.pr, x.rate, x.ad); row[f"r_persist_{nm}"] = wcorr(x.persist, x.rate, x.ad)
            row[f"r_clim_{nm}"] = wcorr(x.tclim.fillna(0), x.rate, x.ad)
            row[f"mae_model_{nm}"] = np.average(np.abs(x.rate - x.pr), weights=x.ad)
            row[f"mae_persist_{nm}"] = np.average(np.abs(x.rate - x.persist), weights=x.ad)
            row[f"good_brier_{nm}"] = np.average((x.pg - x.good) ** 2, weights=x.n)
            row[f"good_brier_clim_{nm}"] = np.average((x.gclim.fillna(x.good.mean()) - x.good) ** 2, weights=x.n)
        rows.append(row); print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
        e.to_pickle(HERE / "data" / f"oof_outlook_tuna_L{L}.pkl")
    pd.DataFrame(rows).to_csv(HERE / "data" / "outlook_tuna_bt.csv", index=False)
    (HERE / "data" / "outlook_tuna_resid.json").write_text(json.dumps(resid))


def forecast(db, today):
    t = trips(db)
    t = t[t.date < today]
    resid = json.loads((HERE / "data" / "outlook_tuna_resid.json").read_text())
    out = []
    for L in range(1, 8):
        c, S, cache = table(t, L)
        feats = [x for x in c.columns if x not in ("tlb", "dep", "tuna", "ad", "good", "n", "date", "rate", "lead")]
        dep = today + pd.Timedelta(days=L)
        te = pd.DataFrame([features(S, t, tlb, dep, L, cache) for tlb in TLBS]); te["tlb"] = TLBS
        pr, pg = fit_predict(c, te, feats)
        for i, tlb in enumerate(TLBS):
            q = resid[str(L)][tlb]
            lo, hi = np.expm1(np.log1p(pr[i]) + q[0]), np.expm1(np.log1p(pr[i]) + q[3])
            out.append(dict(fishing_day=dep.date().isoformat(), lead=L, trip=LABEL[tlb], tlb=tlb,
                            tuna_per_angler_day=round(float(pr[i]), 2), range80=[round(float(max(lo, 0)), 2), round(float(hi), 2)],
                            p_good_trip=round(float(pg[i]), 2), recent_5d=round(float(te.ft_h5[i]), 2) if pd.notna(te.ft_h5[i]) else None,
                            recent_weight=round(float(te.w_h5[i]), 1), clim=round(float(te.tclim[i]), 2) if pd.notna(te.tclim[i]) else None))
        print(L, dep.date(), [(LABEL[tlb], round(float(pr[i]), 2), round(float(pg[i]), 2)) for i, tlb in enumerate(TLBS)], flush=True)
    last_rep = t.groupby("tlb").date.max().dt.date.astype(str).to_dict()
    recent = (t[t.date >= today - pd.Timedelta(days=7)].groupby("tlb").agg(trips=("tuna", "size"), tuna=("tuna", "sum"), ad=("ad", "sum")))
    recent["rate"] = (recent.tuna / recent.ad).round(2)
    meta = dict(issued=today.date().isoformat(), last_report_by_trip=last_rep,
                last7=recent.reset_index().to_dict("records"))
    (HERE / "data" / "outlook_tuna_live.json").write_text(json.dumps(dict(meta=meta, days=out), indent=1))


if __name__ == "__main__":
    import shadow as S
    S.WORK = S.SH / "work_outlook"
    db = S.snapshot().as_posix()
    if sys.argv[1] == "backtest":
        backtest(db)
    else:
        forecast(db, pd.Timestamp(dt.date.today()))
