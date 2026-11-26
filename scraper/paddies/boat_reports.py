"""
Party-boat trip reports from BloodyDecks -> per-boat "what anglers say".

Reads paddy_sources rows from the boat_reports feeds (feeds.py kind
"boat_reports": SoCal Sportboats and Long Range forums), asks Claude to
classify each post and pull out, per boat on the trip:

  * trip date / length,
  * sentiment (-2..+2, or null when not mentioned) for captain, crew, galley,
    bunks, fish-finding and overall, each backed by a short verbatim quote,
  * would-rebook (true / false / null), also quote-backed,
  * a one-line catch summary in our own words, plus tackle and spots.

Every aspect score must come with a quote that really appears in the post
(checked with extract.quote_matches_source); otherwise the score is dropped.
That keeps the model from inventing opinions.

Results go to data/paddies.db:
  boat_report_runs      one row per source post: status ok | not_report | failed
  forum_boat_reports    one row per (post, boat) with the fields above, the
                        boat matched to tracker.db names, and the landing's
                        own count for that trip when we can find it.

write_export() turns that into web/api/v1/boat_forum_reports.json for the boat
page's "From BloodyDecks trip reports" panel, and write_whats_working() into
web/api/v1/whats_working.json (recent tackle / bait / conditions per trip type).
forum_signals (birds, bait, water, bite windows) is research-only input for the
forecast R&D work: exported with --signals-csv, never published on the site. Nothing here is a verified review: we
publish our summary, short quotes and a link to the thread, never the post
itself or the author's username.

CLI:
    python -m scraper.paddies.boat_reports              # extract pending, then export
    python -m scraper.paddies.boat_reports --limit 10   # cap Claude calls this run
    python -m scraper.paddies.boat_reports --export-only
    python -m scraper.paddies.boat_reports --dry-run --limit 3   # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import coords as coords_mod
from . import regions as regions_mod
from . import extract as paddy_extract
from .feeds import feed_ids, get_feed

log = logging.getLogger("paddies.boat_reports")

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = paddy_extract.DB_PATH
TRACKER_DB_PATH = ROOT / "tracker.db"
EXPORT_PATH = ROOT / "web" / "api" / "v1" / "boat_forum_reports.json"
WHATS_WORKING_PATH = ROOT / "web" / "api" / "v1" / "whats_working.json"
STATE_PATH = ROOT / "data" / "paddies_ingest_state.json"

MODEL = paddy_extract.MODEL
MAX_TOKENS = 2500
MAX_BODY_CHARS = 14000          # long-range reports run to 17k; the tail is mostly sign-off
DEFAULT_RUN_LIMIT = 40          # Claude calls per run; the backlog drains over a few runs
MAX_ATTEMPTS = 3                # per post, then we stop retrying it
MAX_POST_AGE_DAYS = 365         # thread *start* older than this when fetched = too old to publish (matches EXPORT_WINDOW_DAYS)
REQUEST_SLEEP = 0.5
EXPORT_WINDOW_DAYS = 365
QUOTE_MAX_WORDS = 15
MIN_BODY_CHARS = 150            # shorter = photo-only post, one-liner or question: skip the call

ASPECTS = ("overall", "captain", "crew", "galley", "bunks", "fish_finding")

SCHEMA = """
CREATE TABLE IF NOT EXISTS boat_report_runs (
    source_id     TEXT PRIMARY KEY,      -- paddy_sources.id
    status        TEXT NOT NULL,         -- ok | not_report | failed
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    extracted_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forum_boat_reports (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT NOT NULL,
    feed_id        TEXT NOT NULL,
    boat_raw       TEXT NOT NULL,        -- as written in the post
    boat           TEXT,                 -- matched tracker.db name, or NULL
    landing        TEXT,                 -- from the matched trip / boats table
    trip_date      TEXT,                 -- departure, YYYY-MM-DD
    trip_length    TEXT,                 -- '1/2 Day', 'Full Day', '2 Day', ...
    overall        INTEGER,              -- -2..2 or NULL (not mentioned)
    captain        INTEGER,
    crew           INTEGER,
    galley         INTEGER,
    bunks          INTEGER,
    fish_finding   INTEGER,
    would_rebook   INTEGER,              -- 1 / 0 / NULL
    quotes         TEXT NOT NULL,        -- JSON {aspect: quote}
    catch_summary  TEXT,                 -- our words, one line
    tackle         TEXT,                 -- JSON [str]
    spots          TEXT,                 -- JSON [str]
    bait           TEXT,                 -- our words: bait type / size / quality
    conditions     TEXT,                 -- our words: water, weather, birds
    trip_match     TEXT,                 -- JSON {date, anglers, catch, landing} from tracker.db
    match_confidence REAL,               -- 0..1 that `boat` is the right tracker.db boat
    extracted_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fbr_boat ON forum_boat_reports(boat);
CREATE INDEX IF NOT EXISTS idx_fbr_source ON forum_boat_reports(source_id);

-- Research-only signals for the forecast R&D work (never shown on the site
-- as predictions). One row per (post, boat); every non-null value was backed
-- by a verbatim quote, kept in `evidence`.
--   NULL      = the post does not mention it
--   0 / []    = the post says it explicitly (e.g. "no birds", bird_pressure 0)
--   unverified lists fields the model gave but whose quote was not found in
--   the post (so NULL there means "claimed but unverified", not "silent").
-- Rows are append-only: a post is extracted once and its signal rows are
-- never rewritten, so fetched_at is what was knowable when.
CREATE TABLE IF NOT EXISTS forum_signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT NOT NULL,
    feed_id        TEXT NOT NULL,
    boat           TEXT,
    trip_date      TEXT,
    trip_length    TEXT,
    published_at   TEXT,
    spots          TEXT,                 -- JSON [str]
    bird_pressure  INTEGER,              -- 0 none .. 3 severe (birds stealing baits)
    bait_type      TEXT,                 -- sardine | anchovy | mackerel | squid | mixed
    bait_size_in   REAL,
    bait_quality   INTEGER,              -- -2..2
    water_temp_f   REAL,
    water_color    TEXT,                 -- blue | green | off_color | dirty
    bite_windows   TEXT,                 -- JSON [grey_light|morning|midday|afternoon|twilight|night]
    size_grade     TEXT,                 -- our words, e.g. "YFT 20-40 lb, few 60+"
    evidence       TEXT NOT NULL,        -- JSON {field: quote}
    unverified     TEXT,                 -- JSON [field] (see above)
    fetched_at     TEXT,                 -- when we first stored the post (knowable-at time)
    trip_match     TEXT,                 -- JSON landing count for the trip, as forum_boat_reports
    match_confidence REAL,
    extracted_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fsig_date ON forum_signals(trip_date);

-- Research-only location signals: every place a trip report says the boat
-- fished or saw fish/paddies/kelp/the fleet. Append-only like forum_signals.
-- lat/lon are only set when the quote itself holds coordinates (parsed in
-- code, never taken from the model); they are NEVER published as-is
-- (spots.py snaps/rounds before anything leaves the DB).
CREATE TABLE IF NOT EXISTS forum_locations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT NOT NULL,
    feed_id        TEXT NOT NULL,
    boat           TEXT,
    trip_date      TEXT,
    trip_length    TEXT,
    published_at   TEXT,
    fetched_at     TEXT,                 -- knowable-at time
    name           TEXT,                 -- place as written ("the Ridge", "9 Mile")
    kind           TEXT NOT NULL,        -- see LOCATION_KINDS
    distance_nm    REAL,                 -- "12 miles off <from_place>"
    bearing_deg    REAL,
    from_place     TEXT,
    lat            REAL,                 -- only from coordinates written in the quote
    lon            REAL,
    species        TEXT,                 -- JSON [species]
    quality        TEXT,                 -- see LOCATION_QUALITY
    water_temp_f   REAL,
    quote          TEXT NOT NULL,        -- verbatim, verified against the post
    extracted_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_floc_date ON forum_locations(trip_date);
"""

# Columns added after the first release of the tables (ALTER on old DBs).
_LATE_COLUMNS = {"forum_boat_reports": {"bait": "TEXT", "conditions": "TEXT",
                                        "match_confidence": "REAL"},
                 "forum_signals": {"unverified": "TEXT", "fetched_at": "TEXT",
                                   "trip_match": "TEXT", "match_confidence": "REAL"}}

MATCH_CONFIDENCE_MIN = 0.7      # below this a boat entry is stored but not published

BAIT_TYPES = ["sardine", "anchovy", "mackerel", "squid", "mixed"]
WATER_COLORS = ["blue", "green", "off_color", "dirty"]
BITE_WINDOWS = ["grey_light", "morning", "midday", "afternoon", "twilight", "night"]
SIGNAL_FIELDS = ("bird_pressure", "bait_type", "bait_size_in", "bait_quality",
                 "water_temp_f", "water_color", "bite_windows")

LOCATION_KINDS = ["bank", "island", "kelp", "paddy", "fleet", "coords", "offset", "area"]
LOCATION_QUALITY = ["wide_open", "good", "fair", "slow", "none"]
LOCATION_SPECIES = ["bluefin", "yellowfin", "yellowtail", "dorado", "wahoo", "albacore",
                    "skipjack", "bigeye", "bonito", "barracuda", "calico", "rockfish", "other"]
MAX_LOCATIONS = 6

TRIP_LENGTHS = ["1/2 Day", "3/4 Day", "Full Day", "Overnight", "1.5 Day", "2 Day",
                "2.5 Day", "3 Day", "3.5 Day", "4 Day", "5 Day", "6 Day", "7 Day",
                "8 Day", "9 Day", "10 Day", "11 Day", "12 Day", "13 Day", "14 Day",
                "15 Day", "16 Day", "Other"]
LENGTH_DAYS = {"1/2 Day": 0.5, "3/4 Day": 0.75, "Full Day": 1, "Overnight": 1}
for _l in TRIP_LENGTHS:
    m = re.match(r"^(\d+(?:\.5)?) Day$", _l)
    if m:
        LENGTH_DAYS[_l] = float(m.group(1))

_score = {"type": ["integer", "null"], "minimum": -2, "maximum": 2}
_quote = {"type": ["string", "null"]}

REPORT_TOOL = {
    "name": "record_trip_report",
    "description": "Record what this forum post says about the party boat(s) the author fished on.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_trip_report": {
                "type": "boolean",
                "description": "True only if the author describes a trip they took on a "
                               "named party/charter boat (sportboat). False for questions, "
                               "gear threads, 'help get this trip off the dock' posts, "
                               "second-hand news, private-boat or lodge/panga trips.",
            },
            "boats": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "boat_raw": {"type": "string", "description": "Boat name as written"},
                        "boat": {"type": ["string", "null"],
                                 "description": "Exact name from the KNOWN BOATS list, or null"},
                        "trip_date": {"type": ["string", "null"],
                                      "description": "Departure date YYYY-MM-DD if stated or clearly implied"},
                        "trip_length": {"type": ["string", "null"], "enum": TRIP_LENGTHS + [None]},
                        **{a: _score for a in ASPECTS},
                        "would_rebook": {"type": ["boolean", "null"]},
                        "quotes": {
                            "type": "object",
                            "description": "For EVERY non-null score and for would_rebook: a verbatim "
                                           "quote of at most 15 words, copied exactly from the post, "
                                           "that supports it. Keys: " + ", ".join(ASPECTS) + ", would_rebook.",
                            "properties": {k: _quote for k in (*ASPECTS, "would_rebook")},
                        },
                        "catch_summary": {"type": ["string", "null"],
                                          "description": "One short line in your own words: species, "
                                                         "sizes, how many (boat totals if given)."},
                        "tackle": {"type": "array", "items": {"type": "string"},
                                   "description": "Only tackle that actually produced fish on this "
                                                  "trip (not complaints or what failed): line test, "
                                                  "hooks, jigs and colours, technique. Max 5. Each a "
                                                  "short noun phrase of 6 words or fewer, not a "
                                                  "sentence, e.g. 'pink Marauder - wahoo', "
                                                  "'40 lb fluoro, #1 circle', 'braid + 3 ft topshot'."},
                        "spots": {"type": "array", "items": {"type": "string"},
                                  "description": "Named fishing areas only: banks, islands, kelp beds, "
                                                 "high spots (e.g. Colonet, the Ridge, 9 Mile Bank). "
                                                 "Not directions, depths or descriptions. Max 5."},
                        "bait": {"type": ["string", "null"],
                                 "description": "Starts with the bait type (sardine, anchovy, "
                                                "mackerel, squid...), then size/quality, 10 words or "
                                                "fewer, e.g. 'green sardine 4-6 in, lively'. Null if the "
                                                "post does not name the bait; bait condition alone "
                                                "goes in conditions."},
                        "conditions": {"type": ["string", "null"],
                                       "description": "12 words or fewer, your own words: water temp/"
                                                      "colour, weather, swell, birds."},
                        "locations": {
                            "type": "array",
                            "maxItems": MAX_LOCATIONS,
                            "description": "Every place this trip fished or saw fish, paddies, kelp "
                                           "or the fleet, in order. Only what the post states.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": ["string", "null"],
                                             "description": "Place as written: bank, island, kelp bed, "
                                                            "high spot, area. Null for bare coordinates."},
                                    "kind": {"type": "string", "enum": LOCATION_KINDS,
                                             "description": "fleet = 'the fleet was at ...'; coords = the "
                                                            "quote holds lat/lon or GPS/LORAN numbers; "
                                                            "offset = 'N miles <dir> of <place>'"},
                                    "distance_nm": {"type": ["number", "null"]},
                                    "bearing": {"type": ["string", "null"],
                                                "description": "Compass direction FROM from_place, e.g. 'SW'"},
                                    "from_place": {"type": ["string", "null"]},
                                    "species": {"type": "array",
                                                "items": {"type": "string", "enum": LOCATION_SPECIES}},
                                    "quality": {"type": ["string", "null"], "enum": LOCATION_QUALITY + [None],
                                                "description": "How the fishing was THERE; null if not said"},
                                    "water_temp_f": {"type": ["number", "null"]},
                                    "quote": {"type": "string",
                                              "description": "Verbatim, <=25 words, copied exactly; must "
                                                             "contain the place name or numbers"},
                                },
                                "required": ["name", "kind", "distance_nm", "bearing", "from_place",
                                             "species", "quality", "water_temp_f", "quote"],
                            },
                        },
                        "signals": {
                            "type": "object",
                            "description": "Structured conditions. Null unless the post states it; "
                                           "every non-null field needs a verbatim quote (<=15 words) "
                                           "in evidence under the same key.",
                            "properties": {
                                "bird_pressure": {"type": ["integer", "null"], "minimum": 0, "maximum": 3,
                                                  "description": "Birds (shearwaters etc.) taking baits: "
                                                                 "0 = post says birds were NOT a problem, "
                                                                 "1 mild .. 3 severe; null if birds are "
                                                                 "not mentioned"},
                                "bait_type": {"type": ["string", "null"], "enum": BAIT_TYPES + [None]},
                                "bait_size_in": {"type": ["number", "null"]},
                                "bait_quality": {"type": ["integer", "null"], "minimum": -2, "maximum": 2},
                                "water_temp_f": {"type": ["number", "null"]},
                                "water_color": {"type": ["string", "null"], "enum": WATER_COLORS + [None]},
                                "bite_windows": {"type": "array",
                                                 "items": {"type": "string", "enum": BITE_WINDOWS},
                                                 "description": "When the best bite happened"},
                                "size_grade": {"type": ["string", "null"],
                                               "description": "Our words: typical sizes by species"},
                                "evidence": {"type": "object",
                                             "properties": {k: _quote for k in SIGNAL_FIELDS}},
                            },
                            "required": [*SIGNAL_FIELDS, "size_grade", "evidence"],
                        },
                    },
                    "required": ["boat_raw", "boat", "trip_date", "trip_length", *ASPECTS,
                                 "would_rebook", "quotes", "catch_summary", "tackle", "spots",
                                 "bait", "conditions", "locations", "signals"],
                },
            },
        },
        "required": ["is_trip_report", "boats"],
    },
}

PROMPT = """You read San Diego / Southern California sportfishing forum posts and record what the \
author says about the party boat(s) they fished on. Be conservative.

Scores are -2 (very negative) .. +2 (very positive). Use null when the post does not \
clearly talk about that aspect: do not infer galley or bunks from silence, and do not \
score captain/crew just because fish were caught.
  overall: the author's overall verdict on the boat/trip experience (not the fishing luck)
  captain: the skipper's decisions, attitude, communication
  crew: deckhands' work, helpfulness
  galley: food, cook, galley service and prices
  bunks: bunks, staterooms, comfort, space, cleanliness
  fish_finding: how well the boat found and stayed on fish given conditions
would_rebook: true/false only if the author says or plainly implies they would or would not \
fish this boat again.

Every non-null score and would_rebook needs a supporting verbatim quote (max 15 words) copied \
exactly from the post text. If you cannot quote it, use null.

Sarcasm and jokes are common; read them in context. Several boats can appear in one post: \
give each boat the author fished on during the trip(s) this post reports its own entry. A boat \
merely mentioned (another boat nearby, a comparison with a past trip) is not an entry.

locations: one item per place the post says this trip fished, found fish, paddies or kelp, or \
where "the fleet" was. Copy coordinates only if the post itself prints them; never guess \
coordinates or distances.

For "boat", use the exact spelling from KNOWN BOATS when it is clearly the same boat \
(e.g. "PQ" = "Pacific Queen", "Lo Ann" = "New Lo-An"), otherwise null.

The post was published {published}. Resolve dates like "11/8" against that.

KNOWN BOATS: {boats}

TITLE: {title}

POST:
{body}"""

_client = None
_last_error: str | None = None


# ------------------------------------------------------------------ db

def open_db(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, cols in _LATE_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pending_rows(conn: sqlite3.Connection, limit: int | None = None,
                 now: datetime | None = None) -> list[sqlite3.Row]:
    """Boat-report posts not yet classified (or failed < MAX_ATTEMPTS times)."""
    ids = feed_ids("boat_reports")
    q = (f"SELECT s.id, s.url, s.title, s.published_at, s.fetched_at, s.raw_text, "
         f"s.truncated, s.feed_id FROM paddy_sources s "
         f"LEFT JOIN boat_report_runs r ON r.source_id = s.id "
         f"WHERE s.feed_id IN ({','.join('?' * len(ids))}) "
         f"AND s.truncated = 0 "
         f"AND (r.source_id IS NULL OR (r.status = 'failed' AND r.attempts < ?)) "
         f"ORDER BY s.published_at DESC")
    rows = [r for r in conn.execute(q, (*ids, MAX_ATTEMPTS)) if not _is_stale_bump(r)]
    return rows[:limit] if limit else rows


def _is_stale_bump(row) -> bool:
    """A thread started long before we fetched it (an old thread with a new reply)."""
    pub, fet = _parse_ts(row["published_at"]), _parse_ts(row["fetched_at"])
    return bool(pub and fet and (fet - pub).days > MAX_POST_AGE_DAYS)


def _parse_ts(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ boats

def load_known_boats(path: Path | None = None) -> dict[str, list[str]]:
    """{boat name: [landings]} for boats seen in the last ~2 years."""
    path = path or TRACKER_DB_PATH
    out: dict[str, set] = {}
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cutoff = (date.today() - timedelta(days=730)).isoformat()
        for b, l in c.execute("SELECT DISTINCT boat, landing FROM trips WHERE date >= ?", (cutoff,)):
            out.setdefault(b, set()).add(l)
        for b, l in c.execute("SELECT name, landing FROM boats"):
            out.setdefault(b, set()).add(l)
        c.close()
    except sqlite3.Error as e:
        log.warning("could not read boats from %s: %r", path, e)
    return {b: sorted(x for x in ls if x) for b, ls in out.items() if b}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def match_boat(model_choice: str | None, raw: str, known: dict[str, list[str]]) -> str | None:
    """Trust the model's pick only if it is a known name; else normalised exact match."""
    if model_choice and model_choice in known:
        return model_choice
    by_norm = {}
    for b in known:
        by_norm.setdefault(_norm(b), b)
    for cand in (model_choice, raw):
        if cand and _norm(cand) in by_norm:
            return by_norm[_norm(cand)]
    return None


def match_confidence(model_choice: str | None, raw: str, boat: str | None,
                     trip_match: dict | None) -> float:
    """How sure we are that `boat` (a tracker.db name) is the boat the post means.

    0.95  the name as written is the tracker.db name (spacing/punctuation aside)
    0.85  the model's pick only matched after normalising
    0.80  the model mapped a nickname/abbreviation ("PQ") to a known boat
    +0.15 (capped at 1.0) when the landing's own count confirms a trip on that
          boat around the stated dates
    """
    if not boat:
        return 0.0
    if _norm(raw) == _norm(boat):
        c = 0.95
    elif model_choice == boat:
        c = 0.80
    else:
        c = 0.85
    if trip_match:
        c = min(1.0, c + 0.15)
    return round(c, 2)


def match_trip(boat: str, trip_date: str | None, trip_length: str | None,
               path: Path | None = None) -> dict | None:
    """Find the landing's count for this trip: tracker.db dates trips by return day."""
    path = path or TRACKER_DB_PATH
    if not boat or not trip_date:
        return None
    try:
        d0 = date.fromisoformat(trip_date)
    except ValueError:
        return None
    days = LENGTH_DAYS.get(trip_length or "", 1)
    lo, hi = d0, d0 + timedelta(days=int(days + 0.5) + 2)
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT date, landing, trip_length, anglers, full_catch FROM trips "
            "WHERE boat = ? AND date BETWEEN ? AND ? ORDER BY date",
            (boat, lo.isoformat(), hi.isoformat())).fetchall()
        c.close()
    except sqlite3.Error:
        return None
    if trip_length:
        same = [r for r in rows if r[2] == trip_length]
        rows = same or rows
    if not rows:
        return None
    d, landing, length, anglers, full_catch = rows[0]
    try:
        catch = json.loads(full_catch) if full_catch else None
    except ValueError:
        catch = None
    return {"date": d, "landing": landing, "trip_length": length,
            "anglers": anglers, "catch": catch}


# ------------------------------------------------------------------ claude

def build_prompt(row, known: dict[str, list[str]]) -> str:
    body = (row["raw_text"] or "")[:MAX_BODY_CHARS]
    return PROMPT.format(published=(row["published_at"] or "")[:10],
                         boats="; ".join(sorted(known)), title=row["title"] or "", body=body)


def call_claude(prompt: str) -> dict | None:
    """Forced tool call -> the tool input dict. None on failure (error kept in _last_error)."""
    global _client, _last_error
    try:
        if _client is None:
            _client = paddy_extract._get_client()
    except Exception as e:  # noqa: BLE001
        _last_error = f"client init: {e!r}"[:200]
        return None

    def once():
        resp = _client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            tools=[REPORT_TOOL],
            tool_choice={"type": "tool", "name": REPORT_TOOL["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "max_tokens":
            raise ValueError("hit max_tokens")
        for block in resp.content:
            if block.type == "tool_use":
                return block.input
        raise ValueError("no tool_use block")

    for attempt in range(2):
        try:
            return once()
        except Exception as e:  # noqa: BLE001
            _last_error = f"{type(e).__name__}: {str(e)[:200]}"
            log.warning("Claude call failed (%s)%s", _last_error, ", retrying" if not attempt else "")
            if not attempt:
                time.sleep(2.0)
    return None


# ------------------------------------------------------------------ validation

def _clip_quote(q: str) -> str:
    words = q.split()
    return " ".join(words[:QUOTE_MAX_WORDS]) + ("…" if len(words) > QUOTE_MAX_WORDS else "")


def _valid_date(s, published: str | None) -> str | None:
    try:
        d = date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    pub = _parse_ts(published)
    if pub and not (pub.date() - timedelta(days=60) <= d <= pub.date() + timedelta(days=1)):
        return None   # a trip can't start after the report, nor (plausibly) months before
    return d.isoformat()


def validate_entry(e: dict, body: str, published: str | None,
                   known: dict[str, list[str]]) -> dict | None:
    raw = (e.get("boat_raw") or "").strip()
    if not raw:
        return None
    quotes_in = e.get("quotes") or {}
    quotes: dict[str, str] = {}
    out = {"boat_raw": raw[:80], "boat": match_boat(e.get("boat"), raw, known)}
    for a in ASPECTS:
        v = e.get(a)
        q = quotes_in.get(a)
        ok = isinstance(v, int) and not isinstance(v, bool) and -2 <= v <= 2
        if ok and q and paddy_extract.quote_matches_source(q, body):
            out[a] = v
            quotes[a] = _clip_quote(q)
        else:
            out[a] = None
    rb, q = e.get("would_rebook"), quotes_in.get("would_rebook")
    if isinstance(rb, bool) and q and paddy_extract.quote_matches_source(q, body):
        out["would_rebook"] = 1 if rb else 0
        quotes["would_rebook"] = _clip_quote(q)
    else:
        out["would_rebook"] = None
    out["quotes"] = quotes
    out["trip_date"] = _valid_date(e.get("trip_date"), published)
    tl = e.get("trip_length")
    out["trip_length"] = tl if tl in TRIP_LENGTHS else None
    cs = e.get("catch_summary")
    out["catch_summary"] = cs.strip()[:200] if isinstance(cs, str) and cs.strip() else None
    out["tackle"] = [str(t)[:120] for t in (e.get("tackle") or []) if str(t).strip()][:5]
    out["spots"] = [str(t)[:60] for t in (e.get("spots") or []) if str(t).strip()][:5]
    for k in ("bait", "conditions"):
        x = e.get(k)
        out[k] = x.strip()[:140] if isinstance(x, str) and x.strip() else None
    out["signals"] = validate_signals(e.get("signals") or {}, body)
    out["locations"] = validate_locations(e.get("locations") or [], body)
    return out


LOC_QUOTE_MAX_WORDS = 25


def _norm_loose(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def validate_locations(items: list, body: str) -> list[dict]:
    """Keep a location only when its quote is in the post and names the place
    (or holds the coordinates). Coordinates and offsets are re-derived from
    the quote in code; the model's numbers are not trusted on their own."""
    out = []
    seen = set()
    for it in items[:MAX_LOCATIONS]:
        if not isinstance(it, dict):
            continue
        q = (it.get("quote") or "").strip()
        if not q or len(q.split()) > LOC_QUOTE_MAX_WORDS or not paddy_extract.quote_matches_source(q, body):
            continue
        kind = it.get("kind") if it.get("kind") in LOCATION_KINDS else "area"
        name = (it.get("name") or "").strip()[:60] or None
        nq = _norm_loose(q)
        if name and _norm_loose(name) not in nq:
            # the model normalised the spelling; keep it only if some word survives
            words = [w for w in _norm_loose(name).split() if len(w) > 2 and w not in ("the", "bank", "island")]
            if not any(w in nq.split() for w in words):
                name = None
        parsed = coords_mod.parse_coords(q)
        lat = lon = None
        if parsed and coords_mod.in_wide_box(parsed["lat"], parsed["lon"]):
            lat, lon = parsed["lat"], parsed["lon"]
            kind = "coords"
        if not name and lat is None:
            continue
        dist = coords_mod.distance_from_words(q)
        bearing = coords_mod.bearing_from_words(q) if dist is not None else None
        from_place = (it.get("from_place") or "").strip()[:60] or None
        if dist is not None and from_place and _norm_loose(from_place) not in nq:
            from_place = None
        if dist is not None and from_place and not name:
            name = from_place
        species = sorted({x for x in (it.get("species") or []) if x in LOCATION_SPECIES})
        quality = it.get("quality") if it.get("quality") in LOCATION_QUALITY else None
        wt = it.get("water_temp_f")
        wt = float(wt) if isinstance(wt, (int, float)) and not isinstance(wt, bool) and 50 <= wt <= 90 \
            and re.search(r"\d", q) else None
        key = (_norm_loose(name or ""), lat, lon, kind)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "kind": kind, "distance_nm": dist if dist and dist <= 300 else None,
                    "bearing_deg": bearing, "from_place": from_place if dist else None,
                    "lat": lat, "lon": lon, "species": species, "quality": quality,
                    "water_temp_f": wt, "quote": q})
    return out


def validate_signals(sig: dict, body: str) -> dict:
    """Keep a signal only when it has the right type/range AND a quote found in the post."""
    ev_in = sig.get("evidence") or {}
    out: dict = {}
    evidence: dict[str, str] = {}

    def quoted(k):
        q = ev_in.get(k)
        if q and paddy_extract.quote_matches_source(q, body):
            evidence[k] = _clip_quote(q)
            return True
        return False

    def num(x, lo, hi):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi

    checks = {
        "bird_pressure": lambda x: isinstance(x, int) and num(x, 0, 3),
        "bait_type":     lambda x: x in BAIT_TYPES,
        "bait_size_in":  lambda x: num(x, 0.5, 14),
        "bait_quality":  lambda x: isinstance(x, int) and num(x, -2, 2),
        "water_temp_f":  lambda x: num(x, 50, 90),
        "water_color":   lambda x: x in WATER_COLORS,
    }
    unverified = []
    for k, ok in checks.items():
        v = sig.get(k)
        if v is not None and ok(v) and quoted(k):
            out[k] = v
        else:
            out[k] = None
            if v is not None:
                unverified.append(k)
    bw = [w for w in (sig.get("bite_windows") or []) if w in BITE_WINDOWS]
    if bw and quoted("bite_windows"):
        out["bite_windows"] = sorted(set(bw), key=BITE_WINDOWS.index)
    else:
        out["bite_windows"] = []
        if bw:
            unverified.append("bite_windows")
    out["unverified"] = unverified
    sg = sig.get("size_grade")
    out["size_grade"] = sg.strip()[:120] if isinstance(sg, str) and sg.strip() else None
    out["evidence"] = evidence
    return out


def has_signals(sig: dict) -> bool:
    return any(sig.get(k) not in (None, []) for k in SIGNAL_FIELDS)


# ------------------------------------------------------------------ run

def _record_run(conn, source_id: str, status: str, error: str | None = None):
    conn.execute(
        "INSERT INTO boat_report_runs (source_id, status, attempts, last_error, extracted_at) "
        "VALUES (?, ?, 1, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
        "status = excluded.status, attempts = attempts + 1, "
        "last_error = excluded.last_error, extracted_at = excluded.extracted_at",
        (source_id, status, error, _now_iso()))


def process_row(conn, row, known, *, dry_run=False) -> dict:
    if len((row["raw_text"] or "").strip()) < MIN_BODY_CHARS:
        if not dry_run:
            _record_run(conn, row["id"], "not_report", "body too short")
            conn.commit()
        return {"ok": True, "entries": 0}
    result = call_claude(build_prompt(row, known))
    if result is None:
        if not dry_run:
            _record_run(conn, row["id"], "failed", _last_error)
            conn.commit()
        return {"ok": False, "entries": 0}
    body = row["raw_text"] or ""
    entries = []
    if result.get("is_trip_report"):
        for e in result.get("boats") or []:
            v = validate_entry(e, body, row["published_at"], known)
            # No date and no length = usually an aside about some other trip.
            if v and (v["trip_date"] or v["trip_length"]):
                v["trip_match"] = match_trip(v["boat"], v["trip_date"], v["trip_length"]) if v["boat"] else None
                v["match_confidence"] = match_confidence(e.get("boat"), v["boat_raw"], v["boat"], v["trip_match"])
                v["landing"] = (v["trip_match"] or {}).get("landing") or (
                    known.get(v["boat"], [None])[0] if v["boat"] and len(known.get(v["boat"], [])) == 1 else None)
                entries.append(v)
    if dry_run:
        print(json.dumps({"title": row["title"], "is_trip_report": result.get("is_trip_report"),
                          "entries": entries}, indent=1, ensure_ascii=False))
        return {"ok": True, "entries": len(entries)}
    conn.execute("DELETE FROM forum_boat_reports WHERE source_id = ?", (row["id"],))
    # forum_signals is append-only (research needs what was knowable when):
    # if this post already has signal rows, keep them as they are.
    signals_frozen = conn.execute("SELECT 1 FROM forum_signals WHERE source_id = ?",
                                  (row["id"],)).fetchone() is not None
    locations_frozen = conn.execute("SELECT 1 FROM forum_locations WHERE source_id = ?",
                                    (row["id"],)).fetchone() is not None
    now = _now_iso()
    for v in entries:
        conn.execute(
            "INSERT INTO forum_boat_reports (source_id, feed_id, boat_raw, boat, landing, "
            "trip_date, trip_length, overall, captain, crew, galley, bunks, fish_finding, "
            "would_rebook, quotes, catch_summary, tackle, spots, bait, conditions, trip_match, "
            "match_confidence, extracted_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["feed_id"], v["boat_raw"], v["boat"], v["landing"],
             v["trip_date"], v["trip_length"], *(v[a] for a in ASPECTS), v["would_rebook"],
             json.dumps(v["quotes"], ensure_ascii=False), v["catch_summary"],
             json.dumps(v["tackle"], ensure_ascii=False), json.dumps(v["spots"], ensure_ascii=False),
             v["bait"], v["conditions"],
             json.dumps(v["trip_match"]) if v["trip_match"] else None,
             v["match_confidence"], now))
        sig = v["signals"]
        if not signals_frozen and (has_signals(sig) or sig.get("size_grade") or sig.get("unverified")):
            conn.execute(
                "INSERT INTO forum_signals (source_id, feed_id, boat, trip_date, trip_length, "
                "published_at, spots, bird_pressure, bait_type, bait_size_in, bait_quality, "
                "water_temp_f, water_color, bite_windows, size_grade, evidence, unverified, "
                "fetched_at, trip_match, match_confidence, extracted_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], row["feed_id"], v["boat"], v["trip_date"], v["trip_length"],
                 row["published_at"], json.dumps(v["spots"], ensure_ascii=False),
                 sig["bird_pressure"], sig["bait_type"], sig["bait_size_in"], sig["bait_quality"],
                 sig["water_temp_f"], sig["water_color"], json.dumps(sig["bite_windows"]),
                 sig["size_grade"], json.dumps(sig["evidence"], ensure_ascii=False),
                 json.dumps(sig.get("unverified") or []), row["fetched_at"],
                 json.dumps(v["trip_match"]) if v["trip_match"] else None,
                 v["match_confidence"], now))
        if not locations_frozen:
            for loc in v.get("locations") or []:
                conn.execute(
                    "INSERT INTO forum_locations (source_id, feed_id, boat, trip_date, trip_length, "
                    "published_at, fetched_at, name, kind, distance_nm, bearing_deg, from_place, "
                    "lat, lon, species, quality, water_temp_f, quote, extracted_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["id"], row["feed_id"], v["boat"], v["trip_date"], v["trip_length"],
                     row["published_at"], row["fetched_at"], loc["name"], loc["kind"],
                     loc["distance_nm"], loc["bearing_deg"], loc["from_place"], loc["lat"], loc["lon"],
                     json.dumps(loc["species"]), loc["quality"], loc["water_temp_f"], loc["quote"], now))
    _record_run(conn, row["id"], "ok" if entries else "not_report")
    conn.commit()
    return {"ok": True, "entries": len(entries)}


def run(limit: int | None = DEFAULT_RUN_LIMIT, dry_run: bool = False,
        db_path: Path | None = None) -> dict:
    conn = open_db(db_path)
    try:
        known = load_known_boats()
        rows = pending_rows(conn, limit)
        stats = {"posts": 0, "ok": 0, "failed": 0, "entries": 0,
                 "pending_after": 0}
        global _last_error
        streak = 0
        needs_claude = [r for r in rows if len((r["raw_text"] or "").strip()) >= MIN_BODY_CHARS]
        if needs_claude and not os.environ.get("ANTHROPIC_API_KEY") and _client is None:
            _last_error = "ANTHROPIC_API_KEY is not set"
            print(f"[boat_reports] {_last_error}; skipping {len(rows)} posts", file=sys.stderr)
            stats.update(posts=len(rows), failed=len(rows), pending_after=len(pending_rows(conn)))
            return stats
        for row in rows:
            if streak >= paddy_extract.MAX_CONSECUTIVE_FAILURES:
                print(f"[boat_reports] {streak} failures in a row ({_last_error}); stopping",
                      file=sys.stderr)
                break
            stats["posts"] += 1
            r = process_row(conn, row, known, dry_run=dry_run)
            stats["ok" if r["ok"] else "failed"] += 1
            streak = 0 if r["ok"] else streak + 1
            stats["entries"] += r["entries"]
            print(f"  [{row['id'][:10]}] {(row['title'] or '')[:60]!r:62} "
                  f"{'entries=' + str(r['entries']) if r['ok'] else 'FAILED'}")
            time.sleep(REQUEST_SLEEP)
        stats["pending_after"] = len(pending_rows(conn))
        return stats
    finally:
        conn.close()


# ------------------------------------------------------------------ export

def _bucket(v):
    return None if v is None else ("pos" if v > 0 else "neg" if v < 0 else "mixed")


def _dedupe_quotes(quotes: dict) -> dict:
    """Same sentence backing several aspects -> keep it once, under the first aspect."""
    seen, out = set(), {}
    for k in (*ASPECTS, "would_rebook"):
        q = quotes.get(k)
        if q and paddy_extract._normalize_for_quote_match(q).lower() not in seen:
            seen.add(paddy_extract._normalize_for_quote_match(q).lower())
            out[k] = q
    return out


_GAZ = None


def _gazetteer():
    global _GAZ
    if _GAZ is None:
        from .spots import Gazetteer     # late import: spots reads the DB tables defined here
        _GAZ = Gazetteer()
    return _GAZ


def _row_region(r, gaz=None) -> str | None:
    """san_diego | oc_la | both | None for one forum_boat_reports row (+ its source)."""
    gaz = gaz or _gazetteer()
    keys = r.keys()
    # 4+ day trips pass half of SoCal on the way south: the landing decides.
    long_trip = LENGTH_DAYS.get(r["trip_length"] or "", 0) >= 4
    places = [] if long_trip else [gaz.lookup(sp) for sp in json.loads(r["spots"] or "[]")]
    landing = r["landing"] if "landing" in keys else None
    return regions_mod.item_region(landings=[landing] if landing else [],
                                   places=[p for p in places if p],
                                   title=r["title"] if "title" in keys else None,
                                   feed_id=r["feed_id"])


def build_export(conn, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=EXPORT_WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT f.*, s.url, s.title, s.published_at FROM forum_boat_reports f "
        "JOIN paddy_sources s ON s.id = f.source_id "
        "WHERE f.boat IS NOT NULL AND s.published_at >= ? "
        "AND COALESCE(f.match_confidence, 0) >= ? "
        "ORDER BY s.published_at DESC", (cutoff, MATCH_CONFIDENCE_MIN)).fetchall()
    gaz = _gazetteer()
    boats: dict[str, dict] = {}
    for r in rows:
        b = boats.setdefault(r["boat"], {
            "landing": None, "region": None, "report_count": 0,
            "aspects": {a: {"pos": 0, "mixed": 0, "neg": 0} for a in ASPECTS},
            "rebook": {"yes": 0, "no": 0}, "reports": []})
        b["landing"] = b["landing"] or r["landing"]
        b["region"] = b["region"] or regions_mod.region_for_landing(b["landing"])
        b["report_count"] += 1
        for a in ASPECTS:
            k = _bucket(r[a])
            if k:
                b["aspects"][a][k] += 1
        if r["would_rebook"] is not None:
            b["rebook"]["yes" if r["would_rebook"] else "no"] += 1
        feed = get_feed(r["feed_id"]) or {}
        b["reports"].append({
            "title": r["title"], "url": r["url"], "published_at": r["published_at"],
            "forum": feed.get("name", "BloodyDecks"),
            "trip_date": r["trip_date"], "trip_length": r["trip_length"],
            "scores": {a: r[a] for a in ASPECTS if r[a] is not None},
            "would_rebook": None if r["would_rebook"] is None else bool(r["would_rebook"]),
            "quotes": _dedupe_quotes(json.loads(r["quotes"] or "{}")),
            "catch_summary": r["catch_summary"],
            "tackle": json.loads(r["tackle"] or "[]"),
            "spots": json.loads(r["spots"] or "[]"),
            "region": _row_region(r, gaz),
            "landing_count": json.loads(r["trip_match"]) if r["trip_match"] else None,
            "match_confidence": r["match_confidence"],
        })
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "BloodyDecks (bdoutdoors.com) forum trip reports",
        "label": "From BloodyDecks trip reports",
        "note": ("Summaries of public forum posts, extracted automatically. "
                 "Not verified reviews; follow the links for the original posts."),
        "window_days": EXPORT_WINDOW_DAYS,
        "min_match_confidence": MATCH_CONFIDENCE_MIN,
        "regions_note": ("region: san_diego | oc_la | both | null, from the boat's landing and the "
                         "spots fished (an SD boat at Catalina is 'both'). Boat-level region = landing."),
        "boats": dict(sorted(boats.items())),
    }


# ------------------------------------------------------------------ what's working

TRIP_CLASSES = [
    ("short",      "Half & 3/4 day",       {"1/2 Day", "3/4 Day"}),
    ("full",       "Full day & overnight", {"Full Day", "Overnight"}),
    ("multi",      "1.5 to 3.5 day",       {"1.5 Day", "2 Day", "2.5 Day", "3 Day", "3.5 Day"}),
    ("extended",   "4 to 7 day",           {"4 Day", "5 Day", "6 Day", "7 Day"}),
    ("long_range", "Long range (8+ days)", {f"{n} Day" for n in range(8, 17)}),
]
WW_WINDOW_DAYS = 21            # "what's working" = recent; fall back once if thin
WW_FALLBACK_DAYS = 45
WW_MIN_REPORTS = 2
WW_MAX_ITEMS = 8


def trip_class(length: str | None) -> str | None:
    for key, _label, lengths in TRIP_CLASSES:
        if length in lengths:
            return key
    return None


HEADLINE_MAX = 90


def _shorten(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"


def make_headline(top_spots: list[str], items: list[dict]) -> str | None:
    """One line for a collapsed card: top spots, then the newest report's lead tackle note.

    Built from the same extracted fields the card shows (no extra Claude call),
    e.g. "Colonet and the Ridge · 40 lb fluoro, #1 circle".
    """
    parts = []
    if top_spots:
        parts.append(" and ".join(top_spots[:2]))
    lead = next((it for it in items if it.get("tackle") or it.get("bait")), None)
    if lead:
        first = (lead.get("tackle") or [None])[0] or lead["bait"]
        parts.append(_shorten(first, 45))
    if not parts:
        return None
    return _shorten(" · ".join(parts), HEADLINE_MAX)


def _src(r) -> str:
    return r["source"] if "source" in r.keys() else "forum"


def _landing_ww_rows(conn, oldest: str) -> list[dict]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='landing_notes'").fetchone():
        return []
    from .landing_reports import ww_rows
    return ww_rows(conn, oldest)


def _report_day(r) -> str:
    return r["trip_date"] or (r["published_at"] or "")[:10]


def build_whats_working(conn, now: datetime | None = None) -> dict:
    """Per trip type: recent tackle / bait / conditions notes, each linked to its thread."""
    now = now or datetime.now(timezone.utc)
    oldest = (now - timedelta(days=WW_FALLBACK_DAYS)).date().isoformat()
    rows = conn.execute(
        "SELECT f.*, s.url, s.title, s.published_at FROM forum_boat_reports f "
        "JOIN paddy_sources s ON s.id = f.source_id "
        "WHERE COALESCE(f.trip_date, substr(s.published_at, 1, 10)) >= ? "
        "ORDER BY COALESCE(f.trip_date, substr(s.published_at, 1, 10)) DESC", (oldest,)).fetchall()
    rows = list(rows) + _landing_ww_rows(conn, oldest)
    rows.sort(key=_report_day, reverse=True)
    gaz = _gazetteer()
    region_of = {r["id"]: (r["region"] if _src(r) == "landing" else _row_region(r, gaz)) for r in rows}
    by_region = {reg: _ww_classes([r for r in rows if regions_mod.in_region(region_of[r["id"]], reg)],
                                  now, region_of)
                 for reg in (regions_mod.SD, regions_mod.OCLA)}
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": "What's working, from BloodyDecks trip reports and the landings' reports",
        "note": "Automatic summaries of recent public forum posts; follow the links for details.",
        "classes": _ww_classes(rows, now, region_of),
        "by_region": by_region,
        "regions_note": ("classes = every report; by_region.<san_diego|oc_la> = reports from that "
                         "region's landings or spots (a 'both' report is in each)."),
    }


def _ww_classes(rows, now, region_of) -> dict:
    classes = {}
    for key, label, _lengths in TRIP_CLASSES:
        mine = [r for r in rows if trip_class(r["trip_length"]) == key
                and (json.loads(r["tackle"] or "[]") or r["bait"] or r["conditions"])]
        window = WW_WINDOW_DAYS
        cutoff = (now - timedelta(days=window)).date().isoformat()
        recent = [r for r in mine if _report_day(r) >= cutoff]
        if len(recent) < WW_MIN_REPORTS:
            window, recent = WW_FALLBACK_DAYS, mine
        spot_counts: dict[str, int] = {}
        spot_names: dict[str, str] = {}       # case/spacing-insensitive merge
        for r in recent:
            for sp in json.loads(r["spots"] or "[]"):
                k = re.sub(r"\s+", " ", sp.strip().lower())
                spot_names.setdefault(k, sp.strip())
                spot_counts[k] = spot_counts.get(k, 0) + 1
        items = [{
            "boat": r["boat"] if (r["match_confidence"] or 0) >= MATCH_CONFIDENCE_MIN else None,
            "trip_length": r["trip_length"], "trip_date": r["trip_date"],
            "title": r["title"], "url": r["url"],
            "tackle": json.loads(r["tackle"] or "[]")[:4],
            "bait": r["bait"], "conditions": r["conditions"],
            "region": region_of.get(r["id"]),
            "source": _src(r),          # forum (BloodyDecks) | landing (landing / skipper post)
        } for r in recent[:WW_MAX_ITEMS]]
        top_spots = [spot_names[k] for k, _ in
                     sorted(spot_counts.items(), key=lambda x: (-x[1], x[0]))][:5]
        classes[key] = {
            "label": label,
            "headline": make_headline(top_spots, items),
            "window_days": window,
            "report_count": len(recent),
            "top_spots": top_spots,
            "items": items,
        }
    return classes


def write_whats_working(path: Path = WHATS_WORKING_PATH, db_path: Path | None = None) -> dict:
    conn = open_db(db_path)
    try:
        data = build_whats_working(conn)
    finally:
        conn.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def write_signals_csv(path: Path, db_path: Path | None = None) -> int:
    """Research hand-off: forum_signals joined to source URL, as CSV (not published)."""
    import csv
    conn = open_db(db_path)
    try:
        rows = conn.execute(
            "SELECT g.*, s.url FROM forum_signals g JOIN paddy_sources s ON s.id = g.source_id "
            "ORDER BY COALESCE(g.trip_date, g.published_at)").fetchall()
    finally:
        conn.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        cols = [k for k in rows[0].keys() if k != "id"] if rows else []
        w.writerow(cols)
        for r in rows:
            w.writerow([r[k] for k in cols])
    return len(rows)


def write_export(path: Path = EXPORT_PATH, db_path: Path | None = None) -> dict:
    conn = open_db(db_path)
    try:
        data = build_export(conn)
    finally:
        conn.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def record_health(stats: dict, path: Path | None = None) -> None:
    """Fold this run into the shared state file (boat_reports_* keys)."""
    path = path or STATE_PATH
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        state = {}
    now = _now_iso()
    state["boat_reports_last_run_utc"] = now
    if stats["posts"] == 0 or stats["failed"] < stats["posts"]:
        state["boat_reports_last_success_utc"] = now
        state["boat_reports_last_error"] = None
    else:
        state["boat_reports_last_error"] = _last_error or "all posts failed"
    state["boat_reports_pending"] = stats["pending_after"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BloodyDecks party-boat trip reports")
    ap.add_argument("--limit", type=int, default=DEFAULT_RUN_LIMIT,
                    help=f"max Claude calls this run (default {DEFAULT_RUN_LIMIT}; 0 = no cap)")
    ap.add_argument("--dry-run", action="store_true", help="print results, write nothing")
    ap.add_argument("--export-only", action="store_true", help="skip Claude, just write the JSON")
    ap.add_argument("--signals-csv", type=Path,
                    help="write the research-only forum_signals table to this CSV and exit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.signals_csv:
        n = write_signals_csv(args.signals_csv)
        print(f"[boat_reports] wrote {n} signal rows to {args.signals_csv}")
        return 0

    if not args.export_only:
        print(f"[boat_reports] db={DB_PATH} model={MODEL} dry_run={args.dry_run}")
        stats = run(limit=args.limit or None, dry_run=args.dry_run)
        for k, v in stats.items():
            print(f"  {k}: {v}")
        if not args.dry_run:
            record_health(stats)
        if args.dry_run:
            return 0
        if stats["posts"] and stats["failed"] == stats["posts"]:
            print("[boat_reports] all posts failed; exporting what we have", file=sys.stderr)
            write_export()
            write_whats_working()
            return 2
    data = write_export()
    ww = write_whats_working()
    print(f"[boat_reports] wrote {EXPORT_PATH.name}: {len(data['boats'])} boats, "
          f"{sum(b['report_count'] for b in data['boats'].values())} reports; "
          f"{WHATS_WORKING_PATH.name}: "
          + ", ".join(f"{k}={c['report_count']}" for k, c in ww['classes'].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
