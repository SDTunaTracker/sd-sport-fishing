"""verify_sixpack.py — rerunnable proof-of-shipment for the six-pack Analytics
exclusion feature.

Reads tracker.db in read-only mode, mirrors the JS analytics universe filter
(web/analytics.js `preprocessTrips` + `boatWinRates` + `boatLeaderboard`)
in Python, and runs the assertions the user demanded. Prints a final
PASS/FAIL summary. Exits non-zero on any failure so this can be dropped
into CI later.

The 5 gates:
  1. LIST-INTEGRITY   — 20 boats, seed presence/absence.
  2. ACID (recompute) — pick an open-party boat with real head-to-head overlap
                        with Got Bait; assert Win Rate differs OFF vs ON.
  3. DEFAULT-OFF      — Got Bait absent from EVERY analytics output when OFF,
                        present when ON.
  4. REPORTS-UNTOUCHED — Got Bait still resolves in the Reports data path.
  5. CROSS-METRIC     — no listed six-pack survives in ANY analytics metric
                        under OFF (catches per-metric drift).

The Python-side simulation reproduces `web/analytics.js` exactly. If the
frontend changes materially, this file must move in lockstep.
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_DB = _ROOT / "tracker.db"

sys.path.insert(0, str(_ROOT))
from src.sixpack_boats import SIXPACK_BOATS, normalize  # noqa: E402

TROPHY = ("Bluefin", "Yellowfin", "Yellowtail", "Dorado")
MIN_MATCHUPS = 10  # matches web/analytics.js MIN_MATCHUPS in boatWinRates

# Anything to stderr/stdout with these prefixes is machine-scannable for CI:
_PASS = "PASS"
_FAIL = "FAIL"

failures: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    tag = _PASS if ok else _FAIL
    print(f"  [{tag}] {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(label)


# ── Simulate SD.TRIPS ────────────────────────────────────────────────────────
def load_trips() -> list[dict]:
    """Mirror export.py: is_half_day=0 and drop preliminary rows."""
    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT boat, landing, date, trip_length, anglers,
               trophy_per_angler_per_day, bluefin, yellowfin, yellowtail, dorado
        FROM trips
        WHERE is_half_day = 0
          AND COALESCE(is_preliminary, 0) = 0
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def preprocess(trips: list[dict], include_sixpack: bool) -> list[dict]:
    """Mirror web/analytics.js preprocessTrips + _sixpackFilter."""
    if include_sixpack:
        exclude = set()
    else:
        exclude = {normalize(n) for n in SIXPACK_BOATS}

    out = []
    for t in trips:
        if exclude and normalize(t["boat"]) in exclude:
            continue
        total_tuna = sum(int(t.get(sp.lower(), 0) or 0) for sp in TROPHY)
        # tripLengthDays not stored per row here — synthesize from tripLength.
        # For win-rate + boat leaderboard we only need trophy_per_angler_per_day
        # which is pre-computed by the exporter. calcDays only matters for TPA
        # aggregations — we skip it since our metrics use TPA/day directly.
        out.append({**t, "totalTuna": total_tuna})
    return out


# ── Mirror boatWinRates (web/analytics.js) ───────────────────────────────────
def boat_win_rates(processed: list[dict]) -> dict[tuple[str, str], dict]:
    """Returns {(boat, tripLength): {winRate, wins, matchupCount, total, avgTPAPerDay}}."""
    by_day_len: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in processed:
        by_day_len[(t["date"], t["trip_length"])].append(t)

    m_stats: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"wins": 0, "matchupCount": 0}
    )
    for group in by_day_len.values():
        if len(group) < 2:
            continue
        top = max(t["trophy_per_angler_per_day"] or 0 for t in group)
        for t in group:
            key = (t["boat"], t["trip_length"])
            r = m_stats[key]
            r["matchupCount"] += 1
            if (t["trophy_per_angler_per_day"] or 0) >= top - 1e-9:
                r["wins"] += 1

    t_stats: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"tpaSum": 0.0, "total": 0}
    )
    for t in processed:
        key = (t["boat"], t["trip_length"])
        t_stats[key]["tpaSum"] += t["trophy_per_angler_per_day"] or 0
        t_stats[key]["total"] += 1

    out: dict[tuple[str, str], dict] = {}
    for key, ts in t_stats.items():
        ms = m_stats.get(key, {"wins": 0, "matchupCount": 0})
        out[key] = {
            "total":        ts["total"],
            "avgTPAPerDay": (ts["tpaSum"] / ts["total"]) if ts["total"] else 0.0,
            "wins":         ms["wins"],
            "matchupCount": ms["matchupCount"],
            "winRate":      (ms["wins"] / ms["matchupCount"])
                             if ms["matchupCount"] >= MIN_MATCHUPS else None,
        }
    return out


# ── Mirror boatLeaderboard (web/analytics.js) ────────────────────────────────
def boat_leaderboard(processed: list[dict]) -> dict[str, dict]:
    """Returns per-boat aggregates. Boat set = keys of the dict."""
    by_boat: dict[str, dict] = defaultdict(
        lambda: {"trips": 0, "totalTuna": 0, "totalAnglers": 0,
                 "tpas": [], "tpaPerDays": []}
    )
    for t in processed:
        b = by_boat[t["boat"]]
        b["trips"] += 1
        b["totalTuna"] += t["totalTuna"]
        anglers = max(1, t["anglers"] or 0)
        b["totalAnglers"] += t["anglers"] or 0
        tpa = (t["totalTuna"] / anglers) if anglers > 0 else 0
        b["tpas"].append(tpa)
        b["tpaPerDays"].append(t["trophy_per_angler_per_day"] or 0)
    return dict(by_boat)


# ── Mirror top-performer-rate: fraction of trips >= fleet-median TPA/Day ─────
def top_performer_rate(processed: list[dict]) -> dict[str, float]:
    """Per boat, fraction of its trips whose TPA/day >= fleet median TPA/day."""
    all_tpapd = [t["trophy_per_angler_per_day"] or 0 for t in processed]
    if not all_tpapd:
        return {}
    fleet_med = statistics.median(all_tpapd)
    by_boat: dict[str, list[float]] = defaultdict(list)
    for t in processed:
        by_boat[t["boat"]].append(t["trophy_per_angler_per_day"] or 0)
    return {
        boat: sum(1 for x in tpds if x >= fleet_med) / len(tpds)
        for boat, tpds in by_boat.items() if tpds
    }


# ── ACID auto-selector ───────────────────────────────────────────────────────
def pick_acid_pair(all_trips: list[dict]) -> tuple[str, str, str, int] | None:
    """Pick (open_boat, tripLength, sixpack_target, shared_matchup_count).

    Selection rule: find the open-party boat whose (date, tripLength) tuples
    overlap most heavily with SIXPACK targets. We want a real head-to-head
    delta, not a cosmetic one, so we bias to boats with the largest number of
    shared matchup slots against Got Bait (or any six-pack when Got Bait has
    thin overlap).

    Returns None if no head-to-head overlap exists — that would itself be a
    signal the filter is untestable on this DB and the caller should surface.
    """
    six_set = {normalize(n) for n in SIXPACK_BOATS}

    # Build the (date, tripLength) slots each boat appears in
    slots_by_boat: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for t in all_trips:
        slots_by_boat[t["boat"]].add((t["date"], t["trip_length"]))

    # Also index which six-packs are in each slot for attribution
    six_in_slot: dict[tuple[str, str], set[str]] = defaultdict(set)
    for t in all_trips:
        if normalize(t["boat"]) in six_set:
            six_in_slot[(t["date"], t["trip_length"])].add(t["boat"])

    best = None  # (shared_count, open_boat, trip_length, sixpack)
    for boat, slots in slots_by_boat.items():
        if normalize(boat) in six_set:
            continue  # only consider open-party candidates
        # Group shared slots by trip length so we can report a specific length
        shared_by_len: dict[str, tuple[int, set[str]]] = defaultdict(
            lambda: (0, set())
        )
        for slot in slots:
            if slot in six_in_slot:
                cnt, sixes = shared_by_len[slot[1]]
                shared_by_len[slot[1]] = (cnt + 1, sixes | six_in_slot[slot])
        for tl, (cnt, sixes) in shared_by_len.items():
            if cnt < MIN_MATCHUPS:
                continue  # need enough matchups for a stable winRate
            # Prefer Got Bait as the attributed six-pack if it's one of them
            attributed = "Got Bait" if "Got Bait" in sixes else sorted(sixes)[0]
            if best is None or cnt > best[0]:
                best = (cnt, boat, tl, attributed)
    if best is None:
        return None
    cnt, boat, tl, attributed = best
    return (boat, tl, attributed, cnt)


# ── Reports data path (mirrors src/export.py `_today_summary` inputs) ────────
def reports_data_for(boat: str, all_trips_incl_preliminary: list[dict]) -> int:
    """Reports 'Today's Report' path in export.py reads all_rows (which INCLUDES
    preliminary rows) and feeds it to _today_summary. We check whether the
    given boat has ANY row in the DB that would be visible to that path,
    regardless of the analytics-side filter.

    The analytics filter lives in the FRONTEND only (window.SD_PROC_TRIPS).
    Reports render from window.SD.TODAY which is pre-baked at export time
    and never re-derived from settings. So the correct verification is: the
    Reports source of truth (the DB) must have Got Bait rows, and the export
    payload for TODAY must not conditionally exclude them.
    """
    return sum(1 for t in all_trips_incl_preliminary if t["boat"] == boat)


def load_all_rows_including_preliminary() -> list[dict]:
    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT boat, date, is_preliminary FROM trips WHERE is_half_day = 0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    if not _DB.exists():
        print(f"{_FAIL}: tracker.db not found at {_DB}")
        return 1

    print("=" * 78)
    print("verify_sixpack.py — six-pack Analytics exclusion, live-DB proof")
    print("=" * 78)
    print()

    # ── Gate 1: LIST-INTEGRITY ─────────────────────────────────────────
    print(f"[Gate 1] Exclusion list resolved from src/sixpack_boats.py "
          f"(driven by forecast/sixpack_candidates.csv):")
    print()
    for i, name in enumerate(SIXPACK_BOATS, 1):
        print(f"  {i:2d}. {name}")
    print()
    _check("count == 21",           len(SIXPACK_BOATS) == 21,
           f"got {len(SIXPACK_BOATS)}")
    _check("Got Bait present",              "Got Bait" in SIXPACK_BOATS)
    _check("Freeman 34 present",            "Freeman 34" in SIXPACK_BOATS)
    _check("Lucky B Sportfishing present",  "Lucky B Sportfishing" in SIXPACK_BOATS)
    _check("El Gato Dos present (manual add)", "El Gato Dos" in SIXPACK_BOATS)
    _check("Nautilus ABSENT",       "Nautilus" not in SIXPACK_BOATS)
    _check("Intrigue ABSENT",       "Intrigue" not in SIXPACK_BOATS)
    _check("Graylight ABSENT",      "Graylight" not in SIXPACK_BOATS)
    print()

    all_trips = load_trips()
    proc_off = preprocess(all_trips, include_sixpack=False)
    proc_on  = preprocess(all_trips, include_sixpack=True)
    print(f"Analytics universe sizes: OFF={len(proc_off):,} trips  "
          f"ON={len(proc_on):,} trips  (delta={len(proc_on)-len(proc_off):,})")
    print()

    # ── Gate 2: ACID — recompute proves it's not cosmetic ───────────────
    print("[Gate 2] ACID TEST — recomputed head-to-head winRate must differ")
    pair = pick_acid_pair(all_trips)
    if pair is None:
        _check("Auto-selected open-party boat with real head-to-head overlap",
               False, "no boat with >=10 shared matchup slots against a six-pack")
    else:
        open_boat, trip_length, sixpack, shared = pair
        print(f"  Selected: open-party '{open_boat}' at trip length "
              f"'{trip_length}' — shared {shared} slots with '{sixpack}'.")
        wr_off = boat_win_rates(proc_off)
        wr_on  = boat_win_rates(proc_on)
        r_off = wr_off.get((open_boat, trip_length))
        r_on  = wr_on.get((open_boat, trip_length))
        print(f"  {open_boat} | {trip_length}   OFF: winRate="
              f"{_fmt_rate(r_off)}  matchups={r_off['matchupCount']}")
        print(f"  {open_boat} | {trip_length}   ON : winRate="
              f"{_fmt_rate(r_on)}  matchups={r_on['matchupCount']}")
        matchup_delta = r_on["matchupCount"] - r_off["matchupCount"]
        rate_delta = None
        if r_on["winRate"] is not None and r_off["winRate"] is not None:
            rate_delta = r_on["winRate"] - r_off["winRate"]
        _check("Matchup pool expanded when toggle ON",
               matchup_delta > 0,
               f"delta_matchups={matchup_delta}")
        _check("winRate value actually differs (not cosmetic)",
               rate_delta is not None and abs(rate_delta) > 1e-9,
               f"delta_rate={rate_delta}")
        _check("Attributed driver was actually excluded under OFF",
               normalize(sixpack) in {normalize(n) for n in SIXPACK_BOATS})
    print()

    # ── Gate 3: DEFAULT-OFF ──────────────────────────────────────────────
    print("[Gate 3] DEFAULT-OFF — Got Bait invisible under OFF, visible under ON")
    got_bait_present_off = any(t["boat"] == "Got Bait" for t in proc_off)
    got_bait_present_on  = any(t["boat"] == "Got Bait" for t in proc_on)
    _check("Got Bait absent from processed universe (OFF)",
           not got_bait_present_off)
    _check("Got Bait present in processed universe (ON)",
           got_bait_present_on)

    lb_off = boat_leaderboard(proc_off)
    lb_on  = boat_leaderboard(proc_on)
    _check("Got Bait absent from boat leaderboard (OFF)",
           "Got Bait" not in lb_off)
    _check("Got Bait present in boat leaderboard (ON)",
           "Got Bait" in lb_on)

    wr_off = boat_win_rates(proc_off) if pair is None else wr_off
    wr_on  = boat_win_rates(proc_on)  if pair is None else wr_on
    got_bait_wr_keys_off = [k for k in wr_off if k[0] == "Got Bait"]
    got_bait_wr_keys_on  = [k for k in wr_on  if k[0] == "Got Bait"]
    _check("Got Bait absent from Win Rate stats (OFF)",
           not got_bait_wr_keys_off,
           f"found {len(got_bait_wr_keys_off)} keys")
    _check("Got Bait present in Win Rate stats (ON)",
           bool(got_bait_wr_keys_on),
           f"found {len(got_bait_wr_keys_on)} keys")

    tpr_off = top_performer_rate(proc_off)
    tpr_on  = top_performer_rate(proc_on)
    _check("Got Bait absent from top-performer-rate (OFF)",
           "Got Bait" not in tpr_off)
    _check("Got Bait present in top-performer-rate (ON)",
           "Got Bait" in tpr_on)

    # TPA/Day — same universe check via leaderboard rows carrying tpaPerDays
    tpapd_off_boats = {b for b, s in lb_off.items() if s["tpaPerDays"]}
    tpapd_on_boats  = {b for b, s in lb_on.items()  if s["tpaPerDays"]}
    _check("Got Bait absent from TPA/Day pool (OFF)",
           "Got Bait" not in tpapd_off_boats)
    _check("Got Bait present in TPA/Day pool (ON)",
           "Got Bait" in tpapd_on_boats)
    print()

    # ── Gate 4: REPORTS-UNTOUCHED ────────────────────────────────────────
    print("[Gate 4] REPORTS-UNTOUCHED — Got Bait resolves in Reports path")
    all_rows_incl_prelim = load_all_rows_including_preliminary()
    reports_hits = reports_data_for("Got Bait", all_rows_incl_prelim)
    _check("Got Bait has rows visible to _today_summary/TODAY path",
           reports_hits > 0,
           f"{reports_hits} rows in DB feed the Reports data path")
    # Confirm export.py does not conditionally strip six-packs from _today_summary
    # by inspecting the file text (fast sanity, not a runtime check).
    export_text = (_ROOT / "src" / "export.py").read_text(encoding="utf-8")
    reports_touched = ("SIXPACK" in export_text
                       and "_today_summary" in export_text
                       and export_text.rfind("SIXPACK") >
                       export_text.rfind("_today_summary"))
    # Only fail if SIXPACK is referenced INSIDE _today_summary logic; the
    # payload injection at the outer scope is expected and fine.
    inside_today_summary = False
    lines = export_text.splitlines()
    in_fn = False
    for line in lines:
        if line.startswith("def _today_summary"):
            in_fn = True
            continue
        if in_fn and line.startswith("def "):
            in_fn = False
        if in_fn and "SIXPACK" in line:
            inside_today_summary = True
            break
    _check("_today_summary does NOT touch SIXPACK filtering",
           not inside_today_summary)
    print()

    # ── Gate 5: CROSS-METRIC CONSISTENCY ─────────────────────────────────
    print("[Gate 5] CROSS-METRIC — no listed six-pack leaks into ANY analytics metric under OFF")
    six_set_norm = {normalize(n) for n in SIXPACK_BOATS}

    # Metric A: universe
    leaked_universe = {t["boat"] for t in proc_off
                       if normalize(t["boat"]) in six_set_norm}
    _check("universe has no six-packs (OFF)",
           not leaked_universe,
           f"leaked: {sorted(leaked_universe)}")

    # Metric B: leaderboard
    leaked_lb = {b for b in lb_off if normalize(b) in six_set_norm}
    _check("boat leaderboard has no six-packs (OFF)",
           not leaked_lb,
           f"leaked: {sorted(leaked_lb)}")

    # Metric C: Win Rate keys
    leaked_wr = {b for (b, _) in wr_off if normalize(b) in six_set_norm}
    _check("Win Rate has no six-packs (OFF)",
           not leaked_wr,
           f"leaked: {sorted(leaked_wr)}")

    # Metric D: top-performer-rate
    leaked_tpr = {b for b in tpr_off if normalize(b) in six_set_norm}
    _check("Top Performer Rate has no six-packs (OFF)",
           not leaked_tpr,
           f"leaked: {sorted(leaked_tpr)}")

    # Metric E: TPA/Day pool
    leaked_tpapd = {b for b in tpapd_off_boats if normalize(b) in six_set_norm}
    _check("TPA/Day pool has no six-packs (OFF)",
           not leaked_tpapd,
           f"leaked: {sorted(leaked_tpapd)}")
    print()

    # ── Summary ───────────────────────────────────────────────────────────
    print("=" * 78)
    if failures:
        print(f"{_FAIL}: {len(failures)} assertion(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"{_PASS}: all assertions across 5 gates passed against live DB.")
    print("Remaining verification is browser-side (not automated here):")
    print("  a) production build-commit hash matches this feature")
    print("  b) fresh/incognito browser shows six-packs hidden by default")
    print("  c) toggle persists across a hard refresh (localStorage + Clerk)")
    return 0


def _fmt_rate(r: dict | None) -> str:
    if r is None or r.get("winRate") is None:
        return "None (insufficient matchups)"
    return f"{r['winRate'] * 100:.1f}%"


if __name__ == "__main__":
    sys.exit(main())
