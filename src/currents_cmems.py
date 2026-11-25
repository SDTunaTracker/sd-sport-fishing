"""Surface currents for the Charts map from Copernicus Marine (CMEMS).

This replaces the HYCOM feed that died in 2018, now a synthetic "DEMO" layer.
We checked the free US options first (2026-11-25): the SCCOOS/HFRNet HF-radar
dataset `ucsdHfrW6` returns 404/503 on NOAA CoastWatch ERDDAP, and the SCCOOS
ROMS nowcast stops in 2022. Copernicus is free for commercial use with the
credit line below. It needs a free account.

Product: GLOBAL_ANALYSISFORECAST_PHY_001_024, dataset
`cmems_mod_glo_phy-cur_anfc_0.083deg_PT6H-i` (uo/vo, 1/12°, 6-hourly, with a
10-day forecast). We take the surface level at the latest time step at or before
now, thin it to about 0.25°, and write leaflet-velocity JSON to web/currents_grid.json.

    pip install copernicusmarine          # only where this step runs
    set COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD
    python -m src.currents_cmems

It does nothing (exit 0) when the package or credentials are missing, so it is
safe in the daily workflow before the owner signs up.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "currents_grid.json"
DATASET = "cmems_mod_glo_phy-cur_anfc_0.083deg_PT6H-i"
CREDIT = "Generated using E.U. Copernicus Marine Service Information"
# Same extent as the Charts map's current grid (web/charts.jsx _CURR_*), plus a margin.
BBOX = {"lat_min": 30.0, "lat_max": 35.5, "lon_min": -121.5, "lon_max": -116.5}
STRIDE = 3  # 1/12° * 3 ≈ 0.25°


def to_velocity_json(lats, lons, u2d, v2d, ref_time: str, stride: int = STRIDE) -> dict:
    """Convert a surface uo/vo grid (rows = lats, cols = lons) to leaflet-velocity format.

    leaflet-velocity wants rows north→south, columns west→east, with la1 the
    northern edge. Land and missing cells (NaN) become 0 so particles stop there.
    Values stay in m/s, which is what the Charts layer expects.
    """
    lat_idx = list(range(0, len(lats), stride))
    lon_idx = list(range(0, len(lons), stride))
    if lats[0] < lats[-1]:          # ascending → flip to north-first
        lat_idx = lat_idx[::-1]
    sel_lats = [float(lats[i]) for i in lat_idx]
    sel_lons = [float(lons[j]) for j in lon_idx]

    def clean(x):
        x = float(x)
        return 0.0 if math.isnan(x) else round(x, 3)

    u = [clean(u2d[i][j]) for i in lat_idx for j in lon_idx]
    v = [clean(v2d[i][j]) for i in lat_idx for j in lon_idx]
    nx, ny = len(sel_lons), len(sel_lats)
    dx = round(abs(sel_lons[1] - sel_lons[0]), 4) if nx > 1 else 0.25
    dy = round(abs(sel_lats[0] - sel_lats[1]), 4) if ny > 1 else 0.25
    header = {
        "parameterCategory": 2, "lo1": sel_lons[0], "la1": sel_lats[0],
        "lo2": sel_lons[-1], "la2": sel_lats[-1], "dx": dx, "dy": dy,
        "nx": nx, "ny": ny, "refTime": ref_time,
    }
    valid = sum(1 for a, b in zip(u, v) if a or b)
    return {
        "source": f"Copernicus Marine {DATASET}",
        "credit": CREDIT,
        "refTime": ref_time,
        "validCells": valid,
        "data": [
            {"header": {**header, "parameterNumber": 2}, "data": u},
            {"header": {**header, "parameterNumber": 3}, "data": v},
        ],
    }


def fetch_grid(now: datetime | None = None) -> dict:
    import copernicusmarine  # optional dependency, imported only when credentials exist

    now = now or datetime.now(timezone.utc)
    ds = copernicusmarine.open_dataset(
        dataset_id=DATASET,
        variables=["uo", "vo"],
        minimum_longitude=BBOX["lon_min"], maximum_longitude=BBOX["lon_max"],
        minimum_latitude=BBOX["lat_min"], maximum_latitude=BBOX["lat_max"],
        minimum_depth=0, maximum_depth=1,
        start_datetime=(now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S"),
        end_datetime=now.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    ds = ds.isel(depth=0, time=-1)
    ref = str(ds["time"].values)[:19] + "Z"
    lats = ds["latitude"].values
    lons = ds["longitude"].values
    return to_velocity_json(lats, lons, ds["uo"].values, ds["vo"].values, ref)


def run(out: Path = OUT) -> str:
    if not (os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") and os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")):
        return "Currents: no Copernicus credentials; Charts keeps the DEMO layer"
    try:
        import copernicusmarine  # noqa: F401
    except ImportError:
        return "Currents: `copernicusmarine` not installed; Charts keeps the DEMO layer"
    grid = fetch_grid()
    if grid["validCells"] < 20:
        raise ValueError(f"too few ocean cells ({grid['validCells']}); keeping the old file")
    out.write_text(json.dumps(grid, separators=(",", ":")), encoding="utf-8")
    return f"Currents: wrote {out.name} ({grid['validCells']} cells, {grid['refTime']})"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        print(run())
    except Exception as e:  # never fail the daily workflow over the map layer
        print(f"Currents ERROR (non-fatal): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
