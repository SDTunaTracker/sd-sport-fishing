# Forecast R&D — experiment log

Research only. Nothing here is wired into production. Data = read-only snapshot
`data/tracker_snapshot.db` copied from the main checkout on 2026-11-24 via the
SQLite backup API. Private env in `.venv/` (pandas, scikit-learn; LightGBM's DLL
would not load on this machine, so gradient boosting = sklearn HistGradientBoosting).

## Setup decisions (E0)

**Unit of prediction:** one trip = (boat, landing, departure date, trip length).
`trips.date` is the report/return date; departure = date − max(0, round(tl−1)),
matching `src/trip_conditions.py`.

**Hygiene:** 0.75 ≤ trip_length_days ≤ 3.5, not half-day, 5 ≤ anglers ≤ 120 →
42,840 of 50,577 trips. Evaluated rows also need a leak-free climatology and a
percentile reference (≥25 comparable prior-year trips): ~38.6k rows, ~32k in test years.

**Targets**
- `y` = trophy fish (BFT+YFT+YT+DOR) per angler per day; per-species versions too.
- `above` (the angler question, "will my trip be above normal?"): the trip's
  mid-rank percentile within the PRIOR-YEARS distribution of comparable trips
  (same landing × trip-length bucket × departure ±15 days; region-level fallback)
  is > 0.5. Base rate ≈ 41% in 2018–26 (not 50% because of ties at zero, and
  recent years running slightly below the 2015–2017 history).
- `clim0` = shrunk climatological mean (boat×tl → landing×tl, k=20), prior years only.

**Why not "above the mean":** tried first; only 30% of trips beat their
climatological mean (skewed distribution), so "always predict below" scores 70%
direction accuracy. Direction accuracy against a mean is therefore not a skill
measure. All direction numbers below are reported next to the majority-class rate,
and the primary probabilistic metrics are AUC and Brier skill score (BSS).

**Leakage rules (lead L days):** issue = departure − L. Allowed: catch reports
with report date ≤ issue−1; observed conditions ≤ issue−1 (persistence);
NOAA upwelling ≤ issue−31; deterministic trip facts (date, moon, boat, landing,
trip length). Not allowed: anglers count (not known 14 days out), observed weather
on the trip day (used only in the explicit "oracle" bound, prefix `orc_`).

**Folds:** walk-forward by year, test 2018…2026; train on trips reported ≥15 days
before Jan 1 of the test year. Retraining yearly is pessimistic vs. daily retraining.

## E1 — production model as a baseline (`baseline_existing.py`)
Hypothesis: `score_segment` (SST, wind, swell, moon, upwelling, monthly) ranks
trips by how they will do. Fed with as-of-issue conditions; calibrated per fold.
Generous to it: its monthly table and weights were fit on all history (in-sample).

| lead | AUC above-normal | BSS | Spearman(score, y) | MAE |
|---|---|---|---|---|
| 1 | 0.520 | 0.001 | 0.19 | 1.50 |
| 7 | 0.511 | −0.001 | 0.21 | 1.49 |
| 14 | 0.493 | −0.004 | 0.20 | 1.48 |

Adding climatology to it doesn't help (AUC 0.51). **Result: no skill on the
angler question.** Its raw correlation with fish counts is seasonality only (which
the climatology baseline already captures far better: MAE 1.33). Keep as the
baseline to beat; production claims of ~80% direction accuracy are likely
majority-class artefacts of a skewed "normal" (see setup).

## E2 — Round 1: baselines, gradient boosting, input-group ablations (`run_round1.py`)
Test 2018–2026, n = 31,935 trips. AUC/BSS are for P(above normal); base rate 41%,
majority-class accuracy 59%. MAE in trophy fish / angler / day (climatology MAE 1.34).

| lead | model | MAE | Spearman | AUC | BSS | dir acc (p>.5) |
|---|---|---|---|---|---|---|
| 1 | climatology (`clim0`) | 1.335 | 0.45 | — | — | 59% (majority) |
| 1 | boat's last trips (EWM-3) | 1.135 | 0.56 | — | — | — |
| 1 | fleet last 7 days | 1.132 | 0.53 | — | — | — |
| 1 | **ridge/logistic: clim + fleet 7/14d + boat EWM** | **1.097** | **0.59** | **0.697** | **0.109** | **65.3%** |
| 1 | boosting, all 87 features | 1.104 | 0.57 | 0.689 | 0.095 | 64.3% |
| 3 | ridge/logistic | 1.138 | 0.56 | 0.673 | 0.085 | 63.9% |
| 7 | ridge/logistic | 1.186 | 0.53 | 0.644 | 0.062 | 62.6% |
| 14 | ridge/logistic | 1.239 | 0.49 | 0.611 | 0.039 | 61.5% |

Ablations (boosting, AUC change when a group is removed; lead 1 / lead 7):
fleet momentum −0.022 / −0.006 · boat momentum −0.044 / −0.034 · SST 0.000 / +0.004 ·
wind −0.002 / 0.000 · swell −0.003 / +0.007 · pressure −0.002 / −0.001 ·
upwelling −0.001 / 0.000 · moon +0.003 / 0.000. Base-only (no momentum) AUC 0.56.
**Oracle** (observed trip-day wind/swell/pressure/SST added): AUC 0.687 vs 0.689 — no gain.

**Conclusions**
- Momentum is the signal; it decays with lead time (AUC 0.70 → 0.61 from 1 to 14 days).
- None of the condition inputs add skill once momentum is known — not even a perfect
  weather forecast. ⇒ Buying/archiving weather forecasts is not worth it (drop).
- Boosting < linear: too noisy/non-stationary for 87 features. Next: better-normalised
  momentum and heavier regularisation.
- Keep: clim + momentum. Drop (for now): wind, swell, pressure, moon, upwelling, point SST.

## E3 — Round 2: percentile momentum + new ocean data (`build_round2.py`, `run_round2.py`)
New inputs:
- **Percentile momentum**: recent trips scored as percentile-vs-their-own-normal
  (`pct`) rather than raw fish/angler/day, so trips of different types/seasons are
  comparable. Boat's own (last, EWM-3, EWM-8) and fleet means over 3/7/14/30 days at
  landing×trip-length, landing, region×segment, region.
- **MUR satellite SST** (NASA JPL MUR 0.01°, via NOAA CoastWatch ERDDAP, free;
  subsampled to 0.1°, 30.5–33.6N × 119.6–116.9W, 2014-01 → 2026-11-20): warm-water
  area within 150 km of Point Loma at 64/66/68/70/72 °F, distance to nearest such
  water, front strength (gradient mean/p90/cell count), SST at 8 named banks, 7/30-day
  changes. As of issue−2 days.
- **ENSO (ONI) and PDO** monthly (NOAA PSL), value 2 months before issue.

AUC for P(above normal), test 2018–26 (n≈31.9k):

| model | lead 1 | lead 3 | lead 7 | lead 14 |
|---|---|---|---|---|
| R0 linear, raw momentum | 0.679 | 0.655 | 0.630 | 0.601 |
| R1 linear, + percentile momentum | **0.730** | — | 0.658 | — |
| R2 boosting, pct momentum + species + activity | **0.731** | **0.703** | **0.660** | **0.606** |
| R3 linear + MUR | 0.702 | 0.676 | 0.636 | 0.593 |
| R3g boosting + MUR | 0.725 | — | 0.663 | — |
| R4 linear + ENSO/PDO | 0.711 | — | 0.612 | — |
| R5 linear + point SST/wind/swell/upwelling | 0.710 | — | 0.615 | — |
| R6 conditions only (no momentum), linear / boosting | 0.554 / 0.534 | 0.551 | 0.560 / 0.540 | 0.554 |
| R7 boosting, everything | 0.725 | 0.692 | 0.645 | 0.606 |

**Conclusions**
- Keep percentile momentum (+0.05 AUC at lead 1). It is the single best improvement so far.
- MUR spatial SST, ENSO/PDO and point conditions: **drop**. They hurt the linear model
  (it overfits regime-level signals that don't transfer across years) and are neutral
  for boosting. On their own (no momentum) conditions give AUC ≈ 0.55 — a weak signal that
  momentum already contains (the fleet's recent results *are* the ocean's report card).
- Species-level momentum and fleet-activity counts: no gain for the linear model.
- BloodyDecks paddies: **not testable** — `web/api/v1/paddies.json` is a single 14-day
  snapshot (Sep 2026, ~25 reports) and `data/paddies.db` doesn't exist in the main
  checkout. Needs months of accumulated history before it can be backtested.

## E4 — Round 3: ceiling, night-before lead, ensemble, calibration, species (`run_round3.py`)
- **Lead 0 added** ("night before": issued the morning of departure using every
  count reported through the previous evening). This is when most anglers check.
- **Ensemble** = mean of the regularised logistic/ridge model and the boosted model,
  on base + raw momentum + percentile momentum (no conditions).

| lead | AUC | BSS | acc (p>.5) vs majority 59% | MAE (clim 1.34) | Spearman |
|---|---|---|---|---|---|
| 0 | **0.764** | 0.203 | 70.0% | 1.061 | 0.64 |
| 1 | 0.738 | 0.163 | 68.0% | 1.116 | 0.60 |
| 3 | 0.710 | 0.127 | 65.8% | 1.163 | 0.56 |
| 7 | 0.669 | 0.084 | 63.2% | 1.217 | 0.52 |
| 14 | 0.618 | 0.036 | 59.9% | 1.272 | 0.47 |

Ensemble beats both members at every lead (keep).

**Predictability ceiling.** Score each trip by how the *other* boats of the same
landing × trip length returning the *same day* did (leave-one-out, i.e. perfect
hindsight knowledge of that day's bite): AUC **0.732** (n=19k); same region × segment:
**0.749** (n=30k). The lead-0 model (0.764) already matches it, because it also knows
boat quality. ⇒ Most of the remaining trip-to-trip variance is boat/captain/luck,
not "conditions", which is why ocean/weather inputs can't add much per trip.

**Practical lift (lead 0 / 1 / 7):** trips in the model's top 20% beat normal
73% / 69% / 59% of the time; bottom 20%: 11% / 13% / 19% (base 41%).

**Aggregated (day × landing × trip length, ≥2 boats):** AUC 0.785 / 0.750 / 0.666
(lead 0/1/7); day × region × segment: 0.805 / 0.764 / 0.659.

**Calibration:** good in the 0.3–0.9 range at lead 0–1 (e.g. "70–80%" → 76%/74% observed);
low end too high ("8%" → 3%); at lead 7 overconfident above 0.6 ("70–80%" → 68%).
Fix with isotonic recalibration (E5).

**By segment (lead 0 AUC):** by year 0.70 (2019) → 0.77–0.78 (2024–25); worse in the
peak tuna months Jun–Aug (0.74–0.76) than Oct–Apr (0.75–0.93, where "zero stays zero"
is easy); full-day 0.80 > overnight 0.75 > 1.5-day 0.71, 2-day 0.73, 2.5+ day 0.73;
OC/LA 0.87 vs San Diego 0.74.

**Species** (boosting + species momentum; rows where the species is normally caught
>15% of the time, rule set on pre-2018 data). AUC lead 0 / 1 / 7:
bluefin 0.75/0.72/0.66 · yellowfin 0.77/0.74/0.67 · yellowtail 0.74/0.71/0.59 ·
dorado 0.82/0.79/0.65.

## E5 — Round 4: boat skill, time-decayed fleet, bookings, recalibration (`run_round4.py`)
Test 2019–2026 (isotonic needs a prior out-of-fold year), n ≈ 28.9k.
New inputs: the boat's all-time expanding mean percentile, the same split by trip
length, and exponentially decayed fleet percentile (half-life 2/5/15 days) by
region × segment, landing × trip length and region × trip length.

| lead | ensemble (round 3 features) | + boat skill + decay | Δ |
|---|---|---|---|
| 0 | 0.7685 | **0.7732** | +0.005 |
| 1 | 0.7424 | **0.7473** | +0.005 |
| 3 | 0.7135 | **0.7164** | +0.003 |
| 7 | 0.6730 | **0.6815** | +0.009 |
| 14 | 0.6208 | **0.6341** | +0.013 |

- Keep boat skill + decay. Small but consistent at every lead.
- Anglers on board (stand-in for bookings) at lead 0: AUC 0.7749 (+0.002). Drop. Not worth a bookings feed.
- Isotonic recalibration: AUC −0.002 to −0.009, BSS lower. Drop. The raw ensemble is already well calibrated in the middle.
- Simple 3-input logistic (bp_ewm3, fp_lt7, fp_rs7): AUC 0.749 / 0.725 / 0.702 / 0.673 / 0.637.
  Gets about 90% of the lift and is easy to explain. It's a strong fallback.

## Open hypotheses / next round
- **Trip intent.** Knowing what a full-day trip targets (rockfish vs yellowtail) would
  sharpen both "normal" and the forecast. `scheduled_trips.target_species` exists but has
  only 452 recent rows. Start archiving it now.
- **Fleet position as momentum.** AIS: where the fleet fished yesterday and how far from
  port. Not in tracker.db. The positions dataset is elsewhere.
- **Paddy/kelp reports.** Need months of archived history before they can be tested.
- **Live shadow forward test** of the round-4 ensemble before any production decision.

## E6 — Handover pitfalls check (from "Tuna tracker audit" session)
Already handled: the target is recomputed from raw species counts ÷ (anglers × trip_length_days),
so the inconsistent stored `trophy_per_angler_per_day` is never used. anglers ≥ 5. "Normal" is
ranked against PRIOR years only, unlike check_forecast_accuracy, which leaks. Results are
broken out per trip-length class.
Newly added to `build_dataset.py`: drop `source='text_fallback'` rows, exact
boat/landing/date/length duplicates, and trips over 12 trophy fish per angler-day. 42,840 → 42,672 trips.
Rerun of round 4, AUC with vs without the new filters: lead 0 0.7733 (was 0.7732), lead 1 0.7469 (0.7473),
lead 3 0.7177 (0.7164), lead 7 0.6797 (0.6815), lead 14 0.6344 (0.6341). MAE about 0.02 lower everywhere.
**Conclusions unchanged.** Keep the filters (pre-filter results are in data/pre_hygiene/).
Not yet tested, from the handover: daily CUTI/BEUTI upwelling. Low priority, since NOAA upwelling,
wind and the ceiling result all say conditions add little per trip.
Queued: BloodyDecks `forum_signals` (bird pressure, bait quality, fleet location). Backtest once
a season of rows exists. About 25–35 reports a month gives low power, so the realistic test is
whether bird pressure or bait quality explains residuals of the momentum model.

### E6a — BloodyDecks forum_signals: join and timing contract (from the BD session, branch claude/bloodydecks-revive-7f7db7 @ 8ea51e9e+, not yet on main)
- Join: match_confidence ≥ 0.7 AND trip_match not null.
- Knowable-at = `fetched_at`, not published_at (for RSS rows, published_at is the thread's last activity).
  Rows from the 150-day backfill carry the backfill's fetch time, so exclude them from strict point-in-time tests.
  Separately labelled variant: available at trip_date + posting lag, with the lag measured from live rows.
- Semantics: NULL = not mentioned; bird_pressure 0 = "birds not a problem"; `unverified` lists claimed-but-unquoted fields, which stay NULL.
- Planned test: does bird_pressure or bait_quality explain the residuals of the round-4 ensemble
  (actual pct − predicted p), and does recent fleet bird pressure improve the next trips' forecasts? This is a hypothesis, not a finding.
- Live-row fetched_at is to the second, but ingest runs every 3 h (cron can slip about 1 h), so availability is late by up to about 4 h.
  That's negligible for day-level leads; I'll use fetched_at as is. The BD docs now label the signals as untested hypotheses.

## E7 — Live shadow test setup (`shadow.py`, `shadow/`)
The user approved a 4–6 week live shadow test of the round-4 ensemble (model `r4-ens-v1`).
It is never shown on the site or app.

**Protocol**
- `shadow.py issue` (daily): takes a fresh read-only SQLite backup of the live `tracker.db`, drops every
  trip REPORTED today or later (so the issue uses only counts through last night), retrains the
  ensemble on all history and forecasts **candidates**. Candidates are every boat that reported in the last 21 days,
  for each trip-length bucket it ran in the last 45 days, departing today + {0,1,3,7,14}.
  Appends rows to `shadow/forecasts.csv`, append-only and idempotent per (issue_date, lead, boat, landing, tlb),
  with `issued_at_utc`, the model version and a code hash.
- `shadow.py score`: matches logged forecasts to trips that actually ran (boat, landing, departure, trip-length
  bucket) and scores them in `shadow/REPORT.md`: AUC, Brier, BSS, accuracy, top/bottom-20% hit rates,
  MAE vs climatology and calibration. A live forecast counts only if logged no later than the trip's report date.
  Most candidates never sail. Only trips that ran are scored, which matches how the backtest was scored.
- Pipeline changes for this: `build_dataset.build(extra=candidates, cutoff=issue_date)`. Candidate rows
  have no outcome and are excluded from every history aggregate (climatology, percentile reference,
  fleet sums, boat recency). The date ranges now run to 2027-12-31.

**Leakage check (passed):** with an issue date of 2026-11-01 under the cutoff, every candidate that matched a real trip
had exactly the same model inputs as that trip in the full-history backtest dataset, at leads 0, 1, 7 and 14
(one bp_ewm8 difference below 1e-6, float noise). Coverage: every qualifying trip that departed on 2026-11-01 had a candidate.

**Caveat:** volume in Dec–Jan is low (about 5–25 qualifying trips a day) and off-season trips are easier to call
(zero-trophy days persist). A winter shadow run mainly proves the pipeline is honest. Summer skill
evidence comes from the replay below and from the backtest.

### E7a — Replay of the live code, peak season 2026 (`shadow.py replay 2026-07-01 2026-11-10 4`)
33 issue dates, each retrained under the cutoff (daily-style retraining, unlike the yearly backtest folds);
33,190 candidate forecasts, of which 4,848 matched trips that ran (`shadow/REPLAY_REPORT.md`).

| lead | n | beat normal | AUC replay (backtest) | BSS | top-20% hit | bottom-20% hit | MAE (clim) |
|---|---|---|---|---|---|---|---|
| 0 | 1009 | 55% | 0.766 (0.773) | 0.202 | 84% | 20% | 0.95 (1.14) |
| 1 | 977 | 55% | 0.745 (0.747) | 0.168 | 84% | 24% | 0.96 (1.10) |
| 3 | 980 | 52% | 0.720 (0.716) | 0.144 | 79% | 24% | 1.03 (1.14) |
| 7 | 944 | 53% | 0.687 (0.682) | 0.099 | 76% | 25% | 1.06 (1.15) |
| 14 | 938 | 55% | 0.666 (0.634) | 0.039 | 79% | 40% | 1.12 (1.22) |

- The production-style pipeline reproduces the backtest. **Keep.**
- **New finding, level bias in an anomalous year:** in summer 2026, 55% of trips beat normal against about 40% historically. Ranking held,
  but probabilities ran 5–7 points low at every level ("40–60%" happened 56% of the time, "60–80%" 75%).
  Next experiment (offline, not mid-shadow): a recency-weighted intercept or a season-to-date fleet-pct feature.

### E7b — Live shadow started 2026-11-25
- First issue at 07:46 local: 95 candidates × 5 leads = 475 forecasts in `shadow/forecasts.csv`.
  Scoring fixes followed (an empty-match timezone parse, and console encoding), so day-1 rows carry
  code_hash f15657ba6a. The issue logic is unchanged.
- Scheduled: Windows task "TunaTracker Forecast Shadow", daily 07:45 → `shadow/run_shadow.ps1` →
  `shadow.py issue` (logs the day's forecasts, then rescores everything in `shadow/REPORT.md`). Log: `shadow/run.log`.
  Remove with `schtasks /Delete /TN "TunaTracker Forecast Shadow" /F`.
- The model is frozen at r4-ens-v1 for the whole shadow window. Improvements are tested offline only.
- Review points: about 2 weeks in (pipeline health) and about 6 weeks in (decision). Expect a few hundred
  scored trips per lead by then, roughly ±0.04 AUC.

### E6b — forum_signals reached main (ad86f50f), in data/paddies.db
No rows yet. The table starts filling only after the user re-saves the ANTHROPIC_API_KEY repo secret. The first rows will be the 150-day
backfill (excluded from point-in-time tests); live rows follow at about 40 posts per 3-hour run. Earliest useful backtest:
after about one season of live rows, unless a backfill-labelled residual check is wanted sooner.

## E6c — Early forum_signals check (2026-11-25): blocked, no rows yet
- Asked to run the early "does it line up" check on the BloodyDecks backfill rows.
- Result: **no rows exist.** Latest `data/paddies.db` on origin/main (Paddies commit 2026-11-25 09:19 UTC,
  remote main = c45bbb23) has no `forum_signals` table; it's created on the first extractor run, which
  needs the ANTHROPIC_API_KEY repo secret. None of the local worktree copies have it either.
- Built `forum_check.py` so this is one command once rows land: pulls origin/main's paddies.db (read-only
  `git show`, writes data/ext/paddies_main.db), keeps match_confidence ≥ 0.7, joins on boat + departure (±1 day)
  to lead-1 OOF forecasts (oof_best_lead1.pkl), and reports:
  A) same-trip: Spearman of bird_pressure / bait_quality / water_temp vs residual (above − p_above), perm p, by-level table;
  B) forward: region-mean signal from posts published in [issue−7, issue−1] vs residual (published_at stand-in
     for knowable-at; exploratory only).
- Validated on a synthetic DB (400 real 2026 trips, planted bird effect + random bait): planted r = −0.53
  (p<0.001), random bait r = −0.04 (p=0.53), forward ≈ 0 as expected. Real run → data/forum_check.md says "no rows".
- Caveat for when it runs: OOF covers trips through the dataset build (~Nov 2026); trips after that need a rebuild.

## E6d — forum_signals first real run (2026-11-25, Paddies commit 3fb41689 17:15 UTC)
- The first extractor run after the key was re-saved processed 40 posts: 13 trip reports and 27 not reports, giving 13 forum_signals rows, 11 with conf ≥ 0.7.
- `forum_check.py` matched only **2** of those rows to forecast trips. The others are mostly long-range boats (Vagabond, Searcher, Excel, Islander, Shogun, Pursuit) on trips longer than 3.5 days. The forecast dataset filters those out (0.75 ≤ tl ≤ 3.5).
- bird_pressure was filled in once, on an unmatched row. bait_quality was filled in on 8 rows.
- Section B (bait, n = 23 trips, r = −0.30, p = 0.17) comes from a handful of posts. Treat it as noise.
- **No conclusion is possible at this size.** Re-run after the backfill fills in (~40 posts per 3-hour run).
- Structural risk: BD trip reports skew to long-range, which this forecast doesn't cover. The usable overlap could stay small even after the full backfill.

## E8 — Product reframe + round 5 (2026-11-25)
User goal: a Surfline-style outlook ("this weekend looks good, book a trip"). That means a fleet-level rating per
trip type × date for the next 1–14 days, plus a sea-conditions layer.

**E8a — How much day-to-day signal exists?** (San Diego, fleet mean pct per tlb × departure day, 2015–26)
- About 41–50% of the variance in daily fleet pct is between fortnights (slow).
- The estimated sampling noise from only ~2.4–4.2 trips/day is 62–81% of the variance.
- ⇒ Essentially no real within-fortnight day-to-day bite signal remains. The outlook can call the next 1–2 weeks
  "good" but cannot honestly say Saturday beats Sunday on the bite.
- Exception: day of week. Saturday departures beat normal 38.6% of the time vs 43–48% on other days (n = 8,002).
  The pct normal isn't weekday-aware, so add day-of-week features.

**E8b — Sea layer (sea_layer.py → data/sea_layer.md).** Free Open-Meteo Previous Runs (archived forecasts), 9-Mile Bank.
- Wind, daily max 04–16 local, 2022–26:
  - MAE 1.9 kn at lead 1 → 2.8 kn at lead 7.
  - Rough-day (≥20 kn) AUC 0.99 / 0.97 / 0.97 / 0.93 / 0.87 at leads 1 / 2 / 3 / 5 / 7.
- Fleet activity: with forecast ≥20 kn, SD boats run at roughly 10–65% of usual (small n); under 15 kn, about 104%.
- Wave height (marine API, ~1 yr archive): corr 0.98 / 0.96 / 0.88 / 0.91 / 0.84 at leads 1 / 2 / 3 / 5 / 7; MAE 0.05–0.16 m.
- ⇒ "Will it be rough / will my trip run" is very forecastable to 3–5 days. This is the dependable conditions half of
  the product. (Earlier finding stands: on trips that do run, weather doesn't predict catch beyond momentum.)

**E8c — Round 5 (run_round5.py), lead 1, 2019–26.**
- A0 yearly: AUC 0.7469, BSS 0.174; 2026 bias −0.076.
- A1 monthly retrain: AUC 0.7496, BSS 0.180; 2026 bias −0.060. Small but consistent gain; the live shadow already retrains daily.

## E8d — BD spot reports received as a hypothesis (2026-11-25; branch claude/bd-spots @ 824adf11, not merged)
- Research CSV via `python -m scraper.paddies.spots --research-csv <path> --db <paddies.db>`.
  Fields: report/trip date, fetched_at (knowable-at), species, quality (wide_open..none), water temp, place, precision_nm.
- Hypotheses to test once there are live rows (backfill rows are excluded from point-in-time tests):
  - H-S1: the share of wide_open/good reports in the last 3–7 days adds to fleet momentum for the
    *outlook*. This includes private-boat reports, which the landing counts never see.
  - H-S2: the distance from SD to the nearest recent good bite predicts which trip lengths will do well
    (a close bite favours full-day and overnight trips).
- No action yet: mostly September backfill, unmerged, and research only.

**E8e — Fleet outlook, lead 1 (run_outlook.py; 8,718 region × tlb × day cells, 2019–26, monthly retrain).**
- Correlation with the realized day rating: 0.570 vs persistence 0.538. The noise ceiling is 0.816.
- MAE 0.137 vs persistence 0.140 vs flat-0.5 0.181.
- Rating hit (4 classes) 45%.
- Trips beating normal by forecast rating: **great 78%** (376 days), **poor 18%** (2,502 days), all days 40%.
- Within-week ranking of days: Spearman −0.02. This confirms E8a: no day-level bite discrimination.

**E8f — Fleet outlook, all leads.** Correlation with the realized day rating (noise ceiling 0.816).

| model | L1 | L3 | L7 | L14 |
|---|---|---|---|---|
| Persistence (decayed fleet pct) | 0.538 | 0.487 | 0.411 | 0.315 |
| run_outlook (ridge + GB, ~40 feats) | 0.570 | 0.493 | 0.410 | 0.276 |
| outlook_v2 lean+lt, ridge α = 3000 | 0.570 | 0.512 | 0.434 | 0.324 |
| outlook_v2 lean, α = 3000 | — | — | — | 0.332 |

- Trips beating normal on days rated "great": 78–80% (L1), 79% (L3), 75–77% (L7). Days rated "poor": 17–20%. Base rate 40%.
- At L14 the shrunk forecast never reaches "great". Ratings should be shown as a calibrated chance, not fixed cutoffs.
- Takeaway: fleet outlook = persistence + strong mean reversion. The rich model overfits at long leads (L14 0.276 < persistence).
- E8g (outlook_v3.py): adding MUR SST features to the lean outlook *hurts* at L7 (0.438 → 0.432) and L14 (0.335 → 0.309).
  ENSO/PDO hurts further (L14 0.292). Ocean state still adds nothing on top of fleet momentum, even at fleet level and long leads.

**E8h — Date alignment (user reminder: counts are dated by RETURN day).** Checked against scheduled_trips times.
H&M times are UTC (+00:00); the other landings are naive local, and hours under 12 look like lost am/pm.
- Overnight: departs ~8 pm on day 0, fishes day 1, returns ~8 pm on day 1 → report = fishing day.
- 1.5-day: departs 5 pm, fishes day 1, returns ~6 am on day 2 → report = fishing day + 1.
- 2–3-day: report on the last fishing day or the morning after.
- `dep` in build_dataset (report − floor(tl − 0.5)) is therefore ≈ the FIRST FISHING DAY, not the literal departure.
  Bite and weather alignment are correct on that basis.
- Caveat found: "lead 0 / night-before" is a genuine pre-departure forecast only for full-day trips. Overnight and
  multi-day boats left the evening before `dep`, so their honest night-before is lead 1. This applies to the shadow
  REPORT and RESULTS lead-0 numbers for tl ≥ 1. A product must label by departure/booking date and forecast the fishing day(s).
- Data-quality note for the owner (not research code): scheduled_trips mixes UTC and naive local times; the
  naive ones appear to drop am/pm.

**E8i — Honest selection + uncertainty for the outlook (outlook_v4.py).** E8f chose α on the scored years, which is
optimistic. Now α is chosen on 2019–22 and the outlook is scored on held-out 2023–26. CI from a 14-day block bootstrap (1,000 resamples).

| lead | α | r model | r persist | gain [95% CI] | "poor" days beat normal | base |
|---|---|---|---|---|---|---|
| 1 | 1000 | 0.612 | 0.585 | +0.026 [+0.014, +0.038] | 14% | 37% |
| 3 | 3000 | 0.569 | 0.546 | +0.023 [+0.010, +0.036] | 15% | 37% |
| 7 | 3000 | 0.503 | 0.480 | +0.023 [+0.005, +0.041] | 15% | 37% |
| 14 | 10000 | 0.434 | 0.409 | +0.025 [−0.003, +0.055] | 16% | 37% |

- "great" days were rare in 2023–26: 66 at L1 (77% beat normal), 33 at L3 (70%), 10 at L7, 0 at L14.
- The gain over persistence is small but real at L1–7 and not significant at L14. Most of the outlook's value is
  persistence plus mean reversion, and it is best at flagging POOR stretches (14–16% vs a 37% base).

## E9 — Hypothesis queue from the data-sources research (2026-11-25; note: data-sources-forecast-hypotheses.md)
Priority, given that rounds 1–5 found ocean/weather add nothing over momentum for the BITE:
1. **H1 fleet AIS behaviour** (Marine Cadastre 2009–24): fleet centroid distance, convergence, drift vs run hours.
   Best prior: it observes where/how the fleet is fishing before counts post. Cost: very large downloads,
   so ask the user before pulling. Note it ends in 2024, so no live feed: it would need a live AIS source to ship.
2. **H6 cancellation / short-load target** (NWS Small Craft Advisory via the IEM archive). Partly done: E8b shows
   forecast wind ≥ 20 kn → boats run at 10–65% of usual. SCA text adds the official signal. Fits the product's sea layer.
3. **H3 booking velocity.** Started collecting history today: shadow/snap_schedule.py appends scheduled_trips daily
   (runs inside run_shadow.ps1, outside code_hash). Testable after ~1 season. Caveat: round 4 found realized anglers
   add only +0.002 AUC.
4. **H2 size grade / bait.** Waiting on forum_signals volume (E6d); overlap with ≤ 3.5-day trips is small.
5. **H4 CDFW block × month climatology.** Pending the owner's data request. Likely adds little over our own climatology.
6. **H5 HF-radar fronts.** Low prior; the dataset is unavailable.

## E10 — Round 5 per-trip results, lead 1 (run_round5.py, paired_test.py, online_recal.py)
2019–26 scores (2026 bias in brackets):

| variant | AUC | BSS | 2026 bias |
|---|---|---|---|
| A0 yearly (r4 protocol) | 0.7469 | 0.174 | −0.076 |
| A1 monthly retrain | 0.7496 | 0.180 | −0.060 |
| A2 monthly + recency hl 3 y | 0.7497 | 0.181 | −0.050 |
| A3 monthly + hl 1.5 y | 0.7486 | 0.180 | −0.040 |
| B1 + season-level fleet feats | 0.7480 | 0.178 | −0.056 |
| B2 + boat seasonality | 0.7484 | 0.178 | −0.062 |
| B3/B4 both (± hl3) | 0.748 | 0.178 | −0.05 |

Paired 14-day-block bootstrap:
- A1 vs A0: ΔAUC +0.0027 [+0.0004, +0.0052], ΔBrier −0.0014 [−0.0024, −0.0005] → **monthly retraining is real**.
  The live shadow already retrains daily, so it already has this.
- A2 vs A1: ΔAUC +0.0001 [−0.0015, +0.0016] → recency weighting is not significant.
- B1 vs A1: ΔAUC −0.0016 [−0.0038, +0.0003] → season features don't help; the fd_*/fp_* momentum already covers them.

**Online level correction** (leak-free): shift the logit by k × the mean residual of region trips reported in [issue−W, issue−1].
- Grid W ∈ {14, 30, 60}, k ∈ {2, 4}. Chosen on 2019–22 by Brier: W = 30, k = 2.
- **Held-out 2023–26: ΔAUC +0.0051 [+0.0016, +0.0084], ΔBrier −0.0024 [−0.0036, −0.0012].**
- In 2026 it halves the hot-year bias (−0.060 → −0.034).
- ⇒ First per-trip gain since round 4 that survives held-out selection. Candidate for an r5 model (NOT applied to
  the frozen shadow model; it could be added as a separate logged column without changing r4-ens-v1).

## E11 — H6 NWS marine advisories (sca_check.py → data/sca_check.md; IEM VTEC PZZ750 + PZZ775, 2016–26)
- Advisory (SC/GL/SI/SW/TR) issued by 20:00 the night before and in effect during fishing hours: 112 days (5%).
  - SD fleet activity was 0.58× usual (coastal zone only: 0.40×). Big-drop (<60% usual) rate 46% vs 6% on other days.
  - Big-drop AUC 0.62 alone (rare flag).
- 2022–26 overlap: wind forecast lead 1 AUC 0.722; + advisory 0.723 → **no added information beyond the wind forecast.**
- Bite on trips that ran: 40% beat normal under an advisory vs 41% → no bite effect (consistent with E8b).
- ⇒ Product: show advisories as an official, explainable "rough day" label in the sea layer. The wind forecast
  carries the predictive skill.
- Note for E10: the online level correction needs only past forecasts + outcomes, so it can be scored on the live
  shadow log retroactively once ~30 days of outcomes exist. The frozen model doesn't need to change.

## E12 — El Niño-stratified check (A1 monthly OOF, lead 1, 2019–26; ONI lagged 2 months, as in the features)

| phase | trips | months | beat normal | forecast | bias | AUC |
|---|---|---|---|---|---|---|
| La Niña (≤ −0.5) | 5,403 | 28 | 45% | 45% | −0.006 | 0.774 |
| neutral | 14,604 | 37 | 35% | 37% | +0.028 | 0.736 |
| weak/mod El Niño | 6,602 | 22 | 43% | 43% | +0.005 | 0.723 |
| strong El Niño (> 1.5) | 2,128 | 8 | 55% | 50% | −0.049 | 0.759 |

- Ranking skill holds in every phase.
- The strong-El-Niño under-forecast is 93% Sep–Nov 2026 trips, so it is confounded with the 2026 hot year
  (only one other episode since 2019, with 110 trips). Not separable.
- The E10 online level correction targets exactly this bias.
- ENSO is now stored in tracker.db (branch claude/data-sources-a3296d, src/enso.py). It is context only and not re-added as a feature (E3/E8g: no skill).

## E13 — H2b: landing_notes (branch claude/landing-notes, not on main; data/paddies.db)
- The landings' own trip reports, per boat × trip: species [{name, count, max_lb, min_lb}], bait_type, bait_on_board,
  tackle, region, trip_date, published_at, fetched_at (knowable-at). Values are quote-checked.
- Export: `python -m scraper.paddies.landing_reports --export-only --research-csv <path>`.
- Better than forum_signals for H2: it covers the same ≤3.5-day trips we forecast (forum posts skew to long range, E6d).
- Hypotheses:
  - H2b-1: the fleet's recent max/min size grade (e.g. YFT/BFT max_lb) predicts residuals. Big fish arriving ⇒ a bite
    shift that counts lag?
  - H2b-2: bait type changes (sardine ↔ anchovy) and "bait on board" issues lead pct changes.
- Plan: after merge plus the first CI run (~30 days back), join on boat + fishing day (report dates are return days,
  see E8h). Point-in-time by fetched_at; the 30-day back-fill gives only an explanatory look, and the strict test
  needs ~1 season of live rows.

## E14 — Round 6: weekday features (run_round6.py; fri/sat/sun/weekend added to F4, monthly folds)
- L1: AUC 0.7535 vs 0.7496 (A1). Paired ΔAUC +0.0039 [+0.0016, +0.0064], ΔBrier −0.0013 [−0.0020, −0.0006].
- L7: AUC 0.6931 vs 0.6893. ΔAUC +0.0038 [+0.0007, +0.0069], ΔBrier −0.0010 [−0.0017, −0.0003].
- Snooping check: the effect was found on all years, but it is already present in pre-test 2015–18 data.
  Saturday beat normal 38.5% vs 43–51% on other days; in 2019–26 the figures are 33.8% vs 40–46%. So it is not a test-period artefact.
- Interpretation: the pct normal ignores weekday; weekend boats (more casual anglers, more pressure) underperform.
- ⇒ Add fri/sat/sun to the r5 candidate. Expected combined L1 ≈ 0.757–0.758 (not yet run jointly with the online correction).
- E14b: full r5 candidate (C1 + online correction p_30_2.0), 2019–26 AUC 0.781 / 0.757 / 0.732 / 0.703 / 0.671 at L0 / 1 / 3 / 7 / 14.
  The online correction's held-out gains hold on top of the weekday features (L1 +0.0049 [+0.0016, +0.0080]). See RESULTS.md.

## E15 — r5 candidate joins the live shadow in parallel (2026-11-25)
- shadow_r5.py runs daily inside run_shadow.ps1 after the frozen r4. It writes shadow/forecasts_r5.csv and REPORT_r5.md,
  with model_version r5-cand-v1 and its own code_hash. It reuses r4's candidates and scoring, so the two are
  compared on identical trips.
- Live online correction: a model trained on reports < today−45 predicts trips reported in [today−30, today−1].
  The mean residual per region (n ≥ 20) is applied as a 2× logit shift. This mirrors backtest p_30_2.0.
- First issue (2026-11-25), 475 forecasts:
  - level_adj: San Diego +0.05…+0.11 logit (hot fleet); OC/LA −0.05…−0.17.
  - Correlation with r4's p_above is 0.98–0.99. Mean p_above is +2 to +5 points at most leads.
- Go/no-go: at the ~6-week review, compare r5 vs r4 on the same matched trips (paired).
