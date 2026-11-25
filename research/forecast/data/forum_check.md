# Forum signals vs forecast misses (EARLY, exploratory)

Source: `paddies_main.db`. Lead 1 out-of-fold forecasts (r4 best). Backfill rows: fetched_at is not a real knowable-at time, so this is a 'does it line up' look only, not a point-in-time test.

forum_signals rows (conf ≥ 0.7): 11; matched to a forecast trip: 2 (2 boats, 2026-11-08 … 2026-11-12). Field coverage among matched: bird_pressure 0%, bait_quality 50%, water_temp_f 0%

## A. Same trip: did the post's conditions line up with the model's miss?

| signal | n | Spearman vs residual | perm p | Spearman vs trip pct |
|---|---|---|---|---|
| bird_pressure | 0 | +nan | nan | +nan |
| bait_quality | 1 | +nan | nan | +nan |
| water_temp_f | 0 | +nan | nan | +nan |

## B. Forward: region-mean signal from posts published in the 7 days before issue

| signal | n trips | Spearman vs residual | perm p |
|---|---|---|---|
| bird_pressure | 0 | +nan | nan |
| bait_quality | 23 | -0.298 | 0.170 |

Reading this: a residual is (beat normal ? 1 : 0) − model probability. A negative Spearman for bird_pressure means bad-bird trips did worse than the model expected. With a few hundred matched trips, |r| < ~0.1 is indistinguishable from nothing; trip reports are also self-selected (people post more about great or awful days).