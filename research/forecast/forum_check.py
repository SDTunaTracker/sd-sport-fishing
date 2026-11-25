"""EARLY, EXPLORATORY check of BloodyDecks forum_signals against the forecast's misses.

    python forum_check.py                 # pull data/paddies.db from origin/main (read-only) and run
    python forum_check.py path/to/paddies.db

This is NOT a point-in-time test. The first forum_signals rows are a 150-day
backfill: fetched_at is when we scraped the post, not when it was knowable, so
anything here is a "does it line up?" look, never proof that the signal would
have improved a live forecast. Writes data/forum_check.md and nothing else.

Two questions:
  A. Same trip (explanatory): when a post about a trip says birds were bad / bait
     was poor, did that trip come in below what the model expected?
     residual = above - p_above (OOF, round-4 best, lead 1).
  B. Forward (forecastable shape): does the mean bird_pressure / bait_quality in
     posts PUBLISHED in the 7 days before a trip's issue date line up with that
     trip's residual? (Region-level; uses published_at as a stand-in for
     knowable-at, which the backfill can't give us honestly.)
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).parent
MAIN_REPO = Path(r"C:/Users/Jenelle/Projects/sd-sport-fishing")
OUT = HERE / "data" / "forum_check.md"
LEAD = 1
MIN_CONF = 0.7
SIGS = ["bird_pressure", "bait_quality", "water_temp_f"]
rng = np.random.default_rng(0)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fetch_db() -> Path:
    dst = HERE / "data" / "ext" / "paddies_main.db"
    blob = subprocess.run(["git", "-C", str(MAIN_REPO), "show", "origin/main:data/paddies.db"],
                          capture_output=True, check=True).stdout
    dst.write_bytes(blob)
    return dst


def load_signals(db: Path) -> pd.DataFrame | None:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    if not con.execute("select 1 from sqlite_master where name='forum_signals'").fetchone():
        return None
    s = pd.read_sql("select * from forum_signals", con)
    con.close()
    s = s[(s.match_confidence.fillna(0) >= MIN_CONF) & s.boat.notna() & s.trip_date.notna()].copy()
    s["dep"] = pd.to_datetime(s.trip_date, errors="coerce")
    s["pub"] = pd.to_datetime(s.published_at, errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    return s[s.dep.notna()]


def perm_spearman(x, y, n=2000):
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 10 or np.unique(x).size < 2:
        return len(x), np.nan, np.nan
    r = spearmanr(x, y).statistic
    null = np.array([spearmanr(rng.permutation(x), y).statistic for _ in range(n)])
    return len(x), r, float(np.mean(np.abs(null) >= abs(r)))


def by_level(df, col):
    g = df.groupby(col).agg(n=("resid", "size"), said=("p_above", "mean"),
                           happened=("above", "mean"), resid=("resid", "mean"))
    return g


def main():
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else fetch_db()
    s = load_signals(db)
    lines = ["# Forum signals vs forecast misses (EARLY, exploratory)", "",
             f"Source: `{db.name}`. Lead {LEAD} out-of-fold forecasts (r4 best). "
             "Backfill rows: fetched_at is not a real knowable-at time, so this is a "
             "'does it line up' look only, not a point-in-time test.", ""]
    if s is None or s.empty:
        lines.append("**No usable forum_signals rows** (table missing or no rows with "
                     f"match_confidence ≥ {MIN_CONF}). Nothing to check yet.")
        OUT.write_text("\n".join(lines), encoding="utf-8"); print("\n".join(lines)); return

    o = pd.read_pickle(HERE / "data" / f"oof_best_lead{LEAD}.pkl")
    o = o[o.p_above.notna() & o.above.notna()].copy()
    o["resid"] = o.above - o.p_above
    # forum trip_date is departure; allow +-1 day slop on the match
    rows = []
    for k in (0, -1, 1):
        x = s.assign(dep=s.dep + pd.Timedelta(days=k)).merge(
            o[["boat", "dep", "landing", "region", "tlb", "above", "p_above", "resid", "pct"]],
            on=["boat", "dep"], how="inner").assign(slop=abs(k))
        rows.append(x)
    m = (pd.concat(rows).sort_values("slop")
         .drop_duplicates(["id"]).drop_duplicates(["source_id", "boat"]))
    lines += [f"forum_signals rows (conf ≥ {MIN_CONF}): {len(s):,}; matched to a forecast trip: "
              f"{len(m):,} ({m.boat.nunique()} boats, {m.dep.min():%Y-%m-%d} … {m.dep.max():%Y-%m-%d}). "
              f"Field coverage among matched: " +
              ", ".join(f"{c} {m[c].notna().mean():.0%}" for c in SIGS), ""]

    # A. same-trip
    lines += ["## A. Same trip: did the post's conditions line up with the model's miss?", "",
              "| signal | n | Spearman vs residual | perm p | Spearman vs trip pct |", "|---|---|---|---|---|"]
    for c in SIGS:
        n, r, p = perm_spearman(m[c].to_numpy(float), m.resid.to_numpy(float))
        _, r2, _ = perm_spearman(m[c].to_numpy(float), m.pct.to_numpy(float), n=1)
        lines.append(f"| {c} | {n} | {r:+.3f} | {p:.3f} | {r2:+.3f} |")
    for c in ["bird_pressure", "bait_quality", "water_color"]:
        if m[c].notna().sum() >= 10:
            g = by_level(m[m[c].notna()], c)
            lines += ["", f"By {c}:", "", "| level | n | model said | happened | mean residual |", "|---|---|---|---|---|"]
            lines += [f"| {k} | {int(r.n)} | {r.said:.0%} | {r.happened:.0%} | {r.resid:+.2f} |" for k, r in g.iterrows()]

    # B. forward: region mean of posts published in [issue-7, issue-1]
    pub = s.merge(o[["boat", "region"]].drop_duplicates("boat"), on="boat", how="inner")
    pub = pub[pub.pub.notna()]
    tgt = o[(o.dep >= pub.pub.min() + pd.Timedelta(days=8)) & (o.dep <= pub.pub.max() + pd.Timedelta(days=8))].copy()
    tgt["issue"] = tgt.dep - pd.Timedelta(days=LEAD)
    lines += ["", "## B. Forward: region-mean signal from posts published in the 7 days before issue", "",
              "| signal | n trips | Spearman vs residual | perm p |", "|---|---|---|---|"]
    for c in ["bird_pressure", "bait_quality"]:
        vals = np.full(len(tgt), np.nan)
        for reg, g in tgt.groupby("region"):
            p = pub[(pub.region == reg) & pub[c].notna()]
            if p.empty:
                continue
            daily = p.groupby("pub")[c].agg(["sum", "size"])
            for i, iss in zip(g.index, g.issue):
                w = daily[(daily.index >= iss - pd.Timedelta(days=7)) & (daily.index <= iss - pd.Timedelta(days=1))]
                if w["size"].sum() >= 2:
                    vals[tgt.index.get_indexer([i])[0]] = w["sum"].sum() / w["size"].sum()
        n, r, pp = perm_spearman(vals, tgt.resid.to_numpy(float), n=500)
        lines.append(f"| {c} | {n} | {r:+.3f} | {pp:.3f} |")

    lines += ["", "Reading this: a residual is (beat normal ? 1 : 0) − model probability. A negative "
              "Spearman for bird_pressure means bad-bird trips did worse than the model expected. "
              "With a few hundred matched trips, |r| < ~0.1 is indistinguishable from nothing; "
              "trip reports are also self-selected (people post more about great or awful days)."]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
