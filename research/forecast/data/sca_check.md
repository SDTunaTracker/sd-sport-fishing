# H6 — NWS marine advisories vs fleet activity and bite (San Diego)

| flag | days flagged | activity when flagged | when not | big-drop rate flagged / not | AUC for big drop |
|---|---|---|---|---|---|
| sca_any | 139 (6%) | 0.64 | 1.04 | 43% / 6% | 0.640 |
| sca_nb | 112 (5%) | 0.58 | 1.04 | 46% / 6% | 0.623 |
| sca_coast_nb | 69 (3%) | 0.40 | 1.03 | 64% / 6% | 0.610 |

2022–26 overlap (n=637 days): AUC big-drop — wind fc lead1 0.722, SCA night-before 0.541, wind + 10·SCA 0.723

Bite on trips that ran (share beating normal): sca_any: 40% (n=903) vs 41%, sca_nb: 40% (n=596) vs 41%, sca_coast_nb: 37% (n=298) vs 41%