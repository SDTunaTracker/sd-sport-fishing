# Replay (past issue dates, cutoff-simulated)

Generated 2026-11-25T07:45. Forecasts logged: 33,190; matched to a reported trip: 4,848.

| lead | n trips | beat normal | AUC (backtest) | Brier | BSS vs base | acc p>.5 | top-20% hit | bottom-20% hit | MAE fish/angler/day (clim) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 1009 | 55% | 0.766 (0.773) | 0.198 | 0.202 | 68% | 84% | 20% | 0.95 (1.14) |
| 1 | 977 | 55% | 0.745 (0.747) | 0.206 | 0.168 | 67% | 84% | 24% | 0.96 (1.10) |
| 3 | 980 | 52% | 0.720 (0.716) | 0.214 | 0.144 | 66% | 79% | 24% | 1.03 (1.14) |
| 7 | 944 | 53% | 0.687 (0.682) | 0.224 | 0.099 | 62% | 76% | 25% | 1.06 (1.15) |
| 14 | 938 | 55% | 0.666 (0.634) | 0.238 | 0.039 | 60% | 79% | 40% | 1.12 (1.22) |

Calibration (all leads):

| forecast | n | said | happened |
|---|---|---|---|
| (0.0, 0.2] | 376.0 | 14% | 18% |
| (0.2, 0.4] | 1320.0 | 31% | 38% |
| (0.4, 0.6] | 1884.0 | 49% | 56% |
| (0.6, 0.8] | 931.0 | 69% | 75% |
| (0.8, 1.0] | 337.0 | 85% | 88% |

Note: the backtest AUCs in brackets are over 2019–26; a few weeks of shadow data has wide error bars (±0.03–0.05 AUC at n≈500).