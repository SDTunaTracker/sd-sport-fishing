"""Build a leak-free, per-trip modelling table for each forecast lead time.

Research only. Reads data/tracker_snapshot.db (a read-only snapshot copy).

Timing model
------------
trips.date is the REPORT (return) date. departure = date - max(0, round(tl-1)).
For a lead time L (days), the forecast is issued on the morning of
    issue = departure - L
and may use only:
  * catch reports with report date <= issue - 1
  * observed conditions with date <= issue - 1      (persistence of last obs)
  * NOAA upwelling with date <= issue - 31          (~30 day publish lag)
  * deterministic things about the trip itself      (date, moon, boat, landing,
                                                      trip length)
"Oracle" columns (prefix `orc_`) hold the OBSERVED conditions on the trip's
own days. They are never used in honest models; they are only used to measure
how much a perfect weather/ocean forecast could add (an upper bound).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DB = HERE / "data" / "tracker_snapshot.db"
OUT = HERE / "data"
LEADS = [0, 1, 3, 7, 14]
SPECIES = ["bluefin", "yellowfin", "yellowtail", "dorado"]


def load_trips(c) -> pd.DataFrame:
    t = pd.read_sql(
        "select id,date,boat,landing,region,trip_length,trip_length_days tl,anglers,"
        "bluefin,yellowfin,yellowtail,dorado,skipjack,bigeye,albacore,"
        "rockfish,calico_bass,sand_bass,halibut,lingcod,whitefish,sheephead,"
        "bonito,barracuda,white_sea_bass,trophy_count,is_half_day,source from trips", c)
    t["date"] = pd.to_datetime(t["date"])
    n0 = len(t)
    t = t[(t.tl >= 0.75) & (t.tl <= 3.5) & (t.is_half_day == 0)]
    t = t[(t.anglers >= 5) & (t.anglers <= 120)]
    # handover pitfalls: text-report fallback rows (often duplicates), exact dupes,
    # implausible rates (> 12 trophy fish per angler-day)
    t = t[t.source != "text_fallback"]
    t = t.drop_duplicates(["boat", "landing", "date", "tl"], keep="first")
    t = t[(t[SPECIES].sum(axis=1) / (t.anglers * t.tl)) <= 12]
    print(f"trips raw {n0:,} -> hygiene {len(t):,}")
    shift = np.maximum(0, np.round(t.tl - 1 + 1e-9).astype(int))  # matches sql_round for .5
    # sql_round rounds half away from zero; np.round is banker's. Do it explicitly.
    shift = np.maximum(0, np.floor(t.tl - 1 + 0.5).astype(int))
    t["dep"] = t["date"] - pd.to_timedelta(shift, unit="D")
    t["ad"] = t.anglers * t.tl  # angler-days
    for s in SPECIES:
        t[f"y_{s}"] = t[s] / t.ad
    t["y"] = t[SPECIES].sum(axis=1) / t.ad  # trophy fish per angler per day
    t["seg"] = np.where(t.tl <= 1.0, "in", "off")
    t["tlb"] = t.tl.map(lambda v: "0.75" if v < 1 else ("1.0" if v == 1 else
                        ("1.5" if v == 1.5 else ("2.0" if v == 2 else "2.5+"))))
    return t.reset_index(drop=True)


def daily_fleet(t: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    """Cumulative sums of fleet catch by report date, per (region, seg)."""
    out = {}
    for (reg, seg), g in t.groupby(["region", "seg"]):
        d = g.groupby("date").agg(ad=("ad", "sum"), n=("id", "size"),
                                  **{s: (s, "sum") for s in SPECIES}).reindex(days, fill_value=0)
        d["trophy"] = d[SPECIES].sum(axis=1)
        out[(reg, seg)] = d.cumsum()
    return out


def window(cs: pd.DataFrame, end: pd.Series, w: int, col: str) -> np.ndarray:
    """Sum of col over report dates in [end-w+1, end] using cumulative sums."""
    idx = cs.index
    e = idx.get_indexer(end)
    s = idx.get_indexer(end - pd.Timedelta(days=w))
    v = cs[col].to_numpy()
    return v[e] - np.where(s >= 0, v[np.clip(s, 0, None)], 0)


def climatology(t: pd.DataFrame, keys: list[str], name: str, halfwin=15) -> pd.Series:
    """Prior-YEARS mean of y in a +/-halfwin day-of-year window, by keys.
    Uses only seasons strictly before the trip's year -> no leakage."""
    t = t.copy()
    t["yr"] = t.dep.dt.year
    t["doy"] = t.dep.dt.dayofyear
    res = pd.Series(np.nan, index=t.index)
    cnt = pd.Series(0.0, index=t.index)
    for yr in sorted(t.yr.unique()):
        hist = t[(t.yr < yr) & t.y.notna()]  # candidate (future) rows never count as history
        cur = t[t.yr == yr]
        if hist.empty:
            continue
        # aggregate hist by keys x doy
        h = hist.groupby(keys + ["doy"]).agg(s=("y", "sum"), n=("y", "size")).reset_index()
        # circular window: expand each doy into +/- halfwin
        parts = []
        for off in range(-halfwin, halfwin + 1):
            hh = h.copy()
            hh["doy"] = ((hh.doy - 1 + off) % 366) + 1
            parts.append(hh)
        hw = pd.concat(parts).groupby(keys + ["doy"])[["s", "n"]].sum()
        m = cur[keys + ["doy"]].merge(hw, left_on=keys + ["doy"], right_index=True, how="left")
        res.loc[cur.index] = (m.s / m.n).to_numpy()
        cnt.loc[cur.index] = m.n.fillna(0).to_numpy()
    t[name] = res
    return res, cnt


def percentile_vs_history(t: pd.DataFrame, keys: list[str], fb_keys: list[str],
                          halfwin=15, min_n=25) -> pd.Series:
    """Mid-rank percentile of each trip's y within the PRIOR-YEARS distribution of
    trips with the same keys and departure day-of-year within +/-halfwin.
    Falls back to fb_keys when fewer than min_n comparison trips exist."""
    t = t.copy()
    t["yr"] = t.dep.dt.year
    t["doy"] = t.dep.dt.dayofyear
    out = pd.Series(np.nan, index=t.index)
    for kk in (fb_keys, keys):  # finer keys overwrite coarse where n is enough
        for yr in sorted(t.yr.unique()):
            hist = t[(t.yr < yr) & t.y.notna()]
            if hist.empty:
                continue
            cur = t[t.yr == yr]
            hg = {k: g for k, g in hist.groupby(kk)}
            for k, cg in cur.groupby(kk):
                if k not in hg:
                    continue
                h = hg[k]
                hd = h.doy.to_numpy(); hy = h.y.to_numpy()
                for doy, cd in cg.groupby("doy"):
                    dist = np.abs(hd - doy); dist = np.minimum(dist, 366 - dist)
                    ref = np.sort(hy[dist <= halfwin])
                    if len(ref) < min_n:
                        continue
                    v = cd.y.to_numpy()
                    lo = np.searchsorted(ref, v - 1e-9, "left"); hi = np.searchsorted(ref, v + 1e-9, "right")
                    out.loc[cd.index] = (lo + hi) / 2 / len(ref)
    return out


def boat_recent_safe(t, issue):
    """boat_recent over outcome rows only, aligned back to every row of t."""
    hist = t[t.y.notna()]
    b = hist[["boat", "landing", "date", "y"]].copy().sort_values("date")
    g = b.groupby(["boat", "landing"])
    b["b_ewm3"] = g.y.transform(lambda s: s.ewm(span=3).mean())
    b["b_last"] = b.y
    b["b_last_date"] = b.date
    b = b.groupby(["boat", "landing", "date"]).last().reset_index().rename(columns={"date": "key"}).sort_values("key")
    q = pd.DataFrame({"boat": t.boat, "landing": t.landing, "key": issue, "i": np.arange(len(t))}).sort_values("key")
    m = pd.merge_asof(q, b[["boat", "landing", "key", "b_ewm3", "b_last", "b_last_date"]],
                      on="key", by=["boat", "landing"], allow_exact_matches=False)
    m = m.set_index("i").sort_index()
    m["b_days_since"] = (m.key - m.b_last_date).dt.days
    return m[["b_ewm3", "b_last", "b_days_since"]]


def boat_recent(t: pd.DataFrame, asof: pd.Series) -> pd.DataFrame:
    """Boat's own recent trips (any length) reported strictly before `asof`."""
    b = t[["boat", "landing", "date", "y", "tl"]].copy().sort_values("date")
    g = b.groupby(["boat", "landing"])
    b["b_ewm3"] = g.y.transform(lambda s: s.ewm(span=3).mean())
    b["b_last"] = b.y
    b["b_last_date"] = b.date
    # collapse to one row per boat-date (last)
    b = b.groupby(["boat", "landing", "date"]).last().reset_index()
    q = pd.DataFrame({"boat": t.boat, "landing": t.landing, "key": asof, "i": t.index})
    q = q.sort_values("key")
    b = b.rename(columns={"date": "key"}).sort_values("key")
    m = pd.merge_asof(q, b[["boat", "landing", "key", "b_ewm3", "b_last", "b_last_date"]],
                      on="key", by=["boat", "landing"], allow_exact_matches=False)
    m = m.set_index("i").sort_index()
    m["b_days_since"] = (m.key - m.b_last_date).dt.days
    return m[["b_ewm3", "b_last", "b_days_since"]]


def conditions(c) -> pd.DataFrame:
    h = pd.read_sql("select * from historical_conditions", c)
    h["date"] = pd.to_datetime(h.date)
    h = h.set_index("date").sort_index()
    cols = ["sst_nearshore", "sst_9mile", "sst_offshore", "sst_cortez", "sst_anomaly",
            "sst_gradient", "sst_warming_trend", "wind_speed", "wind_direction_deg",
            "wind_is_upwelling", "wind_is_offshore", "swell_height", "swell_period",
            "pressure", "pressure_trend"]
    h = h[cols].apply(pd.to_numeric, errors="coerce")
    h = h.groupby(level=0).mean()
    full = pd.date_range("2014-12-01", h.index.max())
    h = h.reindex(full)
    # derived: SST change over 7/14/30 days, 7-day wind mean
    for loc in ["sst_offshore", "sst_9mile", "sst_cortez", "sst_nearshore"]:
        h[f"{loc}_d7"] = h[loc] - h[loc].shift(7)
        h[f"{loc}_d30"] = h[loc] - h[loc].shift(30)
    h["wind7"] = h.wind_speed.rolling(7, min_periods=3).mean()
    h["swell7"] = h.swell_height.rolling(7, min_periods=3).mean()
    up = pd.read_sql("select date, upwelling_index from upwelling_obs", c)
    up["date"] = pd.to_datetime(up.date)
    up = up.groupby("date").upwelling_index.mean().reindex(full)
    h["upw"] = up
    h["upw30"] = up.rolling(30, min_periods=10).mean()
    return h


def prep_candidates(x: pd.DataFrame) -> pd.DataFrame:
    """Future trips to forecast (no outcome). Needs boat, landing, region, tl, tlb, dep."""
    x = x.copy()
    shift = np.maximum(0, np.floor(x.tl - 1 + 0.5).astype(int))
    x["date"] = x.dep + pd.to_timedelta(shift, unit="D")
    x["seg"] = np.where(x.tl <= 1.0, "in", "off")
    for col in ["anglers", "ad", "y"] + SPECIES + [f"y_{s}" for s in SPECIES]:
        x[col] = np.nan
    x["is_half_day"] = 0
    return x


def build(extra: pd.DataFrame | None = None, cutoff: pd.Timestamp | None = None, leads=None):
    """extra: candidate future trips (see prep_candidates); cutoff: drop every trip
    REPORTED on/after this date (simulates what was known at issue time)."""
    leads = LEADS if leads is None else leads
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    t = load_trips(c)
    if cutoff is not None:
        t = t[t.date < cutoff].reset_index(drop=True)
    if extra is not None:
        t = pd.concat([t, prep_candidates(extra)], ignore_index=True)
    h = conditions(c)
    days = pd.date_range("2014-12-01", "2027-12-31")
    fleet = daily_fleet(t[t.y.notna()], days)

    # climatology (prior years, doy window) at several pooling levels
    t["clim_boat"], t["clim_boat_n"] = climatology(t, ["boat", "landing", "tlb"], "clim_boat")
    t["clim_land"], t["clim_land_n"] = climatology(t, ["landing", "tlb"], "clim_land")
    t["clim_reg"], t["clim_reg_n"] = climatology(t, ["region", "tlb"], "clim_reg")
    for s in SPECIES:
        tt = t.assign(y=t[f"y_{s}"])
        t[f"clim_land_{s}"], _ = climatology(tt, ["landing", "tlb"], "x")

    t["pct"] = percentile_vs_history(t, ["landing", "tlb"], ["region", "tlb"]).where(t.y.notna())
    for s in SPECIES:
        t[f"pct_{s}"] = percentile_vs_history(t.assign(y=t[f"y_{s}"]), ["landing", "tlb"], ["region", "tlb"]).where(t.y.notna())
    print("pct coverage", t.pct.notna().mean(), "share above 0.5", (t.pct > 0.5).mean())

    # deterministic trip-day features
    t["doy"] = t.dep.dt.dayofyear
    t["month"] = t.dep.dt.month
    t["doy_s"] = np.sin(2 * np.pi * t.doy / 365.25)
    t["doy_c"] = np.cos(2 * np.pi * t.doy / 365.25)
    t["dow"] = t.dep.dt.dayofweek
    # moon (deterministic) -- simple synodic-phase calc from a known new moon
    ref = pd.Timestamp("2000-01-06 18:14")
    ph = ((t.dep + pd.Timedelta(hours=12) - ref).dt.total_seconds() / 86400 / 29.530588) % 1
    t["moon_phase"] = ph
    t["moon_illum"] = (1 - np.cos(2 * np.pi * ph)) / 2
    t["moon_s"] = np.sin(2 * np.pi * ph)
    t["moon_c"] = np.cos(2 * np.pi * ph)

    # oracle: observed conditions on the departure day (never used honestly)
    orc = h.reindex(t.dep).reset_index(drop=True)
    orc.columns = [f"orc_{k}" for k in orc.columns]
    t = pd.concat([t, orc], axis=1)

    for L in leads:
        d = t.copy()
        issue = d.dep - pd.Timedelta(days=L)
        last = issue - pd.Timedelta(days=1)  # last report/obs date available
        d["lead"] = L
        # persistence conditions
        hc = h.reindex(last).reset_index(drop=True)
        hc.columns = [f"c_{k}" for k in hc.columns]
        d = pd.concat([d, hc], axis=1)
        d["c_upw_lag"] = h.upw.reindex(issue - pd.Timedelta(days=31)).to_numpy()
        d["c_upw30_lag"] = h.upw30.reindex(issue - pd.Timedelta(days=31)).to_numpy()
        # fleet momentum, by own region x segment and by the other segment
        for which in ["own", "other"]:
            for w in [3, 7, 14, 30]:
                num = {k: np.full(len(d), np.nan) for k in ["trophy", "ad", "n"] + SPECIES}
                for (reg, seg), cs in fleet.items():
                    segsel = d.seg if which == "own" else d.seg.map({"in": "off", "off": "in"})
                    m = ((d.region == reg) & (segsel == seg)).to_numpy()
                    if not m.any():
                        continue
                    for k in num:
                        num[k][m] = window(cs, last[m], w, k)
                p = f"f{which}{w}"
                d[f"{p}_n"] = num["n"]
                d[f"{p}_tpad"] = np.where(num["ad"] > 0, num["trophy"] / np.maximum(num["ad"], 1), np.nan)
                if w in (7, 14):
                    for s in SPECIES:
                        d[f"{p}_{s}"] = np.where(num["ad"] > 0, num[s] / np.maximum(num["ad"], 1), np.nan)
        # SD fleet as a whole for OC/LA (SD offshore fleet often leads)
        cs = fleet[("san_diego", "off")]
        for w in [7, 14]:
            d[f"fsdoff{w}_tpad"] = window(cs, last, w, "trophy") / np.maximum(window(cs, last, w, "ad"), 1)
        # last-year same time momentum anomaly is in climatology; momentum anomaly vs clim:
        d["mom_ratio7"] = (d.fown7_tpad + 0.05) / (d.clim_reg + 0.05)
        d["mom_ratio14"] = (d.fown14_tpad + 0.05) / (d.clim_reg + 0.05)
        br = boat_recent_safe(t, issue)
        d = pd.concat([d, br.reset_index(drop=True)], axis=1)
        d.to_pickle(OUT / f"ds_lead{L}.pkl")
        print(L, d.shape)


if __name__ == "__main__":
    build()
