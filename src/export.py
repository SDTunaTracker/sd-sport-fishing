"""Dump trips out of SQLite into web/data.js so the static front-end can render.

The output mirrors the shape the design's analytics.js expects (window.SD.TRIPS)
but extends it with yellowtail, dorado, trophyCount, and per-angler-per-day so
the trophy-focused dashboard works.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .conditions import snapshot as conditions_snapshot

LANDINGS = (
    "H&M Landing",
    "Fisherman's Landing",
    "Point Loma Sportfishing",
    "Seaforth Sportfishing",
)

TRIP_LENGTHS = (
    "3/4 Day", "Full Day", "Overnight",
    "1.5 Day", "2 Day", "2.5 Day", "3 Day", "4 Day", "5 Day",
    "6 Day", "7 Day", "Long Range",
)

SPECIES = ("Bluefin", "Yellowfin", "Yellowtail", "Dorado",
           "Skipjack", "Bigeye", "Albacore")

TROPHY_SPECIES = ("Bluefin", "Yellowfin", "Yellowtail", "Dorado")

MOON_PHASES = ("New", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
               "Full", "Waning Gibbous", "Last Quarter", "Waning Crescent")


def _trip_to_js(row: sqlite3.Row) -> dict:
    d = row["date"]
    year, month, day = (int(x) for x in d.split("-"))
    return {
        "id": row["id"],
        "date": d,
        "year": year,
        "month": month,
        "day": day,
        "boat": row["boat"],
        "landing": row["landing"],
        "tripLength": row["trip_length"],
        "tripLengthDays": row["trip_length_days"],
        "anglers": row["anglers"],
        "Bluefin": row["bluefin"],
        "Yellowfin": row["yellowfin"],
        "Yellowtail": row["yellowtail"],
        "Dorado": row["dorado"],
        "Skipjack": row["skipjack"],
        "Bigeye": row["bigeye"],
        "Albacore": row["albacore"],
        "trophyCount": row["trophy_count"],
        "trophyPerAngler": row["trophy_per_angler"],
        "trophyPerAnglerPerDay": row["trophy_per_angler_per_day"],
        # Alias so the design's analytics.js can keep using `totalTuna` as the
        # "all species" rollup field. With trophy-focused semantics this is the
        # trophy count (bluefin + yellowfin + yellowtail + dorado).
        "totalTuna": row["trophy_count"],
        "moonPhase": row["moon_phase"],
        "moonIllum": row["moon_illum"],
        "daysFromNew": row["days_from_new"],
        "daysFromFull": row["days_from_full"],
    }


def _boats_from_trips(trips: list[dict]) -> list[dict]:
    """Distinct boat/landing pairs seen in the data, with the trip lengths each
    boat has actually run. Drives the boat-filter dropdown."""
    by_key: dict[tuple[str, str], dict] = {}
    for t in trips:
        key = (t["boat"], t["landing"])
        b = by_key.setdefault(key, {"name": t["boat"], "landing": t["landing"], "lengths": set()})
        b["lengths"].add(t["tripLength"])
    return [
        {"name": b["name"], "landing": b["landing"], "lengths": sorted(b["lengths"])}
        for b in sorted(by_key.values(), key=lambda x: (x["landing"], x["name"]))
    ]


def _scheduled_to_js(row: sqlite3.Row) -> dict:
    return {
        "landing": row["landing"],
        "boat": row["boat"],
        "tripTypeRaw": row["trip_type_raw"],
        "tripLength": row["trip_length"],
        "tripLengthDays": row["trip_length_days"],
        "departureAt": row["departure_at"],
        "returnAt": row["return_at"],
        "price": row["price"],
        "capacity": row["capacity"],
        "openSpots": row["open_spots"],
        "reservedSpots": row["reserved_spots"],
        "note": row["note"],
        "sourceId": row["source_id"],
    }


def export(conn: sqlite3.Connection, out_path: Path) -> int:
    """Write data.js. Returns trip count written."""
    rows = conn.execute("SELECT * FROM trips ORDER BY date, id").fetchall()
    trips = [_trip_to_js(r) for r in rows]
    boats = _boats_from_trips(trips)
    schedule_rows = conn.execute(
        "SELECT * FROM scheduled_trips ORDER BY departure_at, landing, boat"
    ).fetchall()
    schedule = [_scheduled_to_js(r) for r in schedule_rows]
    last_scrape = conn.execute(
        "SELECT MAX(finished_at) AS t FROM scrape_log WHERE status='ok'"
    ).fetchone()
    payload = {
        "LANDINGS": list(LANDINGS),
        "TRIP_LENGTHS": list(TRIP_LENGTHS),
        "SPECIES": list(SPECIES),
        "TROPHY_SPECIES": list(TROPHY_SPECIES),
        "MOON_PHASES": list(MOON_PHASES),
        "BOATS": boats,
        "TRIPS": trips,
        "SCHEDULE": schedule,
        "META": {
            "lastScrape": last_scrape["t"] if last_scrape and last_scrape["t"] else None,
            "tripCount": len(trips),
            "scheduleCount": len(schedule),
            **conditions_snapshot(),  # sstF / moonPhase / moonIllum / sources
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Minified JSON — drops indentation and inter-token whitespace. Cuts the
    # on-disk size roughly in half versus indent=2, which matters because the
    # browser has to download + parse this file synchronously at page load.
    js = "// Auto-generated by src/export.py — do not edit.\n"
    js += "window.SD = " + json.dumps(payload, separators=(",", ":"), default=str) + ";\n"
    out_path.write_text(js, encoding="utf-8")
    return len(trips)
