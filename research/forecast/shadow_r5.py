"""Parallel live SHADOW of the r5 candidate (research only; never shown to users).
r4-ens-v1 (shadow.py) stays frozen; this writes its own log shadow/forecasts_r5.csv.

r5 = r4 features + fri/sat/sun/weekend, retrained daily (as r4 live), plus a 30-day online level
correction: a model trained on reports < today-45 predicts trips REPORTED in [today-30, today-1];
their mean residual (above - p) per region (n >= 20) shifts each forecast's logit by 2x that residual.
Mirrors the backtest (monthly models 15-45 days old; online_recal.py p_30_2.0).

  python shadow_r5.py issue | score
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sys
import warnings

import numpy as np
import pandas as pd

import build_dataset as BD
import build_round2 as B2
import shadow as S
from run_round4 import add_feats
from run_round5 import F4, fit_ens

warnings.filterwarnings("ignore")
WORK = S.SH / "work_r5"
LOG = S.SH / "forecasts_r5.csv"
REPORT = S.SH / "REPORT_r5.md"
DOW = ["fri", "sat", "sun", "wkend"]
FEATS = F4 + DOW
MODEL_VERSION = "r5-cand-v1"
W, K, AGE = 30, 2.0, 45


def code_hash() -> str:
    h = hashlib.sha256()
    for f in ["build_dataset.py", "build_round2.py", "run_round2.py", "run_round4.py", "run_round5.py", "shadow.py", "shadow_r5.py"]:
        h.update((S.HERE / f).read_bytes())
    return h.hexdigest()[:10]


def add_dow(d):
    dow = d.dep.dt.day_of_week
    for k, nm in ((4, "fri"), (5, "sat"), (6, "sun")):
        d[nm] = (dow == k).astype(float)
    d["wkend"] = d.sat + d.sun
    return d


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def issue(today: pd.Timestamp):
    S.WORK = WORK
    db = S.snapshot()
    BD.DB = db; BD.OUT = WORK; B2.DATA = WORK
    import sqlite3
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    hist = BD.load_trips(con); con.close()
    cand = S.candidates(hist, today)
    BD.build(extra=cand.drop(columns=["cand_lead"]), cutoff=today)
    B2.main()
    out = []
    for L in S.LEADS:
        d = pd.read_pickle(WORK / f"ds2_lead{L}.pkl").reset_index(drop=True)
        d = add_dow(S.prep_train(add_feats(d, L)))
        tr = d[(d.id >= 0) & d.clim0.notna() & d.pct.notna()]
        te = d[(d.id < 0) & (d.dep == today + pd.Timedelta(days=L))].copy()
        if te.empty:
            continue
        te["clim0"] = te.clim0.fillna(tr.clim0.median())
        pa, pr = fit_ens(tr, te, FEATS)
        # online level correction from recent residuals of an older model
        old = tr[tr.date < today - pd.Timedelta(days=AGE)]
        rec = tr[(tr.date >= today - pd.Timedelta(days=W)) & (tr.date <= today - pd.Timedelta(days=1))].copy()
        adj = np.zeros(len(te))
        if len(rec):
            rec["p"], _ = fit_ens(old, rec, FEATS)
            g = rec.assign(res=rec.above - rec.p).groupby("region").res.agg(["mean", "size"])
            m = te.region.map(g["mean"].where(g["size"] >= 20)).fillna(0).to_numpy()
            adj = K * m
        te["p_above_raw"] = pa
        te["p_above"] = 1 / (1 + np.exp(-(logit(pa) + adj)))
        te["level_adj"] = adj; te["exp_fish_pad"] = pr; te["lead"] = L
        out.append(te)
        print(f"r5 lead {L}: {len(te)} candidates, train n={len(tr)}, recent n={len(rec)}, adj by region "
              f"{dict(zip(te.region, np.round(adj, 3)))}", flush=True)
    f = pd.concat(out, ignore_index=True)
    f["issue_date"] = today.date().isoformat()
    f["issued_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    f["dep"] = f.dep.dt.date.astype(str); f["expected_report_date"] = f.date.dt.date.astype(str)
    f["model_version"] = MODEL_VERSION; f["code_hash"] = code_hash(); f["live"] = True
    f["clim_fish_pad"] = f.clim0
    cols = S.KEY + ["dep", "expected_report_date", "region", "tl", "p_above", "p_above_raw", "level_adj",
                    "exp_fish_pad", "clim_fish_pad", "issued_at_utc", "model_version", "code_hash", "live"]
    f = f[cols]
    if LOG.exists():
        old = pd.read_csv(LOG)
        done = set(map(tuple, old[S.KEY].astype(str).values))
        f = f[[tuple(map(str, r)) not in done for r in f[S.KEY].values]]
    f.to_csv(LOG, mode="a", header=not LOG.exists(), index=False)
    print(f"r5 logged {len(f)} forecasts -> {LOG}")
    return db


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "issue":
        db = issue(pd.Timestamp(dt.date.today()))
        S.score(LOG, REPORT, db, "Live shadow test — r5 candidate (parallel to frozen r4)")
    elif cmd == "score":
        S.WORK = WORK
        S.score(LOG, REPORT, S.snapshot(), "Live shadow test — r5 candidate (parallel to frozen r4)")
