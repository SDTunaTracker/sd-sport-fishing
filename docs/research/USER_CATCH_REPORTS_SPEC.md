# User-submitted catch reports: product spec (proposal, not built)

*Status: proposal for the owner, 2026-11-25. Nothing here is built. Source: DATA_SOURCES.md row 14.*

## 1. Why

The landing counts tell us **how many** fish a boat caught. They don't say how big the fish were, what worked, what the trip felt like, or how *I* did as opposed to the boat. Anglers who just got off a boat know all of that. A short report from them, tied to the exact trip row we already have, gives us:

- **Size grade per trip** ("YFT 25–40, one 70"), which no source we scrape has consistently.
- **Per-angler outcome** ("I got 3 of the boat's 76"), for a fairer "what can I expect" view.
- **First-party photos and reviews** for boat pages. Today `boat_reviews` has 1 row, and Google reviews (once built) can't be stored or summarised.
- **Owned data:** the one source no landing, forum or platform can switch off. It also helps any data-licence talk with the TECK network.

It doesn't help the forecast directly (too sparse at first), but size grade and bait type are hypotheses H2 in DATA_SOURCES §5.

**Honest value read:** high long-term, low short-term. Volume will be small. Expect about 1–3% of active users after a trip, so maybe 20–60 reports a month in season at today's traffic. The design has to work with sparse data, and must never display a "4.9 from 2 reports" as if it were authoritative.

## 2. Scope (v1)

In: open-party trips we already track (the `trips` table), for SD first, then OC/LA and SF Bay. Out: private charters, six-packs, kayak and shore reports, and real-time "they're biting now" posts (spot-burning, safety and accuracy problems).

## 3. The form

Entry points:
1. Boat page → "Fished this boat? Add your catch".
2. A trip row in Trip History → "I was on this trip".
3. Post-trip email or push (later, if the user saved the trip in the Trip Planner).

Steps (mobile first, about 60 seconds, reusing the existing 3-step review modal pattern in `web/boat-reviews.jsx`):

| Step | Fields | Notes |
|---|---|---|
| 1. Which trip | Boat (prefilled), return date (prefilled when started from a trip row), trip length | We match to a `trips` row (§5). If no match, we keep it as "unmatched" and don't show it publicly until a count appears. |
| 2. Your catch | Per species: fish **you** landed (number), biggest fish (lb, optional), typical size (picker: under 15 / 15–25 / 25–40 / 40–60 / 60–100 / 100+ lb) | Only our 7 tracked species, plus "other". Released fish go in a separate optional field and never count toward totals (same rule as the counts). |
| 3. What worked (optional chips) | Bait (sardine / anchovy / squid / mackerel / none), technique (fly-line, sinker, kite, yo-yo, surface iron, trolling), line test, and a 1–5 star "would rebook?" | Chips, not free text, so it's structured and safe. |
| 4. Optional | Up to 3 photos, a ≤500-character note, and a display-name choice: "first name + initial" or "anonymous angler" | Photos go to Cloudinary (existing unsigned preset), with EXIF stripped (§7). |

Validation: per-angler numbers capped at plausible limits (e.g. bluefin ≤ 2/day under current regs, yellowfin ≤ 10/day in Mexico, × trip days). Biggest fish within species ranges (dorado ≤ 70 lb, YFT ≤ 400 lb). Any value over the cap gets the report flagged, not rejected.

## 4. Moderation

1. **Automatic gate** (Worker, at submit):
   - schema and caps
   - profanity and URL filter on the note
   - rate limit: 3 reports a day per account, and 5 an hour per IP, as in today's review-ingest
   - duplicate check (same account + trip)
2. **Plausibility vs. the count:** the angler's own fish must be ≤ the boat's landed count for that species on the matched trip. Over-count → auto-flag.
3. **AI pre-screen** (Claude, the same pattern as BD extraction): the note is checked for personal attacks on named crew, other people's personal info, spot GPS numbers (we strip coordinates), commercial spam, and claims that contradict the numbers. Output: `ok` / `review` / `reject` plus a reason.
4. **Human queue:**
   - `review` items and every report with photos go to the owner dashboard (`/owner`, already behind Cloudflare Access) with one-click approve or reject.
   - Target: under 48 h.
   - Text-only `ok` reports from accounts older than 7 days auto-publish. New accounts' first 2 reports always go to the queue.
5. **Takedowns:** "Report this" on every public report. Boats and landings can request a correction through a contact form; we respond within 5 days. Reports are never edited by us, only hidden.

## 5. Tie to trip rows

- Match on `boat` + `return date ±1 day` + `trip_length` against `trips` (our counts are dated by return day, see the trip-dates memory).
- Store `trip_id` when exactly one row matches. If two match (a boat doing two trips in a day), ask the user to pick.
- **Unmatched** reports stay private for 3 days, then rematch nightly (counts can post late). After 14 days with no match, they're shown only as an unverified "angler note" on the boat page, never in stats.
- Every public report carries a **"Matches landing count ✓"** badge when matched, the same idea as the BD reports' landing-count join.

## 6. How it shows

**Boat page → Reviews tab**, a new "Angler catch reports" block. It sits above Google and BD, since it's first-party, matched data. Coordinate the exact order with the BloodyDecks agent, which owns the forum panel, and the website UX agent.

- **Summary** (only when there are ≥5 matched reports in the last 365 days):
  - typical size per species, as a median band
  - "anglers caught a median of 3 of the boat's YFT" (per-angler share)
  - bait and technique chips by frequency
  - "Would rebook" %, shown alongside its report count
- **List:** report cards with trip date, trip length, matched badge, per-species numbers, size, chips, photos and note, plus display name or "Anonymous angler".
- **Trip History row:** a small camera or 💬 icon when a matched report exists, which opens the card.
- **Co-Captain:** may use aggregated size bands and "what worked" chips ("anglers on recent PQ 3-days reported 25–40 lb YFT on sardine"), never individual notes or names. Co-Captain's no-prediction rule stands.
- **Never** shown: precise times, GPS, or the user's email or account id.

## 7. Privacy and safety

- **Accounts:** require sign-in (Clerk, already in the app) to submit; that's the main abuse control. Reading stays public.
- **Stored:** account id (internal), the report, a photo URL, and a hashed IP for 30 days (rate limiting). No email in the report record.
- **EXIF:** strip GPS and device data from photos before upload (client side, by canvas re-encode) and again server side via Cloudinary's `strip` flag. Spot-burning and personal-location risk.
- **Faces:** a note in the form asks users to only post photos where people agreed. Faces aren't blurred automatically in v1, and removal takes one click from the queue.
- **Deletion:** users can delete their reports at any time (account page). Account deletion removes all reports and photos within 30 days.
- **Licence:** at submit, the user grants Tunatracker a non-exclusive licence to display the report and photos and use them in aggregates. They keep ownership. This needs a short Terms addition and a privacy-policy update, written by the owner or a lawyer.
- **Minors:** 13+ to create an account (COPPA). Photos of kids are allowed only from the parent's account (a form note).

## 8. Data model (when built)

```sql
CREATE TABLE angler_reports (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, boat TEXT NOT NULL, landing TEXT,
  return_date TEXT NOT NULL, trip_length TEXT, trip_id INTEGER,        -- NULL until matched
  catch_json TEXT NOT NULL,      -- {"yellowfin":{"kept":3,"released":0,"max_lb":42,"band":"25-40"},...}
  bait TEXT, technique TEXT, line_lb INTEGER, rebook INTEGER,
  note TEXT, photos_json TEXT, display_name TEXT,
  status TEXT NOT NULL,          -- pending | published | hidden | rejected
  flags TEXT, created_at TEXT NOT NULL, published_at TEXT
);
```

Storage: Cloudflare D1, the same Worker family as analytics and owner dashboard ingest. The daily export pulls published, matched reports into `web/api/v1/angler_reports.json` per boat.

## 9. Build plan and effort (for when the owner says go)

| Phase | What | Effort |
|---|---|---|
| 0 | Terms and privacy text (owner/lawyer); confirm Clerk sign-in is live | Owner |
| 1 | Worker `angler-reports` (D1, validation, rate limits, AI pre-screen), owner-dashboard queue | 3–4 days |
| 2 | Form (reusing the review modal), trip matching, nightly rematch, export JSON | 3 days |
| 3 | Boat-page block, Trip History icon, summary rules | 2 days |
| 4 | Co-Captain aggregate context, post-trip prompt for saved trips | 1–2 days |

**Success measure after one season:** ≥200 matched reports, ≥30% of top-20 boats with a ≥5-report summary, and <2% of published reports later hidden.

## 10. Risks

- **Too few reports to matter:** mitigate with the post-trip prompt and the "I was on this trip" button on every Trip History row.
- **Boats gaming it:** sign-in, the count-plausibility check, the new-account queue, and visible report counts make this costly.
- **Defamation or crew complaints:** chips over free text, a 500-character limit, the AI screen, and takedown handling.
- **Spot-burning:** no GPS, EXIF stripped, no real-time posting.
