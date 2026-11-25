"""
The landings' own trip reports: daily "Update" posts, "called in with ..." lines
and skipper reports with photos, from the TECK fish-report network that the
landings publish through:

  * sandiegofishreports.com  /fish_reports/saltwater.php  (H&M, Fisherman's,
    Seaforth, Point Loma, Oceanside, long-range boats)
  * socalfishreports.com     /fish_reports/saltwater.php  (OC/LA, Channel
    Islands, Ventura, Santa Barbara ...)

Per run: page 1 of each listing (plus older pages on the first run), then one
fetch per new report page, 2.5 s apart. robots.txt on both sites allows all.

Claude reads each report (forced tool use, like boat_reports.py) and records,
per boat: size grade (count / max / min lb per species), bait (type, on board),
tackle, a one-line skipper note in our words, conditions, and open spots the
post advertises. Every size, bait and tackle value needs a verbatim quote found
in the post. We publish our summaries, one short quote, a link to the report
and photo URLs (hot-linked from media.fishreports.com, never re-hosted).

Outputs:
  * landing_reports / landing_report_runs / landing_notes tables in paddies.db
  * web/api/v1/landing_notes.json   (boat pages, Co-Captain, app)
  * rows merged into whats_working.json (source: "landing")
  * --research-csv for forecast R&D (hypothesis H2: size grade + bait)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import extract as paddy_extract
from . import regions as regions_mod

log = logging.getLogger("paddies.landing_reports")

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("PADDIES_DB") or (ROOT / "data" / "paddies.db"))
EXPORT_PATH = ROOT / "web" / "api" / "v1" / "landing_notes.json"
STATE_PATH = ROOT / "data" / "paddies_ingest_state.json"

SITES = {
    "sdfr": {"base": "https://www.sandiegofishreports.com", "name": "San Diego Fish Reports",
             "default_region": regions_mod.SD},
    "scfr": {"base": "https://socalfishreports.com", "name": "SoCal Fish Reports",
             "default_region": None},
}
LISTING_PATH = "/fish_reports/saltwater.php"
USER_AGENT = "TunaTracker/1.0 (+https://thetunatracker.com)"
TIMEOUT_SECONDS = 20
RATE_LIMIT_SECONDS = 2.5
FIRST_RUN_DAYS = 30            # first run walks listing pages back this far
MAX_LISTING_PAGES = 12
DEFAULT_MAX_DETAILS = 120      # report-page fetches per run
DEFAULT_RUN_LIMIT = 80         # Claude calls per run
MAX_ATTEMPTS = 3
MAX_BODY_CHARS = 9000
MIN_BODY_CHARS = 60
QUOTE_MAX_WORDS = 15
EXPORT_WINDOW_DAYS = 60
NOTES_PER_BOAT = 6
PHOTOS_PER_NOTE = 4
REQUEST_SLEEP = 0.5

# Landing names the SD feed uses that aren't in web/regions.js (long-range
# companies sail from San Diego).
EXTRA_LANDING_REGIONS = {
    "Independence Sportfishing": regions_mod.SD, "Intrepid Sportfishing": regions_mod.SD,
    "Polaris Supreme Sportfishing": regions_mod.SD, "Royal Star Sportfishing": regions_mod.SD,
    "Searcher Sportfishing": regions_mod.SD, "American Angler Sportfishing": regions_mod.SD,
    "Red Rooster III Sportfishing": regions_mod.SD, "Excel Sportfishing": regions_mod.SD,
    "Vagabond Sportfishing": regions_mod.SD, "Shogun Sportfishing": regions_mod.SD,
    "Spirit of Adventure Sportfishing": regions_mod.SD,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS landing_reports (
    report_id     INTEGER PRIMARY KEY,
    site          TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    source_name   TEXT,          -- landing or boat named on the listing card
    author        TEXT,          -- byline (landing staff / skipper)
    landing       TEXT,
    published_at  TEXT,          -- local timestamp from the listing, ISO
    fetched_at    TEXT NOT NULL, -- when we first saw it (knowable-at time)
    body          TEXT,          -- report text (NULL until the page is fetched)
    photos        TEXT,          -- JSON [url] on media.fishreports.com
    fetch_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lr_pub ON landing_reports(published_at);

CREATE TABLE IF NOT EXISTS landing_report_runs (
    report_id     INTEGER PRIMARY KEY,
    status        TEXT NOT NULL,  -- ok | not_report | failed
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    extracted_at  TEXT NOT NULL
);

-- One row per (report, boat). Append-only per report like forum_signals.
CREATE TABLE IF NOT EXISTS landing_notes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id      INTEGER NOT NULL,
    site           TEXT NOT NULL,
    landing        TEXT,
    region         TEXT,
    boat_raw       TEXT,
    boat           TEXT,
    trip_date      TEXT,
    trip_length    TEXT,
    anglers        INTEGER,
    species        TEXT,          -- JSON [{name, count, max_lb, min_lb}]
    size_quote     TEXT,
    bait_type      TEXT,          -- sardine | anchovy | mackerel | squid | mixed
    bait_on_board  INTEGER,       -- 1 = post says it is on board now
    bait_quote     TEXT,
    tackle         TEXT,          -- JSON [str]
    tackle_quote   TEXT,
    skipper_note   TEXT,          -- our words, one line
    conditions     TEXT,          -- our words
    quote          TEXT,          -- one verbatim line, <= 15 words
    published_at   TEXT,
    fetched_at     TEXT,
    extracted_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ln_boat ON landing_notes(boat);

CREATE TABLE IF NOT EXISTS landing_open_spots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    INTEGER NOT NULL,
    landing      TEXT,
    region       TEXT,
    boat         TEXT,
    trip_date    TEXT,
    trip_length  TEXT,
    quote        TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);
"""

_last_error: str | None = None


# ------------------------------------------------------------------ db / http

def open_db(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.executescript(SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str) -> str | None:
    import requests
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        log.warning("fetch %s: %r", url, e)
        return None
    if r.status_code != 200:
        log.warning("fetch %s: HTTP %s", url, r.status_code)
        return None
    r.encoding = r.encoding or "utf-8"
    return r.text


# ------------------------------------------------------------------ parsing

_STAMP_FORMATS = ("%b %d, %Y %I:%M %p", "%m-%d-%Y", "%b %d, %Y")


def _parse_stamp(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"[^\w:,\- ]+", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    m = re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}(?: \d{1,2}:\d{2} [AP]M)?|\d{2}-\d{2}-\d{4}", t)
    if not m:
        return None
    for fmt in _STAMP_FORMATS:
        try:
            dt = datetime.strptime(m.group(0), fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:00") if "%H" in fmt or "%I" in fmt else dt.date().isoformat()
        except ValueError:
            continue
    return None


def _photo_url(src: str | None, base: str) -> str | None:
    if not src or "media.fishreports.com" not in src or "/logos/" in src:
        return None
    if not re.search(r"/(reports|photos)/", src):
        return None
    return "https:" + src if src.startswith("//") else urljoin(base, src)


_REPORT_LINK = re.compile(r"/(?:fish_reports|reports)/(\d+)/")


def parse_listing(html: str, site: str) -> list[dict]:
    base = SITES[site]["base"]
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for card in soup.select("div.report-card"):
        # landing reports: /fish_reports/<id>/...; long-range boats link to
        # longrangesportfishing.net/reports/<id>/... (same network, same ids)
        a = card.find("a", href=_REPORT_LINK)
        if not a:
            continue
        rid = int(_REPORT_LINK.search(a["href"]).group(1))
        top = card.select_one(".report-card-top")
        title_el = top.find("strong") if top else None
        src_el = card.select_one(".report-card-source")
        bottom = card.select_one(".report-card-bottom")
        lines = [s.strip() for s in bottom.get_text("\n").split("\n") if s.strip()] if bottom else []
        stamp = card.select_one(".report-card-stamp")
        published = _parse_stamp(stamp.get_text(" ") if stamp else None) or \
            next((p for p in (_parse_stamp(l) for l in lines) if p), None)
        thumb = card.select_one(".report-card-middle img")
        out.append({
            "report_id": rid, "site": site, "url": urljoin(base, a["href"]),
            "title": (title_el.get_text(" ", strip=True) if title_el else a.get_text(" ", strip=True))[:200],
            "source_name": src_el.get_text(" ", strip=True) if src_el else None,
            "author": lines[0][:80] if lines else None,
            "landing": lines[1][:80] if len(lines) > 1 and not _parse_stamp(lines[1]) else None,
            "published_at": published,
            "thumb": _photo_url(thumb.get("src") if thumb else None, base),
        })
    return out


def parse_report(html: str, base: str) -> dict:
    """Body text (between the byline and 'Previous Report') and the report's photos."""
    cut = html.find("More Reports")
    head = html[:cut] if cut > 0 else html
    photos = []
    for src in re.findall(r'(?:src|href|data-src)="([^"]*media\.fishreports\.com/[^"]+)"', head):
        u = _photo_url(src, base)
        if u and u not in photos:
            photos.append(u)
    soup = BeautifulSoup(head, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    text = re.sub(r"[ \t\xa0]+", " ", soup.get_text("\n"))
    text = re.sub(r"\n\s*\n+", "\n", text)
    # Byline: "by Seaforth Staff" (landing sites) or, on longrangesportfishing.net,
    # "Fish Report for <date> / <title> / <date> / <author>" with no "by".
    m = re.search(r"\n\s*by ([^\n]+)\n", text) or \
        re.search(r"Fish Report for [^\n]*\n[^\n]*\n\s*\d{2}-\d{2}-\d{4}\s*\n[^\n]*\n", text)
    start = m.end() if m else 0
    end = text.find("< Previous Report", start)
    body = text[start:end if end > 0 else None]
    # drop phone / website / photo-carousel lines
    body = re.sub(r"^\s*(\(\d{3}\)\s*[\d-]+|Website|https?://\S+|Photos|Previous|Next|\W)\s*$", "",
                  body, flags=re.M)
    body = re.sub(r"\s*\n\s*", "\n", body).strip()
    # join "The \n Boat \n called in" fragments back into sentences
    body = re.sub(r"(?<![.!?:])\n(?=[a-z(\d])|(?<=\bThe)\n", " ", body)
    return {"body": body[:MAX_BODY_CHARS], "photos": photos[:12]}


# ------------------------------------------------------------------ ingest

def _upsert_listing(conn, item: dict, fetched_at: str) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO landing_reports (report_id, site, url, title, source_name, author, "
        "landing, published_at, fetched_at, photos) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (item["report_id"], item["site"], item["url"], item["title"], item["source_name"],
         item["author"], item["landing"], item["published_at"], fetched_at,
         json.dumps([item["thumb"]] if item.get("thumb") else [])))
    return cur.rowcount > 0


def ingest(conn, *, max_pages: int | None = None, max_details: int = DEFAULT_MAX_DETAILS,
           fetcher=fetch, sleep=time.sleep) -> dict:
    stats = {"listing_pages": 0, "new_reports": 0, "details_fetched": 0, "errors": 0}
    now = _now_iso()
    for site, cfg in SITES.items():
        have_any = conn.execute("SELECT 1 FROM landing_reports WHERE site = ? LIMIT 1", (site,)).fetchone()
        pages = max_pages or (MAX_LISTING_PAGES if not have_any else 1)
        oldest = (date.today() - timedelta(days=FIRST_RUN_DAYS)).isoformat()
        for page in range(1, pages + 1):
            url = cfg["base"] + LISTING_PATH + (f"?page={page}" if page > 1 else "")
            html = fetcher(url)
            stats["listing_pages"] += 1
            if not html:
                stats["errors"] += 1
                break
            items = parse_listing(html, site)
            new = sum(_upsert_listing(conn, it, now) for it in items)
            stats["new_reports"] += new
            conn.commit()
            dates = [it["published_at"] for it in items if it["published_at"]]
            if not items or (dates and min(dates)[:10] < oldest) or (have_any and new == 0):
                break
            sleep(RATE_LIMIT_SECONDS)
    rows = list(conn.execute(
        "SELECT report_id, site, url FROM landing_reports WHERE body IS NULL AND fetch_attempts < ? "
        "ORDER BY published_at DESC LIMIT ?", (MAX_ATTEMPTS, max_details)))
    for r in rows:
        sleep(RATE_LIMIT_SECONDS)
        html = fetcher(r["url"])
        if not html:
            stats["errors"] += 1
            conn.execute("UPDATE landing_reports SET fetch_attempts = fetch_attempts + 1 WHERE report_id = ?",
                         (r["report_id"],))
            conn.commit()
            continue
        p = parse_report(html, SITES[r["site"]]["base"])
        old = json.loads(conn.execute("SELECT photos FROM landing_reports WHERE report_id = ?",
                                      (r["report_id"],)).fetchone()[0] or "[]")
        photos = list(dict.fromkeys(p["photos"] + old))
        conn.execute("UPDATE landing_reports SET body = ?, photos = ?, fetch_attempts = fetch_attempts + 1 "
                     "WHERE report_id = ?", (p["body"], json.dumps(photos), r["report_id"]))
        conn.commit()
        stats["details_fetched"] += 1
    return stats


# ------------------------------------------------------------------ extraction

BAIT_TYPES = ["sardine", "anchovy", "mackerel", "squid", "mixed"]


def _trip_lengths():
    from .boat_reports import TRIP_LENGTHS
    return TRIP_LENGTHS


def report_tool() -> dict:
    q = {"type": ["string", "null"]}
    return {
        "name": "record_landing_report",
        "description": "Record what a sportfishing landing's or skipper's report says, per boat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_fishing_report": {"type": "boolean",
                                      "description": "False for holiday hours, ads, schedule-only posts."},
                "open_spots": {
                    "type": "array",
                    "description": "Trips the post says have room / light load / need anglers.",
                    "items": {"type": "object", "properties": {
                        "boat": {"type": ["string", "null"]},
                        "trip_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                        "trip_length": {"type": ["string", "null"], "enum": _trip_lengths() + [None]},
                        "quote": {"type": "string"}},
                        "required": ["boat", "trip_date", "trip_length", "quote"]},
                },
                "boats": {
                    "type": "array",
                    "items": {"type": "object", "properties": {
                        "boat_raw": {"type": "string"},
                        "boat": {"type": ["string", "null"], "description": "Exact name from KNOWN BOATS, or null"},
                        "trip_date": {"type": ["string", "null"], "description": "Trip date YYYY-MM-DD"},
                        "trip_length": {"type": ["string", "null"], "enum": _trip_lengths() + [None]},
                        "anglers": {"type": ["integer", "null"]},
                        "species": {"type": "array", "items": {"type": "object", "properties": {
                            "name": {"type": "string", "description": "lowercase, e.g. yellowfin, bluefin, "
                                                                      "yellowtail, dorado, skipjack, wahoo"},
                            "count": {"type": ["integer", "null"]},
                            "max_lb": {"type": ["number", "null"]},
                            "min_lb": {"type": ["number", "null"]}},
                            "required": ["name", "count", "max_lb", "min_lb"]}},
                        "size_quote": dict(q, description="Verbatim words giving the sizes (e.g. "
                                                          "'Yellowfin up to 70 pounds'); null if no sizes"),
                        "bait_type": {"type": ["string", "null"], "enum": BAIT_TYPES + [None]},
                        "bait_on_board": {"type": ["boolean", "null"],
                                          "description": "True if the post says the bait is on board now"},
                        "bait_quote": q,
                        "tackle": {"type": "array", "items": {"type": "string"},
                                   "description": "Recommended or productive tackle, short noun phrases "
                                                  "of 6 words or fewer, max 5"},
                        "tackle_quote": q,
                        "skipper_note": {"type": ["string", "null"],
                                         "description": "One line, your own words, <= 20 words: what the "
                                                        "skipper/landing says about the fishing"},
                        "conditions": {"type": ["string", "null"], "description": "<= 12 words, your words"},
                        "quote": dict(q, description="The single most useful line, verbatim, <= 15 words"),
                    }, "required": ["boat_raw", "boat", "trip_date", "trip_length", "anglers", "species",
                                    "size_quote", "bait_type", "bait_on_board", "bait_quote", "tackle",
                                    "tackle_quote", "skipper_note", "conditions", "quote"]},
                },
            },
            "required": ["is_fishing_report", "open_spots", "boats"],
        },
    }


PROMPT = """You read posts that San Diego / Southern California sportfishing landings and skippers \
publish (daily updates, "X called in with ...", trip reports). Record, per boat the post reports \
on, what it says. Be literal: only what the post states.

- species: counts and sizes. max_lb from "up to 70 pounds", "to 75 lbs"; min_lb/max_lb from \
"(25-75lbs.)". Sizes need size_quote copied exactly from the post.
- bait: sardine / anchovy / ... with bait_quote copied exactly. bait_on_board true only for \
"... on board", "... available", "loaded up on ...".
- tackle: what the post recommends or says worked, with tackle_quote copied exactly.
- A post can cover the landing in general (e.g. a daily update about 3/4 day trips): use \
boat_raw = the landing or trip type, boat = null.
- open_spots: trips the post says have room / light load / need anglers.

The post was published {published}. Resolve dates like "11/24" or "Tuesday" against that.

KNOWN BOATS: {boats}

LANDING: {landing}
TITLE: {title}

POST:
{body}"""


def _clip(q: str | None, n: int = QUOTE_MAX_WORDS) -> str | None:
    if not q:
        return None
    w = q.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def _quoted(q, body) -> bool:
    return bool(q) and paddy_extract.quote_matches_source(q, body)


def _valid_date(s, published: str | None) -> str | None:
    try:
        d = date.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    try:
        pub = date.fromisoformat((published or "")[:10])
    except ValueError:
        return d.isoformat()
    return d.isoformat() if pub - timedelta(days=30) <= d <= pub + timedelta(days=45) else None


def validate_entry(e: dict, body: str, published: str | None, known: dict) -> dict | None:
    from .boat_reports import match_boat, TRIP_LENGTHS
    raw = (e.get("boat_raw") or "").strip()
    if not raw:
        return None
    sq = e.get("size_quote")
    size_ok = _quoted(sq, body) and re.search(r"\d", sq or "")
    species = []
    for s in e.get("species") or []:
        name = str(s.get("name") or "").strip().lower()[:30]
        if not name:
            continue
        cnt = s.get("count") if isinstance(s.get("count"), int) and 0 <= s.get("count") < 100000 else None

        def lb(x):
            return float(x) if size_ok and isinstance(x, (int, float)) and not isinstance(x, bool) \
                and 0 < x <= 1000 else None
        species.append({"name": name, "count": cnt, "max_lb": lb(s.get("max_lb")), "min_lb": lb(s.get("min_lb"))})
    bq = e.get("bait_quote")
    bait_ok = _quoted(bq, body)
    tq = e.get("tackle_quote")
    tackle_ok = _quoted(tq, body)
    tl = e.get("trip_length")
    an = e.get("anglers")
    return {
        "boat_raw": raw[:80], "boat": match_boat(e.get("boat"), raw, known),
        "trip_date": _valid_date(e.get("trip_date"), published),
        "trip_length": tl if tl in TRIP_LENGTHS else None,
        "anglers": an if isinstance(an, int) and 0 < an < 500 else None,
        "species": species,
        "size_quote": _clip(sq) if size_ok else None,
        "bait_type": e.get("bait_type") if bait_ok and e.get("bait_type") in BAIT_TYPES else None,
        "bait_on_board": (1 if e.get("bait_on_board") else 0) if bait_ok and isinstance(e.get("bait_on_board"), bool) else None,
        "bait_quote": _clip(bq) if bait_ok else None,
        "tackle": [str(t).strip()[:60] for t in (e.get("tackle") or []) if str(t).strip()][:5] if tackle_ok else [],
        "tackle_quote": _clip(tq) if tackle_ok else None,
        "skipper_note": (e.get("skipper_note") or "").strip()[:180] or None,
        "conditions": (e.get("conditions") or "").strip()[:120] or None,
        "quote": _clip(e.get("quote")) if _quoted(e.get("quote"), body) else None,
    }


def report_region(row, boat: str | None, known: dict) -> str | None:
    landings = [row["landing"], row["source_name"]]
    if boat:
        landings += known.get(boat, [])
    regs = [regions_mod.region_for_landing(l) or EXTRA_LANDING_REGIONS.get(l or "") for l in landings]
    r = regions_mod.combine(regs)
    return r if r else SITES.get(row["site"], {}).get("default_region")


def call_claude(prompt: str) -> dict | None:
    global _last_error
    client = paddy_extract._get_client()
    tool = report_tool()
    for attempt in range(2):
        try:
            msg = client.messages.create(
                model=paddy_extract.MODEL, max_tokens=2500, tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": prompt}])
            for b in msg.content:
                if getattr(b, "type", None) == "tool_use":
                    return b.input
            _last_error = "no tool_use block"
        except Exception as e:  # noqa: BLE001
            _last_error = repr(e)[:300]
            time.sleep(2.0)
    return None


def pending(conn, limit: int | None) -> list:
    q = ("SELECT r.* FROM landing_reports r LEFT JOIN landing_report_runs x ON x.report_id = r.report_id "
         "WHERE r.body IS NOT NULL AND (x.report_id IS NULL OR (x.status = 'failed' AND x.attempts < ?)) "
         "ORDER BY r.published_at DESC")
    rows = list(conn.execute(q, (MAX_ATTEMPTS,)))
    return rows[:limit] if limit else rows


def _record_run(conn, rid: int, status: str, err: str | None = None):
    conn.execute(
        "INSERT INTO landing_report_runs (report_id, status, attempts, last_error, extracted_at) "
        "VALUES (?, ?, 1, ?, ?) ON CONFLICT(report_id) DO UPDATE SET status = excluded.status, "
        "attempts = attempts + 1, last_error = excluded.last_error, extracted_at = excluded.extracted_at",
        (rid, status, err, _now_iso()))


def process(conn, row, known) -> dict:
    body = row["body"] or ""
    if len(body) < MIN_BODY_CHARS:
        _record_run(conn, row["report_id"], "not_report", "body too short")
        conn.commit()
        return {"ok": True, "entries": 0}
    prompt = PROMPT.format(published=row["published_at"] or "unknown",
                           boats=", ".join(sorted(known)), landing=row["landing"] or row["source_name"] or "?",
                           title=row["title"] or "", body=body)
    res = call_claude(prompt)
    if res is None:
        _record_run(conn, row["report_id"], "failed", _last_error)
        conn.commit()
        return {"ok": False, "entries": 0}
    if conn.execute("SELECT 1 FROM landing_notes WHERE report_id = ?", (row["report_id"],)).fetchone():
        _record_run(conn, row["report_id"], "ok")   # append-only: keep the first extraction
        conn.commit()
        return {"ok": True, "entries": 0}
    now = _now_iso()
    n = 0
    if res.get("is_fishing_report"):
        for e in res.get("boats") or []:
            v = validate_entry(e, body, row["published_at"], known)
            if not v:
                continue
            useful = v["species"] or v["size_quote"] or v["bait_type"] or v["tackle"] or v["skipper_note"]
            if not useful:
                continue
            conn.execute(
                "INSERT INTO landing_notes (report_id, site, landing, region, boat_raw, boat, trip_date, "
                "trip_length, anglers, species, size_quote, bait_type, bait_on_board, bait_quote, tackle, "
                "tackle_quote, skipper_note, conditions, quote, published_at, fetched_at, extracted_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["report_id"], row["site"], row["landing"] or row["source_name"],
                 report_region(row, v["boat"], known), v["boat_raw"], v["boat"], v["trip_date"],
                 v["trip_length"], v["anglers"], json.dumps(v["species"]), v["size_quote"], v["bait_type"],
                 v["bait_on_board"], v["bait_quote"], json.dumps(v["tackle"], ensure_ascii=False),
                 v["tackle_quote"], v["skipper_note"], v["conditions"], v["quote"], row["published_at"],
                 row["fetched_at"], now))
            n += 1
    for o in res.get("open_spots") or []:
        if not _quoted(o.get("quote"), body):
            continue
        from .boat_reports import match_boat, TRIP_LENGTHS
        boat = match_boat(o.get("boat"), o.get("boat") or "", known) if o.get("boat") else None
        conn.execute(
            "INSERT INTO landing_open_spots (report_id, landing, region, boat, trip_date, trip_length, "
            "quote, extracted_at) VALUES (?,?,?,?,?,?,?,?)",
            (row["report_id"], row["landing"] or row["source_name"], report_region(row, boat, known), boat,
             _valid_date(o.get("trip_date"), row["published_at"]),
             o.get("trip_length") if o.get("trip_length") in TRIP_LENGTHS else None, _clip(o["quote"]), now))
    _record_run(conn, row["report_id"], "ok" if (n or res.get("is_fishing_report")) else "not_report")
    conn.commit()
    return {"ok": True, "entries": n}


def run(limit: int | None = DEFAULT_RUN_LIMIT, db_path: Path | None = None) -> dict:
    global _last_error
    from .boat_reports import load_known_boats
    conn = open_db(db_path)
    rows = pending(conn, limit)
    stats = {"pending": len(rows), "processed": 0, "failed": 0, "entries": 0, "last_error": None}
    if rows and not os.environ.get("ANTHROPIC_API_KEY"):
        stats["last_error"] = "ANTHROPIC_API_KEY is not set"
        conn.close()
        return stats
    known = load_known_boats()
    streak = 0
    for row in rows:
        r = process(conn, row, known)
        stats["processed"] += 1
        stats["entries"] += r["entries"]
        if r["ok"]:
            streak = 0
            time.sleep(REQUEST_SLEEP)
        else:
            stats["failed"] += 1
            streak += 1
            if streak >= 5:
                break
    stats["last_error"] = _last_error if stats["failed"] else None
    stats["backlog"] = len(pending(conn, None))
    conn.close()
    return stats


# ------------------------------------------------------------------ export

def _ago(days: int, now: datetime) -> str:
    return (now - timedelta(days=days)).date().isoformat()


def _note_day(r) -> str:
    return r["trip_date"] or (r["published_at"] or "")[:10]


def build_export(conn, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = _ago(EXPORT_WINDOW_DAYS, now)
    rows = [r for r in conn.execute(
        "SELECT n.*, r.url, r.title, r.author, r.photos FROM landing_notes n "
        "JOIN landing_reports r ON r.report_id = n.report_id ORDER BY n.published_at DESC, n.id DESC")
        if _note_day(r) >= cutoff]
    boats: dict[str, dict] = {}
    for r in rows:
        if not r["boat"]:
            continue
        b = boats.setdefault(r["boat"], {"landing": r["landing"], "region": r["region"], "notes": []})
        if len(b["notes"]) >= NOTES_PER_BOAT:
            continue
        b["notes"].append(_note_json(r))
    by_region = {}
    for reg in (regions_mod.SD, regions_mod.OCLA):
        mine = [r for r in rows if regions_mod.in_region(r["region"], reg)]
        bait = next((r for r in mine if r["bait_type"]), None)
        by_region[reg] = {
            "bait": ({"type": bait["bait_type"], "on_board": None if bait["bait_on_board"] is None
                      else bool(bait["bait_on_board"]), "date": _note_day(bait), "landing": bait["landing"],
                      "quote": bait["bait_quote"], "url": bait["url"]} if bait else None),
            "notes": [_note_json(r) for r in mine[:12]],
        }
    today = now.date().isoformat()
    opens = [dict(boat=o["boat"], landing=o["landing"], region=o["region"], trip_date=o["trip_date"],
                  trip_length=o["trip_length"], quote=o["quote"], url=o["url"], title=o["title"])
             for o in conn.execute(
                 "SELECT o.*, r.url, r.title FROM landing_open_spots o JOIN landing_reports r "
                 "ON r.report_id = o.report_id WHERE o.trip_date >= ? ORDER BY o.trip_date", (today,))]
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": "From the landings' reports",
        "source": "Landing and skipper posts on SanDiegoFishReports.com / SoCalFishReports.com",
        "note": ("Automatic summaries; sizes, bait and tackle are quote-checked. Photos link to the "
                 "landing's report and are not re-hosted."),
        "window_days": EXPORT_WINDOW_DAYS,
        "boats": dict(sorted(boats.items())),
        "by_region": by_region,
        "open_spots": opens,
    }


def _note_json(r) -> dict:
    return {
        "date": _note_day(r), "trip_length": r["trip_length"], "anglers": r["anglers"],
        "title": r["title"], "url": r["url"], "by": r["author"], "landing": r["landing"],
        "region": r["region"], "boat": r["boat"],
        "skipper_note": r["skipper_note"],
        "size": [s for s in json.loads(r["species"] or "[]") if s.get("max_lb") or s.get("min_lb")],
        "catch": [{"name": s["name"], "count": s["count"]} for s in json.loads(r["species"] or "[]")
                  if s.get("count")],
        "bait": r["bait_type"], "bait_on_board": None if r["bait_on_board"] is None else bool(r["bait_on_board"]),
        "tackle": json.loads(r["tackle"] or "[]"), "conditions": r["conditions"], "quote": r["quote"],
        "photos": json.loads(r["photos"] or "[]")[:PHOTOS_PER_NOTE],
    }


def ww_rows(conn, oldest: str) -> list[dict]:
    """landing_notes in the shape boat_reports._ww_classes reads (source = 'landing')."""
    out = []
    for r in conn.execute(
            "SELECT n.*, r.url, r.title FROM landing_notes n JOIN landing_reports r "
            "ON r.report_id = n.report_id ORDER BY n.published_at DESC"):
        if _note_day(r) < oldest or not (json.loads(r["tackle"] or "[]") or r["bait_type"]):
            continue
        bait = None
        if r["bait_type"]:
            bait = r["bait_type"] + (" (on board)" if r["bait_on_board"] else "")
        out.append({
            "id": f"L{r['id']}", "source": "landing", "region": r["region"], "feed_id": None,
            "boat": r["boat"], "match_confidence": 0.95 if r["boat"] else 0, "landing": r["landing"],
            "trip_length": r["trip_length"], "trip_date": r["trip_date"],
            "published_at": r["published_at"], "title": r["title"], "url": r["url"],
            "tackle": r["tackle"], "bait": bait, "conditions": r["conditions"], "spots": "[]",
        })
    return out


def write_export(path: Path = EXPORT_PATH, db_path: Path | None = None) -> dict:
    conn = open_db(db_path)
    data = build_export(conn)
    conn.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


RESEARCH_COLUMNS = ["report_id", "site", "landing", "region", "boat", "trip_date", "trip_length",
                    "anglers", "species", "bait_type", "bait_on_board", "tackle", "published_at",
                    "fetched_at", "url"]


def write_research_csv(path: Path, db_path: Path | None = None) -> int:
    conn = open_db(db_path)
    rows = list(conn.execute(
        "SELECT n.report_id, n.site, n.landing, n.region, n.boat, n.trip_date, n.trip_length, n.anglers, "
        "n.species, n.bait_type, n.bait_on_board, n.tackle, n.published_at, n.fetched_at, r.url "
        "FROM landing_notes n JOIN landing_reports r ON r.report_id = n.report_id ORDER BY n.published_at"))
    conn.close()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(RESEARCH_COLUMNS)
        w.writerows([tuple(r) for r in rows])
    return len(rows)


def record_health(stats: dict, path: Path = STATE_PATH) -> None:
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        state = {}
    now = _now_iso()
    state["landing_reports_last_run_utc"] = now
    if not stats.get("last_error"):
        state["landing_reports_last_success_utc"] = now
    state["landing_reports_last_error"] = stats.get("last_error")
    state["landing_reports_backlog"] = stats.get("backlog")
    state["landing_reports_ingest"] = stats.get("ingest")
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Landing / skipper reports -> landing_notes")
    ap.add_argument("--limit", type=int, default=DEFAULT_RUN_LIMIT, help="Claude calls this run (0 = no cap)")
    ap.add_argument("--max-details", type=int, default=DEFAULT_MAX_DETAILS)
    ap.add_argument("--no-ingest", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--research-csv", type=Path)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    stats: dict = {}
    if not args.export_only:
        if not args.no_ingest:
            conn = open_db()
            stats["ingest"] = ingest(conn, max_details=args.max_details)
            conn.close()
        stats.update(run(limit=args.limit or None))
        record_health(stats)
    write_export()
    if args.research_csv:
        stats["research_rows"] = write_research_csv(args.research_csv)
    log.info("landing_reports: %s", json.dumps(stats))
    return 1 if stats.get("last_error") == "ANTHROPIC_API_KEY is not set" else 0


if __name__ == "__main__":
    sys.exit(main())
