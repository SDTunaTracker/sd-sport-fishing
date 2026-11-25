"""Round-2 features added on top of ds_lead{L}.pkl -> ds2_lead{L}.pkl

* Percentile momentum: recent trips' percentile-vs-normal (pct) instead of raw
  fish/angler/day, so a rockfish full-day and a 2.5-day tuna trip are comparable.
  - boat's own recent pct (last trip, EWM over 3 and 8 trips)
  - fleet mean pct over 3/7/14/30 days at landing x tlb, landing, region x seg, region
  - species-level fleet pct (region x seg, 7/14 days)
* MUR satellite SST spatial features (warm-water extent/distance, fronts, banks),
  as of issue-2 days (NRT latency).
* ENSO (ONI) and PDO monthly indices, value of the month 2 months before issue.
All "as of" logic: only trips REPORTED on or before issue-1.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
SPECIES = ["bluefin", "yellowfin", "yellowtail", "dorado"]
DAYS = pd.date_range("2014-12-01", "2027-12-31")
DATA = HERE / "data"  # shadow runs point this at their own work dir


def grouped_cumsum(t, keys, col):
    """dict key -> (cumsum of col, cumsum of count) over calendar DAYS by report date."""
    ok = t[t[col].notna()]
    out = {}
    for k, g in ok.groupby(keys):
        s = g.groupby("date")[col].agg(["sum", "size"]).reindex(DAYS, fill_value=0)
        out[k if isinstance(k, tuple) else (k,)] = (s["sum"].cumsum().to_numpy(), s["size"].cumsum().to_numpy())
    return out


def window_mean(d, keys, cs, last, w, min_n=1):
    e = DAYS.get_indexer(last)
    b = DAYS.get_indexer(last - pd.Timedelta(days=w))
    res = np.full(len(d), np.nan); cnt = np.zeros(len(d))
    kk = list(zip(*[d[k] for k in keys]))
    for i, k in enumerate(kk):
        if k not in cs:
            continue
        sm, n = cs[k]
        s = sm[e[i]] - (sm[b[i]] if b[i] >= 0 else 0)
        c = n[e[i]] - (n[b[i]] if b[i] >= 0 else 0)
        cnt[i] = c
        if c >= min_n:
            res[i] = s / c
    return res, cnt


def boat_pct(t, issue):
    b = t[t.pct.notna()][["boat", "landing", "date", "pct"]].sort_values("date").copy()
    g = b.groupby(["boat", "landing"]).pct
    b["bp_last"] = b.pct
    b["bp_ewm3"] = g.transform(lambda s: s.ewm(span=3).mean())
    b["bp_ewm8"] = g.transform(lambda s: s.ewm(span=8).mean())
    b["bp_ntrips"] = g.cumcount() + 1
    b = b.groupby(["boat", "landing", "date"]).last().reset_index().rename(columns={"date": "key"})
    q = pd.DataFrame({"boat": t.boat, "landing": t.landing, "key": issue, "i": np.arange(len(t))}).sort_values("key")
    m = pd.merge_asof(q, b.sort_values("key")[["boat", "landing", "key", "bp_last", "bp_ewm3", "bp_ewm8", "bp_ntrips"]],
                      on="key", by=["boat", "landing"], allow_exact_matches=False)
    return m.set_index("i").sort_index()[["bp_last", "bp_ewm3", "bp_ewm8", "bp_ntrips"]].reset_index(drop=True)


def indices():
    def parse(fn):
        rows = []
        for line in (HERE / "data" / "ext" / fn).read_text().splitlines()[1:]:
            p = line.split()
            if len(p) == 13 and p[0].isdigit():
                for m, v in enumerate(p[1:], 1):
                    v = float(v)
                    if v > -90:
                        rows.append((pd.Timestamp(int(p[0]), m, 1), v))
        return pd.Series(dict(rows)).sort_index()
    return parse("oni.txt"), parse("pdo.txt")


def main(leads=(0, 1, 3, 7, 14)):
    mur = pd.read_pickle(HERE / "data" / "ext" / "mur_daily.pkl")
    mur.columns = [f"m_{c}" for c in mur.columns]
    oni, pdo = indices()
    for L in leads:
        d = pd.read_pickle(DATA / f"ds_lead{L}.pkl").reset_index(drop=True)
        issue = d.dep - pd.Timedelta(days=L)
        last = issue - pd.Timedelta(days=1)
        for keys, nm in [(["landing", "tlb"], "lt"), (["landing"], "l"), (["region", "seg"], "rs"), (["region"], "r")]:
            cs = grouped_cumsum(d, keys, "pct")
            for w in (3, 7, 14, 30):
                d[f"fp_{nm}{w}"], d[f"fp_{nm}{w}_n"] = window_mean(d, keys, cs, last, w)
        for s in SPECIES:
            cs = grouped_cumsum(d, ["region", "seg"], f"pct_{s}")
            for w in (7, 14):
                d[f"fp_rs{w}_{s}"], _ = window_mean(d, ["region", "seg"], cs, last, w)
        d = pd.concat([d, boat_pct(d, issue)], axis=1)
        mm = mur.reindex(issue - pd.Timedelta(days=2)).reset_index(drop=True)
        d = pd.concat([d, mm], axis=1)
        mon = (issue.dt.to_period("M") - 2).dt.to_timestamp()
        d["oni"] = oni.reindex(mon).to_numpy()
        d["pdo"] = pdo.reindex(mon).to_numpy()
        d.to_pickle(DATA / f"ds2_lead{L}.pkl")
        print(L, d.shape, d[["fp_lt7", "bp_ewm3", "m_warm68_dist", "oni"]].notna().mean().round(3).to_dict(), flush=True)


if __name__ == "__main__":
    main()
