"""Daily spatial SST features from the MUR grid (0.1 deg, 30.5-33.6N, 119.6-116.9W).

warm-water extent, distance from Point Loma to warm water, frontal strength,
SST at named banks. Output data/ext/mur_daily.pkl indexed by date.
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
PL = (32.67, -117.24)  # Point Loma
BANKS = {"coronados": (32.4, -117.3), "nine_mile": (32.6, -117.4), "f43": (32.6, -117.5),
         "sixty_mile": (32.1, -118.2), "tanner": (32.7, -119.1), "cortez": (32.4, -119.1),
         "san_clemente": (32.9, -118.5), "ens_baja": (31.3, -116.9)}


def km(lat1, lon1, lat2, lon2):
    return 111.0 * np.hypot(lat2 - lat1, (lon2 - lon1) * np.cos(np.radians((lat1 + lat2) / 2)))


def main():
    files = sorted((HERE / "data" / "ext" / "mur").glob("mur_*.csv"))
    rows = []
    for f in files:
        g = pd.read_csv(f, skiprows=[1])
        g["date"] = pd.to_datetime(g.time.str[:10])
        g["f"] = g.analysed_sst * 9 / 5 + 32
        lats = np.sort(g.latitude.unique()); lons = np.sort(g.longitude.unique())
        LA, LO = np.meshgrid(lats, lons, indexing="ij")
        dist = km(PL[0], PL[1], LA, LO)
        within = dist <= 150  # ~80 nmi radius = realistic 1-2 day range
        bank_idx = {k: (np.abs(lats - a).argmin(), np.abs(lons - b).argmin()) for k, (a, b) in BANKS.items()}
        for dt, dd in g.groupby("date"):
            Z = dd.pivot(index="latitude", columns="longitude", values="f").reindex(index=lats, columns=lons).to_numpy()
            ocean = ~np.isnan(Z)
            r = {"date": dt}
            for th in (64, 66, 68, 70, 72):
                w = (Z >= th) & ocean
                r[f"warm{th}_frac150"] = w[within].sum() / max(1, (ocean & within).sum())
                r[f"warm{th}_dist"] = dist[w].min() if w.any() else 400.0
            gy, gx = np.gradient(Z)  # deg F per 0.1 deg cell
            gm = np.hypot(gy, gx)
            sel = within & ~np.isnan(gm)
            r["front_mean150"] = np.nanmean(gm[sel]) if sel.any() else np.nan
            r["front_p90_150"] = np.nanpercentile(gm[sel], 90) if sel.any() else np.nan
            r["front_cells150"] = (gm[sel] > 0.5).sum() if sel.any() else np.nan  # >0.5F per ~10km
            r["sst_mean150"] = np.nanmean(Z[within & ocean])
            r["sst_max150"] = np.nanmax(Z[within & ocean])
            for k, (i, j) in bank_idx.items():
                r[f"bank_{k}"] = Z[i, j]
            rows.append(r)
        print(f.name, len(rows), flush=True)
    m = pd.DataFrame(rows).set_index("date").sort_index()
    m = m.reindex(pd.date_range(m.index.min(), m.index.max())).interpolate(limit=3)
    for c in ["warm66_frac150", "warm68_frac150", "warm68_dist", "sst_mean150"]:
        m[f"{c}_d7"] = m[c] - m[c].shift(7)
        m[f"{c}_d30"] = m[c] - m[c].shift(30)
    # seasonal anomaly of mean SST: deviation from day-of-year mean (computed later per fold is
    # stricter; a whole-record doy mean leaks only the seasonal shape, not the anomaly sign)
    m.to_pickle(HERE / "data" / "ext" / "mur_daily.pkl")
    print(m.shape, m.index.min(), m.index.max())


if __name__ == "__main__":
    main()
