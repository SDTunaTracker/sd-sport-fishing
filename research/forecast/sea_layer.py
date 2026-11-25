"""Sea-conditions layer: how well do ARCHIVED wind forecasts (Open-Meteo Previous Runs, 9-Mile Bank)
predict rough days and fleet cancellations 1-7 days out? Research only."""
import json, sys, warnings
import numpy as np, pandas as pd
from harness import HERE, auc
warnings.filterwarnings("ignore"); sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = HERE / "data" / "ext" / "prevruns"
fr = []
for f in sorted(P.glob("wind_*.json")):
    j = json.loads(f.read_text())["hourly"]; fr.append(pd.DataFrame(j))
h = pd.concat(fr); h["time"] = pd.to_datetime(h.time); h = h.set_index("time").apply(pd.to_numeric, errors="coerce")
h = h.between_time("04:00", "16:00")  # fishing hours
dmax = h.resample("D").max()
leads = [1, 2, 3, 5, 7]
obs = dmax.wind_speed_10m
lines = ["# Sea-conditions layer (wind) — archived forecasts vs what happened", "",
         f"9-Mile Bank, daily max 10 m wind 04:00–16:00 local, {dmax.index.min():%Y-%m-%d} … {dmax.index.max():%Y-%m-%d}.", "",
         "| lead (days) | MAE kn | corr | rough day (≥20 kn) AUC | hit rate when forecast ≥20 | caught |", "|---|---|---|---|---|---|"]
rough = obs >= 20
for k in leads:
    fc = dmax[f"wind_speed_10m_previous_day{k}"]; ok = fc.notna() & obs.notna()
    f, o, r = fc[ok], obs[ok], rough[ok]
    lines.append(f"| {k} | {np.mean(np.abs(f-o)):.1f} | {np.corrcoef(f.to_numpy(float),o.to_numpy(float))[0,1]:.2f} | {auc(r, f):.3f} | "
                 f"{r[f>=20].mean():.0%} (n={int((f>=20).sum())}) | {(f[r]>=20).mean():.0%} of {int(r.sum())} |")
# fleet activity (San Diego): trips departing vs usual for weekday/season
d = pd.read_pickle(HERE / "data" / "ds2_lead0.pkl"); d = d[d.region == "san_diego"]
a = d.groupby("dep").size().rename("n").to_frame().reindex(pd.date_range("2016-01-01", "2026-11-20"), fill_value=0)
a["dow"] = a.index.day_of_week
a["exp"] = a.groupby("dow").n.transform(lambda s: s.rolling(7, center=True, min_periods=3).median())
a = a[a.exp >= 3]; a["ratio"] = a.n / a.exp; a["cancel"] = a.ratio < 0.6
lines += ["", "Fleet activity (San Diego trips that ran ÷ usual for that weekday/season) by FORECAST wind:", "",
          "| lead | <15 kn | 15–20 | 20–25 | ≥25 | 'big drop' (<60% usual) AUC |", "|---|---|---|---|---|---|"]
for k in [0] + leads:
    col = "wind_speed_10m" if k == 0 else f"wind_speed_10m_previous_day{k}"
    x = a.join(dmax[col].rename("w")).dropna()
    g = x.groupby(pd.cut(x.w, [0, 15, 20, 25, 99]), observed=True).ratio.mean()
    lines.append(f"| {k if k else 'actual'} | " + " | ".join(f"{v:.2f}" for v in g.reindex(g.index).values) +
                 f" | {auc(x.cancel, x.w):.3f} |")
(HERE / "data" / "sea_layer.md").write_text("\n".join(lines), encoding="utf-8"); print("\n".join(lines))
