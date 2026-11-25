# Brand Strategy: thetunatracker.com and the companion app

Status: Phase 1 draft for the owner's review (2026-11-24). Nothing here is decided. The owner makes all brand and name calls.

---

## 1. The one-line brand

**The scoreboard for SoCal sportboats.** Every boat, every landing, every day, normalized so you can tell which trip actually fishes best, then book it.

---

## 2. Who it's for

| Segment | Who they are | What they need from us | How often they show up |
|---|---|---|---|
| **First-timers and families** | Booking a first half-day or full-day, maybe a gift trip | "Which boat should I pick, and is it worth it?" Plain words, no jargon, a clear Book button. Co-Captain does the hand-holding | A few times a season |
| **Weekend regulars** | Fish 4 to 15 overnight or 1.5-day trips a year | Who's on the fish this week, which boats over-deliver per angler, when to book | Several times a week in season |
| **Long-range regulars** | 3 to 16-day trips, big spend, deep knowledge | Trip-length-fair comparisons, history by boat and month, credibility | Daily in season, planning in winter |
| **Crew, captains, landing staff** (secondary) | They read the leaderboards too | Fair, accurate numbers; being shown well | Weekly |

What they share: they already read fish counts every morning. They don't need to be told what a yellowtail is. They distrust hype, because every landing and report says the fishing is "wide open". What they lack is a **fair comparison**: raw counts reward big boats and long trips.

---

## 3. Where we sit against the alternatives

| Alternative | What it does well | Where it leaves a gap |
|---|---|---|
| **fishcounts.com and landing sites** (H&M, Fisherman's, Seaforth, Point Loma) | The source of truth, published daily | One landing at a time, raw counts, no comparison, no history you can query |
| **SportfishingReport / sandiegofishreports / 976-TUNA** | Daily roundups and written reports, long-standing | Lists, not analysis. Hard to compare boats or trip lengths |
| **BloodyDecks** | The community: trip reports, photos, tribal knowledge | Forum format. Signal is buried in threads |
| **FishTrack, Fishdope** | Ocean conditions, SST and chlorophyll charts, paid dope | Built for private boaters; sportboat comparison is not the core |
| **Fish City (iOS app)** | The closest direct competitor: California fish counts by boat and landing, NOAA conditions, alerts | Counts, not normalized per-angler-per-day performance. iPhone only. No booking assistant |

**Our position:** the only place that turns every SoCal landing's daily counts into a *fair* boat leaderboard (trophy fish per angler per day), puts it next to conditions and history, and then helps you book the trip through Co-Captain.

**Positioning statement.** For SoCal anglers choosing a sportboat trip, The Tuna Tracker is the fish-count analytics site that shows which boats actually catch the most per angler, across every landing, so you can book with confidence instead of guessing. Unlike landing sites and report roundups, it compares every boat fairly across trip lengths.

---

## 4. Value proposition

- **Headline promise:** Stop guessing. Start catching. (Keep it. It's short, it's the right promise, and it's already on the homepage and meta description.)
- **Proof points, in order:**
  1. Every boat from every tracked landing, updated every morning.
  2. Fair rankings: trophy fish per angler per day, so a full-day can beat a 3-day.
  3. History: how a boat fishes by month, moon and trip length.
  4. Help booking: Co-Captain finds and links you to the trip.
- **What we never promise:** forecasts as fact. The forecast work is R&D. Brand copy must never say "predict", "guaranteed" or "know where the fish will be". Allowed: "see how boats have fished", "conditions right now", "trends".

---

## 5. Brand pillars

| Pillar | Means | Shows up as | Never |
|---|---|---|---|
| **Straight numbers** (data you can trust) | Sourced, dated, explained. Show the method | Source and "updated 6:30 AM" stamps, metric tooltips, released fish excluded and said so | Inflated claims, "#1" claims we can't back, unlabeled estimates |
| **Dock-level local** | Built by people who stand at the rail. Knows the landings, boats and slang | Boat and landing names front and center, SoCal photography, seasonal language | Generic "fishing app" clip-art, freshwater imagery |
| **Quiet premium** | Feels like a well-made logbook or a good chart table, not a tackle-shop flyer | Cream paper, pine ink, one orange, serif headlines, generous space, mono numbers | Glossy gradients, clip-art fish, stock-photo grins, ALL-CAPS shouting |

---

## 6. Voice and tone

**Voice (constant):** a sharp deckhand who also keeps a spreadsheet. Direct, dry, a little salty, never cute. Talks in numbers and boats.

| We are | We aren't |
|---|---|
| Plain and specific: "(boat name): 2.4 trophies per angler per day" | Vague hype: "Epic bite going off!!" |
| Confident about data, honest about limits | Certain about the future |
| Insider vocabulary when it helps (rail, paddy, full-day, 1.5-day) and explained for first-timers | Jargon walls |
| Short sentences, sentence case | Title Case Marketing Headlines |

**Tone shifts by moment:**

| Moment | Tone | Example |
|---|---|---|
| Hero / marketing | Punchy, confident | "Stop guessing. Start catching." |
| Leaderboard / data | Neutral, exact | "Ranked by trophy fish per angler per day. Half-days excluded." |
| Empty or error states | Dry and helpful | "No counts posted yet. Landings usually report by 7 PM." |
| Co-Captain | Warm, practical, first person | "Two boats fit a Saturday overnight under $400. Want the one that's fished better this month?" |
| Forecast / R&D | Careful | "Experimental. Based on past seasons; not a prediction." |

**Rewrites of current copy:**

| Current | Suggested | Why |
|---|---|---|
| ★ San Diego's #1 Sportfishing Analytics | San Diego sportboat counts, ranked fairly | "#1" is an unprovable claim and the star reads cheap |
| Trusted by data from {N} trips | Built from {N} trips across every landing | "Trusted by data" is awkward; lead with the number |
| TRACK. ANALYZE. COMPARE. CATCH MORE. (logo tagline) | Drop it from the mark | Four verbs is a list, not a tagline |

---

## 7. Audit of the current brand expression

| Element | What's there now | Verdict | Recommendation |
|---|---|---|---|
| **Name** | "The Tuna Tracker", domain thetunatracker.com (registered 2026-05-21) | Memorable, alliterative, ownable in the niche. Narrow: tuna-only, and "tracker" suggests GPS/fish-finding. "The" makes app-store and handles awkward | See NAMING.md. Shortest good path: keep the equity, drop "The" in the product name |
| **Logo** (`web/logo.png`) | AI-style illustrated circular badge: leaping tuna, sportboat, skyline, palm trees, distressed block caps, navy/yellow | Doesn't match the cream/pine/orange system; unreadable under 64px; too much detail; navy palette is from the old site; looks like a T-shirt print, not a premium product | Replace with a simple wordmark plus a monogram/symbol (mockups in `docs/brand/mockups/`). Keep the badge style only for merch if wanted |
| **Header wordmark** (`web/ui.jsx`) | "The Tuna Tracker" in Fraunces 600, 17px, text only | Good base. No symbol, so no recognisable mark at small sizes | Add the symbol at left; tighten tracking |
| **Favicon** (`web/favicon.ico`) | Derived from the badge | Turns to mush at 16px | Simple monogram on pine |
| **App icon / PWA** (`manifest.webmanifest`) | Uses logo.png; `theme_color #0ea5e9` (sky blue) and `background_color #0f172a` (slate) | **Off-brand leftovers** from the Pacific Slate era; the browser chrome on Android shows sky blue | Set theme/background to pine/cream; ship proper 192/512 maskable PNGs |
| **`<meta name="theme-color">`** in `index.html` | `#0ea5e9` | Same leftover | `#17332C` |
| **OG / Twitter image** | The badge logo (square) | Square image gets cropped badly in link previews; no message | 1200×630 template: headline, today's number, wordmark |
| **Palette** (`web/design-system.css`) | Cream `#FBFAF6`, pine `#17332C`, orange `#CF6A3C`, sea `#2F7F86`, good/warn/bad, species colors | Strong, distinctive in a sea of navy-and-blue fishing brands. Keep | Formalize as brand tokens (see guide); orange reserved for actions |
| **Type** | Fraunces (headings), Inter (UI), DM Mono (labels/numbers) | Good combination; Fraunces gives the "logbook" premium feel | Keep. Use DM Mono for every number in tables. App is already moving to Fraunces + DM Mono |
| **Photography** | Boat photos hot-linked/downloaded from landing sites (`web/images/boats/`, 63 files); hero `hero-sunrise.jpg` | **Licensing risk.** Not ours to use; inconsistent quality and crops | See guide: ask landings/boats for written permission, commission or license a small set, use typographic placeholders otherwise |
| **Copy** | "Stop guessing. Start catching." strong; some "#1" claims and generic phrases | Mostly good | Voice rules above |
| **Name in app** | Companion app (`tuna-tracker` repo) | Needs an app-store name that fits ~30 chars and searches well | e.g. "Tuna Tracker: SoCal Fish Counts" |

**Biggest issues, in order:** (1) the logo doesn't belong to the new design system and fails at small sizes; (2) leftover sky-blue theme colors in the manifest and meta tags; (3) unlicensed boat photography; (4) a name narrower than the product.

---

## 8. What success looks like

- Someone who's seen the site once recognises the icon on their home screen and in a link preview.
- The site, the app and a shared link preview look like one product.
- Copy never over-promises; numbers always carry a source and a date.
- Any rename decision is made with SEO input and a written migration plan, not on vibes.
