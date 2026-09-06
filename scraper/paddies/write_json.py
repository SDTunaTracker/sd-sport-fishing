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
from collections import defaultdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "tracker.db"
GAZETTEER_PATH = ROOT / "data" / "banks.geojson"
OUT_DIR = ROOT / "web" / "api" / "v1"
PADDIES_OUT = OUT_DIR / "paddies.json"
BANKS_OUT = OUT_DIR / "banks.json"

WINDOW_DAYS = 14
RECENT_PER_BANK = 5


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

    q = f"""
      SELECT
        m.bank            AS bank,
        COALESCE(m.trip_date, DATE(s.published_at)) AS effective_date,
        m.paddy_count     AS paddy_count,
        m.holding         AS holding,
        m.species_json    AS species_json,
        m.quote           AS quote,
        s.url             AS url
      FROM paddy_mentions m
      JOIN paddy_sources s ON s.id = m.source_id
      WHERE COALESCE(m.trip_date, DATE(s.published_at)) >= ?
      ORDER BY effective_date DESC, m.id DESC
    """
    rows = list(conn.execute(q, (cutoff,)))

    per_bank: dict[str, list[sqlite3.Row]] = defaultdict(list)
    unresolved = 0
    for r in rows:
        if r["bank"] is None:
            unresolved += 1
            continue
        if r["bank"] not in id_to_name:
            unresolved += 1  # gazetteer changed under us — count as unresolved
            continue
        per_bank[r["bank"]].append(r)

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
                "holding":     bool(e["holding"]) if e["holding"] is not None else None,
                "species":     json.loads(e["species_json"] or "[]"),
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

        if not dry_run:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            BANKS_OUT.write_text(
                json.dumps(banks_payload, separators=(",", ":")), encoding="utf-8",
            )
            PADDIES_OUT.write_text(
                json.dumps(paddies_payload, indent=2), encoding="utf-8",
            )
        return {
            "build": build_sha,
            "generated_at": generated_at,
            "banks_features": banks_payload["metadata"]["feature_count"],
            "paddies_banks":  len(paddies_payload["banks"]),
            "unresolved":     paddies_payload["unresolved"],
            "paddies_out":    str(PADDIES_OUT),
            "banks_out":      str(BANKS_OUT),
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
