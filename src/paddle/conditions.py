"""Race-day conditions for PAST races -> web/api/v1/paddle_race_conditions.json.

For each dated race with a course, the wind each leg actually had (Open-Meteo
historical archive, ERA5 reanalysis, hourly at each leg's midpoint) and the
NOAA tidal-current prediction for that day, scored with the same rule as the
forecast (score.py). Gives the one-line note shown on race and profile pages,
e.g. "NW 15 kt → downwind across the channel", because conditions change
finish times a lot.

Each race is fetched once and kept (results don't change); the archive runs a
few days behind, so races in the last 6 days wait for the next run.

Run:  python -m src.paddle.conditions [--redo RACE_ID]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..surf import forecast as SF
from . import course as CO
from .forecast import DEFAULT_PACE, DEFAULT_START, TZ, score_course, start_utc

log = logging.getLogger(__name__)

OUT = CO.ROOT / "web" / "api" / "v1" / "paddle_race_conditions.json"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
LAG_DAYS = 6


def archive_wind(points: list[dict], day: str) -> list[dict[int, tuple]]:
    """Per point {epoch hour: (kt, from deg, gust kt)} for one local day (UTC hours around it)."""
    d = date.fromisoformat(day)
    js = SF._get_json(ARCHIVE, {
        "latitude": ",".join(str(round(p["lat"], 4)) for p in points),
        "longitude": ",".join(str(round(p["lon"], 4)) for p in points),
        "start_date": d.isoformat(), "end_date": (d + timedelta(days=1)).isoformat(),
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kn", "timezone": "GMT",
    })
    js = js if isinstance(js, list) else [js]
    out = []
    for loc in js:
        h = loc.get("hourly", {})
        m = {}
        for t, s, dr, g in zip(h.get("time", []), h.get("wind_speed_10m", []),
                               h.get("wind_direction_10m", []), h.get("wind_gusts_10m", [])):
            if s is None or dr is None:
                continue
            ep = int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp())
            m[ep] = (float(s), float(dr), None if g is None else float(g))
        out.append(m)
    return out


def race_day(race: dict, dist: dict, legs: list[dict], defaults: dict) -> dict:
    day = race["date"]
    pace = float(dist.get("paceMph") or race.get("paceMph") or defaults.get("paceMph") or DEFAULT_PACE)
    hhmm = dist.get("startLocal") or race.get("startLocal")
    wind = archive_wind([{"lat": l["midLat"], "lon": l["midLon"]} for l in legs], day)
    currents = {}
    for st in {l["current"] for l in legs if l.get("current")}:
        try:
            currents[st] = SF.currents(datetime.fromisoformat(day) - timedelta(days=1), days=2, station=st)
        except Exception as e:  # noqa: BLE001
            log.warning("current %s %s failed: %s", st, day, e)
    r = score_course(legs, start_utc(day, hhmm or DEFAULT_START), pace, wind, [None] * len(legs), currents, None)
    return {"date": day, "start": hhmm or DEFAULT_START, "startAssumed": not hhmm, "paceMph": pace,
            "source": "ERA5 reanalysis via Open-Meteo; NOAA current predictions", **r}


def build(existing: dict | None = None, today: date | None = None, redo: set[str] | None = None,
          races_path: Path = CO.RACES, courses: Path = CO.COURSES) -> dict:
    today = today or datetime.now(TZ).date()
    doc = json.loads(races_path.read_text(encoding="utf-8"))
    defaults = doc.get("defaults") or {}
    out = {"races": dict((existing or {}).get("races") or {})}
    for race in doc.get("races", []):
        if not race.get("date") or date.fromisoformat(race["date"]) > today - timedelta(days=LAG_DAYS):
            continue
        for dist in race.get("distances", []):
            if not dist.get("courseId"):
                continue
            have = out["races"].get(race["id"], {}).get(dist["id"])
            if have and race["id"] not in (redo or set()) and have.get("date") == race["date"] \
                    and have.get("start") == (dist.get("startLocal") or race.get("startLocal") or DEFAULT_START):
                continue
            try:
                legs = CO.legs(CO.load(dist["courseId"], courses))
                out["races"].setdefault(race["id"], {})[dist["id"]] = race_day(race, dist, legs, defaults)
                log.info("conditions %s/%s: %s", race["id"], dist["id"], out["races"][race["id"]][dist["id"]]["reason"])
            except Exception as e:  # noqa: BLE001
                log.warning("conditions %s/%s failed: %s", race["id"], dist["id"], e)
    out["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--redo", action="append", default=[], metavar="RACE_ID")
    a = ap.parse_args(argv)
    try:
        existing = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        existing = None
    payload = build(existing, redo=set(a.redo))
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"paddle_race_conditions.json: {sum(len(v) for v in payload['races'].values())} race course(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
