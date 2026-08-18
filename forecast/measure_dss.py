"""Measure offshore 2025 held-out numbers from daily_segment_stats.

Reads dss offshore rows, joins conditions (via HC single-day OR from dss span
columns per --span flag), computes species baseline scores, and reports
direction accuracy / MAE / Brier per species on the 2025 held-out slice.

Used as the checkpoint after each step of the wire-up.
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

from validate_candidates import (
    species_baseline,
    _BLUEFIN_BREAKS, _YELLOWFIN_BREAKS, _DORADO_BREAKS,
    direction_accuracy, mae, brier,
    actual_ratings_train_test,
)

DB = ROOT / "tracker.db"


def measure(label: str, use_span_cols: bool = False) -> None:
    """Reads dss offshore + conditions and prints held-out metrics per species.

    If use_span_cols=True, reads sst_offshore_span etc. from dss (Step 3).
    Otherwise LEFT JOINs historical_conditions on hc.date=dss.date (Steps 1-2).
    """
    con = sqlite3.connect(DB)

    if use_span_cols:
        # Read from dss span columns.
        q = """
            SELECT date AS dss_date, segment,
                   bluefin_tpa, yellowfin_tpa, dorado_tpa,
                   sst_offshore_span    AS sst_offshore,
                   sst_anomaly_span     AS sst_anomaly,
                   wind_speed_span      AS wind_speed,
                   swell_height_span    AS swell_height,
                   moon_illum_span      AS moon_illum
            FROM daily_segment_stats
            WHERE segment='offshore'
        """
    else:
        # Join HC on dss.date (single day at whatever key dss uses).
        q = """
            SELECT dss.date AS dss_date, dss.segment,
                   dss.bluefin_tpa, dss.yellowfin_tpa, dss.dorado_tpa,
                   hc.sst_offshore, hc.sst_anomaly, hc.wind_speed,
                   hc.swell_height, hc.moon_illum
            FROM daily_segment_stats dss
            LEFT JOIN historical_conditions hc ON hc.date = dss.date
            WHERE dss.segment='offshore'
        """

    df = pd.read_sql(q, con)
    con.close()

    numeric = ["bluefin_tpa","yellowfin_tpa","dorado_tpa",
               "sst_offshore","sst_anomaly","wind_speed",
               "swell_height","moon_illum"]
    for c in numeric:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["swell_height_ft"] = df["swell_height"] * 3.28084
    df["dss_date"] = pd.to_datetime(df["dss_date"])
    df = df.dropna(subset=["sst_offshore"]).reset_index(drop=True)

    is_train = (df["dss_date"] <= pd.Timestamp("2024-12-31")).reset_index(drop=True)
    is_test  = ((df["dss_date"] >= pd.Timestamp("2025-01-01"))
                & (df["dss_date"] <= pd.Timestamp("2025-12-31"))).reset_index(drop=True)

    print(f"\n=== {label} ===")
    print(f"  offshore rows: {len(df):,}   train (<=2024): {int(is_train.sum()):,}"
          f"   test (2025): {int(is_test.sum()):,}")
    print(f"  cond source: {'dss.*_span' if use_span_cols else 'historical_conditions on dss.date'}")

    for species, breaks, col in [
        ("bluefin",   _BLUEFIN_BREAKS,   "bluefin_tpa"),
        ("yellowfin", _YELLOWFIN_BREAKS, "yellowfin_tpa"),
        ("dorado",    _DORADO_BREAKS,    "dorado_tpa"),
    ]:
        # Baseline species score.
        scores = df.apply(lambda r: species_baseline(
            sst_f     = r["sst_offshore"],
            anomaly   = r["sst_anomaly"],
            moon      = r["moon_illum"],
            wind      = r["wind_speed"],
            swell_ft  = r["swell_height_ft"],
            breaks    = breaks,
        ), axis=1)
        # Actual = percentile rank of dss species tpa vs TRAIN dist.
        resp = pd.DataFrame({"species_pa": df[col].fillna(0.0).values})
        actual = actual_ratings_train_test(resp, is_train)
        actual.index = df.index

        pred_te = scores[is_test]
        actual_te = actual[is_test]
        if len(pred_te) == 0:
            print(f"  {species:<10}  no test rows"); continue
        d = direction_accuracy(pred_te, actual_te)
        m = mae(pred_te, actual_te)
        b = brier(pred_te, actual_te)
        print(f"  {species:<10}  n_test={len(pred_te):,}  dir_acc={d:.4f}  MAE={m:.3f}  Brier={b:.4f}")


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "current"
    use_span = "--span" in sys.argv
    measure(label, use_span_cols=use_span)
