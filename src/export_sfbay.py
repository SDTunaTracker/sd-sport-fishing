"""SF Bay Area export: norcal_trips -> web/data-region-sfbay.js (window.SFBAY).

Kept apart from data.js (window.SD) on purpose:
  * San Diego / OC-LA code never sees SF Bay trips, so the "All SoCal"
    (no landing filter) views can't pick them up.
  * The file is only loaded when SHOW_SFBAY is on (web/feature-flags.js), so
    SD visitors download nothing extra.

Everything here is derived and rebuilt on every run (targets, limit rates,
six-pack classification, boat list), so a regs change in src/norcal.py takes
effect on the next export without touching stored rows.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import norcal as N
from .dates import pacific_today

SFBAY_JS_REL = "data-region-sfbay.js"

# Booking pages verified by hand. Only verified links ship; the UI says
# "booking link coming soon" for the rest. Key = landing name as posted.
LANDING_SITES: dict[str, dict] = {
    "Fish Emeryville": {"site": "https://www.fishemeryville.com/",
                        "booking": "https://emeryville.fishingreservations.net/sales/"},
}

# Conditions sources (links only for v1; live values are a follow-up).
CONDITIONS = [
    {"id": "ndbc-46026", "label": "SF buoy (18 nm W)", "url": "https://www.ndbc.noaa.gov/station_page.php?station=46026"},
    {"id": "ndbc-46012", "label": "Half Moon Bay buoy (24 nm SSW of SF)", "url": "https://www.ndbc.noaa.gov/station_page.php?station=46012"},
    {"id": "ndbc-46237", "label": "SF Bar waverider", "url": "https://www.ndbc.noaa.gov/station_page.php?station=46237"},
    {"id": "tide-9414290", "label": "SF tides (Golden Gate)", "url": "https://tidesandcurrents.noaa.gov/stationhome.html?id=9414290"},
    {"id": "nws-marine", "label": "Bay Area marine and bar forecast (NWS)", "url": "https://www.weather.gov/mtr/marine"},
]


def _marine(conn: sqlite3.Connection) -> dict | None:
    """Live marine conditions (NWS zones, SF tides, buoys incl. the SF Bar)
    from src.marine, built by the data-health session (branch
    claude/ais-conditions). Optional: None until that module is on main and
    has data, and the page falls back to links."""
    try:
        from . import marine
    except ImportError:
        return None
    try:
        m = marine.region_payload(conn, N.REGION_SF_BAY)
    except Exception:
        return None
    return m if (m and (m.get("zones") or m.get("buoys") or (m.get("tides") or {}).get("events"))) else None


def _r(v, n=3):
    return None if v is None else round(v, n)


def build_payload(conn: sqlite3.Connection, today: date | None = None) -> dict:
    today = today or pacific_today()
    rows = conn.execute(
        "SELECT date, boat, boat_slug, landing, landing_slug, port, trip_type_raw, trip_length,"
        " trip_length_days, anglers, landed_json FROM norcal_trips WHERE region = ?"
        " ORDER BY date, landing, boat", (N.REGION_SF_BAY,)).fetchall()

    trips: list[dict] = []
    for (d, boat, slug, landing, lslug, port, ttype, tl, tld, anglers, lj) in rows:
        landed = json.loads(lj or "{}")
        trips.append({
            "date": d, "boat": boat, "boat_slug": slug, "landing": landing, "landing_slug": lslug,
            "port": port, "trip": ttype, "bucket": tl, "days": tld, "anglers": anglers,
            "landed": landed, "target": N.infer_target(ttype, landed, anglers),
        })
    N.fill_unknown_targets(trips)
    sixpack = N.classify_sixpacks(trips)

    boats: dict[str, dict] = {}
    for t in trips:
        b = boats.setdefault(t["boat_slug"], {
            "slug": t["boat_slug"], "name": t["boat"], "landing": t["landing"], "port": t["port"],
            "sixpack": sixpack.get(t["boat_slug"], False), "trips": 0, "first": t["date"],
            "last": t["date"], "maxAnglers": 0, "targets": Counter(),
        })
        b["trips"] += 1
        b["last"] = t["date"]
        b["name"], b["landing"], b["port"] = t["boat"], t["landing"], t["port"]  # latest wins
        b["maxAnglers"] = max(b["maxAnglers"], t["anglers"])
        b["targets"][t["target"]] += 1
    boat_list = sorted(boats.values(), key=lambda b: (-b["trips"], b["name"]))
    idx = {b["slug"]: i for i, b in enumerate(boat_list)}
    for b in boat_list:
        b["mainTarget"] = b["targets"].most_common(1)[0][0]
        b["targets"] = dict(b["targets"])

    # Compact rows: [date, boatIdx, tripLabel, anglers, target, limitRate, halfDay, catch]
    out_trips = []
    for t in trips:
        rate = N.limit_rate(t["target"], t["landed"], t["anglers"])
        out_trips.append([
            t["date"], idx[t["boat_slug"]], t["trip"], t["anglers"], t["target"],
            _r(rate), 1 if N.is_half_day(t["days"]) else 0, t["landed"],
        ])

    landings: dict[str, dict] = {}
    for b in boat_list:
        L = landings.setdefault(b["landing"], {"name": b["landing"], "port": b["port"], "boats": 0,
                                               **LANDING_SITES.get(b["landing"], {})})
        L["boats"] += 1
    for t in trips:
        if t.get("landing_slug"):
            landings[t["landing"]]["slug"] = t["landing_slug"]

    latest = trips[-1]["date"] if trips else None
    since7 = (today - timedelta(days=7)).isoformat()
    open7 = sum(1 for t in trips if t["date"] > since7 and not sixpack.get(t["boat_slug"]))
    fetch_rows = conn.execute(
        "SELECT date, status, rows, no_counts FROM norcal_fetch_log WHERE date > ? ORDER BY date",
        ((today - timedelta(days=14)).isoformat(),)).fetchall()

    return {
        "MARINE": _marine(conn),
        "META": {
            "region": N.REGION_SF_BAY,
            "label": "SF Bay Area",
            "ports": sorted(set(N.SF_BAY_PORTS.values())),
            "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "latestDate": latest,
            "firstDate": trips[0]["date"] if trips else None,
            "tripCount": len(out_trips),
            "openTrips7d": open7,
            "slowSeason": open7 < N.SLOW_SEASON_TRIPS_7D,
            "source": "norcalfishreports.com",
            "recentFetches": [{"date": d, "status": s, "rows": r, "noCounts": bool(nc)}
                              for d, s, r, nc in fetch_rows],
        },
        "TARGETS": {k: {"label": v["label"], "groups": list(v["groups"])} for k, v in N.TARGETS.items()},
        "BAG_LIMITS": N.BAG_LIMITS,
        "SEASONS": N.SEASONS,
        "CONDITIONS": CONDITIONS,
        "LANDINGS": sorted(landings.values(), key=lambda L: (-L["boats"], L["name"])),
        "BOATS": boat_list,
        "TRIP_FIELDS": ["date", "boat", "trip", "anglers", "target", "limitRate", "halfDay", "catch"],
        "TRIPS": out_trips,
    }


def write_sfbay_js(conn: sqlite3.Connection, web_dir: Path, today: date | None = None) -> tuple[Path, int]:
    payload = build_payload(conn, today=today)
    body = json.dumps(payload, separators=(",", ":"), default=str, ensure_ascii=False)
    path = web_dir / SFBAY_JS_REL
    path.write_text("// Auto-generated by src/export_sfbay.py. Do not edit.\nwindow.SFBAY=" + body + ";\n",
                    encoding="utf-8")
    return path, len(payload["TRIPS"])
