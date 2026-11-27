"""Presentation extras for surf.json (additive; no model logic here).

Called once from forecast.build() via enrich(). Adds fields the page shows
next to the model forecast:
  breaks[].tideWindow / swellWindow   the break's config preferences
  breaks[].hours[].energyKj           wave energy, Surf-forecast style
  tides.hourly                        [[iso, ft]] NOAA hourly predictions
  sun                                 first light / sunrise / sunset / last light
  waterTemp                           CDIP buoy sea-surface temperature
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import cdip as C
from .breaks import BY_ID

log = logging.getLogger(__name__)
LA = ZoneInfo("America/Los_Angeles")
SUN_LAT, SUN_LON = 32.867, -117.257          # Scripps Pier; ±2 min across the county
SST_STATIONS = ("201", "220")                # Scripps Nearshore, Mission Bay


def energy_kj(hs_m: float | None, tp_s: float | None) -> int | None:
    """Energy per wavelength per metre of crest, rho·g²·H²·T²/(64π) ≈ 0.49·H²·T² kJ.
    The same scale as Surf-forecast.com (≈100 kJ small, 200–1000 kJ punchy)."""
    if not hs_m or not tp_s:
        return None
    return round(1025 * 9.81 ** 2 * hs_m ** 2 * tp_s ** 2 / (64 * math.pi) / 1000)


def _sun_event(d: date, zenith: float, rising: bool, lat=SUN_LAT, lon=SUN_LON) -> datetime | None:
    """NOAA general solar position equations; UTC time when the sun's centre
    crosses `zenith` degrees (90.833 sunrise/set, 96 civil twilight)."""
    def at(hour_utc: float):
        g = 2 * math.pi / 365 * (d.timetuple().tm_yday - 1 + (hour_utc - 12) / 24)
        eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                        - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
        dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
               + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
        la = math.radians(lat)
        c = (math.cos(math.radians(zenith)) / (math.cos(la) * math.cos(dec)) - math.tan(la) * math.tan(dec))
        if abs(c) > 1:
            return None
        ha = math.degrees(math.acos(c))
        mins = 720 - 4 * (lon + (ha if rising else -ha)) - eqt
        return mins / 60
    h = at(12.0)
    if h is None:
        return None
    h = at(h) or h                            # one refinement at the event time
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(hours=h)


def sun_days(start: datetime, days: int = 8) -> list[dict]:
    out = []
    d0 = start.astimezone(LA).date()
    for i in range(days):
        d = d0 + timedelta(days=i)
        ev = {"firstLight": _sun_event(d, 96, True), "sunrise": _sun_event(d, 90.833, True),
              "sunset": _sun_event(d, 90.833, False), "lastLight": _sun_event(d, 96, False)}
        out.append({"date": d.isoformat(),
                    **{k: v.isoformat(timespec="minutes") for k, v in ev.items() if v}})
    return out


def water_temp(now: datetime) -> dict | None:
    for st in SST_STATIONS:
        try:
            d = C.series(C.buoy_urls(st)[-1], ["sstSeaSurfaceTemperature", "sstFlagPrimary"],
                         since=now - timedelta(hours=6), time_var="sstTime", max_age_s=1800)
        except Exception as e:  # noqa: BLE001
            log.info("SST %s failed: %s", st, e)
            continue
        ok = [(t, c) for t, c, f in zip(d["sstTime"], d["sstSeaSurfaceTemperature"], d["sstFlagPrimary"])
              if f == 1 and 5 < c < 35]
        if ok:
            t, c = ok[-1]
            return {"station": st, "t": C.to_iso(t), "c": round(c, 1), "f": round(c * 9 / 5 + 32)}
    return None


def enrich(payload: dict, tide_hourly: dict[int, float], now: datetime) -> dict:
    for br in payload.get("breaks", []):
        cfg = BY_ID.get(br["id"], {})
        if "tide" in cfg:
            br["tideWindow"] = list(cfg["tide"])
        if "swell" in cfg:
            br["swellWindow"] = list(cfg["swell"])
        for h in br.get("hours", []):
            e = energy_kj(h.get("hsM"), h.get("tpS"))
            if e is not None:
                h["energyKj"] = e
    payload.setdefault("tides", {})["hourly"] = [[C.to_iso(t), round(v, 2)]
                                                for t, v in sorted(tide_hourly.items())]
    payload["sun"] = sun_days(now - timedelta(days=1))
    try:
        payload["waterTemp"] = water_temp(now)
    except Exception as e:  # noqa: BLE001
        log.warning("water temp failed: %s", e)
        payload["waterTemp"] = None
    return payload
