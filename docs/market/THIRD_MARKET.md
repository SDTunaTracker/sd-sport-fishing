# Tunatracker: Third Market Recommendation

*Research date: 2026-11-25. Research only: no product code was changed. All sources were read politely, one page at a time, with no accounts or sign-ups. Anything marked **(est.)** is an estimate. Sources are listed at the end.*

---

## TL;DR

**Recommendation: Central & Northern California, from Santa Barbara to Bodega Bay. Launch the Central Coast first (Santa Barbara, Avila, Morro Bay, Monterey, Santa Cruz), then the SF Bay Area.**

- **The data is already in a format we parse.** These landings post per-trip counts (Boat | Trip Type | Anglers | Fish Count) on the same fish-report network that feeds San Diego and OC/LA today (fishcounts.com, socalfishreports.com, norcalfishreports.com, sportfishingreport.com, all on TECK.net). Two Central Coast landings (Morro Bay Landing and Patriot / Avila) already show up on the socalfishreports page our OC/LA scraper reads.
- **There is a deep archive.** Day-by-day dock totals go back to at least **2010** on sportfishingreport.com and **2019** on norcalfishreports.com. Both were verified live.
- **There is real volume.** Sampled summer days show 30–45 open-party boats and **~400–600 reported anglers per day** in Central and NorCal combined. That is roughly 50–65% of a San Diego summer day (est., from samples).
- **There is tuna.** Morro Bay's *Endeavor* posted **6 Pacific bluefin (up to 50 lb) on 2026-11-24**, and Fish Emeryville posted **3 bluefin on 2026-08-15**. The tuna is sporadic, but it is real and it is news when it happens.
- **Booking deep links work the same way as in San Diego.** Morro Bay Landing, Fish Emeryville and Patriot all book through **fishingreservations.net** subdomains, which `src/schedule.py` already parses.

**The biggest risk applies to every region, including the live ones.** sportfishingreport.com's Terms (updated 2026-09-01) forbid scraping and automated access to "current or historical fish counts" without prior written permission. That is the same network San Diego and OC/LA already rely on. **Get a data license or written OK from Sportfishing Report, Inc. / TECK.net before launching a new region, and ideally for the existing ones too.** This is not legal advice. See §6.

No other candidate comes close on the deciding factor. The East Coast, Gulf and Florida have large headboat fleets but **no shared, structured per-trip count feed**. Their reports are narrative posts, pool winners and Facebook. They would need boat-by-boat partnerships, not a scraper.

---

## 1. Scoring method

Each criterion is scored from 1 (poor) to 5 (excellent). The weights reflect the brief: data availability is weighted highest.

| Criterion | Weight | What a 5 looks like |
|---|---:|---|
| **Data availability** | **35%** | Daily per-trip counts (boat, trip, anglers, species) in HTML on a shared platform, with a multi-year archive |
| Market size | 15% | Many open-party boats, long season, high angler volume |
| Strategic fit | 15% | Adjacent to SoCal, shared audience, tuna present, clear next step |
| Demand signals | 10% | Strong search, forum and social interest |
| Product fit | 10% | The trophy-per-angler-per-day model works with light changes |
| Effort & cost | 10% | Reuses existing parsers and conditions sources, with low legal friction |
| Competition | 5% | No good normalized aggregator exists |

## 2. Scored comparison

| # | Market | Data (35) | Size (15) | Strategic (15) | Demand (10) | Fit (10) | Effort (10) | Compet. (5) | **Weighted** |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **1** | **Central + NorCal (Santa Barbara → Bodega), one region** | 5 | 4 | 4.5 | 4 | 3.5 | 4.5 | 4 | **4.43** |
| 1a | ↳ Central Coast only (SB, Avila, Morro Bay, Monterey, Santa Cruz) | 5 | 3 | 5 | 3 | 4 | 5 | 4 | 4.35 |
| 1b | ↳ SF Bay Area + North Coast only | 5 | 4 | 3 | 4 | 3 | 4 | 4 | 4.10 |
| 2 | Pacific Northwest (Westport / Ilwaco WA, Oregon coast) | 3 | 3 | 3 | 3 | 3 | 4 | 4 | 3.15 |
| 3 | Northern Baja (Ensenada / San Quintín) | 2 | 2 | 5 | 3 | 4 | 3 | 4 | 2.95 |
| 4 | Baja Sur (Cabo / La Paz / East Cape) | 1.5 | 3 | 4 | 4 | 3 | 2 | 3 | 2.63 |
| 5 | NJ / NY headboats (Pt Pleasant, Belmar, Cape May, Montauk, Captree, Freeport) | 1 | 5 | 1 | 5 | 2 | 1 | 3 | 2.20 |
| 6 | Florida Atlantic (Keys, Miami/Ft Lauderdale, Pt Canaveral, Jupiter/Palm Beach drift boats) | 1 | 5 | 1 | 4 | 2 | 1 | 3 | 2.10 |
| 7 | Gulf (Galveston, Orange Beach, Destin/PCB, Clearwater/Tampa) | 1 | 4 | 1 | 4 | 2 | 1 | 3 | 1.95 |
| 8 | New England (Pt Judith RI, Gloucester/Plymouth MA, Ogunquit ME), Outer Banks, Ocean City MD | 1 | 3 | 1 | 3 | 2 | 1 | 3 | 1.70 |
| 9 | Hawaii | 1 | 1 | 2 | 3 | 2 | 2 | 3 | 1.65 |
| 10 | Great Lakes | 1 | 3 | 1 | 3 | 1 | 1 | 3 | 1.60 |

*The scores are judgment calls based on the evidence below. Search-volume figures weren't measured: no keyword tool was used. Demand scores are proxies (metro size, fleet size, forum and report activity) and should be checked with Google Keyword Planner or Search Console before spending money.*

### Evidence by candidate (short form)

| Market | Where counts live | Format / scrapeable? | Archive | Notes |
|---|---|---|---|---|
| **Central Coast** | socalfishreports.com and sportfishingreport.com landing pages; socal `dock_totals/boats.php?date=` | HTML table, same template as our SoCal sources ✅ | 2010+ (verified 2010-07-17) | ~5 landings and ~10–15 open-party boats. Morro Bay Landing fleet: Avenger, Endeavor, Starfire and others. Patriot (Avila): Flying Fish, Patriot, Sunny Day. Santa Barbara Landing: Coral Sea, Stardust. Monterey: Chris', J&M. Santa Cruz: Stagnaro's, Monterey Bay Charters |
| **Bay Area / North Coast** | norcalfishreports.com landing pages; `dock_totals/?date=` | HTML table, same template ✅ | 2019+ verified (likely earlier) | ~20 landings reporting on peak days. Fish Emeryville is the anchor (7–12 boats/day). Others: Berkeley (Happy Hooker, California Dawn), Sausalito, SF, Half Moon Bay, Bodega Bay, Eureka, Fort Bragg |
| Pacific NW | sportfishingreport.com ("Washington Coast" and "Oregon Coast" regions) | Same template ✅, but sparse | 2024+ seen | Only 2–4 boats/day reporting (Westport: Predator, Mutineer, Blue Eyes; Ilwaco: Sea Breeze). Oregon Coast showed **no rows** on any sampled day. Mostly six-packs |
| Northern Baja | sportfishingreport.com (Sergio's, Ensenada) | Same template ✅, but sparse | patchy | Sergio's posted 1 boat on 2026-11-22 (El Cazador: yellowtail, whitefish, 1 YFT). Other Ensenada and San Quintín fleets don't post structured counts |
| Baja Sur | sportfishingreport.com "Baja California Sur" region | Same template, very sparse | patchy | 2 landings and 4 boats (13 anglers) on 2026-08-15. Cabo is a private charter and panga market, not open-party |
| NJ / NY | Each boat's website or blog (e.g. Viking Fleet Montauk report blog), Facebook | Narrative posts ❌. Pool winners and weights, rarely angler counts | Viking has years of blog posts | Large headboat fleets, but no shared platform and no per-trip angler counts |
| Florida / Gulf | Facebook, FishingBooker reviews, boat websites | Narrative or reviews ❌ | n/a | NOAA's Southeast Region Headboat Survey covers ~96 Atlantic and ~94 Gulf headboats in **confidential logbooks**, not public daily data |
| Hawaii / Great Lakes | Charter websites | ❌ | n/a | Almost no open-party model. Great Lakes is charter/six-pack |

---

## 3. Top 3 briefs

### #1: Central & Northern California (Santa Barbara → Bodega Bay)

**What it is.** These are the open-party landings north of Point Conception. Our OC/LA region already covers Channel Islands Sportfishing (Oxnard) and Ventura Harbor. This region picks up where those leave off.

| Sub-area | Landings (open-party, reporting) | Typical trips |
|---|---|---|
| Santa Barbara | Santa Barbara Landing (Coral Sea, Stardust) | 3/4 day |
| San Luis Obispo | Patriot Sportfishing (Avila), Morro Bay Landing, Virg's / Black Pearl | 1/2 day, 3/4 day, full day, occasional overnight tuna |
| Monterey / Santa Cruz | Chris' Fishing Trips, J&M, Stagnaro's, Monterey Bay Charters | 3/4 day, full day |
| SF Bay Area | Fish Emeryville, Berkeley (Happy Hooker, California Dawn), Sausalito, SF piers, Half Moon Bay / Pillar Point | full day, salmon, crab combos |
| North Coast | Bodega Bay Sportfishing Center, Eureka, Fort Bragg / Noyo | full day |

**1. Data availability (5/5).**
- The per-trip HTML table is the same one we already parse: Boat | Trip Type | Anglers | Fish Count. It was verified on Morro Bay Landing (latest 2026-11-24), Santa Barbara Landing (2026-11-22), Fish Emeryville (2026-11-23) and Monterey Bay Charters (2026-11-23).
- Daily region roll-ups are available by date: `norcalfishreports.com/dock_totals/?date=YYYY-MM-DD` and `sportfishingreport.com/dock_totals/?date=YYYY-MM-DD`. The socal `dock_totals/boats.php?date=` page already lists Morro Bay and Avila boat by boat.
- There are monthly per-landing archives: `sportfishingreport.com/landingdetail.php?month=M&year=YYYY&landing_id=N` (Morro Bay = 311).
- Archive depth: 2010-07-17 returned real Central Coast rows (Patriot, Virg's), and NorCal 2019-07-20 returned 17 landings.
- **Consistency caveat:** small landings post irregularly. Many days have only 1–2 boats in winter (Nov 23: one Santa Cruz crab trip). NorCal dock totals show "No Counts Provided Today" on slow days.

**2. Market size (est.)**
- Sampled peak days: 2026-07-04 had Bay Area 31 boats / 387 anglers plus Central 8 / 180. 2026-07-18 NorCal had 36 boats / 496 anglers. 2026-08-15 had Bay Area 21 / 298, Central 11 / 223, and Santa Barbara 57 more.
- Rough annual reported volume: **~80k–130k angler-trips (est.)**. That assumes ~450 anglers/day for ~150 peak days plus ~100–150/day for the rest of the year. San Diego posted 863 anglers on the same 2026-08-15 sample day, so this is a market about half San Diego's size.
- CDFW requires every CPFV ("party boat") to file a logbook with angler counts (14 CCR §165, separate forms north and south of Point Conception), with public data back to 2000. Ask CDFW's MFSU (AskMarine@wildlife.ca.gov) for official regional totals to replace the estimate.
- Season: groundfish runs roughly Apr–Dec (state season and depth rules change yearly). Salmon depends on yearly openings (it was open in 2026: Emeryville posted 74 kings on 2026-07-18). Dungeness crab combos run Nov–Jun. Tuna is a sporadic fall bonus.

**3. Demand signals (unmeasured, proxies only).** The Bay Area has ~7.7M people. Fish Emeryville runs 7–12 boats on summer days. norcalfishreports carries an active fish-report stream. Check "<landing> fish counts" query volume before launch.

**4. Competition.** The source sites themselves offer raw daily tables and per-boat YTD pages; sportfishingreport's YTD pages show a per-angler figure. There are also FishingBooker (charter reviews) and generic apps (Fishbrain). **Nobody offers normalized leaderboards, per-angler-per-day comparisons across trip lengths, conditions overlays or booking deep links.** That is the same gap we fill in SoCal.

**5. Product fit (3.5/5): the metric needs a regional trophy set.**
- Rockfish dominate the totals (e.g. 240 rockfish + 54 lingcod for 27 anglers). Counting rockfish as "trophy" would swamp the leaderboard.
- Proposed *NorCal trophy set*: **lingcod, king (Chinook) salmon, California halibut, white seabass, bluefin, albacore and yellowtail.** Tuna would be a highlighted "tuna alert", not the main metric.
- Add a **"limit rate"** metric: rockfish per angler ÷ bag limit, with 10 as the current CA RCG limit (verify the yearly regs). Add the same for crab. This is the honest headline for a groundfish fleet.
- Trip filter: many Central Coast trips are 1/2-day (Avenger AM/PM, Patriot). The current rule drops half-days, so decide whether this region keeps them or shows them separately.
- Species parser additions: bocaccio, copper/red/blue rockfish, "rockcod", bolina, Dungeness crab, king salmon, halibut, ocean whitefish, sheephead and lingcod.

**6. Effort & cost (4.5/5).**
- Parser: reuse the generic table parser in `src/scrape.py`. Central Coast is mostly **adding landing URLs**. Bay Area adds a second host (norcalfishreports.com) with the same markup.
- Booking: `src/schedule.py` already parses fishingreservations.net. Verified: `morrobaylanding.fishingreservations.net/sales/`, `emeryville.fishingreservations.net/sales/` and `patriot.fishingreservations.net/sales/`.
- Conditions: add NDBC buoys and NOAA tide stations. Candidates, with IDs to verify: buoys 46053 (E. Santa Barbara), 46011 (Santa Maria), 46042 (Monterey), 46026 (San Francisco) and 46013 (Bodega Bay); tides 9411340 (Santa Barbara), 9412110 (Port San Luis), 9413450 (Monterey) and 9414290 (San Francisco). SST and chlorophyll come from the same satellite products we use already.
- Legal: see the Terms risk in §6.

**7. Strategic fit (4.5/5).** It is contiguous with OC/LA, which already reaches Oxnard and Ventura. California anglers often fish several regions, and the regs, license and app audience are the same. The bluefin push north (Morro Bay and Bay Area bluefin in 2024–2026) is the tuna story for "Tunatracker". This region also completes **"the whole California coast"**, which is a clean pitch for the app and for landing partnerships.

**Risks.**
1. **Terms of use / data rights.** This is the highest risk, and it is shared with the existing regions (§6).
2. **Thin winter data.** Many days have 0–2 reports, so the UI needs "season closed / slow" states.
3. **Weak tuna presence most of the year.** It works as a highlight, not the headline, and the brand has to stretch.
4. **Regulatory volatility.** Salmon closures happened in recent years, and groundfish depth and season rules change. Regs need a yearly config.
5. **Many tiny landings.** There's a long tail of six-packs posting irregularly. Restrict the leaderboard to open-party boats and a minimum-anglers threshold (reuse `src/sixpack_boats.py`).

---

### #2: Pacific Northwest (Westport & Ilwaco WA, Oregon coast)

- **Data (3/5).** These landings sit on the *same network* (the sportfishingreport "Washington Coast" and "Oregon Coast" regions) in the same table format. But only **2–4 boats/day** report (Westport: Predator, Mutineer, Blue Eyes; Ilwaco: Sea Breeze). **Oregon showed no rows** on any sampled day, so Depoe Bay and Newport don't post here. WDFW publishes **weekly** ocean salmon catch-and-effort summaries by port (aggregate, not per trip).
- **Market.** Westport is a big charter port: one WDFW week counted 2,568 anglers. But most boats are 6–20 passenger charters, and per-trip public counts are rare.
- **Fit.** Salmon, bottomfish, halibut and **albacore**, a real tuna fishery (Blue Eyes: 88 albacore for 8 anglers, 2024-09-09). The per-angler-per-day metric works, but the species set needs to change.
- **Effort.** Low for the parser, since it is the same template. The problem is coverage, not parsing. It would need direct partnerships with the Westport Charterboat Association or individual boats to get enough volume.
- **Verdict.** It is a good "phase 4" add-on once Central and NorCal are live. On its own it's too thin to be a region.

### #3: Northern Baja (Ensenada / San Quintín)

- **Data (2/5).** Only Sergio's (Ensenada) posts on the network, about 1 boat on most days (2026-11-22: El Cazador, 7 anglers, 34 yellowtail and 1 yellowfin). Other Ensenada and San Quintín operators post to Facebook or FishingBooker reviews.
- **Fit & strategy (5/5 strategic).** This is the best brand and audience overlap: San Diego anglers drive down, and the catch is yellowtail, tuna and dorado. Our current trophy set works unchanged. Long-range San Diego boats already fish Baja waters, and those trips are in our data.
- **Effort.** The parser is easy, but coverage is the problem. Mexican fishing licenses and regs would need explaining, and Spanish-language sources would be needed for any expansion.
- **Verdict.** Add **Sergio's as a "Baja" landing inside the San Diego region** now, which is nearly free. Don't build it as a standalone market.

**Why not the East Coast, Gulf or Florida?** By fleet size and demand these are the biggest headboat markets in the US. But **no shared structured count platform exists there.** Boats post narrative blogs (e.g. Viking Fleet Montauk: pool winner and weight, no angler counts), Facebook photos or FishingBooker reviews. NOAA's Southeast Region Headboat Survey (~190 vessels) is confidential logbook data. Entering these markets is a **partnership/data-entry business** (landings submitting counts through a Tunatracker form or app), not a scraper. That is a different and much more expensive product motion, and it's worth revisiting once the app has a "submit counts" flow for captains.

---

## 4. Launch plan for #1

### Scrapers / sources

| Sub-area | Source (verified live 2026-11-22 → 24) | Parser |
|---|---|---|
| Santa Barbara | `https://socalfishreports.com/landings/santa_barbara_landing.php` | existing socal landing-page parser |
| Morro Bay | `https://www.sportfishingreport.com/landings/morro-bay-landing.php`, and the socal boats page | same template |
| Avila | `https://www.sportfishingreport.com/landings/patriot-sportfishing.php` (listed on fishcounts.com/central_cal.php) | same |
| Monterey / Santa Cruz | `https://norcalfishreports.com/landings/monterey_bay_charters.php`, plus Chris', J&M and Stagnaro's landing pages | same |
| Bay Area / North Coast | `https://www.norcalfishreports.com/landings/fish_emeryville.php`, landing index at `https://www.norcalfishreports.com/landings/index.php` | same, new host |
| Daily roll-up (optional, 1 request/day) | `https://www.norcalfishreports.com/dock_totals/?date=YYYY-MM-DD`, `https://www.socalfishreports.com/dock_totals/boats.php?date=YYYY-MM-DD` | new small parser |
| Booking deep links | `https://morrobaylanding.fishingreservations.net/sales/`, `https://emeryville.fishingreservations.net/sales/`, `https://patriot.fishingreservations.net/sales/` | existing `schedule.py` fishingreservations parser |

robots.txt on sportfishingreport.com and norcalfishreports.com disallows nothing and sets no crawl-delay. **The Terms are a separate matter and are far stricter** (§6).

### Backfill depth

- **Available:** daily archives to **2010** (sportfishingreport) and at least **2019** (norcalfishreports).
- **Recommended:** backfill **2019 → present** for leaderboards and seasonality charts. That is ~2,500 daily pages for the NorCal roll-up and the same for Central. At 1 request per 3–5 seconds, it takes ~3–4 hours per host, run once, overnight.
- **Do not run the backfill until data rights are settled** (§6). Bulk historical pulls are exactly what the Terms name.

### Timeline (est., one developer)

| Week | Work |
|---|---|
| 0 | **Data-rights outreach** to Sportfishing Report, Inc. / TECK.net: a license, partnership or written OK, covering existing regions too. Ask CDFW MFSU for CPFV regional totals |
| 1 | Central Coast: add landings to the scraper config, extend the species map (rockfish complex, lingcod, salmon, crab, halibut, whitefish), add the `central_nor_cal` region to `regions.js` |
| 2 | Bay Area + North Coast host; six-pack filter; decide whether this region keeps half-day trips |
| 3 | Regional trophy set and the "limit rate" metric in `analytics.js`; tuna-alert badge; conditions (buoys, tides) |
| 4 | Backfill (once cleared), booking deep links, SEO pages per landing, soft launch |
| 5–6 | Polish: winter "slow season" states, regs config, Co-Captain prompt update for NorCal species |

---

## 5. Cross-cutting findings for the owner

1. **fishcounts.com, socalfishreports.com, norcalfishreports.com and sportfishingreport.com are one network** (TECK.net). San Diego, OC/LA and this new region all depend on it. That is a concentration risk, and also an opportunity: one partnership could cover all of California, plus parts of WA and Baja.
2. **976-tuna.com's TLS certificate had expired** when we fetched it on 2026-11-25. The OC/LA backfill scraper (`src/scrape_ocla.py`) uses that site, so the OC/LA launch session should know.
3. **Morro Bay and Avila are already on the socalfishreports `boats.php` page.** If the existing OC/LA path ever reads that page, Central Coast rows may already be arriving untagged. Worth checking during implementation.

## 6. Legal / Terms-of-use note (not legal advice)

The sportfishingreport.com Terms (last updated **2026-09-01**) say:
- **§1.2:** commercial use, redistribution or "automated access" needs prior written authorization or a data/API license.
- **§2.1:** "fish counts" and "current and historical catch information" are listed as protected content.
- **§3.1:** scraping, crawling, bots and building a database from the content are prohibited, and so is getting around rate limits or blocks.
- **§9:** access may be blocked, and legal remedies are reserved. The governing law is Nevada.

The socalfishreports.com and norcalfishreports.com terms pages showed only "Under Construction" placeholders, and fishcounts.com links to no terms page. These sites are part of the same network, so assume the strictest terms apply. The underlying facts (a boat caught N fish) are generally less protected than the presentation, but the Terms are a contract risk regardless. **Recommended action:** approach Sportfishing Report, Inc. for a data license or partnership. Tunatracker sends them traffic and booking intent, so there is a real pitch. Also have a lawyer review the arrangement before scaling to a third region.

---

## Sources

Verified fetches (2026-11-25, cached copies dated 2026-11-22 → 24 unless noted):
- [sportfishingreport.com: Morro Bay Landing](https://www.sportfishingreport.com/landings/morro-bay-landing.php): 6 bluefin, 2026-11-24
- [sportfishingreport.com: Sergio's Sportfishing, Ensenada](https://www.sportfishingreport.com/landings/sergios-sportfishing.php)
- [sportfishingreport.com: landings index](https://www.sportfishingreport.com/landings/) (~171 landings: CA ~97, WA ~26, Baja ~16, OR ~15, FL 8, TX 4)
- [sportfishingreport.com: dock totals](https://www.sportfishingreport.com/dock_totals/), [2026-08-15](https://www.sportfishingreport.com/dock_totals/?date=2026-08-15), [2026-07-04](https://www.sportfishingreport.com/dock_totals/?date=2026-07-04), [2010-07-17](https://www.sportfishingreport.com/dock_totals/?date=2010-07-17)
- [sportfishingreport.com: Terms](https://www.sportfishingreport.com/terms.php), [robots.txt](https://www.sportfishingreport.com/robots.txt)
- [norcalfishreports.com: landings index](https://www.norcalfishreports.com/landings/index.php), [dock totals](https://norcalfishreports.com/dock_totals/), [2026-07-18](https://www.norcalfishreports.com/dock_totals/?date=2026-07-18), [2019-07-20](https://www.norcalfishreports.com/dock_totals/?date=2019-07-20), [Monterey Bay Charters](https://norcalfishreports.com/landings/monterey_bay_charters.php), [Fish Emeryville](https://www.norcalfishreports.com/landings/fish_emeryville.php), [robots.txt](https://www.norcalfishreports.com/robots.txt)
- [socalfishreports.com: boats page](https://www.socalfishreports.com/dock_totals/boats.php), [2026-08-15](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-08-15), [Santa Barbara Landing](https://socalfishreports.com/landings/santa_barbara_landing.php)
- [fishcounts.com](https://www.fishcounts.com/): [Central Cal](https://www.fishcounts.com/central_cal.php), [Bay Area](https://www.fishcounts.com/bay_area.php), [North Coast](https://www.fishcounts.com/north_coast.php)
- [Morro Bay Landing](https://www.morrobaylanding.com/) → [booking](https://morrobaylanding.fishingreservations.net/sales/); [Fish Emeryville](https://www.fishemeryville.com/) → [booking](https://emeryville.fishingreservations.net/sales/); [Patriot Sportfishing](https://www.patriotsportfishing.com/) → [booking](https://patriot.fishingreservations.net/sales/)

Search results and secondary sources:
- [Blue Eyes Sportfishing, Westport](https://sportfishingreport.com/landings/blue-eyes-sportfishing.php), [Sea Breeze Charters, Ilwaco](https://sportfishingreport.com/landings/sea-breeze-charters.php), [WDFW ocean salmon update](https://wdfw.wa.gov/node/105708)
- [Viking Fleet Montauk report archive](https://fishingreports.vikingfleet.com/category/fishing-reports/montauk-fishing-report-2/page/127/)
- [The Fisherman: Jersey Shore party boat primer](https://www.thefisherman.com/article/heads-you-win-jersey-shore-party-boat-primer/), [FishingBooker NJ party boat guide](https://fishingbooker.com/blog/?p=37272)
- [FishingBooker Destin reports](https://fishingbooker.com/reports/destination/us/FL/destin), [Clearwater reports](https://fishingbooker.com/reports/destination/us/FL/clearwater?offset=5)
- [NOAA Southeast Region Headboat Survey](https://www.fisheries.noaa.gov/inport/item/2503), [SRHS overview](https://www.fisheries.noaa.gov/southeast/recreational-fishing/southeast-region-headboat-survey)
- [NOAA For-Hire Survey at a glance](https://www.fisheries.noaa.gov/recreational-fishing-data/hire-survey-glance), [MRIP data downloads](https://fisheries.noaa.gov/recreational-fishing-data/data-downloads)
- [CDFW Marine Fisheries Statistical Unit (CPFV logbooks)](https://wildlife.ca.gov/Conservation/Marine/MFSU), [South Coast CPFV baseline study (CA Sea Grant)](https://caseagrant.ucsd.edu/sites/default/files/SCMPA-29-CPFV-Final-Report.pdf), [North Central Coast CPFV report](https://caseagrant.ucsd.edu/sites/default/files/RMPA-16_Ecotrust_FinalReport3_CPFV.pdf)
- [NorCal Fish Report: Bay Area bluefin crew trip (2026-08-25)](https://www.norcalfishreports.com/fish_reports/242959/crew-trip-today-for-bluefin-tuna.php)

*Not measured: Google search volume, social follower counts, MRIP state-level for-hire effort (the MRIP Query Tool needs interactive use). The size figures are extrapolated from sampled dock-total days.*
