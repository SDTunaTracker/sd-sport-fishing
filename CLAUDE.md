# SD Sport Fishing — Claude Code Context

## What this project is
A daily-updated analytics dashboard tracking trophy fish catches across the four major San Diego sportfishing landings. The site is live at **thetunatracker.com**.

## The four landings we track
| Landing | Source |
|---|---|
| H&M Landing | fishcounts.com/hmlanding |
| Fisherman's Landing | fishcounts.com/fishermanslanding |
| Seaforth Sportfishing | fishcounts.com/seaforth |
| Point Loma Sportfishing | pointlomasportfishing.com/fishcounts.php |

H&M, Fisherman's, and Seaforth share the same fishcounts.com backend and HTML structure. Point Loma has its own page but the same logical shape — one parser handles all four.

## The seven tracked species
**Trophy fish (headline metric):** Bluefin Tuna, Yellowfin Tuna, Yellowtail, Dorado
**Also tracked (in DB + charts, not leaderboard):** Skipjack, Bigeye, Albacore

## The three key metrics
| Metric | Formula | Purpose |
|---|---|---|
| `trophy_count` | bluefin + yellowfin + yellowtail + dorado | Raw haul |
| `trophy_per_angler` | trophy_count ÷ anglers | Normalizes for boat size |
| `trophy_per_angler_per_day` | trophy_per_angler ÷ trip_length_days | Apples-to-apples across trip lengths |

`trophy_per_angler_per_day` is the headline leaderboard stat — it lets a full-day trip compete fairly against a 3-day long range trip.

## What gets filtered out
- Half-day, 1/2 Day AM/PM, twilight, and shorter trips
- Rows with unparseable trip length or missing angler counts
- "Released" (catch-and-release) counts — only landed fish count

## Data pipeline
```
4 landing fish-count pages
        ↓ HTTP scrape (requests + bs4)
src/scrape.py       ← one generic table parser for all 4 landings
        ↓
tracker.db          ← SQLite, UNIQUE(date, boat, landing, trip_length, anglers)
        ↓              re-runs are idempotent (INSERT OR IGNORE)
src/export.py       ← exports to web/data.js
        ↓
web/SD Sport Fishing.html  ← React 18 + Babel-in-browser reads window.SD
```

## Frontend stack
- **React 18 + Babel-in-browser** — no build step, no Vite, no webpack
- Must be served via HTTP (not file://) because Chrome blocks JSX file:// fetches
- `scripts/serve.ps1` spins up a local server on port 8765

## Key frontend files
| File | Role |
|---|---|
| `web/SD Sport Fishing.html` | Entry point |
| `web/app.jsx` | Routing |
| `web/dashboard.jsx` | Main dashboard view |
| `web/boats.jsx` | Boat leaderboard |
| `web/drilldown.jsx` | Boat / landing detail pages |
| `web/filterbar.jsx` | Global date/landing/species filters |
| `web/tweaks-panel.jsx` | UI tweaks panel |
| `web/analytics.js` | All aggregation logic |
| `web/ui.jsx` | Shared primitives, species colors |
| `web/styles.css` | All styling |
| `web/data.js` | Auto-generated — do not edit manually |

## Key backend files
| File | Role |
|---|---|
| `src/scrape.py` | HTTP fetcher + HTML table parser |
| `src/parse.py` | Trip-length, species, date parsers |
| `src/db.py` | SQLite schema + insert helpers |
| `src/export.py` | SQLite → web/data.js |
| `src/moon.py` | Moon phase calculator |
| `src/main.py` | Daily orchestrator (entry point) |

## Common operations

### Run today's scrape
```powershell
scripts\run-daily.ps1
```

### Re-run a specific past date
```powershell
.venv\Scripts\python.exe -m src.main --date 2026-05-19
```
Note: landings only show recent days — once a date scrolls off the page it can't be backfilled.

### Regenerate data.js without scraping (useful after frontend changes)
```powershell
.venv\Scripts\python.exe -m src.main --export-only
```

### Serve locally
```powershell
scripts\serve.ps1
# Opens browser at http://localhost:8765
```

### Inspect the DB
```python
import sqlite3
c = sqlite3.connect("tracker.db")
for r in c.execute("SELECT boat, trip_length, trophy_count, ROUND(trophy_per_angler_per_day, 2) FROM trips ORDER BY 4 DESC LIMIT 10"):
    print(r)
```

## Deployment
Live at thetunatracker.com. The daily scrape runs via Windows Task Scheduler at 06:30 local time (configured by `scripts/install-task.ps1`).

## Things to know
- **Babel-in-browser**: JSX is transpiled in the browser at runtime — no build step needed, but also no hot reload. After editing any `.jsx` or `.css` file, just hard-refresh the browser.
- **data.js is gitignored**: It's auto-generated on each scrape run. Don't manually edit it.
- **tracker.db is gitignored**: Created on first run.
- **Idempotent inserts**: Safe to re-run the same day multiple times — duplicates are ignored.
- **Corporate SSL**: `pip-system-certs` is pinned in requirements.txt to handle corporate proxy CA issues on Windows.
