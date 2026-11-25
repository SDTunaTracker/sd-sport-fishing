"""
Forum spot reports: every place a BloodyDecks post says fish, paddies, kelp
or the fleet were, geocoded and dated.

Inputs (all already in data/paddies.db):
  * report_mentions   — paddy-forum mentions (extract.py): bank ids, GPS and
                        "N miles off X" positions, bite outcome, species, temp
  * forum_locations   — party-boat trip reports (boat_reports.py): named
                        places, coordinates, offsets, fleet / kelp / paddy
  * forum_boat_reports.spots — older trip-report rows extracted before
                        forum_locations existed (names only)

Outputs:
  * forum_spot_reports (table, rebuilt every run from the append-only inputs
    above): one row per place mention with trip date, knowable-at time
    (fetched_at), species, catch quality, source link, the research-only exact
    point and the PUBLIC point + precision radius.
  * web/api/v1/forum_spots.geojson — "Recent forum reports by spot": one
    feature per spot for the last 14 days (7-day counts too).
  * --research-csv — the dated series for forecast R&D (not for production).

Positions: the owner decided (2026-11-25) that coordinates posted publicly on
the forum are fair to show as posted. Every point carries a precision radius
so the map and forecast know how far to trust it:
  * coordinates printed in the post   -> exact, ~0.1 nm
  * "N miles <dir> of X" estimates    -> computed point, max(1 nm, N/4)
  * a named bank / island / area      -> its centre, the spot's radius
No quotes or usernames are published; every point links to its thread.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import coords as coords_mod

log = logging.getLogger("paddies.spots")

ROOT = Path(__file__).resolve().parents[2]
GAZETTEER_PATH = ROOT / "data" / "banks.geojson"
PLACES_PATH = ROOT / "data" / "forum_places.json"
OUT_PATH = ROOT / "web" / "api" / "v1" / "forum_spots.geojson"
STATE_PATH = ROOT / "data" / "paddies_ingest_state.json"

WINDOW_DAYS = 14
SHORT_WINDOW_DAYS = 7
COORD_PRECISION_NM = 0.1   # coordinates printed in a post
OFFSET_MIN_PRECISION_NM = 1.0
OFFSET_PRECISION_FRACTION = 0.25   # "12 miles SW of X" is good to about 3 nm
SNAP_SLACK_NM = 1.0        # a posted position this close to a spot's radius is named after it
# Fixed species vocabulary for the public layer (matches the site's species colours).
PUBLIC_SPECIES = ("yellowfin", "bluefin", "yellowtail", "dorado", "skipjack", "bigeye", "albacore")
MAX_SOURCES_PER_SPOT = 5

OUTCOME_TO_QUALITY = {"wide_open": "wide_open", "steady": "good",
                      "scratchy": "slow", "skunk": "none"}
QUALITY_ORDER = ["wide_open", "good", "fair", "slow", "none"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS forum_spot_reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    origin           TEXT NOT NULL,     -- paddy_mention | trip_location | trip_spot
    origin_id        INTEGER,
    source_id        TEXT NOT NULL,
    feed_id          TEXT,
    url              TEXT,
    title            TEXT,
    boat             TEXT,
    trip_date        TEXT,
    published_at     TEXT,
    fetched_at       TEXT,              -- knowable-at time
    report_date      TEXT NOT NULL,     -- trip_date, else published date
    kind             TEXT,              -- bank|island|kelp|paddy|fleet|coords|offset|area|bite|conditions
    name_raw         TEXT,
    place_id         TEXT,
    place_name       TEXT,
    geocode          TEXT NOT NULL,     -- gazetteer | places | coords | offset | unresolved
    geocode_confidence REAL,
    lat_exact        REAL,              -- posted or computed position (NULL for a named spot)
    lon_exact        REAL,
    lat_pub          REAL,              -- published point (exact when posted, else spot centre / estimate)
    lon_pub          REAL,
    precision_nm     REAL,
    species          TEXT,              -- JSON [species]
    quality          TEXT,              -- wide_open | good | fair | slow | none
    water_temp_f     REAL
);
CREATE INDEX IF NOT EXISTS idx_fsr_date ON forum_spot_reports(report_date);
"""


# ------------------------------------------------------------------ gazetteer

def norm(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\bpt\b\.?", "point", s)
    s = re.sub(r"\bst\b\.?", "san", s) if re.search(r"\bst\.? martin\b", s) else s
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _variants(n: str) -> list[str]:
    out = [n]
    for pat in (r"^the ", r" spot$", r" area$", r" bank$", r" island$", r" islands$"):
        out += [re.sub(pat, "", v).strip() for v in list(out)]
    return [v for v in dict.fromkeys(out) if v]


class Gazetteer:
    def __init__(self, gaz_path: Path = GAZETTEER_PATH, places_path: Path = PLACES_PATH):
        self.places: dict[str, dict] = {}
        self.index: dict[str, str] = {}
        feats = json.loads(Path(gaz_path).read_text(encoding="utf-8"))["features"]
        for f in feats:
            p = f["properties"]
            if p.get("kind") == "admin":
                continue
            lon, lat = f["geometry"]["coordinates"]
            self.places[p["id"]] = {"id": p["id"], "name": p["name"], "lat": lat, "lon": lon,
                                    "radius_nm": float(p.get("radius_nm") or 1), "confidence": 0.9,
                                    "source": "gazetteer"}
            for a in [p["name"], p.get("source_name"), *(p.get("aliases") or [])]:
                if a:
                    self.index.setdefault(norm(a), p["id"])
        extra = json.loads(Path(places_path).read_text(encoding="utf-8")) if Path(places_path).exists() else {}
        for pl in extra.get("places", []):
            self.places[pl["id"]] = {"id": pl["id"], "name": pl["name"], "lat": pl["lat"], "lon": pl["lon"],
                                     "radius_nm": float(pl.get("radius_nm") or 5),
                                     "confidence": float(pl.get("confidence") or 0.7), "source": "places"}
            for a in [pl["name"], *(pl.get("aliases") or [])]:
                self.index.setdefault(norm(a), pl["id"])
        # forum spellings that override a same-named SWYC entry (e.g. "Avalon" the town)
        for alias, pid in (extra.get("aliases_to_bank") or {}).items():
            if pid in self.places:
                self.index[norm(alias)] = pid

    def lookup(self, name: str | None) -> dict | None:
        if not name:
            return None
        for v in _variants(norm(name)):
            pid = self.index.get(v)
            if pid:
                return self.places[pid]
        return None

    def get(self, pid: str | None) -> dict | None:
        return self.places.get(pid) if pid else None

    def snap(self, lat: float, lon: float) -> dict | None:
        """The smallest known spot whose radius (plus slack) contains the point."""
        best = None
        for p in self.places.values():
            d = coords_mod.haversine_nm(lat, lon, p["lat"], p["lon"])
            if d <= p["radius_nm"] + SNAP_SLACK_NM and (best is None or p["radius_nm"] < best["radius_nm"]):
                best = p
        return best

    def nearest(self, lat: float, lon: float) -> tuple[dict | None, float]:
        best, bd = None, math.inf
        for p in self.places.values():
            d = coords_mod.haversine_nm(lat, lon, p["lat"], p["lon"])
            if d < bd:
                best, bd = p, d
        return best, bd


def offset_precision(distance_nm: float | None) -> float:
    return max(OFFSET_MIN_PRECISION_NM, (distance_nm or 0) * OFFSET_PRECISION_FRACTION)


# ------------------------------------------------------------------ build

def _date(s: str | None) -> str | None:
    return (s or "")[:10] or None


def _row(**kw) -> dict:
    base = dict(origin=None, origin_id=None, source_id=None, feed_id=None, url=None, title=None,
                boat=None, trip_date=None, published_at=None, fetched_at=None, report_date=None,
                kind=None, name_raw=None, place_id=None, place_name=None, geocode="unresolved",
                geocode_confidence=None, lat_exact=None, lon_exact=None, lat_pub=None, lon_pub=None,
                precision_nm=None, species="[]", quality=None, water_temp_f=None)
    base.update(kw)
    base["report_date"] = base["trip_date"] or _date(base["published_at"])
    return base


def _place_fields(place: dict | None, how: str) -> dict:
    if not place:
        return {}
    return {"place_id": place["id"], "place_name": place["name"], "geocode": how,
            "geocode_confidence": place["confidence"], "lat_pub": place["lat"], "lon_pub": place["lon"],
            "precision_nm": place["radius_nm"]}


def _exact_fields(lat: float, lon: float, gaz: Gazetteer, how: str, conf: float,
                  precision_nm: float = COORD_PRECISION_NM) -> dict:
    """A posted (or computed) position is published as-is; the spot it falls in only names it."""
    snapped = gaz.snap(lat, lon)
    out = {"lat_exact": lat, "lon_exact": lon, "lat_pub": lat, "lon_pub": lon,
           "precision_nm": round(precision_nm, 2), "geocode": how, "geocode_confidence": conf}
    if snapped:
        out.update(place_id=snapped["id"], place_name=snapped["name"])
    return out


def _has_table(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _from_mentions(conn, gaz: Gazetteer) -> list[dict]:
    if not _has_table(conn, "report_mentions"):
        return []
    rows = []
    for r in conn.execute("""
            SELECT m.id, m.type, m.source_id, m.feed_id, m.trip_date, m.bank, m.lat, m.lon,
                   m."precision" AS precision, m.payload, m.confidence,
                   s.url, s.title, s.published_at, s.fetched_at
            FROM report_mentions m JOIN paddy_sources s ON s.id = m.source_id"""):
        p = json.loads(r["payload"] or "{}")
        kind = {"paddy": "paddy", "bite": "bite", "conditions": "conditions"}.get(r["type"], "area")
        if r["type"] == "position":
            kind = "coords" if p.get("kind") == "gps" else "offset"
        base = _row(origin="paddy_mention", origin_id=r["id"], source_id=r["source_id"],
                    feed_id=r["feed_id"], url=r["url"], title=r["title"], trip_date=r["trip_date"],
                    published_at=r["published_at"], fetched_at=r["fetched_at"], kind=kind,
                    name_raw=r["bank"],
                    species=json.dumps(sorted(set(p.get("species") or []))),
                    quality=OUTCOME_TO_QUALITY.get(p.get("outcome")),
                    water_temp_f=p.get("water_temp_f") if isinstance(p.get("water_temp_f"), (int, float)) else None)
        conf = float(r["confidence"] or 0.7)
        # lat/lon with precision 'bank' is just the bank centre; anything else is a
        # posted position (GPS numbers or an offset), which must be coarsened.
        if r["lat"] is not None and r["lon"] is not None and r["precision"] != "bank":
            how = "offset" if (r["precision"] == "offset" or kind == "offset") else "coords"
            base.update(_exact_fields(r["lat"], r["lon"], gaz, how, conf,
                                      COORD_PRECISION_NM if how == "coords"
                                      else offset_precision(p.get("distance_nm"))))
        elif r["bank"] and gaz.get(r["bank"]):
            base.update(_place_fields(gaz.get(r["bank"]), "gazetteer"))
            base["geocode_confidence"] = min(conf, base["geocode_confidence"])
        rows.append(base)
    return rows


def _from_locations(conn, gaz: Gazetteer) -> tuple[list[dict], set[str]]:
    if not _has_table(conn, "forum_locations"):
        return [], set()
    rows, sources = [], set()
    for r in conn.execute("""
            SELECT l.*, s.url, s.title FROM forum_locations l
            LEFT JOIN paddy_sources s ON s.id = l.source_id"""):
        sources.add(r["source_id"])
        base = _row(origin="trip_location", origin_id=r["id"], source_id=r["source_id"],
                    feed_id=r["feed_id"], url=r["url"], title=r["title"], boat=r["boat"],
                    trip_date=r["trip_date"], published_at=r["published_at"], fetched_at=r["fetched_at"],
                    kind=r["kind"], name_raw=r["name"], species=r["species"] or "[]",
                    quality=r["quality"], water_temp_f=r["water_temp_f"])
        if r["lat"] is not None and r["lon"] is not None:
            base.update(_exact_fields(r["lat"], r["lon"], gaz, "coords", 0.9))
        elif r["distance_nm"] and r["bearing_deg"] is not None and gaz.lookup(r["from_place"] or r["name"]):
            ref = gaz.lookup(r["from_place"] or r["name"])
            lat, lon = coords_mod.apply_offset(ref["lat"], ref["lon"], r["bearing_deg"], r["distance_nm"])
            base.update(_exact_fields(lat, lon, gaz, "offset", min(0.7, ref["confidence"]),
                                      offset_precision(r["distance_nm"])))
        else:
            place = gaz.lookup(r["name"])
            base.update(_place_fields(place, place["source"] if place else "unresolved"))
        rows.append(base)
    return rows, sources


def _from_trip_spots(conn, gaz: Gazetteer, skip_sources: set[str]) -> list[dict]:
    """Older trip-report rows (before forum_locations) carry spot names only."""
    if not _has_table(conn, "forum_boat_reports"):
        return []
    rows = []
    for r in conn.execute("""
            SELECT b.id, b.source_id, b.feed_id, b.boat, b.trip_date, b.spots,
                   s.url, s.title, s.published_at, s.fetched_at
            FROM forum_boat_reports b LEFT JOIN paddy_sources s ON s.id = b.source_id"""):
        if r["source_id"] in skip_sources:
            continue
        for name in json.loads(r["spots"] or "[]"):
            place = gaz.lookup(name)
            base = _row(origin="trip_spot", origin_id=r["id"], source_id=r["source_id"],
                        feed_id=r["feed_id"], url=r["url"], title=r["title"], boat=r["boat"],
                        trip_date=r["trip_date"], published_at=r["published_at"],
                        fetched_at=r["fetched_at"], kind="area", name_raw=name)
            base.update(_place_fields(place, place["source"] if place else "unresolved"))
            rows.append(base)
    return rows


COLUMNS = ["origin", "origin_id", "source_id", "feed_id", "url", "title", "boat", "trip_date",
           "published_at", "fetched_at", "report_date", "kind", "name_raw", "place_id", "place_name",
           "geocode", "geocode_confidence", "lat_exact", "lon_exact", "lat_pub", "lon_pub",
           "precision_nm", "species", "quality", "water_temp_f"]


def rebuild(conn: sqlite3.Connection, gaz: Gazetteer | None = None) -> dict:
    gaz = gaz or Gazetteer()
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    loc_rows, loc_sources = _from_locations(conn, gaz)
    rows = _from_mentions(conn, gaz) + loc_rows + _from_trip_spots(conn, gaz, loc_sources)
    rows = [r for r in rows if r["report_date"]]
    conn.execute("DELETE FROM forum_spot_reports")
    conn.executemany(
        f"INSERT INTO forum_spot_reports ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
        [tuple(r[c] for c in COLUMNS) for r in rows])
    conn.commit()
    unresolved = Counter(r["name_raw"] for r in rows if r["geocode"] == "unresolved" and r["name_raw"])
    return {"rows": len(rows), "geocoded": sum(r["geocode"] != "unresolved" for r in rows),
            "unresolved_names": dict(unresolved.most_common(25))}


# ------------------------------------------------------------------ publish

def _cell_key(r) -> str:
    """Named-spot mentions group by spot; each posted/estimated position is its own point."""
    if r["lat_exact"] is not None:
        return f"pt:{r['lat_pub']:.4f},{r['lon_pub']:.4f}"
    return r["place_id"]


POSITION_KIND = {"coords": "posted", "offset": "estimate"}


def public_species(names) -> Counter:
    c = Counter()
    for n in names:
        c[n if n in PUBLIC_SPECIES else "other"] += 1
    return c


def build_geojson(conn: sqlite3.Connection, gaz: Gazetteer | None = None,
                  now: datetime | None = None, window_days: int = WINDOW_DAYS) -> dict:
    gaz = gaz or Gazetteer()
    conn.row_factory = sqlite3.Row
    now = now or datetime.now(timezone.utc)
    cutoff = (now.date() - timedelta(days=window_days)).isoformat()
    cutoff_short = (now.date() - timedelta(days=SHORT_WINDOW_DAYS)).isoformat()
    today = now.date().isoformat()
    rows = list(conn.execute(
        "SELECT * FROM forum_spot_reports WHERE lat_pub IS NOT NULL AND report_date >= ? "
        "AND report_date <= ? ORDER BY report_date DESC, id DESC", (cutoff, today)))
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[_cell_key(r)].append(r)

    features = []
    for key, rs in groups.items():
        first = rs[0]
        position = POSITION_KIND.get(first["geocode"], "spot")
        if first["place_id"]:
            name = first["place_name"]
        else:
            near, d = gaz.nearest(first["lat_pub"], first["lon_pub"])
            name = f"~{round(d)} nm from {near['name']}" if near and d < 60 else "Offshore"
        srcs_14 = {r["source_id"] for r in rs}
        srcs_7 = {r["source_id"] for r in rs if r["report_date"] >= cutoff_short}
        species = Counter()
        quality = Counter()
        kinds = Counter()
        temps = []
        for r in rs:
            species.update(public_species(json.loads(r["species"] or "[]")))
            if r["quality"]:
                quality[r["quality"]] += 1
            kinds[r["kind"] or "area"] += 1
            if r["water_temp_f"]:
                temps.append(float(r["water_temp_f"]))
        links, seen = [], set()
        for r in rs:
            if r["url"] and r["url"] not in seen:
                seen.add(r["url"])
                links.append({"url": r["url"], "title": r["title"], "date": r["report_date"],
                              "feed": r["feed_id"]})
            if len(links) >= MAX_SOURCES_PER_SPOT:
                break
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [first["lon_pub"], first["lat_pub"]]},
            "properties": {
                "id": key, "name": name,
                "position": position,      # posted | estimate | spot
                "precision_nm": max(r["precision_nm"] or COORD_PRECISION_NM for r in rs),
                "reports_7d": len(srcs_7), "reports_14d": len(srcs_14),
                "last_report": first["report_date"],
                "species": dict(species.most_common()),
                "quality": {q: quality[q] for q in QUALITY_ORDER if quality[q]},
                "kinds": dict(kinds.most_common()),
                "water_temp_f": {"min": min(temps), "max": max(temps)} if temps else None,
                "sources": links,
            },
        })
    features.sort(key=lambda f: (-f["properties"]["reports_14d"], f["properties"]["name"]))
    return {
        "type": "FeatureCollection",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": "Recent forum reports by spot",
        "source": "BloodyDecks (bdoutdoors.com) public forum posts, summarized automatically",
        "window_days": window_days, "short_window_days": SHORT_WINDOW_DAYS,
        "note": ("position 'posted' = coordinates printed in the thread; 'estimate' = worked out "
                 "from 'N miles off X'; 'spot' = the named spot's centre. precision_nm says how far "
                 "to trust each point. Follow the links for the original posts."),
        "attribution": "Spot list courtesy SWYC Anglers",
        "features": features,
    }


def write_geojson(path: Path = OUT_PATH, conn: sqlite3.Connection | None = None) -> dict:
    data = build_geojson(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


RESEARCH_COLUMNS = ["report_date", "trip_date", "published_at", "fetched_at", "feed_id", "source_id",
                    "url", "boat", "kind", "name_raw", "place_id", "place_name", "geocode",
                    "geocode_confidence", "lat_exact", "lon_exact", "lat_pub", "lon_pub",
                    "precision_nm", "species", "quality", "water_temp_f"]


def write_research_csv(path: Path, conn: sqlite3.Connection) -> int:
    """Dated spot + catch-quality series for forecast R&D. Research only:
    includes the exact research point, so it stays out of web/ and git."""
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(f"SELECT {', '.join(RESEARCH_COLUMNS)} FROM forum_spot_reports "
                             "ORDER BY report_date, id"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(RESEARCH_COLUMNS)
        w.writerows([tuple(r) for r in rows])
    return len(rows)


def record_health(stats: dict, path: Path = STATE_PATH) -> None:
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        state = {}
    state["spots_last_run_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["spots_rows"] = stats.get("rows")
    state["spots_geocoded"] = stats.get("geocoded")
    state["spots_features"] = stats.get("features")
    state["spots_unresolved_names"] = stats.get("unresolved_names")
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.environ.get("PADDIES_DB") or str(ROOT / "data" / "paddies.db"))
    ap.add_argument("--out", default=str(OUT_PATH))
    ap.add_argument("--research-csv", help="also write the research series here (keep out of git)")
    ap.add_argument("--no-state", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conn = sqlite3.connect(args.db, timeout=30)
    gaz = Gazetteer()
    stats = rebuild(conn, gaz)
    data = build_geojson(conn, gaz)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    stats["features"] = len(data["features"])
    if args.research_csv:
        stats["research_rows"] = write_research_csv(Path(args.research_csv), conn)
    if not args.no_state:
        record_health(stats)
    log.info("spots: %s", json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
