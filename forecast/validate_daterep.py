"""Held-out re-baseline: V0 (return-date + single-day conditions) vs
V1 (departure-date + span-averaged conditions) for the offshore species.

Purpose: measure how much the audit-flagged skew (live forecaster joins
return-date single-day conditions; backtest calibrates on span-averaged
departure-date conditions) is actually distorting held-out accuracy.

This does NOT flip live scoring. It builds V1 in parallel with the current
V0 and reports V0 vs V1 metrics side-by-side so we get an honest corrected
baseline before deciding to wire the live path.

Isolation:
  * V0 and V1 are computed from the SAME trips filter (offshore, hygiene).
  * The response variable (per-angler catch) is IDENTICAL between them --
    the only differences are the DATE the trip is bucketed to and the
    conditions row that gets joined.
  * Inshore aggregations must be byte-identical (shift=0, span=1 for
    trip_length_days<=1.0). Verified explicitly.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "forecast"))

# Shared source of truth for the date shift + span-average semantics.
from src.trip_conditions import departure_date, span_days, averaged_conditions

# Baseline species-scoring + metrics we already validated in an earlier task.
from validate_candidates import (
    species_baseline,
    _BLUEFIN_BREAKS, _YELLOWFIN_BREAKS, _DORADO_BREAKS,
    direction_accuracy, mae, brier,
    actual_ratings_train_test,
)

DB   = ROOT / "tracker.db"
OUT  = ROOT / "forecast" / "daterep_report.txt"

# historical_conditions numeric columns we care about for the baseline scorer.
_HC_NUMERIC = [
    "sst_offshore", "sst_nearshore", "sst_anomaly",
    "sst_gradient", "wind_speed", "swell_height", "moon_illum",
]

_lines: list[str] = []
def emit(s: str = "") -> None:
    _lines.append(s)
    print(s, flush=True)


# ─── Load ─────────────────────────────────────────────────────────────────────
def load_trips(con) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT date AS filed_date, boat, landing, trip_length_days, anglers, "
        "       bluefin, yellowfin, yellowtail, dorado "
        "FROM trips "
        "WHERE is_half_day=0 AND anglers>=5 "
        "  AND trip_length_days>=0.75 AND trip_length_days<=2.0",
        con,
    )
    df["filed_date"] = pd.to_datetime(df["filed_date"])
    return df


def load_hc(con) -> dict[str, dict]:
    """Return {'YYYY-MM-DD': {col: value}} keyed as backtest expects."""
    hc = pd.read_sql("SELECT * FROM historical_conditions", con)
    for c in _HC_NUMERIC:
        if c in hc.columns:
            hc[c] = pd.to_numeric(hc[c], errors="coerce")
    # historical_conditions stores swell_height in metres (per src/forecast.py
    # fallback conversion). Convert to feet for scoring.
    if "swell_height" in hc.columns:
        hc["swell_height_ft"] = hc["swell_height"] * 3.28084
    if "moon_phase_name" not in hc.columns:
        hc["moon_phase_name"] = None
    out: dict[str, dict] = {}
    for _, row in hc.iterrows():
        # Trim any timestamp fluff to YYYY-MM-DD.
        d = str(row["date"])[:10]
        out[d] = row.to_dict()
    return out


# ─── V0: filed-date grouping, single-day conditions ───────────────────────────
def aggregate_by_filed(trips: pd.DataFrame, segment: str) -> pd.DataFrame:
    if segment == "offshore":
        sub = trips[trips["trip_length_days"] > 1.0].copy()
    else:
        sub = trips[trips["trip_length_days"] <= 1.0].copy()
    agg = sub.groupby("filed_date").agg(
        n_trips        = ("boat",    "count"),
        total_anglers  = ("anglers", "sum"),
        bluefin_total  = ("bluefin", "sum"),
        yellowfin_total= ("yellowfin","sum"),
        dorado_total   = ("dorado",  "sum"),
        yellowtail_total=("yellowtail","sum"),
        avg_trip_length= ("trip_length_days", "mean"),
    ).reset_index()
    agg = agg[agg["n_trips"] >= 2].reset_index(drop=True)
    for sp in ("bluefin", "yellowfin", "dorado", "yellowtail"):
        agg[f"{sp}_pa"] = agg[f"{sp}_total"] / agg["total_anglers"]
    agg["date_key"] = agg["filed_date"]
    return agg


def attach_v0_conditions(agg: pd.DataFrame, hc: dict[str, dict]) -> pd.DataFrame:
    """V0: join historical_conditions on filed_date (single day)."""
    keys = agg["filed_date"].dt.strftime("%Y-%m-%d")
    for c in ["sst_offshore", "sst_nearshore", "sst_anomaly",
              "sst_gradient", "wind_speed", "swell_height_ft", "moon_illum"]:
        agg[c] = keys.map(lambda k: hc.get(k, {}).get(c))
        agg[c] = pd.to_numeric(agg[c], errors="coerce")
    return agg


# ─── V1: dep-date grouping, span-averaged conditions ──────────────────────────
def aggregate_by_dep(trips: pd.DataFrame, segment: str) -> pd.DataFrame:
    if segment == "offshore":
        sub = trips[trips["trip_length_days"] > 1.0].copy()
    else:
        sub = trips[trips["trip_length_days"] <= 1.0].copy()
    # Reconstruct departure date via the shared helper (uses sql_round so it
    # matches the SQLite ROUND semantics backtest.py has been running).
    sub["dep_date"] = pd.to_datetime([
        departure_date(fd.date(), tl)
        for fd, tl in zip(sub["filed_date"], sub["trip_length_days"])
    ])
    agg = sub.groupby("dep_date").agg(
        n_trips        = ("boat",    "count"),
        total_anglers  = ("anglers", "sum"),
        bluefin_total  = ("bluefin", "sum"),
        yellowfin_total= ("yellowfin","sum"),
        dorado_total   = ("dorado",  "sum"),
        yellowtail_total=("yellowtail","sum"),
        avg_trip_length= ("trip_length_days", "mean"),
    ).reset_index()
    agg = agg[agg["n_trips"] >= 2].reset_index(drop=True)
    for sp in ("bluefin", "yellowfin", "dorado", "yellowtail"):
        agg[f"{sp}_pa"] = agg[f"{sp}_total"] / agg["total_anglers"]
    agg["date_key"] = agg["dep_date"]
    return agg


def attach_v1_conditions(agg: pd.DataFrame, hc: dict[str, dict]) -> pd.DataFrame:
    """V1: for each row, average historical_conditions over span_days(avg_trip_length)
    starting at dep_date, via the shared helper."""
    cols = ["sst_offshore", "sst_nearshore", "sst_anomaly",
            "sst_gradient", "wind_speed", "swell_height_ft", "moon_illum"]
    for c in cols:
        agg[c] = np.nan
    for i, row in agg.iterrows():
        n = span_days(row["avg_trip_length"])
        d = row["dep_date"].date()
        avg = averaged_conditions(hc, d, n, cols)
        if avg is None:
            continue
        for c in cols:
            agg.at[i, c] = avg.get(c)
    for c in cols:
        agg[c] = pd.to_numeric(agg[c], errors="coerce")
    return agg


# ─── Evaluation ───────────────────────────────────────────────────────────────
def score_and_measure(agg: pd.DataFrame, species: str, breaks: list,
                      sst_col: str, label: str) -> dict:
    """Score baseline + actual rating on train/test split. Return metric dict."""
    date_ts = agg["date_key"]
    is_train = date_ts <= pd.Timestamp("2024-12-31")
    is_test  = (date_ts >= pd.Timestamp("2025-01-01")) & (date_ts <= pd.Timestamp("2025-12-31"))

    # Baseline species score for every row.
    def _score(r):
        return species_baseline(
            sst_f     = r[sst_col],
            anomaly   = r["sst_anomaly"],
            moon      = r["moon_illum"],
            wind      = r["wind_speed"],
            swell_ft  = r["swell_height_ft"],
            breaks    = breaks,
        )
    scores = agg.apply(_score, axis=1)

    # Actual rating = percentile vs TRAIN distribution (mid-rank on ties).
    resp = pd.DataFrame({"species_pa": agg[f"{species}_pa"].values})
    actual = actual_ratings_train_test(resp, pd.Series(is_train.values))
    actual.index = agg.index

    # Naive seasonal baseline: per-month mean actual on train.
    month = agg["date_key"].dt.month
    m_mean = actual[is_train].groupby(month[is_train]).mean()
    global_mean = actual[is_train].mean() if is_train.any() else 5.5
    naive = month.map(m_mean).fillna(global_mean)

    def _metrics(pred, act):
        return {
            "n":             int(len(pred)),
            "direction_acc": direction_accuracy(pred, act) if len(pred) else float("nan"),
            "mae":           mae(pred, act)                if len(pred) else float("nan"),
            "brier":         brier(pred, act)              if len(pred) else float("nan"),
        }

    return {
        "label":    label,
        "n_train":  int(is_train.sum()),
        "n_test":   int(is_test.sum()),
        "model":    _metrics(scores[is_test], actual[is_test]),
        "naive":    _metrics(naive[is_test],  actual[is_test]),
    }


# ─── Reporting helpers ────────────────────────────────────────────────────────
def print_species_block(species: str, v0: dict, v1: dict) -> None:
    emit()
    emit("=" * 78)
    emit(f"SPECIES: {species.upper()}   (offshore)")
    emit("=" * 78)
    emit(f"  V0 (return-date, single-day):  train={v0['n_train']:,}  test={v0['n_test']:,}")
    emit(f"  V1 (dep-date, span-averaged):  train={v1['n_train']:,}  test={v1['n_test']:,}")
    emit()
    emit(f"  {'metric':<20} {'V0 model':>10} {'V1 model':>10} {'delta':>10}   "
         f"{'V0 naive':>10} {'V1 naive':>10}")
    for k in ("direction_acc", "mae", "brier"):
        vm0, vm1 = v0["model"][k], v1["model"][k]
        vn0, vn1 = v0["naive"][k], v1["naive"][k]
        d = vm1 - vm0
        emit(f"  {k:<20} {vm0:>10.4f} {vm1:>10.4f} {d:>+10.4f}   "
             f"{vn0:>10.4f} {vn1:>10.4f}")

    # Verdict
    dir_delta = v1["model"]["direction_acc"] - v0["model"]["direction_acc"]
    mae_delta = v1["model"]["mae"] - v0["model"]["mae"]         # lower better
    bri_delta = v1["model"]["brier"] - v0["model"]["brier"]     # lower better
    n_test    = v1["n_test"]
    emit()
    if n_test < 30:
        emit(f"  VERDICT: TEST SLICE TOO SMALL (n={n_test}) -- cannot conclude.")
    elif dir_delta > 0 and mae_delta <= 0 and bri_delta <= 0:
        emit(f"  VERDICT: V1 IMPROVES  direction {dir_delta*100:+.1f}pp, "
             f"MAE {mae_delta:+.3f}, Brier {bri_delta:+.4f} on n={n_test}. "
             "Aligning live scoring to the calibrated representation would help.")
    elif dir_delta < -0.02 or mae_delta > 0.10 or bri_delta > 0.01:
        emit(f"  VERDICT: V1 REGRESSES  direction {dir_delta*100:+.1f}pp, "
             f"MAE {mae_delta:+.3f}, Brier {bri_delta:+.4f} on n={n_test}. ")
        emit("  *** CRITICAL: the corrected representation performs WORSE, which")
        emit("  *** implies the backtest calibration itself may be tracking the")
        emit("  *** old return-date single-day representation rather than the")
        emit("  *** shift+span it claims. Investigate before shipping either way.")
    else:
        emit(f"  VERDICT: V0 ~= V1  direction {dir_delta*100:+.1f}pp, "
             f"MAE {mae_delta:+.3f}, Brier {bri_delta:+.4f} on n={n_test}. "
             "The date-representation skew is not measurably distorting held-out "
             "accuracy at the daily-segment level.")


# ─── Isolation check ──────────────────────────────────────────────────────────
def inshore_isolation_check(trips: pd.DataFrame) -> None:
    emit()
    emit("=" * 78)
    emit("ISOLATION: inshore V0 vs V1 must be byte-identical")
    emit("=" * 78)
    v0 = aggregate_by_filed(trips, "inshore").sort_values("filed_date").reset_index(drop=True)
    v1 = aggregate_by_dep  (trips, "inshore").sort_values("dep_date").reset_index(drop=True)

    # Rename date column for a like-for-like diff.
    v0 = v0.rename(columns={"filed_date": "date_"})
    v1 = v1.rename(columns={"dep_date":   "date_"})
    v0 = v0.drop(columns=["date_key"])
    v1 = v1.drop(columns=["date_key"])

    emit(f"  V0 inshore rows: {len(v0):,}")
    emit(f"  V1 inshore rows: {len(v1):,}")
    if len(v0) != len(v1):
        emit("  *** ROWS DIFFER -- isolation FAILED")
        return
    # Compare per column.
    all_equal = True
    for col in v0.columns:
        if col == "date_":
            eq = (v0["date_"].values == v1["date_"].values).all()
        else:
            a, b = v0[col].values, v1[col].values
            eq = np.allclose(a, b, equal_nan=True) if np.issubdtype(a.dtype, np.number) else (a == b).all()
        if not eq:
            emit(f"  * mismatch in column {col}")
            all_equal = False
    if all_equal:
        emit("  All columns byte-identical -- inshore isolation OK.")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    emit("=" * 78)
    emit("V0 (return-date, single-day) vs V1 (departure-date, span-averaged)")
    emit("Held-out re-baseline for offshore species; time split train<=2024, test=2025.")
    emit("=" * 78)

    emit()
    emit("Sanity: shift + span from src.trip_conditions.sql_round match SQLite ROUND")
    from datetime import date as _date
    for tl in (0.75, 1.0, 1.5, 2.0, 2.5):
        emit(f"  trip_length_days={tl}: "
             f"dep_shift_days={ (departure_date(_date(2025,8,15), tl) - _date(2025,8,15)).days :>3}, "
             f"span_days={span_days(tl)}")

    trips = load_trips(con)
    emit(f"\ntrips (after hygiene: anglers>=5, half-day filtered, tl in [0.75, 2.0]): {len(trips):,}")

    hc = load_hc(con)
    emit(f"historical_conditions rows loaded: {len(hc):,}")

    # V0 offshore
    v0_off = aggregate_by_filed(trips, "offshore")
    v0_off = attach_v0_conditions(v0_off, hc)
    v0_off_pre = len(v0_off)
    v0_off = v0_off.dropna(subset=["sst_offshore"])
    emit(f"\nV0 offshore day-groups: {v0_off_pre:,}   after dropping rows with no HC/sst_offshore: {len(v0_off):,}")

    # V1 offshore
    v1_off = aggregate_by_dep(trips, "offshore")
    v1_off = attach_v1_conditions(v1_off, hc)
    v1_off_pre = len(v1_off)
    v1_off = v1_off.dropna(subset=["sst_offshore"])
    emit(f"V1 offshore day-groups: {v1_off_pre:,}   after dropping rows with no HC/sst_offshore: {len(v1_off):,}")

    # Per species
    for species, breaks in [
        ("bluefin",   _BLUEFIN_BREAKS),
        ("yellowfin", _YELLOWFIN_BREAKS),
        ("dorado",    _DORADO_BREAKS),
    ]:
        v0_m = score_and_measure(v0_off, species, breaks, "sst_offshore",
                                 label=f"V0 {species}")
        v1_m = score_and_measure(v1_off, species, breaks, "sst_offshore",
                                 label=f"V1 {species}")
        print_species_block(species, v0_m, v1_m)

    # Isolation check
    inshore_isolation_check(trips)

    # Summary
    emit()
    emit("=" * 78)
    emit("Written parallel V0 / V1 -- no live production behavior changed. If any")
    emit("species shows a clean V1 IMPROVES verdict AND the isolation check passes,")
    emit("the next atomic task is a single-file wire-up of daily_segment_stats (or")
    emit("the forecaster's join) to use trip_conditions helpers for offshore only.")
    emit("=" * 78)

    OUT.write_text("\n".join(_lines), encoding="utf-8")
    print(f"\n(report saved to {OUT.relative_to(ROOT)})")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
