"""Build the SAMPLE Surfline-style 7-day SD tuna forecast page (research only, not production).

Inputs: data/outlook_tuna_live.json (fleet tuna outlook), data/ext/live/sea_days.json (Open-Meteo
wind/wave/SST + NOAA tides + moon), data/outlook_tuna_bt.csv (held-out skill by lead).
Output: sample_7day_forecast.html
"""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
live = json.loads((HERE / "data/outlook_tuna_live.json").read_text(encoding="utf-8"))
sea = json.loads((HERE / "data/ext/live/sea_days.json").read_text(encoding="utf-8"))
bt = pd.read_csv(HERE / "data/outlook_tuna_bt.csv")
skill = {int(r.lead): dict(r_model=round(r.r_model_hold23_26, 3), r_persist=round(r.r_persist_hold23_26, 3),
                           brier=round(r.good_brier_hold23_26, 3), brier_clim=round(r.good_brier_clim_hold23_26, 3))
         for r in bt.itertuples()}
payload = dict(meta=live["meta"], days=live["days"], sea=sea, skill=skill)
tpl = (HERE / "sample_page_template.html").read_text(encoding="utf-8")
out = tpl.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
(HERE / "sample_7day_forecast.html").write_text(out, encoding="utf-8")
print("wrote sample_7day_forecast.html")
