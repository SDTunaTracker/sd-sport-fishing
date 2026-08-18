"""Backfill AIS positions from the NOAA Marine Cadastre archive into
tracker.db.positions. One (year, month) per invocation.

Archive layout (verified against real HEAD requests):
  2015 - 2024  ->  https://coast.noaa.gov/htdata/CMSP/AISDataHandler/YYYY/
                   AIS_YYYY_MM_DD.zip     (ZIP with one CSV inside)
  2025 - now   ->  https://coast.noaa.gov/htdata/CMSP/AISDataHandler/YYYY/
                   ais-YYYY-MM-DD.csv.zst (zstd-compressed CSV)

Files are nationwide (no UTM zoning). Uncompressed a day is roughly 1-4 GB,
so we stream decompression and filter row-by-row against a target MMSI list.

CSV schema is version-dependent:
  2015-2024:  MMSI, BaseDateTime, LAT, LON, SOG, COG, Heading, VesselName, ...
  2025+   :   mmsi, base_date_time, latitude, longitude, sog, cog, heading, ...
We normalise every column name to lowercase on read and check both LAT/latitude
and BaseDateTime/base_date_time so one loader handles either era.

Notes:
  * BaseDateTime is UTC per NOAA. We append 'Z' before insert so the timestamp
    round-trips through inventory.py's parser without local-tz ambiguity.
  * SOG / COG land as REAL or NULL -- never a synthesized 0.0.
  * INSERT OR IGNORE dedupes on UNIQUE(mmsi, timestamp). Re-running the same
    (year, month) is safe.
  * source='marine_cadastre' keeps archive rows separate from source='aisstream'
    rows so downstream queries can pick an era.

Usage:
    py forecast/backfill_marine_cadastre.py --year 2025 --month 8
    py forecast/backfill_marine_cadastre.py --year 2024 --month 9 \\
        --mmsi-file data/vessel_mmsi.json      # wider 64-vessel set
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
import tempfile
import time
import zipfile
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH    = ROOT / "tracker.db"
BASE_URL   = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"
SOURCE_TAG = "marine_cadastre"

# Positions schema is defined inline so the loader stands on its own -- no
# import from scripts/ais_push.py required. Migration is idempotent, safe to
# run every invocation.
_POSITIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    mmsi      INTEGER NOT NULL,
    timestamp TEXT    NOT NULL,
    lat       REAL    NOT NULL,
    lon       REAL    NOT NULL,
    sog       REAL,
    cog       REAL,
    source    TEXT    NOT NULL,
    UNIQUE(mmsi, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_positions_mmsi_ts ON positions(mmsi, timestamp);
"""


def open_positions_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_POSITIONS_SCHEMA)
    conn.commit()
    return conn


def load_mmsi_targets(path: Path) -> dict[int, str]:
    """Load target MMSIs from a JSON config file.

    Auto-detects two shapes we have on disk:
      boat-mmsi.json    -> {"BoatName": "3388xxxxxxx", ...}  ('_' keys skipped)
      vessel_mmsi.json  -> {"vessels": {"338xxxxxxx": {"name": "...", ...}}}
    """
    raw = json.loads(path.read_text())
    out: dict[int, str] = {}
    if isinstance(raw, dict) and isinstance(raw.get("vessels"), dict):
        for m, v in raw["vessels"].items():
            try:
                out[int(m)] = v.get("name", m) if isinstance(v, dict) else str(v)
            except (TypeError, ValueError):
                continue
    else:
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            if isinstance(v, str) and v.isdigit():
                out[int(v)] = k
    return out


def parse_day_spec(spec: str, y: int, m: int) -> set[int]:
    """'03,04,05' or '18-31,25' -> {3,4,5} / {18,19,...,31}. Silently drops
    days outside the actual month length so callers can freely ask for '31'."""
    _, last = monthrange(y, m)
    out: set[int] = set()
    for tok in (t.strip() for t in spec.split(",")):
        if not tok:
            continue
        if "-" in tok:
            lo_s, hi_s = tok.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
        else:
            lo = hi = int(tok)
        for d in range(lo, hi + 1):
            if 1 <= d <= last:
                out.add(d)
    return out


def build_daily_urls(
    y: int, m: int, days_filter: set[int] | None = None,
) -> list[tuple[date, str, bool]]:
    """Return (date, url, is_zst) for every day of the month. If days_filter
    is set, only include days present in it (used for surgical gap-fills)."""
    _, last_day = monthrange(y, m)
    result: list[tuple[date, str, bool]] = []
    for d in range(1, last_day + 1):
        if days_filter is not None and d not in days_filter:
            continue
        dt = date(y, m, d)
        if y >= 2025:
            fname = f"ais-{y:04d}-{m:02d}-{d:02d}.csv.zst"
            zst = True
        else:
            fname = f"AIS_{y:04d}_{m:02d}_{d:02d}.zip"
            zst = False
        result.append((dt, f"{BASE_URL}/{y}/{fname}", zst))
    return result


def stream_zip_rows(url: str) -> Iterable[dict]:
    """Materialise the ZIP to a temp file (central directory lives at the
    tail so true streaming is impossible), then stream-read the CSV inside.
    Temp file is deleted before the next day's download starts."""
    with tempfile.NamedTemporaryFile(prefix="mc_", suffix=".zip", delete=False) as tf:
        tmp_path = Path(tf.name)
    try:
        with requests.get(url, stream=True, timeout=(30, 600)) as r:
            r.raise_for_status()
            with tmp_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                    if chunk:
                        f.write(chunk)
        with zipfile.ZipFile(tmp_path) as zf:
            csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
            with zf.open(csv_name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                yield from csv.DictReader(text)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def stream_zst_rows(url: str) -> Iterable[dict]:
    """Stream HTTP body -> zstd stream_reader -> CSV rows. No disk hit."""
    import zstandard as zstd
    with requests.get(url, stream=True, timeout=(30, 600)) as r:
        r.raise_for_status()
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(r.raw) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8", newline="")
            yield from csv.DictReader(text)


def parse_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _flush(conn: sqlite3.Connection, batch: list) -> tuple[int, int]:
    """Insert a batch of position tuples. Returns (inserted, duplicates)."""
    before = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    conn.executemany(
        "INSERT OR IGNORE INTO positions "
        "(mmsi, timestamp, lat, lon, sog, cog, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        batch,
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    ins = after - before
    return ins, len(batch) - ins


def process_day_with_retry(
    conn: sqlite3.Connection,
    day: date,
    url: str,
    is_zst: bool,
    targets: dict[int, str],
    retries: int = 3,
) -> tuple[int, int, int, int, bool]:
    """Wrap process_day with exponential backoff on transient network errors.

    NOAA's older .zip archive host drops connections mid-download under
    sustained load -- one such drop cost us ~100 days on the 2020-2025 sweep.
    Retries here are for network failures only; 404 is still handled inline
    inside process_day (no point retrying a genuinely missing file).

    Rows partially inserted before a mid-stream failure are safe:
    INSERT OR IGNORE against UNIQUE(mmsi, timestamp) dedupes them on the
    retry pass.
    """
    delays = [5, 15, 45]  # seconds between attempts 1->2, 2->3, 3->4
    net_errors = (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )
    for attempt in range(retries + 1):
        try:
            return process_day(conn, day, url, is_zst, targets)
        except net_errors as e:
            if attempt >= retries:
                raise
            delay = delays[min(attempt, len(delays) - 1)]
            print(f"    retry {attempt + 1}/{retries} after "
                  f"{type(e).__name__}: sleeping {delay}s", flush=True)
            time.sleep(delay)
    raise RuntimeError("unreachable")  # for type checker


def process_day(
    conn: sqlite3.Connection,
    day: date,
    url: str,
    is_zst: bool,
    targets: dict[int, str],
) -> tuple[int, int, int, int, bool]:
    """Returns (rows_seen, rows_matched, rows_inserted, rows_dupes, missing_404).

    missing_404 is True when the archive doesn't have that day (some early or
    late edges of the year skip days). Loader keeps going.
    """
    fname = url.rsplit("/", 1)[-1]
    print(f"  {day.isoformat()}  {fname} ...", flush=True)
    t0 = time.time()

    seen = matched = inserted = dupes = 0
    batch: list[tuple] = []
    BATCH = 5000

    reader_iter = stream_zst_rows(url) if is_zst else stream_zip_rows(url)
    try:
        for raw_row in reader_iter:
            seen += 1
            # 2024- files ship PascalCase headers ('MMSI', 'BaseDateTime', 'LAT');
            # 2025+ files ship snake_case ('mmsi', 'base_date_time', 'latitude').
            # Lowercase once and look up either alias.
            row = {(k or "").lower(): v for k, v in raw_row.items()}
            try:
                mm = int(row["mmsi"])
            except (KeyError, ValueError, TypeError):
                continue
            if mm not in targets:
                continue
            lat = parse_float(row.get("lat") or row.get("latitude"))
            lon = parse_float(row.get("lon") or row.get("longitude"))
            if lat is None or lon is None:
                continue
            ts_raw = (row.get("basedatetime") or row.get("base_date_time") or "").strip()
            if not ts_raw:
                continue
            # Archive omits TZ; NOAA states UTC. Append 'Z' so inventory.py's
            # parser (and any consumer) treats it as UTC unambiguously.
            ts = ts_raw + "Z" if not ts_raw.endswith("Z") else ts_raw
            batch.append((
                mm, ts, lat, lon,
                parse_float(row.get("sog")),
                parse_float(row.get("cog")),
                SOURCE_TAG,
            ))
            matched += 1
            if len(batch) >= BATCH:
                ins, dup = _flush(conn, batch)
                inserted += ins
                dupes += dup
                batch.clear()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print(f"    (404 -- file missing, skipping)")
            return seen, matched, inserted, dupes, True
        raise
    if batch:
        ins, dup = _flush(conn, batch)
        inserted += ins
        dupes += dup

    dt = time.time() - t0
    print(f"    seen={seen:>10,}  matched={matched:>5,}  inserted={inserted:>5,}"
          f"  dup_skipped={dupes:>5,}  ({dt:>5.1f}s)")
    return seen, matched, inserted, dupes, False


def warn_if_overlap(conn: sqlite3.Connection, first: date, last: date) -> None:
    """Print a warning (still proceed) if the backfill window overlaps the
    live-ingest window. Overlap is possible when the archive gets published
    for months already covered by live persistence."""
    r = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM positions "
        "WHERE source = 'aisstream'"
    ).fetchone()
    if r is None or r[0] is None:
        return
    live_first = r[0][:10].replace(" ", "T")  # 'YYYY-MM-DD' from either format
    if live_first <= last.isoformat():
        print()
        print("  WARNING: backfill window overlaps live-ingest window.")
        print(f"    live-ingest first stored ts: {r[0]}")
        print(f"    backfill window:             {first} .. {last}")
        print("    Loading both; sources stay separate via the 'source' column.")
        print("    Audit later with:")
        print("      SELECT * FROM positions")
        print(f"       WHERE source='marine_cadastre'")
        print(f"         AND substr(timestamp,1,10) >= '{live_first}';")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--year",       type=int, required=True)
    ap.add_argument("--month",      type=int, required=True)
    ap.add_argument("--mmsi-file",  type=str,
                    default=str(ROOT / "data" / "boat-mmsi.json"),
                    help="JSON file listing target MMSIs (default: 14 curated boats)")
    ap.add_argument("--limit-days", type=int, default=0,
                    help="If >0, process only the first N days of the month (smoke test)")
    ap.add_argument("--days", default="",
                    help="Only process these day-of-month values, e.g. "
                         "'13,20,21' or '18-31,25'. Default: all days.")
    args = ap.parse_args()

    if not (1 <= args.month <= 12):
        print(f"ERROR: month must be 1..12 (got {args.month})", file=sys.stderr)
        return 2
    if args.year < 2015 or args.year > 2030:
        print(f"ERROR: year {args.year} outside supported range", file=sys.stderr)
        return 2

    mmsi_path = Path(args.mmsi_file)
    if not mmsi_path.is_absolute():
        mmsi_path = ROOT / mmsi_path
    targets = load_mmsi_targets(mmsi_path)
    if not targets:
        print(f"ERROR: no target MMSIs loaded from {mmsi_path}", file=sys.stderr)
        return 2

    days_filter = parse_day_spec(args.days, args.year, args.month) if args.days else None
    urls = build_daily_urls(args.year, args.month, days_filter)
    if args.limit_days > 0:
        urls = urls[: args.limit_days]
    if not urls:
        print(f"ERROR: no days to process for {args.year}-{args.month:02d} "
              f"(--days filter left empty set)", file=sys.stderr)
        return 2

    first_day, last_day = urls[0][0], urls[-1][0]
    print(f"Marine Cadastre backfill  {first_day} .. {last_day}")
    print(f"Target MMSIs: {len(targets)} from {mmsi_path.relative_to(ROOT)}")
    print(f"Days to process: {len(urls)}")
    print()

    conn = open_positions_db()
    try:
        warn_if_overlap(conn, first_day, last_day)

        # Snapshot pre-run counters so we can report the delta.
        pre_total   = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        pre_by_src  = dict(conn.execute(
            "SELECT source, COUNT(*) FROM positions GROUP BY source"
        ).fetchall())
        print(f"positions rows before run: total={pre_total}  by_source={pre_by_src}")
        print()

        tot_seen = tot_matched = tot_ins = tot_dup = 0
        skipped_days: list[str] = []
        for day, url, is_zst in urls:
            try:
                seen, matched, inserted, dupes, missing = process_day_with_retry(
                    conn, day, url, is_zst, targets
                )
                if missing:
                    skipped_days.append(day.isoformat())
                    continue
                tot_seen    += seen
                tot_matched += matched
                tot_ins     += inserted
                tot_dup     += dupes
            except KeyboardInterrupt:
                print("\ninterrupted; partial progress is committed")
                raise
            except Exception as e:
                print(f"    FAILED: {type(e).__name__}: {e}")
                skipped_days.append(day.isoformat() + " (error)")

        post_total  = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        post_by_src = dict(conn.execute(
            "SELECT source, COUNT(*) FROM positions GROUP BY source"
        ).fetchall())

        print()
        print("=" * 68)
        print("BACKFILL SUMMARY")
        print("=" * 68)
        print(f"days processed         : {len(urls) - len(skipped_days)} / {len(urls)}")
        if skipped_days:
            print(f"days skipped (missing) : {skipped_days}")
        print(f"total rows streamed    : {tot_seen:,}")
        print(f"rows matched MMSI      : {tot_matched:,}")
        print(f"rows inserted          : {tot_ins:,}")
        print(f"rows skipped duplicate : {tot_dup:,}")
        print()
        print(f"positions before       : total={pre_total:,}  by_source={pre_by_src}")
        print(f"positions after        : total={post_total:,}  by_source={post_by_src}")

        # Quick data-quality peek: source tag, non-null lat/lon, sog nullability.
        r = conn.execute(
            "SELECT COUNT(*) tot, "
            "  SUM(CASE WHEN lat IS NULL OR lon IS NULL THEN 1 ELSE 0 END) missing_ll, "
            "  SUM(CASE WHEN sog IS NULL THEN 1 ELSE 0 END) sog_null, "
            "  SUM(CASE WHEN cog IS NULL THEN 1 ELSE 0 END) cog_null "
            "FROM positions WHERE source = 'marine_cadastre'"
        ).fetchone()
        if r and r[0]:
            print()
            print("marine_cadastre rows:")
            print(f"  total          : {r[0]:,}")
            print(f"  missing lat/lon: {r[1]}  (should be 0)")
            print(f"  sog non-null   : {r[0] - r[2]:,} / {r[0]:,}")
            print(f"  cog non-null   : {r[0] - r[3]:,} / {r[0]:,}")
            print()
            print("sample rows:")
            for row in conn.execute(
                "SELECT mmsi, timestamp, lat, lon, sog, cog, source "
                "FROM positions WHERE source='marine_cadastre' "
                "ORDER BY timestamp LIMIT 5"
            ):
                print(f"  {row}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
