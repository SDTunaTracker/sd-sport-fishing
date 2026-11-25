# Data sources beyond the landings and BloodyDecks

*Research date: 2026-11-25. Research only: no production code or data was changed. No logins, accounts, sign-ups or purchases. Requests were one page at a time, with a 1–2 s gap or more. Prices and terms were read on this date and can change, so re-check them before signing anything. This is not legal advice.*

## Build status (2026-11-25, after the owner approved the quick wins)

| Item | Owner | State |
|---|---|---|
| AIS archive, conditions pack, retiring `scrape-mmsi.py` | "Backfill data gaps and add data-health alerts" | Assigned |
| Landing narratives | "Revive BloodyDecks data collection" | Assigned |
| Regs card | "Co-Captain chatbot" | Assigned |
| Schedule snapshots | Forecast R&D | Started |
| CDFW request | Owner sends `CDFW_EMAIL_DRAFT.md` | Drafted |
| Google reviews | This branch: `cloudflare-worker/places-proxy.js`, `web/google-reviews.jsx`, `scripts/match_google_places.py` | Built, flag off; needs the owner's key (`OWNER_SETUP_KEYS.md` §A) |
| Currents | This branch: `src/currents_cmems.py`, Charts loader | Built, falls back to DEMO; needs a Copernicus account (§B). HF radar still 404/503 |
| YouTube videos | This branch: `src/youtube.py`, `web/boat-videos.jsx` | Built, flag off; needs a key and a privacy-page line (§C) |
| ENSO/ONI | This branch: `src/enso.py`, Co-Captain context | Built; runs weekly, no key |
| User catch reports | `USER_CATCH_REPORTS_SPEC.md` | Spec only, awaiting the owner's decision |

## TL;DR

1. **The best new data is data we already touch and throw away.**
   - Our live AIS feed (aisstream) keeps only the latest position plus a short trail in Cloudflare KV.
   - The schedule scraper overwrites `open_spots` on every run.
   - Archiving both gives us: where each boat actually fished, how far it ran, how fast trips fill, and a history the forecast can use. It costs nothing and needs no new terms.
2. **The landings' own websites carry more than counts.**
   - The daily "Update" text and trip reports give fish sizes ("Yellowfin up to 70 pounds", "25–75 lbs") and bait on board ("Sardines are currently on board").
   - They also give tackle advice and trip photos.
   - They run on the same TECK.net / SanDiegoFishReports platform as our count sources, so the **terms risk is the same one the owner already accepted, not a new one**.
3. **CDFW CPFV logbooks are the only official, multi-decade, block-level party-boat catch record.**
   - The free public tables are statewide annual totals for 1980–2022.
   - Block-level data (10×10 nm) needs an email request to CDFW's Marine Fisheries Statistical Unit.
   - It's the strongest candidate to **legitimise** the product and give the forecast a location-aware climatology.
4. **Google Places reviews** would fill the empty boat-page review panels (`boat_reviews` has **1** row).
   - Cost is about $0 at our volume: 1,000 free calls a month, then $25 per 1,000.
   - The terms are strict: max 5 reviews per place, live display with attribution, and no caching except `place_id`.
5. **A free NOAA "trip-day conditions" pack** costs almost nothing and carries zero terms risk:
   - NWS coastal-waters forecast and Small Craft Advisories
   - NOAA CO-OPS tides
   - CDIP swell buoys
   - more NDBC buoys

   It suits trip pages and Co-Captain, but **not** the forecast: forecast R&D found ocean and weather add nothing on top of momentum.

**Hard flags (don't use):**
- Instagram and Facebook scraping (robots `Disallow: /` plus an explicit "automated means … prohibited" notice).
- Fishdope (Terms forbid "any commercial purpose, or … any public display").
- Global Fishing Watch API (non-commercial licence only).
- MarineTraffic and VesselFinder scraping (VesselFinder ToS §9 bans automated extraction). **Note:** `scripts/scrape-mmsi.py` already scrapes VesselFinder; see §6.
- Yelp ($229/month and up, poor fit).
- The dated sandiegofishreports `/daily-species-report/*/20…` pages (robots disallows them for every agent).

**What the forecast can use.** Ocean data is a dead end for the forecast (forecast-rnd rounds 1–4). The promising inputs are **behavioural**: fleet positions (AIS), booking fill rate, bait type, and catch size grade. They went to forecast R&D as hypotheses H1–H6 (§5).

---

## 1. What we already collect (excluded from this survey)

Found in code or docs: the four SD landing count pages (fishcounts.com, pointlomasportfishing.com) and the network sister sites:
- socalfishreports, sportfishingreport, norcalfishreports
- 976-tuna.com (OC/LA, back to 2003)
- sandiegofishreports `dock_totals/boats.php` (deep backfill)

Plus:
- fishingreservations.net and H&M's `/xolacache` (Xola) schedules, with price and `open_spots`
- BloodyDecks: Offshore paddies, Sportboats and Long Range reports, `forum_signals`
- Reddit (`src/reddit.py`)
- NDBC 46232 (SST, `src/conditions.py`)
- Open-Meteo forecast, marine and ERA5 archive (`src/weather.py`, `src/backtest.py`)
- CoastWatch ERDDAP SST, upwelling and chlorophyll
- the moon (`src/moon.py`)
- Marine Cadastre AIS history (`forecast/backfill_marine_cadastre.py`)
- **aisstream.io live AIS** (`scripts/ais_push.py`): 105 MMSIs across 15 landings, with the latest position pushed to CF KV every 5 min
- VesselFinder for MMSI discovery (`scripts/scrape-mmsi.py`)

## 2. Ranked table

Scores: **Value** 1–5 (to leaderboards, boat pages, the map, Co-Captain, the forecast) × **Feasibility** 1–5 (effort, cost, reliability). **Terms risk:**
- **Low:** public domain or an explicit licence
- **Same:** the same TECK network risk the owner already accepted
- **Med:** unclear or no published terms
- **High:** terms restrict our use
- **⛔:** forbidden, don't use

Rank mostly follows V × F. A few rows move up where strategic value is high: CDFW (credibility, 40-year history) and the HF-radar map layer (it replaces a dead feature).

| Rank | Source | What it gives us | Used by | Coverage / freshness | Access & cost | Terms risk | V | F | Score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **AIS fleet-position archive** (aisstream live + Marine Cadastre history) | Where each tracked boat fished, how far it ran, how long it drifted vs. moved, fleet clustering | Map ("where the fleet is"), boat pages (run distance), Co-Captain ("fleet is at the Ridge"), forecast H1 | SoCal; aisstream is live, Marine Cadastre 2009 → ~1 yr lag | WebSocket (key already in `.env`, free); Marine Cadastre bulk CSV (free) | Med (aisstream has no published terms; `/terms` returned 404). Marine Cadastre is Low (US gov) | 5 | 5 | **25** |
| 2 | **Landing first-party narratives**: daily "Update" text, "called in with …" lines, `detailed_report.php` trip reports and photos | Fish size grade, bait on board (sardine/anchovy), tackle advice, skipper comments, trip photos | Leaderboard (size grade), boat pages (photos, skipper notes), "What's working", Co-Captain, forecast H2 | All 4 SD landings, plus OC/LA landings on the same platform; same-day | HTML, free. Robots: FL `Disallow:` (empty, allow all), H&M allows all except wp-admin, Seaforth allow all | **Same** (footer: "Fish Count publishing service by SanDiegoFishReports.com") | 4 | 5 | **20** |
| 3 | **Booking fill-rate snapshots** (our own schedule scrape, kept over time) | Spots left vs. days before departure, sell-outs, price changes | Trip planner ("filling fast"), forecast H3, owner dashboard | Every trip we already scrape | Already fetched; keep rows instead of overwriting (`UNIQUE(landing, source_id)` today) | **Same** as today | 4 | 5 | **20** |
| 4 | **NWS coastal-waters forecast + alerts** (`api.weather.gov` CWF SGX, PZZ740/750/775) | Wind and seas by period, Small Craft Advisories, synopsis | Trip pages ("SCA in effect Thu"), Co-Captain, a cancellation-risk badge (H6) | SoCal zones; updated 2–4×/day | JSON API, free, no key (a User-Agent is requested) | Low (US gov, public domain) | 3 | 5 | 15 |
| 5 | **CDFW CPFV logbooks** | Official per-trip catch, effort and fishing block (10×10 nm). Public: statewide annual HMS kept-catch 1980–2022 | Map (historic hot blocks by month), "season so far vs. 40-yr average", forecast H4, credibility | CA, 1980 → about a 1-yr lag | Public tables on the CDFW site; block data by email request to MFSU (free; confidentiality rules) | Low (government), but **vessel-level data is confidential**: "catch is excluded in years where less than three vessels reported" | 4 | 3 | 12 (high strategic value) |
| 6 | **Google Places reviews** (Place Details, Enterprise + Atmosphere SKU) | Star rating, review count, ≤5 "most relevant" reviews per place | Boat pages (we have 1 review), landing pages | Global; live | API key + billing account; 1,000 free events/month, then $25 per 1,000. Our ~150 places × weekly ≈ 650/month ≈ **$0** | Med–High: no caching except `place_id`; must show author attribution; max 5 reviews | 4 | 3 | 12 |
| 7 | **NOAA CO-OPS tides** (San Diego 9410170, LA 9410660, SF 9414290) | High/low times and heights; currents at some stations | Trip pages, Co-Captain, half-day/bay trip context | Every US port; predictions years ahead | JSON API, free, no key | Low | 2 | 5 | 10 |
| 8 | **CDIP swell buoys** (191 Point Loma South, 100 Torrey Pines Outer, etc.) | Hs, peak period and direction; swell forecasts | Trip pages ("8 ft at 14 s, lumpy ride"), map | SoCal and NorCal, about 30-minute updates | Text/netCDF/THREDDS, free | Low (UCSD/USACE public data). robots disallows `/cgi-bin/` and query-string `end=`, so use THREDDS | 2 | 4 | 8 |
| 9 | **Regulations and permits** (CDFW ocean regs, NOAA HMS bluefin limits, Mexico CONAPESCA licence, FMM) | Bag limits, closures, "you need a Mexican licence for every passenger" | Trip pages, Co-Captain (a very common question) | Static; changes a few times a year | Manual curation from official pages | Low | 3 | 3 | 9 |
| 10 | **HF-radar surface currents** (SCCOOS/HFRNet, `ucsdHfrW6`) | Hourly 6 km surface currents, 2012 → | Map (replaces the currents layer that died in 2018) | US West Coast, about 100 mi offshore | ERDDAP, free | Low | 2 | 2 (**dataset 404 on CoastWatch today**) | 4 |
| 11 | **Copernicus Marine** currents/physics | Global daily currents and SSH | Map currents layer if HF radar stays down | Global, 1993 → plus a 10-day forecast | Free account; commercial use allowed with credit "Generated using E.U. Copernicus Marine Service Information" | Low (free funding committed until mid-2028) | 2 | 3 | 6 |
| 12 | **YouTube Data API** | Trip videos per boat (title, date, embed) | Boat pages ("Videos") | Global; same-day | API key; 10,000 units/day free (`search.list` = 100 units) | Low via the API (robots disallows `/feeds/videos.xml` and `/results`, so don't scrape) | 2 | 4 | 8 |
| 13 | **TripAdvisor Content API** | Rating plus up to 5 reviews per location | Landing pages | Landings, a few boats; live | Key + card; free allowance 1k–5k calls/month (sources disagree) | High: attribution, no caching except `location_id` | 2 | 3 | 6 |
| 14 | **User-submitted catch reports** (our own) | Sizes, photos, per-angler ratings tied to a trip row | Boat pages, reviews, a data moat | Ours | Build: form, moderation, abuse handling | Low (our data) | 4 (long term) | 2 | 8 |
| 15 | ENSO / ONI index (CPC) | Season context ("El Niño year") | Co-Captain, season narrative | 1950 →, monthly | Text file, free | Low | 1 | 5 | 5 |
| 16 | Western Outdoor News fish reports | Weekly narrative, Baja context | Co-Captain context | SoCal/Baja, weekly | HTML, partly paid; terms page not found | Med | 1 | 3 | 3 |
| 17 | Bait receivers (Everingham Bros) | Sardine/anchovy availability | "What's working", forecast H2 | SD/Mission Bay/Dana Point; ad-hoc | No structured feed (phone, social). Use #2 and BD `forum_signals` instead | — | 2 | 1 | 2 |
| 18 | Paid SST/front products (FishTrack ~$96/yr, ROFFS, Ripcharts, Hilton's, Terrafin) | Break charts, fronts | Map | — | Consumer subscriptions, not licensed for redistribution | High | 1 | 1 | 1 |
| 19 | FishingBooker | Ratings for 6-pack charters | — | — | — | Med (fishingbooker.com returned 403 to us) | 1 | 2 | 2 (out of scope: not open-party) |
| 20 | Fishbrain / FishAngler / iAngler logbooks | Private-angler catches | — | — | No public API; iAngler is a Florida program | Med–High | 1 | 1 | 1 |
| 21 | Kayak forums (kayakfishingsd) | Inshore kayak reports | — | — | — | robots `Disallow: /` | 1 | 1 | ⛔ |
| ⛔ | **Instagram / Facebook** (landing and boat accounts) | Daily catch photos and captions | (would be: boat pages) | — | Only legitimate path is the Graph API "Business Discovery" from **our own** IG business account, plus Meta App Review and Business Verification. Or embed single posts | ⛔ for scraping: robots `Disallow: /` and "Collection of data on Instagram through automated means is prohibited unless you have express written permission" | 3 | 1 | — |
| ⛔ | **Fishdope** ($199/yr) | Spotter-plane GPS numbers, hot-bite maps | (would be: map, forecast) | SoCal/N. Baja | Member login | ⛔ Terms: "personal, non-commercial transitory viewing only … may not … use the materials for any commercial purpose, or for any public display". robots blocks ClaudeBot/GPTBot | 4 | 0 | — |
| ⛔ | **Global Fishing Watch API** | AIS-derived fishing effort | — | Global | Free key | ⛔ for us: "only available for non-commercial purposes"; CC BY-NC 4.0; no public commercial licence | 2 | 0 | — |
| ⛔ | **MarineTraffic / VesselFinder** web | Vessel positions, MMSI lookup | — | — | Paid APIs only | ⛔ for scraping: VesselFinder ToS §9 bans "access or extract Content using automated means (bots, scrapers, crawlers) except through authorized APIs" | 2 | 1 | — |
| ⛔ | **sandiegofishreports Daily Species Report (dated pages)** | Per-species daily history since 2005 | Deep backfill | — | HTML | ⛔: robots `Disallow: /daily-species-report/*/20` for all agents; ClaudeBot/anthropic-ai blocked site-wide | 3 | 0 | — |
| — | Yelp Places API | Ratings and 3–7 review excerpts | — | — | From **$229/month** after a 30-day trial | High | 1 | 1 | skip |
| — | NOAA MRIP | — | — | **Doesn't sample California**; CA uses CRFS/RecFIN | — | — | 0 | — | skip |
| — | RecFIN / CRFS estimates | Monthly party-boat (PBR mode) effort and catch estimates by district | Context, owner dashboard | CA/OR/WA, 2005 → | Web reports, free | Low for a normal scraper; robots blocks ClaudeBot and sets `ai-train=no` (we didn't fetch pages) | 2 | 3 | 6 |

---

## 3. Top 5 briefs

### Brief 1: AIS fleet-position archive (Score 25)

**What.** Keep every aisstream position we already receive for our 105 tracked MMSIs, instead of overwriting KV. Backfill history from Marine Cadastre daily files, which we already download for the forecast.

**Sample (our own cached `web/ais_positions.json`, no new request).** It shows the current setup loses history:

```
Ocean Odyssey  H&M Landing        32.723,-117.227  2026-09-24T00:51  trail 0
Islander       Fisherman's        32.725,-117.226  2026-09-23T17:33  trail 0
Tribute        Seaforth           32.713,-117.232  2026-09-17T18:34  trail 0
```

The local copy is two months stale, and the trail is empty. `merge_trail()` keeps only `MAX_TRAIL` points.

**How it helps.**
- **Map:** a "Fleet last 24 h" heat layer, more trustworthy than forum spot names.
- **Boat pages:** "ran 92 nm south", "fished the Coronados".
- **Trip validation:** did the boat really go out? This catches count-page errors and duplicates.
- **Co-Captain:** "most of the 1.5-day fleet fished the 302 yesterday".
- **Forecast H1** (§5).

**Integration sketch.**
1. In `scripts/ais_push.py`, append each position to `data/ais_track.sqlite` as `(mmsi, ts, lat, lon, sog, cog)`. Optionally downsample to one point per 5 minutes.
2. Add a nightly job that segments tracks into trips (leave the dock geofence → return) and joins them to the `trips` row by boat and return date.
3. Store `max_range_nm`, `fishing_centroid` (low-SOG clusters) and `fishing_block` (CDFW 10×10 nm) on the trip.
4. Export a privacy-safe aggregate to the map: fleet density by block, not live tracks of individual boats.

**Size.** About 105 boats × 288 points/day ≈ 30k rows/day, ~1 MB/day. Trivial.

**Caveats.**
- The terms are unclear. aisstream publishes no ToS (`/terms` returns 404) and calls itself free. Ask them by GitHub issue, which is not a sign-up.
- Show aggregates rather than raw re-broadcast tracks.
- Some captains don't like real-time positions shown ("spot burning"), so delay map display by 24 hours.
- Class B transponders and coverage gaps past ~40 nm mean long-range trips go dark offshore.

**Owner agent:** app-dev (pipeline), with forecast-rnd consuming the features. **Effort:** about 1 day for the archive, 2–3 days for trip segmentation.

### Brief 2: Landing first-party narratives (Score 20)

**What.** Each landing's own site (Fisherman's, H&M, Seaforth, Point Loma) publishes:
- a dated **"Update"** paragraph
- per-boat **"called in with …"** lines
- **trip reports** with photos (`/detailed_report.php?report_id=…`)

**Sample (fishermanslanding.com/fish-counts/, fetched once):**

> Update for Nov. 25, 2026 … "Bring your 25lb/30lb flyline and reverse dropper loop setups with 40lb fluorocarbon leaders and Yo-Yo jigs (JRI 66)" … "Sardines are currently on board".
> 11/24/2026 "The Constitution called in with 76 Yellowfin up to 70 pounds, 38 Yellowtail, 2 Dorado and 45 Skipjack for their 5 day trip with 16 anglers."
> "The Pacific Queen called in with 129 Yellowfin Tuna (25-75lbs.) …"

The trip-report sample (Shogun 10-day, 11-25) had a short skipper note plus 5 photos on `media.fishreports.com`.

**What we gain over counts.**
- A **size grade** (max and range per species). The counts don't have it.
- **Bait type** on board.
- A **tackle recipe** per trip type, which feeds the BD "What's working" card with a second, official source.
- **Photos** for boat pages: link to them or embed them. Don't rehost.
- Counts posted before the dock totals, a few hours earlier.

**Integration sketch.**
1. Fetch the four landing count pages once per daily run (4 requests).
2. Hash each paragraph and keep only new ones.
3. Run a Claude extraction into a `landing_notes` table: `{date, landing, boat?, species[{name, count, max_lb, min_lb}], bait[], tackle[], quote≤15 words}`.
4. Match to `trips` by boat and date.

The parser can reuse the BD extraction prompt style, with quote-checking.

**Terms.** The footer says "Fish Count publishing service by SanDiegoFishReports.com". It's the **same TECK network**, so this is covered by the same risk and the same future data-licence conversation (THIRD_MARKET §7), not a new exposure. robots.txt allows all. Keep quotes short and link back.

**Owner agent:** app-dev (scrape) + co-captain (extraction prompt). **Effort:** 1–2 days.

### Brief 3: CDFW CPFV logbooks (Score 12, top strategic pick)

**What.**
- Every California party boat must file a logbook per trip: date, anglers, hours, **fishing block**, and fish kept or released by species.
- CDFW publishes statewide **annual CPFV kept-catch tables for 1980–2022**: "Dolphinfish and Tunas", "Sharks and Billfish", "Mackerel".
- The fine-grained data sits with the Marine Fisheries Statistical Unit (MFSU).
- NOAA's catalog says SWFSC requests it each spring, and that "logbook data are completed by vessel captains and can be suspect".

**Sample.** The CDFW Pelagic "Catch" page, fetched once, says: "Annual Commercial Passenger Fishing Vessel catch (fish kept) … from 1980-2022. To protect confidentiality, catch is excluded in years where less than three vessels reported kept catch". The tables load dynamically, so we didn't pull the numbers.

**How it helps.**
- A **40-year season baseline** ("2026 yellowfin: best CPFV year since 2015") for the dashboard and Co-Captain.
- **Block-by-month climatology** for the map ("historically, November YFT comes from blocks 860–880").
- A location-aware prior for the forecast (H4).
- An **independent audit** of the scraped counts.
- An official relationship: we could offer CDFW our cleaned daily data. That supports any future data-licence talk with TECK.

**Integration sketch.**
1. The owner emails MFSU@wildlife.ca.gov (CPFV questions: CPFV.Help@wildlife.ca.gov) asking for block × month × species × trip-type aggregates for 1980–2025, at ≥3 vessels per cell. Confidential vessel-level data won't be released.
2. Load the result into `cpfv_logbook_agg`.
3. Join our CDFW block grid to AIS (Brief 1).

**Freshness.** About a 1-year lag, so it's a history/context source, not a daily one.

**Owner agent:** forecast-rnd (analysis) + owner (outreach). **Effort:** the email takes 1 hour; the turnaround is CDFW's (weeks); the load takes 1 day.

### Brief 4: Google Places reviews (Score 12)

**What.**
- Place Details (New) with `rating`, `userRatingCount`, `reviews`, `googleMapsUri`.
- The Enterprise + Atmosphere SKU: 1,000 free events a month, then $25 per 1,000.
- Many SD boats (Pacific Queen, Tribute, Dolphin…) and all landings have Google listings.

**Sample.** Not pulled, since that needs an API key (owner sign-up).

**Terms (Places API policies).**
- "a Place object … can contain up to five reviews".
- You must show author attribution and say how reviews are sorted.
- You may cache only `place_id` and must fetch content fresh (no long-term storage).
- So a review panel has to be rendered from a live call or a short-lived edge cache.

That makes it a poor input for Claude summaries or the forecast, but a fine **"Google rating ★4.7 (312)" badge + 5 reviews** widget.

**Integration sketch.**
1. Do a one-time manual `place_id` match for about 150 boats and landings, stored in `boats.google_place_id` (cacheable).
2. A Cloudflare Worker calls Place Details when a boat page loads, with a short CDN cache (follow the current policy text on duration).
3. Render the badge and reviews with attribution.

Volume: ~150 pages × a few thousand views a month. Use a 24-hour edge cache only if the policy allows it; otherwise the cost scales with views. At 10k views/month it's about $225/month, so **check this first**.

**Sign-up:** a Google Cloud project, billing account and Places API key. **Owner agent:** app-ux (panel) + app-dev (Worker). **Effort:** 1–2 days.

### Brief 5: Trip-day conditions pack: NWS + tides + CDIP (+ NDBC) (Score 15/10/8)

**Samples (all fetched 2026-11-25).**

- **NWS CWF SGX** (`api.weather.gov/products/types/CWF/locations/SGX/latest`, issued 08:09Z). Synopsis: "Combined seas increase to 8-12 feet tonight into Thursday … A Small Craft Advisory is in effect late this morning through late Thursday morning."
  PZZ740 (out to 10 nm), tonight: "Wind N 10 kt … Seas 5 to 7 ft. Wave Detail: … W 7 ft at 14 seconds."
  The old `tgftp…/pzz750.txt` file is **stale (March 2025)**, so use the API.
- **CO-OPS tides**, San Diego 9410170 today:

  ```json
  {"t":"2026-11-25 08:34","v":"7.449","type":"H"},{"t":"2026-11-25 15:57","v":"-1.448","type":"L"}
  ```

- **CDIP 191, Point Loma South**, 18:00Z: `Hs(m): 2.15  Tp(s): 13.33  Dp(deg): 275`.

**How it helps.**
- Trip planner cards: "⚠ Small Craft Advisory on your departure day; seas 8–12 ft".
- Co-Captain answers ("will it be rough Saturday?").
- A data-health cross-check: a short count day plus an SCA means the day isn't a data gap.

It does **not** help catch forecasting (forecast-rnd: weather adds nothing). It may help a different target, *P(trip runs / gets cancelled)*, which is H6.

**Integration sketch.**
- Extend `src/weather.py` with `nws_cwf(zone)` (parse the `.TODAY…` periods), `coops_tides(station)`, and `cdip_latest(stn)` via THREDDS.
- Add NDBC 46086 (San Clemente Basin), 46047 (Tanner Bank) and 46025 (Santa Monica Basin) for offshore context.
- Cache 1 h.
- Mapping: SD → PZZ740/750/775; OC/LA → PZZ655/750; SF → PZZ530/545.

No keys; send a descriptive User-Agent. **Owner agent:** app-dev. **Effort:** about 1 day.

---

## 4. Quick wins (do first, in this order)

1. **Archive AIS positions** (Brief 1, step 1). Do it today: every day not archived is history lost for good, and it needs no new source or terms.
2. **Snapshot schedules.** Add a `schedule_snapshots(source_id, scraped_at, open_spots, price)` table, or stop overwriting. That gives "filling fast" badges and forecast H3. Same rule: history can't be backfilled.
3. **NWS/tides/CDIP conditions pack** (Brief 5): about 1 day, zero risk, visible on every trip card.
4. **Landing "Update" extraction** (Brief 2): about 1–2 days, adds size grade and bait.
5. **Owner emails CDFW MFSU** (Brief 3): 1 hour of owner time; the long lead time is why it should start now.
6. **Static regs card** (CDFW bag limits, Mexican licence for all passengers, bluefin limits) for trip pages and Co-Captain. Half a day, curated by hand, with a "last checked" date.

## 5. Hypotheses handed to forecast R&D

These were sent to "Fish forecast R&D: model and backtest" and written to the shared notes folder (`data-sources-forecast-hypotheses.md`). All are untested, and the evidence bar is held-out walk-forward AUC on top of the round-4 momentum model.

| # | Hypothesis | Data | Backtestable now? |
|---|---|---|---|
| H1 | **Fleet AIS behaviour adds skill beyond catch momentum.** Examples: yesterday's fleet centroid distance from port, the share of boats converging on one block, how long boats drifted (fishing) vs. ran. | Marine Cadastre 2009–2024 (already downloaded for some years) | **Yes** |
| H2 | **Size grade and bait type matter.** "Sardines on board" vs. anchovy, and max/avg fish size in the last 3 days, predict the per-angler outcome. | Landing narratives (start archiving now), BD `forum_signals` | Partly (BD history) |
| H3 | **Booking velocity is an insider signal.** Open spots at T-3 days vs. normal for that trip type and season leads catch momentum, because regulars rebook when it's hot. | Schedule snapshots (start now) | No (needs about 1 season) |
| H4 | **A block-level CPFV climatology** (40 years, by month) beats our landing × trip-length × ±15-day climatology, especially for rare years. | CDFW MFSU request | After the data arrives |
| H5 | **HF-radar convergence/fronts.** Low prior, given ocean variables failed; only test if H1 shows location matters. | HFRNet 2012→ (currently 404) | Later |
| H6 | **A new target, P(trip cancelled or short load).** NWS SCA/seas forecasts at T-1 to T-3 predict cancellations and underfilled trips. This is useful for trip planning even though weather doesn't predict catch. | NWS archive (Iowa Env. Mesonet keeps text products) + our schedule/trip rows | Yes, roughly |

## 6. Flags for the owner

- **Existing practice, not new:** `scripts/scrape-mmsi.py` scrapes VesselFinder, whose ToS §9 forbids automated extraction "except through authorized APIs". Its one-time job (MMSI discovery) is done. Recommend stopping it and keeping `data/vessel_mmsi.json` up to date by hand.
- **HF-radar currents are down:** `ucsdHfrW6` returns "Currently unknown datasetID" on CoastWatch (and on the `upwell` mirror, which redirects there). Don't build the currents layer on it until it's back; Copernicus is the fallback.
- **aisstream has no published terms.** Ask before showing positions publicly, delay the map by 24 hours, and show aggregates.
- **Google/TripAdvisor review terms** don't allow storing reviews. They can't feed `boat_reviews`, Claude summaries or SEO pages; they can only be displayed live with attribution.
- **Research conduct note:** we fetched Fishdope's public home and terms pages once each with a browser User-Agent. Its robots.txt allows `*` but blocks ClaudeBot. We didn't fetch RecFIN pages or the disallowed sandiegofishreports pages.

## 7. What to sign up for (owner action; we did none of this)

| Service | Why | Cost |
|---|---|---|
| Google Cloud project + Places API key | Brief 4 | $0 up to 1,000 Enterprise+Atmosphere calls a month, then $25 per 1,000 (a card is required) |
| Copernicus Marine account (only if HF radar stays down) | Currents layer | Free, commercial use with credit |
| YouTube Data API key (optional) | Boat-page videos | Free, 10,000 units/day |
| Email CDFW MFSU | Brief 3 | Free |
| GitHub issue to aisstream asking about commercial display | Brief 1 | Free |
| *Not recommended:* Yelp ($229+/month), Fishdope ($199/yr, forbids commercial use), FishTrack (~$96/yr, consumer only) | — | — |

## Sources

- Code: `scripts/ais_push.py`, `src/schedule.py`, `src/db.py` (`scheduled_trips` UNIQUE key), `src/conditions.py`, `src/weather.py`, `web/ais_positions.json`, `data/vessel_mmsi.json`
- Fisherman's Landing: [fish counts](https://www.fishermanslanding.com/fish-counts/), [trip report 247457](https://www.fishermanslanding.com/detailed_report.php?report_id=247457), [robots](https://www.fishermanslanding.com/robots.txt); [H&M robots](https://www.hmlanding.com/robots.txt); [Seaforth robots](https://www.seaforthlanding.com/robots.txt)
- [aisstream.io](https://aisstream.io/), [docs (limits)](https://aisstream.io/documentation); [Marine Cadastre](https://coast.noaa.gov/)
- [CDFW Pelagic catch / CPFV summaries](https://wildlife.ca.gov/Conservation/Marine/Pelagic-Fisheries/Catch), [CDFW MFSU](https://wildlife.ca.gov/Conservation/Marine/MFSU), [NOAA InPort: CPFV Fishery](https://www.fisheries.noaa.gov/inport/item/2325), [Pacific Council HMS rec description](https://www.pcouncil.org/?p=61214)
- [NWS API CWF SGX](https://api.weather.gov/products/types/CWF/locations/SGX/latest); [CO-OPS API](https://api.tidesandcurrents.noaa.gov/api/prod/); [CDIP](https://cdip.ucsd.edu/), [CDIP robots](https://cdip.ucsd.edu/robots.txt); [NDBC robots](https://www.ndbc.noaa.gov/robots.txt); [CPC ONI](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt)
- HF radar: [data.gov listing](https://catalog.data.gov/dataset/currents-hf-radar-us-west-coast-rtv-near-real-time-2012-present-hourly-6km), [SCCOOS HFR](https://sccoos.org/high-frequency-radar/), [CoastWatch ERDDAP](https://coastwatch.pfeg.noaa.gov/erddap/info/ucsdHfrW6/index.html) (404 on 2026-11-25)
- Copernicus: [licence](https://marine.copernicus.eu/user-corner/service-commitments-and-licence), [free in future?](https://help.marine.copernicus.eu/en/articles/4220312-i-just-opened-my-account-but-will-it-still-be-free-in-2-3-or-5-years)
- Google: [Places pricing](https://developers.google.com/maps/billing-and-pricing/pricing), [Places SKU details](https://developers.google.com/maps/billing-and-pricing/sku-details/places), [Places policies](https://developers.google.com/maps/documentation/places/web-service/policies), [Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)
- [TripAdvisor Content API FAQ](https://tripadvisor-content-api.readme.io/reference/faq), [rate limits](https://tripadvisor-content-api.readme.io/reference/rate-limits)
- Yelp: [TechCrunch on API charges](https://techcrunch.com/2024/08/02/yelps-lack-of-transparency-around-api-charges-angers-developers), [API report card](https://supergood.ai/api-report-card/yelp)
- [YouTube quota costs](https://developers.google.com/youtube/v3/determine_quota_cost), [YouTube robots](https://www.youtube.com/robots.txt)
- Meta: [IG Business Discovery](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-discovery), [App Review](https://developers.facebook.com/docs/instagram-platform/app-review), [Instagram robots](https://www.instagram.com/robots.txt), [Facebook robots](https://www.facebook.com/robots.txt)
- Global Fishing Watch: [licence & rate limits](https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits), [commercial FAQ](https://globalfishingwatch.org/faqs/can-i-use-global-fishing-watch-apis-for-commercial-purposes/)
- [VesselFinder terms](https://www.vesselfinder.com/terms); [MarineTraffic robots](https://www.marinetraffic.com/robots.txt)
- Fishdope: [home](https://www.fishdope.com/), [terms](https://www.fishdope.com/terms), [robots](https://www.fishdope.com/robots.txt); [sandiegofishreports robots](https://www.sandiegofishreports.com/robots.txt); [RecFIN robots](https://www.recfin.org/robots.txt); [kayakfishingsd robots](https://www.kayakfishingsd.com/robots.txt)
- FishTrack pricing: [paywall tracker](https://adapty.io/paywall-library/fishtrack/), [app pricing](https://apppricinglab.com/iap/apple/952022603)
- Bait: [San Diego Reader, Mar 2025](https://www.sandiegoreader.com/news/2025/mar/26/fishing-report-sardine-bait-is-back/), [WON: bait receivers](https://wonews.com/bait-receivers-running-light/)
- Mexico licence: [BajaBound](https://www.bajabound.com/before/permits/fishing), [MexPro](https://www.mexpro.com/blog/fishing-mexico/)
- FishingBooker: [example listing](https://fishingbooker.com/charters/view/12943)
- Prior internal docs: `docs/bloodydecks/DATA_OPPORTUNITIES.md` (claude/bloodydecks-revive-7f7db7), `docs/market/THIRD_MARKET.md` (claude/market-research-f9f582), forecast-rnd rounds 1–4 notes
