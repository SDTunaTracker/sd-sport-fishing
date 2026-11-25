"""Append-only archive of live AIS positions for our tracked boats.

Listens to aisstream.io and stores every position report from a boat in
data/vessel_mmsi.json into %LOCALAPPDATA%/TunaTracker/ais_archive.db, outside the
repo. Each day not archived is lost, so this is meant to run continuously.

PRIVATE BY DESIGN. The repo is public and tracker.db is committed to it, so
raw tracks are never written to tracker.db, web/, or anything else that is
published. aisstream's terms are unclear (its /terms page returns 404 as of
2026-11-25). Use the archive only internally and for the forecast until the
owner clears publishing.

    .venv\\Scripts\\python.exe -m src.ais_archive                  # run forever
    .venv\\Scripts\\python.exe -m src.ais_archive --duration 600   # 10 minutes
    .venv\\Scripts\\python.exe -m src.ais_archive --status

Needs AISSTREAM_API_KEY in .env.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Outside the repo on purpose, so no `git add -A` can ever publish it.
ARCHIVE_DB = Path(os.environ.get("AIS_ARCHIVE_DB")
                  or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TunaTracker" / "ais_archive.db")
MMSI_PATH = ROOT / "data" / "vessel_mmsi.json"
STREAM_URL = "wss://stream.aisstream.io/v0/stream"
SOURCE = "aisstream"

# SoCal + Baja long-range grounds, and the SF Bay / Central Coast.
BOXES = [
    [[20.0, -125.0], [35.5, -109.0]],
    [[36.5, -124.5], [38.6, -121.5]],
]
MSG_TYPES = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"]
MAX_MMSI_FILTER = 50   # aisstream's per-subscription MMSI filter limit
FLUSH_EVERY = 5.0      # seconds between DB commits

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS ais_positions (
    mmsi        INTEGER NOT NULL,
    ts          TEXT    NOT NULL,   -- report time, UTC ISO (aisstream time_utc)
    lat         REAL    NOT NULL,
    lon         REAL    NOT NULL,
    sog         REAL,               -- knots
    cog         REAL,               -- degrees
    heading     REAL,
    msg_type    TEXT,
    source      TEXT    NOT NULL,
    received_at TEXT    NOT NULL,   -- when we stored it, UTC ISO
    UNIQUE (mmsi, ts)
);
CREATE INDEX IF NOT EXISTS idx_ais_positions_ts ON ais_positions(ts);
CREATE TABLE IF NOT EXISTS archive_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    host        TEXT,
    messages    INTEGER DEFAULT 0,
    stored      INTEGER DEFAULT 0,
    last_error  TEXT
);
"""


def open_db(path: Path = ARCHIVE_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(DDL)
    return conn


def load_tracked(path: Path = MMSI_PATH) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): v for k, v in data.get("vessels", {}).items() if str(k).isdigit()}


def _norm_ts(t: str | None) -> str:
    """aisstream time_utc looks like '2026-11-25 18:03:11.123456789 +0000 UTC'."""
    if not t:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    s = t.replace(" +0000 UTC", "").strip()
    date_part, _, time_part = s.partition(" ")
    time_part = time_part.split(".")[0]
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}+00:00").isoformat(timespec="seconds")
    except ValueError:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_message(raw: str | bytes, tracked: dict[str, dict]) -> tuple | None:
    """aisstream JSON -> row tuple for ais_positions, or None if not ours."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    meta = data.get("MetaData") or {}
    mmsi = str(meta.get("MMSI", "")).strip()
    if mmsi not in tracked:
        return None
    mtype = data.get("MessageType")
    msg = (data.get("Message") or {}).get(mtype) or {}
    lat = meta.get("latitude", msg.get("Latitude"))
    lon = meta.get("longitude", msg.get("Longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 0.001 and abs(lon) < 0.001:   # "no position" sentinel
        return None
    head = msg.get("TrueHeading")
    return (int(mmsi), _norm_ts(meta.get("time_utc")), float(lat), float(lon),
            msg.get("Sog"), msg.get("Cog"), None if head in (None, 511) else head,
            mtype, SOURCE, datetime.now(timezone.utc).isoformat(timespec="seconds"))


_INSERT = ("INSERT OR IGNORE INTO ais_positions (mmsi, ts, lat, lon, sog, cog, heading,"
           " msg_type, source, received_at) VALUES (?,?,?,?,?,?,?,?,?,?)")


def subscription(api_key: str, tracked: dict) -> dict:
    sub = {"APIKey": api_key, "BoundingBoxes": BOXES, "FilterMessageTypes": MSG_TYPES}
    if len(tracked) <= MAX_MMSI_FILTER:
        sub["FiltersShipMMSI"] = sorted(tracked)
    return sub   # else: boxes only, filtered locally in parse_message


async def _listen(conn, run_id: int, api_key: str, tracked: dict, deadline: float | None) -> None:
    import websockets
    stats = {"messages": 0, "stored": 0}
    backoff = 5.0
    while deadline is None or time.monotonic() < deadline:
        try:
            async with websockets.connect(STREAM_URL, ping_interval=30, max_size=2 ** 22) as ws:
                await ws.send(json.dumps(subscription(api_key, tracked)))
                log.info("connected; tracking %d boats", len(tracked))
                backoff = 5.0
                batch, last_flush = [], time.monotonic()
                async for raw in ws:
                    stats["messages"] += 1
                    row = parse_message(raw, tracked)
                    if row:
                        batch.append(row)
                    now = time.monotonic()
                    if now - last_flush >= FLUSH_EVERY:
                        _flush(conn, run_id, batch, stats)
                        batch, last_flush = [], now
                    if deadline is not None and now >= deadline:
                        break
                _flush(conn, run_id, batch, stats)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — reconnect on anything
            log.warning("stream dropped: %s; reconnecting in %.0fs", e, backoff)
            conn.execute("UPDATE archive_runs SET last_error=? WHERE id=?",
                         (f"{type(e).__name__}: {e}"[:300], run_id))
            conn.commit()
            await asyncio.sleep(backoff + random.uniform(0, 3))
            backoff = min(backoff * 2, 300.0)


def _flush(conn, run_id: int, batch: list, stats: dict) -> None:
    if batch:
        before = conn.total_changes
        conn.executemany(_INSERT, batch)
        stats["stored"] += conn.total_changes - before
    conn.execute("UPDATE archive_runs SET ended_at=?, messages=?, stored=? WHERE id=?",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  stats["messages"], stats["stored"], run_id))
    conn.commit()


def status(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT mmsi), MIN(ts), MAX(ts) FROM ais_positions").fetchone()
    last = conn.execute("SELECT started_at, ended_at, messages, stored, last_error FROM archive_runs"
                        " ORDER BY id DESC LIMIT 1").fetchone()
    return {"rows": row[0], "boats": row[1], "first": row[2], "last": row[3],
            "last_run": dict(zip(("started", "heartbeat", "messages", "stored", "last_error"), last))
            if last else None}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duration", type=int, default=0, help="seconds to run (0 = forever)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--db", type=Path, default=ARCHIVE_DB)
    ap.add_argument("--env", type=Path, default=ROOT / ".env", help=".env holding AISSTREAM_API_KEY")
    ap.add_argument("--mmsi", type=Path, default=MMSI_PATH, help="vessel_mmsi.json")
    a = ap.parse_args(argv)
    conn = open_db(a.db)
    if a.status:
        print(json.dumps(status(conn), indent=1))
        return 0
    try:
        from dotenv import load_dotenv
        load_dotenv(a.env)
    except ImportError:
        pass
    key = os.environ.get("AISSTREAM_API_KEY")
    if not key:
        print("AISSTREAM_API_KEY not set in .env")
        return 1
    import socket
    tracked = load_tracked(a.mmsi)
    cur = conn.execute("INSERT INTO archive_runs (started_at, host) VALUES (?,?)",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"), socket.gethostname()))
    conn.commit()
    deadline = time.monotonic() + a.duration if a.duration else None
    try:
        asyncio.run(_listen(conn, cur.lastrowid, key, tracked, deadline))
    except KeyboardInterrupt:
        pass
    print(json.dumps(status(conn), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
