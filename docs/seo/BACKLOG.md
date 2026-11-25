# SEO backlog — thetunatracker.com

Ranked by expected organic impact ÷ effort. Evidence for each item is in [AUDIT.md](AUDIT.md).
Status: `todo` · `doing` · `done (branch)` · `shipped` (on main and live) · `user` (needs the user) · `coord` (needs another agent).

## P0: indexing blockers

| # | Item | Status | Notes |
|---|---|---|---|
| S1 | Prerendered pages: keep the static content **visible when the app fails to load** (Googlebot's 2 MB cap truncates data.js), and drop `aria-hidden` | done (claude/seo-d3e39f) | Inline check after `data.js` hides `#root` and shows `#seo-static` when `window.SD` is missing. No change for normal visitors |
| S2 | `seo.js` stops overwriting prerendered `<title>`, description, canonical, og and JSON-LD on first load | done (claude/seo-d3e39f) | `<html data-prerendered>` marker; SPA navigation still updates meta |
| S3 | Canonical, `og:url` and sitemap use the served URL (trailing slash) | done (claude/seo-d3e39f) | Removes "Page with redirect" for ~130 URLs |
| S4 | Sitemap built from the *same* list as the generated pages, with real `lastmod` (last trip date) | done (claude/seo-d3e39f) | |
| S5 | `www.thetunatracker.com` returns 522. Add it as a Pages custom domain or a 301 Redirect Rule to the apex | **user** | Cloudflare dashboard |
| S6 | Prerender static HTML for `/`, `/sd/today` and `/sd/boats` (the highest-demand SPA routes): today's counts by landing, crawlable nav and boat links | todo | Generate `web/sd/today/index.html` etc. and drop those `_redirects` rewrites; or prerender into `index.html`'s `#root`. Needs a check of CF Pages precedence between `_redirects` and static files |
| S7 | Search Console + Bing setup; sitemap submit; URL Inspection "View tested page" on `/sd/today` + one boat page to confirm S1/S6 | **user** | See AUDIT §4 |

## P1: programmatic page quality (biggest traffic lever)

| # | Item | Status | Notes |
|---|---|---|---|
| S8 | Boat template: last-trip date, last 10 trips table, trip-length mix, best months, BreadcrumbList | done (claude/seo-d3e39f) | Answers "<boat> fish report" |
| S9 | Boat/landing/species: `BreadcrumbList` JSON-LD; replace address-less `LocalBusiness` with `Dataset`/`WebPage` | done (claude/seo-d3e39f) for breadcrumbs + landing/species; boat keeps LocalBusiness only when ≥3 reviews | |
| S10 | Landing fleet table: min 5 trips to rank, plus "last 7 days at <landing>" trips table | done (claude/seo-d3e39f) | Fixes 1-trip boats ranked #1 |
| S11 | `noindex` boat pages with <5 trips; exclude them from the sitemap | done (claude/seo-d3e39f) | 13 boats |
| S12 | Boat landing = landing of the most recent trip | done (claude/seo-d3e39f) | 27 boats moved landings |
| S13 | Species pages: "last 14 days" block (boats and counts) | todo | |
| S14 | Sibling links on boat pages (other boats at the landing / same trip lengths) | todo | Internal link graph |
| S15 | Consistent metric with the app (exclude half-days; mean over all trips, not only nonzero) plus a methodology page | coord (app/UX) | Numbers on pages must match the app |

## P1: new data-driven pages

| # | Item | Status | Notes |
|---|---|---|---|
| S16 | `/sd/report/`: rolling 7-day "San Diego fishing report this week" | todo | Plus a weekly archive capped at 12 indexed weeks |
| S17 | `/sd/trips/<length>/` for Overnight, 1.5, 2, 3 Day and Full Day | todo | Catch per angler by month, boats that run it |
| S18 | `/sd/best-boats/`: leaderboard with methodology | todo | |

## P2: performance and polish

| # | Item | Status | Notes |
|---|---|---|---|
| S19 | Split data.js into a core (<500 KB) and lazy TRIPS chunks | coord (app-dev) | Fixes Googlebot rendering at the root, plus LCP/INP |
| S20 | Load Leaflet CSS only on `/sd/charts`; subset Font Awesome | coord (UX) | Render-blocking CSS |
| S21 | Move Organization + WebSite JSON-LD into `index.html` raw HTML | done (claude/seo-d3e39f) | |
| S22 | Fix stale meta copy: "34+ boats" (analytics), "live current forecasts" (charts) | done (claude/seo-d3e39f) | hourly scrape confirmed (cron :37), so "hourly" stays | `web/seo.js` |
| S23 | 1200×630 share image; `theme-color` to match the redesign | coord (Brand/UX) | |
| S24 | Centralize `SITE_URL`/`SITE_NAME` (seo.js, generate_pages.py, export.py, robots, index) so a rename is a one-line change | done (claude/seo-d3e39f) | Brand set to "Tunatracker" with alternateName for the old names. Manifest, ui.jsx and the logo stay with Brand. Domain move: [DOMAIN_MIGRATION.md](DOMAIN_MIGRATION.md) | Rename prep, see AUDIT §5 |
| S25 | Normalize boat URL encoding (`(`/`)` encoded the same way in the app and sitemap) | todo | |
| S26 | OC/LA: `_redirects` rewrites + generated pages when `SHOW_OCLA` launches | todo (blocked on launch) | 65 boats, 10 landings |
| S27 | PageSpeed Insights run on `/sd/today` and a boat page (no account needed) | **user** | API quota was exhausted from here |

## Done log
- 2026-11-24: brand name → "Tunatracker" in titles, OG, site_name and schema (alternateName keeps the old names); DOMAIN_MIGRATION.md contingency plan.
- 2026-11-24: audit written; S1–S4, S8–S12 implemented on `claude/seo-d3e39f` (not pushed).
