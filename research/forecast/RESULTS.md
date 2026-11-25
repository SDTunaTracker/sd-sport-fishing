# Forecast R&D — results leaderboard

**Question answered:** *"Will my trip (this boat, landing, trip length, date) beat a
normal trip of its kind?"* Here "normal" means the median of comparable past trips:
same landing × trip length × ±15 days, prior years only. The model also gives an
expected trophy fish per angler per day.

**Honest test:** walk-forward by year. Each year from 2019 to 2026 is predicted by a
model trained only on earlier years, using only data that existed at the forecast's
issue time. n ≈ 28.9k trips, of which 40.1% beat normal (majority-class accuracy 59.9%).
AUC: 0.5 = coin flip, 1.0 = perfect. BSS = Brier skill score vs. always saying 40%.

## Leaderboard (2019–2026 test years)

| Model | Lead 0 (night before) | Lead 1 | Lead 3 | Lead 7 | Lead 14 |
|---|---|---|---|---|---|
| **Best: ensemble (logistic + boosting), climatology + percentile momentum + boat skill + decayed fleet** | **AUC 0.773** · BSS 0.215 · acc 71.0% | **0.747** · 0.175 · 68.9% | **0.716** · 0.135 · 66.5% | **0.682** · 0.096 · 64.2% | **0.634** · 0.050 · 61.5% |
| Simple 3-input logistic (boat's last ~3 trips, landing × trip-length fleet 7d, region fleet 7d) | 0.749 | 0.725 | 0.702 | 0.673 | 0.637 |
| Ensemble without boat skill / decay (round 3) | 0.769 | 0.742 | 0.714 | 0.673 | 0.621 |
| Raw-momentum linear (round 2 R0)† | — | 0.679 | 0.655 | 0.630 | 0.601 |
| Conditions only: SST, MUR fronts, wind, swell, upwelling, ENSO/PDO, no momentum† | — | 0.554 | 0.551 | 0.560 | 0.554 |
| **Current production model** (`src/forecast.py` score_segment, calibrated)† | — | **0.520** | 0.511 | 0.511 | 0.493 |
| Climatology (always the base rate) | 0.5 | 0.5 | 0.5 | 0.5 | 0.5 |

† test years 2018–2026 (one extra year); comparable within ±0.01.

**Fish per angler per day (lead 0 / 1 / 7 / 14):** MAE 1.01 / 1.07 / 1.17 / 1.22 against
1.30 for climatology (−22% / −18% / −10% / −6%). RMSE 1.50 / 1.56 / 1.65 / 1.70 against 1.77.
The production model's MAE is 1.50, which is worse than climatology.

**What the probabilities mean in practice (best model):**

| Lead | Top 10% of trips beat normal | Top 20% | Bottom 20% | Base rate |
|---|---|---|---|---|
| 0 | 80% | 74% | 9% | 40% |
| 1 | 75% | 70% | 11% | 40% |
| 3 | 70% | 65% | 14% | 40% |
| 7 | 64% | 60% | 17% | 40% |
| 14 | 55% | 54% | 23% | 40% |

**Calibration (lead 0):** when the model says 30–40% it happens 34% of the time, 50–60% → 56%,
70–80% → 77%, 80–90% → 84%. The low end is a bit high: "≤10%" happens about 2% of the time.
At lead 7, forecasts above 70% are overconfident: "70–80%" happens 69% of the time.

**By species (lead 0 / 1 / 7 AUC):** bluefin 0.75/0.72/0.66 · yellowfin 0.77/0.74/0.67 ·
yellowtail 0.74/0.71/0.59 · dorado 0.82/0.79/0.65.

**Where it's weaker:** peak tuna months Jun–Aug (lead-0 AUC 0.74–0.76), 1.5-day trips (0.71),
San Diego (0.74) vs OC/LA (0.87), and 2018–19 (0.70). Lead 14 is barely better than climatology.

## What predicts trip performance (and what doesn't)

1. **Recent catch momentum, measured against normal.** This is nearly all of the skill.
   It means how this boat's last few trips did against their own normal, and how the
   landing's and region's fleet did over the last 3–14 days. It decays with lead time.
2. **Boat skill.** Some boats beat normal consistently. Adding it gives +0.005 to +0.013 AUC.
3. **Seasonal climatology** of boat × trip length. It sets "normal" and the fish-count level.
4. **Ocean and weather add nothing measurable on top of momentum.** This held for point
   SST, satellite SST fronts and warm-water extent, wind, swell, pressure, NOAA upwelling,
   moon and ENSO/PDO. It held even with *perfect hindsight* weather on the trip day.
   Used alone they give AUC ≈ 0.55. The fleet's recent results already summarise
   what the ocean is doing.
5. **Ceiling.** Perfect knowledge of how the other boats did *that same day* scores only
   AUC 0.73–0.75. The best model is already at that level. The rest is boat, captain and
   luck, so no ocean or weather feed can push per-trip accuracy much higher.

## Verdict

- **Lead 0–3 days:** good enough to *consider* for production as a calibrated
  "chance your trip beats normal" next to a fish-per-angler estimate. It is far better
  than the current model, which has no skill. It is moderate, not high, predictability.
  Recommended path: a 4–6 week live shadow run that logs forecasts daily and compares
  them with returns before anything is shown to users.
- **Lead 7–14 days:** weak (AUC 0.68 / 0.63). Show climatology with wide uncertainty,
  not a confident forecast.
- **Not recommended:** buying weather or forecast archives, or currents data, for this purpose.

---

## Round 5 + product reframe (2026-11-25)

### Per-trip model: r4 → r5 candidate (monthly retrain + 30-day online level correction)
2019–26, departures scored walk-forward. Every gain was selected on 2019–22 or tested with a paired 14-day-block bootstrap.

| lead | r4 protocol AUC | r5 AUC | Brier r4 → r5 | 2026 bias r4 → r5 |
|---|---|---|---|---|
| 0 | 0.773 | **0.777** | 0.1877 → 0.1864 | −0.063 → −0.030 |
| 1 | 0.747 | **0.754** | 0.1968 → 0.1951 | −0.076 → −0.034 |
| 3 | 0.718 | **0.729** | 0.2052 → 0.2030 | −0.082 → −0.038 |
| 7 | 0.680 | **0.700** | 0.2146 → 0.2116 | −0.109 → −0.050 |
| 14 | 0.634 | **0.664** | 0.2244 → 0.2214 | −0.143 → −0.067 |

- Monthly retraining: significant at L3–14 (L14 ΔAUC +0.017 [+0.008, +0.026]). The live shadow retrains daily, so it already has this.
- Online level correction (held-out 2023–26): ΔAUC +0.003 / +0.005 / +0.007 / +0.012 / +0.026 at L0 / 1 / 3 / 7 / 14. All CIs exclude zero.
- Didn't help: season-level fleet features, boat seasonality, recency weighting (beyond monthly), MUR SST, ENSO.
- Lead 0 is a genuine pre-departure forecast only for full-day trips. Overnight and multi-day boats leave the evening
  before (counts are dated by return day), so lead 1 is their night-before.

### Fleet outlook (Surfline-style: region × trip type × fishing day)
Held-out 2023–26, shrinkage chosen on 2019–22:
- Correlation with the realized day rating: 0.61 / 0.57 / 0.50 / 0.43 at L1 / 3 / 7 / 14.
- That beats persistence by +0.023 to +0.026 at L1–7 (CI > 0). At L14 the gain is not significant.
- Strongest at flagging poor stretches: 14–16% of trips beat normal on days rated "poor", vs a 37% base.
- No real within-fortnight day-to-day bite signal exists (sampling noise from 2–4 trips/day dominates).
  The exception is Saturday, which beats normal less often (39% vs 43–48%).

### Sea-conditions layer (archived Open-Meteo forecasts, 9-Mile Bank)
- Wind ≥ 20 kn rough-day AUC: 0.99 / 0.97 / 0.97 / 0.93 / 0.87 at L1 / 2 / 3 / 5 / 7.
- Wave-height correlation: 0.98 → 0.84 over the same leads.
- Forecast ≥ 20 kn → SD boats run at about 10–65% of usual.
- An NWS advisory the night before → activity 0.58× usual. It adds nothing beyond the wind forecast, but is a good official label.
- Weather doesn't change the bite on trips that run.

### Product verdict
- A Surfline-style tool is supportable as: a **sea-comfort / will-it-run rating per day to ~5 days** (strong), plus a
  **bite outlook for the next 1–2 weeks** (moderate, honest about uncertainty, best at "skip this stretch").
- Not supportable: day-by-day bite picks within a week.
- r5 is worth considering for production after its correction is verified on the live shadow log (~30 days of outcomes).

### r5 candidate, final (monthly retrain + weekday features + 30-day online correction), 2019–26 walk-forward

| lead | r4 protocol AUC | **r5 AUC** | Brier r4 → r5 | 2026 bias r4 → r5 |
|---|---|---|---|---|
| 0 | 0.773 | **0.781** | 0.1877 → 0.1850 | −0.063 → −0.031 |
| 1 | 0.747 | **0.757** | 0.1968 → 0.1939 | −0.076 → −0.034 |
| 3 | 0.718 | **0.732** | 0.2052 → 0.2022 | −0.082 → −0.038 |
| 7 | 0.680 | **0.703** | 0.2146 → 0.2107 | −0.109 → −0.051 |
| 14 | 0.634 | **0.671** | 0.2244 → 0.2200 | −0.143 → −0.066 |

Each component passed a paired block bootstrap or held-out selection (LOG E10, E14).
Remaining caveat: 2026 is still under-forecast by 3–7 points, so the hot year isn't fully captured.

## 7-day SD tuna outlook (2026-11-25, LOG E16–E19)
- **Target:** tuna (bluefin + yellowfin + bigeye + albacore) per angler per fishing day. A good trip is ≥ 1.
- **Accuracy, held out 2023–26:** the fleet forecast ranks days at r = 0.61 one day ahead and 0.50 seven days ahead.
  "Same as last 5 days" scores 0.60 and 0.49, and the seasonal normal scores 0.40. Chance-of-good-trip errors are
  11–21% lower than using the normal.
- **What drives it:** the recent fleet catch, season and trip type. Wind, swell, SST, pressure, moon, tides and fronts add
  nothing once the recent catch is known, and adding them makes the model slightly worse (E16, E18). Wind and seas
  forecasts are very accurate for spotting rough or cancelled days, so they are shown as a separate comfort layer.
- **Sample page:** https://claude.ai/artifact/PCFZ9pgdB2vFcRsL4uzvgF (private; research only).
- **Production verdict:** NOT yet. It is honest and modestly better than the naive baseline, but it needs a live shadow
  run on the outlook (not just the per-trip r4/r5) before anyone decides to ship it.
