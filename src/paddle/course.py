"""Race courses: GeoJSON files in web/api/v1/paddle_courses/<id>.geojson.

One FeatureCollection per course (race + distance):
  * properties: id, name, status ("draft — confirm" until the owner OKs it),
    summary, sources
  * one LineString feature (properties.kind = "course"): start → marks → finish
  * one Point feature per LineString vertex (properties.kind = "waypoint"),
    in the same order, with i (vertex index), name, role (start|mark|via|finish)
    and, for every vertex but the finish, the leg that starts there:
      leg            short name, written to read after a wind word
                     ("on the ocean leg", "into the bay")
      water          ocean | channel | bay   (swell is scored on ocean legs only)
      current        NOAA current station id (e.g. PCT0031), optional
      currentFactor  share of that station's speed felt on the leg (default 1)

A leg is the segment between two consecutive vertices.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COURSES = ROOT / "web" / "api" / "v1" / "paddle_courses"
RACES = ROOT / "web" / "api" / "v1" / "paddle_races.json"

EARTH_MI = 3958.8
ROLES = {"start", "mark", "via", "finish"}
WATERS = {"ocean", "channel", "bay"}


def distance_mi(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MI * math.asin(math.sqrt(h))


def bearing_deg(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Initial true bearing from a to b, 0–360 (direction of travel)."""
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def validate(fc: dict) -> list[str]:
    """Problems with a course file ([] when it is fine)."""
    errs = []
    props = fc.get("properties") or {}
    for k in ("id", "name", "status"):
        if not props.get(k):
            errs.append(f"missing properties.{k}")
    lines = [f for f in fc.get("features", []) if (f.get("properties") or {}).get("kind") == "course"]
    pts = [f for f in fc.get("features", []) if (f.get("properties") or {}).get("kind") == "waypoint"]
    if len(lines) != 1 or lines[0]["geometry"]["type"] != "LineString":
        return errs + ["need exactly one LineString feature with kind=course"]
    coords = lines[0]["geometry"]["coordinates"]
    if len(coords) < 2:
        errs.append("course needs at least two points")
    if len(pts) != len(coords):
        errs.append(f"{len(pts)} waypoints for {len(coords)} course points")
    for n, f in enumerate(sorted(pts, key=lambda f: f["properties"].get("i", -1))):
        p = f["properties"]
        if p.get("i") != n:
            errs.append(f"waypoint index {p.get('i')} out of order (expected {n})")
            continue
        if n < len(coords) and [round(c, 6) for c in f["geometry"]["coordinates"]] != [round(c, 6) for c in coords[n]]:
            errs.append(f"waypoint {n} ({p.get('name')}) is not on the course line")
        if not p.get("name"):
            errs.append(f"waypoint {n} has no name")
        if p.get("role") not in ROLES:
            errs.append(f"waypoint {n} role {p.get('role')!r}")
        last = n == len(coords) - 1
        if last and p.get("role") != "finish":
            errs.append("last waypoint must be the finish")
        if n == 0 and p.get("role") != "start":
            errs.append("first waypoint must be the start")
        if not last:
            if not p.get("leg"):
                errs.append(f"waypoint {n} has no leg name")
            if p.get("water") not in WATERS:
                errs.append(f"waypoint {n} water {p.get('water')!r}")
    for lon, lat in coords:
        if not (32.0 < lat < 34.5 and -119.5 < lon < -116.5):
            errs.append(f"point {lat},{lon} is outside Southern California")
    return errs


def load(course_id: str, folder: Path = COURSES) -> dict:
    fc = json.loads((folder / f"{course_id}.geojson").read_text(encoding="utf-8"))
    errs = validate(fc)
    if errs:
        raise ValueError(f"course {course_id}: " + "; ".join(errs))
    return fc


def legs(fc: dict) -> list[dict]:
    """The course as legs, in race order, with bearing, length and position."""
    pts = sorted((f for f in fc["features"] if f["properties"].get("kind") == "waypoint"),
                 key=lambda f: f["properties"]["i"])
    out, run = [], 0.0
    for a, b in zip(pts, pts[1:]):
        (alon, alat), (blon, blat) = a["geometry"]["coordinates"], b["geometry"]["coordinates"]
        p = a["properties"]
        mi = distance_mi(alat, alon, blat, blon)
        out.append({
            "i": p["i"], "leg": p["leg"], "from": p["name"], "to": b["properties"]["name"],
            "water": p["water"], "current": p.get("current"),
            "currentFactor": float(p.get("currentFactor", 1.0)),
            "bearing": round(bearing_deg(alat, alon, blat, blon)),
            "miles": round(mi, 2), "startMi": round(run, 2),
            "midLat": (alat + blat) / 2, "midLon": (alon + blon) / 2,
        })
        run += mi
    return out


def total_mi(fc: dict) -> float:
    return round(sum(l["miles"] for l in legs(fc)), 1)
