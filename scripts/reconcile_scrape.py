"""Read-only scrape reconciliation diagnostic.

For the target Pacific date, re-fetches every source the scraper hits and
counts where rows are dropped: raw HTML rows → parsed → filtered → stored.
Picks 5 stored trips and prints the raw source block beside the parsed
object so the user can eyeball whether the right fields were grabbed.

Usage:
    python -m scripts.reconcile_scrape                # today (Pacific)
    python -m scripts.reconcile_scrape 2026-06-21     # explicit date

No DB writes, no source mutations. Safe to run anytime.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import parse as P
from src.dates import pacific_today
from src.scrape import (
    SOURCES,
    _extract_rows,
    _fetch,
    _harvest_narrative_reports,
    _extract_text_blocks,
    _fetch_optional,
    _SKIP_FIRST_CELL,
    _BOAT_NAME_BLACKLIST,
    parse_page,
)

DB_PATH = ROOT / "tracker.db"


# ── Reconciliation per source ─────────────────────────────────────────────────

def reconcile_source(src, target_date: _date, known_boats: list[str]) -> dict:
    """Re-fetch one source and account for every raw row's fate.

    Returns a dict with raw_count, parsed_ok, parse_failed (list), filtered_out
    (list with reason), stored_count, plus the raw rows + parsed trips for
    later side-by-side sampling.
    """
    result: dict[str, Any] = {
        "src": src,
        "fetch_error": None,
        "html_size": 0,
        "raw_rows": [],
        "page_date": None,
        "parsed_ok": [],
        "parse_failed": [],
        "filtered_out": [],
        "narrative_new": [],
        "narrative_fetched_urls": [],
        "stored_db": [],
    }

    # ── Fetch ─────────────────────────────────────────────────────────────────
    try:
        html = _fetch(src)
        result["html_size"] = len(html)
    except Exception as exc:
        result["fetch_error"] = f"{type(exc).__name__}: {exc}"
        return result

    # ── Step 1: raw row extraction (BEFORE any filtering) ─────────────────────
    raw_rows, page_date = _extract_rows(html)
    result["raw_rows"] = raw_rows
    result["page_date"] = page_date

    # ── Step 2: walk parse_page's logic, attributing every drop ──────────────
    for r in raw_rows:
        # Replicate parse_page's date fallback (we want to know WHY each row
        # was kept/dropped — not mutate the scrape).
        row_date = r["date"]
        if row_date is None:
            row_date = target_date  # mirror parse_page fallback for the target

        # Filter 1: date window (silent skip in production)
        if row_date != target_date:
            result["filtered_out"].append({
                "reason":  "date_window",
                "detail":  f"row date={r['date']} != target={target_date}",
                "boat":    r["boat"],
                "raw":     r,
            })
            continue

        # Filter 2: trip-length parse
        try:
            length_bucket, length_days = P.parse_trip_length(r["trip_type_raw"])
        except Exception as exc:
            result["parse_failed"].append({
                "stage":   "parse_trip_length",
                "error":   f"{type(exc).__name__}: {exc}",
                "boat":    r["boat"],
                "raw":     r,
            })
            continue
        if length_bucket is None or length_days is None:
            result["filtered_out"].append({
                "reason":  "trip_length_unparsable",
                "detail":  f"trip_type_raw={r['trip_type_raw']!r}",
                "boat":    r["boat"],
                "raw":     r,
            })
            continue

        # Filter 3: anglers
        try:
            anglers = P.parse_anglers(r["anglers_text"])
        except Exception as exc:
            result["parse_failed"].append({
                "stage":   "parse_anglers",
                "error":   f"{type(exc).__name__}: {exc}",
                "boat":    r["boat"],
                "raw":     r,
            })
            continue
        if not anglers or anglers <= 0:
            result["filtered_out"].append({
                "reason":  "anglers_missing_or_zero",
                "detail":  f"anglers_text={r['anglers_text']!r}",
                "boat":    r["boat"],
                "raw":     r,
            })
            continue

        # Filter 4: fish-count parse never raises in current implementation,
        # but wrap defensively.
        try:
            tracked, other = P.parse_fish_counts(r["fish_count_text"])
        except Exception as exc:
            result["parse_failed"].append({
                "stage":  "parse_fish_counts",
                "error":  f"{type(exc).__name__}: {exc}",
                "boat":   r["boat"],
                "raw":    r,
            })
            continue

        result["parsed_ok"].append({
            "raw": r,
            "parsed": {
                "boat":          r["boat"],
                "date":          row_date.isoformat(),
                "trip_length":   length_bucket,
                "trip_length_days": length_days,
                "anglers":       anglers,
                "tracked":       {k: v for k, v in tracked.items() if v > 0},
                "other":         other,
            },
        })

    # ── Step 3: narrative-text harvest (separate path; fills + new trips) ────
    #           This re-uses the production code so we report what it actually
    #           does. Fetched URLs are recorded so missing/404 supplementary
    #           pages can be flagged.
    if src.main_url or src.news_url:
        for url in [u for u in [src.main_url, src.news_url] if u]:
            try:
                html_extra = _fetch_optional(url)
                ok = html_extra is not None
                blocks = len(_extract_text_blocks(html_extra)) if ok else 0
                result["narrative_fetched_urls"].append({
                    "url": url, "ok": ok, "text_blocks": blocks,
                })
            except Exception as exc:
                result["narrative_fetched_urls"].append({
                    "url": url, "ok": False, "error": str(exc), "text_blocks": 0,
                })
        try:
            narrative = _harvest_narrative_reports(
                src,
                [p["parsed"] for p in result["parsed_ok"]],  # current parsed_ok as 'today's trips'
                known_boats,
                target_date,
            )
            result["narrative_new"] = narrative
        except Exception as exc:
            result["narrative_error"] = f"{type(exc).__name__}: {exc}"

    # ── Step 4: what's actually stored in the DB for this source/date ────────
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        result["stored_db"] = list(conn.execute(
            "SELECT id, boat, trip_length, anglers, trophy_count, source, "
            "is_preliminary, bluefin, yellowfin, yellowtail, dorado, skipjack, "
            "bigeye, albacore, other_species_json, full_catch, source_url, "
            "written_text "
            "FROM trips WHERE landing=? AND date=? ORDER BY boat, trip_length",
            (src.name, target_date.isoformat()),
        ).fetchall())

    return result


# ── Output helpers ────────────────────────────────────────────────────────────

def _truncate(s: str | None, n: int = 120) -> str:
    if s is None:
        return ""
    s = str(s).replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[:n - 3] + "..."


def _print_block(result: dict) -> None:
    src = result["src"]
    sep = "─" * 78
    print(f"\n{sep}")
    print(f" {src.name}  [{src.region}]")
    print(f"   url:    {src.url}")
    if src.main_url:
        print(f"   main:   {src.main_url}")
    if src.news_url:
        print(f"   news:   {src.news_url}")
    print(sep)

    if result["fetch_error"]:
        print(f"   !! FETCH FAILED: {result['fetch_error']}")
        return

    raw   = len(result["raw_rows"])
    ok    = len(result["parsed_ok"])
    failed = len(result["parse_failed"])
    filt  = len(result["filtered_out"])
    stored = len(result["stored_db"])
    narr  = len(result["narrative_new"])

    print(f"   HTML size:      {result['html_size']:,} bytes")
    print(f"   page_date:      {result['page_date']}")
    print(f"   rawCount:       {raw}        rows from fish-count table(s)")
    print(f"   parsedOk:       {ok}")
    print(f"   parseFailed:    {failed}     (caught exceptions during parse)")
    print(f"   filteredOut:    {filt}     (dropped by a filter)")
    print(f"   storedInDB:     {stored}    (for this source on {result.get('page_date') or 'target'})")
    if narr:
        print(f"   narrative_new:  {narr}    (text-only fallbacks, separate path)")

    # Invariants — flag if broken
    rule1 = (ok + failed + filt) == raw
    if not rule1:
        print(f"   !! INVARIANT BROKEN: parsedOk({ok}) + parseFailed({failed}) + filteredOut({filt}) = {ok+failed+filt} != rawCount({raw})")

    # Parse failures
    if result["parse_failed"]:
        print()
        print("   --- PARSE FAILURES (silently skipped in production) ---")
        for pf in result["parse_failed"]:
            print(f"     stage={pf['stage']}  boat={pf['boat']!r}  error={pf['error']}")
            print(f"       raw: {_truncate(pf['raw'])}")

    # Filtered-out, grouped by reason
    if result["filtered_out"]:
        by_reason: dict[str, list] = {}
        for f in result["filtered_out"]:
            by_reason.setdefault(f["reason"], []).append(f)
        print()
        print("   --- FILTERED OUT ---")
        for reason, items in sorted(by_reason.items()):
            print(f"     [{reason}] x{len(items)}")
            for f in items[:8]:  # cap output
                print(f"       - boat={f['boat']!r}  {f['detail']}")
                print(f"           raw={_truncate(f['raw'])}")
            if len(items) > 8:
                print(f"       ... and {len(items) - 8} more")

    # Narrative URL fetches
    if result["narrative_fetched_urls"]:
        print()
        print("   --- narrative URL fetches ---")
        for u in result["narrative_fetched_urls"]:
            status = "OK" if u["ok"] else "FAIL"
            blocks = u.get("text_blocks", 0)
            err = f"  error={u['error']}" if u.get("error") else ""
            print(f"     [{status}]  {u['url']}  text_blocks={blocks}{err}")


def _print_totals(results: list[dict]) -> None:
    print("\n" + "═" * 78)
    print(" TOTALS")
    print("═" * 78)
    raw = sum(len(r["raw_rows"]) for r in results if not r["fetch_error"])
    ok = sum(len(r["parsed_ok"]) for r in results if not r["fetch_error"])
    failed = sum(len(r["parse_failed"]) for r in results if not r["fetch_error"])
    filt = sum(len(r["filtered_out"]) for r in results if not r["fetch_error"])
    stored = sum(len(r["stored_db"]) for r in results if not r["fetch_error"])
    narr = sum(len(r["narrative_new"]) for r in results if not r["fetch_error"])
    fetch_fail = sum(1 for r in results if r["fetch_error"])
    print(f"   sources fetched OK:    {len(results) - fetch_fail}/{len(results)}")
    if fetch_fail:
        print(f"   sources FETCH FAILED:  {fetch_fail}")
        for r in results:
            if r["fetch_error"]:
                print(f"     - {r['src'].name}: {r['fetch_error']}")
    print(f"   rawCount       total = {raw}")
    print(f"   parsedOk       total = {ok}")
    print(f"   parseFailed    total = {failed}")
    print(f"   filteredOut    total = {filt}")
    print(f"   storedInDB     total = {stored}   (across all sources for the target date)")
    print(f"   narrative_new  total = {narr}   (text-only fallback rows)")
    print()
    inv1 = (ok + failed + filt) == raw
    inv2_lhs = ok + narr
    inv2_rhs = stored  # rough: stored may include older text_fallback entries
    print(f"   INVARIANT 1: rawCount == parsedOk + parseFailed + filteredOut")
    print(f"      {raw} == {ok} + {failed} + {filt}  ({'PASS' if inv1 else 'FAIL'})")
    print(f"   INVARIANT 2: parsedOk + narrative_new ~~ storedInDB (today)")
    print(f"      {ok} + {narr} = {inv2_lhs}   vs storedInDB={inv2_rhs}")
    if inv2_lhs != inv2_rhs:
        diff = inv2_rhs - inv2_lhs
        print(f"      DELTA = {diff:+d}  ({'extra rows in DB (text_fallback carryover, prior runs, dedup)' if diff > 0 else 'rows missing from DB!'})")


# ── Wrong-data spot-check ─────────────────────────────────────────────────────

def _find_raw_for(stored_row: sqlite3.Row, parsed_ok: list[dict]) -> dict | None:
    """Find the parsed_ok entry whose raw row matches a stored DB row (by boat
    + trip_length match if possible)."""
    for p in parsed_ok:
        if (p["parsed"]["boat"].lower() == stored_row["boat"].lower()
                and p["parsed"]["trip_length"] == stored_row["trip_length"]):
            return p
    # Fallback: boat match only
    for p in parsed_ok:
        if p["parsed"]["boat"].lower() == stored_row["boat"].lower():
            return p
    return None


def _print_eyeball_samples(results: list[dict], n: int = 5) -> None:
    print("\n" + "═" * 78)
    print(f" EYEBALL SAMPLES — raw HTML row vs parsed-object (first {n} stored trips)")
    print("═" * 78)

    # Collect across all sources, prefer ones with high catch counts (interesting).
    samples: list[tuple[dict, sqlite3.Row]] = []
    for r in results:
        for stored in r["stored_db"]:
            samples.append((r, stored))
    samples.sort(key=lambda s: -(s[1]["trophy_count"] or 0))
    picked = samples[:n]

    if not picked:
        print("   (no stored trips for this date)")
        return

    for idx, (res, stored) in enumerate(picked, 1):
        src = res["src"]
        matching = _find_raw_for(stored, res["parsed_ok"])
        print(f"\n   [{idx}] {src.name} — {stored['boat']} ({stored['trip_length']})  source={stored['source']}")
        if matching:
            raw = matching["raw"]
            print(f"       RAW HTML row:")
            print(f"         boat:            {raw['boat']!r}")
            print(f"         trip_type_raw:   {raw['trip_type_raw']!r}")
            print(f"         anglers_text:    {raw['anglers_text']!r}")
            print(f"         fish_count_text: {raw['fish_count_text']!r}")
        else:
            print(f"       (no matching raw row found — likely text_fallback or pre-existing record)")
            if stored["written_text"]:
                print(f"       written_text:    {_truncate(stored['written_text'], 200)}")
        # Render parsed object
        species_kv = []
        for col in ("bluefin", "yellowfin", "yellowtail", "dorado",
                    "skipjack", "bigeye", "albacore"):
            v = stored[col]
            if v:
                species_kv.append(f"{col}={v}")
        other = stored["other_species_json"] or "{}"
        try:
            other_d = {k: v for k, v in json.loads(other).items() if v}
        except Exception:
            other_d = {}
        print(f"       PARSED (in DB):")
        print(f"         anglers:      {stored['anglers']}")
        print(f"         tracked:      {' '.join(species_kv) or '(none)'}")
        if other_d:
            print(f"         other:        {other_d}")
        print(f"         trophy_count: {stored['trophy_count']}  (sum of Bluefin/Yellowfin/Yellowtail/Dorado)")
        print(f"         full_catch:   {_truncate(stored['full_catch'], 160)}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    if len(argv) > 1:
        try:
            target = _date.fromisoformat(argv[1])
        except ValueError:
            print(f"Bad date: {argv[1]!r}. Use YYYY-MM-DD.", file=sys.stderr)
            return 2
    else:
        target = pacific_today()

    print("═" * 78)
    print(f" SCRAPE RECONCILIATION REPORT")
    print(f" Target date: {target.isoformat()}  (Pacific)")
    print(f" Generated:   {datetime.now(timezone.utc).isoformat(timespec='seconds')}  UTC")
    print(f" DB:          {DB_PATH}")
    print("═" * 78)
    print()
    print("Pipeline rejection points instrumented:")
    print("  1. HTML row extraction (_extract_rows)")
    print("     - Tables filtered by header ('Boat' + 'Fish Count')")
    print("     - Row reject if cells != 4")
    print("     - Row reject if first cell empty OR matches:", _SKIP_FIRST_CELL)
    print("     - Row reject if anglers cell has no digit")
    print("  2. parse_page filters")
    print("     - SILENT skip if row.date != target_date  [date_window]")
    print("     - WARN+skip if trip_length unparsable     [trip_length_unparsable]")
    print("     - WARN+skip if anglers <= 0 or missing   [anglers_missing_or_zero]")
    print("  3. db.insert_trips (UNIQUE(date,boat,landing,trip_length,anglers))")
    print("     - Dups within 3 days: INSERT OR REPLACE; older: INSERT OR IGNORE")
    print("  4. Boat allowlist: NONE in structured-page path.")
    print(f"     A blacklist exists ONLY in narrative-text harvest: {sorted(_BOAT_NAME_BLACKLIST)}")
    print("  5. Pagination: NONE — fishcounts.com pages are single-page.")
    print("     OC/LA landings: fetched directly, no follow-up requests.")
    print()

    # Load known boats from DB for narrative harvest
    with sqlite3.connect(DB_PATH) as conn:
        known_boats = [r[0] for r in conn.execute("SELECT DISTINCT boat FROM trips").fetchall()]

    results: list[dict] = []
    for src in SOURCES:
        try:
            results.append(reconcile_source(src, target, known_boats))
        except Exception as exc:
            print(f"  EXCEPTION reconciling {src.name}: {type(exc).__name__}: {exc}")
            results.append({"src": src, "fetch_error": str(exc), "raw_rows": [],
                            "parsed_ok": [], "parse_failed": [], "filtered_out": [],
                            "narrative_new": [], "narrative_fetched_urls": [],
                            "stored_db": []})

    for r in results:
        _print_block(r)

    _print_totals(results)
    _print_eyeball_samples(results, n=5)

    print("\n" + "═" * 78)
    print(" NOTES ON SILENT DROPS / KNOWN GOTCHAS")
    print("═" * 78)
    print(" * `date_window` filtering is SILENT in production — rows for past")
    print("   dates on multi-day pages (H&M shows yesterday at top) are simply")
    print("   skipped with no log line. Counted here under filteredOut.")
    print(" * Parse-time exceptions in parse_anglers / parse_trip_length /")
    print("   parse_fish_counts are NOT actually caught in production —")
    print("   they'd propagate up to scrape_all's try/except and mark the")
    print("   whole landing 'error', losing every row from that landing.")
    print("   This diagnostic catches them per-row to show which one broke.")
    print(" * The narrative text harvest creates parallel text_fallback rows.")
    print("   These show up under storedInDB but NOT parsedOk (different path).")
    print(" * UNIQUE constraint is (date, boat, landing, trip_length, anglers).")
    print("   An AM and PM Half Day trip with different anglers ARE separate.")
    print("   Two identical rows from re-scrape are merged (upsert).")
    print(" * Boat allowlist: structured path accepts ANY boat name on the")
    print("   page. The narrative blacklist only blocks species-name boats")
    print("   like 'Bluefin' from being matched as boats in free text.")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
