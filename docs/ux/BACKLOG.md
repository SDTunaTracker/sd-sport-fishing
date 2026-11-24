# UX/UI Backlog — thetunatracker.com + Tuna Tracker app

Living, ranked list. Owner: UX/UI agent (branch `claude/ux-polish-469566`).
Pass 1 audit: 2026-11-24, against the shared checkout's local build (redesign in progress) at 1440px and 375px, plus the app's web preview at 390px.

Status key: **todo** · **CR** (change request sent to the session that owns the file) · **branch** (fixed on this branch, not pushed) · **decide** (needs the user) · **done**

Files the redesign session currently has uncommitted (don't edit here until it lands): `app.jsx`, `home.jsx`, `dashboard.jsx`, `drilldown.jsx`, `styles.css`, `index.html`, new `design-system.css`.

## Ranked

| # | Surface | Page | Issue | Fix | Status |
|---|---|---|---|---|---|
| 1 | Web 375 | Today (`dashboard.jsx`) | Boat names truncated to "San D…", "Produ…", "Sea …" in Boats reporting table; landing column dropped. The boat is the most important cell on the page. | On phones render each row as a two-line card (boat + landing on line 1, trip · anglers · TPA on line 2), same pattern the home Counts list already uses. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 2 | Web 375/1440 | Boat page (`drilldown.jsx`) | Trip History "Species mix" column is empty for every row. Looks broken. | Fill it (e.g. "75 Yellowfin · 13 Dorado", as on home) or drop the column. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 3 | Web both | Today | Old visual language: emoji (🔥, blue ⬆ boxes), bright green/blue/yellow rating chips, yellow "Yellowfin" header on cream (fails contrast), bright green "Above Average" panel. Clashes with the calm cream/pine home page. Home says "vs usual +41%"; Today says "Above Avg" chips for the same idea. | Reuse home's "vs usual" ▲/▼ % treatment; species headers in ink; drop emoji; one pine/orange accent. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 4 | Web both | Boats (`boats.jsx`) | All 12 Seaforth boats and all 6 Oceanside boats show an empty green tile (Seaforth ones without even the sailboat icon). The "Hot" badge on those tiles is green text on green, unreadable. Search icon overlaps the placeholder ("🔍earch boats"). | Consistent placeholder (icon + boat initials), badge with solid background, fix input padding-left. Photos are a data task, flag to data agents. | todo |
| 5 | Web both | Footer (`ui.jsx`) | Says "38,600+ trips" while hero says "43,600+"; "all four major landings" but five are tracked; Oceanside missing from Data Sources. | Footer uses the same `META.tripCount` rounding as hero; "every major San Diego landing"; add Oceanside Sea Center. | branch |
| 6 | Web both | Footer | "About" and "Privacy" are grey non-links: look broken. | User chose: write Privacy. Added static `/privacy/` page built from what the code actually collects; footer links to it; dead "About" removed. **User should have it reviewed before relying on it legally.** | branch |
| 7a | Web both | Analytics Overview | "Top Boats — Tuna per Angler per Day" defaults to min 1 trip, so a one-trip boat ("Outer Limits", 7.00) ranks #1. Misleading headline. | Default min trips to 5, matching Season leaders. | todo |
| 7 | Web 375 | Analytics | "Recent Form" lists all ~55 boats (~3,000px of dots). "By trip length" shows 5 Day / 7 Day rows at 0.00. | Show top 10 + "Show all"; hide rows with no trips. | todo |
| 8 | Web both | Today + Home + Analytics | Same "Top boats / Season leaders" list appears on three pages (home rail, Today bottom, Analytics). | User chose: remove from Today, keep Home + Analytics. Sent to redesign session. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 9 | Web 375 | Home (`home.jsx`) | Hero eyebrow wraps to orphan "ANALYTICS"; "Start catching." touches the right edge; "FLEET CATCH RATE · LAST 30 DAYS" wraps to 4 lines; "Full season analytics →" wraps to 4 lines; landing chip row is cut ("Poir") with no scroll hint. | Shorter eyebrow on mobile, clamp() H1 size, single-line label, link on its own row, edge fade on chip scroller. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 10 | Web 1440 | Charts | Map opens zoomed out to Las Vegas/Yuma; the fishing grounds are a small part of the screen. Temp legend overlaps "Las Vegas". | Initial bounds on SD–Ensenada offshore banks. | todo |
| 11 | Web both | Today | Date shown twice (Report for 11/23/26 + Date dropdown); "7-Day Forecast →" is low-contrast on the dark card. | Merge into one date control like home's ‹ Mon, Nov 23 ›; lighten link. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 12 | Web 375 | Boat page | Four stacked actions (Book, Compare, Save, Write review). Month chart axis labels unreadably small. | Book as primary; Save/Compare/Review as one icon row. Larger axis ticks. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 13 | Web both | Trip Planner | "Trip details" toggle missing on some cards; moon label in mixed orange/purple; chat bubble floats over cards; "Cheapest from $150" tab looks disabled. | Consistent card footer; ink moon text; move chat button clear of content. | todo |
| 14 | Web 375 | All | Tap targets under 44px: date ‹ › (30px), landing chips (30px), footer links (20px), home "Book this trip" (30px). | 44px min per design system. | fixed in redesign 2af8e1e1 (not yet on origin) |
| 15 | App | Today | Web preview shows June 21 data (mock?) on Nov 24; dev overlay error "`<button>` cannot contain a nested `<button>`" (real a11y/HTML bug in the report card). | Check data source; un-nest the expand button. | todo (need app folder access) |
| 16 | Web + App | All | Two visual languages: app has pine header + Playfair/JetBrains Mono, site has cream + Fraunces/DM Mono. App counts "tuna counted" (147), site "total fish". | User chose: app switches to Fraunces + DM Mono. Metric names still open. | app fonts on tuna-tracker branch `claude/app-fonts-match-site` (7c2876a, not pushed); metric names open |

## Done
- (none yet)
