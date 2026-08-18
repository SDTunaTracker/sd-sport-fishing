# Site flow & navigation — UX spec

Companion to `site_flow.html` (the visual map). Defines the information architecture, navigation behavior, the core user journeys, cross-linking rules, and per-page flow/states. Goal: a coherent product where every data point is a doorway and the three core journeys are frictionless. Built on the Coastal design system (`homepage_coastal.html`, `DESIGN_SYSTEM_ROLLOUT_HANDOFF.md`).

## Information architecture
- **Primary nav (fixed, every page):** Today · Forecast · Charts · Boats · Analytics · Trip Planner — plus wordmark (→ Today) and Sign In / account.
- **Today (home) is the hub.** It answers the two questions anglers actually have — *"what's biting?"* and *"what should I book?"* — and routes to everything else.
- **Detail pages** (boat, trip, landing) are reachable from many places, not one — treat them as shared destinations.
- **URLs are real, path-based, crawlable, deep-linkable** (per the routing work): `/sd/today`, `/sd/boats`, `/sd/boat/<name>`, `/sd/landing/<name>`, `/sd/tripplanner`, `/sd/charts`, `/sd/forecast`, `/sd/analytics/<subtab>`.

## The three core journeys (optimize these first)
- **A — Check today's bite (daily habit):** Enter → Today → Latest reports (all landings) → tap a boat → Boat detail. *Make tapping any report row land on that boat instantly.*
- **B — Book the best trip (conversion):** Today → "Top trip to book" or Trip Planner → filter (date · species · open spots) → Trip detail (with the boat's performance case) → Book. *The performance "why" must travel with the trip all the way to the booking handoff.*
- **C — Scout a boat (research):** Boats leaderboard / search → Boat detail → history · reviews · upcoming trips → Follow / Book. *Every boat detail must surface its next bookable trip.*

## Navigation behavior
- **Persistent top nav** with an active-state indicator (coral underline) on the current section. Wordmark always returns to Today.
- **Breadcrumbs** on detail pages (e.g., Boats → Pacific Voyager) so users can climb back out.
- **No dead ends:** every list row, name, and stat that *could* lead somewhere is a link (see cross-links).
- **Back/forward** must work (path routing + `popstate`); deep links and refreshes load the right view (SPA fallback).
- **Sign-in is non-blocking:** the whole product is usable logged-out (great for SEO + first visit). Auth unlocks personalization (follows, alerts, saved views), never basic access.

## Cross-linking rules (wire all of these)
| From | To |
|---|---|
| Report row (Today) | Boat detail |
| Leaderboard row (Boats / Season leaders) | Boat detail |
| "Top trip to book" (Today) | Trip detail → Book |
| Charts "catches" pin | Boat detail |
| Boat detail · upcoming trips | Trip detail |
| Landing name (anywhere) | Landing detail |
| Season leader | Boat detail → its next open trip |
| Forecast "good day" | Trip Planner filtered to that day |
| Boat detail | Its landing, its reviews, head-to-head vs another boat |

## Per-page flow & key states

**Today (home)** — hub. Scroll order: hero → Latest reports (all landings) + Season leaders → On the water today (water-temp trend · wind · moon) → Top trip to book → explore cards. Empty/slow-day state: if few/no trips today, show the most recent reports with a quiet "Slow day" note (don't show a blank). Loading: skeletons, not spinners.

**Boats** — leaderboard, sortable (TPA/Day, recent form, species) + filterable (landing, trip length, date range) + searchable by name. Each row → boat detail. Mobile: card reflow or sticky-first-column scroll.

**Trip Planner** — filters first (date, trip length, landing, species, open spots, price), results as trip cards ranked by boat performance, each → trip detail. Persist filter state in the URL (shareable). Empty state: "No open trips match — widen your filters."

**Trip detail** — boat, date, time, price, open spots, and the performance case (fish/angler recent, % outfished, season rank, recent species). Primary CTA = Book (carry context to the booking handoff). Secondary → boat detail.

**Boat detail** — header (photo, name, landing, captain), season performance, recent catches (links to reports), reviews, **upcoming open trips** (→ trip detail). Actions: Follow (auth), Book. Cross-link to head-to-head and its landing.

**Landing detail** — all boats at that landing with their numbers; each → boat detail.

**Charts** — map-first; the dark ocean map is the canvas, light controls float over it. Catches overlay pins → boat detail. Mobile: full-bleed map + bottom-sheet layer panel.

**Forecast** — conditions outlook + backtested score with **visible confidence** (fade far-out days). "Good day" → Trip Planner filtered to that day.

**Analytics** (head-to-head / seasonality / moon) — tabbed; head-to-head reachable from any two boats. Charts in-palette, mono axes.

**Account** — manage followed boats, target species, alert preferences, saved region. Drives the personalization that tailors Today.

## Mobile (test at 390px)
- Nav → hamburger (shared `AppHeader`); wordmark + Sign In persist; tap targets ≥44px.
- Hub stacks: reports → leaders → conditions → top-trip (full-width Book button) → explore.
- Tables → stacked cards or sticky-first-column horizontal scroll; never clip numbers.
- Filter bars → scrollable chip row or a "Filters" sheet.
- Charts map → full-bleed; controls in a bottom sheet.
- Detail pages → single column; sticky primary CTA (Book / Follow) within thumb reach.

## Build notes
- Routing/cross-links rely on the path-based routing + crawlable `<a>` links already in progress (`feat(p1-c,seo)`). Detail routes must be deep-linkable and SSR/prerender-friendly for SEO.
- Reuse shared primitives from `ui.jsx` (header, footer, cards, tables, chips, buttons) so every page inherits the look — see `DESIGN_SYSTEM_ROLLOUT_HANDOFF.md`.
- Keep it usable logged-out; gate only personalization behind Clerk.
- Verify each journey end-to-end on desktop + mobile before deploy.
