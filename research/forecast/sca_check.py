"""H6: NWS Small Craft Advisories (IEM VTEC, PZZ750 coastal + PZZ775 outer, SD) vs fleet activity and bite.
'Known the night before' = advisory product issued by 20:00 local on day-1 and in effect 04-16 local on the fishing day."""
import json, sys, numpy as np, pandas as pd
from harness import HERE, auc
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ev = []
for z in ("PZZ750", "PZZ775"):
    for e in json.loads((HERE / "data/ext/nws" / f"vtec_{z}.json").read_text())["events"]:
        ev.append(dict(z=z, ph=e["phenomena"], start=pd.Timestamp(e["issue"]), end=pd.Timestamp(e["expire"]),
                       pt=pd.Timestamp(e["product_id"][:12] + "+00:00") if e.get("product_id") else pd.NaT))
ev = pd.DataFrame(ev); print(ev.ph.value_counts().to_dict())
ev = ev[ev.ph.isin(["SC", "GL", "SE", "HF", "SI", "SW", "TR"])]  # small craft, gale, hazardous seas, hurricane-force
tz = "America/Los_Angeles"
days = pd.date_range("2016-01-01", "2026-11-20")
def flag(zs, known_night_before):
    out = np.zeros(len(days), bool)
    for _, e in ev[ev.z.isin(zs)].iterrows():
        for i, d in enumerate(days):
            pass
    return out
# vectorised: for each day, window [04,16] local
w0 = pd.DatetimeIndex([d + pd.Timedelta(hours=4) for d in days]).tz_localize(tz).tz_convert("UTC")
w1 = w0 + pd.Timedelta(hours=12); nb = w0 - pd.Timedelta(hours=8)  # 20:00 local day-1
def fl(zs, known):
    e = ev[ev.z.isin(zs)]; f = np.zeros(len(days), bool)
    for s, t, p in zip(e.start, e.end, e.pt):
        hit = (s < w1) & (t > w0)
        if known: hit &= (p <= nb) if pd.notna(p) else False
        f |= np.asarray(hit)
    return f
F = pd.DataFrame({"sca_any": fl(["PZZ750", "PZZ775"], False), "sca_nb": fl(["PZZ750", "PZZ775"], True),
                  "sca_coast_nb": fl(["PZZ750"], True)}, index=days)
d = pd.read_pickle(HERE / "data" / "ds2_lead0.pkl"); d = d[d.region == "san_diego"]
a = d.groupby("dep").size().rename("n").to_frame().reindex(days, fill_value=0)
a["dow"] = a.index.day_of_week
a["exp"] = a.groupby("dow").n.transform(lambda s: s.rolling(7, center=True, min_periods=3).median())
a = a.join(F); a = a[a.exp >= 3]; a["ratio"] = a.n / a.exp; a["big"] = a.ratio < 0.6
lines = ["# H6 — NWS marine advisories vs fleet activity and bite (San Diego)", "",
         "| flag | days flagged | activity when flagged | when not | big-drop rate flagged / not | AUC for big drop |", "|---|---|---|---|---|---|"]
for c in F.columns:
    f = a[c]
    lines.append(f"| {c} | {int(f.sum())} ({f.mean():.0%}) | {a.ratio[f].mean():.2f} | {a.ratio[~f].mean():.2f} | "
                 f"{a.big[f].mean():.0%} / {a.big[~f].mean():.0%} | {auc(a.big, f.astype(float)):.3f} |")
# combined with the wind forecast (lead 1) where available
import json as _j
P = HERE / "data/ext/prevruns"
fr = [pd.DataFrame(_j.loads(p.read_text())["hourly"]) for p in sorted(P.glob("wind_*.json"))]
h = pd.concat(fr); h["time"] = pd.to_datetime(h.time); h = h.set_index("time").apply(pd.to_numeric, errors="coerce")
w = h.between_time("04:00", "16:00").resample("D").max().wind_speed_10m_previous_day1.rename("w1")
x = a.join(w).dropna(subset=["w1"])
lines += ["", f"2022–26 overlap (n={len(x)} days): AUC big-drop — wind fc lead1 {auc(x.big, x.w1):.3f}, "
          f"SCA night-before {auc(x.big, x.sca_nb.astype(float)):.3f}, wind + 10·SCA {auc(x.big, x.w1 + 10 * x.sca_nb):.3f}"]
# bite on trips that did run
t = d[d.pct.notna()].join(F, on="dep"); t["above"] = (t.pct > 0.5).astype(float)
lines += ["", "Bite on trips that ran (share beating normal): " + ", ".join(
    f"{c}: {t.above[t[c] == True].mean():.0%} (n={int((t[c] == True).sum())}) vs {t.above[t[c] == False].mean():.0%}" for c in F.columns)]
(HERE / "data" / "sca_check.md").write_text("\n".join(lines), encoding="utf-8"); print("\n".join(lines))
