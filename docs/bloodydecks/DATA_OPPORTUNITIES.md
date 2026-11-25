# BloodyDecks: data opportunities

*Surveyed 2026-11-24. On 2026-11-25 the user approved building #1–#3. Status:*

| # | Built as | Where |
|---|---|---|
| 1 | Sportboats and Long Range feeds, with a 150-day first-run backfill. Claude writes into `forum_boat_reports`, with quote-checked aspect scores, a boat match plus `match_confidence`, and a landing-count join. | `scraper/paddies/boat_reports.py`; `web/api/v1/boat_forum_reports.json`; boat page → Reviews → "From BloodyDecks trip reports" |
| 2 | "What's working" per trip type (21-day window, widened to 45 days when there are few reports) | `web/api/v1/whats_working.json`; trip planner card |
| 3 | Research-only `forum_signals` (birds, bait, water temperature and colour, bite windows, size grade), every value quote-checked | `data/paddies.db`; `python -m scraper.paddies.boat_reports --signals-csv out.csv`; handed to forecast R&D, never shown on the site |

Health alerts cover the new feeds: `bd:feed-errors:<feed>`, `bd:no-new-posts:<feed>` and `bd:boat-reports`.

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
