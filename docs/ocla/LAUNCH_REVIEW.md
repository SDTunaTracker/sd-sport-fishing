# OC / LA region — launch review

Reviewed 2026-11-25 on branch `claude/ocla-launch`, using the live `tracker.db` (data through 2026-11-24)
and the site served locally at `/ocla/...?preview_ocla=true` at 1440px and 375px (15 routes × 2 widths, scripted
with Playwright, plus an SD regression pass).

## Verdict: NO-GO today. GO once the 4 owner decisions and 3 remaining blockers below are done

The plumbing works: OC/LA routing, region filtering, the 11 landings' daily scrapes, and every page renders
with no JS errors and no horizontal overflow at 375px. This branch fixes the San Diego-only content that leaked
into OC/LA pages. **The remaining blocker is the metric.** Every headline number on the site counts trophy fish
(bluefin, yellowfin, yellowtail, dorado), and most OC/LA trips catch none. On Nov 24 the OC/LA fleet ran
23 trips with 726 anglers and landed **2,826 fish**. The Today page says **"11 boats brought in 11 fish."**

---

## Decisions for the owner

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | **Headline metric for OC/LA** | (a) keep trophy/angler/day; (b) **fish per angler per day, all species** (from `full_catch`); (c) the angler picks a species preset, with the default set per region | **(b) for OC/LA, with trophy kept as a secondary column.** The data is already there: `full_catch` is stored for every OC/LA trip. Numbers below. |
| D2 | **Which landings count as "OC / LA"** | Today: 11 landings, including Channel Islands (Oxnard) and Ventura Harbor, which are in Ventura County. Oceanside is grouped with San Diego. | Keep all 11, but name the region for what it covers (D3). Keep Oceanside in San Diego. |
| D3 | **Region name and URL** | `OC / LA` + `/ocla/` (current); "LA & Orange County"; "OC, LA & Ventura" | Keep the `/ocla/` URL (it's in code, sitemap plans and user localStorage). Display it as **"OC / LA"** in the header, and say "Orange County, LA & Ventura" in page titles and descriptions. This branch already uses "Orange County & LA" in SEO titles, so tell me if you want Ventura added. |
| D4 | **Nav placement and launch style** | (a) flip `OCLA_PUBLIC` so the header region switcher shows for everyone; (b) soft launch: share `/?preview_ocla=true` for a week first | **(b) then (a).** The soft-launch URL already works today with no deploy. See the launch plan. |

### D1 data: OC/LA vs San Diego, full-day+ trips, 2026

| Month | OC/LA trophy/angler | OC/LA **all fish/angler** | SD trophy/angler | SD all fish/angler |
|---|---|---|---|---|
| Jun | 0.15 | **7.6** | 1.25 | 4.6 |
| Jul | 0.38 | **6.5** | 1.98 | 3.7 |
| Aug | 0.42 | **5.0** | 2.48 | 3.5 |
| Sep | 0.92 | **5.2** | 3.59 | 4.8 |
| Oct | 1.21 | **5.4** | 2.53 | 4.2 |
| Nov | 0.13 | **6.2** | 2.71 | 4.9 |

OC/LA's top species are rockfish, whitefish, calico bass, bonito and barracuda. Trophy fish show up in Sep–Oct and
are near zero the rest of the year. A trophy-only leaderboard would rank OC/LA boats on noise: the overview's
"best boat" is Ghost with 9.63 tuna/angler, from 5 trips. Labels like "Tuna / Angler", "Total Tuna" and
"no trophy fish" are also wrong for a fleet that mostly fishes for something else.

Once D1 is decided, the implementation is small. `SDA.preprocessTrips` already supports any species set
(Settings → species presets, including "All Species"), so the change is a **region default** for the species set
plus metric labels that follow it.

---

## Go / no-go checklist

Legend: ✅ done/OK · 🔧 fixed on this branch · ❌ blocker · ⚠️ should-fix (not blocking) · 🅾️ owner decision

### 1. Pages (OC/LA region, 1440px + 375px)

| Page | Status | Notes |
|---|---|---|
| All 15 routes | ✅ | No JS errors. No horizontal scroll at 375px. Loads take 4–6s locally, the same as SD (one 20.5 MB `data.js` for all regions). |
| Home hero | 🔧 | Kicker said "SAN DIEGO SPORTBOAT COUNTS". It now follows the region. |
| Home / Today conditions | 🔧 | Showed the **San Diego forecast** ("60-Mile Bank 70°F · solid yellowfin opportunity", rating "GOOD") on OC/LA. Forecasting is R&D-only and SD-offshore-only, so it's now hidden for OC/LA and the fleet-trend band takes the full width. |
| Today "Book next" card | 🔧 | Promoted an SD boat (Producer, H&M). It's now region-filtered, so it's hidden for OC/LA because there are no OC/LA schedules. |
| Today "Still fishing" card | 🔧 | Was unfiltered (SD boats). It's now region-filtered. |
| Today headline + KPIs | ❌🅾️ D1 | "11 boats brought in 11 fish" / "11 total fish" / "0.04 fish per angler, 91% below". It counts trophy fish only. Screens: `screens/today-*-headline-issue.jpg`. |
| Analytics → Overview | ❌🅾️ D1 | "Fleet tuna/angler 0.49", "Total tuna 43,035" (mostly yellowtail), "best boat" from 5 trips. 🔧 The "Approved San Diego landings" panel label now follows the region. |
| Analytics → Find My Boat / H2H / Seasonality / Moon | ⚠️ D1 | Correct OC/LA boats, but scored on trophy species, so "0 tuna" rows dominate. |
| Analytics → Half Day | ✅ | Uses its own all-species counts and works well for OC/LA (lots of half-day trips). |
| Boats leaderboard | ⚠️ D1 | Correct boats. Ranked by trophy/day. |
| Boat page | 🔧 / ⚠️ | 🔧 "Book a trip" went to an empty Trip Planner; it now says **"Book with {landing}"** and links to the landing's booking page. ⚠️ "Total fish: All tracked species" shows 172 for Enterprise, which landed 6,236 fish in total (1,666 rockfish, 1,133 barracuda…). The 7 tracked species exclude local species. ⚠️ No photos, specs or captains for any OC/LA boat (see Data). |
| Landing page | 🔧 | The SEO title was "Today's San Diego Fish Counts" for **every** landing page (SD too). It's now "{Landing} Fish Counts — Fleet & Boat Stats", matching the prerendered SD landing pages. |
| Trip Planner | 🔧 | Showed **San Diego trips** ("San Diego Seaforth Full Day…") and SD BloodyDecks long-range reports under OC/LA. It's now region-filtered. For OC/LA it shows "Trip schedules for OC / LA landings aren't on Tunatracker yet" with booking links for 10 landings (verified 2026-11-25), and the SD-only "What's working" card is hidden. |
| Charts | ✅ / ⚠️ | Region-neutral SoCal map. ⚠️ The tide panel is hard-wired to the "San Diego — NOAA 9410230" station. ⚠️ Mobile Charts takes about 34s to settle on **SD too** (a pre-existing UX issue, not OC/LA). |
| Footer | 🔧 | Said "San Diego's most complete…" and listed the 5 SD landings as data sources, with nav links to `/sd/...`. It now follows the region (SD output is unchanged). |
| Co-Captain chat | 🔧 | See §4. Only mounted on Trip Planner. |

Before/after screenshots are in `docs/ocla/screens/` (home, Trip Planner at 1440 and 375, boat page).

### 2. Data

| Item | Status | Notes |
|---|---|---|
| Daily scrape, all 11 OC/LA landings | ✅ | `scrape_log`: every landing 'ok' on every hourly run Nov 10–25 (51/51). Source: socalfishreports.com. |
| Freshness | ✅ | 9 landings have data through Nov 24, Redondo/Ventura through Nov 22, Pierpoint through Nov 15. Each matches its source page's latest report (checked 2026-11-25). |
| Missing days: outage or no-trip day? | ✅ **No-trip days** | The scraper reads each landing's latest-report page hourly, and on no day since Jun 1 did *all* OC/LA landings go silent. Spot check: pierpoint.net's own "last 10 fishing days" list (Sep 19 – Nov 15) matches our DB date for date (Nov 7, 8, 15; Oct 16, 18, 19, 25), and its "1 trip" Toronado overnight on Nov 15 is in the DB. Redondo (last report Nov 22) and Ventura (Nov 22) show the same pattern. Gaps since Jun 1: Pierpoint 121, Ventura 83, Redondo 78, LA Waterfront 74, Long Beach 50, Newport 28 (more in Oct/Nov = off-season). |
| Gaps you can't backfill | ⚠️ | socalfishreports pages have no date archive. If a scrape run is ever missed, a day that rolls off the page is lost. 976-tuna.com (the history source) now fails with an expired TLS certificate, so the Channel Islands/Ventura/Oceanside top-up via 976 is dead (the daily socalfishreports scrape still covers them). |
| History depth | ⚠️ | Deep history only for Dana Wharf (2019+), Davey's Locker, Newport, Marina Del Rey (2015+) and Long Beach (2022+). The other 6 landings start May 2026, so "vs prior year" and seasonality are thin for them. |
| Metric sanity | ❌🅾️ D1 | See D1. `full_catch` is populated for 100% of OC/LA trips since June. |
| Boat profiles / photos | ⚠️ | **0 of ~60** active OC/LA boats have a profile (photo, length, captains). `src/boats.py` only scrapes the 4 SD landing sites. Pages degrade gracefully (no broken images). |
| Schedules / booking links | ⚠️ | **No OC/LA schedules** (`scheduled_trips` = 4 SD landings only). Workaround on this branch: links out to landing booking pages. Follow-up: 6 OC/LA landings (22nd St, Long Beach, Redondo, Pierpoint, Channel Islands, Ventura) use the **same fishingreservations.net system** as Seaforth, so `src/schedule.py` could likely cover them. Newport, Davey's, Dana Wharf and MdR use other systems. LA Waterfront's site couldn't be confirmed (no link shown). |
| Data volume | ✅ | `data.js` is 20.5 MB, the same file for all regions. Under the 24 MB guard, but OC/LA history adds to it. Worth watching. |

### 3. SEO

| Item | Status | Notes |
|---|---|---|
| Titles/meta on `/ocla/*` | 🔧 | `web/seo.js` now has OC/LA titles and descriptions for home, today, boats, analytics, finder and Trip Planner. SD strings are byte-identical. Boat JSON-LD now uses the landing's city (Newport Beach, San Pedro, Oxnard…) instead of "San Diego". |
| `/ocla/*` served by Cloudflare | ❌ (launch PR) | `web/_redirects` lists only `/sd/...` SPA routes, so `/ocla/today` on prod returns 404 and `404.html` bounces to `/`. Add the `/ocla/...` rewrites **in the flag-flip PR**, not before: with the flag off, those URLs would render SD content under an OC/LA canonical. |
| Prerendered OC/LA pages + sitemap | ❌ (launch PR, SEO session) | `src/generate_pages.py` / sitemap have **0** `/ocla/` entries. This is backlog item S26 ("SEO for thetunatracker.com" session). The prerendered landing/boat copy should follow D1/D3. Note the `/sd/boat/<name>` pages for OC/LA boats don't exist either. |
| Canonical while soft-launching | ✅ | With `?preview_ocla=true`, canonical is `/ocla/...` (query stripped). Nothing links to it publicly, so nothing gets indexed early. |

### 4. Co-Captain

| Item | Status | Notes |
|---|---|---|
| Region scoping | ✅ | Trips and leaderboard were already filtered by `pageContext.regions`. |
| OC/LA prompt | 🔧 | When OC/LA is selected, the prompt now says "Southern California (San Diego, Orange County and LA-area)" and adds an OC/LA block: no schedules (so no trip cards, no invented prices or spots), booking links per landing, last-30-day **all-species** fish/angler per OC/LA boat, and a reminder that the no-forecast rule applies. "TODAY'S COUNTS" is labelled San Diego. **The SD-only prompt is unchanged** (verified by generating both prompts in the page). |
| Live answer test | ⚠️ | Not run: the chat proxy needs the production key. Before flipping, ask on `/ocla/tripplanner?preview_ocla=true`: "best full-day out of Newport this weekend?", "who's catching yellowtail in LA?", "book me a trip on the Enterprise". Expected: OC/LA boats, landing links, no made-up trips. |

### 5. Data-health alerts

| Item | Status | Notes |
|---|---|---|
| OC/LA feed coverage | 🔧 | `src/completeness.py`: new **warning** `scrape:<landing>` when any OC/LA landing or Oceanside has no successful scrape in 30h, plus **`trips:gap:oc_la`** when a day in the last 14 has zero trips across *all* OC/LA landings. |
| No alert spam | 🔧 ✅ | Deliberately **no per-landing day-gap rule** (Pierpoint fishes about 1 day in 3). Run against the live DB, the new rules raise **0** problems. A test pins that a silent small landing with healthy scrapes is not flagged (`tests/test_feed_freshness.py`, 13/13 pass). |

---

## Remaining blockers before flipping

1. **D1 metric**: implement the decided OC/LA headline (region-default species set + labels on Today, Overview, Boats and boat page).
2. **`_redirects`** `/ocla/...` rewrites (in the flip PR).
3. **Prerendered `/ocla/` pages + sitemap** (SEO session, S26).
4. Live Co-Captain check (3 questions above).

Not blocking, but worth doing next: OC/LA schedule scraping (fishingreservations.net landings), OC/LA boat profiles and photos,
tide station by region, and a "vs prior year" guard for landings with less than one year of history.

## Launch plan

1. **Soft launch (no deploy needed):** share `https://thetunatracker.com/?preview_ocla=true` and pick OC / LA in the
   header switcher. Deep links to `/ocla/...` will 404 until step 2, so start from `/`.
2. **Flip PR** (separate, after D1–D4 are done and the owner OKs it): set `OCLA_PUBLIC: true` in `web/feature-flags.js`,
   add `/ocla` rewrites to `web/_redirects`, and merge the SEO S26 pages and sitemap.
3. Watch for 48h: alert emails (`trips:gap:oc_la`, `scrape:*`), Cloudflare 404s on `/ocla/*`, and Co-Captain transcripts.

### Rollback

Set `OCLA_PUBLIC: false` in `web/feature-flags.js` and push. Cloudflare Pages redeploys in about 1 min. `app.jsx` already
strips `oc_la` from any visitor's saved regions when the flag is off, so returning visitors fall back to San Diego
automatically. The `/ocla` rewrites can stay (they'd render SD), or revert the flip PR to remove everything at once.
Nothing in the data pipeline depends on the flag.

## What this branch changed

| File | Change |
|---|---|
| `web/regions.js` | `OCLA_LANDING_SITES`: verified booking pages for 10 OC/LA landings |
| `web/tripplanner.jsx`, `web/styles.css` | Region-filter schedules, OC/LA empty state with landing links, hide SD BloodyDecks card for OC/LA |
| `web/home.jsx`, `web/analytics.js` | Region-aware hero kicker, hide SD forecast/conditions for OC/LA, region-filtered "Book next" and "Still fishing" |
| `web/drilldown.jsx` | OC/LA boat pages: "Book with {landing}" links to the landing site |
| `web/analytics.jsx` | "By Landing" panel label follows the region |
| `web/ui.jsx`, `web/app.jsx` | Region-aware footer blurb, links and data sources |
| `web/seo.js` | OC/LA titles/descs, landing-page titles (fixes SD too), boat JSON-LD city |
| `web/chat-api.js` | Co-Captain OC/LA block (gated to the OC/LA region) |
| `src/completeness.py`, `tests/test_feed_freshness.py` | OC/LA scrape-health + region-gap alerts, no-spam test |
| `web/dist/*`, `web/index.html` | Rebuilt the changed bundles; cache-bust versions bumped |

Unrelated to this branch: 2 failures in `tests/test_text_parser.py` (narrative harvest in `src/scrape.py`, which this branch does not touch). The rest of the suite passes (328 passed).
