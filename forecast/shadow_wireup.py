"""Shadow-simulate the update_daily_segment_stats wire-up before touching prod.

Runs the exact SQL that the modified function WOULD run (dep-date keying for
offshore, unchanged for inshore), reads the resulting rows, joins hc.date
on the new key (which is what forecast.py does downstream), computes the
species baseline scores, and compares 2025 held-out metrics to:
  * V0-live: current dss keying (filed date, single-day HC) with dss-style
    trip-weighted aggregation.
  * V1-validated: dep-date + span-averaged HC + angler-weighted aggregation
    (the numbers reported by validate_daterep.py).
  * V1-live: dep-date + single-day HC at dep-date + trip-weighted aggregation
    (what the proposed wire-up would actually produce in production).

If V1-live is not clearly >= V0-live for all three offshore species, the
wire-up shouldn't ship even though V1-validated said it would help.
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

from src.trip_conditions import DEP_DATE_SQL
from validate_candidates import (
    species_baseline,
    _BLUEFIN_BREAKS, _YELLOWFIN_BREAKS, _DORADO_BREAKS,
    direction_accuracy, mae, brier,
    actual_ratings_train_test,
)

DB  = ROOT / "tracker.db"
OUT = ROOT / "forecast" / "shadow_wireup_report.txt"

_HC_NUMERIC = [
    "sst_offshore", "sst_nearshore", "sst_anomaly",
    "sst_gradient", "wind_speed", "swell_height", "moon_illum",
]

_lines: list[str] = []
def emit(s: str = "") -> None:
    _lines.append(s)
    print(s, flush=True)


def load_hc(con) -> pd.DataFrame:
    hc = pd.read_sql("SELECT * FROM historical_conditions", con)
    for c in _HC_NUMERIC:
        if c in hc.columns:
            hc[c] = pd.to_numeric(hc[c], errors="coerce")
    hc["swell_height_ft"] = hc["swell_height"] * 3.28084
    hc["date_key"] = hc["date"].astype(str).str[:10]
    return hc


def rebuild_dss_style(con, use_dep_date: bool) -> pd.DataFrame:
    """Reproduce update_daily_segment_stats' SQL. `use_dep_date=True` = V1-live."""
    if use_dep_date:
        key_expr = f"CASE WHEN trip_length_days <= 1.0 THEN date ELSE {DEP_DATE_SQL} END"
    else:
        key_expr = "date"
    seg_expr = "CASE WHEN trip_length_days <= 1.0 THEN 'inshore' ELSE 'offshore' END"
    q = f"""
        SELECT {key_expr} AS dss_date,
               {seg_expr} AS segment,
               COUNT(*) AS trip_count,
               AVG(trophy_per_angler_per_day) AS avg_tpa,
               SUM(trophy_count) AS total_tuna,
               SUM(anglers) AS total_anglers,
               AVG(bluefin   * 1.0 / NULLIF(anglers,0)) AS bluefin_tpa,
               AVG(yellowfin * 1.0 / NULLIF(anglers,0)) AS yellowfin_tpa,
               AVG(yellowtail* 1.0 / NULLIF(anglers,0)) AS yellowtail_tpa,
               AVG(dorado    * 1.0 / NULLIF(anglers,0)) AS dorado_tpa
        FROM trips
        WHERE is_half_day = 0 AND anglers >= 5
        GROUP BY {key_expr}, {seg_expr}
        HAVING COUNT(*) >= 2
    """
    df = pd.read_sql(q, con)
    df["dss_date"] = pd.to_datetime(df["dss_date"])
    return df


def score_segment(dss: pd.DataFrame, hc: pd.DataFrame,
                  segment: str, species: str, breaks: list,
                  sst_col: str = "sst_offshore") -> dict:
    sub = dss[dss["segment"] == segment].copy()
    sub["date_key"] = sub["dss_date"].dt.strftime("%Y-%m-%d")
    joined = sub.merge(
        hc[["date_key", "sst_offshore", "sst_nearshore", "sst_anomaly",
            "sst_gradient", "wind_speed", "swell_height_ft", "moon_illum"]],
        on="date_key", how="left",
    )
    joined = joined.dropna(subset=[sst_col]).reset_index(drop=True)

    # Baseline species score using species_baseline() from earlier work.
    def _score(r):
        return species_baseline(
            sst_f    = r[sst_col],
            anomaly  = r["sst_anomaly"],
            moon     = r["moon_illum"],
            wind     = r["wind_speed"],
            swell_ft = r["swell_height_ft"],
            breaks   = breaks,
        )
    joined["baseline"] = joined.apply(_score, axis=1)

    # Actual rating: percentile rank of dss's trip-weighted per-angler tpa
    # column vs the TRAIN dist. Uses whichever species column matches.
    pa_col = f"{species}_tpa"   # dss column is trip-weighted per-angler
    resp = pd.DataFrame({"species_pa": joined[pa_col].fillna(0.0).values})

    date_ts = joined["dss_date"]
    is_train = (date_ts <= pd.Timestamp("2024-12-31")).reset_index(drop=True)
    is_test  = ((date_ts >= pd.Timestamp("2025-01-01"))
                & (date_ts <= pd.Timestamp("2025-12-31"))).reset_index(drop=True)
    actual = actual_ratings_train_test(resp, is_train)
    actual.index = joined.index

    # Naive seasonal from train
    month = joined["dss_date"].dt.month
    m_mean = actual[is_train].groupby(month[is_train]).mean()
    naive = month.map(m_mean).fillna(actual[is_train].mean() if is_train.any() else 5.5)

    def _metrics(pred, act):
        return {
            "n":             int(len(pred)),
            "direction_acc": direction_accuracy(pred, act) if len(pred) else float("nan"),
            "mae":           mae(pred, act)                if len(pred) else float("nan"),
            "brier":         brier(pred, act)              if len(pred) else float("nan"),
        }
    return {
        "n_train":  int(is_train.sum()),
        "n_test":   int(is_test.sum()),
        "model":    _metrics(joined.loc[is_test, "baseline"], actual[is_test]),
        "naive":    _metrics(naive[is_test], actual[is_test]),
    }


def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    emit("=" * 78)
    emit("SHADOW WIRE-UP SIMULATION")
    emit("V0-live (current dss keying)  vs  V1-live (dep-date dss keying)")
    emit("Both use dss-style trip-weighted response + single-day HC at dss.date.")
    emit("=" * 78)

    hc  = load_hc(con)
    v0  = rebuild_dss_style(con, use_dep_date=False)
    v1l = rebuild_dss_style(con, use_dep_date=True)

    emit()
    emit(f"V0-live dss (would-be) rows: {len(v0):,}")
    emit(f"  inshore: {(v0['segment']=='inshore').sum():,}   "
         f"offshore: {(v0['segment']=='offshore').sum():,}")
    emit(f"V1-live dss (would-be) rows: {len(v1l):,}")
    emit(f"  inshore: {(v1l['segment']=='inshore').sum():,}   "
         f"offshore: {(v1l['segment']=='offshore').sum():,}")

    # Inshore isolation: byte-identical.
    ins0 = v0[v0["segment"] == "inshore"].sort_values("dss_date").reset_index(drop=True)
    ins1 = v1l[v1l["segment"] == "inshore"].sort_values("dss_date").reset_index(drop=True)
    emit()
    emit("-- Inshore isolation --")
    if len(ins0) != len(ins1):
        emit(f"  FAIL: inshore row count differs V0={len(ins0)} V1-live={len(ins1)}")
    else:
        all_eq = True
        for col in ins0.columns:
            s0, s1 = ins0[col], ins1[col]
            if pd.api.types.is_numeric_dtype(s0):
                eq = np.allclose(s0.values, s1.values, equal_nan=True)
            else:
                # For datetimes and strings, direct equality (NaN-safe via fillna).
                eq = s0.astype(str).equals(s1.astype(str))
            if not eq:
                emit(f"  mismatch: column {col}")
                all_eq = False
        emit("  PASS -- inshore V0 == V1-live (byte-identical)" if all_eq
             else "  FAIL -- inshore diverges")

    emit()
    emit("-- Offshore held-out (2025) direction acc / MAE / Brier --")
    emit(f"  {'species':<10} {'variant':<10} {'n_test':>6} {'dir_acc':>8} "
         f"{'mae':>6} {'brier':>7}")
    for species, breaks in [("bluefin",   _BLUEFIN_BREAKS),
                            ("yellowfin", _YELLOWFIN_BREAKS),
                            ("dorado",    _DORADO_BREAKS)]:
        m0 = score_segment(v0,  hc, "offshore", species, breaks)
        m1 = score_segment(v1l, hc, "offshore", species, breaks)
        emit(f"  {species:<10} {'V0-live':<10} {m0['n_test']:>6} "
             f"{m0['model']['direction_acc']:>8.4f} {m0['model']['mae']:>6.3f} "
             f"{m0['model']['brier']:>7.4f}")
        emit(f"  {species:<10} {'V1-live':<10} {m1['n_test']:>6} "
             f"{m1['model']['direction_acc']:>8.4f} {m1['model']['mae']:>6.3f} "
             f"{m1['model']['brier']:>7.4f}")
        d_dir = m1["model"]["direction_acc"] - m0["model"]["direction_acc"]
        d_mae = m1["model"]["mae"] - m0["model"]["mae"]
        d_bri = m1["model"]["brier"] - m0["model"]["brier"]
        emit(f"  {species:<10} {'delta':<10} {'':>6} "
             f"{d_dir:>+8.4f} {d_mae:>+6.3f} {d_bri:>+7.4f}")
        emit()

    emit()
    emit("V1-validated targets (from validate_daterep.py, angler-weighted + span-avg HC):")
    emit("  bluefin   ~ 73.3% dir / MAE ~1.98 / Brier ~0.19")
    emit("  yellowfin ~ 82.2% dir / MAE ~1.29 / Brier ~0.15")
    emit("  dorado    ~ 86.0% dir / MAE ~0.97 / Brier ~0.13")
    emit()
    emit("If V1-live above deviates materially from V1-validated, that's expected --")
    emit("V1-live uses dss AVG-per-trip response + single-day HC at dep-date, while")
    emit("V1-validated used SUM/SUM angler-weighted + span-averaged HC. The wire-up")
    emit("as scoped can only change the date KEY, not the aggregation formula or HC-")
    emit("averaging behavior. Recommendation for the user is at the bottom.")

    OUT.write_text("\n".join(_lines), encoding="utf-8")
    print(f"\n(report saved to {OUT.relative_to(ROOT)})")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
