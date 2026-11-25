"""Fetch MUR SST (NASA JPL, free via NOAA CoastWatch ERDDAP) on a 0.1-degree
grid over the SD/Baja offshore fishing grounds, one year per request.
Output: data/ext/mur/mur_<year>.csv  (time, lat, lon, analysed_sst in deg C)
"""
import sys
import time
from pathlib import Path

import requests

OUT = Path(__file__).parent / "data" / "ext" / "mur"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.csv"

for yr in range(2014, 2027):
    f = OUT / f"mur_{yr}.csv"
    if f.exists() and f.stat().st_size > 1000:
        continue
    end = f"{yr}-12-31" if yr < 2026 else "2026-11-20"
    q = (f"?analysed_sst[({yr}-01-01T09:00:00Z):1:({end}T09:00:00Z)]"
         f"[(30.5):10:(33.6)][(-119.6):10:(-116.9)]")
    for attempt in range(3):
        try:
            r = requests.get(BASE + q, timeout=600)
            print(yr, r.status_code, len(r.content), flush=True)
            if r.status_code == 200:
                f.write_bytes(r.content)
                break
        except Exception as e:
            print(yr, "err", e, flush=True)
        time.sleep(10)
