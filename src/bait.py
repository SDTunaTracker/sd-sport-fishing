"""Live bait at the barge: the Everingham Bros. Bait Co. "Bait Report".

Everingham runs the live-bait barges in San Diego Bay, Mission Bay and Dana
Point. Its website embeds a Google Sheet ("Publish to the web") with, per
barge, the bait it is serving and an "As of" time. We read the sheet's CSV
export: one ~0.7 KB request per run, no key.

DORMANT until the owner hears back from Everingham (draft email in
docs/research/BAIT_SOURCES.md §6). The workflow step only runs when the repo
variable BAIT_REPORT_ENABLED is 'true', and the web panel is behind
FEATURES.BAIT_NOW (preview: ?preview_bait=true).

    python -m src.bait                 # fetch, store if changed, export
    python -m src.bait --export-only   # rebuild bait_now.json from the DB
    python -m src.bait --file x.csv    # parse a saved CSV (testing)

Writes tracker.db `bait_receiver_status` (one row per change) and
web/api/v1/bait_now.json.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tracker.db"
OUT = ROOT / "web" / "api" / "v1" / "bait_now.json"
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vSdG-EL9GxlkGH9N26rWvrbzHmXuIeNz1fsI9xGgmdNrqY70tlkIhl-Voh5mMEogdHUh21mKW88dXys"
    "/pub?gid=1941792441&single=true&output=csv"
)
CREDIT = {"name": "Everingham Bros. Bait Co.", "url": "https://baitbarge.com/", "phone": "(619) 477-2248"}
UA = {"User-Agent": "thetunatracker.com/bait-report (credits and links baitbarge.com)"}
PT = ZoneInfo("America/Los_Angeles")
STALE_HOURS = 24

# Which barge supplies which tracked landing. Oceanside has its own receiver
# and is not covered.
BARGES = {
    "san_diego_bay": {"name": "San Diego Bay", "landings": ["H&M Landing", "Fisherman's Landing", "Point Loma Sportfishing"]},
    "mission_bay": {"name": "Mission Bay", "landings": ["Seaforth Sportfishing"]},
    "dana_point": {"name": "Dana Point", "landings": ["Dana Wharf Sportfishing"]},
}
_BARGE_KEYS = [("san diego", "san_diego_bay"), ("mission bay", "mission_bay"), ("dana point", "dana_point")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS bait_receiver_status (
    barge      TEXT NOT NULL,   -- san_diego_bay | mission_bay | dana_point
    as_of      TEXT,            -- barge's own "As of" time, ISO, Pacific offset
    raw        TEXT NOT NULL,   -- e.g. "5-7 inch Sardine" (verbatim)
    species    TEXT,            -- sardine | anchovy | mackerel | squid | ... (lowercase)
    min_in     REAL,
    max_in     REAL,
    fetched_at TEXT NOT NULL,   -- UTC ISO
    PRIMARY KEY (barge, raw, as_of)
);
"""

_SPECIES = ["sardine", "anchovy", "mackerel", "squid", "smelt", "queenfish", "herring"]


def parse_bait(raw: str) -> dict:
    """'5-7 inch Sardine' -> {species: 'sardine', min_in: 5, max_in: 7}.

    Tolerates "5 - 7in", "5 to 7 inch", "6 inch", "Sardine & Anchovy" (first
    species wins). Unknown text keeps species None; the raw text is always
    shown verbatim on the site.
    """
    s = (raw or "").strip()
    low = s.lower()
    species = next((sp for sp in _SPECIES if sp in low), None)
    lo = hi = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:\"|in\b|inch)", low)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:\"|in\b|inch)", low)
        if m:
            lo = hi = float(m.group(1))
    return {"species": species, "min_in": lo, "max_in": hi}


def parse_as_of(text: str, now: datetime) -> str | None:
    """'11/25 - 8:45a' -> ISO in Pacific time. The year is inferred: the
    latest date not more than 2 days in the future (handles Dec→Jan)."""
    m = re.search(r"(\d{1,2})/(\d{1,2})\D+(\d{1,2}):(\d{2})\s*([ap])", (text or "").lower())
    if not m:
        return None
    mo, d, h, mi, ap = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)
    h = h % 12 + (12 if ap == "p" else 0)
    now_pt = now.astimezone(PT)
    for year in (now_pt.year + 1, now_pt.year, now_pt.year - 1):
        try:
            dt = datetime(year, mo, d, h, mi, tzinfo=PT)
        except ValueError:
            continue
        if dt <= now_pt + timedelta(days=2):
            return dt.isoformat()
    return None


def parse_sheet(text: str, now: datetime | None = None) -> list[dict]:
    """Find each '<X> Bait Barge' header column, then the first bait line
    below 'Currently Serving:' and the 'As of:' value to its right."""
    now = now or datetime.now(timezone.utc)
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for r_i, row in enumerate(rows):
        for c_i, cell in enumerate(row):
            if "bait barge" not in cell.lower():
                continue
            key = next((k for needle, k in _BARGE_KEYS if needle in cell.lower()), None)
            if not key:
                continue
            raw, as_of_text, serving_seen = None, None, False
            for below in rows[r_i + 1:]:
                v = below[c_i].strip() if c_i < len(below) else ""
                if not v:
                    continue
                lv = v.lower()
                if "bait barge" in lv:
                    break  # next block
                if lv.startswith("currently serving"):
                    serving_seen = True
                    continue
                if lv.startswith("as of"):
                    rest = v.split(":", 1)[1].strip() if ":" in v else ""
                    nxt = [x.strip() for x in below[c_i + 1:c_i + 3] if x.strip()]
                    as_of_text = rest or (nxt[0] if nxt else "")
                    break
                if serving_seen and raw is None and not v.startswith("*"):
                    raw = v
            if raw:
                out.append({"barge": key, "raw": raw, "as_of": parse_as_of(as_of_text or "", now), **parse_bait(raw)})
    # One entry per barge (the sheet could repeat a header).
    seen, uniq = set(), []
    for e in out:
        if e["barge"] not in seen:
            seen.add(e["barge"])
            uniq.append(e)
    return uniq


def fetch_csv() -> str:
    r = requests.get(CSV_URL, headers=UA, timeout=20)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def store(conn: sqlite3.Connection, entries: list[dict], fetched_at: str) -> int:
    conn.executescript(SCHEMA)
    n = 0
    for e in entries:
        cur = conn.execute(
            "INSERT OR IGNORE INTO bait_receiver_status (barge, as_of, raw, species, min_in, max_in, fetched_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (e["barge"], e["as_of"], e["raw"], e["species"], e["min_in"], e["max_in"], fetched_at),
        )
        n += cur.rowcount
    conn.commit()
    return n


def build_payload(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    conn.executescript(SCHEMA)
    barges = []
    for key, meta in BARGES.items():
        row = conn.execute(
            "SELECT raw, species, min_in, max_in, as_of, fetched_at FROM bait_receiver_status"
            " WHERE barge=? ORDER BY COALESCE(as_of, fetched_at) DESC, fetched_at DESC LIMIT 1",
            (key,),
        ).fetchone()
        if not row:
            continue
        raw, species, lo, hi, as_of, fetched_at = row
        ref = as_of or fetched_at
        try:
            age_h = (now - datetime.fromisoformat(ref)).total_seconds() / 3600
        except ValueError:
            age_h = None
        barges.append({
            "id": key, "name": meta["name"], "landings": meta["landings"],
            "bait": raw, "species": species, "minIn": lo, "maxIn": hi,
            "asOf": as_of, "checkedAt": fetched_at,
            "stale": age_h is None or age_h > STALE_HOURS,
        })
    return {
        "source": CREDIT,
        "note": "Bait can change many times per day; actual bait at the barge may differ.",
        "generatedAt": now.replace(microsecond=0).isoformat(),
        "staleAfterHours": STALE_HOURS,
        "barges": barges,
    }


def export(conn: sqlite3.Connection, out: Path = OUT) -> dict:
    payload = build_payload(conn)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload


def update(db_path: Path = DB_PATH, csv_text: str | None = None) -> str:
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    text = csv_text if csv_text is not None else fetch_csv()
    entries = parse_sheet(text)
    conn = sqlite3.connect(db_path)
    try:
        added = store(conn, entries, fetched_at)
        payload = export(conn)
    finally:
        conn.close()
    if not entries:
        log.warning("bait: no barges parsed; sheet layout may have changed")
    return f"bait: {len(entries)} barges parsed, {added} new, exported {len(payload['barges'])}"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--file", help="parse a saved CSV instead of fetching")
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args(argv)
    if a.export_only:
        conn = sqlite3.connect(a.db)
        try:
            p = export(conn)
        finally:
            conn.close()
        print(f"bait: exported {len(p['barges'])} barges")
        return 0
    text = Path(a.file).read_text(encoding="utf-8") if a.file else None
    print(update(Path(a.db), text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
