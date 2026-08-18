# The Tuna Tracker — Product & UX Roadmap (Claude Code handoff)

Goal: the most impressive, user-friendly, clean, professional site for San Diego sportfishing — fish-count analytics, trip booking, boat info & reviews, advanced weather/ocean charts, and a predictive offshore fishing forecast.

Paste this into Claude Code from the repo root. **Explore the codebase first** (it's React 18 + Babel-in-browser, no build step; Python scrape/analytics/forecast backend → `tracker.db` → `web/data.js`; deployed via Cloudflare Pages). Produce a phase plan before coding. Small reviewable commits. After each phase, verify in a real browser (`scripts\serve.ps1`) — this codebase's failures only show at render time.

---

## Competitive positioning (do NOT copy them — beat them on a different axis)

| Site | Their moat | Their weakness |
|---|---|---|
| **FishDope** ($199/yr) | Crowd-sourced + spotter-plane "hot bite" GPS map; VHF reports; hyper-local SoCal | Dated, text-heavy 2000s design; no boat analytics; paywalled |
| **FishTrack** (premium) | Global cloud-free SST / chlorophyll / current satellite charts; waypoints, offline | A charts utility; no catch data, no boats, no booking |

**The Tuna Tracker's wedge:** neither competitor answers *"which boat is actually catching, and which trip should I book?"* You own **catch-count analytics + boat performance + booking**, with a modern UI. Lead with that. Match them on conditions/forecast where it's cheap to, but don't try to out-satellite FishTrack. Win on **analytics, trust, design, and a forecast that gives an actual answer (a score) instead of raw charts to interpret.**

Positioning line to design around: *"Stop guessing. The data on every San Diego sportboat — who's catching, where it's heading, and the best trip to book."*

---

## Current state (build on what exists, fix what's shaky)

Already built and live: daily fish counts, boat leaderboards (trophy-per-angler-per-day), 11-year trends, charts (Leaflet + SST/chlorophyll), a trip planner, boat reviews, a forecast engine with backtesting, metric tooltips, color-coded ratings, skeleton loaders, expanded footer. The product is far more complete than it looks from outside.

Known issues to resolve before/while adding features:
- **Performance/build:** the compiled (esbuild) build cuts the ~8s Babel-in-browser load, but it currently breaks because separately-compiled files collide on top-level `const` and rely on implicit globals. Fix: build with `--format=iife` **and** ensure every cross-file helper used by another file is assigned to `window` (e.g. `settings.jsx`'s `loadSettings`/`saveSettings`, `account.jsx`'s `MyAccountView`). Verify by loading every view locally before deploying. Keep the Cloudflare build command and `.github/workflows/deploy-pages.yml` esbuild step in sync.
- **Routing/SEO:** path-based routing + crawlable `<a>` links + `404.html` SPA fallback are written (commit `feat(p1-c,seo)`); verify under whichever build ships.
- **Data health:** `tracker.db` read as "malformed" once — run `PRAGMA integrity_check`.

---

## UX/UI — make it feel premium (Phase 1, highest ROI)

The design is already clean; these push it to "best in class":

1. **Design system pass.** Lock design tokens (3–4 type sizes, spacing scale, radii, motion) and a shared component set: Button, Card, Pill/Badge, Tooltip, Tabs, Modal, Skeleton, Toast, EmptyState, StatTile. Compose everything from these so the whole site feels consistent.
2. **Make data scannable.** Every table sortable + filterable; add inline sparklines/mini-bars per boat row; semantic color for ratings (already started). A first-time visitor should understand every metric without a manual (extend the existing `MetricLabel` tooltips everywhere).
3. **Microinteractions & states.** Row hover, smooth nav transitions, active-nav indicator, button press/focus states, `prefers-reduced-motion`. Real empty/loading/error states on every async view (skeletons, not spinners).
4. **Mobile-first.** Most anglers check from a phone at the dock — tables reflow to cards or sticky-first-column scroll, nav collapses cleanly, tap targets ≥44px. Test at 390px.
5. **Accessibility (WCAG AA).** Keyboard nav, focus rings, AA contrast, aria labels on icon buttons, semantic headings/tables.
6. **Trust & polish.** "Data last updated" timestamps, a clear methodology page (how trophy-per-angler-per-day is computed — this is your credibility vs FishDope's vibes), on-brand 404/500, favicon set, fast cold load (the build fix).

---

## Feature roadmap by pillar

### 1. Fish-count analytics (your core moat — go deeper than anyone)
- Boat leaderboards with filters (species, trip length, landing, date range) and head-to-head compare.
- Multi-year trend charts; species breakdown beyond bluefin; "hot streak" detection (boats trending up).
- Deep-linkable, shareable views (filter state in the URL — pairs with the routing work) + CSV/image export.
- A "Best boat for my trip" finder: pick target species + trip length + date → ranked boats by historical performance for those parameters. **This is the booking-analytics bridge no competitor has.**

### 2. Trip booking (convert analytics into action)
- Trip Planner: filter upcoming open-spot trips by date, length, landing, boat, species, price; sort by historical performance.
- Clean trip detail pages (boat, itinerary, included, price, reviews, recent counts, departure-window forecast).
- Booking flow with a **PCI-compliant provider (Stripe/Braintree hosted checkout)** — never handle raw card data. Decide build-vs-integrate with existing landing booking systems (many SD landings already use one). Handle seat holds, confirmation email + calendar invite.

### 3. Boat info & reviews (depth = trust + SEO)
- Complete boat profile pages: specs, capacity, captain, gallery, historical performance (link to analytics), upcoming availability (link to booking). **Finish the photo coverage — see `BOAT_PHOTOS_HANDOFF.md`.**
- Verified reviews (verified-booking badge), structured prompts (crew, value, would-rebook), photos, owner responses, Review JSON-LD for star snippets in search.

### 4. Advanced weather & ocean charts (match FishTrack/FishDope cheaply)
- Layered marine map (already on Leaflet): SST, chlorophyll/water color, currents, wind, swell height/period, pressure, tides, moon. Toggleable layers + time scrubber + saved favorite spots.
- Source from licensed/attributable data (NOAA/NWS, NDBC buoys, CoastWatch/ERDDAP for SST & chl). Lazy-load the map module so it doesn't slow other pages.
- **Differentiator:** overlay your catch data on conditions (e.g., counts vs SST breaks) — FishTrack shows conditions, you show conditions *plus outcomes*.

### 5. Offshore fishing forecast ("the answer, not just charts")
- You already have a forecast engine + backtesting. Make it the headline: a daily 1–10 score (and per-species) with map "zones," a confidence indicator, and a plain-language *why* ("warm break + chlorophyll edge near the 9-mile bank, strong recent counts").
- Show methodology + backtested accuracy openly — this is how you earn trust vs FishDope's unfalsifiable "dope." Start transparent/heuristic, iterate toward ML; never ship a black box.
- Keep the "world's first offshore fishing forecast" claim substantiable (or soften it) and always pair it with the accuracy/methodology view.

### 6. Growth & retention (where FishDope monetizes — do it better)
- Free accounts (Clerk is already wired): saved boats/spots, watchlists, booking history, forecast alerts (email/push) when conditions align for a target species/area.
- Freemium vs FishDope's $199 wall: generous free analytics + counts; premium for forecast detail, alerts, advanced charts. Being the *modern, partially-free* option is a wedge against a dated paywall.
- Installable PWA for dock use; a content/SEO engine (per-boat, per-species, per-landing pages + reports) for long-tail search — your crawlable-routing work unlocks this.

---

## Suggested build order
1. **Phase 1 — Foundations:** fix the compiled build (iife + window exports), confirm routing, design-system + a11y + mobile pass, performance budget. *(Unlocks speed, SEO, and a consistent UI — biggest perceived-quality jump.)*
2. **Phase 2 — Analytics depth:** filters, trends, "best boat for my trip" finder, shareable views. *(Your moat.)*
3. **Phase 3 — Boats & reviews:** finish photos, full profiles, verified reviews + JSON-LD.
4. **Phase 4 — Booking:** trip discovery + secure checkout.
5. **Phase 5 — Charts:** layered conditions map + catch-overlay differentiator.
6. **Phase 6 — Forecast:** explainable score, zones, accuracy view.
7. **Phase 7 — Accounts, alerts, PWA, content/SEO.**

## Guardrails
- Match existing stack/patterns; don't introduce a new framework or CSS system.
- Never handle raw payment card data, credentials, or PII — use the provider's hosted components and existing Clerk auth.
- Only use licensed/attributable third-party data (charts, imagery); record sources.
- `web/data.js`, `web/sitemap.xml`, `tracker.db` are generated/binary — don't hand-edit; regenerate via the export step.
- Verify every change in a real browser before deploy; small commits; pause for review at each phase boundary.
