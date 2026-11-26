# SEO backlog — thetunatracker.com

Ranked by expected organic impact ÷ effort. Evidence for each item is in [AUDIT.md](AUDIT.md).
Status: `todo` · `doing` · `done (branch)` · `shipped` (on main and live) · `user` (needs the user) · `coord` (needs another agent).

## P0: indexing blockers

| # | Item | Status | Notes |
|---|---|---|---|
| S1 | Prerendered pages: keep the static content **visible when the app fails to load** (Googlebot's 2 MB cap truncates data.js), and drop `aria-hidden` | shipped | Inline check after `data.js` hides `#root` and shows `#seo-static` when `window.SD` is missing. No change for normal visitors |
| S2 | `seo.js` stops overwriting prerendered `<title>`, description, canonical, og and JSON-LD on first load | shipped | `<html data-prerendered>` marker; SPA navigation still updates meta |
| S3 | Canonical, `og:url` and sitemap use the served URL (trailing slash) | shipped | Removes "Page with redirect" for ~130 URLs |
| S4 | Sitemap built from the *same* list as the generated pages, with real `lastmod` (last trip date) | shipped | |
| S5 | `www.thetunatracker.com` returned 522 (about 9% of requests, the whole 5xx rate). 301 Redirect Rule to the apex | done (user) | shipped 2026-11-25: Redirect Rule 301s `www.*` to the apex, path and query kept |
| S6 | Prerender static HTML for `/sd/today` and `/sd/boats`: last 3 report days by landing (every species landed), boat directory | done (claude/seo-2) | `web/sd/today.html` / `boats.html`; CF serves `x.html` at `/x` and `_redirects` wins over static files, so those two rewrites are gone |
| S6b | Prerender `/` (home) | todo | `index.html` is hand-edited source, so this needs a generated copy or markers the pipeline fills; coordinate with UX |
| S7 | Search Console + Bing setup; sitemap submit; URL Inspection "View tested page" on `/sd/today` + one boat page to confirm S1/S6 | **user** | See AUDIT §4 |

## P1: programmatic page quality (biggest traffic lever)

| # | Item | Status | Notes |
|---|---|---|---|
| S8 | Boat template: last-trip date, last 10 trips table, trip-length mix, best months, BreadcrumbList | shipped | Answers "<boat> fish report" |
| S9 | Boat/landing/species: `BreadcrumbList` JSON-LD; replace address-less `LocalBusiness` with `Dataset`/`WebPage` | shipped for breadcrumbs + landing/species; boat keeps LocalBusiness only when ≥3 reviews | |
| S10 | Landing fleet table: min 5 trips to rank, plus "last 7 days at <landing>" trips table | shipped | Fixes 1-trip boats ranked #1 |
| S11 | `noindex` boat pages with <5 trips; exclude them from the sitemap | shipped | 13 boats |
| S12 | Boat landing = landing of the most recent trip | shipped | 27 boats moved landings |
| S13 | Species pages: "last 14 days" block (boats and counts) | done (claude/seo-2) | Species queries now SD-only, which also removed links to OC/LA boats with no page |
| S14 | Sibling links on boat pages (other boats at the landing) | done (claude/seo-2) | Up to 12, 5+ trips, most recent first |
| S29 | Generated pages had no Google Analytics tag or web fonts (only `index.html` has them) | done (claude/seo-2) | Visits landing on boat/landing/species pages weren't counted |
| S30 | Species pages: the SPA has no species view and redirected visitors to `/sd/today` | done (claude/seo-2) | Species and trip pages are now static only, with a plain site nav. Styling: ask UX |
| S31 | App landing view shows the slug ("hm-landing") as its heading on `/sd/landing/<slug>/` | coord (app-dev) | Visitors see the app, not the static page there |
| S32 | Trip-length pages: primary CTA "Find the best {length} trip" → `/sd/pick` (yellowtail species page: `/sd/pick?q=yellowtail`) | todo (blocked) | Waits for `/sd/pick` (claude/simple-answers) to reach main. UX request |
| S28 | Stale `web/sd/boat/Bluefin/` page: the boat has no trips, and the generator never deletes old pages | done (claude/seo-2) | Delete pages not regenerated in a run (and keep them out of the sitemap) |
| S15 | Consistent metric with the app (exclude half-days; mean over all trips, not only nonzero) plus a methodology page | coord (app/UX) | Numbers on pages must match the app |

## P1: new data-driven pages

| # | Item | Status | Notes |
|---|---|---|---|
| S16 | `/sd/report/`: rolling 7-day "San Diego fishing report this week" | todo | Plus a weekly archive capped at 12 indexed weeks |
| S17 | `/sd/trips/<length>/` for Full Day, Overnight, 1.5, 2, 2.5, 3 Day | done (claude/seo-2) | Last 14 days, boats that run it (3 yrs, 10+ trips), catch by month ("not a forecast") |
| S18 | `/sd/best-boats/`: leaderboard with methodology | todo | |

## P2: performance and polish

| # | Item | Status | Notes |
|---|---|---|---|
| S19 | Split data.js into a core (<500 KB) and lazy TRIPS chunks | coord (app-dev) | Fixes Googlebot rendering at the root, plus LCP/INP |
| S20 | Load Leaflet CSS only on `/sd/charts`; subset Font Awesome | coord (UX) | Render-blocking CSS |
| S21 | Move Organization + WebSite JSON-LD into `index.html` raw HTML | shipped | |
| S22 | Fix stale meta copy: "34+ boats" (analytics), "live current forecasts" (charts) | shipped | hourly scrape confirmed (cron :37), so "hourly" stays | `web/seo.js` |
| S23 | 1200×630 share image; `theme-color` to match the redesign | coord (Brand/UX) | |
| S24 | Centralize `SITE_URL`/`SITE_NAME` (seo.js, generate_pages.py, export.py, robots, index) so a rename is a one-line change | shipped | Brand set to "Tunatracker" with alternateName for the old names. Manifest, ui.jsx and the logo stay with Brand. Domain move: [DOMAIN_MIGRATION.md](DOMAIN_MIGRATION.md) | Rename prep, see AUDIT §5 |
| S25 | Normalize boat URL encoding (`(`/`)` encoded the same way in the app and sitemap) | todo | |
| S26 | OC/LA: `_redirects` rewrites + generated pages when `SHOW_OCLA` launches | todo (blocked on launch) | 65 boats, 10 landings |
| S27 | PageSpeed Insights run on `/sd/today` and a boat page (no account needed) | **user** | API quota was exhausted from here |

## Done log
- 2026-11-25: S5 www redirect live (user). S17 trip pages, S29 GA tag on generated pages, S30 static species/trip pages on `claude/seo-2`.
- 2026-11-25: S6 (/sd/today, /sd/boats), S13, S14 on `claude/seo-2`; catch tables show the full catch (`full_catch`). PRs #2 and #3 merged.
- 2026-11-24: brand name → "Tunatracker" in titles, OG, site_name and schema (alternateName keeps the old names); DOMAIN_MIGRATION.md contingency plan.
- 2026-11-24: audit written; S1–S4, S8–S12 implemented on `claude/seo-d3e39f` (not pushed).
