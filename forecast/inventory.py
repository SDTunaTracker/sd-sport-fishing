"""Read-only inventory for the forecasting MVP.

Prints a plain-text report to stdout, also written to
forecast/inventory_report.txt, and writes forecast/paired_days.csv.

Does not modify tracker.db, any JSON file, or scrape logic.
Uses src.dates.to_pacific_date for any UTC->calendar conversion so we
don't re-derive Pacific dates from UTC (the same fix as web/dates.js).
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.dates import PACIFIC, to_pacific_date  # noqa: E402

DB_PATH        = ROOT / "tracker.db"
TRACKED_PATH   = ROOT / "data" / "boat-mmsi.json"
VESSELS_PATH   = ROOT / "data" / "vessel_mmsi.json"
DISC_PATH      = ROOT / "data" / "ais-discoveries.json"
SNAPSHOT_PATH  = ROOT / "web" / "ais_positions.json"
OUT_DIR        = ROOT / "forecast"
CSV_PATH       = OUT_DIR / "paired_days.csv"
REPORT_PATH    = OUT_DIR / "inventory_report.txt"

SPECIES_COLS = (
    "bluefin", "yellowfin", "yellowtail", "dorado", "skipjack",
    "bigeye", "albacore", "rockfish", "sheephead", "calico_bass",
    "sand_bass", "halibut", "lingcod", "whitefish", "bonito",
    "barracuda", "white_sea_bass", "other_fish",
)


def parse_iso_utc(ts: str) -> datetime | None:
    """Parse the timestamp strings we see in the wild.

    Accepts:
      - ISO-8601:  '2026-07-11T17:41:10.954Z' or '...+00:00'
      - AISStream ships Go's default time.Format layout:
        '2026-07-11 17:41:10.954976559 +0000 UTC'
        (space separator, nanosecond precision, trailing ' UTC').

    We keep the raw string in the positions table (per the schema comment)
    and normalise here at the read-side so date bucketing still works.
    """
    if not ts:
        return None
    t = ts.strip()
    if t.endswith(" UTC"):
        t = t[:-4].rstrip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    # Go's "+0000" -> ISO "+00:00" (fromisoformat is strict about the colon).
    if len(t) >= 5 and t[-5] in "+-" and t[-4:].isdigit():
        t = t[:-2] + ":" + t[-2:]
    # Python can't parse nanoseconds; trim to microseconds (6 digits).
    if "." in t:
        head, _, tail = t.rpartition(".")
        # tail may look like '954976559+00:00' or '954976559'
        frac = ""
        rest = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                frac += ch
            else:
                rest = tail[i:]
                break
        t = f"{head}.{frac[:6]}{rest}"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d


def norm_name(n: str) -> str:
    """Strip trailing '(...)' disambiguator that boat-mmsi.json uses for dup names."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", n or "").strip()


def load_tracked() -> list[tuple[str, str]]:
    """Return [(mmsi, display_name), ...] for the SD sportfishing curated list."""
    data = json.loads(TRACKED_PATH.read_text())
    out: list[tuple[str, str]] = []
    for name, val in data.items():
        if name.startswith("_"):
            continue
        if isinstance(val, str) and val:
            out.append((val, name))
    return out


def load_vessels() -> dict:
    return json.loads(VESSELS_PATH.read_text()).get("vessels", {})


def load_discoveries() -> dict:
    return json.loads(DISC_PATH.read_text()).get("all_observed_vessels", {})


def load_snapshot() -> list:
    return json.loads(SNAPSHOT_PATH.read_text())


def main() -> int:
    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(s)
        print(s)

    tracked   = load_tracked()
    vessels   = load_vessels()
    all_obs   = load_discoveries()
    snapshot  = load_snapshot()

    now_pac = datetime.now(PACIFIC).isoformat(timespec="seconds")

    emit("=" * 78)
    emit("FORECASTING MVP  DATA INVENTORY")
    emit(f"Generated (Pacific): {now_pac}")
    emit(f"Repo:                {ROOT}")
    emit(f"Catch DB:            {DB_PATH.name}")
    emit("=" * 78)

    # AIS SECTION
    emit()
    emit(" AIS / VESSEL POSITIONS ")
    emit()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # Detect whether ais_push.py has ever run (table appears on first ingest).
    has_positions = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='positions'"
    ).fetchone() is not None

    total_positions = 0
    if has_positions:
        total_positions = con.execute("SELECT COUNT(*) FROM positions").fetchone()[0]

    emit(f"Total stored position rows: {total_positions:,}")
    if not has_positions:
        emit("  positions table does not exist yet  scripts/ais_push.py has not been run.")
    elif total_positions == 0:
        emit("  positions table exists but is empty  live ingest has not landed rows yet.")
    else:
        emit("  Rows written by scripts/ais_push.py (source='aisstream'). CF Worker KV")
        emit("  snapshot still lives at expirationTtl=600 (10 min) but is no longer the")
        emit("  system of record  the positions table is.")
    emit()

    # Sog/cog completeness  loiter detection later depends on these.
    speed_stats = None
    if has_positions and total_positions:
        r = con.execute(
            "SELECT COUNT(*) tot, "
            "  SUM(CASE WHEN sog IS NULL THEN 1 ELSE 0 END) sog_null, "
            "  SUM(CASE WHEN cog IS NULL THEN 1 ELSE 0 END) cog_null "
            "FROM positions"
        ).fetchone()
        speed_stats = (r['tot'], r['sog_null'], r['cog_null'])
        emit(f"Speed/course completeness: sog non-null {r['tot']-r['sog_null']:,}/{r['tot']:,}"
             f"   cog non-null {r['tot']-r['cog_null']:,}/{r['tot']:,}")
        emit("  (nulls mean the AISStream message omitted the field  not the same as 0.0)")
    else:
        emit("Speed/course capture:")
        emit("  ais_push.py:104 captures 'sog' (speed over ground) and 'cog' (course over")
        emit("  ground) on every PositionReport / StandardClassBPositionReport, so rows")
        emit("  land with real values once ingest kicks in. Nothing missing at ingest.")
    emit()

    # Per-MMSI stats  date range, row count, largest gap.
    emit("Per-MMSI position stats:")
    emit(f"  {'MMSI':<11} {'boat':<22} {'rows':>8} {'first_ts (UTC)':<25} {'last_ts (UTC)':<25} {'max_gap':>10}")
    emit("  " + "-" * 102)
    per_mmsi_rows = 0
    for mmsi, name in sorted(tracked, key=lambda kv: kv[1].lower()):
        if not has_positions:
            emit(f"  {mmsi:<11} {name[:22]:<22} {0:>8}  (no positions table)")
            continue
        try:
            mm_int = int(mmsi)
        except ValueError:
            continue
        rows_ = con.execute(
            "SELECT COUNT(*) n, MIN(timestamp) mn, MAX(timestamp) mx "
            "FROM positions WHERE mmsi = ?", (mm_int,)
        ).fetchone()
        n = rows_['n'] or 0
        if n == 0:
            emit(f"  {mmsi:<11} {name[:22]:<22} {0:>8}  {'':<25} {'':<25} {'':>10}")
            continue
        per_mmsi_rows += n
        # Largest gap: max difference between consecutive timestamps for this mmsi.
        ts_list = [r['timestamp'] for r in con.execute(
            "SELECT timestamp FROM positions WHERE mmsi = ? ORDER BY timestamp", (mm_int,)
        )]
        max_gap_s = 0.0
        if len(ts_list) >= 2:
            prev = parse_iso_utc(ts_list[0])
            for t in ts_list[1:]:
                cur_dt = parse_iso_utc(t)
                if prev is not None and cur_dt is not None:
                    delta = (cur_dt - prev).total_seconds()
                    if delta > max_gap_s:
                        max_gap_s = delta
                prev = cur_dt
        # Format gap compactly.
        if max_gap_s >= 86400:
            gap_str = f"{max_gap_s/86400:.1f}d"
        elif max_gap_s >= 3600:
            gap_str = f"{max_gap_s/3600:.1f}h"
        elif max_gap_s >= 60:
            gap_str = f"{max_gap_s/60:.1f}m"
        else:
            gap_str = f"{max_gap_s:.0f}s"
        emit(f"  {mmsi:<11} {name[:22]:<22} {n:>8} {rows_['mn'][:25]:<25} {rows_['mx'][:25]:<25} {gap_str:>10}")
    emit()

    # Distinct (mmsi, Pacific-date) coverage from the positions table.
    coverage_count = 0
    if has_positions and total_positions:
        pac_dates = set()
        for r in con.execute("SELECT mmsi, timestamp FROM positions"):
            dt = parse_iso_utc(r['timestamp'])
            if dt is None:
                continue
            pac_dates.add((r['mmsi'], to_pacific_date(dt).isoformat()))
        coverage_count = len(pac_dates)
    emit(f"Distinct (MMSI, Pacific-date) with position coverage: {coverage_count}")
    emit("  (bucketed via src.dates.to_pacific_date  same helper as web/dates.js)")

    # Last-seen proxy from ais-discoveries.json kept for context (still useful
    # while the positions table is thin).
    emit()
    emit("Last-seen per tracked MMSI (from data/ais-discoveries.json, one entry per boat):")
    emit(f"  {'MMSI':<11} {'boat':<22} {'landing':<28} {'last_seen (Pac)':<12}")
    emit("  " + "-" * 74)
    tracked_last_seen: dict[str, str | None] = {}
    for mmsi, name in sorted(tracked, key=lambda kv: kv[1].lower()):
        rec = all_obs.get(mmsi, {})
        last = rec.get("last_seen") or ""
        landing = vessels.get(mmsi, {}).get("landing", "?")
        pdate = ""
        dt = parse_iso_utc(last)
        if dt is not None:
            pdate = to_pacific_date(dt).isoformat()
            tracked_last_seen[mmsi] = pdate
        else:
            tracked_last_seen[mmsi] = None
        emit(f"  {mmsi:<11} {name[:22]:<22} {landing[:28]:<28} {pdate:<12}")
    con.close()
    emit()

    have_last = sum(1 for v in tracked_last_seen.values() if v)
    emit(f"Distinct (tracked boat, Pacific-date) via last-seen fallback: {have_last} / {len(tracked)}")

    # CATCH SECTION
    emit()
    emit(" CATCH DB (tracker.db.trips) ")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    _ = speed_stats  # kept for future callers; not printed twice
    row = con.execute(
        "SELECT MIN(date) mn, MAX(date) mx, COUNT(*) n, COUNT(DISTINCT boat) bcount "
        "FROM trips"
    ).fetchone()
    emit()
    emit(f"Trip rows:          {row['n']:,}")
    emit(f"Date range:         {row['mn']}  {row['mx']}")
    emit(f"Distinct boats:     {row['bcount']}")
    bdays = con.execute(
        "SELECT COUNT(*) n FROM (SELECT DISTINCT date, lower(boat) FROM trips)"
    ).fetchone()["n"]
    emit(f"Distinct (boat, Pacific-date) catch records: {bdays:,}")
    emit("  (trips.date is stamped by landings on the Pacific business day)")
    emit()

    emit("Tracked MMSI to catch mapping (case-insensitive on the normalised name):")
    emit(f"  {'MMSI':<11} {'tracked name':<20} {'catch rows':>10} {'catch-days':>11}  landing(s)")
    emit("  " + "-" * 76)
    catch_days_by_mmsi: dict[str, int] = {}
    for mmsi, name in sorted(tracked, key=lambda kv: kv[1].lower()):
        base = norm_name(name)
        r = con.execute(
            "SELECT COUNT(*) n, COUNT(DISTINCT date) d, "
            "GROUP_CONCAT(DISTINCT landing) ls "
            "FROM trips WHERE lower(boat) = lower(?)",
            (base,),
        ).fetchone()
        n = r["n"] or 0
        d = r["d"] or 0
        landings = r["ls"] or ""
        catch_days_by_mmsi[mmsi] = d
        emit(f"  {mmsi:<11} {base[:20]:<20} {n:>10} {d:>11}  {landings}")
    emit()

    # Seasonal breakdown of overall catch coverage.
    emit("Catch boat-days by year-month (all trips, for seasonal context):")
    ym_rows = con.execute(
        "SELECT substr(date,1,7) ym, "
        "COUNT(*) OVER () _tot, "
        "COUNT(DISTINCT boat || '|' || date) bd "
        "FROM trips GROUP BY ym ORDER BY ym"
    ).fetchall()
    for r in ym_rows:
        emit(f"  {r['ym']}  boat-days: {r['bd']:>6}")

    # PAIRED BOAT-DAYS  keyed off the real positions table (not the
    # last-seen fallback in ais-discoveries.json).
    emit()
    emit(" PAIRED (AIS x CATCH) BOAT-DAYS ")
    emit()

    # Bucket every stored position into (mmsi, Pacific-date) with per-bucket
    # stats: row count + whether any row in that bucket has non-null sog.
    from collections import defaultdict as _dd
    pos_stats: dict[tuple[int, str], dict] = _dd(lambda: {"n": 0, "sog_nn": 0})
    if has_positions and total_positions:
        for r in con.execute("SELECT mmsi, timestamp, sog FROM positions"):
            dt = parse_iso_utc(r["timestamp"])
            if dt is None:
                continue
            key = (r["mmsi"], to_pacific_date(dt).isoformat())
            pos_stats[key]["n"] += 1
            if r["sog"] is not None:
                pos_stats[key]["sog_nn"] += 1

    tracked_by_mmsi_int: dict[int, tuple[str, str]] = {}
    for mmsi_s, name in tracked:
        try:
            tracked_by_mmsi_int[int(mmsi_s)] = (mmsi_s, name)
        except ValueError:
            continue

    paired_rows: list[dict] = []
    for (mm_int, pdate), stats in sorted(pos_stats.items()):
        if mm_int not in tracked_by_mmsi_int:
            continue
        mmsi_s, name = tracked_by_mmsi_int[mm_int]
        base = norm_name(name)
        catches = con.execute(
            "SELECT bluefin, yellowfin, yellowtail, dorado, skipjack, bigeye, albacore, "
            "  rockfish, sheephead, calico_bass, sand_bass, halibut, lingcod, whitefish, "
            "  bonito, barracuda, white_sea_bass, other_fish, other_species_json, landing "
            "FROM trips WHERE date = ? AND lower(boat) = lower(?)",
            (pdate, base),
        ).fetchall()
        if not catches:
            continue
        species: dict[str, int] = {}
        for row_ in catches:
            for k in SPECIES_COLS:
                v = row_[k] or 0
                if v:
                    species[k] = species.get(k, 0) + v
            try:
                other = json.loads(row_["other_species_json"] or "{}")
                for k, v in other.items():
                    if isinstance(v, (int, float)) and v:
                        species[k] = species.get(k, 0) + int(v)
            except Exception:
                pass
        paired_rows.append({
            "boat": base,
            "mmsi": mmsi_s,
            "date": pdate,
            "n_positions": stats["n"],
            "has_speed_course": "true" if stats["sog_nn"] > 0 else "false",
            "catch_species_json": json.dumps(species, separators=(",", ":")),
        })

    emit(f"Paired boat-days (positions AND catch, tracked MMSIs only): {len(paired_rows)}")
    if len(paired_rows) == 0 and (not has_positions or total_positions == 0):
        emit("  Positions table is empty  no pairing possible until live ingest lands")
        emit("  rows and/or Marine Cadastre backfill runs.")
    elif len(paired_rows) == 0:
        emit("  Positions table has rows, but none of the tracked-MMSI Pacific-dates")
        emit("  intersect the catch table on the same day. Check MMSI list / date range.")
    emit()

    by_month = Counter(r["date"][:7] for r in paired_rows)
    emit("Paired boat-days by year-month:")
    if by_month:
        for ym_, cnt in sorted(by_month.items()):
            emit(f"  {ym_}  paired: {cnt}")
    else:
        emit("  (none)")

    # Write CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["boat", "mmsi", "date", "n_positions", "has_speed_course", "catch_species_json"]
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in paired_rows:
            w.writerow(r)
    emit()
    emit(f"Wrote {CSV_PATH.relative_to(ROOT)}  ({len(paired_rows)} data rows)")

    # Recommendation
    emit()
    emit(" RECOMMENDATION ")
    emit("Bank AIS history first  the modeling MVP is data-starved.")
    emit("  1. Add a positions table to tracker.db:")
    emit("       (mmsi TEXT, ts_utc TEXT, lat REAL, lng REAL, sog REAL, cog REAL,")
    emit("        heading REAL, source TEXT).  Index (mmsi, ts_utc).")
    emit("  2. In scripts/ais_push.py after collect(), also INSERT each new position")
    emit("     into that table before write_local()/push_to_worker(). sog/cog are")
    emit("     already captured at line 104  nothing else to wire.")
    emit("  3. Optional belt-and-suspenders: cron the CF Worker /vessels response into")
    emit("     the same table (needs KV TTL bumped from 600s so nothing is lost).")
    emit("Re-run this inventory after 1-2 seasons of banked history to check whether")
    emit("paired boat-days per season crosses the useful-training threshold.")

    con.close()
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n(report also written to {REPORT_PATH.relative_to(ROOT)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
