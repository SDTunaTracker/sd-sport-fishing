"""ENSO context: NOAA CPC Oceanic Niño Index plus the current ENSO Alert status.

Context only, for Co-Captain and season narratives. Forecast R&D (rounds 1–4)
found ENSO/PDO add no skill to the catch forecast, so this is not a model
input.

    python -m src.enso            # fetch if older than 7 days, then export
    python -m src.enso --force    # fetch now

Sources (US government, public domain, no key):
  https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
  https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml
Writes tracker.db `enso_oni` + `enso_status`, and web/api/v1/enso.json.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
OUT = ROOT / "web" / "api" / "v1" / "enso.json"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
DISC_URL = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml"
UA = {"User-Agent": "thetunatracker.com/enso-ingest"}
REFRESH_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS enso_oni (
    season TEXT NOT NULL,      -- DJF, JFM, ... NDJ (3-month running season)
    year   INTEGER NOT NULL,
    total  REAL,               -- Niño-3.4 SST, °C
    anom   REAL NOT NULL,      -- ONI, °C
    PRIMARY KEY (season, year)
);
CREATE TABLE IF NOT EXISTS enso_status (
    fetched_at TEXT PRIMARY KEY,
    alert      TEXT,           -- e.g. "El Niño Advisory", "La Niña Watch", "Not Active"
    synopsis   TEXT
);
"""
SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


def parse_oni(text: str) -> list[tuple[str, int, float, float]]:
    rows = []
    for line in text.splitlines():
        m = re.match(r"\s*([A-Z]{3})\s+(\d{4})\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", line)
        if m and m.group(1) in SEASONS:
            rows.append((m.group(1), int(m.group(2)), float(m.group(3)), float(m.group(4))))
    return rows


def parse_status(page: str) -> tuple[str | None, str | None]:
    txt = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", page)))
    txt = re.sub(r"\s+", " ", txt)
    alert = re.search(r"ENSO Alert System Status:\s*(.+?)\s+Synopsis:", txt)
    syn = re.search(r"Synopsis:\s*(.+?\.)(?:\s|$)", txt)
    return (alert.group(1).strip() if alert else None, syn.group(1).strip() if syn else None)


def classify(anom: float) -> tuple[str, str | None]:
    """ONI phase plus strength, from the conventional thresholds.

    The official episode call needs 5 overlapping seasons, so the CPC alert is
    the authority.
    """
    a = abs(anom)
    if a < 0.5:
        return "Neutral", None
    phase = "El Niño" if anom > 0 else "La Niña"
    strength = "very strong" if a >= 2.0 else "strong" if a >= 1.5 else "moderate" if a >= 1.0 else "weak"
    return phase, strength


def fetch(conn: sqlite3.Connection) -> int:
    r = requests.get(ONI_URL, headers=UA, timeout=30)
    r.raise_for_status()
    rows = parse_oni(r.text)
    if len(rows) < 100:
        raise ValueError(f"ONI parse produced only {len(rows)} rows")
    conn.executemany("INSERT OR REPLACE INTO enso_oni VALUES (?,?,?,?)", rows)
    alert = syn = None
    try:
        d = requests.get(DISC_URL, headers=UA, timeout=30)
        d.raise_for_status()
        alert, syn = parse_status(d.text)
    except requests.RequestException as e:
        log.warning("ENSO discussion fetch failed: %s", e)
    conn.execute("INSERT OR REPLACE INTO enso_status VALUES (?,?,?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"), alert, syn))
    conn.commit()
    return len(rows)


def export_json(conn: sqlite3.Connection, out: Path = OUT) -> dict | None:
    order = {s: i for i, s in enumerate(SEASONS)}
    rows = sorted(conn.execute("SELECT season, year, anom FROM enso_oni"),
                  key=lambda r: (r[1], order[r[0]]))
    if not rows:
        return None
    st = conn.execute("SELECT fetched_at, alert, synopsis FROM enso_status ORDER BY fetched_at DESC LIMIT 1").fetchone()
    season, year, anom = rows[-1]
    phase, strength = classify(anom)
    data = {
        "updated": st[0] if st else None,
        "source": "NOAA Climate Prediction Center (ONI, ENSO Alert System)",
        "latest": {"season": season, "year": year, "oni": anom, "phase": phase, "strength": strength},
        "alert": st[1] if st else None,
        "synopsis": st[2] if st else None,
        "recent": [{"season": s, "year": y, "oni": a} for s, y, a in rows[-12:]],
        "note": "Context only. Tunatracker's backtests found ENSO does not improve day-to-day catch forecasts.",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def update(db_path: Path = DB_PATH, force: bool = False) -> str:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        last = conn.execute("SELECT MAX(fetched_at) FROM enso_status").fetchone()[0]
        due = force or not last or last < (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).isoformat()
        msg = "ENSO: up to date"
        if due:
            n = fetch(conn)
            msg = f"ENSO: fetched {n} ONI seasons"
        d = export_json(conn)
        if d:
            lt = d["latest"]
            msg += f"; latest {lt['season']} {lt['year']} ONI {lt['oni']:+.2f} ({d.get('alert') or lt['phase']})"
        return msg
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(update(force=a.force))
    return 0


if __name__ == "__main__":
    sys.exit(main())
