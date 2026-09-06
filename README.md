# SD Sport Fishing — Trophy Catch Tracker 

Daily-updated analytics dashboard for the four major San Diego sportfishing landings:
H&M Landing, Fisherman's Landing, Point Loma Sportfishing, and Seaforth Sportfishing.

Tracks each boat's catch across 7 species, with a focus on **trophy fish**
(Bluefin Tuna + Yellowfin Tuna + Yellowtail + Dorado) and three derived
per-boat-per-trip metrics:

| Metric | Definition |
|---|---|
| `trophy_count` | bluefin + yellowfin + yellowtail + dorado on that trip |
| `trophy_per_angler` | trophy_count ÷ anglers |
| `trophy_per_angler_per_day` | trophy_per_angler ÷ trip_length_days |

The last metric is the apples-to-apples comparison across trip lengths — a 3-day
Long Range trip and a Full Day trip can finally be compared on the same axis.

Trips shorter than 3/4 day (half day, twilight) are filtered out at ingest.

---

## Quick start

```powershell
cd C:\Users\Tyler.Christian\Projects\sd-sport-fishing

# 1. One-time setup: creates .venv and installs Python deps
scripts\setup.ps1

# 2. Pull today's data
scripts\run-daily.ps1

# 3. View the dashboard (opens browser at http://localhost:8765)
scripts\serve.ps1

# 4. Schedule the daily run at 06:30 every morning
scripts\install-task.ps1
```

To change the schedule time:
```powershell
scripts\install-task.ps1 -TaskTime "07:15"
```

---

## How it works

```
            ┌──────────────────────────────┐
            │  4 landing fish-count pages  │
            │  3 share fishcounts.com      │
            │  Point Loma hosts its own    │
            └────────────┬─────────────────┘
                         │  HTTP (requests + bs4)
                         ▼
            ┌──────────────────────────────┐
            │ src/scrape.py                │
            │  - One generic table parser  │
            │  - Filters out half-day      │
            │  - Computes moon phase       │
            └────────────┬─────────────────┘
                         │
                         ▼
            ┌──────────────────────────────┐
            │ tracker.db (SQLite)          │
            │  trips table                 │
            │  UNIQUE(date,boat,landing,…) │
            │  re-runs are idempotent      │
            └────────────┬─────────────────┘
                         │
                         ▼
            ┌──────────────────────────────┐
            │ src/export.py                │
            │  -> web/data.js              │
            └────────────┬─────────────────┘
                         │
                         ▼
            ┌──────────────────────────────┐
            │ web/SD Sport Fishing.html    │
            │  React 18 + Babel-in-browser │
            │  Reads window.SD             │
            └──────────────────────────────┘
```

### Data sources

| Landing | URL |
|---|---|
| H&M Landing | `https://www.fishcounts.com/hmlanding/fishcounts.php` |
| Fisherman's Landing | `https://www.fishcounts.com/fishermanslanding/fishcounts.php` |
| Seaforth Sportfishing | `https://www.fishcounts.com/seaforth/fishcounts.php` |
| Point Loma Sportfishing | `https://www.pointlomasportfishing.com/fishcounts.php` |

The first three are served by the same backend (fishcounts.com) and share an
identical 4-column HTML table; only the CSS class prefix differs (HM / FL / SF).
Point Loma hosts its own page with a different class system but the same
logical 4-column shape. One parser handles both, identifying fish-count tables
by their column headers rather than by class.

### What gets ingested

- Date (parsed from page headers like "Fish Counts for May 19th, 2026")
- Boat name (as reported on the source page; landing attribution comes from
  the page, not from any boat→landing lookup)
- Trip type (raw label preserved, plus a canonical bucket like "1.5 Day")
- Anglers
- Per-species counts for the 7 tracked species (Bluefin, Yellowfin,
  Yellowtail, Dorado, Skipjack, Bigeye, Albacore)
- Other species caught (Rockfish, Calico Bass, etc.) — captured as
  `other_species_json` for future use, not in the headline metric
- Derived: trophy_count, trophy_per_angler, trophy_per_angler_per_day,
  moon_phase, moon_illum

### What's excluded

- Half-day, 1/2 Day AM/PM, twilight, and shorter trips
- Rows with unparseable trip length or missing anglers
- "Released" species counts (catch-and-release; not landed fish)

---

## File layout

```
sd-sport-fishing/
├── README.md                  This file
├── requirements.txt           Python deps (requests, bs4, lxml, pip-system-certs)
├── tracker.db                 SQLite — gitignored, created on first run
├── src/
│   ├── moon.py                Moon-phase calculator
│   ├── parse.py               Trip-length / species / date parsers
│   ├── db.py                  Schema + insert helpers
│   ├── scrape.py              HTTP + table parser per landing
│   ├── export.py              SQLite -> web/data.js
│   └── main.py                Daily orchestrator (entry point)
├── web/
│   ├── SD Sport Fishing.html  Entry HTML
│   ├── data.js                Auto-generated, gitignored
│   ├── analytics.js           Aggregation functions (adapted from design)
│   ├── ui.jsx                 Shared primitives, species colors
│   ├── app.jsx                Routing
│   ├── dashboard.jsx          Main view
│   ├── boats.jsx              Boat leaderboard
│   ├── drilldown.jsx          Boat / landing detail
│   ├── filterbar.jsx          Global filters
│   ├── tweaks-panel.jsx       Tweaks UI
│   └── styles.css             All styling
├── scripts/
│   ├── setup.ps1              One-time venv + deps
│   ├── run-daily.ps1          Daily scrape wrapper (writes logs/)
│   ├── install-task.ps1       Register with Task Scheduler
│   └── serve.ps1              Local web server + open browser
└── logs/                      One file per daily run (gitignored)
```

---

## Operations

### Re-run a specific past day

```powershell
.venv\Scripts\python.exe -m src.main --date 2026-05-19
```

Note: the landings only show recent days. Once a date scrolls off the page,
you can't backfill it from these sources.

### Regenerate data.js without scraping

```powershell
.venv\Scripts\python.exe -m src.main --export-only
```

Useful after schema changes or front-end iteration.

### Inspect the DB

```powershell
.venv\Scripts\python.exe
>>> import sqlite3
>>> c = sqlite3.connect("tracker.db")
>>> for r in c.execute("SELECT boat, trip_length, trophy_count, ROUND(trophy_per_angler_per_day, 2) FROM trips ORDER BY 4 DESC LIMIT 10"):
...     print(r)
```

### Schedule details

The task created by `install-task.ps1`:
- Runs as the current user, only when logged on (no stored password)
- Triggers daily at 06:30 local time (override with `-TaskTime "HH:MM"`)
- Has a 15-minute kill-switch in case the scrape hangs
- Will run on next boot if the machine was off at the trigger time
- Re-running the installer is safe — it deletes and recreates the task

If you want the task to run even when you're not logged in, edit the
`$principal` block in `install-task.ps1` to use `-LogonType Password`.

### Removing the schedule

```powershell
Unregister-ScheduledTask -TaskName "SD Sport Fishing - Daily Scrape" -Confirm:$false
```

---

## Implementation notes

- **Corporate SSL inspection**: `pip-system-certs` is pinned because corporate
  proxies often install a custom root CA that Python's bundled certifi bundle
  doesn't know about. The package patches `requests` to use the Windows trust
  store instead. No-op on non-Windows.
- **Babel in browser**: The design ships as a Babel-in-browser prototype (no
  build step). That's why `scripts\serve.ps1` runs a local HTTP server — Chrome
  blocks `file://` fetches, so opening the HTML directly won't load the .jsx
  files. If you want to ditch Babel-in-browser later, the cleanest port is to
  Vite + React.
- **Idempotent inserts**: `UNIQUE(date, boat, landing, trip_length, anglers)`
  on `trips` plus `INSERT OR IGNORE` means re-running the same day's scrape is
  a no-op. Safe to crash-and-restart.
- **Trophy-only metric**: The headline "Trophy/Angler" stat aggregates only the
  4 trophy species. The other 3 tuna (Skipjack, Bigeye, Albacore) are still
  captured in the DB and visible in species-mix charts — they just don't move
  the leaderboard.
- **IDE Python interpreter**: If VS Code shows "package not installed" hints
  on requirements.txt, point its Python interpreter at `.venv\Scripts\python.exe`
  (Ctrl-Shift-P → Python: Select Interpreter).

---

## Provenance

- Original UI design exported from claude.ai/design as "SD Tuna Tracker"
- Adapted to the trophy-fish metric + 7-species schema specified by the user
- Data-source URLs discovered by inspecting each landing's homepage —
  3 of 4 landings turned out to share a fishcounts.com backend, which let
  one parser handle three landings.
- **Spot list courtesy SWYC Anglers** (Southwestern Yacht Club Anglers).
  Public offshore spot list credited to Michael Mooradian, source at
  <https://swycanglers.org/resources/local-offshore-fishing-spots/>.
  Used to generate `data/banks.geojson` via
  `scraper/paddies/build_gazetteer.py`.
- **Group membership is name-based.** The `catalina` and
  `san-clemente-island` group features contain only waypoints whose name
  matches specific keywords (Catalina/Avalon/Isthmus/Two Harbors and
  San Clemente/Pyramid/China Point/Castle Rock/Northwest Harbor
  respectively). Well-known Catalina-area spots like **Farnsworth Bank**,
  **Ship Rock**, **The V's** don't carry those keywords and remain
  independent features. This means paddy counts for "at Catalina" and
  "at Farnsworth" are tallied separately in `/api/v1/paddies.json`.

## Paddies pipeline

`scraper/paddies/` ingests public forum reports (Bloodydecks SoCal
Offshore) and turns them into structured "paddies by bank" data.

Body-source policy:
- **Primary source is the per-forum RSS feed.** `content:encoded`
  carries the full post body for short posts.
- **Longer posts are truncated by RSS at ~500 chars** with a trailing
  "Read more" marker. `ingest_bd.py` detects this and issues ONE
  additional polite `GET` per truncated post to the thread URL, extracts
  the OP's `.bbWrapper` via `bs4`, and replaces `raw_text` with the full
  body. Guarded by:
  - `TunaTracker/1.0 (+https://thetunatracker.com)` UA.
  - 1 request/sec between thread fetches.
  - 25 fetches per run maximum.
  - Immediate STOP on any `HTTP 403` or `HTTP 429` — no retries, no UA
    rotation. Remaining truncated rows keep `truncated=1` and get a
    "post is truncated" hint added to their extraction prompt.
- Phase 0 probe verified both `robots.txt` (no disallow on our forum
  path) and the XenForo terms page (default boilerplate, no anti-scrape
  clause).

Backfill: none in v1. Coverage = current RSS depth (~25 items, ~3 days
of activity at typical posting frequency).
