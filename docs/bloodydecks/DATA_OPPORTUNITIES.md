# BloodyDecks: data opportunities

*Surveyed 2026-11-24. On 2026-11-25 the user approved building #1–#3. Status:*

| # | Built as | Where |
|---|---|---|
| 1 | Sportboats and Long Range feeds, with a 150-day first-run backfill. Claude writes into `forum_boat_reports`, with quote-checked aspect scores, a boat match plus `match_confidence`, and a landing-count join. | `scraper/paddies/boat_reports.py`; `web/api/v1/boat_forum_reports.json`; boat page → Reviews → "From BloodyDecks trip reports" |
| 2 | "What's working" per trip type (21-day window, widened to 45 days when there are few reports) | `web/api/v1/whats_working.json`; trip planner card |
| 3 | Research-only `forum_signals` (birds, bait, water temperature and colour, bite windows, size grade), every value quote-checked | `data/paddies.db`; `python -m scraper.paddies.boat_reports --signals-csv out.csv`; handed to forecast R&D, never shown on the site |

Health alerts cover the new feeds: `bd:feed-errors:<feed>`, `bd:no-new-posts:<feed>` and `bd:boat-reports`.

*Second round, 2026-11-25 (branch `claude/bd-spots`, not yet merged):*

| # | Built as | Where |
|---|---|---|
| 4 | **Spot locations.** Trip reports now record every place the trip fished, saw fish/paddies/kelp, or where "the fleet" was (`forum_locations`, append-only, quote-checked; coordinates and "N miles <dir> of X" offsets are parsed in code from the quote, never taken from the model). `spots.py` merges these with the paddy-forum mentions into `forum_spot_reports`: date, knowable-at time, species, catch quality, source link, geocode method and confidence, precision radius. | `scraper/paddies/spots.py`; `data/forum_places.json` (Baja / long-range places the SWYC list lacks); `web/api/v1/forum_spots.geojson`; `python -m scraper.paddies.spots --research-csv out.csv` for forecast R&D |
| 5 | **Positions as posted** (owner's decision, 2026-11-25: "if they posted it online then its fair game"). Coordinates printed in a thread are published as written, with `precision_nm` 0.1. "N miles off X" estimates get max(1 nm, N/4), and named spots get the spot's radius. Every point has `position` (posted / estimate / spot), a date and a thread link. `reports.json` pins gain `precision_nm`. | `spots._exact_fields`, `spots.offset_precision` |
| 6 | **Back-catalogue for boat reviews**: the trip-report extractor now accepts threads up to 365 days old (was 120, which silently skipped any listing backfill), runs 80 posts per run (was 40), and the workflow takes `backfill_feeds` so a one-off year walk touches only Sportboats + Long Range. | `boat_reports.MAX_POST_AGE_DAYS`; `paddies.yml` |
| 7 | **Region tags for OC/LA** (`san_diego` / `oc_la` / `both` / null, the site's region ids). Each item takes the union of its boat's landing region (parsed from `web/regions.js`), the regions of the spots it names, title keywords (Catalina, PV, Horseshoe, Point Loma…) and, as a fallback, the forum (Long Range / Baja → SD). An SD boat at Catalina is `both`; 4+ day trips use the landing only. Every output carries it: boat entries and reports, `whats_working.by_region`, spot features, `banks.json`, `paddies.json` banks, and `reports.json` banks and pins. The gazetteer gains OC/LA coast and Channel Islands places. A new `bd-california` feed (California Sport Fishing Reports) brings in Catalina, SCI and inshore reports. | `scraper/paddies/regions.py`; `data/forum_places.json` |
| 8 | **The landings' own reports** (data-sources Brief 2, owner-approved 2026-11-25). These are read from the report feeds of sandiegofishreports.com and socalfishreports.com, which carry the landings' daily updates, "called in with …" posts and skipper reports, including longrangesportfishing.net for the long-range boats. Each run fetches 2 listing pages, then one page per new report at 2.5 s intervals; robots.txt allows all three sites. Claude records per boat: size grade, bait (type, on board), tackle, a skipper note, conditions, one quote and the open spots a post advertises. Size, bait and tackle values each need a verbatim quote found in the post. Photos are hot-linked from media.fishreports.com and never re-hosted. | `scraper/paddies/landing_reports.py` → `landing_notes.json` (boat page "From the landing"; `by_region`; `open_spots`), merged into What's working with `source: landing`; `--research-csv` for forecast H2 |

## TL;DR

The best find is the **Southern California Sportboats** forum
(`/forums/forum/southern-california-sportboats/`), a subforum we don't ingest yet. It is almost
entirely party-boat trip reports.

- In season (Jul–Sep 2026) it gets **25–35 threads a month**.
- About **70–85% of titles name a boat in our `boats` table**, covering **15–22 distinct boats a month**.
- Reports routinely praise or criticise the captain, crew, galley and bunks, and give catch, bait and tackle details.
- They can be **joined to our landing counts**: the Pacific Queen 11/8–11/10 report says "24 anglers, 11 yellowfin", exactly the `trips` row (24 anglers, 11 YFT).

**Ranked opportunities**

| # | Opportunity | Value | Effort | Notes |
|---|---|---|---|---|
| 1 | **Forum-sourced boat reviews** (Sportboats + Long Range forums → per-boat sentiment summaries) | High: we have **1** review in `boat_reviews` today | Medium | Reuses the v2 ingest (listing + thread-body fetch) and Claude extraction. Store in a new table, *not* `boat_reviews` (see Risks). |
| 2 | **"What's working" tackle/bait card per trip type** (line test, hooks, jigs and colours, bait quality, bird problems) | High for users, low for the forecast | Low once #1 exists | Comes out of the same extraction pass. |
| 3 | **Forecast-candidate signals**: bird/shearwater pressure, bait quality and size, water temperature and colour, fleet location ("Colonet", "the Ridge", "St Martin"), bite windows | Unknown; needs backtest | Low–medium | Some of this is already extracted from SoCal Offshore paddies posts. Sent to the forecast R&D agent as hypotheses. |
| 4 | **Trip-planning / open-load signals** ("help get it off the dock", "needs 3 more", limited-load reductions) | Medium (a "trips looking for anglers" widget) | Low | Titles alone carry most of it. Very time-sensitive. |
| 5 | **Long-range season narrative** (7–16 day trips) | Medium; a niche but passionate audience | Medium | Long reports (10–17k chars). Many LR boats are missing from our `trips` table (Searcher, Vagabond had no Nov rows). |
| 6 | Classifieds (used tackle prices), Fishing Gear forums | Low for this site | — | Out of scope; skip. |
| 7 | Other regions (NorCal, Oregon, Hawaii…) | Low; we only track SoCal landings | — | Skip unless the region toggle expands. |

## 1. Survey

**Access**
- All forums below are readable **without login**: forum listing pages, thread pages and per-forum `index.rss`.
- Each RSS feed has 25 items. For Sportboats that's about 5 weeks this time of year; for Long Range, about 2 weeks.
- RSS bodies are ~500-character excerpts, so full text requires a thread fetch. The v2 ingest already does this.

**robots.txt** (`www.bdoutdoors.com/robots.txt`)
- For `*` it disallows only `/forums/cron.php`, `/forums/vbseocp.php`, `/bdhosted` and a WP import path. Forum threads and RSS are allowed.
- bingbot gets `Crawl-delay: 1`. We use ≥2–2.5 s between requests anyway.

**Terms** (`/forums/help/terms/`)
- No explicit anti-scraping clause.
- **Users retain copyright** in their posts and grant BD a licence. We have no licence, so we must **not republish posts**. Short quotes, our own summaries and a link back are the defensible pattern.

| Forum | Content | Volume (2026, by thread start) | Login? | Use |
|---|---|---|---|---|
| Southern California Offshore Reports *(ingested)* | Mostly private-boat reports, paddies, banks | Daily | No | Paddies (live) |
| **Southern California Sportboats** | Party-boat trip reports, "get this trip off the dock" threads, landing Q&A | Jul 30, Aug 31, Sep 34, Oct 22, Nov 14 | No | **Boat reviews**, tackle card, open loads |
| **Long Range Fishing** | 3–16 day trip reports, roll calls, gear threads, crew-tip etiquette | Jul 16, Aug 22, Sep 43, Oct 32, Nov 21 (≈30–40% name a tracked boat) | No | LR reviews, season narrative |
| Southern CA Fishing Trip Planning | Weather/NOAA posts, charter open spots, "which trip?" | Several per week | No | Open loads (minor) |
| Baja / Mexico Reports *(feed exists, enabled)* | Panga and lodge reports (Cedros, East Cape) | Weekly | No | Water temperature, El Niño context |
| Spearfishing *(enabled)* | Vis/temperature reports | Weekly | No | Water clarity |
| Classifieds, Gear, Boating, Hunting, etc. | — | — | Some need login | Skip |

Monthly counts come from 8 listing pages for Sportboats and 6 for Long Range, filtered to threads started in 2026. The forums sort by last post, so older months are undercounted, though Jul–Oct should be close.

## 2. Boat reviews from trip reports

### What's extractable (from 16 sampled reports)

| Field | `boat_reviews` column | Reliability | Notes |
|---|---|---|---|
| Boat name | `boat` | **High** | Usually in the title ("Pacific Queen 2 day 11/8-11/10"). Abbreviations ("PQ") and multi-boat posts ("Dolphin full days… Grande yesterday") need an alias map plus Claude. |
| Landing | `landing` | High via join | Rarely stated; take it from the `boats` table or the matched `trips` row. |
| Trip date / length | `trip_date`, `trip_length` | **High** | Title convention "3 day 10/26-10/29". Typos happen ("Tribute 10/30-9/1"), so validate against `trips`. |
| Captain sentiment | `captain_rating` | Medium–high when present (~60%) | "Captain Jeff mandated a fishing break" (neutral/positive), "John is awesome!!!" |
| Crew sentiment | `crew_rating` | **High when present (~75%)** | The most common praise target. |
| Galley | `galley_rating` | Medium (~50%, mostly 2+ day trips) | "Jesse absolutely knocked it out of the park", "most tender porkchop". Prices often given (meal plan $80, tab $49). |
| Bunks / comfort | `bunks_rating` | Low (~25%) | "bunk in the bow… brutal", "better of the 2 bunks". |
| Fish-finding | `fish_finding_rating` | Medium | Inferred from catch vs. effort and the skipper's moves. This is a judgment, so the model must be conservative. |
| Would rebook | `would_rebook` | Medium (~50% explicit) | "will look to get on again next year", "I'd gladly fish with them again". |
| Species / counts | `species_caught`, `tuna_count` | **High** for boat totals when given; personal counts are mixed in | Prefer the landing's `trips` row for boat totals. |
| Sizes, baits, lures, line, spots | *(no column)* | **High** | The richest, most consistent content: "40–50 lb fluoro, #1–1/0", "mint/white yo-yo", "pink Marauder", "Colonet", "the Ridge". |
| Overall | `overall_rating` | Medium | Derive from the above, not a free guess. |

**Usable share per report**
- On the boat-name-in-title threads (≈70% of Sportboats threads), ~85–90% are actual trip reports.
- The rest are "help get it off the dock", gear questions ("Fathom 40 NLD2") or chit-chat. A cheap classifier step (title + first 500 chars) filters them.
- Of a genuine report, typically **20–40% of the text is review-relevant**; the rest is narrative and fishing detail.

**Coverage estimate**
- In season: **~20–28 usable boat reports a month across ~15–20 boats**.
- Off season: ~5–10.
- Long Range adds ~8–12 a month Sep–Nov.

So a popular boat gets 1–3 reports a month. That's enough for a running "what anglers say" summary, but not for numeric star averages that look authoritative.

### Sample extractions (hand-extracted with the proposed schema, 8 reports)

Sentiment is on a −2..+2 scale (`null` = not mentioned). Quotes are kept under 15 words.

1. **Pacific Queen, 2 Day, 11/8–11/10** (Fisherman's): [thread](https://www.bdoutdoors.com/forums/threads/pacific-queen-2-day-11-8-11-10.872292/)
   - captain +2 ("captain bobby"), crew +2, galley +2 ("cook dave"), bunks null, fish-finding +1 ("slow catching" but found them), would_rebook **yes** ("will look to get on again next year").
   - Catch: 24 anglers, 11 YFT to 50 lb, avg 25–30 → **matches `trips`**.
   - Tackle: 40–50 lb fluoro, #1–2/0 circle/J, green sardine "best of the season". Spot: Colonet zone. Bite window: morning of 11/9, ~2 h.
2. **New Lo Ann, 2 Day, 11/11**: [thread](https://www.bdoutdoors.com/forums/threads/new-lo-ann-11-11-2-day-pretty-great.872398/)
   - captain +2 (saved the trip after the generator failed), crew +2 ("work ethic was beyond description"), galley null.
   - **Negative: felt pressured on the tip** (skipper counted the tip, suggested 18–22%). would_rebook null.
   - Catch: YFT 20–40 plus some 60+, yellowtail, 1 wahoo, marlin. Spot: San Martín Island. Price: $880 + $50 fuel.
   - *No `trips` row found.* Either a name mismatch or the boat isn't tracked; worth checking.
3. **Islander, 3 Day, 10/23** (Fisherman's): [thread](https://www.bdoutdoors.com/forums/threads/quick-report-islander-3-day-10-23-26.872028/)
   - captain +1 (helped load gear, explained the plan), galley +2 (porkchop), bunks +1, **rod storage −1** (no numbered racks).
   - Catch: YFT 30–50 lb on 40–50 lb, marlin hooked. Rain squalls.
4. **Constitution, 3 Day, 10/26–10/29** (Fisherman's): [thread](https://www.bdoutdoors.com/forums/threads/constitution-3-day-10-26-10-29-26.872085/)
   - captain +1 ("Captain Jeff" called a bird break), crew null, galley neutral.
   - Catch: wide-open YFT at grey light, 30 lb-grade yellowtail on a mint/white JRI 66 and 60# sinker rigs.
   - Birds bad in the afternoon. Spot: Colonet at anchor; planned paddy trolling on the way home. `trips`: 20 anglers, 55 YFT, 22 YT. ✔
5. **Tribute, 1.5 Day, 10/30** (Seaforth): [thread](https://www.bdoutdoors.com/forums/threads/tribute-10-30-9-1.872083/)
   - would_rebook implied +; "Great trip and light load with 17 people!"
   - Galley prices: meal plan $80, tab $49, fuel $40.
   - Catch: YFT to 80 lb on the slide (30 lb), skipjack; "limits of dorado" were ~1 lb fish, a **useful caveat on the count**.
   - Spot: Colonet, then dolphin schools. `trips`: 18 anglers, 30 YFT. ✔ (title date typo "9/1")
6. **Pursuit, Catalina, early Sep**: [thread](https://www.bdoutdoors.com/forums/threads/pursuit-9th-inning-2-outs-down-2-runs.870877/)
   - captain +2 ("John is awesome!!!", "knows the island better than most").
   - Catch: 17 YT, all over 20 lb, at the last stop, on fluoro. Late return (1.5 h).
7. **Monte Carlo, ½ day AM, 10/17**: [thread](https://www.bdoutdoors.com/forums/threads/monte-carlo-10-17.871746/)
   - crew +2 ("deckhand Brian" catered to the kids). Load −1 (booked ~20, sailed ~50).
   - Kid-friendly signal. Catch: calico, sand bass, sheephead, small YT, bonito.
   - Half-day trips are excluded from our metrics but still useful for reviews.
8. **Searcher, 8 Day, 11/9–11/17** (Point Loma), two reports: [#1](https://www.bdoutdoors.com/forums/threads/8-day-searcher-report-nov-9-17.872469/), [#2](https://www.bdoutdoors.com/forums/threads/searcher-8-day-different-take.872516/)
   - captain +2, crew +2, galley +2 ("Jesse… knocked it out of the park"), **bunks −1** (bow on a 14 h uphill ride), boat "beginning to show its age" −0.5, would_rebook **yes** (both reports).
   - Fuel $480/person.
   - Catch: wahoo on pink/orange Marauders, YFT to 60 on the Ridge, yo-yo YT on mint/white; bait 4–7 in.
   - **Shows the value of aggregation**: one report calls the fishing "slow", the other defends the skipper. A summary should present both.
   - *No `trips` row found for Searcher.*

Also sampled, but not boat reviews: "Local full days" (multi-boat; Dolphin and Grande tackle notes, bird pressure); "Seaforth 11/5" (actually a ¾-day Sea Watch); a Vagabond 10-day (17k chars, crew named, fishing every day); a Cedros lodge report; a gear question; and an off-topic Mayflower post. These show why a classification step is needed.

### Proposed design (if we build #1)

- **Ingest.** Add `southern-california-sportboats` and `san-diego-long-range-sportfishing-reports` to `scraper/paddies/feeds.py`. The listing, backfill and body-fetch code already supports any XenForo forum. Keep the 2.5 s spacing.
- **Extract.** A separate Claude prompt returns `{is_trip_report, boat_mentions[{boat, trip_date, trip_length, captain, crew, galley, bunks, fish_finding, would_rebook, evidence_quote≤15 words}], catch[], tackle[], spots[], conditions{}}`. Store results in a **new `forum_boat_mentions` table**, not `boat_reviews`.
- **Match.** Match the boat to the `boats` table via an alias map ("PQ" → Pacific Queen), then to a `trips` row by boat ± 2 days and trip length. A matched trip gets the landing counts and a "trip confirmed by landing count" badge.
- **Show.** On the boat page, add a **"From forum trip reports (BloodyDecks)"** panel with:
  - a 2–3 sentence Claude summary over the last N reports;
  - per-aspect thumbs (positive/mixed/negative, with counts);
  - "N of M mention they'd rebook";
  - a link to every source thread.

  No star ratings, and never mixed into the user-submitted review average.

## 3. Other signals (forecast candidates)

Sent to the "Fish forecast R&D: model and backtest" session as hypotheses only:

> **Status (2026-11-25): none of these is tested.** Forecast R&D ranks bird pressure and bait quality as the most promising to test, because recent catch momentum (its strongest input) can't see them. Nothing will be backtested until about a season of `forum_signals` rows exists. Don't cite any of these as an improvement until R&D reports a held-out result.

- **Bird pressure (shearwaters)**: mentioned in 5 of 16 reports in Oct–Nov as *the* limiting factor ("Birds birds birds"). This is a catch-*rate* suppressor independent of fish presence, and could explain low counts on days with fish around.
- **Bait quality and size** ("green and slimy sardine, best of the season", "4–7 inch", "mostly anchovy under 4 in") versus catch per angler.
- **Fleet location by trip length** (Colonet, San Martín, the Ridge, Cedros, Catalina backside) as a weekly "where the fleet went" series.
- **Bite timing** (grey light vs. twilight vs. "last stop") as a distribution per species.
- **Water temperature / El Niño mentions** from Baja and Spearfishing posts. These are weak, and satellite SST is better.
- **Size grade** ("dorado were all 1 lb", "YFT 20–40 with 60+") to complement count-only landing data.

## 3b. Spot coordinates

**What a report gives us, by source**

| Source | Location signals | How it is placed |
|---|---|---|
| SoCal Offshore / Baja / Spearfishing (`report_mentions`) | SWYC bank ids, GPS numbers, "3–4 miles off IB", paddies, bite outcome, water temp | Bank centre, or the parsed / computed position as posted |
| Sportboats / Long Range (`forum_locations`) | Named banks, islands, kelp, paddies, "the fleet was at …", coordinates, offsets, species, quality, temp | Gazetteer + `forum_places.json` lookup; offsets from the named place |
| Older trip reports (`forum_boat_reports.spots`) | Names only | Gazetteer lookup |

On the current DB: 342 place mentions, 171 placed. The rest are paddy-forum bite/conditions rows with no place, plus names we deliberately leave unresolved because they are ambiguous ("the Ridge", "the Rocks", "Lower Banks", "13 Fathom") or not yet in `forum_places.json` ("San Carlos", "San Pablo Bay", "Juggs Bank"). `spots_unresolved_names` in the state file lists them, so the gazetteer can be extended with a source and confidence for each.

**Public layer** (`forum_spots.geojson`): one point per named spot, plus one per posted or estimated position, for the last 14 days. Each has 7-day and 14-day report counts, species (fixed site vocabulary plus "other"), catch-quality tallies, water temperature range, kinds (bite, paddy, kelp, fleet…), `position`, `precision_nm` and up to 5 thread links. No quotes or usernames.

**Research series** (`--research-csv`): every row with report date, trip date, published and fetched (knowable-at) times, the point, precision, species and quality. Forecast R&D: hypotheses only; nothing here is a tested predictor.

## 3b-2. OC/LA coverage (2026-11-25, current DB)

- **Posts**: of 569 stored posts, 49 are OC/LA and 10 both. 289 can't be placed yet, mostly because they haven't been extracted (486 are pending). Placed OC/LA posts by month: Sep 36, Oct 11, Nov 6, which works out to about 9 a week in September and 1–3 a week since. Most come from the SoCal Offshore forum (private boats at Horseshoe, the Domes, the Slide, 14 Mile Bank, Catalina).
- **Spots**: 84 of 171 placed mentions are in OC/LA or both. The top spots are Horseshoe (31), Domes (11), the Slide, 105 Spot, 209, Salt Creek, 14 Mile Bank and Catalina.
- **Boats**: 1 of the ~60 OC/LA boats that ran trips in the last year has a forum review (Pursuit, 22nd Street). The Sportboats forum is mostly San Diego boats.
- **Thin**: OC/LA party-boat reviews and anything north of Palos Verdes (Channel Islands, Ventura, Oxnard). The year back-catalogue and `bd-california` will help a little. OC/LA landings' own report pages would do more than BloodyDecks, but that's out of scope here.

## 3c. Next proposals (ranked)

1. **Open-load / "needs N more" trips** (Sportboats + Trip Planning forums). Titles alone carry most of it ("Help get the X 1.5 day off the dock 12/5"). A small "Trips looking for anglers" list on the trip planner, each linking to the thread, auto-expiring after the departure date. Low effort, high value for users, time-sensitive, so it needs the 3-hourly run.
2. **Show the forum panel from 1 report** on boats with a landing-count match. Today it needs 2 reports, so only 2 of 120 active boats show it. One matched report is still a useful, honest signal with the "not a verified review" label. UX call for the design sessions.
3. **Tackle and bait by month and species** from `forum_boat_reports.tackle`/`bait` (already extracted): a "what people used last October for YFT" view. Low effort once a season of rows exists.
4. **Long-range season narrative** (per-trip one-liners for 8–16 day trips). Medium effort, niche audience.

## 3d. Full-site forum survey (2026-11-26)

**Method.** I listed every forum on the BloodyDecks index (about 90 across 6 categories). From the latest 25 RSS items of each of the 17 forums that could hold SoCal or Baja catch data, I measured:
- the rate of new threads;
- how often posts name a species, a SoCal place, or an image;
- the region tags.

I also read 5 full threads from the main forums to measure replies and photos. robots.txt blocks only cron, admin and wp-import paths. Everything was fetched as a guest, with 2–3 s between requests.

**Already read (6 feeds):** SoCal Offshore, Sportboats, Long Range, Baja, Spearfishing, California Sport Fishing Reports.

**Biggest gap: replies.** `ingest_bd` stores only each thread's first post. Busy threads run 10–35 replies, and about 15–20% of those are reports in their own right: "we were there too", a second count, water temperature, what bit. Sampled threads:

| Thread | Replies | Useful replies |
|---|---|---|
| Yellowfin-November 24th | 22 | 4 |
| Cat East End Yellowfin | 11 | 2 |
| Searcher 8 day | 36 | 4 on page 1 |
| Boring Fish Report | 20 | 1 |

Reading replies would roughly double the useful posts. Each useful reply costs one Claude call, so pre-filter with the species/place regex.

**Forums worth adding**

| Forum | New threads/wk | SoCal signal | Use |
|---|---|---|---|
| Southern CA Fishing Trip Planning | 3.3 | 16/25 SoCal, **10 OC/LA** | Open spots on private charters, NOAA and small-craft forecasts, ramp status. Best OC/LA add. |
| Kayak Fishing | 0.9 | 15/25 SoCal | La Jolla kelp, yellowtail, halibut. Inshore SD signal. |
| Surf Fishing | 0.7 | 9/25 | Surf and inshore. Low value for tuna. |
| Jet Ski Anglers | 0.2 | 9/25 SD | La Jolla and SD Bay runs. Tiny volume. |
| Open Seat | ~0 | open loads | Superseded by the Sportboats "help get it off the dock" threads. |
| Northern CA Reports | 0.8 | Half Moon Bay bluefin, salmon | **For the SF Bay page**, not SD/OC-LA. |
| Central CA Reports | 0.5 | Morro Bay bluefin | Same: SF Bay or a future Central Coast page. |
| Mexico Fishing Reports (parent) | 0.9 | Bay of LA, Abreojos | Mostly mainland and Sea of Cortez. Skip; Baja is already read. |

**Skipped, with reasons**
- Chit Chat (25/wk, mostly gear and off-topic).
- Fishing Tips, Jigging, Reels, Rod Building, Brand forums (gear, no catches).
- Boating and Electronics.
- CA DFW Q&A (regulation questions, about 0.2/wk).
- Yellowtail Shootout (tournament promotion).
- Fly, Paddle Board, Saltwater Fly (under 0.2/wk).
- Hunting, Camping, Sports, Classifieds, and every out-of-state forum.
- The pinned "Updated Bait Reports" thread, about 1 post a month.

**Photos.** Forum photos are XenForo attachments (`/forums/attachments/<name>.<id>/`), linked from posts as "View attachment". They are full-size originals (a 2.5 MB JPEG in the sample), guests can fetch them, and they open with any referer. There is no public thumbnail. Embedding them on our pages would load BloodyDecks' full originals on every view, which is not polite.

Recommendation:
- store each post's attachment count and URLs;
- show "📷 3 photos on BloodyDecks" linking to the thread;
- keep embedded photo strips for the landings' own media.fishreports.com images (already built).

Rehosting thumbnails of user photos would need the owner's call; the users hold the copyright.

## 4. Risks

- **Extraction accuracy.** Sentiment from narrative text is subjective. Sarcasm and humour are common ("you know the drill", "Brave Pilgrims"), and multi-boat posts mix boats.
  - Mitigations: an `is_trip_report` gate, per-aspect `null` unless explicitly mentioned, a required evidence quote per aspect, and a spot-check of 50 extractions against hand labels before launch.
  - Expect high accuracy on boat, date and length, and moderate accuracy on aspects.
- **Presentation.**
  - Label everything "From forum trip reports". Never call it "verified" or turn it into star ratings.
  - Show sample size, and hide the panel below ~2 reports.
  - Keep it out of the user-review average and the leaderboard.
- **Attribution.**
  - Link every summary to its source threads, and credit BloodyDecks.
  - Show forum usernames only as part of the link, if at all. These are private individuals, so don't build author profiles.
- **Copyright.**
  - Users retain copyright, so store full text privately for extraction only (as paddies already does).
  - Publish only our summaries, plus quotes under 15 words with links.
  - Don't publish photos.
- **Fairness and defamation.** One angry report (a tip dispute, "that guy") can tank a boat with few reports.
  - Show positives and negatives together, require ≥2 reports, and avoid naming crew members negatively.
  - Give the boat owner a way to flag a summary.
- **Load and blocking.** About 2 extra forums at ≤1 request per 2.5 s, plus around 1–3 thread fetches per new report. That's tiny, and the existing 403/429 stop logic and health alerts cover it.
- **Cost.** About 30–40 reports a month × ~3–5k tokens is cents a month on Sonnet.

## Side observations (not fixed; for follow-up)

- `trips` has two identical Islander rows (10-26 and 10-27, both 25 anglers, 93 trophy). This is possibly a duplicate report counted on two dates.
- Searcher, Vagabond and New Lo Ann had no `trips` rows for these Nov trips, even though the reports confirm the trips ran. This is a possible coverage gap for long-range and Point Loma/H&M multi-day trips.
