# SF Bay Area: third-region launch plan

Branch `claude/sfbay-launch-3cdbd7`, started 2026-11-25. The research behind it is `docs/market/THIRD_MARKET.md` on
`claude/market-research-f9f582`.

## Status: NO-GO until the checklist below is done. The PR is safe to merge with the flag off

The data pipeline, alerts and a dedicated SF Bay page set are built and tested, all behind `SHOW_SFBAY` (off).
Merging collects SF Bay counts daily (about 8 small requests a day) into their own table and does nothing visible.
Launch needs four things from the owner: an OK to run the 2019+ backfill, a regs check, the coordination items below,
and the flag flip.

## Owner decisions (made 2026-11-25)

| # | Decision | Choice |
|---|---|---|
| D1 | Cluster boundaries | **The core 5 ports:** Emeryville, Berkeley, Sausalito, San Francisco, and Half Moon Bay (Pillar Point). Bodega Bay, Monterey/Santa Cruz, Fort Bragg and Eureka are stored as `norcal_other` and not shown, so they can be added later with no re-scrape. |
| D2 | Six-packs | **Excluded** from leaderboards and region stats. They're stored, listed and labelled "not ranked". A boat counts as a six-pack if it never carried more than 6 anglers (the SD rule). There are manual overrides in `src/norcal.py`. |
| D3 | Headline metric | **Limit rate by target** (below). |
| D4 | Name / slug / nav | **"SF Bay Area"**, `/sfbay/...`, in the header region dropdown under a "NorCal" divider. It is never combined with SoCal, so there's no "All California" view. |

### D3: how the limit rate works (`src/norcal.py`)

1. **Target inference.** NorCal labels are nearly all "Full Day", so the target comes from the trip label when it gives a
   hint ("Crab Combo", "Salmon Trolling…") and otherwise from the catch. The group with the highest share of its bag
   limit wins. Crab and rockfish both at 20% or more of limits makes a **Crab & Rockfish** combo. Halibut and stripers
   together make a **Bay** trip. A skunked trip takes the boat's most common target within ±14 days, so zeros count
   against the right target.
2. **Per-trip limit rate** = fish per angler ÷ bag limit for the target, **capped at 100%**. Combos average their
   groups. Sturgeon is catch-and-release only, so it's ranked by fish per angler.
3. **Boat and fleet rate** = the angler-weighted mean of the trip rates. A boat needs at least 3 trips to rank.

**Finding for the owner: rockfish and crab limits are common.** In the sample, the Crab & Rockfish fleet ran at 93% of
limits, and several boats tie at 100%. Salmon and halibut separate boats well (27–100% per trip). So the leaderboard
breaks ties by **share of trips at full limits**, then **lingcod per angler** (for rockfish and crab targets). If you
want something sharper for rockfish later, the next lever is **lingcod per angler as its own column/metric** ("limits
plus lings"). Nothing is needed now.

## Workstreams

Legend: ✅ done on this branch · 🟡 partly done / needs the owner · ⏳ not started (follow-up) · 🤝 another session

### 1. Data collection

| Item | Status | Notes |
|---|---|---|
| Scraper | ✅ | `src/scrape_norcal.py` reads one page per day: `norcalfishreports.com/dock_totals/boats.php?date=`. Honest UA (`TunatrackerBot/1.0`), 3–5 s between requests, disk cache `.cache/norcal/` (gitignored), no retries on 4xx. |
| Stop on block | ✅ | 401/403/429/451 or a challenge/notice page → `SourceBlocked`. The block is recorded in `norcal_fetch_log` and is **sticky**: the daily job won't fetch again until the owner reviews it and runs `DELETE FROM norcal_fetch_log WHERE error='blocked'`. An alert goes out (`sfbay:blocked`). |
| Storage | ✅ | Its own table `norcal_trips`, so no SD/OC-LA query can see SF Bay rows. `UNIQUE(date, boat_slug, landing, trip_type_raw, anglers)`. Days older than 3 are insert-only; the last 3 days update counts in place. |
| Daily hook | ✅ | `src/main.py` runs it at most every 6 h (yesterday + today = about 8 requests a day), then writes `web/data-region-sfbay.js`. It's non-fatal: an SF Bay error never breaks the SD run. The workflow commits `web/data-region-sfbay.js`. |
| No-trip days | ✅ | On a day with no counts the source serves "Dock Totals - <last day with counts>", which is stored as `no_counts=1` (5 of the 10 sampled Nov days). |
| Species map | ✅ | King/Chinook salmon (including the "Chinoook" typo), coho, rockfish (all sub-species), cabezon, greenling, lingcod, California/Pacific halibut, striped bass, white/green sturgeon, Dungeness/rock crab, albacore, bluefin, and others. "Released" counts are kept apart and never scored. Unknown names go to the shared `unknown_species` table. The sample's only unknowns (bonito, mackerel, sand sole) have been added. |
| Trip types | ✅ | Full / 3/4 / 1/2 AM / PM / Twilight / 1/4 day / "7 Hour" / "Crab Combo" / "Bay" / "Salmon Trolling…". It never drops a row for an unparseable label, which counts as a full day. Half-days are kept and flagged. The limit rate isn't per day, so a half-day rockfish limit counts the same as a full-day one. |
| Boat profiles | 🟡 | Name, landing, port, six-pack flag, main target, trip history, and a "Source counts" link to the boat's norcalfishreports page. **No photos or specs yet** (follow-up, as for OC/LA). |
| Booking deep links | 🟡 | Only **verified** links ship. Fish Emeryville (`emeryville.fishingreservations.net/sales/`, 15 of 42 boats) is verified. The other ~18 landings show "Booking link coming soon". Follow-up: verify each landing's site; several likely use fishingreservations.net, so `src/schedule.py` may cover their **schedules** too. |
| Conditions | ✅ / 🤝 | **Live when `src.marine` lands.** `export_sfbay._marine()` calls `src.marine.region_payload(conn, "sf_bay")` from the data-health session (branch `claude/ais-conditions`, not on main yet). That payload covers NWS zones PZZ530/531/545/571 plus alerts, CO-OPS tide station 9414290, and buoys NDBC 46026/46237 and CDIP 142 (SF Bar). The Today page then shows a Small Craft Advisory banner, buoy wave height/period/water temperature, the next 4 SF tides, and the coastal zone forecast. Until then (`ImportError` or no data) it shows links to the official sources only. Rendered with a sample payload: `screens/sfbay-conditions-*.jpg` (sample values, not live). |

### 2. Backfill (2019 → present)

| Item | Status | Notes |
|---|---|---|
| Script | ✅ | `scripts/backfill_sfbay.py`: range or `--dates`, `--offline` (cache only), `--skip-logged` (resume), `--max-requests`, and exit code 3 on a block. It **refuses `tracker.db` without `--i-have-owner-ok`**. |
| Polite sample | ✅ | 20 live requests on 2026-11-25 (peak week Jul 12–18, Nov 15–24, 2019-07-20, 2023-07-15, 2024-02-10, 2025-12-06) into a scratch DB: 320 rows, 0 errors, no block. The 2019 page parses with the same code. |
| Full run | ✅ done 2026-11-25 (owner OK) | Ran 2019-01-01 → 2026-11-24 into a side DB. Fetched 2,884 of 2,885 days; 473 were no-count days. The first SF Bay trip is 2019-01-23. **30,687 trips: 22,788 SF Bay** (2,177–3,305 a year) plus 7,899 Bodega/Monterey (stored, hidden). No block or notice from the source. About 3% of requests hit a dropped connection, never 5 in a row; those were retried twice, and only **2024-01-22** is still missing. Targets: salmon 6,688 · rockfish 5,186 · bay mixed 3,170 · halibut 3,158 · crab combo 2,303 · striper 1,453 · crab 638 · sturgeon 69 · bluefin 62 · albacore 53 · unknown 8. Of 59 boats, 6 are six-packs (Wet Spot, Dragon, Soleman, Drake, Warrior Poet, Que Sera Sera). Boats that peak at 7–10 anglers (Argo, Scallywag, Round 2, …) stay ranked; add `SIXPACK_OVERRIDES` if the owner wants them out. `data-region-sfbay.js` is 1.9 MB raw, **197 KB gzipped**, and the All-time leaderboard renders in ~0.3 s. The full run surfaced one bug, a crash when a boat changes landing, now fixed and tested. |
| Landing the backfill | 🟡 | **Two paths, depending on which lands first.** (a) **Before the R2 cutover:** commit `data/sfbay_backfill.jsonl.gz`, and `main.py` loads it once, insert-only (`scrape_norcal.load_seed`). (b) **After the R2 cutover** (R2 seeded and workflows on R2; data-health session, branch `claude/r2-private-data`): **don't commit the seed.** Start right after an hourly run finishes (they start at about :37 and take 2–5 min, leaving a window of about 50 min): `scripts\db.ps1 pull`, then `.venv\Scripts\python.exe scripts\backfill_sfbay.py --db tracker.db --merge-from <side db> --i-have-owner-ok`, then `scripts\db.ps1 push` straight away. Push is ETag-conditional: exit 3 (HTTP 412) means CI pushed in between, so pull and redo; it can't clobber CI. The merge is insert-only, so re-running it is safe. |
| Derived tables | ✅ | Nothing derived is stored. Targets, limit rates, six-pack flags, the boat list and the slow-season flag are rebuilt on every export (`src/export_sfbay.py`), so a regs edit applies on the next run. |
| Per-region data file | ✅ / 🤝 | The owner approved per-region files (loaded only when that region is selected) to keep `data.js` under Cloudflare's 25 MB limit. SF Bay writes **`web/data-region-sfbay.js`**, so it gets PR #6's caching rules (`_headers` `/data-region-*` no-cache, and `sw.js` treats it as mutable) and the workflow commit. **It deliberately does not use #6's `split_by_region` / `ttRegionData.ensure`, which merge rows into `window.SD`.** SF Bay rows have a different shape (targets, limit rates, released counts, no trophy columns) and live in `norcal_trips`, so they can never reach SoCal aggregations such as "All SoCal", which applies no filter. The file name has no underscore (`sfbay`, not `sf_bay`), so it can't collide with #6's auto-generated `data-region-<trips.region>.js`. `ttRegionData` only loads files listed in `REGION_FILES`, so it ignores this one. |
| Payload size | ✅ | About 160 bytes per trip, so the full history (~22k trips, est.) is ~3.5 MB raw (~0.4 MB gzipped). It's a **separate file** that loads only when someone opens SF Bay, so `data.js` (SD/OC-LA) doesn't grow. |

### 3. Product fit

| Item | Status | Notes |
|---|---|---|
| Pages | ✅ | `web/sfbay.jsx`: **Today** (day picker, fleet headline, a card per target with its top boat, every boat's trip, a six-pack toggle), **Boats** (leaderboard per target × 30/90 days/year/all time), **Boat** page, **Landings** (by port). Analytics / Charts / Trip Planner show "Not available for SF Bay yet". **No forecasts** (R&D only). |
| Header / nav | ✅ | Region dropdown: San Diego · (OC/LA, All SoCal) · **NorCal → SF Bay Area**. The nav changes to Today / Boats / Landings in SF Bay. |
| Slow season | ✅ | Fewer than 10 open-party trips in 7 days → a "Slow season on the Bay" banner with what usually fishes that month (`SEASONS` in `src/norcal.py`). |
| Species colors | ✅ | Per target (`SFB_TARGET_COLORS`). |
| Regs config | 🟡 **verify** | `BAG_LIMITS` in `src/norcal.py`: RCG 10, lingcod 2, salmon 2, CA halibut 3 (north of Pt Sur), striper 2, sturgeon C&R, Dungeness 10 (CPFV), albacore 25, bluefin 2. **Check against the current CDFW regs before launch**, especially salmon (season set yearly) and albacore. |
| 1440px + 375px | ✅ | Playwright pass, 7 SF Bay routes + 2 SD regression routes × 2 widths: **0 JS errors, 0 horizontal overflow**. Screens are in `screens/`. With the flag off, `/sfbay/today` falls back to `/sd/today` and `data-region-sfbay.js` is never requested. |
| SEO | ✅ / 🤝 | `web/seo.js` has SF Bay titles, descriptions and canonicals, plus **`noindex` while `SFBAY_PUBLIC` is off**. 🤝 SEO session: the `/sfbay/*` prerender, sitemap, and `_redirects` rewrites, **in the flip PR** (same rule as OC/LA). |
| Co-Captain | 🤝 | Not mounted on SF Bay pages (ChatBot only shows on Trip Planner, and that page is hidden here). 🤝 Co-Captain session: a NorCal block (targets, limit rate, no schedules, regs caveat) once the region is public. `window.SFBAY` is the data source. |
| BloodyDecks | 🤝 | NorCal forum coverage is for the BloodyDecks session (its outputs carry region tags; an `sf_bay` tag is needed). |
| Mobile app / `app.json` | 🤝 | `app.json` is SD-only today. 🤝 App-dev session: either a `regions.sf_bay` block or a separate `api/v1/sfbay.json` built from `build_payload()`. |

### 4. Data-health alerts (`src/sfbay_health.py`, wired into `main.py`)

These are kept out of `src/completeness.py`, which the OC/LA branch also edits. The rules are tuned for no-trip days:

| Key | Severity | Fires when |
|---|---|---|
| `sfbay:blocked` | blocked | The source refused us or posted a notice (sticky until the owner clears it). |
| `sfbay:fetch` | warning | No successful fetch in 30 h. |
| `sfbay:parse` | warning | A page from the last 3 days parsed to 0 rows **without** the no-counts marker (layout change). |
| `sfbay:quiet` | warning | In season (Apr–Oct) only: no SF Bay trips for 7 days even though the fetches worked. |

A winter week of no-count days raises nothing (tested). 🤝 Data-health session: these feed `src.alerts` with the others.

### 5. Launch

- **Flag:** `SFBAY_PUBLIC: false` in `web/feature-flags.js`, which drives `SHOW_SFBAY`.
- **Soft-launch URL** (works as soon as this PR is deployed and the data file exists):
  `https://thetunatracker.com/?preview_sfbay=true`, then pick **SF Bay Area** in the header. The preview sticks for
  the browser tab (sessionStorage). `?preview_sfbay=false` turns it off. Pages are `noindex` during the preview.
  Deep links like `/sfbay/today` 404 on Cloudflare until the `_redirects` rewrite lands (flip PR), so start from `/`.

## Go / no-go checklist

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Merge this PR with the flag off (daily collection starts) | owner OK | ⬜ |
| 2 | Run the 2019+ backfill and land it | Done. Shipped as the committed seed `data/sfbay_backfill.jsonl.gz` (path a; the R2 cutover is on hold). The daily job loads it insert-only on its first run after merge. | ✅ |
| 3 | Re-check six-pack classification on the full history; add overrides if needed | this session | ⬜ |
| 4 | Verify `BAG_LIMITS` against current CDFW regs (salmon 2026/27 season, albacore) | owner/this session | ⬜ |
| 5 | Soft launch on `?preview_sfbay=true` for a week; review the leaderboards with a NorCal angler | owner | ⬜ |
| 6 | Flip PR: `SFBAY_PUBLIC: true`, `/sfbay/*` rewrites in `web/_redirects`, SEO prerender + sitemap | this session + SEO | ⬜ |
| 7 | Co-Captain NorCal block, app.json, BloodyDecks tag (can trail the launch) | 🤝 sessions | ⬜ |
| 8 | Watch for 48 h: `sfbay:*` alerts, Cloudflare 404s on `/sfbay/*` | owner | ⬜ |

## Rollback

Set `SFBAY_PUBLIC: false` in `web/feature-flags.js` and push. Cloudflare Pages redeploys in about a minute.
`app.jsx` drops `sf_bay` from any visitor's saved region when the flag is off, so returning visitors land on
San Diego, and `/sfbay/...` URLs render San Diego. **To stop collecting too:** remove the SF Bay block in
`src/main.py`, or insert a `blocked` row (`INSERT INTO norcal_fetch_log(date, fetched_at, error) VALUES
('stop', datetime('now'), 'blocked')`), which the daily job honors. Nothing else depends on `norcal_trips`. If the
source sends a notice: stop (the block rule does this automatically on a refusal), tell the owner, and don't
work around it.

## Files on this branch

| File | Change |
|---|---|
| `src/norcal.py` | New: ports/regions, species map, bag limits, targets, limit rate, six-pack rule, seasons |
| `src/scrape_norcal.py` | New: polite cached fetcher, parser, `norcal_trips` schema, idempotent insert, daily hook |
| `src/export_sfbay.py` | New: `web/data-region-sfbay.js` (window.SFBAY), verified landing links, conditions sources |
| `src/sfbay_health.py` | New: the 4 alert rules above |
| `src/main.py` | Calls the SF Bay scrape + export, and the health rules (non-fatal) |
| `scripts/backfill_sfbay.py` | New: backfill / resume / offline / merge, with a production guard |
| `tests/test_sfbay.py` | New: 19 tests (parser, no-count days, targets, rates, idempotency, block stickiness, cache, health) |
| `web/sfbay.jsx`, `web/sfbay.css`, `web/dist/sfbay.js` | New SF Bay pages |
| `web/feature-flags.js` | `SFBAY_PUBLIC`, `?preview_sfbay`, `SHOW_SFBAY` |
| `web/regions.js` | `sf_bay` region (flag-gated), `/sfbay` prefix, subtitle |
| `web/app.jsx`, `web/ui.jsx` (+ dist) | Routing, region choice, NorCal dropdown section, SF Bay nav/footer |
| `web/seo.js` | SF Bay titles + soft-launch `noindex` |
| `web/index.html` | Loads `sfbay.css` + `dist/sfbay.js`; version bumps |
| `.github/workflows/daily-scrape.yml` | Commits `web/data-region-sfbay.js`. **Merge note:** PR #6 adds `git add web/data-region-*.js`, which also covers this file. If #6 merges first, keep #6's line and drop the separate `web/data-region-sfbay.js` from the `git add` list. |
| `.gitignore` | `.cache/` |

The full suite has 374 passing tests and 2 failures in `tests/test_text_parser.py`. The same 2 failures were reported on main by the OC/LA review; this branch doesn't touch that code.
