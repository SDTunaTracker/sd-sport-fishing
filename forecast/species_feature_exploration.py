"""Per-species feature exploration for bluefin, yellowfin, dorado, yellowtail.

Hypothesis-generation only. Ranks candidate features by lagged-Spearman
correlation with each species' per-angler catch. No accuracy claims -- validated
lift requires a separate held-out confirmation test, one feature at a time.

Design choices (per task spec):
  * Response  = species-per-angler per (date, segment), matching forecast_scores.
  * Features  = lagged-only (D-1 or earlier), so every candidate is knowable at
    forecast time. Same-day catch-derived anything is leakage and excluded.
  * AIS       = fleet_median_max_dist_prior_day included ONLY for bluefin
    (confirmed signal in earlier exploration) and dorado (untested case).
    Excluded for yellowfin/yellowtail per prior finding of ~0 correlation.
  * Hygiene   = half-days out, <5 anglers out, trip_length_days > 2 out
    (multi-day trip attribution is fuzzy).
  * Segment   = each species reports on its PRIMARY biological segment
    (bluefin/yellowfin/dorado = offshore; yellowtail reported for BOTH).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB   = ROOT / "tracker.db"
OUT  = ROOT / "forecast" / "species_exploration_report.txt"

PORT_LAT, PORT_LON = 32.71, -117.22
LAG_ENV = [
    "sst_offshore", "sst_nearshore", "sst_gradient", "sst_anomaly",
    "sst_warming_trend", "sst_7day_avg",
    "wind_speed", "wind_is_offshore", "wind_is_upwelling",
    "swell_height", "swell_period", "pressure_trend",
    "upwelling_index",
]

_lines: list[str] = []
def emit(s: str = "") -> None:
    _lines.append(s)
    print(s)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1 = np.radians(lat1), np.radians(lon1)
    lat2, lon2 = np.radians(lat2), np.radians(lon2)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


# ─── Load raw data ────────────────────────────────────────────────────────────
def load_trips(con):
    df = pd.read_sql(
        "SELECT date, boat, landing, trip_length_days, anglers, "
        "       bluefin, yellowfin, yellowtail, dorado "
        "FROM trips",
        con,
    )
    emit(f"trips (raw):                              {len(df):>7,}")
    df = df[df.get("anglers", 0).fillna(0) >= 5]
    emit(f"  after anglers>=5:                       {len(df):>7,}")
    # half-day filter: use trip_length_days<0.75 as fallback since is_half_day
    # exists but was hand-flagged  the length threshold is more consistent.
    df = df[df["trip_length_days"] >= 0.75]
    emit(f"  after trip_length_days>=0.75 (no half): {len(df):>7,}")
    prev = len(df)
    df = df[df["trip_length_days"] <= 2.0]
    emit(f"  after trip_length_days<=2 (drop 3+day): {len(df):>7,}  "
         f"(removed {prev - len(df):,} multi-day rows)")
    df["segment"] = np.where(df["trip_length_days"] <= 1.0, "inshore", "offshore")
    return df


def build_response(trips: pd.DataFrame, species: str, min_trips: int = 2) -> pd.DataFrame:
    """Aggregate per (date, segment). species_pa = sum(species) / sum(anglers)."""
    grp = trips.groupby(["date", "segment"])
    r = grp.agg(
        n_trips=("boat", "count"),
        n_boats=("boat", "nunique"),
        total_anglers=("anglers", "sum"),
        species_total=(species, "sum"),
    ).reset_index()
    r["species_pa"] = r["species_total"] / r["total_anglers"]
    r = r[r["n_trips"] >= min_trips]
    return r


# ─── Env features (lagged) ────────────────────────────────────────────────────
def build_env_features(con):
    env = pd.read_sql("SELECT * FROM historical_conditions", con)
    env["date"] = pd.to_datetime(env["date"])
    env = env.sort_values("date").reset_index(drop=True)

    # historical_conditions ships numeric columns as TEXT/None in the source
    # DB rows -- force numeric so shift+arithmetic and Spearman work cleanly.
    numeric_cols = LAG_ENV + ["moon_illum"]
    for col in numeric_cols:
        if col in env.columns:
            env[col] = pd.to_numeric(env[col], errors="coerce")

    feats = env[["date"]].copy()

    for col in LAG_ENV:
        if col not in env.columns:
            continue
        feats[f"{col}_d1"] = env[col].shift(1)

    # moon illum is astronomical  known ahead, use same-day
    if "moon_illum" in env.columns:
        feats["moon_illum"] = env["moon_illum"]

    # Derived multi-day features (still lagged)
    if "sst_offshore" in env.columns:
        feats["sst_change_d1_d7"] = env["sst_offshore"].shift(1) - env["sst_offshore"].shift(7)
    if "wind_is_offshore" in env.columns:
        feats["wind_off_streak_d1_d3"] = (
            env["wind_is_offshore"].shift(1).fillna(0)
            + env["wind_is_offshore"].shift(2).fillna(0)
            + env["wind_is_offshore"].shift(3).fillna(0)
        )
    if "pressure_trend" in env.columns:
        feats["pressure_falling_streak_d1_d3"] = (
            (env["pressure_trend"].shift(1) < -0.5).fillna(False).astype(int)
            + (env["pressure_trend"].shift(2) < -0.5).fillna(False).astype(int)
            + (env["pressure_trend"].shift(3) < -0.5).fillna(False).astype(int)
        )
    if "sst_gradient" in env.columns:
        feats["sst_gradient_max_d1_d3"] = pd.concat([
            env["sst_gradient"].shift(1),
            env["sst_gradient"].shift(2),
            env["sst_gradient"].shift(3),
        ], axis=1).max(axis=1)

    feats["date"] = feats["date"].dt.strftime("%Y-%m-%d")
    return feats


# ─── AIS feature (bluefin + dorado only) ──────────────────────────────────────
def build_ais_feature(con):
    """fleet_median_max_dist_prior_day  median across tracked boats of
    per-boat max distance-from-port on date-1."""
    # Marine Cadastre only for the historical exploration -- the ~7 aisstream
    # rows from today use Go-format timestamps and aren't in the training window
    # anyway (catch data ends 2026-06-21, before live ingest began).
    pos = pd.read_sql(
        "SELECT mmsi, timestamp, lat, lon, sog FROM positions "
        "WHERE source = 'marine_cadastre'",
        con,
    )
    emit(f"positions rows (marine_cadastre): {len(pos):,}")
    pos["ts"] = pd.to_datetime(pos["timestamp"], format="ISO8601", utc=True)
    pos["pac_date"] = pos["ts"].dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d")
    pos["dist_km"] = haversine_km(PORT_LAT, PORT_LON, pos["lat"].values, pos["lon"].values)

    # Filter to positions where boat clearly went out (proxy for a fishing day)
    boat_day = pos.groupby(["mmsi", "pac_date"]).agg(
        max_dist=("dist_km", "max"),
        max_sog=("sog", "max"),
    ).reset_index()
    boat_day = boat_day[boat_day["max_sog"].fillna(0) >= 5.0]  # actually moved
    emit(f"boat-days with max_sog>=5 (real fishing days): {len(boat_day):,}")

    fleet = boat_day.groupby("pac_date")["max_dist"].median().reset_index(
        name="fleet_median_max_dist_km"
    )
    # Lag by 1 day
    fleet["ref_date"] = (pd.to_datetime(fleet["pac_date"]) + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    return fleet[["ref_date", "fleet_median_max_dist_km"]].rename(
        columns={"ref_date": "date", "fleet_median_max_dist_km": "fleet_median_max_dist_d1"}
    )


# ─── Correlation + ranked table + top-decile comparison ───────────────────────
def rank_features(df: pd.DataFrame, feat_cols: list[str], target: str = "species_pa") -> pd.DataFrame:
    """Spearman rank correlation of each feature vs. target, dropped NaN pairwise."""
    rows = []
    for f in feat_cols:
        if f not in df.columns:
            continue
        sub = df[[f, target]].dropna()
        n = len(sub)
        if n < 30:
            rows.append({"feature": f, "spearman": np.nan, "n": n})
            continue
        c = sub.corr(method="spearman").iloc[0, 1]
        rows.append({"feature": f, "spearman": c, "n": n})
    out = pd.DataFrame(rows)
    out["abs_r"] = out["spearman"].abs()
    return out.sort_values("abs_r", ascending=False, na_position="last").reset_index(drop=True)


def top_decile_vs_zero(df: pd.DataFrame, target: str, feats: list[str]) -> pd.DataFrame:
    """Compare mean feature values on top-decile-catch days vs zero-catch days."""
    if df[target].sum() == 0:
        return pd.DataFrame()
    q90 = df[target].quantile(0.90)
    top = df[df[target] >= q90]
    zero = df[df[target] == 0]
    if len(top) < 5 or len(zero) < 5:
        return pd.DataFrame()
    rows = []
    for f in feats:
        if f not in df.columns:
            continue
        t_mean = top[f].mean()
        z_mean = zero[f].mean()
        # Simple ratio guard against div-by-zero
        ratio = t_mean / z_mean if z_mean and not np.isclose(z_mean, 0) else np.nan
        rows.append({
            "feature": f,
            f"top_mean(n={len(top)})":  round(float(t_mean), 3) if not np.isnan(t_mean) else np.nan,
            f"zero_mean(n={len(zero)})": round(float(z_mean), 3) if not np.isnan(z_mean) else np.nan,
            "ratio":  round(float(ratio), 2) if ratio is not None and not (isinstance(ratio, float) and np.isnan(ratio)) else np.nan,
        })
    return pd.DataFrame(rows)


# ─── Per-species report block ─────────────────────────────────────────────────
def explore_species(sp: str, seg: str, trips: pd.DataFrame,
                    features: pd.DataFrame, ais: pd.DataFrame,
                    include_ais: bool) -> None:
    emit()
    emit("=" * 78)
    emit(f"SPECIES: {sp.upper()}   segment={seg}   include_ais={include_ais}")
    emit("=" * 78)

    # Seasonality + coverage
    with_species = trips[trips[sp] > 0]
    emit(f"trips with {sp} > 0 (all segments): {len(with_species):>6,}")
    if with_species.empty:
        emit(f"  NO catches of {sp} in filtered trip data  skipping")
        return
    emit(f"  date range: {with_species['date'].min()} .. {with_species['date'].max()}")
    per_month = with_species.assign(m=pd.to_datetime(with_species["date"]).dt.month) \
                            .groupby("m").size()
    emit(f"  by month (all years combined):")
    for m, n in per_month.items():
        emit(f"    {int(m):>2}: {n:>5,} trips")

    # Response
    resp = build_response(trips, sp)
    resp_seg = resp[resp["segment"] == seg]
    emit(f"day-segment rows (segment={seg}, n_trips>=2): {len(resp_seg):,}")
    if len(resp_seg) < 100:
        emit(f"  *** SMALL SAMPLE  interpret with caution ***")

    # Merge with features
    df = resp_seg.merge(features, on="date", how="left")
    if include_ais:
        df = df.merge(ais, on="date", how="left")
    df = df.dropna(subset=["sst_offshore_d1"])
    emit(f"after env-merge (require sst_offshore_d1 present): {len(df):,}")

    feat_cols = [c for c in df.columns if c.endswith("_d1")
                 or c in ("moon_illum", "sst_change_d1_d7",
                          "wind_off_streak_d1_d3",
                          "pressure_falling_streak_d1_d3",
                          "sst_gradient_max_d1_d3")]
    if include_ais and "fleet_median_max_dist_d1" in df.columns:
        pass  # already caught by _d1 filter
    else:
        # ensure AIS column not included when include_ais=False
        feat_cols = [c for c in feat_cols if c != "fleet_median_max_dist_d1"]

    # Filter dates to those where AIS coverage exists (bluefin/dorado runs)
    if include_ais:
        pre = len(df)
        df = df.dropna(subset=["fleet_median_max_dist_d1"])
        emit(f"after AIS-availability filter: {len(df):,} (removed {pre - len(df):,} pre-2020 dates)")

    if len(df) < 30:
        emit("  *** TOO FEW SAMPLES for reliable Spearman  skipping ranking ***")
        return

    # Spearman ranking
    ranked = rank_features(df, feat_cols)
    emit(f"\nRanked features by |Spearman(rho, {sp}_per_angler)|:")
    emit(f"  {'feature':<32} {'spearman':>10} {'n':>7}")
    for _, r in ranked.iterrows():
        rho = r["spearman"]
        rho_s = f"{rho:>10.3f}" if not (isinstance(rho, float) and np.isnan(rho)) else f"{'nan':>10}"
        emit(f"  {r['feature']:<32} {rho_s}  {int(r['n']):>7,}")

    # Top-3 features: top-decile vs zero
    top3 = [r["feature"] for _, r in ranked.head(3).iterrows()
            if not np.isnan(r["spearman"])]
    if top3:
        emit(f"\nTop-3 feature values: top-decile-{sp} days vs zero-{sp} days")
        cmp = top_decile_vs_zero(df, "species_pa", top3)
        if not cmp.empty:
            emit(cmp.to_string(index=False))
        else:
            emit("  (insufficient top-decile or zero-catch rows for comparison)")

    # Honest one-line read
    emit("\nREAD:")
    top_r = ranked.iloc[0]["spearman"] if not ranked.empty and not np.isnan(ranked.iloc[0]["spearman"]) else 0.0
    top_f = ranked.iloc[0]["feature"] if not ranked.empty else "none"
    n = len(df)
    if abs(top_r) < 0.10:
        emit(f"  Top feature {top_f} rho={top_r:.3f} on n={n:,}  no meaningful signal in this set")
    elif abs(top_r) < 0.20:
        emit(f"  Weak signal: {top_f} rho={top_r:.3f} on n={n:,}. Candidate for a"
             f" confirmation test but effect is modest.")
    elif abs(top_r) < 0.35:
        emit(f"  Moderate signal: {top_f} rho={top_r:.3f} on n={n:,}. Solid"
             f" candidate for a held-out confirmation test.")
    else:
        emit(f"  Strong signal: {top_f} rho={top_r:.3f} on n={n:,}. High-priority"
             f" candidate.")
    if include_ais:
        ais_row = ranked[ranked["feature"] == "fleet_median_max_dist_d1"]
        if not ais_row.empty:
            r = ais_row.iloc[0]["spearman"]
            emit(f"  AIS fleet_median_max_dist_d1 rho={r:.3f} on n={int(ais_row.iloc[0]['n']):,}")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    emit("=" * 78)
    emit("PER-SPECIES FEATURE EXPLORATION")
    emit("Hypothesis generation, not validated accuracy. Ranks candidates for")
    emit("a separate held-out confirmation test.")
    emit("=" * 78)

    emit("\n---- STEP 0: current forecaster + env inventory ----")
    emit(
        "forecast.py target:   average trophy_per_angler_per_day (TPA), scored 1-10 by\n"
        "                      percentile rank against all historical TPA.\n"
        "                      Also produces species-specific *scores* (bluefin/yellowfin/\n"
        "                      yellowtail/dorado) via SST-break tables; those are 1-10\n"
        "                      derivatives of SST, not modelled from species catch directly.\n"
        "forecast_scores key:  (date, segment)  segment = inshore if trip_length_days<=1 else offshore.\n"
        "Features already in:  SST (nearshore, 9-mile, 60-mile, cortez), sst_anomaly,\n"
        "                      sst_gradient, sst_warming_trend, wind (speed/dir + is_offshore/\n"
        "                      is_upwelling), swell height/period, pressure trend, moon illum,\n"
        "                      upwelling_index, historical monthly baseline TPA."
    )
    emit()
    emit("Env fields ACTUALLY populated (from tracker.db inventory):")
    emit("  SST + anomaly + gradient + warming_trend + 7day_avg    populated 92-100%")
    emit("  wind (speed, dir, is_offshore, is_upwelling)           populated 99-100%")
    emit("  swell (height, period)                                 populated 94-95%")
    emit("  pressure + pressure_trend                              populated 100%")
    emit("  moon_illum                                             populated 100%")
    emit("  upwelling_index                                        populated 96%")
    emit("  chlorophyll_nearshore/offshore                         populated 0%  MISSING")
    emit("  current_speed / current_is_favorable / eddy_detected   populated 30%  STALE (stops 2018)")
    emit("  bathymetry / structure distance                        NOT IN DB")
    emit("  SSH / sea-surface-height / mesoscale eddies (current)  NOT IN DB")
    emit("  tides                                                  NOT IN DB")

    emit()
    emit("---- STEP 1: per-species feature exploration ----")
    emit()

    trips = load_trips(con)
    features = build_env_features(con)
    ais = build_ais_feature(con)

    # bluefin -- offshore, include AIS
    explore_species("bluefin",   "offshore", trips, features, ais, include_ais=True)
    # yellowfin -- offshore, NO AIS (per earlier finding of ~0 correlation)
    explore_species("yellowfin", "offshore", trips, features, ais, include_ais=False)
    # dorado -- offshore, INCLUDE AIS (untested case per spec)
    explore_species("dorado",    "offshore", trips, features, ais, include_ais=True)
    # yellowtail -- report both segments since it's caught in both
    explore_species("yellowtail","offshore", trips, features, ais, include_ais=False)
    explore_species("yellowtail","inshore",  trips, features, ais, include_ais=False)

    emit()
    emit("=" * 78)
    emit("EXPLORATION COMPLETE  next step is a separate held-out validation:")
    emit("  1. Pick the top 1-2 candidate features per species from the 'READ' lines.")
    emit("  2. Hold out a time-forward slice (e.g. 2025 for train up to 2024).")
    emit("  3. Add the candidate to the appropriate model in src/forecast.py, one at a")
    emit("     time, and measure change in direction accuracy + MAE on the held-out slice")
    emit("     via forecast_accuracy_log semantics.")
    emit("  4. Only ship a feature that materially improves out-of-sample accuracy.")
    emit("=" * 78)

    OUT.write_text("\n".join(_lines), encoding="utf-8")
    print(f"\n(report saved to {OUT.relative_to(ROOT)})")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
