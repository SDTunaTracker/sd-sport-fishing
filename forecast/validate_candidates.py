"""Held-out validation of three candidate feature changes.

Candidates (from prior exploration):
  A1  YELLOWTAIL / inshore, add lagged sst_anomaly_d1 to the baseline score.
  A2  YELLOWTAIL / inshore, add lagged sst_gradient_d1 (species-tuned) instead.
  B   DORADO      / offshore, add INVERTED lagged sst_gradient_d1
      (dorado biology: low/uniform gradient = paddy fish territory).

Method (identical for each candidate):
  1. TIME split -- train <= 2024-12-31, test = 2025-01-01..2025-12-31.
  2. Response = species-per-angler on (date, segment) with hygiene:
        anglers >= 5, 0.75 <= trip_length_days <= 2.0, n_trips>=2 per day-segment.
  3. actual_rating = percentile rank of species_pa against the TRAIN
     distribution only, scaled 1..10 (mirrors forecast_accuracy_log semantics).
  4. baseline_score = current forecaster's species score for that day,
     replicated INLINE here so src/forecast.py is not touched. Uses the
     species SST breaks + shared non-SST factors (moon/wind/swell) identical
     to _sp() inside src/forecast.py::score_day.
  5. Fit a 1-feature residual regression on TRAIN:
        (actual_rating - baseline_score) = beta * feature
     (Ordinary least squares, no other features.)  This is the "isolated
     change" -- one feature, learned once, applied blindly to TEST.
  6. treatment_score = clip(baseline_score + beta * feature, 1, 10) on TEST.
  7. Metrics on TEST: direction_accuracy (>=5.5), MAE, Brier.
  8. Also compare to a naive per-month seasonal baseline computed on TRAIN.
  9. Isolation check: score all 4 species under baseline and treatment
     conditions, confirm species OTHER THAN the tested one are byte-identical.
 10. Verdict per candidate: ship / no-ship, with sample-size caveat.

Do NOT touch src/forecast.py, scrape/catch, or AIS code.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB   = ROOT / "tracker.db"
OUT  = ROOT / "forecast" / "validation_report.txt"

# ─── Baseline species-scoring helpers (inline copy of src/forecast.py) ────────
# NOTE: these are lifted verbatim from src/forecast.py so the baseline behaves
# identically to production. If forecast.py changes, this file goes stale --
# that is fine because this is a one-shot validation script, not shipped code.

_YELLOWTAIL_BREAKS = [
    (57, 1.0), (60, 4.5), (62, 7.5), (64, 9.5),
    (67, 9.0), (70, 7.0), (73, 5.0), (float("inf"), 3.0),
]
_DORADO_BREAKS = [
    (65, 1.0), (68, 2.5), (70, 5.0), (72, 7.0),
    (74, 8.5), (76, 9.5), (78, 8.5), (float("inf"), 5.5),
]
# Bluefin / yellowfin breaks are only needed for the isolation check.
# Values copied from src/analytics.py fallback defaults so the baseline scores
# for those species are computable and comparable.
_BLUEFIN_BREAKS = [
    (58, 1.0), (60, 3.0), (62, 5.5), (64, 8.0),
    (67, 9.5), (70, 8.5), (73, 6.0), (float("inf"), 4.0),
]
_YELLOWFIN_BREAKS = [
    (65, 1.0), (68, 3.5), (70, 6.0), (72, 8.5),
    (74, 9.5), (76, 9.0), (78, 7.5), (float("inf"), 5.0),
]

def score_from_breaks(sst_f, breaks):
    if sst_f is None or (isinstance(sst_f, float) and np.isnan(sst_f)):
        return 5.0
    for thresh, val in breaks:
        if sst_f < thresh:
            return val
    return breaks[-1][1]

def anomaly_boost(a):
    if a is None or (isinstance(a, float) and np.isnan(a)):
        return 0.0
    return max(-1.5, min(1.5, a * 0.5))

def moon_score(i):
    if i is None or (isinstance(i, float) and np.isnan(i)):
        return 5.0
    if i <= 5:  return 10.0
    if i <= 15: return 8.5
    if i <= 35: return 6.0
    if i <= 45: return 5.5
    if i <= 55: return 7.0
    if i <= 65: return 5.5
    if i <= 85: return 6.5
    if i <= 95: return 9.0
    return 9.5

def wind_score(kn):
    if kn is None or (isinstance(kn, float) and np.isnan(kn)):
        return 7.0
    if kn < 5:  return 10.0
    if kn < 10: return 8.0
    if kn < 15: return 6.0
    if kn < 20: return 4.0
    return 2.0

def swell_score(ft):
    if ft is None or (isinstance(ft, float) and np.isnan(ft)):
        return 8.0
    if ft < 2: return 10.0
    if ft < 4: return 8.0
    if ft < 6: return 5.0
    if ft < 8: return 3.0
    return 1.0

def species_baseline(sst_f, anomaly, moon, wind, swell_ft, breaks, sp_w=0.65):
    """Exact re-implementation of _sp() inside src/forecast.py::score_day."""
    base = score_from_breaks(sst_f, breaks)
    anom_mod = anomaly_boost(anomaly) * 0.4  # anomaly_weight defaults to 1.0
    base_adj = max(1.0, min(10.0, base + anom_mod))
    W_M, W_W, W_S = 0.10, 0.20, 0.10  # fallback non-SST weights from forecast.py
    W = W_M + W_W + W_S
    f_m = moon_score(moon)
    f_w = wind_score(wind)
    f_s = swell_score(swell_ft)
    non_sst_avg = (f_m * W_M + f_w * W_W + f_s * W_S) / W
    return float(max(1.0, min(10.0, base_adj * sp_w + non_sst_avg * (1 - sp_w))))


# ─── Metrics ──────────────────────────────────────────────────────────────────
def direction_accuracy(pred, actual, threshold=5.5):
    return float(((pred >= threshold) == (actual >= threshold)).mean())

def mae(pred, actual):
    return float((pred - actual).abs().mean())

def brier(pred, actual, threshold=5.5):
    """Brier for the direction call. Treat score as a naive probability
    (score/10 -> p in [0,1])."""
    p = (pred.clip(1, 10) - 1) / 9.0   # rescale so 1 -> 0, 10 -> 1
    y = (actual >= threshold).astype(float)
    return float(((p - y) ** 2).mean())


# ─── Reporting ────────────────────────────────────────────────────────────────
_lines: list[str] = []
def emit(s: str = "") -> None:
    _lines.append(s)
    print(s, flush=True)


# ─── Data loading ─────────────────────────────────────────────────────────────
def load_trips(con) -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT date, boat, landing, trip_length_days, anglers, "
        "       bluefin, yellowfin, yellowtail, dorado "
        "FROM trips",
        con,
    )
    emit(f"trips (raw):                              {len(df):>7,}")
    df = df[df["anglers"].fillna(0) >= 5]
    df = df[df["trip_length_days"] >= 0.75]
    df = df[df["trip_length_days"] <= 2.0]
    df["segment"] = np.where(df["trip_length_days"] <= 1.0, "inshore", "offshore")
    emit(f"trips (after hygiene):                    {len(df):>7,}")
    return df


def load_env(con) -> pd.DataFrame:
    env = pd.read_sql("SELECT * FROM historical_conditions", con)
    env["date"] = pd.to_datetime(env["date"])
    env = env.sort_values("date").reset_index(drop=True)

    numeric_cols = [
        "sst_offshore", "sst_nearshore", "sst_gradient", "sst_anomaly",
        "sst_warming_trend", "sst_7day_avg",
        "wind_speed", "wind_is_offshore", "wind_is_upwelling",
        "swell_height", "swell_period", "pressure_trend",
        "upwelling_index", "moon_illum",
    ]
    for c in numeric_cols:
        if c in env.columns:
            env[c] = pd.to_numeric(env[c], errors="coerce")

    # Convert swell metres -> feet for the score function (matches forecast.py's
    # normalise-on-fallback logic).
    if "swell_height" in env.columns:
        env["swell_height_ft"] = env["swell_height"] * 3.28084

    # Lag D-1 for the columns we need at forecast time.
    lag_cols = ["sst_offshore", "sst_nearshore", "sst_gradient", "sst_anomaly",
                "wind_speed", "swell_height_ft"]
    for c in lag_cols:
        env[f"{c}_d1"] = env[c].shift(1)

    env["date_str"] = env["date"].dt.strftime("%Y-%m-%d")
    return env


def build_response(trips: pd.DataFrame, species: str, segment: str,
                   min_trips: int = 2) -> pd.DataFrame:
    seg_trips = trips[trips["segment"] == segment]
    r = seg_trips.groupby("date").agg(
        n_trips=("boat", "count"),
        n_boats=("boat", "nunique"),
        total_anglers=("anglers", "sum"),
        species_total=(species, "sum"),
    ).reset_index()
    r["species_pa"] = r["species_total"] / r["total_anglers"]
    r = r[r["n_trips"] >= min_trips]
    return r


def actual_ratings_train_test(response: pd.DataFrame, train_mask: pd.Series
                              ) -> pd.Series:
    """Percentile rank each row's species_pa against the TRAIN distribution,
    scaled 1..10. Uses only training values as the reference distribution so
    test-set ranks are honest.

    Uses mid-rank on ties: percentile = (# strictly less + 0.5 * # equal) / N.
    Without mid-rank, zero-catch days get pushed to the TOP of the percentile
    scale in zero-inflated distributions (dorado), inverting the direction
    signal.
    """
    train_vals = np.asarray(response.loc[train_mask, "species_pa"].values,
                            dtype=float)
    train_sorted = np.sort(train_vals)
    N = len(train_sorted)
    if N == 0:
        return pd.Series(5.5, index=response.index)
    v = response["species_pa"].values.astype(float)
    less  = np.searchsorted(train_sorted, v, side="left")
    right = np.searchsorted(train_sorted, v, side="right")
    equal = right - less
    p = (less + 0.5 * equal) / N
    return pd.Series(np.clip(1.0 + p * 9.0, 1.0, 10.0), index=response.index)


def naive_seasonal(response: pd.DataFrame, actual: pd.Series,
                   train_mask: pd.Series) -> pd.Series:
    """Per-month mean rating from train, applied to every row (train+test)."""
    df = response.assign(actual=actual, month=pd.to_datetime(response["date"]).dt.month)
    monthly = df.loc[train_mask].groupby("month")["actual"].mean()
    return df["month"].map(monthly).fillna(actual.mean())


# ─── Validate one candidate ───────────────────────────────────────────────────
def validate(
    label: str,
    species: str,
    segment: str,
    sst_col: str,          # sst_offshore_d1 or sst_nearshore_d1
    breaks: list,
    feature_col: str,      # e.g. 'sst_anomaly_d1' or 'sst_gradient_d1'
    invert_feature: bool,  # for dorado, we test negative-sign gradient
    trips: pd.DataFrame,
    env: pd.DataFrame,
) -> dict:
    emit()
    emit("=" * 78)
    emit(f"CANDIDATE: {label}")
    emit(f"  species={species}  segment={segment}")
    emit(f"  baseline SST input: {sst_col}")
    emit(f"  candidate feature:  {feature_col}  invert={invert_feature}")
    emit("=" * 78)

    resp = build_response(trips, species, segment)
    resp = resp.merge(env[["date_str",
                           "sst_offshore_d1", "sst_nearshore_d1",
                           "sst_gradient_d1", "sst_anomaly_d1",
                           "wind_speed_d1", "swell_height_ft_d1",
                           "moon_illum"]],
                      left_on="date", right_on="date_str", how="left")
    n_before_env = len(resp)
    resp = resp.dropna(subset=[sst_col])
    emit(f"day-segment rows: {n_before_env:,}"
         f"   after env merge (drop rows missing {sst_col}): {len(resp):,}")

    # Time split
    dt = pd.to_datetime(resp["date"])
    train_mask = dt <= pd.Timestamp("2024-12-31")
    test_mask  = (dt >= pd.Timestamp("2025-01-01")) & (dt <= pd.Timestamp("2025-12-31"))
    emit(f"train rows (<=2024): {train_mask.sum():>5,}"
         f"   test rows (2025): {test_mask.sum():>5,}")

    if test_mask.sum() < 30:
        emit("  *** WARNING: TEST SET < 30  results are luck-of-the-split ***")

    # Compute baseline species score for every row.
    def _score_row(row):
        return species_baseline(
            sst_f     = row[sst_col],
            anomaly   = row["sst_anomaly_d1"],
            moon      = row["moon_illum"],
            wind      = row["wind_speed_d1"],
            swell_ft  = row["swell_height_ft_d1"],
            breaks    = breaks,
        )
    resp["baseline_score"] = resp.apply(_score_row, axis=1)

    # Actual rating (percentile rank against TRAIN distribution).
    resp["actual_rating"] = actual_ratings_train_test(resp, train_mask)

    # Fit residual OLS on TRAIN: (actual - baseline) = beta * feature
    tr = resp[train_mask].dropna(subset=[feature_col])
    if len(tr) < 30:
        emit(f"  *** TRAIN has < 30 rows with {feature_col}  cannot fit beta ***")
        return {}
    x = tr[feature_col].values.astype(float)
    if invert_feature:
        x = -x
    y = (tr["actual_rating"] - tr["baseline_score"]).values.astype(float)
    x_mean, y_mean = x.mean(), y.mean()
    beta = float(np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2))
    emit(f"fit on train: beta = {beta:+.4f}   (invert={invert_feature})")

    # Apply on TEST
    te = resp[test_mask].copy()
    tex = te[feature_col].values.astype(float)
    if invert_feature:
        tex = -tex
    te["treatment_score"] = (te["baseline_score"] + beta * tex).clip(1.0, 10.0)
    # Fill treatment_score with baseline where feature is NaN in test.
    fea_missing = te[feature_col].isna()
    te.loc[fea_missing, "treatment_score"] = te.loc[fea_missing, "baseline_score"]
    n_missing_feat = int(fea_missing.sum())
    if n_missing_feat:
        emit(f"  test rows with {feature_col} NaN (kept at baseline score): {n_missing_feat}")

    # Naive seasonal baseline
    resp["naive"] = naive_seasonal(resp, resp["actual_rating"], train_mask)
    te = te.merge(resp[["date", "naive"]], on="date", how="left")

    # Metrics on TEST
    def metrics(pred_col):
        pred = te[pred_col]
        actual = te["actual_rating"]
        return {
            "direction_acc": direction_accuracy(pred, actual),
            "mae":           mae(pred, actual),
            "brier":         brier(pred, actual),
        }

    m_base = metrics("baseline_score")
    m_treat = metrics("treatment_score")
    m_naive = metrics("naive")

    emit()
    emit(f"{'metric':<20} {'naive':>10} {'baseline':>10} {'treatment':>10} "
         f"{'delta_treat-base':>18}")
    for k in ("direction_acc", "mae", "brier"):
        d = m_treat[k] - m_base[k]
        emit(f"  {k:<18} {m_naive[k]:>10.4f} {m_base[k]:>10.4f} "
             f"{m_treat[k]:>10.4f} {d:>+18.4f}")

    # Verdict
    dir_delta = m_treat["direction_acc"] - m_base["direction_acc"]
    mae_delta = m_treat["mae"] - m_base["mae"]        # lower = better -> negative delta is good
    bri_delta = m_treat["brier"] - m_base["brier"]    # lower = better

    improved = (dir_delta > 0) and (mae_delta <= 0) and (bri_delta <= 0)
    marginal = (dir_delta >= 0) and (mae_delta <= 0.05) and (bri_delta <= 0.005)
    n_test = int(test_mask.sum())

    emit()
    emit("VERDICT:")
    if n_test < 30:
        emit(f"  NO-SHIP -- test slice too small (n={n_test}) to trust either way.")
    elif improved:
        emit(f"  SHIP CANDIDATE -- direction +{dir_delta*100:.1f}pp, "
             f"MAE {mae_delta:+.3f}, Brier {bri_delta:+.4f}  "
             f"on n={n_test} held-out 2025 rows.")
    elif marginal:
        emit(f"  MARGINAL -- direction {dir_delta*100:+.1f}pp, MAE {mae_delta:+.3f}, "
             f"Brier {bri_delta:+.4f}  on n={n_test}. Delta is within noise; "
             "not worth shipping.")
    else:
        emit(f"  NO-SHIP -- direction {dir_delta*100:+.1f}pp, MAE {mae_delta:+.3f}, "
             f"Brier {bri_delta:+.4f}  on n={n_test} rows. Change does not "
             "improve out-of-sample.")

    return {
        "label":            label,
        "beta":             beta,
        "n_train":          int(train_mask.sum()),
        "n_test":           n_test,
        "baseline":         m_base,
        "treatment":        m_treat,
        "naive":            m_naive,
        "improved":         improved,
        "delta_direction":  dir_delta,
        "delta_mae":        mae_delta,
        "delta_brier":      bri_delta,
    }


# ─── Isolation check: irrelevant species scores must not shift ────────────────
def isolation_check(env: pd.DataFrame) -> None:
    """Compute baseline (unchanged) scores for all 4 species on a synthetic
    set of conditions and confirm the tested candidates only affect the tested
    species' output. Since baseline is the same function for every species
    (species_baseline), only the SST break table differs between them --
    changing 'yellowtail input' or 'dorado gradient bonus' by construction
    cannot touch bluefin/yellowfin/other-yellowtail-segment outputs.

    We still print concrete numbers for a couple of sanity days to make the
    isolation explicit rather than implicit.
    """
    emit()
    emit("=" * 78)
    emit("ISOLATION CHECK: bluefin & yellowfin scores under baseline vs each")
    emit("candidate. Every candidate touches only one species path; other")
    emit("species must be byte-identical.")
    emit("=" * 78)

    # Pick two sample days that have complete env data.
    sample = env.dropna(subset=["sst_offshore_d1", "sst_nearshore_d1",
                                "sst_gradient_d1", "sst_anomaly_d1",
                                "moon_illum", "wind_speed_d1",
                                "swell_height_ft_d1"]).tail(2)
    if sample.empty:
        emit("  (no fully populated env rows to sanity-check)")
        return

    for _, row in sample.iterrows():
        bf = species_baseline(row["sst_offshore_d1"], row["sst_anomaly_d1"],
                              row["moon_illum"], row["wind_speed_d1"],
                              row["swell_height_ft_d1"], _BLUEFIN_BREAKS)
        yf = species_baseline(row["sst_offshore_d1"], row["sst_anomaly_d1"],
                              row["moon_illum"], row["wind_speed_d1"],
                              row["swell_height_ft_d1"], _YELLOWFIN_BREAKS)
        emit(f"  {row['date_str']}: bluefin={bf:.4f}  yellowfin={yf:.4f}")
    emit("  (These values are computed via species_baseline() using the")
    emit("   BLUEFIN and YELLOWFIN break tables. Neither A1/A2 (yellowtail")
    emit("   feature swap) nor B (dorado gradient) invokes these paths;")
    emit("   the two functions are structurally independent by species.)")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    emit("=" * 78)
    emit("HELD-OUT VALIDATION -- yellowtail anomaly + yellowtail gradient +")
    emit("dorado inverted gradient. Not a production integration; ship/no-ship")
    emit("advisory only. Time-split: train<=2024, test=2025.")
    emit("=" * 78)

    trips = load_trips(con)
    env   = load_env(con)

    # A1: yellowtail-inshore, sst_anomaly_d1
    r_a1 = validate(
        label="A1  yellowtail(inshore) + sst_anomaly_d1",
        species="yellowtail", segment="inshore",
        sst_col="sst_nearshore_d1", breaks=_YELLOWTAIL_BREAKS,
        feature_col="sst_anomaly_d1", invert_feature=False,
        trips=trips, env=env,
    )
    # A2: yellowtail-inshore, sst_gradient_d1 (species-tuned bonus)
    r_a2 = validate(
        label="A2  yellowtail(inshore) + sst_gradient_d1",
        species="yellowtail", segment="inshore",
        sst_col="sst_nearshore_d1", breaks=_YELLOWTAIL_BREAKS,
        feature_col="sst_gradient_d1", invert_feature=False,
        trips=trips, env=env,
    )
    # B: dorado-offshore, INVERTED gradient
    r_b = validate(
        label="B   dorado(offshore) + INVERTED sst_gradient_d1",
        species="dorado", segment="offshore",
        sst_col="sst_offshore_d1", breaks=_DORADO_BREAKS,
        feature_col="sst_gradient_d1", invert_feature=True,
        trips=trips, env=env,
    )

    isolation_check(env)

    emit()
    emit("=" * 78)
    emit("SUMMARY")
    emit("=" * 78)
    for r in (r_a1, r_a2, r_b):
        if not r:
            continue
        emit(f"  {r['label']}")
        emit(f"    beta={r['beta']:+.4f}   n_test={r['n_test']}   "
             f"dir_delta={r['delta_direction']*100:+.1f}pp   "
             f"mae_delta={r['delta_mae']:+.3f}   "
             f"brier_delta={r['delta_brier']:+.4f}")
    emit()
    emit("Next atomic task, if any candidate ships: single-file change to")
    emit("src/forecast.py species scoring path for that species only. Do NOT")
    emit("rewire the ensemble or touch other species until each new feature")
    emit("has its own independent held-out confirmation like this one.")

    OUT.write_text("\n".join(_lines), encoding="utf-8")
    print(f"\n(report saved to {OUT.relative_to(ROOT)})")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
