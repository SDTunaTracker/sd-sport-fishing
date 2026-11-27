"""Every named San Diego County surf spot, Oceanside Harbor to the border.

The 12 tuned breaks live in breaks.py (owned by the surf model work). This
module adds the rest of the county's named spots with DEFAULT settings (type,
tide window, swell window are generic until tuned) and forecasts them with the
same, unchanged forecast.break_forecast(), into a separate file:

    python -m src.surf.spots                    # write web/api/v1/surf_spots.json
    python -m src.surf.spots --build-mop-table  # rebuild src/surf/mop_points.json

Run it once or twice a day; it is ~4 CDIP requests per spot (cached 30 min).

Spot list: our own, from public, licence-clean sources only. `src` says where
each coordinate came from:
  gnis   USGS Geographic Names Information System (public domain)
  osm    OpenStreetMap via Nominatim (ODbL; © OpenStreetMap contributors)
  local  general local knowledge (approximate, within a few hundred metres)
No commercial forecaster's spot list or coordinates were used. Coordinates only
need to pick the right stretch of coast: each spot is forecast at its nearest
CDIP MOP point (~100 m apart along the 10 m contour; table in mop_points.json).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .breaks import BREAKS

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "api" / "v1" / "surf_spots.json"
MOP_TABLE = Path(__file__).with_name("mop_points.json")

# id, name, lat, lon, type (beach|reef), src[, note]
SPOTS: list[tuple] = [
    # Oceanside
    ("tyson-street", "Tyson Street", 33.1914, -117.3840, "beach", "osm"),
    ("wisconsin-street", "Wisconsin Street", 33.1870, -117.3800, "beach", "local"),
    ("buccaneer-beach", "Buccaneer Beach", 33.1815, -117.3736, "beach", "osm"),
    ("cassidy-street", "Cassidy Street", 33.1755, -117.3675, "beach", "osm"),
    ("st-malo", "St. Malo", 33.1670, -117.3606, "beach", "gnis", "Private beach; access is limited."),
    # Carlsbad
    ("carlsbad-state-beach", "Carlsbad State Beach", 33.1600, -117.3530, "beach", "local"),
    ("tamarack", "Tamarack", 33.1478, -117.3466, "beach", "local"),
    ("warm-water-jetties", "Warm Water Jetties", 33.1380, -117.3400, "beach", "osm"),
    ("terramar", "Terramar", 33.1290, -117.3330, "reef", "local"),
    ("south-carlsbad", "South Carlsbad State Beach", 33.1082, -117.3217, "beach", "osm"),
    ("ponto", "Ponto", 33.0870, -117.3115, "beach", "gnis"),
    # Encinitas / Leucadia / Cardiff
    ("grandview", "Grandview", 33.0794, -117.3111, "beach", "osm"),
    ("beacons", "Beacon's", 33.0650, -117.3050, "reef", "local"),
    ("stone-steps", "Stone Steps", 33.0560, -117.3010, "reef", "local"),
    ("moonlight", "Moonlight Beach", 33.0483, -117.2985, "beach", "osm"),
    ("d-street", "D Street", 33.0456, -117.2974, "beach", "osm"),
    ("boneyards", "Boneyards", 33.0390, -117.2960, "reef", "local"),
    ("pipes", "Pipes", 33.0270, -117.2880, "reef", "local"),
    ("seaside-reef", "Seaside Reef", 33.0005, -117.2785, "reef", "local"),
    # Solana Beach / Del Mar / Torrey Pines
    ("tide-park", "Tide Park", 32.9944, -117.2760, "reef", "osm"),
    ("fletcher-cove", "Fletcher Cove", 32.9914, -117.2745, "beach", "osm"),
    ("seascape", "Seascape Surf", 32.9850, -117.2720, "beach", "local"),
    ("del-mar-rivermouth", "Del Mar Rivermouth", 32.9690, -117.2700, "beach", "local"),
    ("del-mar-15th", "Del Mar (15th Street)", 32.9590, -117.2680, "beach", "osm"),
    ("torrey-pines", "Torrey Pines State Beach", 32.9314, -117.2604, "beach", "osm"),
    # La Jolla
    ("la-jolla-cove", "La Jolla Cove", 32.8506, -117.2714, "reef", "gnis"),
    ("boomer-beach", "Boomer Beach", 32.8500, -117.2742, "beach", "gnis", "Heavy shorebreak; experts only."),
    ("wipeout-beach", "Wipeout Beach", 32.8450, -117.2792, "beach", "gnis"),
    ("marine-street", "Marine Street", 32.8370, -117.2814, "beach", "gnis"),
    ("simmons", "Simmons", 32.8270, -117.2820, "reef", "local"),
    ("big-rock", "Big Rock", 32.8223, -117.2814, "reef", "gnis"),
    ("bird-rock", "Bird Rock", 32.8142, -117.2742, "reef", "gnis"),
    # Pacific Beach / Mission Beach
    ("pb-point", "Pacific Beach Point", 32.8075, -117.2670, "reef", "gnis"),
    ("tourmaline", "Tourmaline", 32.8053, -117.2620, "reef", "osm"),
    ("mission-beach", "Mission Beach", 32.7709, -117.2540, "beach", "osm"),
    ("south-mission-jetty", "South Mission Jetty", 32.7607, -117.2530, "beach", "osm"),
    # Ocean Beach / Point Loma
    ("ob-dog-beach", "Ocean Beach (Dog Beach)", 32.7553, -117.2531, "beach", "gnis"),
    ("osprey-point", "Osprey Point", 32.7362, -117.2561, "reef", "gnis"),
    ("pappys-point", "Pappy's Point", 32.7334, -117.2573, "reef", "gnis"),
    ("abs", "Ab's", 32.7284, -117.2567, "reef", "gnis"),
    ("ratkay-point", "Ratkay Point", 32.7256, -117.2584, "reef", "gnis"),
    # Coronado / Silver Strand / Imperial Beach
    ("coronado-north-beach", "Coronado (North Beach)", 32.6862, -117.1925, "beach", "gnis"),
    ("coronado-central", "Coronado Central Beach", 32.6842, -117.1870, "beach", "gnis"),
    ("coronado-shores", "Coronado Shores", 32.6764, -117.1745, "beach", "gnis"),
    ("silver-strand", "Silver Strand State Beach", 32.6342, -117.1702, "beach", "osm"),
    ("ib-north", "Imperial Beach (North End)", 32.5890, -117.1345, "beach", "local"),
    ("ib-south", "Imperial Beach (South End)", 32.5650, -117.1300, "beach", "local"),
    ("tijuana-rivermouth", "Tijuana River Mouth", 32.5530, -117.1290, "beach", "local",
     "Often closed for sewage contamination. Check county beach water quality first."),
    ("border-field", "Border Field", 32.5424, -117.1250, "beach", "osm",
     "Often closed for sewage contamination. Check county beach water quality first."),
]

# Generic settings until a spot is tuned [D] (agreed with the surf model session):
# - swell window from each spot's own MOP shore normal ± 60°;
# - a wide, no-penalty tide window, since we don't know the spot's preference;
# - rating capped at FAIR (3.0) via `potential` (rate() caps at it), below the
#   FAIR–GOOD model ceiling used for the tuned breaks.
DEFAULTS = {
    "beach": {"gamma": 0.78},
    "reef": {"gamma": 0.95},
}
TIDE_ANY = (-2.0, 8.0)
SWELL_HALF = 60
POTENTIAL_UNTUNED = 2.99   # just under FAIR–GOOD (labels switch at 3.0)

AREAS = (  # (south limit latitude, area); first match from the north
    (32.975, "North County"),
    (32.81, "Del Mar–La Jolla"),
    (32.70, "PB–Point Loma"),
    (-90, "Coronado–Imperial Beach"),
)


def area_of(lat: float) -> str:
    return next(a for lim, a in AREAS if lat > lim)


def _km(a_lat, a_lon, b_lat, b_lon) -> float:
    x = math.radians(b_lon - a_lon) * math.cos(math.radians((a_lat + b_lat) / 2))
    y = math.radians(b_lat - a_lat)
    return 6371 * math.hypot(x, y)


def mop_table() -> list[dict]:
    t = json.loads(MOP_TABLE.read_text(encoding="utf-8"))
    pts = [dict(zip(t["fields"], p)) for p in t["points"]]
    return [p for p in pts if 0 <= p["normal"] <= 360]   # D0930: normal missing


def nearest_mop(lat: float, lon: float, table: list[dict]) -> tuple[dict, float]:
    best = min(table, key=lambda p: _km(lat, lon, p["lat"], p["lon"]))
    return best, _km(lat, lon, best["lat"], best["lon"])


def spot_configs() -> list[dict]:
    """SPOTS as break configs for forecast.break_forecast(), default settings."""
    table = mop_table()
    out = []
    for s in SPOTS:
        sid, name, lat, lon, typ, src = s[:6]
        mop, km = nearest_mop(lat, lon, table)
        near = min(BREAKS, key=lambda b: _km(lat, lon, b["lat"], b["lon"]))
        d = DEFAULTS[typ]
        n = mop["normal"]
        cfg = {"id": sid, "name": name, "lat": lat, "lon": lon, "mop": mop["id"], "type": typ,
               "gamma": d["gamma"], "cal": 1.0, "tide": TIDE_ANY,
               "swell": (n - SWELL_HALF, n + SWELL_HALF), "buoy": near["buoy"],
               "potential": POTENTIAL_UNTUNED, "src": src, "mopKm": round(km, 2)}
        if len(s) > 6:
            cfg["note"] = s[6]
        out.append(cfg)
    return out


def build(now: datetime | None = None) -> dict:
    from . import forecast as F
    from .extras import energy_kj

    now = now or datetime.now(timezone.utc)
    cfgs = spot_configs()
    try:
        winds = F.wind_hourly(cfgs)
    except Exception as e:  # noqa: BLE001
        log.warning("spots wind failed: %s", e)
        winds = [{} for _ in cfgs]
    try:
        tide_h, _ = F.tides(now.replace(hour=0, minute=0) - timedelta(days=1))
    except Exception as e:  # noqa: BLE001
        log.warning("spots tides failed: %s", e)
        tide_h = {}
    spots = []
    for b, w in zip(cfgs, winds):
        try:
            r = F.break_forecast(b, w, tide_h, now)
        except Exception as e:  # noqa: BLE001
            log.warning("spot %s (%s) failed: %s", b["id"], b["mop"], e)
            continue
        for h in r["hours"]:
            e = energy_kj(h.get("hsM"), h.get("tpS"))
            if e is not None:
                h["energyKj"] = e
        r.update({"defaults": True, "area": area_of(b["lat"]), "src": b["src"],
                  "tideWindow": list(b["tide"]), "swellWindow": list(b["swell"])})
        if b.get("note"):
            r["note"] = b["note"]
        spots.append(r)
    return {"generatedAt": now.isoformat(timespec="minutes"), "staleAfterHours": 30,
            "label": "Model forecast", "settings": "default",
            "about": "More San Diego County spots, forecast with the same model as the main breaks but "
                     "with default settings (break type, tide and swell windows not yet tuned per spot).",
            "sources": "Spot names and positions: USGS GNIS (public domain), © OpenStreetMap "
                       "contributors (ODbL), local knowledge. Forecast point: nearest CDIP MOP point.",
            "spots": spots}


def write(path: Path = OUT) -> int:
    payload = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return len(payload["spots"])


def build_mop_table(first: int = 1, last: int = 930, path: Path = MOP_TABLE) -> int:
    """Rebuild mop_points.json from CDIP MOP metadata (D0001 = border … D0930)."""
    import re
    from concurrent.futures import ThreadPoolExecutor

    from . import cdip as C

    def one(i):
        pid = f"D{i:04d}"
        try:
            txt = C._get(C.mop_url(pid, "ecmwf_fc") + ".ascii?metaLatitude,metaLongitude,metaWaterDepth,"
                         "metaShoreNormal", 30 * 86400)
        except Exception as e:  # noqa: BLE001
            log.info("MOP %s: %s", pid, e)
            return None
        v = {k: float(m) for k, m in re.findall(r"^meta(\w+), ([-\d.]+)", txt, re.M)}
        return [pid, round(v["Latitude"], 5), round(v["Longitude"], 5), round(v["ShoreNormal"]),
                round(v["WaterDepth"], 1)]
    with ThreadPoolExecutor(4) as ex:
        rows = [r for r in ex.map(one, range(first, last + 1)) if r]
    path.write_text(json.dumps({"source": "CDIP MOP_alongshore *_ecmwf_fc metadata (metaLatitude, "
                                          "metaLongitude, metaShoreNormal, metaWaterDepth)",
                                "fields": ["id", "lat", "lon", "normal", "depthM"], "points": rows},
                               separators=(",", ":")), encoding="utf-8")
    return len(rows)


def main() -> int:
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if "--build-mop-table" in sys.argv:
        print(f"mop_points.json: {build_mop_table()} points")
        return 0
    print(f"surf_spots.json: {write()} spots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
