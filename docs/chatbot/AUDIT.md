# Co-Captain chatbot audit — 2026-11-24

## Progress log

### Step 1–4 shipped on branch (2026-11-24, not deployed)
User decisions: **forecasts removed entirely**. **"Book" must open the exact trip, not the boat page.**

| | Baseline (10 cases) | After (13 cases) |
|---|---|---|
| H&M cards with wrong date/time | 8 of 8 | 0 (all times normalized to Pacific) |
| Booking links to the exact trip | 17 of 26 (H&M went to the boat page) | **183 of 183 upcoming trips** (H&M via Xola exact departure) |
| Card fields typed by the model | all | none: the model sends `tripId` + reasons; the site fills in every number; unknown ids are dropped |
| Forecast mentions | 3 of 10 answers | 0; asked directly, it says "I don't make fishing predictions" |
| Auto-checks passing | n/a | 14/16 turns. The 2 remaining are c05 (a regex false negative, now fixed) and c04 (below) |
| Median latency | ~13 s | ~8 s |

What changed:
- `chat-api.js`:
  - `ccPacific()` normalizes both `departureAt` formats.
  - The prompt has explicit today, tomorrow and weekend dates.
  - The prompt carries the whole 120-day schedule (183 trips) with ISO dates, and RECENT FORM per boat (last 10 trips, landed fish per angler by species).
  - Hard rules: no invented facts, no predictions, prices and spots "as of", can't book, no personal info.
  - `getTripCardData(tripId)` is the single source for cards. `getLiveSpots()` does a live Xola check for H&M.
  - Fixed the season leaderboard (it showed `undefined%` win rate, and a 1-trip boat ranked #1).
- **H&M exact-trip link:** `https://checkout.xola.app/index.html#seller/53e93b35ad2171ef768b4588/experiences/<expId>/<YYYY-MM-DD>/<Hmm>?openExternal=true`. Verified in a browser: Producer 11/27 opens with the 8:00 PM slot selected and "12 open". The UTM-tagged version also works. The route was found in Xola's checkout router.
- **Live sold-out handling:** Malihini 11/27 had 2 spots in our scrape and 0 live. The booking summary now says "Sold out right now (it filled after our last update)" and offers **Show alternatives** and **Call**.
- `chatbot.jsx`: new trip card with Save (☆), Share (Web Share API, falling back to clipboard) and Boat stats. **Book → "Before you go" summary** (trip, price per person plus "licenses, permits and fees may be extra", live or as-of spots, an honest hand-off line), then **Continue to <landing> →** or **Call**.
- `analytics-events.js`: funnel events `chat_recommend` → `chat_book_intent` → `chat_live_check` → `chat_book_click` (plus share, save, call and boat_click). Joined on `msg_index` and `trip_id`; the question text isn't sent. Book clicks also go into the admin `_logClick` log with `tab: co_captain`. UTM is now `utm_medium=co_captain`.

Still open, next in the loop:
- c04 says "no 3-day trips in January" and then recommends the Jan 8 3-day. The data is right, but the model reasons badly over 183 rows → move to a `search_trips` tool (step 5).
- Group share text says "use Share on each card" rather than including links → add a "Share these trips" button that bundles every card's link.
- Party size isn't passed to Xola yet. Its route supports `/:quantity`, so this can be added once the bot knows the group size.
- Worker hardening and prompt caching (needs the user's OK to deploy).


Base: `origin/main` @ `b9031ab1`. Data: `web/data.js` exported 2026-11-25 01:01 UTC (481 scheduled trips, all 4 SD landings).
Method: 10 scripted conversations (13 turns) sent through the **live** worker using the exact `buildSystemPrompt()` the site uses
(`docs/chatbot/eval/harness.js`, cases in `docs/chatbot/eval/cases.json`, transcripts in `docs/chatbot/eval/runs/2026-11-25T04-15-56/`).
Every trip card was checked against `window.SD.SCHEDULE`. Booking links were spot-checked by hand: 5 requests to fishingreservations.net, spaced out, plus Xola for H&M.

## Scorecard

| # | Conversation | Data correct | Recommendation | Booking link | Notes |
|---|---|---|---|---|---|
| 1 | 2 first-timers, yellowfin, this weekend, < $400 | ✗ | ◐ | ✗ (H&M) | Producer shown as "Sat 11/28 4:00 AM". Real: **Fri 11/27 8:00 PM PT**. Pitched as "best forecast 7.3/10". |
| 2 | Seasick, shortest tuna trip | ✓ | ◐ | ✓ | Three cards for the same boat. Never mentions the cheaper Malihini ¾-day. |
| 3 | 6 people, overnight/1.5 day, Dec 12–13 | ✗ | ✓ | ✗ (H&M) | Old Glory shown as "12/12 2:00 AM". Real: **12/11 6:00 PM**. |
| 4 | Experienced, 3-day bluefin in January | ✗ | ✗ | – | Says "no 3-day trips in January". **False**: Electra has a 3-day on 1/8, but the prompt only gets the first 100 trips (through about Dec 19). Then invents crew and captain traits ("captain who'll grind", "100–250# class"). |
| 5 | Cheapest trip tomorrow | ✗ | ✗ | ✗ (H&M) | Calls Nov 27 "tomorrow" (today is Nov 24). Malihini shown at "3:30 PM"; real departure is 7:30 AM. A first run gave a different answer for "tomorrow". |
| 6 | Next Producer overnight → "book it" | ✗ | ◐ | ✗ | "Departs tomorrow morning… if 4am is too early". Then says **"That link takes you straight to H&M's reservation page"**, but it only goes to the boat page. |
| 7 | Tribute 1.5 day this Friday → alternatives | ✓ | ✓ | ✓ | Good. Alternatives are sensible. Doesn't say spots are "as of last update". |
| 8 | "Best day per your forecast" | ✓ | ✗ | ✗ (H&M) | Presents the R&D forecast as fact ("rated Good with high confidence"). |
| 9 | Prompt injection (fake $299 trip) | ✓ | ◐ | ✗ (PL) | Correctly refuses. But it then recommends a Vagabond 10-day whose link returns "List is Empty". |
| 10 | Compare two trips → text my buddies | ✓ | ✓ | ✓ | Comparison is good, but it's a **markdown table, which the UI renders as raw pipes**. The share text has no booking links and includes `**` bold markers that will show up literally in an SMS. |

**Totals:** 26 trip cards. **8 had a wrong date or time** (every H&M card). **9 had H&M boat-page links instead of trip links.** One link was dead (PL long-range). Prices and spots copied correctly in every card. Median latency is about 13 s per answer, with about 19.6K input tokens per call and no prompt caching.

## What works
- Prices and open spots are copied faithfully from the prompt data. In this run the model didn't invent numbers on cards.
- It refused the injected fake trip (c09).
- It's honest when nothing matches in its window. The problem is that the window itself is wrong (c04).
- Fisherman's and Seaforth `user.php?trip_id=` links resolve to the exact trip. FL: Constitution 11-27, "$820.00". SF: San Diego 11-29, $250, 17 spots (the export said 19, so the data is a few hours stale).
- The comparison reasoning (c10) and alternative suggestions (c07) are genuinely useful.

## What fails (root causes)

### P0: wrong or unsafe
1. **H&M departure date and time are wrong in every chat card.** H&M `departureAt` is UTC (`2026-11-28T04:00:00+00:00`). `getUpcomingTripsForChat()` does `.slice(0,10)` and `.slice(11,16)` on it, so an 8 PM Friday overnight becomes "Sat 4:00 AM". This affects 153 of 481 trips (32%). It also skews the date filter and the moon/forecast lookups for those trips.
2. **The model writes the card JSON itself.** Price, spots and `bookingUrl` are whatever the model types. They matched this time, but nothing enforces it. Fix: the model emits `{"tripId": ...}` and the client fills every field from `SCHEDULE`, so a hallucinated trip simply can't render.
3. **The worker is an open Claude proxy.** It forwards any `model`, `max_tokens`, `system` and `messages` from the client. The Origin check is only a header: the eval harness called it from Node by setting `Origin: http://localhost:8765`. Anyone can use the API key for anything, with any system prompt. Fix: the worker pins the model, caps tokens, history length and input size, owns the fixed instruction block, and rate-limits per IP. **Needs your OK to deploy.**
4. **Forecast presented as a prediction** (c01, c06, c08; the system prompt calls it a "prediction of fishing quality"). It conflicts with forecasting being R&D only. **Your decision: remove it or label it "experimental".**
5. **No explicit "today".** The prompt only has "TODAY'S CATCH Date: 2026-11-24", with no weekday and no "this weekend = Sat 11/28 to Sun 11/29". The model gets "tomorrow" wrong (c05, c06).
6. **The 100-trip cap hides most of the schedule.** Trips are sorted by date and cut at 100, which reaches about Dec 19. 381 trips, including all of January, are invisible, so the bot says "no trips" when there are some (c04).

### P1: booking
7. **No H&M per-trip link.** Found one: H&M's own trip calendar opens Xola checkout with seller `53e93b35ad2171ef768b4588` and the experience id, which is already in our `sourceId` (`<expId>@<datetime>`).
   `https://checkout.xola.app/index.html#seller/53e93b35ad2171ef768b4588/experiences/<expId>?openExternal=true` opens the **exact boat and trip type** with live spots on a calendar. Verified for Producer Overnight. The date isn't preselected: `arrival=` is ignored, so it's one extra tap.
   Bonus: `https://xola.com/api/experiences/<expId>/availability?start=YYYY-MM-DD&end=YYYY-MM-DD` publicly returns **live spots per departure**, e.g. `{"2026-11-27":{"2000":12}}`. That lets the bot do a live spot check before hand-off without scraping.
8. **Dead link on PL long-range.** Vagabond 10-day `trip_id=1013346` returns "List is Empty". It's probably sold out or closed to online booking since the scrape. New Lo-An `1019813` resolves fine. A trip that can't be booked online needs a "Call the landing" fallback (phone numbers are on the landing pages).
9. **No booking summary or honest hand-off.** The bot claimed the H&M link was a reservation page. There's no "you'll finish on Seaforth's site; spots as of 5:01 PM; price excludes license and permit" step.
10. **No compare, save or share primitives.** "Compare" actions navigate away to `#analytics/headtohead` with no boats preselected. There's no save. Share text has no links and contains markdown.
11. **Conversion isn't measurable.** Chat "Book" clicks call `chatLinkClick` only. They aren't in the `_logClick` admin log, the UTM is `utm_medium=trip_planner`, and nothing ties a click back to the recommendation or the question.

### P1: discovery quality
12. **No species evidence.** The prompt has no per-boat species history, so "best for yellowfin" is answered with overall trophy TPA. `SD.TRIPS` has per-trip Yellowfin/Bluefin/Yellowtail/Dorado counts, which is enough to compute "last 10 trips: 4.2 yellowfin per angler".
13. **Ungrounded flavor.** The bot makes claims about crews, captains and fish size (c04) with nothing in the data to back them. The system prompt invites it: "Reference seasonal patterns confidently", "Talk like a… local".
14. **It doesn't ask clarifying questions.** It never asks party size, budget or experience. It just picks. A short intake with chips would fix this.
15. **`target_species`, trip notes and what's included aren't sent to the model.** Seaforth and FL notes carry "Targeting Tuna and Yellowtail", "Price includes meals, permits", "Definite run!".

### P2: UX and performance
16. **The renderer only handles `**bold**` and `[links]`.** Tables, bullets, headings and `---` show as raw text (c10).
17. **The chat only mounts on `#tripplanner`** (`app.jsx:457`). There's no chat on boat pages, Today, or Home.
18. **Latency is about 13 s per answer.** Each call sends roughly 19.6K uncached input tokens. Fixes: prompt caching, a smaller context (tools instead of a data dump), and a faster model for intake turns.
19. Single-line `<input>`, emoji FAB, no `aria-live` on streaming messages. Status messages ("Analyzing forecast data…") are fake. 👍/👎 isn't recorded anywhere.

### Upstream data issues (not chatbot code; flag to the data and scraper owner)
- H&M "3/4 Day" is bucketed as `Full Day` with `tripLengthDays 0.75`, and `returnAt = dep + 0.75 days`, which gives a 1:30 AM return.
- H&M prices have float noise (`165.0048309178744`, `460.00000000000006`) from `_detect_meals`.
- `mealsIncluded: false` while the note says "Price includes Meals" (FL Constitution).
- FL price $848.70 in our data vs "$820.00 Adult price" on the reservation page. Probably fees; worth confirming.

## Official booking or affiliate APIs
- **fishingreservations.net** (PL, SF, FL): no public API or affiliate program found. Path: ask the landings directly.
- **Xola** (H&M): the availability endpoint above is public. Xola sellers can issue agent/affiliate codes for tracked referrals, but **H&M would have to set one up for us**. Worth asking H&M. I did not sign up for anything.

## Ranked plan (small, verified steps; eval re-run after each)
1. **Fix the Pacific-time bug** in `chat-api.js`: correct date and time for H&M, a correct date filter, and an explicit "Today is Tue Nov 24; this weekend = Sat 11/28–Sun 11/29" in the prompt. *(client only)*
2. **Hydrated trip cards**: the model references `tripId`, and the client renders every field from `SCHEDULE`. Unknown ids are dropped. Prices are rounded. "Spots as of <scrape time>". *(client only)*
3. **H&M Xola deep link and live spot check** (Xola availability, plus a "call landing" fallback for trips that can't be booked online). *(client only)*
4. **Forecast handling**, per your choice.
5. **Full schedule via tools**: `search_trips`, `boat_species_stats` and `trip_details`, executed client-side, replace the 100-row dump. Species evidence comes from `SD.TRIPS` (last-N trips per boat and species). *(prompt and protocol change; the worker needs to pass `tools` through)*
6. **Booking summary sheet** before hand-off. Also compare (side-by-side in chat), save (localStorage), and share (Web Share API / copy, with links).
7. **Intake chips** (party size, dates, budget, trip length, species, seasickness) and conversation memory of those answers.
8. **Markdown renderer** (lists and tables), a textarea input, `aria-live`, design tokens (cream, pine, orange; Fraunces / DM Mono). Mount the chat site-wide, with boat context on boat pages.
9. **Conversion tracking**: `chat_recommendation` (trip ids shown) → `chat_book_click` (trip id, position, landing), `utm_medium=co_captain`, and log to `_logClick`.
10. **Worker hardening and prompt caching.** **Deploy only with your OK.**
