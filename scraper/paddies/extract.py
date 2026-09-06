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
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env from project root if present (matches src/reddit_insights.py).
# No-op if python-dotenv isn't installed or .env is absent.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "tracker.db"
GAZETTEER_PATH = ROOT / "data" / "banks.geojson"

MODEL = "claude-sonnet-4-6"  # matches src/reddit_insights.py
MAX_TOKENS = 1500
REQUEST_SLEEP = 0.5          # polite gap between successful calls (seconds)
RETRY_BACKOFF = 2.0          # single retry after this many seconds
DB_TIMEOUT_SECONDS = 30
DB_BUSY_TIMEOUT_MS = 30000

TRUNCATED_HINT = (
    "\nNOTE: this post is truncated at ~500 chars (RSS excerpt only). "
    "Report only what is present. Do not invent details for content that "
    "may exist past the cut-off.\n"
)

ALLOWED_SPECIES = {"yellowtail", "dorado", "yellowfin", "bluefin"}

log = logging.getLogger("paddies.extract")

MENTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS paddy_mentions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT NOT NULL,
    trip_date      TEXT,                       -- YYYY-MM-DD or NULL
    bank           TEXT,                       -- gazetteer feature id or NULL
    route_json     TEXT NOT NULL DEFAULT '[]', -- JSON array of feature ids
    paddy_count    INTEGER,
    holding        INTEGER,                    -- 0 / 1 / NULL
    species_json   TEXT NOT NULL DEFAULT '[]',
    water_temp_f   REAL,
    confidence     REAL,
    quote          TEXT,
    extracted_at   TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES paddy_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_paddy_mentions_source ON paddy_mentions(source_id);
CREATE INDEX IF NOT EXISTS idx_paddy_mentions_bank   ON paddy_mentions(bank);
CREATE INDEX IF NOT EXISTS idx_paddy_mentions_date   ON paddy_mentions(trip_date);
"""


# ------------------------------------------------------------------ client

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


# ------------------------------------------------------------------ gazetteer

def load_gazetteer(path: Path = GAZETTEER_PATH) -> dict:
    """Return {'valid_ids': set[str], 'prompt_lines': str}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    valid_ids: set[str] = set()
    lines: list[str] = []
    for feat in data["features"]:
        p = feat["properties"]
        if p["kind"] == "admin":
            continue  # per rule 6: admin excluded from matching
        valid_ids.add(p["id"])
        aliases = p.get("aliases") or []
        # compact "id (name): alias, alias, ..." line
        head = p["id"]
        if p["name"].lower() != p["id"].replace("-", " "):
            head += f" ({p['name']})"
        if aliases:
            head += ": " + ", ".join(aliases)
        lines.append(head)
    return {"valid_ids": valid_ids, "prompt_lines": "\n".join(sorted(lines))}


# ------------------------------------------------------------------ prompt

PROMPT_TEMPLATE = """You are extracting paddy (floating kelp paddy) sightings from a SoCal offshore fishing report.

Context: paddies are drifting kelp mats offshore. Yellowtail (YT), dorado (dodo/dorados), and sometimes yellowfin school under them. Fishermen scout for paddies, note whether fish are "holding" (present under them), and refer to locations by numbered bank ("the 43", "182", "9-mile"), named bank, or general area.

TITLE: {title}
PUBLISHED: {published_at}
BODY:
\"\"\"
{body}
\"\"\"

Named locations you may reference. Only use ids from THIS list in "bank" and "route":
{gazetteer_lines}

Return a JSON ARRAY. One element per distinct paddy sighting or paddy summary. Each element:
{{
  "trip_date": "YYYY-MM-DD" or null,   // date the trip actually happened; null if unclear
  "bank": "<id from list above>" or null,
  "route": ["<id>", ...],              // ordered banks visited on the trip; [] if not a loop
  "paddy_count": integer or null,      // "a few"=3, "several"=5, "handful"=4, "10 to 15"=12, "none/no kelp"=0
  "holding": true or false or null,    // fish caught on/around the paddy
  "species": [...],                    // subset of ["yellowtail","dorado","yellowfin","bluefin"], on the paddy specifically
  "water_temp_f": number or null,
  "confidence": 0.0-1.0,
  "quote": "<= 25 words verbatim from the body that supports this mention"
}}

Rules:
- If the post has no paddy or kelp language at all, return [].
- Emit one element per paddy sighting. Multi-bank trips with paddies at each bank -> multiple elements.
- Only put a bank id if it clearly appears in the alias list above. If a place is named but you cannot find it in the list, use null and mention the raw name in "quote".
- For bare-number references that could match multiple features, pick the primary if the alias list resolves it; otherwise use null.
- "quote" must be verbatim words from BODY (no paraphrase).
- If a generic term is used ("the corner", "the ridge") that literally matches only one feature name in the list, use that id; otherwise null with confidence <= 0.5.
- Return ONLY the JSON array. No prose, no markdown fences.
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


def validate_mention(m: dict, valid_ids: set[str], source_id: str) -> dict | None:
    """Coerce and clean one mention dict. None if we can't salvage it."""
    if not isinstance(m, dict):
        log.warning("[%s] mention not a dict: %r", source_id, m)
        return None

    bank = m.get("bank")
    if bank is not None and bank not in valid_ids:
        log.info("[%s] unknown bank id %r -> null", source_id, bank)
        bank = None

    route = m.get("route") or []
    if not isinstance(route, list):
        route = []
    clean_route = []
    for r in route:
        if isinstance(r, str) and r in valid_ids:
            clean_route.append(r)
        elif isinstance(r, str):
            log.info("[%s] unknown route id %r -> dropped", source_id, r)

    species = m.get("species") or []
    if not isinstance(species, list):
        species = []
    clean_species = []
    for s in species:
        if isinstance(s, str) and s.lower() in ALLOWED_SPECIES:
            clean_species.append(s.lower())
    clean_species = sorted(set(clean_species))

    confidence = _as_float(m.get("confidence"))
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))

    quote = m.get("quote")
    if isinstance(quote, str):
        quote = quote.strip()
        # cap at 25 words softly
        words = quote.split()
        if len(words) > 30:
            quote = " ".join(words[:30])
    else:
        quote = None

    return {
        "trip_date":    _valid_date(m.get("trip_date")),
        "bank":         bank,
        "route_json":   json.dumps(clean_route),
        "paddy_count":  _as_int(m.get("paddy_count")),
        "holding":      _as_bool(m.get("holding")),
        "species_json": json.dumps(clean_species),
        "water_temp_f": _as_float(m.get("water_temp_f")),
        "confidence":   confidence,
        "quote":        quote,
    }


# ------------------------------------------------------------------ DB

def ensure_schema(conn):
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    conn.executescript(MENTIONS_SCHEMA)
    conn.commit()


def open_db(path: Path = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    conn.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    return conn


def replace_mentions(conn, source_id: str, mentions: list[dict], extracted_at: str):
    conn.execute("DELETE FROM paddy_mentions WHERE source_id = ?", (source_id,))
    for m in mentions:
        row = dict(m)
        row["source_id"] = source_id
        row["extracted_at"] = extracted_at
        conn.execute("""
            INSERT INTO paddy_mentions
                (source_id, trip_date, bank, route_json, paddy_count, holding,
                 species_json, water_temp_f, confidence, quote, extracted_at)
            VALUES
                (:source_id, :trip_date, :bank, :route_json, :paddy_count, :holding,
                 :species_json, :water_temp_f, :confidence, :quote, :extracted_at)
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

    cleaned = []
    unresolved = 0
    for m in raw:
        v = validate_mention(m, gaz["valid_ids"], source_row["id"])
        if v is None:
            continue
        if v["bank"] is None and not json.loads(v["route_json"]):
            unresolved += 1
        cleaned.append(v)

    if not dry_run:
        replace_mentions(
            conn, source_row["id"], cleaned,
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

        # tolerate old DBs without the truncated column
        cols = {r[1] for r in conn.execute("PRAGMA table_info(paddy_sources)")}
        trunc_col = "truncated" if "truncated" in cols else "0 AS truncated"

        q = (f"SELECT id, url, title, author, published_at, raw_text, {trunc_col} "
             "FROM paddy_sources WHERE extracted = 0 ORDER BY published_at ASC")
        params = ()
        if only_id:
            q = (f"SELECT id, url, title, author, published_at, raw_text, {trunc_col} "
                 "FROM paddy_sources WHERE id = ?")
            params = (only_id,)
        if limit and not only_id:
            q += f" LIMIT {int(limit)}"
        rows = list(conn.execute(q, params))

        stats = {"posts": 0, "posts_extracted": 0, "posts_failed": 0,
                 "mentions_written": 0, "unresolved": 0}
        for row in rows:
            stats["posts"] += 1
            result = extract_one(conn, row, gaz, dry_run=dry_run)
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
