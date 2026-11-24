"""
Emit /api/v1/paddies.json and /api/v1/banks.json under web/.

Called after ingest + extract on the nightly workflow. Uses the current
gazetteer and the last 14 days of paddy_mentions to compute per-bank
aggregates. Only includes banks with at least one mention in-window.
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

from .feeds import enabled_feeds

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("PADDIES_DB") or (ROOT / "data" / "paddies.db"))
GAZETTEER_PATH = ROOT / "data" / "banks.geojson"
OUT_DIR = ROOT / "web" / "api" / "v1"
PADDIES_OUT = OUT_DIR / "paddies.json"
BANKS_OUT = OUT_DIR / "banks.json"
REPORTS_OUT = OUT_DIR / "reports.json"

WINDOW_DAYS = 14
RECENT_PER_BANK = 5
RECENT_PER_BANK_REPORTS = 8   # v2 spec: last 8 per bank in reports.json
TOP_BANKS_48H = 3
SUMMARY_HOURS = 48


def short_sha() -> str:
    """GITHUB_SHA on CI, else `git rev-parse --short HEAD`, else 'local'."""
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:7]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip() or "local"
    except Exception:
        return "local"


def load_gazetteer_features() -> list[dict]:
    data = json.loads(GAZETTEER_PATH.read_text(encoding="utf-8"))
    return data["features"]


def build_banks_json(features: list[dict], build_sha: str, generated_at: str) -> dict:
    """Public banks catalogue — non-admin features only."""
    out_features = []
    for f in features:
        if f["properties"]["kind"] == "admin":
            continue
        out_features.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": {
                k: v for k, v in f["properties"].items()
                if k != "source_name"
            },
        })
    return {
        "build": build_sha,
        "generated_at": generated_at,
        "type": "FeatureCollection",
        "metadata": {
            "attribution": "Spot list courtesy SWYC Anglers",
            "source_credit": "SWYC Anglers public spot list (Michael Mooradian)",
            "source_url": "https://swycanglers.org/resources/local-offshore-fishing-spots/",
            "feature_count": len(out_features),
        },
        "features": out_features,
    }


def build_paddies_json(conn: sqlite3.Connection, features: list[dict],
                      build_sha: str, generated_at: str,
                      window_days: int = WINDOW_DAYS) -> dict:
    id_to_name = {f["properties"]["id"]: f["properties"]["name"] for f in features}
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()

    # v2: read from report_mentions filtered to type='paddy'. All the
    # paddy-specific fields (paddy_count, holding, species) live in payload.
    q = """
      SELECT
        m.bank            AS bank,
        COALESCE(m.trip_date, DATE(s.published_at)) AS effective_date,
        m.payload         AS payload_json,
        m.quote           AS quote,
        s.url             AS url
      FROM report_mentions m
      JOIN paddy_sources s ON s.id = m.source_id
      WHERE m.type = 'paddy'
        AND COALESCE(m.trip_date, DATE(s.published_at)) >= ?
      ORDER BY effective_date DESC, m.id DESC
    """
    rows = list(conn.execute(q, (cutoff,)))

    # unpack payload once per row
    def _unpack(r):
        p = json.loads(r["payload_json"] or "{}")
        return {
            "bank":           r["bank"],
            "effective_date": r["effective_date"],
            "paddy_count":    p.get("paddy_count"),
            "holding":        p.get("holding"),
            "species":        p.get("species") or [],
            "quote":          r["quote"],
            "url":            r["url"],
        }
    entries_all = [_unpack(r) for r in rows]

    per_bank: dict[str, list[dict]] = defaultdict(list)
    unresolved = 0
    for e in entries_all:
        if e["bank"] is None or e["bank"] not in id_to_name:
            unresolved += 1
            continue
        per_bank[e["bank"]].append(e)

    banks_out: dict[str, dict] = {}
    for bank_id, entries in per_bank.items():
        mentions_14d = len(entries)
        paddies_reported = sum((e["paddy_count"] or 0) for e in entries)
        holdings = [e["holding"] for e in entries if e["holding"] is not None]
        holding_ratio = (
            round(sum(1 for h in holdings if h) / len(holdings), 3)
            if holdings else None
        )
        last_report = entries[0]["effective_date"]
        recent = []
        for e in entries[:RECENT_PER_BANK]:
            recent.append({
                "trip_date":   e["effective_date"],
                "paddy_count": e["paddy_count"],
                "holding":     e["holding"],
                "species":     e["species"],
                "quote":       e["quote"],
                "url":         e["url"],
            })
        banks_out[bank_id] = {
            "name":                    id_to_name[bank_id],
            "mentions_14d":            mentions_14d,
            "paddies_reported_14d":    paddies_reported,
            "holding_ratio_14d":       holding_ratio,
            "last_report":             last_report,
            "recent":                  recent,
        }

    return {
        "build":        build_sha,
        "generated_at": generated_at,
        "window_days":  window_days,
        "banks":        banks_out,
        "unresolved":   unresolved,
    }


def _rows_in_window(conn, cutoff_iso: str) -> list[dict]:
    """One place to load every mention in the window, joined to its source."""
    rows = list(conn.execute("""
        SELECT m.id, m.type, m.source_id, m.bank, m.lat, m.lon,
               m."precision" AS precision, m.payload, m.quote, m.confidence,
               COALESCE(m.trip_date, DATE(s.published_at)) AS effective_date,
               s.url, s.feed_id, s.published_at
        FROM report_mentions m
        JOIN paddy_sources s ON s.id = m.source_id
        WHERE COALESCE(m.trip_date, DATE(s.published_at)) >= ?
        ORDER BY effective_date DESC, m.id DESC
    """, (cutoff_iso,)))
    return [dict(r) for r in rows]


def _recent_entry(row: dict) -> dict:
    """Serialize a report_mentions row for a bank's `recent[]` slot."""
    p = json.loads(row["payload"] or "{}")
    is_bite = row["type"] == "bite"
    is_cond = row["type"] == "conditions"
    return {
        "type":         row["type"],
        "trip_date":    row["effective_date"],
        "species":      p.get("species") or [],
        "count":        p.get("count") if is_bite else None,
        "size_lb":      p.get("size_lb") if is_bite else None,
        "outcome":      p.get("outcome") if is_bite else None,
        "water_temp_f": p.get("water_temp_f"),
        "water_color":  p.get("water_color") if is_cond else None,
        "quote":        row["quote"],
        "url":          row["url"],
        "feed_id":      row["feed_id"],
    }


def build_reports_json(conn: sqlite3.Connection, features: list[dict],
                       build_sha: str, generated_at: str,
                       feeds: list[dict],
                       window_days: int = WINDOW_DAYS,
                       now: datetime | None = None) -> dict:
    """
    Emit /api/v1/reports.json. Aggregates all typed mentions (not just paddy)
    over the 14-day window, with a 48-hour summary block and an explicit
    pins array carrying every valid position.
    """
    id_to_feat = {f["properties"]["id"]: f for f in features}
    now = now or datetime.now(timezone.utc)
    cutoff = (now.date() - timedelta(days=window_days)).isoformat()
    cutoff_48h_iso = (now - timedelta(hours=SUMMARY_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = _rows_in_window(conn, cutoff)

    # feeds — items_14d per feed
    feeds_out = []
    for f in feeds:
        n = conn.execute(
            "SELECT COUNT(*) FROM paddy_sources "
            "WHERE feed_id = ? AND DATE(published_at) >= ?",
            (f["id"], cutoff),
        ).fetchone()[0]
        feeds_out.append({
            "id":        f["id"],
            "name":      f["name"],
            "forum_url": f["forum_url"],
            "items_14d": n,
        })

    # banks — group non-position mentions by bank
    per_bank: dict[str, list[dict]] = defaultdict(list)
    unresolved = 0
    for r in rows:
        if r["type"] == "position":
            continue
        bank = r["bank"]
        if bank and bank in id_to_feat:
            per_bank[bank].append(r)
        else:
            # unresolved: no bank AND no resolved coordinate. Paddies with a
            # non-empty `route` count as "resolved enough" (v1 rule carried over).
            if r["lat"] is not None:
                continue
            if r["type"] == "paddy":
                try:
                    if json.loads(r["payload"] or "{}").get("route"):
                        continue
                except Exception:
                    pass
            unresolved += 1

    banks_out: dict[str, dict] = {}
    for bank_id, entries in per_bank.items():
        feat = id_to_feat[bank_id]
        lon, lat = feat["geometry"]["coordinates"]
        radius_nm = feat["properties"].get("radius_nm")

        bite_14d = sum(1 for e in entries if e["type"] == "bite")
        species_14d: dict[str, int] = defaultdict(int)
        outcomes: list[str] = []
        for e in entries:
            p = json.loads(e["payload"] or "{}")
            for s in (p.get("species") or []):
                species_14d[s] += 1
            if e["type"] == "bite" and p.get("outcome"):
                outcomes.append(p["outcome"])
        outcome_mode = Counter(outcomes).most_common(1)[0][0] if outcomes else None

        banks_out[bank_id] = {
            "name":          feat["properties"]["name"],
            "lat":           lat,
            "lon":           lon,
            "radius_nm":     radius_nm,
            "mentions_14d":  len(entries),
            "bite_14d":      bite_14d,
            "species_14d":   dict(species_14d),
            "outcome_mode":  outcome_mode,
            "last_report":   entries[0]["effective_date"],
            "recent":        [_recent_entry(e) for e in entries[:RECENT_PER_BANK_REPORTS]],
        }

    # pins — every valid position, with cross-reference to sibling mentions
    # in the same source that inherited its lat/lon (so we can populate
    # species/bank on the pin for the UI).
    sibling_by_pos: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["type"] != "position" and r["lat"] is not None and r["lon"] is not None:
            sibling_by_pos[(r["source_id"], r["lat"], r["lon"])].append(r)

    pins = []
    for r in rows:
        if r["type"] != "position" or r["lat"] is None:
            continue
        pl = json.loads(r["payload"] or "{}")
        kind = pl.get("kind")
        ref = pl.get("ref_bank")
        if kind == "gps":
            resolution = "gps"
        elif kind == "offset" and ref:
            resolution = f"offset:{ref}"
        else:
            resolution = None

        siblings = sibling_by_pos.get((r["source_id"], r["lat"], r["lon"]), [])
        sib_species: set[str] = set()
        sib_banks: set[str] = set()
        for s in siblings:
            sp = json.loads(s["payload"] or "{}")
            sib_species.update(sp.get("species") or [])
            if s["bank"]:
                sib_banks.add(s["bank"])
        pin_bank = list(sib_banks)[0] if len(sib_banks) == 1 else None

        pins.append({
            "lat":        r["lat"],
            "lon":        r["lon"],
            "precision":  r["precision"],
            "resolution": resolution,
            "trip_date":  r["effective_date"],
            "bank":       pin_bank,
            "species":    sorted(sib_species),
            "quote":      r["quote"],
            "url":        r["url"],
            "feed_id":    r["feed_id"],
            "raw":        pl.get("raw"),
        })

    # summary_48h
    recent48 = [r for r in rows if _in_last_hours(r, now, SUMMARY_HOURS)]

    per_bank_48: dict[str, list[dict]] = defaultdict(list)
    for r in recent48:
        if r["type"] == "position":
            continue
        if r["bank"] and r["bank"] in id_to_feat:
            per_bank_48[r["bank"]].append(r)

    top_banks_48 = []
    for bank_id, entries in sorted(per_bank_48.items(), key=lambda kv: -len(kv[1]))[:TOP_BANKS_48H]:
        sp_counts: dict[str, int] = defaultdict(int)
        for e in entries:
            p = json.loads(e["payload"] or "{}")
            for s in (p.get("species") or []):
                sp_counts[s] += 1
        top_species = [s for s, _ in sorted(sp_counts.items(), key=lambda kv: -kv[1])[:3]]
        top_banks_48.append({
            "bank":         bank_id,
            "name":         id_to_feat[bank_id]["properties"]["name"],
            "mentions":     len(entries),
            "top_species":  top_species,
        })

    species_counts_48: dict[str, int] = defaultdict(int)
    temps_48: list[float] = []
    colors_48: list[str] = []
    paddies_reported_48 = 0
    for r in recent48:
        p = json.loads(r["payload"] or "{}")
        for s in (p.get("species") or []):
            species_counts_48[s] += 1
        t = p.get("water_temp_f")
        if isinstance(t, (int, float)):
            temps_48.append(float(t))
        if r["type"] == "conditions" and p.get("water_color"):
            colors_48.append(p["water_color"])
        if r["type"] == "paddy":
            paddies_reported_48 += (p.get("paddy_count") or 0)

    water_temp = None
    if temps_48:
        s = sorted(temps_48)
        water_temp = {"min": s[0], "max": s[-1], "median": s[len(s) // 2]}
    water_color_mode = Counter(colors_48).most_common(1)[0][0] if colors_48 else None

    summary_48h = {
        "top_banks":         top_banks_48,
        "species_counts":    dict(species_counts_48),
        "water_temp_f":      water_temp,
        "water_color_mode":  water_color_mode,
        "paddies_reported":  paddies_reported_48,
    }

    return {
        "build":            build_sha,
        "generated_at":     generated_at,
        "window_days":      window_days,
        "feeds":            feeds_out,
        "summary_48h":      summary_48h,
        "banks":            banks_out,
        "pins":             pins,
        "unresolved_14d":   unresolved,
    }


def _in_last_hours(row: dict, now: datetime, hours: int) -> bool:
    """Row falls inside the last N hours (uses trip_date if present, else published_at)."""
    trip_date = row.get("effective_date")
    if not trip_date:
        return False
    try:
        # trip_date is YYYY-MM-DD; treat as noon UTC for a coarse but stable test
        dt = datetime.strptime(trip_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (now - dt) <= timedelta(hours=hours)


def write(dry_run: bool = False) -> dict:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        features = load_gazetteer_features()
        build_sha = short_sha()
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        banks_payload = build_banks_json(features, build_sha, generated_at)
        paddies_payload = build_paddies_json(conn, features, build_sha, generated_at)
        reports_payload = build_reports_json(
            conn, features, build_sha, generated_at, enabled_feeds(),
        )

        if not dry_run:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            BANKS_OUT.write_text(
                json.dumps(banks_payload, separators=(",", ":")), encoding="utf-8",
            )
            PADDIES_OUT.write_text(
                json.dumps(paddies_payload, indent=2), encoding="utf-8",
            )
            REPORTS_OUT.write_text(
                json.dumps(reports_payload, indent=2), encoding="utf-8",
            )
        return {
            "build":              build_sha,
            "generated_at":       generated_at,
            "banks_features":     banks_payload["metadata"]["feature_count"],
            "paddies_banks":      len(paddies_payload["banks"]),
            "paddies_unresolved": paddies_payload["unresolved"],
            "reports_banks":      len(reports_payload["banks"]),
            "reports_pins":       len(reports_payload["pins"]),
            "reports_unresolved": reports_payload["unresolved_14d"],
            "paddies_out":        str(PADDIES_OUT),
            "banks_out":          str(BANKS_OUT),
            "reports_out":        str(REPORTS_OUT),
        }
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    stats = write(dry_run=args.dry_run)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
