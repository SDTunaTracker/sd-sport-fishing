# Tunatracker: Third Market Recommendation

*Research date: 2026-11-25 (rev. 2: owner's boat-choice gate added). Research only: no product code was changed. All sources were read politely, one page at a time, with no accounts or sign-ups. Anything marked **(est.)** is an estimate. Sources are listed at the end.*

---

## TL;DR

**Revised #1: the SF Bay cluster (Emeryville, Berkeley, Sausalito, San Francisco, Half Moon Bay).** It is the only *new* area that passes both must-pass gates by a wide margin:

- **Gate 1, daily public per-trip counts:** ✅ It uses the same fish-report network and the same Boat | Trip | Anglers | Counts table we already parse. The per-boat daily page is `norcalfishreports.com/dock_totals/boats.php?date=`, with an archive back to 2019 or earlier.
- **Gate 2, multiple landings and a real boat choice:** ✅ In the July 12–18, 2026 sample week, **18 landings** posted **133 trips** from **35 boats**, of which **25 were open-party rather than six-packs**, carrying **1,681 anglers**. **16 landings ran Full Day trips on all 7 days.** An Emeryville angler really is choosing among 13 boats at one dock, with 9 more in Berkeley 10 minutes away.

**Update 2026-11-26 (§8):** a September sample week confirms the SF Bay pick: 11 landings, 18 open-party boats, and Full Day trips at 2+ landings on all 7 days. Official CDFW logbooks put the Bay Area at **~75k angler-days a year in normal years** (45k in 2023, a closure year), roughly **$12–21M a year in ticket spend (est.)**. The only partial competitor is norcalfishreports' own Fish-per-Angler Top 10, which leaves out rockfish. Winter is very thin (0–1 boats a day in January), and Morro Bay/Avila **fails** the gate in September.

**Do this quick win first: Santa Barbara Channel.** The cluster with the strongest boat choice of all is **Santa Barbara / Ventura / Oxnard**: 4 landings, 18 boats and 1,623 anglers in the same week, with yellowtail, white seabass and halibut, and 2+ landings running the same trip type **every day**. But 2 of its 4 landings (Channel Islands Sportfishing and Ventura Harbor) are **already in our OC/LA region**, so it isn't really a new market. The two missing landings, **Santa Barbara Landing and Hooks Landing (Oxnard)**, are on the same socalfishreports page we already scrape. Adding them is a few days of work, and it completes the most competitive boat-choice cluster north of San Diego.

**What fails the gate:**
- **Monterey/Santa Cruz:** 3 landings, 5 boats, 206 anglers, and only 1 day of head-to-head overlap.
- **Bodega Bay:** 2 boats.
- **Pacific NW:** 2–4 boats a day, mostly six-packs.
- **Ensenada:** one landing posts.
- **Montauk and Point Judith:** one operator dominates each.
- **Ocean City MD and Destin.**
- **Morro Bay/Avila is borderline:** 3 landings, 7 boats, overlap on only 3 days a week.

**The East Coast passes the boat-choice gate but fails the data gate.** Central NJ (about 25 headboats across 4 ports within 25 minutes) and South Shore Long Island (10 open boats at Captree alone) are true boat-choice markets. But **not one boat we opened posts per-trip angler counts or per-species tallies.** Reports are narrative, with pool winners and Facebook posts, and there's no aggregator. These markets are worth a "captains submit counts" product later. They can't be scraped.

**The biggest risk applies to every region, including the live ones.** sportfishingreport.com's Terms (updated 2026-09-01) forbid scraping and automated access to fish counts without written permission. That covers the same network San Diego and OC/LA use. Get a data license or written OK first (§7). This is not legal advice.

---

## 1. Must-pass gates and scoring method

**Gates (pass/fail, applied before scoring):**
1. **Daily public counts:** landings or boats publish per-trip counts (boat, trip type, anglers, species) publicly, nearly every day in season.
2. **Boat choice:** (a) **2+ distinct landings** competing within a reasonable drive (about 30 minutes), counted as landings, not boats; and (b) enough **open-party boats running the same trip types on overlapping days** that anglers actually compare boats. The working test is that, in a peak week, 2+ landings post the same trip type on most days (5 or more of 7) and there are at least 8 open-party boats. Single-landing towns and one-boat ports fail.

**Scoring (only for markets that pass both gates), 1 = poor to 5 = excellent:**

| Criterion | Weight | What a 5 looks like |
|---|---:|---|
| **Data availability** | **35%** | Daily per-trip HTML counts on a shared platform, multi-year archive |
| Market size | 15% | Many open-party boats, long season, high angler volume |
| Strategic fit | 15% | Adjacent to SoCal, shared audience, tuna present, expansion path |
| Demand signals | 10% | Strong search, forum and social interest |
| Product fit | 10% | Trophy-per-angler-per-day model works with light changes |
| Effort & cost | 10% | Reuses existing parsers and conditions sources, low legal friction |
| Competition | 5% | No good normalized aggregator exists |

## 2. The boat-choice gate, cluster by cluster

### 2a. California clusters: one peak week, July 12–18, 2026 (measured)

Counts come from the per-boat daily pages listed under each source. "Open-party" excludes boats that carried 6 or fewer anglers on every trip that week.

| Cluster | Distinct landings that posted | Boats (open-party) | Trips / week | Anglers / week | Trip types run by 2+ landings | Days with 2+ landings on the same trip type | Gate 2 |
|---|---:|---:|---:|---:|---|---:|:---:|
| **SF Bay** (Emeryville, Berkeley, Sausalito, SF, Half Moon Bay) | **18** | **35 (25)** | 133 | **1,681** | Full Day (32 boats, 16 landings, 123 trips); 1/2 Day AM (4 boats, 2 landings) | **7 / 7** | ✅ **Pass** |
| **Santa Barbara / Ventura / Oxnard** | **4** | **18 (17)** | 82 | **1,623** | 1/2 Day AM (3 landings), 3/4 Day (5 boats, 3 landings), Full Day (8 boats, 2), Overnight (6 boats, 4), 2 Day (3 boats, 3), 1/2 Twilight (2) | **7 / 7** | ✅ **Pass** (half already in OC/LA) |
| Morro Bay / Avila / Port San Luis | 3 (2 towns, ~25 min apart) | 7 (6) | 33 | 686 | 1/2 Day AM (5 boats, 2 landings), 3/4 Day (6 boats, 3), Full/hourly (3 boats, 2) | 3 / 7 | ⚠️ Borderline |
| Monterey / Santa Cruz / Moss Landing | 3 | 5 (4) | 15 | 206 | Full Day (2 boats, 2 landings) | 1 / 7 | ❌ Fail |
| Bodega Bay | 2 | 2 (1) | 6 | 64 | Full Day (2 boats) | 2 / 7 | ❌ Fail |
| *(Other NorCal: Eureka)* | 2 | 2 (0) | 10 | 54 | Full Day (two six-packs) | 2 / 7 | ❌ Fail |

**SF Bay detail.**
- Emeryville (Fish Emeryville) posted 13 boats, among them New Huck Finn, Sea Wolf, C Gull II, Lady K, Pacific Pearl, TigerFish, KingFish and Oakland Anglers II.
- Berkeley posted 9 boats across 5 landings: Happy Hooker, California Dawn / New California Dawn, Pacific Dream, New Easy Rider, Goldeneye 2000, Reel Addiction 1/2 and Round 2.
- Sausalito posted 6: Salty Lady, Hog Heaven, New Rayann, Blue Runner, Outer Limits and Chasin Crustacean.
- San Francisco posted 4: Lovely Martha, Bass-Tub, Argo and Top Gun SF.
- Half Moon Bay posted 3: New Captain Pete, Queen of Hearts and Riptide.
- Ten boats were six-packs.
- Daily trips ranged from 9 to 28, and daily anglers from 136 to 374.
- **Caveat:** NorCal trip labels are almost all "Full Day" whatever the target (rockfish/lingcod, salmon, crab combo, halibut). A fair head-to-head has to infer the target from the catch, for example by grouping trips by their dominant species.

**Santa Barbara Channel detail.**
- Channel Islands Sportfishing posted 9 boats: Aloha Spirit, Cobra, Graylight, Island Fox, Island Tak, Mirage, Speed Twin, Indicator and Gentleman.
- Ventura Harbor posted 4: Island Spirit, Pacific Eagle, Endeavor and Californian.
- Hooks Landing posted 3: Coroloma, Estella and New Hustler.
- Santa Barbara Landing posted 2: Coral Sea and Stardust.
- Catch for the week (approx.): about 270 yellowtail, about 231 white seabass and about 125 halibut. Bonito appeared, but no tuna.
- **Already tracked:** Channel Islands Sportfishing and Ventura Harbor are in `src/scrape.py` / `src/scrape_ocla.py` under `oc_la`. **Not tracked:** Santa Barbara Landing and Hooks Landing, which return no matches in the scraper configs.

### 2b. Other candidates through the gate

| Cluster | Landings / open boats (est. where marked) | Boat choice? | Gate 1 (daily counts) | Gate 2 (boat choice) |
|---|---|---|:---:|:---:|
| **Central NJ** (Atlantic Highlands, Belmar, Brielle, Pt Pleasant, ~25 min span) | 4 ports, **~25–27 headboats** (est., partly from older guides): Big Mohawk, Golden Eagle, Miss Belmar Princess, Ocean Explorer, Jamaica II, Gambler, Queen Mary, Norma-K III, Dauntless and others | Yes: identical 1/2-day AM/PM fluke and sea bass, 3/4-day striper/sea bass, night blues, canyon overnights | ❌ Daily *narrative* posts only (e.g. Golden Eagle, Big Mohawk), with no angler counts or tallies, sometimes a pool winner | ✅ |
| **South Shore Long Island** (Captree, Freeport, Pt Lookout, Sheepshead Bay) | **Captree alone has ~10 open boats** on one dock (Laura Lee, Capt. Gillen, Fishfinder II, Captree Princess, Captree Pride, Island Princess and others); Freeport (Capt. Lou Fleet); Pt Lookout; Sheepshead Bay (est. 3–5) | Yes: side-by-side fluke/sea bass/striper half-days | ❌ One boat (Captree Princess) printed a single fluke count, with no date or angler count | ✅ |
| South NJ (LBI → Cape May, ~1.5 h span) | ~17 boats across 4 separate ports | Within each port only | ❌ Facebook and schedule pages | ⚠️ Partial |
| SE Florida drift boats (Boynton, Ft Lauderdale, Pompano, Jupiter) | Many small hubs (Sea Mist III, Lady K, Catch My Drift, Fishing Headquarters and others) | Yes: same 8am / 1pm / 6:30pm reef drifts | ❌ The only blog found was last updated Dec 2023 | ⚠️ Partial |
| Montauk | 1 harbor; Viking Fleet dominates, plus 2–3 others | Limited | ❌ Viking posts daily narrative | ❌ |
| Point Judith RI | Essentially one operator (Frances Fleet) | No | ❌ | ❌ |
| Ocean City MD | ~3–4 headboats | Limited | ❌ | ❌ |
| Destin / Gulf | 1 harbor per town, a few party boats | Limited | ❌ | ❌ |
| Pacific NW (Westport / Ilwaco) | Several charter offices, but only **2–4 boats/day post**, mostly six-packs; Oregon posted nothing on any sampled day | Weak | ⚠️ Same template, sparse | ❌ |
| Northern Baja (Ensenada) | Only Sergio's posts (~1 boat/day) | No | ⚠️ Sparse | ❌ |
| Cabo / La Paz, Hawaii, Great Lakes | Private charter and panga markets | No | ❌ | ❌ |

## 3. Scored comparison (gate column first)

| # | Market / cluster | Gate 1 | Gate 2 | Data (35) | Size (15) | Strategic (15) | Demand (10) | Fit (10) | Effort (10) | Compet. (5) | **Weighted** |
|---|---|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|
| — | *Santa Barbara Channel (SB / Ventura / Oxnard), extension of OC/LA* | ✅ | ✅ | 5 | 4 | 5 | 3 | 5 | 5 | 4 | *4.60* |
| **1** | **SF Bay cluster** | ✅ | ✅ | 5 | 4 | 3 | 4 | 3 | 4 | 4 | **4.10** |
| 2 | Morro Bay / Avila (add-on to the SB Channel or a Central Coast tab) | ✅ | ⚠️ | 5 | 2 | 4 | 2 | 4 | 5 | 4 | 4.05 (gate borderline) |
| 3 | Central NJ headboats | ❌ | ✅ | 1 | 5 | 1 | 5 | 2 | 1 | 3 | 2.20 (fails data gate) |
| 3= | South Shore Long Island | ❌ | ✅ | 1 | 4 | 1 | 4 | 2 | 1 | 3 | 1.95 (fails data gate) |
| — | Monterey / Santa Cruz | ✅ | ❌ | — | — | — | — | — | — | — | fails gate |
| — | Bodega Bay, Eureka | ✅ | ❌ | — | — | — | — | — | — | — | fails gate |
| — | Pacific NW, Ensenada, Montauk, Pt Judith, Ocean City MD, Destin/Gulf, Cabo, Hawaii, Great Lakes | ❌ / ⚠️ | ❌ | — | — | — | — | — | — | — | fails gate |

*The Santa Barbara Channel is shown in italics because it scores highest but is about half launched already. It's a cheap extension of OC/LA, not a third market. Scores are judgment calls based on the evidence here. Demand wasn't measured with a keyword tool, so those scores are proxies.*

---

## 4. Top 3 briefs

### #1: SF Bay cluster (Emeryville · Berkeley · Sausalito · San Francisco · Half Moon Bay)

**Why it wins.** It is the largest boat-choice market we can actually get data for outside SoCal. There are 18 landings within about 45 minutes of one another, and the two big docks, Emeryville and Berkeley, are 10 minutes apart with 22 boats between them. A Bay Area angler deciding "Huck Finn or Sea Wolf or Happy Hooker this Saturday?" is exactly the leaderboard use case.

1. **Data (5/5).**
   - Per-boat daily page: `norcalfishreports.com/dock_totals/boats.php?date=YYYY-MM-DD`. It was verified for all of 2026-07-12 → 18, with columns boat | landing | city | trip | counts.
   - Landing pages: `norcalfishreports.com/landings/<slug>.php`.
   - Archive: verified on 2019-07-20 (17 landings).
   - Winter is thin: Nov 23 had only one Santa Cruz crab trip, and slow days show "No Counts Provided Today".
2. **Size (est.).**
   - Peak week: 1,681 anglers and 133 trips.
   - Roughly **40k–60k reported angler-trips a year (est.)**, from ~1,200–1,700 anglers a week across ~26 peak weeks, plus a thinner crab/rockfish winter.
   - CDFW CPFV logbooks would give the official figure (ask MFSU, AskMarine@wildlife.ca.gov).
   - For scale, San Diego had 863 anglers on a single sample day in August.
3. **Demand (proxy).** The Bay Area has ~7.7M people. Fish Emeryville runs up to 12 boats a day, and norcalfishreports carries an active report stream.
4. **Competition.** Only the raw source pages exist. Nobody offers normalized leaderboards, head-to-heads, conditions or booking deep links.
5. **Product fit (3/5).**
   - It needs a **regional trophy set:** lingcod, king salmon, California halibut, striped bass, sturgeon, white seabass and tuna.
   - Add a **limit-rate** headline: rockfish per angler ÷ bag limit, and the same for crab.
   - Add **target inference**, because nearly every trip is labelled "Full Day".
   - Add a six-pack filter (`src/sixpack_boats.py`).
   - Tuna shows up as a sporadic bluefin alert (Emeryville had 3 bluefin on 2026-08-15).
6. **Effort (4/5).**
   - One new host, with the same table markup as the existing parsers.
   - Booking: `emeryville.fishingreservations.net/sales/` (verified), parsed by the existing `src/schedule.py`.
   - Conditions: buoys 46026 (SF) and 46012 (Half Moon Bay), and tide station 9414290 (SF). These IDs still need checking.
7. **Strategic (3/5).**
   - Not adjacent to SoCal, and weak tuna branding.
   - But it is the biggest Pacific angler population after LA, it has the same state license and regs framework, and it sets up a "whole California coast" pitch.

**Risks.**
1. Terms of use (§7).
2. Salmon and groundfish regs change every year; the 2023–25 salmon closures are an example.
3. Thin winter.
4. Many one-boat "landings" in Sausalito and SF, so the real choice concentrates in Emeryville and Berkeley.
5. The brand stretch: it's the "Tunatracker" for rockfish and salmon.

### #2: Morro Bay / Avila, as an add-on (not standalone)

- It has 3 landings (Morro Bay Landing, Black Pearl, Patriot) and 7 boats (6 open-party), carrying 686 anglers in the peak week.
- Same-trip overlap happened on only 3 of 7 days, so it's **borderline on its own.**
- Its strength is tuna: Morro Bay's *Endeavor* posted **6 Pacific bluefin on 2026-11-24**, the best tuna story north of Point Conception.
- It's already on the socalfishreports `boats.php` page we read, so the cost is near zero.
- **Recommendation:** add it as a "Central Coast" tab alongside the SB Channel extension rather than as its own region. Booking: `morrobaylanding.fishingreservations.net/sales/` and `patriot.fishingreservations.net/sales/`.

### #3: Central NJ headboats (passes boat choice, fails data)

- This is the strongest true boat-choice market in the country by fleet size: about 25 headboats across Atlantic Highlands, Belmar, Brielle and Point Pleasant, all within about 25 minutes, running the same half-day fluke, 3/4-day sea bass/striper and night trips.
- But it has **no per-trip counts:** boats post narrative daily reports (Golden Eagle, Big Mohawk), pool winners or Facebook posts, and there's no aggregator.
- A product here would need a **"captains submit counts" flow**, perhaps in the companion app, or extracting numbers from narrative text with low reliability.
- Booking runs on FareHarbor (Big Mohawk, Viking) and Peek (Capt. Lou), which is deep-linkable.
- **Verdict:** this is the expansion path *after* the app has a captain-submission feature. It can't be scraped today. South Shore Long Island (Captree's 10-boat dock) is the same story.

---

## 5. Launch plan

### Phase A: Santa Barbara Channel completion (inside OC/LA, ~3–5 days)

- Add **Santa Barbara Landing** (`https://socalfishreports.com/landings/santa_barbara_landing.php`, verified 2026-11-22) and **Hooks Landing (Oxnard)**, which appears under "Oxnard Fish Counts" on `socalfishreports.com/dock_totals/boats.php?date=`.
- Optionally add Morro Bay Landing, Black Pearl and Patriot as a "Central Coast" sub-area from the same `boats.php` page.
- Optionally split a "Santa Barbara Channel" sub-region tab (SB, Ventura, Oxnard) out of OC/LA in `regions.js`.

### Phase B: SF Bay cluster as the third region (~4 weeks, one developer, est.)

| Week | Work |
|---|---|
| 0 | **Data-rights outreach** to Sportfishing Report, Inc. / TECK.net, covering the existing regions too. Ask CDFW MFSU for CPFV totals |
| 1 | Parser for `norcalfishreports.com/dock_totals/boats.php?date=` (one request a day); landing map for the 18 SF Bay landings; species map (rockfish complex, lingcod, king salmon, halibut, striper, sturgeon, Dungeness crab, bluefin) |
| 2 | Six-pack filter, target inference for "Full Day" trips, the `sf_bay` region in `regions.js` |
| 3 | Regional trophy set and limit-rate metric in `analytics.js`; conditions (buoys, tides); booking deep links (fishingreservations.net) |
| 4 | Backfill 2019 → present (once cleared: ~2,500 daily pages at 1 request per 3–5 s, ~3 h, one night); landing SEO pages; soft launch |

**Verified sample URLs (live, Nov 2026):**
- `https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-18`
- `https://www.norcalfishreports.com/dock_totals/?date=2019-07-20`
- `https://www.norcalfishreports.com/landings/fish_emeryville.php`
- `https://www.norcalfishreports.com/landings/index.php`
- `https://emeryville.fishingreservations.net/sales/`

### Later: East Coast via captain submission (not scheduled)

Revisit Central NJ and South Shore Long Island once the app supports captains or landings posting counts directly.

---

## 6. Cross-cutting findings

1. **One network feeds everything.** fishcounts.com, socalfishreports.com, norcalfishreports.com and sportfishingreport.com are sister sites (TECK.net). That is a concentration risk, but also a single partnership target for all of California, plus parts of WA and Baja.
2. **976-tuna.com's TLS certificate had expired** on 2026-11-25. `src/scrape_ocla.py` uses that site, so the OC/LA session should know.
3. **Morro Bay and Avila rows are already on the socalfishreports `boats.php` page.** If any existing scraper reads that page, check that these rows aren't being dropped or mis-tagged.

## 7. Legal / Terms-of-use note (not legal advice)

The sportfishingreport.com Terms (last updated **2026-09-01**) say:
- **§1.2:** "automated access" and commercial reuse need prior written authorization or a data/API license.
- **§2.1:** "fish counts" and "current and historical catch information" are protected content.
- **§3.1:** scraping, bots and building databases from the content are prohibited, and so is getting around rate limits or blocks.
- **§9:** access may be blocked, and legal remedies are reserved. The governing law is Nevada.

The socal and norcal terms pages are "Under Construction" placeholders, and fishcounts.com links to no terms page. Since these are the same network, assume the strictest terms apply. robots.txt disallows nothing, but that does not override the Terms. **Recommended:** approach Sportfishing Report, Inc. for a data license or partnership (Tunatracker sends them traffic and booking intent), and have a lawyer review it before scaling.

---

## 8. Addendum (2026-11-26): open items closed

This addendum closes the gaps flagged in rev. 2: a second sample week, official market size, competitors, and ticket prices. The SF Bay launch decisions (core 5 ports, six-packs excluded, limit-rate metric, `/sfbay`) were made on 2026-11-25 and are not revisited here.

### 8a. Second sample week (Sep 14–20, 2025) and winter days

| Cluster | Week | Landings posted | Boats (open-party) | Trips | Anglers | 2+ landings on the same trip type | Gate 2 |
|---|---|---:|---:|---:|---:|---|:---:|
| **SF Bay core** | Jul 12–18, 2026 | 18 | 35 (25) | 133 | 1,681 | Full Day 7/7 days | ✅ |
| **SF Bay core** | **Sep 14–20, 2025** | **11** | **22 (18)** | **52** | **824** | **Full Day 7/7 days**; 1/2 Day AM 2/7 | ✅ |
| SB / Ventura / Oxnard | Jul 12–18, 2026 | 4 | 18 (17) | 82 | 1,623 | every day | ✅ |
| SB / Ventura / Oxnard | **Sep 14–20, 2025** | 4 | 14 (14) | 43 | 851 | 3/4 Day 4/7, Full Day 2/7, 1/2 AM 1/7 | ⚠️ weaker off-peak |
| Morro Bay / Avila | Jul 12–18, 2026 | 3 | 7 (6) | 33 | 686 | 3/7 | ⚠️ |
| Morro Bay / Avila | **Sep 14–20, 2025** | **2** | 5 (5) | 20 | 324 | at most 2/7 per trip type | ❌ |

**SF Bay targets in September, inferred from the top species on each trip:**
- 41 rockfish/lingcod trips across 9 landings.
- 10 striped bass trips across 4 landings.
- 1 bluefin trip (Scallywag, Fish Emeryville, 9/20).
- No salmon or crab trips.

So the head-to-head that matters most in fall is **rockfish/lingcod limit rate across ~9 landings**. Striper is a real secondary category.

**Winter (Jan 18, 21 and 24, 2026):** the core cluster posted **0–1 boats a day**, and only Fish Emeryville's *Pacific Pearl* ran (crab combo, 180 Dungeness for 18 anglers). The boat-choice decision effectively disappears from about December to March. Plan winter UI states ("off-season: last season's rankings") instead of empty leaderboards.

**Weekday vs weekend:** September weekdays had 2–7 trips a day, against 14–18 on weekends. In shoulder season, boat choice is mostly a **weekend** decision.

### 8b. Official market size: CDFW CPFV logbooks

From CDFW's *Annual Report of Statewide Fish Landings by the CPFV Fleet*, by port. "Fishers" may include crew, so treat these as angler-days, not unique anglers.

| Port area (CDFW grouping) | 2018 | 2019 | 2023 | 2023 reporting CPFVs |
|---|---:|---:|---:|---:|
| San Francisco / SF Bay–Delta | 54,621 | 54,909 | 40,420 | 92 |
| Princeton (HMB) – Bodega Bay | 23,281 | 19,546 | 4,785 | 18 |
| **Bay Area subtotal** | **77,902** | **74,455** | **45,205** | 110 |
| Monterey – Moss Landing – Santa Cruz | 18,602 | 20,025 | 14,687 | 22 |
| Avila Beach – Morro Bay | 28,176 | 26,005 | 20,759 | 11 |
| Port Hueneme – Oxnard – Ventura – Santa Barbara | 62,737 | 53,967 | 39,884 | 37 |
| LA (San Pedro / Long Beach + Redondo / MdR) | 123,226 | 111,058 | 86,348 | 85 |
| Newport Beach | 48,784 | 43,258 | 40,162 | 35 |
| Oceanside – Dana Harbor | 55,107 | 46,727 | 34,449 | 35 |
| San Diego – Mission Bay | 94,551 | 87,164 | 109,850 | 140 |
| **Statewide** | 521,952 | 475,874 | 401,337 | 515 |

What the table shows:
- In a normal year (2018–19), the Bay Area is **the third-largest CPFV market in California**, behind LA and San Diego, with roughly 75k angler-days.
- The 2023 dip (45k) matches the 2023 salmon closure and the August 2023 groundfish restrictions. It shows how sensitive the region is to regulations.
- The SB Channel runs 40–63k a year. Morro Bay/Avila runs 21–28k a year but comes from only 11 CPFVs.
- No 2024 or 2025 port report was found, so ask CDFW MFSU for newer data.

**Ticket spend (est.):**
- Bay Area open-party tickets cost about **$250–$290** for rockfish or crab combos and **$330–$400** for salmon. Emeryville crab combo: $275 cash. Happy Hooker crab/rockcod: $250. HMB salmon: $330.
- All-in per angler-day is about **$290–$420** with a one-day license ($21.09), tackle and rental.
- 45k–78k angler-days × ~$275 ≈ **$12–21M a year** in Bay Area party-boat ticket spend (est.). That is the booking-intent pool our deep links point into.

### 8c. Competitors in the SF Bay

| Competitor | What it offers | Pricing | Gap we fill |
|---|---|---|---|
| **norcalfishreports.com** (closest) | Daily per-boat scores; per-boat pages with a Book Now link; a **"Top 10 Charter Boats" YTD table with Fish per Angler**, limited to albacore, halibut, crab, king salmon, lingcod, Pacific halibut and striper. **Rockfish is not offered**, and the table was nearly empty when fetched | Free, ad/sponsor supported | No rockfish ranking (the bulk of Bay CPFV catch), no limit rate, no ranking across landings by target, no trends or conditions |
| sportfishingreport.com (same company) | Landing pages with daily counts and annual species totals (e.g. Fish Emeryville rockfish 57,305 in 2026 vs 83,891 in 2025) | Free | No per-angler stats or rankings |
| Fish Emeryville site | Counts embedded from NCFR; booking | Free | One landing only |
| FishingBooker | 28 Berkeley rockfish listings at $225–$1,770, with reviews; mostly private or six-pack boats | Captains pay 10–30% commission | No catch data; few true open-party boats |
| Captain Experiences | Private-charter marketplace (Sausalito trips from $500 to $4,400) | Fees not disclosed | Doesn't serve walk-on party-boat buyers |
| Fishbrain | Crowd-logged catches (17,100 SF catches); Pro adds stats and forecasts | Pro ~$9.99/mo or $74.99/yr (2026 price unverified) | Shore and private anglers; nothing on CPFVs or boat choice |
| BD Outdoors NorCal forum, Fish Sniffer | Narrative trip reports, mostly private boats | Free (Fish Sniffer membership price not visible) | Anecdotal, no ranking |
| SF Chronicle outdoors | No current weekly count column found | Paywalled | — |
| Reddit / Facebook groups | Not verifiable (Reddit refused automated fetches) | — | — |

**The gap:** nobody ranks Bay Area open-party boats by **limit rate across all targets, including rockfish and crab combos**, with conditions and booking deep links. Pricing headroom: the only paid consumer tool nearby (Fishbrain Pro, ~$75/yr) isn't party-boat specific. A free, ad- or affiliate-supported model like NCFR's is the norm. Subscription pricing is unproven for this audience.

### 8d. What's next after SF Bay (fourth-market view)

1. **The SB Channel completion** (Santa Barbara Landing + Hooks Landing) is still the cheapest boat-choice win. It is strong in summer and weaker in September.
2. **Morro Bay/Avila** stays an optional tab, not a region, because it fails the gate in September with 2 landings.
3. **East Coast (Central NJ, South Shore LI)** waits for a "captains submit counts" flow. Nothing scrapeable exists there.

---

## Sources

**Boat-choice measurement (peak week 2026-07-12 → 18, all HTTP 200):**
- NorCal per-boat pages: [07-12](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-12), [07-13](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-13), [07-14](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-14), [07-15](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-15), [07-16](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-16), [07-17](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-17), [07-18](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-07-18)
- SoCal / Central Coast per-boat pages: [07-12](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-07-12), [07-13](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-07-13), [07-14](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-07-14), [07-15](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-07-15), [07-16](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-07-16), [07-17](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-07-17), [07-18](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-07-18)

**California data sources (cached copies dated 2026-11-22 → 24 unless noted):**
- [sportfishingreport.com: Morro Bay Landing](https://www.sportfishingreport.com/landings/morro-bay-landing.php) (6 bluefin, 2026-11-24); [Sergio's, Ensenada](https://www.sportfishingreport.com/landings/sergios-sportfishing.php); [landings index](https://www.sportfishingreport.com/landings/)
- sportfishingreport.com dock totals: [current](https://www.sportfishingreport.com/dock_totals/), [2026-08-15](https://www.sportfishingreport.com/dock_totals/?date=2026-08-15), [2026-07-04](https://www.sportfishingreport.com/dock_totals/?date=2026-07-04), [2010-07-17](https://www.sportfishingreport.com/dock_totals/?date=2010-07-17); [Terms](https://www.sportfishingreport.com/terms.php); [robots.txt](https://www.sportfishingreport.com/robots.txt)
- norcalfishreports.com: [landings index](https://www.norcalfishreports.com/landings/index.php), [dock totals](https://norcalfishreports.com/dock_totals/), [2026-07-18](https://www.norcalfishreports.com/dock_totals/?date=2026-07-18), [2019-07-20](https://www.norcalfishreports.com/dock_totals/?date=2019-07-20), [Monterey Bay Charters](https://norcalfishreports.com/landings/monterey_bay_charters.php), [Fish Emeryville](https://www.norcalfishreports.com/landings/fish_emeryville.php), [robots.txt](https://www.norcalfishreports.com/robots.txt)
- socalfishreports.com: [boats page](https://www.socalfishreports.com/dock_totals/boats.php), [2026-08-15](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-08-15), [Santa Barbara Landing](https://socalfishreports.com/landings/santa_barbara_landing.php)
- fishcounts.com: [home](https://www.fishcounts.com/), [Central Cal](https://www.fishcounts.com/central_cal.php), [Bay Area](https://www.fishcounts.com/bay_area.php), [North Coast](https://www.fishcounts.com/north_coast.php)
- Booking: [Morro Bay Landing](https://www.morrobaylanding.com/) → [fishingreservations](https://morrobaylanding.fishingreservations.net/sales/); [Fish Emeryville](https://www.fishemeryville.com/) → [fishingreservations](https://emeryville.fishingreservations.net/sales/); [Patriot](https://www.patriotsportfishing.com/) → [fishingreservations](https://patriot.fishingreservations.net/sales/)
- [NorCal Fish Report: Bay Area bluefin crew trip (2026-08-25)](https://www.norcalfishreports.com/fish_reports/242959/crew-trip-today-for-bluefin-tuna.php)

**East Coast (opened 2026-11-25 unless marked as search or older guide):**
- [The Fisherman: Jersey Shore party boat primer](https://www.thefisherman.com/article/heads-you-win-jersey-shore-party-boat-primer/), [Belmar port page](https://www.thefisherman.com/port/belmar/), [2019 party boat guide](https://www.thefisherman.com/article/2019-party-boat-guide/)
- [Golden Eagle reports](https://www.goldeneaglefishing.com/fishingreports), [Big Mohawk 2026-11-22](https://bigmohawk.com/november-22-2026/), [Miss Barnegat Light reports](https://www.missbarnegatlight.com/daily-fishing-reports)
- [Viking Fleet reports](https://fishingreports.vikingfleet.com/2026/11/25/tue-nov-24-night-squid/), [Viking boats](https://vikingfleet.com/about-our-boats/)
- [Captree Fleet](https://www.captreefleet.com/), [NY State Parks: Captree fishing](https://parks.ny.gov/parks/captree/fishing.aspx), [Captree Princess reports](https://www.captreeprincess.com/fishing-reports), [Capt. Lou Fleet](https://www.captloufleet.com/), [NY Sea Grant party/charter directory (undated)](https://www.seagrant.sunysb.edu/nysportfishing/pubs/PartyAndCharterBoatDirectory.pdf)
- [Frances Fleet](https://www.francesfleet.com/), [Morning Star (OC MD)](https://www.morningstarfishing.com/fishing-report)
- [Boynton Inlet drift boats (2014)](https://thecoastalstar.com/profiles/blogs/on-the-water-boynton-inlet-drift-boats), [Fishing Headquarters drift reports](https://www.fishheadquarters.com/blog/category/drift-fishing-reports/)

**Addendum sources (2026-11-26):**
- NorCal per-boat pages, Sep 14–20, 2025: [09-14](https://www.norcalfishreports.com/dock_totals/boats.php?date=2025-09-14) … [09-20](https://www.norcalfishreports.com/dock_totals/boats.php?date=2025-09-20); winter: [2026-01-18](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-01-18), [01-21](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-01-21), [01-24](https://www.norcalfishreports.com/dock_totals/boats.php?date=2026-01-24)
- SoCal per-boat pages, Sep 14–20, 2025: [09-14](https://www.socalfishreports.com/dock_totals/boats.php?date=2025-09-14) … [09-20](https://www.socalfishreports.com/dock_totals/boats.php?date=2025-09-20)
- CDFW CPFV landings by port: [2023](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=218591), [2019](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=178003), [2018](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=171088); statewide [2022](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=211365), [2020–21](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=197136); [2024 By the Numbers](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=229396&inline); [2023 By the Numbers](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=220034&inline)
- Competitors: [NCFR year-to-date](https://www.norcalfishreports.com/year-to-date.php), [NCFR New Huck Finn](https://www.norcalfishreports.com/charter_boats/newhuckfinn.php), [NCFR about](https://www.norcalfishreports.com/about.php), [SFR Fish Emeryville](https://sportfishingreport.com/landings/fish-emeryville.php), [FishingBooker Berkeley rockfish](https://fishingbooker.com/fish/rockfish/us/CA/berkeley), [FishingBooker commission](https://fishingbooker.com/blog/choosing-commission/), [Captain Experiences Sausalito](https://captainexperiences.com/locations/california/sausalito), [Fishbrain SF](https://fishbrain.com/fishing-waters/3tlEBiQL/sf), [Fishbrain Pro](https://fishbrain.helpshift.com/hc/en/3-fishbrain---social-fishing-forecast-app/faq/230-what-is-included-in-fishbrain-pro), [BD NorCal forum](https://www.bdoutdoors.com/forums/forum/northern-california-fishing-reports/), [Fish Sniffer report](https://fishsniffer.com/report/benmechling/sf-bay-crab-and-rockfish-action-remains-strong-12-14-2025)
- Ticket prices: [Emeryville sales](https://emeryville.fishingreservations.net/sales/), [Happy Hooker sales](https://happyhooker.fishingreservations.net/sales/), [Fish Reapers HMB](https://fishreaperssportfishing.schedulista.com/), [Riptide HMB](https://fishingbooker.com/charters/view/1228), [Fish Emeryville extras](https://www.fishemeryville.com/)

**Other:**
- [Blue Eyes Sportfishing, Westport](https://sportfishingreport.com/landings/blue-eyes-sportfishing.php), [Sea Breeze, Ilwaco](https://sportfishingreport.com/landings/sea-breeze-charters.php), [WDFW ocean salmon update](https://wdfw.wa.gov/node/105708)
- [NOAA Southeast Region Headboat Survey](https://www.fisheries.noaa.gov/inport/item/2503), [SAFMC headboat report](https://safmc.net/documents/fc1_a6a_sa-headboats-report_202506-pdf), [NOAA For-Hire Survey](https://www.fisheries.noaa.gov/recreational-fishing-data/hire-survey-glance)
- [CDFW MFSU (CPFV logbooks)](https://wildlife.ca.gov/Conservation/Marine/MFSU), [South Coast CPFV baseline (CA Sea Grant)](https://caseagrant.ucsd.edu/sites/default/files/SCMPA-29-CPFV-Final-Report.pdf), [North Central Coast CPFV report](https://caseagrant.ucsd.edu/sites/default/files/RMPA-16_Ecotrust_FinalReport3_CPFV.pdf)
- [FishingBooker Destin reports](https://fishingbooker.com/reports/destination/us/FL/destin)

*Not measured: Google search volume, social follower counts, MRIP state-level for-hire effort (CDFW CPFV logbook totals were added in §8b). East Coast fleet lists are partly from older guides and should be treated as estimates. Facebook-hosted reports could not be read. The California boat-choice numbers come from a single peak week. A second sample week (e.g. September) would firm them up.*
