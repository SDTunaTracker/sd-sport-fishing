# Sea-conditions layer (wind) — archived forecasts vs what happened

9-Mile Bank, daily max 10 m wind 04:00–16:00 local, 2022-01-01 … 2026-11-24.

| lead (days) | MAE kn | corr | rough day (≥20 kn) AUC | hit rate when forecast ≥20 | caught |
|---|---|---|---|---|---|
| 1 | 1.9 | 0.80 | 0.988 | 63% (n=46) | 83% of 35 |
| 2 | 1.9 | 0.78 | 0.969 | 76% (n=33) | 71% of 35 |
| 3 | 2.1 | 0.73 | 0.965 | 71% (n=28) | 57% of 35 |
| 5 | 2.5 | 0.61 | 0.932 | 56% (n=27) | 44% of 34 |
| 7 | 2.8 | 0.46 | 0.867 | 33% (n=46) | 44% of 34 |

Fleet activity (San Diego trips that ran ÷ usual for that weekday/season) by FORECAST wind:

| lead | <15 kn | 15–20 | 20–25 | ≥25 | 'big drop' (<60% usual) AUC |
|---|---|---|---|---|---|
| actual | 1.03 | 0.84 | 0.21 | 0.33 | 0.697 |
| 1 | 1.05 | 0.84 | 0.64 | 0.09 | 0.722 |
| 2 | 1.04 | 0.76 | 0.21 | 0.38 | 0.710 |
| 3 | 1.04 | 0.67 | 0.14 | 0.67 | 0.698 |
| 5 | 1.04 | 0.68 | 0.40 | 0.43 | 0.696 |
| 7 | 1.04 | 0.87 | 0.35 | 0.40 | 0.689 |