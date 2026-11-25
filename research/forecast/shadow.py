"""Live SHADOW test of the round-4 forecast model. Research only, never shown to users.

  python shadow.py issue            # forecast today's candidates at leads 0,1,3,7,14 (append-only log)
  python shadow.py score            # score every logged forecast whose trip has reported
  python shadow.py replay A B STEP  # honest replay of past issue dates (separate log)

Reads the live tracker.db READ-ONLY via a fresh SQLite backup snapshot; writes only
under research/forecast/shadow/.

What is forecast: every boat that reported a trip in the last 21 days, for each
trip-length bucket it ran in the last 45 days (its usual length), departing
today+L. Most candidates never run (boats don't sail every day); only trips that
actually run and report are scored, which is exactly how the backtest was scored.
A forecast counts only if it was logged BEFORE departure (issued_at is recorded).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import build_dataset as BD
import build_round2 as B2
from harness import auc
from run_round2 import BASE, CAT, MOM_PCT, MOM_RAW, gb, lin_cls, lin_reg
from run_round4 import NEW, add_feats

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).parent
SH = HERE / "shadow"
WORK = SH / "work_live"  # replay uses its own dir so the two never clash
LIVE_DB = Path(r"C:/Users/Jenelle/Projects/sd-sport-fishing/tracker.db")
LEADS = [0, 1, 3, 7, 14]
FEATS = BASE + MOM_RAW + MOM_PCT + NEW
MODEL_VERSION = "r4-ens-v1"
KEY = ["issue_date", "lead", "boat", "landing", "tlb"]


def code_hash() -> str:
    h = hashlib.sha256()
    for f in ["build_dataset.py", "build_round2.py", "run_round2.py", "run_round4.py", "shadow.py"]:
        h.update((HERE / f).read_bytes())
    return h.hexdigest()[:10]


def snapshot() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / "snap.db"
    src = sqlite3.connect(f"file:{LIVE_DB.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    src.backup(dst); dst.close(); src.close()
    return out


def candidates(hist: pd.DataFrame, today: pd.Timestamp) -> pd.DataFrame:
    h = hist[hist.date < today]
    active = h[h.date >= today - pd.Timedelta(days=21)][["boat", "landing"]].drop_duplicates()
    recent = h[h.date >= today - pd.Timedelta(days=45)].merge(active, on=["boat", "landing"])
    c = (recent.groupby(["boat", "landing", "region", "tlb"]).tl
         .agg(lambda s: s.mode().iloc[0]).reset_index())
    rows = []
    for L in LEADS:
        x = c.copy(); x["dep"] = today + pd.Timedelta(days=L); x["cand_lead"] = L
        rows.append(x)
    x = pd.concat(rows, ignore_index=True)
    x["id"] = -(np.arange(len(x)) + 1)
    x["trip_length"] = "candidate"
    return x


def prep_train(d: pd.DataFrame) -> pd.DataFrame:
    k = 20.0
    cl = d.clim_land.where(d.clim_land.notna(), d.clim_reg)
    nb = d.clim_boat_n.fillna(0)
    d["clim0"] = (nb * d.clim_boat.fillna(cl) + k * cl) / (nb + k)
    d["above"] = (d.pct > 0.5).astype(float)
    return d


def fit_predict(tr: pd.DataFrame, te: pd.DataFrame):
    Xtr, Xte = tr[FEATS + CAT].copy(), te[FEATS + CAT].copy()
    pa = (lin_cls(FEATS).fit(Xtr, tr.above).predict_proba(Xte)[:, 1])
    pr = np.maximum(0, lin_reg(FEATS).fit(Xtr, tr.y).predict(Xte))
    Gtr, Gte = Xtr.copy(), Xte.copy()
    for c in CAT:
        cats = pd.Categorical(pd.concat([Gtr[c], Gte[c]])).categories
        Gtr[c] = pd.Categorical(Gtr[c], categories=cats); Gte[c] = pd.Categorical(Gte[c], categories=cats)
    pa = (pa + gb(FEATS, True).fit(Gtr, tr.above).predict_proba(Gte)[:, 1]) / 2
    pr = (pr + np.maximum(0, gb(FEATS, False).fit(Gtr, tr.y).predict(Gte))) / 2
    return pa, pr


def issue(today: pd.Timestamp, db: Path, log: Path, live: bool):
    BD.DB = db; BD.OUT = WORK; B2.DATA = WORK
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    hist = BD.load_trips(con); con.close()
    cand = candidates(hist, today)
    BD.build(extra=cand.drop(columns=["cand_lead"]), cutoff=today)
    B2.main()
    out = []
    for L in LEADS:
        d = pd.read_pickle(WORK / f"ds2_lead{L}.pkl").reset_index(drop=True)
        d = prep_train(add_feats(d, L))
        tr = d[(d.id >= 0) & d.clim0.notna() & d.pct.notna()]
        # training labels must be public before today: report date <= today-1 (cutoff did this)
        te = d[(d.id < 0) & (d.dep == today + pd.Timedelta(days=L))].copy()
        if te.empty:
            continue
        te["clim0"] = te.clim0.fillna(tr.clim0.median())
        pa, pr = fit_predict(tr, te)
        te["p_above"] = pa; te["exp_fish_pad"] = pr; te["lead"] = L
        out.append(te)
        print(f"lead {L}: {len(te)} candidates, train n={len(tr)}", flush=True)
    f = pd.concat(out, ignore_index=True)
    f["issue_date"] = today.date().isoformat()
    f["issued_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    f["dep"] = f.dep.dt.date.astype(str); f["expected_report_date"] = f.date.dt.date.astype(str)
    f["model_version"] = MODEL_VERSION; f["code_hash"] = code_hash(); f["live"] = live
    f["clim_fish_pad"] = f.clim0
    cols = KEY + ["dep", "expected_report_date", "region", "tl", "p_above", "exp_fish_pad",
                  "clim_fish_pad", "issued_at_utc", "model_version", "code_hash", "live"]
    f = f[cols]
    if log.exists():
        old = pd.read_csv(log)
        done = set(map(tuple, old[KEY].astype(str).values))
        f = f[[tuple(map(str, r)) not in done for r in f[KEY].values]]
    f.to_csv(log, mode="a", header=not log.exists(), index=False)
    print(f"logged {len(f)} forecasts -> {log}")


def outcomes(db: Path) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    t = BD.load_trips(con); con.close()
    t["pct"] = BD.percentile_vs_history(t, ["landing", "tlb"], ["region", "tlb"])
    t["dep"] = t.dep.dt.date.astype(str)
    return t.drop_duplicates(["boat", "landing", "dep", "tlb"])[["boat", "landing", "dep", "tlb", "y", "pct", "anglers", "date"]]


def score(log: Path, report: Path, db: Path, title: str):
    f = pd.read_csv(log, dtype={"tlb": str})
    o = outcomes(db)
    m = f.merge(o, on=["boat", "landing", "dep", "tlb"], how="inner")
    if f.live.astype(str).eq("True").all():
        # live log: the forecast must have been written before the trip's catch was reported
        # (report lands the evening of expected_report_date at the earliest)
        issued_local = (pd.to_datetime(m.issued_at_utc, utc=True).dt.tz_convert("America/Los_Angeles")
                        .dt.tz_localize(None).dt.normalize())
        m = m[issued_local <= pd.to_datetime(m.expected_report_date)]
    m = m[m.pct.notna()]
    m["above"] = (m.pct > 0.5).astype(float)
    m.to_csv(report.with_suffix(".scored.csv"), index=False)
    bt = {0: 0.773, 1: 0.747, 3: 0.716, 7: 0.682, 14: 0.634}
    lines = [f"# {title}", "", f"Generated {dt.datetime.now().isoformat(timespec='minutes')}. "
             f"Forecasts logged: {len(f):,}; matched to a reported trip: {len(m):,}.", "",
             "| lead | n trips | beat normal | AUC (backtest) | Brier | BSS vs base | acc p>.5 | top-20% hit | bottom-20% hit | MAE fish/angler/day (clim) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for L, g in m.groupby("lead"):
        if len(g) < 5:
            lines.append(f"| {L} | {len(g)} | — | too few | | | | | | |"); continue
        b = np.mean((g.p_above - g.above) ** 2); b0 = np.mean((g.above.mean() - g.above) ** 2)
        q = g.p_above.rank(pct=True)
        lines.append(f"| {L} | {len(g)} | {g.above.mean():.0%} | {auc(g.above, g.p_above):.3f} ({bt[L]}) | {b:.3f} | "
                     f"{1 - b / b0 if b0 > 0 else float('nan'):.3f} | {np.mean((g.p_above > .5) == g.above):.0%} | "
                     f"{g.above[q > .8].mean():.0%} | {g.above[q <= .2].mean():.0%} | "
                     f"{np.mean(np.abs(g.y - g.exp_fish_pad)):.2f} ({np.mean(np.abs(g.y - g.clim_fish_pad)):.2f}) |")
    cal = m.assign(bin=pd.cut(m.p_above, [0, .2, .4, .6, .8, 1])).groupby("bin", observed=True).agg(
        n=("above", "size"), said=("p_above", "mean"), happened=("above", "mean"))
    lines += ["", "Calibration (all leads):", "", "| forecast | n | said | happened |", "|---|---|---|---|"]
    lines += [f"| {k} | {r.n} | {r.said:.0%} | {r.happened:.0%} |" for k, r in cal.iterrows()]
    lines += ["", "Note: the backtest AUCs in brackets are over 2019–26; a few weeks of shadow data "
              "has wide error bars (±0.03–0.05 AUC at n≈500)."]
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    cmd = sys.argv[1]
    SH.mkdir(exist_ok=True)
    if cmd == "issue":
        today = pd.Timestamp(dt.date.today())
        issue(today, snapshot(), SH / "forecasts.csv", live=True)
        score(SH / "forecasts.csv", SH / "REPORT.md", WORK / "snap.db", "Live shadow test")
    elif cmd == "score":
        score(SH / "forecasts.csv", SH / "REPORT.md", snapshot(), "Live shadow test")
    elif cmd == "replay":
        WORK = SH / "work_replay"
        a, b, step = pd.Timestamp(sys.argv[2]), pd.Timestamp(sys.argv[3]), int(sys.argv[4])
        db = snapshot()
        for day in pd.date_range(a, b, freq=f"{step}D"):
            print("REPLAY", day.date(), flush=True)
            issue(day, db, SH / "replay_forecasts.csv", live=False)
        score(SH / "replay_forecasts.csv", SH / "REPLAY_REPORT.md", db, "Replay (past issue dates, cutoff-simulated)")
