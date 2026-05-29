"""Dump trips out of SQLite into web/data.js so the static front-end can render.

The output mirrors the shape the design's analytics.js expects (window.SD.TRIPS)
but extends it with yellowtail, dorado, trophyCount, and per-angler-per-day so
the trophy-focused dashboard works.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .analytics import (
    _OVERALL_BREAKS, _anomaly_boost, _breaks_from_weights, _load_weights, _score,
    build_forecast,
)
from .conditions import snapshot as conditions_snapshot
from .forecast import build_forecast_payload, calculate_consensus
from .sst import LOCATIONS as SST_LOCATIONS

LANDINGS_META = [
    {"name": "H&M Landing",            "lat": 32.7235, "lng": -117.2276, "googleRating": 4.3, "googleCount": 850,  "region": "san_diego"},
    {"name": "Fisherman's Landing",     "lat": 32.7250, "lng": -117.2265, "googleRating": 4.5, "googleCount": 650,  "region": "san_diego"},
    {"name": "Point Loma Sportfishing", "lat": 32.7241, "lng": -117.2273, "googleRating": 4.4, "googleCount": 420,  "region": "san_diego"},
    {"name": "Seaforth Sportfishing",   "lat": 32.7631, "lng": -117.2355, "googleRating": 4.7, "googleCount": 310,  "region": "san_diego"},
    {"name": "Oceanside Sea Center",    "lat": 33.2052, "lng": -117.3891, "googleRating": 4.6, "googleCount": 180,  "region": "san_diego"},
]

LANDINGS = (
    "H&M Landing",
    "Fisherman's Landing",
    "Point Loma Sportfishing",
    "Seaforth Sportfishing",
    "Oceanside Sea Center",
    # OC/LA
    "22nd Street Landing",
    "Long Beach Sportfishing",
    "Marina Del Rey Sportfishing",
    "Redondo Beach Sportfishing",
    "LA Waterfront Sportfishing",
    "Pierpoint Landing",
    "Newport Landing",
    "Davey's Locker",
    "Dana Wharf Sportfishing",
    # Ventura
    "Channel Islands Sportfishing",
    "Ventura Harbor Sportfishing",
)

TRIP_LENGTHS = (
    "Full Day", "Overnight",
    "1.5 Day", "2 Day", "2.5 Day", "3 Day", "4 Day", "5 Day",
    "6 Day", "7 Day", "Long Range",
)

SPECIES = ("Bluefin", "Yellowfin", "Yellowtail", "Dorado",
           "Skipjack", "Bigeye", "Albacore")

TROPHY_SPECIES = ("Bluefin", "Yellowfin", "Yellowtail", "Dorado")

MOON_PHASES = ("New", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
               "Full", "Waning Gibbous", "Last Quarter", "Waning Crescent")


_FULL_CATCH_CUTOFF: str = (date.today() - timedelta(days=30)).isoformat()


def _trip_to_js(row: sqlite3.Row, include_full_catch: bool = False) -> dict:
    d = row["date"]
    year, month, day = (int(x) for x in d.split("-"))
    t = {
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
        "region": row["region"] or "san_diego",
        "Rockfish":      row["rockfish"]       or 0,
        "Sheephead":     row["sheephead"]      or 0,
        "Calico Bass":   row["calico_bass"]    or 0,
        "Sand Bass":     row["sand_bass"]      or 0,
        "Halibut":       row["halibut"]        or 0,
        "Lingcod":       row["lingcod"]        or 0,
        "Whitefish":     row["whitefish"]      or 0,
        "Bonito":        row["bonito"]         or 0,
        "Barracuda":     row["barracuda"]      or 0,
        "White Sea Bass": row["white_sea_bass"] or 0,
        "source": row["source"] or "fish_count_page",
        "isPreliminary": bool(row["is_preliminary"]),
        "reportedAt": row["reported_at"] if "reported_at" in row.keys() else None,
        "rawText": (row["written_text"] or "")[:300] if "written_text" in row.keys() and row["written_text"] else None,
    }
    if include_full_catch or d >= _FULL_CATCH_CUTOFF:
        fc = row["full_catch"] if "full_catch" in row.keys() else None
        if fc:
            t["fullCatch"] = json.loads(fc)
    return t


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
        "tripStatus": row["trip_status"],
        "targetSpecies": row["target_species"],
        "whatsIncluded": row["whats_included"],
        "mealsIncluded": bool(row["meals_included"]) if row["meals_included"] is not None else False,
        "mealValue": row["meals_value"] or 0,
        "effectivePrice": row["effective_price"],
        "sourceId": row["source_id"],
        "bookable": bool((row["open_spots"] or 0) > 0) and (row["trip_status"] or "").lower() != "cancelled",
    }


def _today_summary(trips: list[dict]) -> dict | None:
    """Summarise the most recent date's catch for the Today's Catch banner.

    Uses the latest date present in the data rather than calendar today,
    because landing sites typically post yesterday's results — the widget
    would otherwise always be empty until sites catch up.

    Splits boats into:
      - boats: returned/final trips (is_preliminary=False) — count toward totals
      - stillFishing: preliminary/called-in trips (is_preliminary=True) — shown separately
    """
    if not trips:
        return None
    qualifying = [t for t in trips if t["tripLength"] in TRIP_LENGTHS]
    if not qualifying:
        return None
    today_str = max(t["date"] for t in qualifying)
    today = [t for t in qualifying if t["date"] == today_str]
    if not today:
        return None

    # Split into final (returned) and preliminary (still fishing).
    final_today = [t for t in today if not t.get("isPreliminary")]
    prelim_today = [t for t in today if t.get("isPreliminary")]

    # One row per boat for final: keep the trip with the highest trophyPerAnglerPerDay.
    by_boat: dict[str, dict] = {}
    for t in final_today:
        key = t["boat"]
        if key not in by_boat or (t["trophyPerAnglerPerDay"] or 0) > (by_boat[key]["trophyPerAnglerPerDay"] or 0):
            by_boat[key] = t
    boats = sorted(by_boat.values(), key=lambda t: t["trophyPerAnglerPerDay"] or 0, reverse=True)
    deduped = list(by_boat.values())

    # Preliminary trips: flat list, one entry per boat (dedup, keep first seen).
    seen_prelim: set[str] = set()
    still_fishing: list[dict] = []
    for t in prelim_today:
        key = t["boat"].lower()
        if key in seen_prelim:
            continue
        seen_prelim.add(key)
        catch: dict[str, int] = {}
        for sp in ("Bluefin", "Yellowfin", "Yellowtail", "Dorado", "Skipjack", "Bigeye", "Albacore"):
            v = t.get(sp, 0) or 0
            if v > 0:
                catch[sp] = v
        still_fishing.append({
            "boat": t["boat"],
            "landing": t["landing"],
            "tripLength": t["tripLength"],
            "anglers": t["anglers"],
            "catch": catch,
            "reportedAt": t.get("reportedAt"),
            "rawText": t.get("rawText"),
            "source": t.get("source"),
        })

    return {
        "date": today_str,
        "trophyCount": sum(t["trophyCount"] for t in deduped),
        "anglers": sum(t["anglers"] for t in deduped),
        "boatCount": len(deduped),
        "boats": [
            {
                "boat": t["boat"],
                "landing": t["landing"],
                "tripLength": t["tripLength"],
                "anglers": t["anglers"],
                "Bluefin": t["Bluefin"],
                "Yellowfin": t["Yellowfin"],
                "Yellowtail": t["Yellowtail"],
                "Dorado": t["Dorado"],
                "trophyPerAnglerPerDay": t["trophyPerAnglerPerDay"],
                **({"fullCatch": t["fullCatch"]} if "fullCatch" in t else {}),
            }
            for t in boats
        ],
        "stillFishing": still_fishing,
        "Bluefin":    sum(t["Bluefin"]    for t in deduped),
        "Yellowfin":  sum(t["Yellowfin"]  for t in deduped),
        "Yellowtail": sum(t["Yellowtail"] for t in deduped),
        "Dorado":     sum(t["Dorado"]     for t in deduped),
    }


def _sst_payload(conn: sqlite3.Connection) -> dict:
    """Build window.SD.SST: forecast + 90-day history per location."""
    history_rows = conn.execute(
        """SELECT date, location, sst_fahrenheit, anomaly
           FROM ocean_temps
           WHERE date >= date('now', '-90 days')
           ORDER BY date, location"""
    ).fetchall()
    history = [
        {
            "date": r["date"],
            "location": r["location"],
            "sst": r["sst_fahrenheit"],
            "anomaly": r["anomaly"],
        }
        for r in history_rows
    ]
    return {
        "forecast": build_forecast(conn),
        "history": history,
        "locations": list(SST_LOCATIONS.keys()),
    }


def _recent_predictions(conn: sqlite3.Connection, days: int = 14) -> list[dict]:
    """Last `days` days of model-predicted score vs actual fishing quality."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    all_tpa = [r[0] for r in conn.execute(
        "SELECT AVG(trophy_per_angler_per_day) FROM trips"
        " WHERE is_half_day=0 AND anglers>=5 GROUP BY date HAVING COUNT(*)>=2"
    ).fetchall() if r[0] is not None]
    if not all_tpa:
        return []
    w = _load_weights()
    overall_breaks = _breaks_from_weights(w, "overall_breaks", _OVERALL_BREAKS)

    def _pct_rating(tpa: float) -> float:
        rank = sum(1 for v in all_tpa if v <= tpa) / len(all_tpa)
        return round(max(1.0, min(10.0, 1.0 + rank * 9.0)), 1)

    try:
        rows = conn.execute(
            """SELECT hc.date, hc.sst_offshore, hc.sst_anomaly,
                      AVG(t.trophy_per_angler_per_day) AS avg_tpa,
                      COUNT(DISTINCT t.id) AS n_boats
               FROM historical_conditions hc
               JOIN trips t ON t.date = hc.date
               WHERE hc.date >= ? AND t.is_half_day=0 AND t.anglers>=5
               GROUP BY hc.date
               HAVING COUNT(DISTINCT t.id) >= 2
               ORDER BY hc.date DESC LIMIT ?""",
            (cutoff, days),
        ).fetchall()
    except Exception:
        return []

    result = []
    for r in rows:
        if r["sst_offshore"] is None:
            continue
        boost = _anomaly_boost(r["sst_anomaly"])
        predicted = round(min(10.0, max(1.0, _score(r["sst_offshore"], overall_breaks) + boost)), 1)
        actual_rating = _pct_rating(r["avg_tpa"])
        result.append({
            "date": r["date"],
            "predicted": predicted,
            "actualTpa": round(r["avg_tpa"], 3),
            "actualRating": actual_rating,
            "error": round(abs(predicted - actual_rating), 2),
            "nBoats": r["n_boats"],
        })
    return result


def _consensus_accuracy_correlation(conn: sqlite3.Connection) -> list[dict]:
    """Retroactively compute offshore consensus for logged accuracy days and group by label."""
    try:
        from .forecast import _wind_direction_score, _sst_gradient_score
        from .chlorophyll import score_chlorophyll

        rows = conn.execute(
            """SELECT al.date, al.error, al.correct_direction,
                      hc.sst_offshore,
                      hc.wind_is_offshore, hc.wind_is_upwelling,
                      hc.sst_gradient,
                      hc.chlorophyll_nearshore, hc.chlorophyll_offshore
               FROM forecast_accuracy_log al
               LEFT JOIN historical_conditions hc ON hc.date = al.date
               WHERE al.error IS NOT NULL AND hc.sst_offshore IS NOT NULL
               ORDER BY al.date DESC LIMIT 365"""
        ).fetchall()
        if not rows:
            return []

        bw = _load_weights()
        ob = _breaks_from_weights(bw, "overall_breaks", _OVERALL_BREAKS)

        by_label: dict[str, list] = {"Strong": [], "Moderate": [], "Mixed": [], "Conflicted": []}
        for r in rows:
            fs = {
                "sst":          round(_score(r["sst_offshore"], ob), 1),
                "wind_dir":     round(_wind_direction_score(r["wind_is_offshore"], r["wind_is_upwelling"], "offshore"), 1),
                "sst_gradient": round(_sst_gradient_score(r["sst_gradient"], "offshore"), 1),
                "chlorophyll":  round(score_chlorophyll(r["chlorophyll_nearshore"], r["chlorophyll_offshore"], "offshore"), 1),
            }
            lbl = calculate_consensus(fs, "offshore")["consensus_label"]
            if lbl in by_label:
                by_label[lbl].append({"error": r["error"], "dir": r["correct_direction"]})

        result = []
        for lbl in ["Strong", "Moderate", "Mixed", "Conflicted"]:
            entries = by_label[lbl]
            if not entries:
                continue
            avg_err = sum(e["error"] for e in entries) / len(entries)
            dir_acc = sum(e["dir"] for e in entries) / len(entries) * 100
            result.append({
                "label":        lbl,
                "n":            len(entries),
                "avg_error":    round(avg_err, 2),
                "direction_acc": round(dir_acc, 1),
            })
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("consensus_correlation failed: %s", e)
        return []


def _reddit_payload(conn: sqlite3.Connection) -> dict:
    """Recent Reddit posts sorted by date, top 20."""
    from datetime import datetime
    rows = conn.execute(
        """SELECT id, title, url, subreddit, score, num_comments,
                  created_utc, author, snippet, boat_mentioned
           FROM reddit_reports
           ORDER BY created_utc DESC LIMIT 20"""
    ).fetchall()
    reports = []
    for r in rows:
        try:
            d = datetime.utcfromtimestamp(r['created_utc']).strftime('%Y-%m-%d')
        except Exception:
            d = None
        reports.append({
            'id':            r['id'],
            'title':         r['title'],
            'url':           r['url'],
            'subreddit':     r['subreddit'],
            'score':         r['score'],
            'num_comments':  r['num_comments'],
            'date':          d,
            'author':        r['author'],
            'snippet':       r['snippet'],
            'boat_mentioned': r['boat_mentioned'],
        })
    last_row = conn.execute(
        "SELECT MAX(fetched_date) AS d FROM reddit_reports"
    ).fetchone()
    return {
        'reports':      reports,
        'last_updated': last_row['d'] if last_row else None,
    }


def _reviews_payload(conn: sqlite3.Connection) -> dict:
    try:
        from .reviews import reviews_for_export
        return reviews_for_export(conn)
    except Exception:
        return {'byBoat': {}, 'summary': {}}


def _reviews_admin_stats(conn: sqlite3.Connection) -> dict:
    try:
        from .reviews import reviews_admin_stats
        return reviews_admin_stats(conn)
    except Exception:
        return {'total': 0, 'pending': 0, 'approved': 0, 'rejected': 0, 'pendingReviews': []}


def _community_payload(conn: sqlite3.Connection) -> dict:
    """Build window.SD.COMMUNITY from analyzed Reddit insights."""
    try:
        from .reddit_insights import community_payload
        return community_payload(conn)
    except Exception:
        return {
            'biteReport': {'updated': None, 'species': []},
            'hotspots': [], 'weeklySummary': None,
            'recentPosts': [], 'boatMentions': {},
            'stats': {'totalAnalyzed': 0, 'weekAnalyzed': 0,
                      'topSpeciesWeek': [], 'topLocsWeek': []},
        }


def _boat_profiles_payload(conn: sqlite3.Connection) -> dict:
    """Build window.SD.BOAT_PROFILES: keyed by boat name for O(1) lookup."""
    try:
        rows = conn.execute(
            "SELECT boat, landing, photo_url, description, captains,"
            "       year_built, length_ft, passenger_capacity, source_url"
            " FROM boat_profiles"
        ).fetchall()
    except Exception:
        return {}
    result = {}
    for r in rows:
        captains = []
        if r["captains"]:
            try:
                captains = json.loads(r["captains"])
            except Exception:
                captains = [r["captains"]]
        result[r["boat"]] = {
            "landing":           r["landing"],
            "photoUrl":          r["photo_url"],
            "description":       r["description"],
            "captains":          captains,
            "yearBuilt":         r["year_built"],
            "lengthFt":          r["length_ft"],
            "passengerCapacity": r["passenger_capacity"],
            "sourceUrl":         r["source_url"],
        }
    return result


def _admin_payload(conn: sqlite3.Connection) -> dict:
    """Build window.SD.ADMIN: data for the internal admin dashboard."""
    # Scrape log — last 10 runs per source
    log_rows = conn.execute(
        "SELECT started_at, landing, trips_seen, trips_kept, status, error"
        " FROM scrape_log ORDER BY started_at DESC LIMIT 200"
    ).fetchall()
    by_source: dict = {}
    for r in log_rows:
        src = r["landing"]
        if src not in by_source:
            by_source[src] = []
        if len(by_source[src]) < 10:
            by_source[src].append({
                "at": r["started_at"], "seen": r["trips_seen"],
                "kept": r["trips_kept"], "status": r["status"],
                "error": r["error"],
            })

    # SST — latest date + value per location
    sst_recent = conn.execute(
        "SELECT location, MAX(date) AS last_date, sst_fahrenheit, anomaly"
        " FROM ocean_temps GROUP BY location"
    ).fetchall()
    sst_log = [{"location": r["location"], "date": r["last_date"],
                 "sstF": r["sst_fahrenheit"], "anomaly": r["anomaly"]}
               for r in sst_recent]

    # DB stats
    ts = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN is_half_day=1 THEN 1 ELSE 0 END) AS half_day,
                  MIN(date) AS earliest, MAX(date) AS latest,
                  SUM(anglers) AS total_anglers,
                  SUM(trophy_count) AS total_tuna
           FROM trips"""
    ).fetchone()
    by_landing = [{"landing": r["landing"], "count": r["n"]} for r in conn.execute(
        "SELECT landing, COUNT(*) AS n FROM trips WHERE is_half_day=0"
        " GROUP BY landing ORDER BY n DESC"
    ).fetchall()]
    by_year = [{"year": r["yr"], "count": r["n"]} for r in conn.execute(
        "SELECT strftime('%Y',date) AS yr, COUNT(*) AS n"
        " FROM trips WHERE is_half_day=0 GROUP BY yr ORDER BY yr"
    ).fetchall()]
    unknowns = [{"species": r["species_name"], "total": r["n"], "lastSeen": r["last_seen"]}
                for r in conn.execute(
                    "SELECT species_name, SUM(count) AS n, MAX(date) AS last_seen"
                    " FROM unknown_species GROUP BY species_name ORDER BY n DESC LIMIT 50"
                ).fetchall()]
    new_species_week = conn.execute(
        "SELECT COUNT(DISTINCT species_name) FROM unknown_species"
        " WHERE date >= date('now','-7 days')"
        "   AND species_name NOT IN ("
        "     SELECT DISTINCT species_name FROM unknown_species"
        "     WHERE date < date('now','-7 days'))"
    ).fetchone()[0]

    # Backtest results — latest run + history for weight changelog
    backtest = None
    backtest_history: list = []
    try:
        rows = conn.execute(
            "SELECT * FROM backtest_results ORDER BY run_date DESC LIMIT 12"
        ).fetchall()
        for i, bt in enumerate(rows):
            entry = dict(bt)
            for field in ("by_month", "weights", "by_species"):
                if entry.get(field):
                    try:
                        entry[field] = json.loads(entry[field])
                    except Exception:
                        pass
            if i == 0:
                backtest = entry
            backtest_history.append(entry)
    except Exception:
        pass

    # Current weights (scalar keys only — skip calibrated break arrays)
    weights_path = Path(__file__).resolve().parents[1] / "backtest_weights.json"
    weights: dict = {}
    if weights_path.exists():
        try:
            raw = json.loads(weights_path.read_text())
            weights = {k: v for k, v in raw.items() if not k.endswith("_breaks")}
        except Exception:
            pass

    return {
        "scrapeLog":         by_source,
        "sstLog":            sst_log,
        "dbStats": {
            "totalTrips":        ts["total"],
            "halfDayTrips":      ts["half_day"],
            "earliestDate":      ts["earliest"],
            "latestDate":        ts["latest"],
            "totalAnglers":      ts["total_anglers"],
            "totalTuna":         ts["total_tuna"],
            "byLanding":         by_landing,
            "byYear":            by_year,
            "unknownSpecies":    unknowns,
            "newSpeciesThisWeek": new_species_week,
        },
        "backtestResults":      backtest,
        "backtestHistory":      backtest_history,
        "recentPredictions":    _recent_predictions(conn),
        "weights":              weights,
        "consensusCorrelation": _consensus_accuracy_correlation(conn),
        "reviews":              _reviews_admin_stats(conn),
        "forecastScores":       _forecast_scores_history(conn),
    }


def _forecast_scores_history(conn: sqlite3.Connection) -> list:
    """Last 30 days of ensemble model scores per segment for admin monitoring."""
    try:
        rows = conn.execute(
            """SELECT date, segment, model_a, model_b, model_c, ensemble, std_dev, confidence, n_days_b
               FROM forecast_scores
               ORDER BY date DESC, segment
               LIMIT 60"""
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _scrape_status_payload(conn: sqlite3.Connection) -> dict:
    """Build per-landing freshness from the last 24h of scrape_log."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    rows = conn.execute("""
        SELECT
            landing,
            MAX(CASE WHEN status='ok' THEN started_at END) AS last_success,
            MAX(started_at)                                  AS last_attempt,
            MAX(CASE WHEN status='ok' THEN trips_kept END)   AS trips_today
        FROM scrape_log
        WHERE started_at >= datetime('now', '-24 hours')
        GROUP BY landing
    """).fetchall()

    landings: dict = {}
    last_full: str | None = None

    for row in rows:
        ls = row["last_success"]
        status = "failed"
        if ls:
            try:
                dt = datetime.fromisoformat(ls)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_min = (now - dt).total_seconds() / 60
                status = "fresh" if age_min < 90 else "stale" if age_min < 240 else "failed"
            except Exception:
                pass
        landings[row["landing"]] = {
            "lastSuccess": ls,
            "lastAttempt": row["last_attempt"],
            "status": status,
            "tripsToday": row["trips_today"] or 0,
        }
        if ls and (last_full is None or ls > last_full):
            last_full = ls

    return {"lastFullScrape": last_full, "landings": landings}


def export(conn: sqlite3.Connection, out_path: Path, weather_forecast: list | None = None) -> int:
    """Write data.js. Returns trip count written.

    weather_forecast: optional output of weather.fetch_marine_forecast() — passed
    through to build_forecast_payload() for wind/swell scoring in the 7-day strip.
    """
    rows = conn.execute(
        "SELECT * FROM trips WHERE is_half_day = 0 ORDER BY date, id"
    ).fetchall()
    trips = [_trip_to_js(r) for r in rows]
    boats = _boats_from_trips(trips)
    schedule_rows = conn.execute(
        "SELECT * FROM scheduled_trips ORDER BY departure_at, landing, boat"
    ).fetchall()
    schedule = [_scheduled_to_js(r) for r in schedule_rows]
    last_scrape = conn.execute(
        "SELECT MAX(finished_at) AS t FROM scrape_log WHERE status='ok'"
    ).fetchone()

    # Build forecast payload — non-fatal if something goes wrong
    forecast_payload: dict | None = None
    try:
        forecast_payload = build_forecast_payload(conn, weather_forecast)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Forecast payload failed: %s", e)

    payload = {
        "LANDINGS": list(LANDINGS),
        "LANDINGS_META": LANDINGS_META,
        "TRIP_LENGTHS": list(TRIP_LENGTHS),
        "SPECIES": list(SPECIES),
        "TROPHY_SPECIES": list(TROPHY_SPECIES),
        "MOON_PHASES": list(MOON_PHASES),
        "BOATS": boats,
        "TRIPS": trips,
        "TODAY": _today_summary(trips),
        "SCHEDULE": schedule,
        "SST": _sst_payload(conn),
        "FORECAST": forecast_payload,
        "REDDIT": _reddit_payload(conn),
        "REVIEWS": _reviews_payload(conn),
        "COMMUNITY": _community_payload(conn),
        "BOAT_PROFILES": _boat_profiles_payload(conn),
        "ADMIN": _admin_payload(conn),
        "SCRAPE_STATUS": _scrape_status_payload(conn),
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

    # Regenerate sitemap.xml alongside data.js.
    try:
        _write_sitemap(out_path, boats)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Sitemap generation failed: %s", e)

    return len(trips)


def _write_sitemap(data_js_path: Path, boats: list[dict]) -> None:
    """Write sitemap.xml to the same directory as data.js."""
    from urllib.parse import quote
    base  = "https://thetunatracker.com"
    today = date.today().isoformat()
    sd_landings = {
        "H&M Landing", "Fisherman's Landing", "Seaforth Sportfishing",
        "Point Loma Sportfishing", "Oceanside Sea Center",
    }
    entries = [
        (base + "/",                       "1.0", "daily"),
        (base + "/#sd/today",              "0.9", "daily"),
        (base + "/#sd/forecast",           "0.7", "weekly"),
        (base + "/#sd/boats",              "0.8", "weekly"),
        (base + "/#sd/analytics/overview", "0.7", "weekly"),
        (base + "/#sd/tripplanner",        "0.6", "daily"),
    ]
    seen: set[str] = set()
    for b in boats:
        name    = b.get("name") or b.get("boat", "")
        landing = b.get("landing", "")
        if not name or name in seen or landing not in sd_landings:
            continue
        seen.add(name)
        entries.append((f"{base}/#sd/boat/{quote(name)}", "0.5", "weekly"))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, priority, freq in entries:
        lines += [
            "  <url>",
            f"    <loc>{url}</loc>",
            f"    <lastmod>{today}</lastmod>",
            f"    <changefreq>{freq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ]
    lines.append("</urlset>")
    (data_js_path.parent / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
