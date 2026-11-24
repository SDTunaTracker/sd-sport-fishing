"""
Data-health check for the BloodyDecks (paddies) pipeline.

check() returns a list of Problem records with the same shape as
src/completeness.Problem (key, feed, severity, detail) so the data-health
alerter can append them to its own list and text/email the owner:

    from scraper.paddies import health as paddies_health
    probs += [completeness.Problem(**vars(p)) for p in paddies_health.check()]

By default it reads the *published* state (the state file on GitHub main and
the live /api/v1/paddies.json), so it works from any checkout, however far
behind origin it is. Pass local=True to judge the local files instead (what
the paddies workflow does right after a run).

Rules (keys are stable for alert de-duplication):
  bd:ingest       critical  no successful BD feed fetch in INGEST_MAX_AGE
  bd:feed-errors  warning   primary feed failing FEED_FAIL_RUNS runs in a row
  bd:no-new-posts warning   newest stored post older than NO_POSTS_MAX_AGE
  bd:extract      warning   Claude extraction failing while posts wait
  bd:publish      warning   live paddies.json not regenerated in PUBLISH_MAX_AGE
  bd:health       warning   state could not be read at all

CLI:
    python -m scraper.paddies.health            # published state; exit 1 on any problem
    python -m scraper.paddies.health --local    # local files
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "paddies_ingest_state.json"
PADDIES_JSON_PATH = ROOT / "web" / "api" / "v1" / "paddies.json"

STATE_URL = ("https://raw.githubusercontent.com/SDTunaTracker/sd-sport-fishing/"
             "main/data/paddies_ingest_state.json")
PADDIES_URL = "https://thetunatracker.com/api/v1/paddies.json"

# The workflow runs every 3 h; GitHub cron can slip by several hours, so a
# full day without a successful fetch means it is genuinely stalled. The RSS
# window is ~8 days and ingest backfills gaps, so a 1-day alert leaves a week
# to fix things before anything is lost.
INGEST_MAX_AGE = timedelta(hours=24)
FEED_FAIL_RUNS = 3
NO_POSTS_MAX_AGE = timedelta(days=3)     # SoCal offshore forum posts most days
EXTRACT_MAX_AGE = timedelta(hours=48)
PUBLISH_MAX_AGE = timedelta(hours=24)

FEED = "bloodydecks"


@dataclass
class Problem:
    key: str
    feed: str
    severity: str   # "critical" | "warning"
    detail: str


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ago(dt: datetime, now: datetime) -> str:
    h = (now - dt).total_seconds() / 3600
    return f"{h:.0f}h ago" if h < 48 else f"{h / 24:.1f} days ago"


def _get_json(url: str, timeout: float = 20) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "TunaTracker-health/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _read_local(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def evaluate(state: dict | None, paddies: dict | None, now: datetime) -> list[Problem]:
    """Pure rules over already-loaded state; see module docstring."""
    probs: list[Problem] = []
    if not state:
        return [Problem("bd:health", FEED, "warning",
                        "BloodyDecks health state unreadable (data/paddies_ingest_state.json)")]

    last_ok = _parse(state.get("last_success_utc"))
    if last_ok is None or now - last_ok > INGEST_MAX_AGE:
        when = _ago(last_ok, now) if last_ok else "never"
        probs.append(Problem("bd:ingest", FEED, "critical",
                             f"BloodyDecks collection stalled: last successful forum fetch {when} "
                             f"(paddies workflow not running or failing)"))

    fails = state.get("consecutive_failures") or 0
    if fails >= FEED_FAIL_RUNS:
        probs.append(Problem("bd:feed-errors", FEED, "warning",
                             f"BloodyDecks feed failed {fails} runs in a row: "
                             f"{state.get('last_error') or 'unknown error'}"))

    newest = _parse(state.get("newest_post_published_at"))
    if newest is not None and now - newest > NO_POSTS_MAX_AGE:
        probs.append(Problem("bd:no-new-posts", FEED, "warning",
                             f"No new BloodyDecks posts stored since {newest:%Y-%m-%d} "
                             f"({_ago(newest, now)}); feed may be empty or blocked"))

    pending = state.get("pending_extract") or 0
    ex_ok = _parse(state.get("extract_last_success_utc"))
    ex_fails = state.get("extract_consecutive_failed_runs") or 0
    if pending and (ex_ok is None or now - ex_ok > EXTRACT_MAX_AGE) and (ex_fails or ex_ok):
        probs.append(Problem("bd:extract", FEED, "warning",
                             f"BloodyDecks Claude extraction failing ({ex_fails} runs, "
                             f"{pending} posts waiting; raw posts are still being saved): "
                             f"{state.get('extract_last_error') or 'unknown error'}"))

    if paddies is not None:
        gen = _parse(paddies.get("generated_at"))
        if gen is None or now - gen > PUBLISH_MAX_AGE:
            when = _ago(gen, now) if gen else "unknown"
            probs.append(Problem("bd:publish", FEED, "warning",
                                 f"Live /api/v1/paddies.json last regenerated {when}"))
    return probs


def check(now: datetime | None = None, *, local: bool = False) -> list[Problem]:
    """Load state (published by default, local files with local=True) and evaluate."""
    now = now or datetime.now(timezone.utc)
    if local:
        return evaluate(_read_local(STATE_PATH), _read_local(PADDIES_JSON_PATH), now)
    try:
        state = _get_json(STATE_URL)
    except Exception:  # noqa: BLE001 - fall back to whatever is on disk
        state = _read_local(STATE_PATH)
    try:
        paddies = _get_json(PADDIES_URL)
    except Exception:  # noqa: BLE001 - the site being down is another check's job
        paddies = None
    return evaluate(state, paddies, now)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--local", action="store_true", help="judge local files, not published state")
    ap.add_argument("--json", action="store_true", help="print problems as JSON")
    args = ap.parse_args(argv)
    probs = check(local=args.local)
    if args.json:
        print(json.dumps([asdict(p) for p in probs], indent=2))
    elif probs:
        for p in probs:
            print(f"[{p.severity}] {p.key}: {p.detail}")
            if p.severity == "critical":
                print(f"::error title=paddies health::{p.detail}")
            else:
                print(f"::warning title=paddies health::{p.detail}")
    else:
        print("BloodyDecks pipeline healthy.")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
