"""
Claude-powered extraction of paddy sightings from paddy_sources rows.

For each row where extracted=0:
  * Build a prompt with the post title/body + a compact gazetteer summary
    (id -> aliases). Feed to Claude (model matches src/reddit_insights.py).
  * Parse the JSON array response. Validate bank ids against the gazetteer;
    unknown ids become null and are logged.
  * Idempotent per source: DELETE existing mentions for that source_id,
    then INSERT the new set. Mark extracted=1.
  * On API/JSON failure: log, leave extracted=0, continue.

Rate-limited, retries once with backoff on API errors.

Usage:
    .venv/Scripts/python.exe -m scraper.paddies.extract           # all pending
    .venv/Scripts/python.exe -m scraper.paddies.extract --limit 5 # first 5
    .venv/Scripts/python.exe -m scraper.paddies.extract --dry-run # don't write
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
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import coords

# Load .env from project root if present (matches src/reddit_insights.py).
# No-op if python-dotenv isn't installed or .env is absent.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("PADDIES_DB") or (ROOT / "data" / "paddies.db"))
GAZETTEER_PATH = ROOT / "data" / "banks.geojson"

from .feeds import feed_ids as _feed_ids

# Boat-report feeds (Sportboats, Long Range) are read by boat_reports.py,
# not here; their posts would only produce noise paddy/bite mentions.
PADDY_FEED_IDS = _feed_ids("paddies")

# Sonnet: a Haiku test on 8 posts matched only 26 of 35 mentions (banks often
# differed), so the paddy map stays on Sonnet. PADDIES_MODEL overrides it.
MODEL = os.environ.get("PADDIES_MODEL") or "claude-sonnet-4-6"
MAX_TOKENS = 3000            # wider v2 schema can yield more mentions per post
REQUEST_SLEEP = 0.5          # polite gap between successful calls (seconds)
RETRY_BACKOFF = 2.0          # single retry after this many seconds
# Stop the run after this many posts fail in a row: it is the client or the
# key that is broken, not the posts, and retrying hundreds of posts just burns
# the job's time budget before the commit step.
MAX_CONSECUTIVE_FAILURES = 5
DB_TIMEOUT_SECONDS = 30
DB_BUSY_TIMEOUT_MS = 30000

TRUNCATED_HINT = (
    "\nNOTE: this post is truncated at ~500 chars (RSS excerpt only). "
    "Report only what is present. Do not invent details for content that "
    "may exist past the cut-off.\n"
)

ALLOWED_SPECIES = {"yellowtail", "dorado", "yellowfin", "bluefin"}
# Bite widens the species list per v2 spec.
ALLOWED_SPECIES_BITE = ALLOWED_SPECIES | {
    "calico", "rockfish", "marlin", "wahoo", "seabass",
    "halibut", "barracuda", "bonito",
}
ALLOWED_METHOD      = {"flyline","yoyo","surface_iron","troll","kite",
                       "sonar","dropper","other"}
ALLOWED_BAIT        = {"sardine","anchovy","mackerel","squid","artificial"}
ALLOWED_OUTCOME     = {"wide_open","steady","scratchy","skunk"}
ALLOWED_WATER_COLOR = {"blue","green","dirty","off"}
ALLOWED_CURRENT     = {"strong","light","none"}
ALLOWED_LIFE        = {"birds","porpoise","jumpers","breezers","mola"}
ALLOWED_SEA_STATE   = {"flat","bumpy","rough"}

MENTION_TYPES = {"paddy", "bite", "conditions", "position"}

# Generic-word bank ids — matching these caps confidence at 0.5 per rule 7 of
# the gazetteer spec. Kept small and hand-curated; grow via evidence, not
# guesses.
GENERIC_BANK_IDS = {
    "the-corner", "the-worm", "the-boot", "the-slide",
    "the-airplane", "rockpile", "hardbottom",
}

MAX_CONF_GENERIC = 0.5   # generic-term bank match
MAX_CONF_OFFSET  = 0.7   # position with precision=offset


# ------------------------------------------------------------------ quote/source comparison

def _normalize_for_quote_match(s: str) -> str:
    """
    Prep a string for verbatim quote-in-source comparison.

    - NFKC: fold typographic variants (curly quotes, non-breaking spaces,
      fullwidth punctuation) into their canonical forms so `couldn’t`
      (U+2019) compares equal to `couldn't` (U+0027).
    - Whitespace collapsed to single spaces (line breaks in source don't
      matter for quote matching).

    We deliberately keep the model's quote as-returned in the DB (per spec
    for the mentions field) — the normalization is only for verification.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("‘", "'").replace("’", "'")   # left/right single quotes
    s = s.replace("“", '"').replace("”", '"')   # left/right double quotes
    s = s.replace("–", "-").replace("—", "-")   # en/em dash
    s = s.replace("…", "...")                          # horizontal ellipsis
    s = re.sub(r"\s+", " ", s).strip()
    return s


def quote_matches_source(quote: str, source_text: str) -> bool:
    """True iff `quote` appears as a substring of `source_text` after both
    are NFKC-normalized. Used by verification tooling — does not change
    what gets stored."""
    if not quote or not source_text:
        return False
    return _normalize_for_quote_match(quote) in _normalize_for_quote_match(source_text)

log = logging.getLogger("paddies.extract")

REPORT_MENTIONS_SCHEMA = """
-- v2 report_mentions supersedes v1 paddy_mentions. Wider schema: each
-- mention is typed (paddy | bite | conditions | position), carries its
-- feed_id and resolved coordinate (when the model or code produced one),
-- and stores type-specific fields in `payload` (JSON).
CREATE TABLE IF NOT EXISTS report_mentions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT NOT NULL,
    feed_id        TEXT NOT NULL,
    type           TEXT NOT NULL,              -- paddy | bite | conditions | position
    trip_date      TEXT,                       -- YYYY-MM-DD or NULL
    bank           TEXT,                       -- gazetteer feature id or NULL
    lat            REAL,                       -- resolved coordinate, if any
    lon            REAL,
    "precision"    TEXT,                       -- gps | offset | bank | NULL
    payload        TEXT NOT NULL DEFAULT '{}', -- type-specific fields (JSON)
    confidence     REAL,
    quote          TEXT,
    extracted_at   TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES paddy_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_report_mentions_source  ON report_mentions(source_id);
CREATE INDEX IF NOT EXISTS idx_report_mentions_bank    ON report_mentions(bank);
CREATE INDEX IF NOT EXISTS idx_report_mentions_date    ON report_mentions(trip_date);
CREATE INDEX IF NOT EXISTS idx_report_mentions_type    ON report_mentions(type);
CREATE INDEX IF NOT EXISTS idx_report_mentions_feed    ON report_mentions(feed_id);
"""


# ------------------------------------------------------------------ client

_client = None
_last_error: str | None = None   # last Claude failure, recorded in health state


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


# ------------------------------------------------------------------ gazetteer

def load_gazetteer(path: Path = GAZETTEER_PATH) -> dict:
    """Return {'valid_ids': set[str], 'prompt_lines': str, 'id_to_coord': dict}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    valid_ids: set[str] = set()
    id_to_coord: dict[str, tuple[float, float]] = {}
    lines: list[str] = []
    for feat in data["features"]:
        p = feat["properties"]
        if p["kind"] == "admin":
            continue  # per rule 6: admin excluded from matching
        valid_ids.add(p["id"])
        lon, lat = feat["geometry"]["coordinates"]
        id_to_coord[p["id"]] = (lat, lon)
        aliases = p.get("aliases") or []
        head = p["id"]
        if p["name"].lower() != p["id"].replace("-", " "):
            head += f" ({p['name']})"
        if aliases:
            head += ": " + ", ".join(aliases)
        lines.append(head)
    return {
        "valid_ids":  valid_ids,
        "prompt_lines": "\n".join(sorted(lines)),
        "id_to_coord": id_to_coord,
    }


# ------------------------------------------------------------------ prompt

PROMPT_TEMPLATE = """You extract fishing observations from a SoCal offshore forum post.

TITLE: {title}
PUBLISHED: {published_at}
BODY:
\"\"\"
{body}
\"\"\"

GAZETTEER (id → aliases; only ids from this list are valid):
{gazetteer_lines}

Return a JSON ARRAY of TYPED observations. Every element has these common fields:
  "type":         "paddy" | "bite" | "conditions" | "position"
  "trip_date":    "YYYY-MM-DD" or null   (day the trip actually happened)
  "bank":         "<gazetteer id>" or null
  "position_ref": integer index into THIS array pointing to a "position" element, or null
  "confidence":   0.0-1.0
  "quote":        "<=25 words verbatim from BODY that supports this element"

Type-specific fields:

type="paddy"  (kelp paddy sighting)
  "paddy_count":  int or null   ("a few"=3, "several"=5, "10 to 15"=12, "no kelp"=0)
  "holding":      true|false|null   (were fish holding under the paddy?)
  "species":      subset of ["yellowtail","dorado","yellowfin","bluefin"]
  "water_temp_f": number or null
  "route":        ordered list of ["<gazetteer id>", ...] if a multi-bank loop is described

type="bite"  (fish caught or bites reported)
  "species":  subset of ["yellowtail","dorado","yellowfin","bluefin","calico",
                          "rockfish","marlin","wahoo","seabass","halibut",
                          "barracuda","bonito"]
  "count":    int or null
  "size_lb":  number or null
  "method":   one of ["flyline","yoyo","surface_iron","troll","kite","sonar","dropper","other"] or null
  "bait":     one of ["sardine","anchovy","mackerel","squid","artificial"] or null
  "outcome":  one of ["wide_open","steady","scratchy","skunk"] or null

type="conditions"  (water / weather / life observations)
  "water_temp_f":  number or null
  "water_color":   one of ["blue","green","dirty","off"] or null
  "current":       one of ["strong","light","none"] or null
  "bait_marks":    true|false|null
  "life":          subset of ["birds","porpoise","jumpers","breezers","mola"]
  "sea_state":     one of ["flat","bumpy","rough"] or null

type="position"  (explicit coordinate or offset from a bank)
  "raw":         "<the coordinate or bearing text EXACTLY as written in BODY>"
  "kind":        "gps" or "offset"
  For kind="gps":
    "lat", "lon" numbers (we re-parse "raw" in code and will use our parse if they disagree)
  For kind="offset":
    "ref_bank":     "<gazetteer id>" (the bank the offset is measured from)
    "bearing_deg":  0-360 (from ref_bank toward the target)
    "distance_nm":  number

Rules:
- If the post has no relevant observations, return [].
- Emit one element per distinct observation. A trip that fishes 3 banks and
  reports a bite at one, a paddy at another, and conditions at all three
  -> up to 5 elements. Do NOT emit more than 12 elements — split hairs and
  merge related observations if you're heading over that.
- Only use bank ids from the gazetteer above.
- "position_ref" ties a non-position element to an explicit position element
  in the same array. Do not set both bank AND position_ref for the same
  element unless the bank is genuinely different from the position (rare).
- Only emit type="position" if the post EXPLICITLY writes a coordinate or a
  bearing+distance from a named bank. Do not invent positions.
- "quote" must be verbatim. Do not paraphrase.
- Prefer null over a guess.
- Return ONLY the JSON array. No markdown fences, no prose.
"""


def build_prompt(title: str, published_at: str, body: str, gazetteer_lines: str,
                 truncated: bool = False) -> str:
    body_out = body or "(empty)"
    if truncated:
        body_out = body_out + TRUNCATED_HINT
    return PROMPT_TEMPLATE.format(
        title=title or "(no title)",
        published_at=published_at or "(unknown)",
        body=body_out,
        gazetteer_lines=gazetteer_lines,
    )


# ------------------------------------------------------------------ Claude call

def call_claude(prompt: str) -> list | None:
    """Return the parsed JSON array. None on any failure."""
    try:
        client = _get_client()
    except Exception as e:
        log.error("Claude client init failed: %r", e)
        return None

    def _try_once():
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # strip optional ``` fences
        if text.startswith("```"):
            lines = text.split("\n")
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[1:end]).strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError(f"expected JSON array, got {type(parsed).__name__}")
        return parsed

    try:
        return _try_once()
    except json.JSONDecodeError as e:
        log.warning("JSON decode failed: %s", e)
        return None
    except Exception as e:
        # transient error → retry once
        log.warning("Claude call failed (%r), retrying after %ss", e, RETRY_BACKOFF)
        time.sleep(RETRY_BACKOFF)
        try:
            return _try_once()
        except Exception as e2:
            global _last_error
            _last_error = f"{type(e2).__name__}: {str(e2)[:200]}"
            log.error("Claude retry also failed: %r", e2)
            return None


# ------------------------------------------------------------------ validation

def _as_int(x):
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _as_float(x):
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _as_bool(x):
    if x is True or x is False:
        return x
    return None


def _valid_date(s):
    if not isinstance(s, str):
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _pick_enum(m, key, allowed):
    v = m.get(key)
    if isinstance(v, str) and v.lower() in allowed:
        return v.lower()
    return None


def _subset_of(m, key, allowed):
    v = m.get(key) or []
    if not isinstance(v, list):
        return []
    return sorted({s.lower() for s in v
                    if isinstance(s, str) and s.lower() in allowed})


def _cap_conf(conf, ceiling):
    return None if conf is None else min(conf, ceiling)


def _validate_common(m, valid_ids, source_id):
    """Return (bank, confidence, quote, trip_date, position_ref)."""
    bank = m.get("bank")
    if bank is not None and bank not in valid_ids:
        log.info("[%s] unknown bank id %r -> null", source_id, bank)
        bank = None

    conf = _as_float(m.get("confidence"))
    if conf is not None:
        conf = max(0.0, min(1.0, conf))

    quote = m.get("quote")
    if isinstance(quote, str):
        quote = quote.strip()
        words = quote.split()
        if len(words) > 30:
            quote = " ".join(words[:30])
    else:
        quote = None

    return (bank, conf, quote,
            _valid_date(m.get("trip_date")),
            _as_int(m.get("position_ref")))


def _base_row(mtype, bank, conf, quote, trip_date, pos_ref):
    """Skeleton row shared across paddy/bite/conditions (positions set their own)."""
    return {
        "type":         mtype,
        "trip_date":    trip_date,
        "bank":         bank,
        "lat":          None,
        "lon":          None,
        "precision":    "bank" if bank else None,
        "confidence":   conf,
        "quote":        quote,
        "position_ref": pos_ref,   # transient — stripped in validate_mentions
    }


def _validate_paddy(m, valid_ids, source_id):
    bank, conf, quote, trip_date, pos_ref = _validate_common(m, valid_ids, source_id)
    route = m.get("route") or []
    if not isinstance(route, list):
        route = []
    clean_route = []
    for r in route:
        if isinstance(r, str) and r in valid_ids:
            clean_route.append(r)
        elif isinstance(r, str):
            log.info("[%s] unknown route id %r -> dropped", source_id, r)
    payload = {
        "route":        clean_route,
        "paddy_count":  _as_int(m.get("paddy_count")),
        "holding":      _as_bool(m.get("holding")),
        "species":      _subset_of(m, "species", ALLOWED_SPECIES),
        "water_temp_f": _as_float(m.get("water_temp_f")),
    }
    if bank in GENERIC_BANK_IDS:
        conf = _cap_conf(conf, MAX_CONF_GENERIC)
    row = _base_row("paddy", bank, conf, quote, trip_date, pos_ref)
    row["payload"] = json.dumps(payload)
    return row


def _validate_bite(m, valid_ids, source_id):
    bank, conf, quote, trip_date, pos_ref = _validate_common(m, valid_ids, source_id)
    payload = {
        "species": _subset_of(m, "species", ALLOWED_SPECIES_BITE),
        "count":   _as_int(m.get("count")),
        "size_lb": _as_float(m.get("size_lb")),
        "method":  _pick_enum(m, "method",  ALLOWED_METHOD),
        "bait":    _pick_enum(m, "bait",    ALLOWED_BAIT),
        "outcome": _pick_enum(m, "outcome", ALLOWED_OUTCOME),
    }
    if bank in GENERIC_BANK_IDS:
        conf = _cap_conf(conf, MAX_CONF_GENERIC)
    row = _base_row("bite", bank, conf, quote, trip_date, pos_ref)
    row["payload"] = json.dumps(payload)
    return row


def _validate_conditions(m, valid_ids, source_id):
    bank, conf, quote, trip_date, pos_ref = _validate_common(m, valid_ids, source_id)
    payload = {
        "water_temp_f": _as_float(m.get("water_temp_f")),
        "water_color":  _pick_enum(m, "water_color", ALLOWED_WATER_COLOR),
        "current":      _pick_enum(m, "current",     ALLOWED_CURRENT),
        "bait_marks":   _as_bool(m.get("bait_marks")),
        "life":         _subset_of(m, "life",        ALLOWED_LIFE),
        "sea_state":    _pick_enum(m, "sea_state",   ALLOWED_SEA_STATE),
    }
    if bank in GENERIC_BANK_IDS:
        conf = _cap_conf(conf, MAX_CONF_GENERIC)
    row = _base_row("conditions", bank, conf, quote, trip_date, pos_ref)
    row["payload"] = json.dumps(payload)
    return row


def _validate_position(m, valid_ids, source_id, id_to_coord):
    """
    kind='gps': parse `raw` in code; if model supplied lat/lon and it disagrees
                with the code parse by more than the tolerance, code wins.
                Sanity + on-land test either way.
    kind='offset': resolve ref_bank via gazetteer, take bearing/distance from
                the raw text (fall back to model's values), apply flat-earth
                offset. If bearing/distance absent, precision falls back to
                'bank' with the ref bank's own coords.
    """
    _, conf, quote, trip_date, _ = _validate_common(m, valid_ids, source_id)
    raw = m.get("raw") if isinstance(m.get("raw"), str) else ""
    kind = m.get("kind") if m.get("kind") in ("gps", "offset") else None

    lat = lon = None
    precision = None
    ref_bank_id = None
    bearing_deg = None
    distance_nm = None

    if kind == "gps":
        parsed = coords.parse_coords(raw)
        model_lat = _as_float(m.get("lat"))
        model_lon = _as_float(m.get("lon"))
        if parsed:
            code_pair = (parsed["lat"], parsed["lon"])
            if model_lat is not None and model_lon is not None:
                if not coords.coords_agree((model_lat, model_lon), code_pair):
                    log.info("[%s] model/code coord disagree: model=(%s,%s) "
                             "code=%s -> using code parse",
                             source_id, model_lat, model_lon, code_pair)
            if coords.valid_offshore(*code_pair):
                lat, lon = code_pair
                precision = "gps"
            else:
                log.info("[%s] gps parse out of sanity or on land: %s",
                         source_id, code_pair)
        else:
            log.info("[%s] raw coord %r unparseable", source_id, raw)

    elif kind == "offset":
        ref_bank = m.get("ref_bank")
        if isinstance(ref_bank, str) and ref_bank in valid_ids:
            ref_bank_id = ref_bank
            model_bearing  = _as_float(m.get("bearing_deg"))
            model_distance = _as_float(m.get("distance_nm"))
            code_bearing  = coords.bearing_from_words(raw)
            code_distance = coords.distance_from_words(raw)
            bearing_deg = code_bearing if code_bearing is not None else model_bearing
            distance_nm = code_distance if code_distance is not None else model_distance
            if id_to_coord and ref_bank_id in id_to_coord:
                rlat, rlon = id_to_coord[ref_bank_id]
                if bearing_deg is not None and distance_nm is not None:
                    lat, lon = coords.apply_offset(rlat, rlon, bearing_deg, distance_nm)
                    if coords.valid_offshore(lat, lon):
                        precision = "offset"
                    else:
                        # Offset from an inshore ref (or in a direction that
                        # crosses land) can land on shore. Fall back to the
                        # ref bank's own coord — same as the no-distance path.
                        log.info("[%s] offset result out of sanity: (%s,%s) "
                                 "-> falling back to ref bank coord",
                                 source_id, lat, lon)
                        lat, lon = rlat, rlon
                        precision = "bank"
                else:
                    # No distance/bearing -> use ref bank's own coord.
                    lat, lon = rlat, rlon
                    precision = "bank"
        else:
            log.info("[%s] offset ref_bank %r not in gazetteer",
                     source_id, ref_bank)

    payload = {
        "raw":         raw,
        "kind":        kind,
        "ref_bank":    ref_bank_id,
        "bearing_deg": bearing_deg,
        "distance_nm": distance_nm,
    }
    if precision == "offset":
        conf = _cap_conf(conf, MAX_CONF_OFFSET)

    return {
        "type":         "position",
        "trip_date":    trip_date,
        "bank":         None,           # positions don't attach to a bank
        "lat":          lat,
        "lon":          lon,
        "precision":    precision,
        "payload":      json.dumps(payload),
        "confidence":   conf,
        "quote":        quote,
        "position_ref": None,
    }


def validate_mention(m: dict, valid_ids: set[str], source_id: str,
                     id_to_coord: dict | None = None) -> dict | None:
    """
    Dispatch by type. Legacy v1 responses (no `type` field) are treated as
    paddy. Returns a row dict compatible with report_mentions (still carries
    a transient `position_ref` that validate_mentions() strips after
    cross-resolution).
    """
    if not isinstance(m, dict):
        log.warning("[%s] mention not a dict: %r", source_id, m)
        return None
    mtype = m.get("type", "paddy")
    if mtype not in MENTION_TYPES:
        log.warning("[%s] unknown mention type %r -> dropped", source_id, mtype)
        return None
    if mtype == "paddy":
        return _validate_paddy(m, valid_ids, source_id)
    if mtype == "bite":
        return _validate_bite(m, valid_ids, source_id)
    if mtype == "conditions":
        return _validate_conditions(m, valid_ids, source_id)
    # mtype == "position"
    return _validate_position(m, valid_ids, source_id, id_to_coord)


def validate_mentions(raw_list, valid_ids, source_id, id_to_coord=None):
    """
    Validate an entire model-returned array. Resolves position_ref: any
    paddy/bite/conditions element pointing at a valid position inherits the
    position's lat/lon/precision. Strips the transient position_ref field
    before returning (not a report_mentions column).
    """
    if not isinstance(raw_list, list):
        return []
    validated = [
        validate_mention(m, valid_ids, source_id, id_to_coord)
        for m in raw_list
    ]
    for v in validated:
        if v is None:
            continue
        pr = v.get("position_ref")
        if pr is not None and 0 <= pr < len(validated):
            pos = validated[pr]
            if (pos and pos["type"] == "position"
                    and pos["lat"] is not None and pos["lon"] is not None):
                v["lat"] = pos["lat"]
                v["lon"] = pos["lon"]
                # Precision reflects strongest signal we now have on this row
                v["precision"] = pos["precision"]
    for v in validated:
        if v is not None:
            v.pop("position_ref", None)
    return [v for v in validated if v is not None]


# ------------------------------------------------------------------ DB

def ensure_schema(conn):
    """
    Create report_mentions if missing, migrate v1 paddy_mentions rows if
    they still exist, then drop the old table. Idempotent.
    """
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    had_old = "paddy_mentions" in tables
    had_new = "report_mentions" in tables

    conn.executescript(REPORT_MENTIONS_SCHEMA)

    # Migration: only run when the old table is present AND we're not
    # colliding with a populated new table.
    if had_old:
        new_row_count = conn.execute(
            "SELECT COUNT(*) FROM report_mentions"
        ).fetchone()[0] if had_new else 0
        if new_row_count == 0:
            _migrate_paddy_mentions(conn)
        conn.execute("DROP TABLE paddy_mentions")
    conn.commit()


def _migrate_paddy_mentions(conn):
    """Copy v1 paddy_mentions rows to report_mentions as type='paddy'."""
    old_rows = list(conn.execute(
        "SELECT source_id, trip_date, bank, route_json, paddy_count, holding, "
        "species_json, water_temp_f, confidence, quote, extracted_at "
        "FROM paddy_mentions"
    ))
    if not old_rows:
        return
    for r in old_rows:
        (source_id, trip_date, bank, route_json, paddy_count, holding_int,
         species_json, water_temp_f, confidence, quote, extracted_at) = r
        holding = (bool(holding_int) if holding_int is not None else None)
        payload = {
            "route":        json.loads(route_json or "[]"),
            "paddy_count":  paddy_count,
            "holding":      holding,
            "species":      json.loads(species_json or "[]"),
            "water_temp_f": water_temp_f,
        }
        # Look up feed_id from paddy_sources (falls back to the v1 default).
        row = conn.execute(
            "SELECT feed_id FROM paddy_sources WHERE id = ?", (source_id,)
        ).fetchone()
        feed_id = row[0] if row and row[0] else "bd-socal-offshore"
        precision = "bank" if bank else None
        conn.execute(
            'INSERT INTO report_mentions '
            '(source_id, feed_id, type, trip_date, bank, lat, lon, "precision", '
            ' payload, confidence, quote, extracted_at) '
            "VALUES (?, ?, 'paddy', ?, ?, NULL, NULL, ?, ?, ?, ?, ?)",
            (source_id, feed_id, trip_date, bank, precision,
             json.dumps(payload), confidence, quote, extracted_at),
        )


def open_db(path: Path = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    return conn


def replace_mentions(conn, source_id: str, feed_id: str,
                     mentions: list[dict], extracted_at: str):
    """
    Idempotent per source: wipe this source's mentions and insert the
    fresh set. `mentions` come from validate_mention() and are already
    typed report_mentions dicts.
    """
    conn.execute("DELETE FROM report_mentions WHERE source_id = ?", (source_id,))
    for m in mentions:
        row = dict(m)
        row["source_id"] = source_id
        row["feed_id"] = feed_id
        row["extracted_at"] = extracted_at
        conn.execute("""
            INSERT INTO report_mentions
                (source_id, feed_id, type, trip_date, bank, lat, lon, "precision",
                 payload, confidence, quote, extracted_at)
            VALUES
                (:source_id, :feed_id, :type, :trip_date, :bank, :lat, :lon, :precision,
                 :payload, :confidence, :quote, :extracted_at)
        """, row)
    conn.execute("UPDATE paddy_sources SET extracted = 1 WHERE id = ?", (source_id,))


# ------------------------------------------------------------------ main loop

def extract_one(conn, source_row, gaz, *, dry_run=False) -> dict:
    """Process a single source. Returns a stats dict."""
    # `truncated` column may be absent on very old rows; treat missing as False.
    try:
        truncated = bool(source_row["truncated"])
    except (IndexError, KeyError):
        truncated = False
    try:
        feed_id = source_row["feed_id"] or "bd-socal-offshore"
    except (IndexError, KeyError):
        feed_id = "bd-socal-offshore"
    prompt = build_prompt(
        title=source_row["title"],
        published_at=source_row["published_at"],
        body=source_row["raw_text"],
        gazetteer_lines=gaz["prompt_lines"],
        truncated=truncated,
    )
    raw = call_claude(prompt)
    if raw is None:
        return {"ok": False, "mentions": 0, "unresolved": 0}

    cleaned = validate_mentions(
        raw, gaz["valid_ids"], source_row["id"], gaz.get("id_to_coord"),
    )
    # Unresolved = paddy/bite/conditions with no bank AND no resolved lat/lon.
    # Positions and pure route-only paddies aren't counted here.
    unresolved = 0
    for v in cleaned:
        if v["type"] not in ("paddy", "bite", "conditions"):
            continue
        if v["bank"] is None and v["lat"] is None:
            # For paddy, having any route items also counts as "resolved enough"
            if v["type"] == "paddy":
                try:
                    if json.loads(v["payload"]).get("route"):
                        continue
                except Exception:
                    pass
            unresolved += 1

    if not dry_run:
        replace_mentions(
            conn, source_row["id"], feed_id, cleaned,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        )
        conn.commit()
    return {"ok": True, "mentions": len(cleaned), "unresolved": unresolved}


def run(limit: int | None = None, dry_run: bool = False, only_id: str | None = None) -> dict:
    conn = open_db()
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        gaz = load_gazetteer()

        # Tolerate old DBs — ensure_schema (ingest_bd.ensure_schema, called
        # by the workflow before extract) is responsible for adding
        # truncated / feed_id. We still guard here in case someone runs
        # extract standalone against a pre-migration DB.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(paddy_sources)")}
        trunc_col   = "truncated" if "truncated" in cols else "0 AS truncated"
        feed_col    = "feed_id"   if "feed_id"   in cols else "'bd-socal-offshore' AS feed_id"

        q = (f"SELECT id, url, title, author, published_at, raw_text, "
             f"{trunc_col}, {feed_col} "
             "FROM paddy_sources WHERE extracted = 0 "
             f"AND {feed_col.split(' AS ')[0]} IN ({','.join('?' * len(PADDY_FEED_IDS))}) "
             "ORDER BY published_at DESC")
        params = tuple(PADDY_FEED_IDS)
        if only_id:
            q = (f"SELECT id, url, title, author, published_at, raw_text, "
                 f"{trunc_col}, {feed_col} "
                 "FROM paddy_sources WHERE id = ?")
            params = (only_id,)
        if limit and not only_id:
            q += f" LIMIT {int(limit)}"
        rows = list(conn.execute(q, params))

        stats = {"posts": 0, "posts_extracted": 0, "posts_failed": 0,
                 "mentions_written": 0, "unresolved": 0}
        global _last_error
        streak = 0
        if rows and not os.environ.get("ANTHROPIC_API_KEY"):
            _last_error = "ANTHROPIC_API_KEY is not set"
            print(f"[paddies:extract] {_last_error}; skipping {len(rows)} posts", file=sys.stderr)
            stats["posts"] = stats["posts_failed"] = len(rows)
            return stats
        for row in rows:
            if streak >= MAX_CONSECUTIVE_FAILURES:
                print(f"[paddies:extract] {streak} failures in a row ({_last_error}); "
                      f"stopping, {len(rows) - stats['posts']} posts left for the next run",
                      file=sys.stderr)
                break
            stats["posts"] += 1
            result = extract_one(conn, row, gaz, dry_run=dry_run)
            streak = 0 if result["ok"] else streak + 1
            if result["ok"]:
                stats["posts_extracted"] += 1
                stats["mentions_written"] += result["mentions"]
                stats["unresolved"] += result["unresolved"]
                print(f"  [{row['id'][:10]}] {row['title'][:60]!r:62}  "
                      f"mentions={result['mentions']}  unresolved={result['unresolved']}")
            else:
                stats["posts_failed"] += 1
                print(f"  [{row['id'][:10]}] {row['title'][:60]!r:62}  FAILED")
            time.sleep(REQUEST_SLEEP)
        return stats
    finally:
        conn.close()


def record_health(stats: dict, now: datetime | None = None,
                  state_path: Path | None = None) -> dict:
    """Fold this run into data/paddies_ingest_state.json (extract_* keys)."""
    from . import ingest_bd
    path = state_path or ingest_bd.STATE_PATH
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    now_s = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["extract_last_run_utc"] = now_s
    if stats["posts"] == 0 or stats["posts_failed"] < stats["posts"]:
        state["extract_last_success_utc"] = now_s
        state["extract_consecutive_failed_runs"] = 0
        state["extract_last_error"] = None
    else:
        state["extract_consecutive_failed_runs"] = state.get("extract_consecutive_failed_runs", 0) + 1
        state["extract_last_error"] = _last_error or "all posts failed"
    state["pending_extract"] = max(0, state.get("pending_extract", 0) - stats["posts_extracted"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="max posts to process (default: all pending)")
    ap.add_argument("--dry-run", action="store_true",
                    help="don't write to DB")
    ap.add_argument("--only-id", help="process only the given source id")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    print(f"[paddies:extract] db={DB_PATH}  model={MODEL}  dry_run={args.dry_run}")
    stats = run(limit=args.limit, dry_run=args.dry_run, only_id=args.only_id)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if not args.dry_run and not args.only_id:
        record_health(stats)
    # Fail loudly if EVERY post failed — usually means Claude client is broken
    # (bad ANTHROPIC_API_KEY, network partition, etc.). One-off post failures
    # per spec are non-fatal.
    if stats["posts"] > 0 and stats["posts_failed"] == stats["posts"]:
        print(f"[paddies:extract] FATAL: all {stats['posts']} posts failed extraction",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
