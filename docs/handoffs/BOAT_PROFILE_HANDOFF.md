# Boat profile page — enrichment brief

Visual reference: `boat_profile_mockup.html` (Coastal style; `NEW` badges mark additions). Build onto `web/drilldown.jsx` (`BoatDetail`). **Keep what's already there** — restyle it to the design system and add the missing high-value pieces. This page is where journeys A (check today's bite) and C (scout a boat) end, so it should show your moat at full depth.

## Already in `drilldown.jsx` (keep — just restyle to Coastal)
- Hero with boat photo + captains + rating tags + review badge.
- KPIs: Tuna/Angler, Total Fish.
- "Catch Rate Through the Year" (monthly, boat vs landing avg) · "By Species" (catch/angler) · trip stat rows.
- Tabs: **Trip History** (full past-trips table) · **Reviews** (`ReviewsSection`) · **Reddit Reports**.
- Head-to-head button.
→ Re-skin these with the shared primitives (`Panel`, table, chips, StatTile, buttons) per `DESIGN_SYSTEM_ROLLOUT_HANDOFF.md`.

## Add these (the gaps)

1. **Live status pill — "Out now · returns ~3:30pm" / "In port"** `[NEW, signature feature]`. You already have the AIS vessel-tracker worker (`VESSEL_WORKER_URL`, `data/boat-mmsi.json`) — wire it in. Boat→MMSI→live AIS position/speed → infer out/returning/in-port. Nobody else surfaces this; make it prominent in the hero. Gracefully hide if no MMSI/position.
2. **Specs strip in the hero** `[NEW]` — length, passenger capacity, year built, trip types, rating — you already store `lengthFt`, `passengerCapacity`, `yearBuilt`, `captains` in `boat_profiles`; just render them.
3. **Season rank badge — "#3 of 62 this season"** `[NEW]` — you compute the leaderboard already; show the boat's position.
4. **Richer stat row** `[partly new]` — TPA/Day (+rank), **fish/angler last 10 trips**, **% it outfished comparable boats**, total fish landed (season). The last two are new metrics — add to `analytics.js` (the % outfished reuses the comparable-trip logic behind ratings).
5. **Upcoming trips with open spots + Book** `[NEW — conversion]` — pull this boat's upcoming trips from `SD.SCHEDULE`; show date, time, trip length, price, spots left, and a coral **Book →** per trip, plus a "Book next trip" CTA in the hero. Links into the Trip Planner / booking handoff.
6. **Follow button** `[NEW]` — in the hero; ties to the account/alerts work (`ACCOUNT_SETTINGS_HANDOFF.md`). Logged-out → the free-account prompt.
7. **Species specialty callout** `[NEW, derived]` — "Bluefin specialist — 58% of its catch is bluefin, above the fleet; best on 1.5-day trips." Derive from the species mix + by-trip-length data you already have.
8. **Photo gallery** `[NEW, optional]` — support multiple images if/when available (single `photoUrl` today).
9. **Per-page SEO** `[NEW]` — boat profiles are prime search entry points: per-boat `<title>`/meta/OG and JSON-LD (Product/Service + AggregateRating from reviews). Pairs with the crawlable path routing.

## Layout (match the mockup)
Breadcrumb (Boats › Name) → **hero** (photo bg, name, landing+captains, specs chips, live-status + rank badges, Book + Follow) → **4 stat tiles** → **Upcoming trips** → **Performance** (monthly form vs landing | species mix + specialty) → **Tabs** (Trip history · Reviews · Reddit).

## Mobile (test 390px)
- Hero stacks: badges → name → specs (wrap) → actions row (Book + Follow full-width).
- Stat tiles → 2×2. Performance panels → single column. Trip-history table → stacked cards or sticky-first-column scroll (don't clip the catch line).
- Keep **Book** reachable (sticky bottom CTA on mobile is fine).

## Guardrails
- Reuse shared primitives; don't fork styles. Use real data (`SD` + AIS worker + analytics); add new metrics to `analytics.js`, don't hand-edit `data.js`.
- Live status must fail gracefully (no MMSI / stale position → hide the pill, don't show a broken state).
- Accessibility: real links, alt text on the photo, heading order, AA contrast. Small commits; verify desktop + mobile; keep the compiled build green.
