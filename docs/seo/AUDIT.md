# SEO audit — thetunatracker.com

Audit date: 2026-11-24. Based on `origin/main` @ `fe45d6a5` and the live site.
Owner: SEO agent. The fix plan is in [BACKLOG.md](BACKLOG.md).

Goal: more organic traffic from anglers searching things like "san diego fish counts",
"<boat> fish report", "<landing> fish counts", "1.5 day trip san diego",
"yellowfin tuna san diego this week", and "best sportfishing boat san diego".

---

## TL;DR: the five things that matter most

1. **Googlebot can't render the app.** `data.js` is 21.3 MB uncompressed (1.78 MB with
   brotli on the wire). Googlebot fetches at most **2 MB of each resource, measured
   uncompressed** (Google, *Inside Googlebot*, Mar 2026), so it gets a cut-off script,
   `window.SD` is never defined, and React's error boundary renders
   *"Something went wrong: Cannot read properties of undefined (reading 'TRIPS')"*.
   I reproduced this locally with a server that cuts every response at 2 MB
   (`/sd/today` and `/sd/boat/Pegasus/` both show only that error). **Google probably
   indexes the error text, or nothing, for every SPA route.**
2. **The prerendered pages (122 boats, 5 landings, 4 species) are the only crawlable
   content, and they hide it from Google.** The `#seo-static` block has
   `aria-hidden="true"` and an inline script sets it to `display:none` before the app
   loads. After rendering, Google sees hidden content plus the error box. `seo.js` then
   overwrites the good prerendered `<title>`, description, canonical and JSON-LD with
   generic text.
3. **Canonical, sitemap and internal links all point at URLs that redirect.** Pages live at
   `/sd/boat/Pegasus/` (directory `index.html`), but the canonical, `og:url`, sitemap
   `<loc>` and every in-app `<a href>` use `/sd/boat/Pegasus`, which **308s** to the slash
   version. A canonical that points at a redirect is a mixed signal, and Search Console
   will report "Page with redirect" for all 134 sitemap URLs except the home page.
4. **The SPA routes with the most search demand have no server-rendered content.**
   `/`, `/sd/today` ("san diego fish counts"), `/sd/boats` and `/sd/tripplanner` all
   return the same 8.6 KB shell with an empty `#root`. No route answers "fish counts this
   week", "<landing> fish counts today" or "<trip length> trip" with crawlable HTML.
5. **`www.thetunatracker.com` returns Cloudflare error 522.** Anyone who types `www.`
   (and any backlink that uses it) gets a dead page. This is a DNS/Cloudflare fix the user
   has to make (see Off-site).

None of the fixes need a visual change. Items 1–4 are generator and `seo.js` work in this
repo. Item 1 also needs a medium-term **data.js split** (shared with the app-dev agent,
since it's also the main page-speed problem).

---

## 1. Technical

### 1.1 What Googlebot sees

| URL | Status (Googlebot UA) | Raw HTML content | Rendered (2 MB cap simulated) |
|---|---|---|---|
| `/` | 200, 8.6 KB | empty `#root` + skeleton | "Something went wrong" |
| `/sd/today` | 200, 8.6 KB | empty | "Something went wrong" |
| `/sd/boats`, `/sd/charts`, `/sd/tripplanner`, `/sd/analytics/overview` | 200, 8.6 KB | empty | "Something went wrong" |
| `/sd/boat/Pegasus` | **308** → `/sd/boat/Pegasus/` | — | — |
| `/sd/boat/Pegasus/` | 200, 6.5 KB | h1, intro, stats table, species totals (hidden) | static block hidden + error |
| `/sd/landing/hm-landing/` | 200, 10.7 KB | fleet table, 46 boats (hidden) | same |
| `/sd/species/bluefin-tuna/` | 200 | top-10 boats + month table (hidden) | same |
| `/ocla/today`, `/sd+ocla/today`, `/ocla` | **404** | — | — |
| `/privacy` | 404 (the page is still on the UX branch) | — | — |
| `www.thetunatracker.com/*` | **522** | — | — |
| `http://` → `https://` | 301 ✅ | | |
| unknown path `/sd/nonexistent` | 404 ✅ (real 404 status) | | |

Method: `curl -A Googlebot` for raw HTML. For the rendered view, a local server
(`gbot_serve.py` in the session scratchpad) mirrors the CF Pages routing and cuts each
response at 2,097,152 bytes. The page was loaded in Chromium and I read
`document.body.innerText`. Without the cap the app renders fine.

**Why the 2 MB limit applies:** Google's documented Googlebot limit is per fetched URL,
applied to each JS/CSS resource requested during rendering, and counted on decompressed
bytes. `data.js` is 21.3 MB decompressed, and `TRIPS` alone is about 17.8 MB. Even if Google
ever got the whole file, parsing 21 MB of JS is the kind of render cost that WRS times
out on.

### 1.2 Routing and `_redirects`
- The SPA-route 200 rewrites (`/sd/today` → `/` 200, etc.) are correct: crawlers now get a
  200 instead of 404.html. ✅
- `/sd/forecast*` → `/sd/charts` 301 ✅ (consistent with forecast being R&D only).
- **OC/LA routes (`/ocla/*`, `/sd+ocla/*`) are missing from `_redirects`**, so they 404 for
  crawlers even though the app can route them (behind `FEATURES.SHOW_OCLA`). Fine while the
  feature is hidden. When OC/LA launches, add the rewrites and pages.
- Trailing-slash mismatch on prerendered pages (see TL;DR #3).
- Encoding mismatch: the app links `/sd/boat/Patriot%20(SD)` while the sitemap uses
  `Patriot%20%28SD%29`. Both resolve, but they're two URLs for one page. Normalize on one
  encoder.

### 1.3 Titles, descriptions and canonicals

| Route | `<title>` (from `seo.js` at runtime; raw HTML always has the home title) | Notes |
|---|---|---|
| home | The Tuna Tracker — San Diego Sportfishing Fish Counts & Boat Leaderboards | 76 chars, truncated in SERPs |
| today | Today's San Diego Fish Counts — Live Sportfishing Report \| Tuna Tracker | Good target. Desc says "updated hourly"; the scrape is daily plus some hourly — keep it true |
| boats | San Diego Sportfishing Boats Directory \| Tuna Tracker | ok |
| analytics | "…Analytics… **34+ boats** … 11 years" | stale count (187 boats in DB, 112 active in last 90 days) |
| tripplanner | "…highest historical win rate…" | ok |
| charts | "…live current forecasts" | Currents layer is DEMO/retired. Drop "live current forecasts" |
| boat (runtime) | `{boat} — Fish Counts, Reviews & Schedule` | **overwrites** the better prerendered title |
| boat (prerendered) | `{boat} — {landing} Fish Counts & Win Rate \| Tuna Tracker` | Good. Add "Fish Report" (the actual query wording) |

- Raw HTML for **every** SPA route has the home title, description and canonical
  (`https://thetunatracker.com/`). Google only sees the right ones if rendering
  succeeds, which it doesn't (1.1). Result: every SPA route looks like a duplicate of `/`
  with canonical → `/`.
- No `<meta name="robots">` anywhere; that's fine.

### 1.4 robots.txt
- The live file is **Cloudflare Managed robots.txt** prepended to ours. It disallows AI
  *training* crawlers (GPTBot, ClaudeBot, Google-Extended, CCBot…) and sets
  `Content-Signal: search=yes, ai-train=no`. Googlebot and Bingbot are allowed. ✅
- Side effect: it also blocks **GoogleOther**, **Applebot-Extended** and **meta-externalagent**.
  None of those affect Google or Bing Search ranking. Applebot (Siri/Spotlight) is still
  allowed. That's the user's call; no SEO harm.
- Our own block has `Disallow: /admin` ✅ and the `Sitemap:` line ✅.
- `/api/v1/*.json` and `/data.js` are crawlable. That's harmless; they aren't HTML.

### 1.5 sitemap.xml
- Generated daily by `src/export.py::_write_sitemap` and committed by the workflow ✅.
- 134 URLs: 5 SPA routes, 120 boats, 5 landings, 4 species.
- Problems:
  - **Every `<loc>` except `/` 308-redirects** (no trailing slash on prerendered pages).
  - `lastmod` = today for every URL every day. Google ignores lastmod that is always
    "now". Use the boat's last trip date (landing/species: latest trip).
  - The boat list comes from `boats` in data.js, but pages come from a separate DB query, so
    sitemap and pages can drift (the sitemap lists boats with no page and vice versa).
  - `changefreq`/`priority` are ignored by Google (harmless).
  - Missing: `/sd/charts` (fine), and the future report pages.

### 1.6 Structured data
- Home (runtime only): `Organization` + `WebSite`, injected by `seo.js`, so Google never
  sees it in raw HTML. Move it into `index.html`.
- Boat pages: `LocalBusiness` with name/description/url, **no address, no
  `parentOrganization`, no image**. Rich-result eligibility for `LocalBusiness` needs an
  address. A charter boat isn't really a LocalBusiness we own, and marking up a business
  we don't operate is a gray area. Better: `BreadcrumbList` (eligible) plus
  `Dataset` (catch data, eligible for Dataset Search) on boat, landing and species pages.
  Keep `AggregateRating` **only** for first-party reviews. Google's review-snippet
  policy disallows self-serving reviews but allows ratings collected about third-party
  businesses. Our reviews come from users, so that's OK, but only once ≥3 real reviews
  exist (already gated).
- Landing pages: `LocalBusiness` with a city-only address. Same concern. Use
  `BreadcrumbList` + `Dataset`, with `about` → `{"@type":"Place","name":"H&M Landing"}`.
- No `BreadcrumbList` anywhere, though HTML breadcrumbs already exist. Easy win.
- Never add `Event`/`TouristTrip` with prices we don't control. Schedule data goes stale.

### 1.7 Open Graph and Twitter
- Present on index and generated pages ✅. Boat pages use the boat photo for `og:image` ✅.
- `og:image` falls back to `logo.png`, which is not 1200×630. A branded share card
  (one static PNG) would help social CTR. **Brand agent's call** (new name and logo pending).
- `theme-color` is `#0ea5e9` (old sky blue), which doesn't match the redesign palette.
  Flag for UX.

### 1.8 Core Web Vitals and page weight
- Field data (CrUX): not available through the API (the shared PageSpeed quota was used up
  today). **The user should run https://pagespeed.web.dev on `/sd/today` and a boat page**;
  it needs no account.
- Lab, desktop Chromium on a fast connection: DOMContentLoaded 1.85 s, load 2.16 s,
  CLS 0.000 on `/sd/today`. `data.js` = 1.78 MB transfer, 633 ms download, 21.3 MB to parse.
- Expected on a mid-range phone over 4G: LCP well over 4 s ("poor"), because the whole
  21 MB `data.js` is a **synchronous, render-blocking `<script>`** in `<body>` before any
  app code, and nothing paints until React mounts. INP risk: preprocessing ~50k trips
  on the main thread (`SDA.preprocessTrips` in the `App` initializer).
- Other render-blocking resources: Google Fonts CSS, Font Awesome (full 6.5.2 set),
  Leaflet CSS on every page (only `/sd/charts` needs it), and the Clerk SDK (async ✅).
- **Fix direction (shared with the app-dev agent):** split `data.js` into a small
  "today + boats + meta" core (<500 KB) plus lazily fetched `TRIPS` chunks (by year or
  region). This fixes Googlebot rendering *and* LCP. Until then, prerendered HTML is the
  real SEO fix.

### 1.9 Mobile
- Viewport meta ✅. The redesign was mobile-checked by the UX agent. Not re-audited here.

### 1.10 Internal linking
- Nav and boat-list links are real `<a href>` elements ✅ (67 anchors on `/sd/boats`, 54 to
  boat pages).
- But those anchors exist only in the rendered DOM, which Googlebot doesn't get (1.1). In raw
  HTML, the only crawlable link graph is landing page → boats and species page → top-10
  boats. **Boat pages link to nothing except their landing and `/sd/boats`.** There are no
  sibling links (similar boats, same trip length) and no links from boat → species.
- The home page has zero crawlable links in raw HTML.

### 1.11 Images
- On `/sd/boats`, all 47 images have `alt` ✅. Boat photos live under `/images/boats/` ✅.

### 1.12 hreflang
- Not relevant (English only, US audience). A Spanish version isn't worth it.

---

## 2. Programmatic pages (`web/sd/`, from `src/generate_pages.py`)

Inventory: **122 boat pages, 5 landing pages, 4 species pages**. Generated on each export
and committed by the daily workflow, so they're fresh daily ✅.

### Quality assessment

| Check | Boat pages | Landing pages | Species pages |
|---|---|---|---|
| Unique content | Partly: numbers differ, but it's a 1-sentence template + 4-row table + 4 species totals | Fleet table is unique and useful | Top 10 + month table, useful |
| Word count (visible) | ~80 words → **thin** | ~200 + table | ~150 + tables |
| Freshness signal | None: no "last trip" date, no recent trips (`stats['recent']` is computed but **never rendered**) | None | "last 5 years" |
| Answers "<boat> fish report"? | No: the searcher wants *the latest counts*, which aren't on the page | — | — |
| Ranking sanity | — | **Sorted by win rate, so 1-trip boats (Ronin, Sun Dance II, Carolena 0%) rank top/bottom** | min 5 trips, but includes half-day trips |
| Metric clarity | "win rate" isn't defined; "avg fish/angler/day" averages only *nonzero* trips (inflated) | same | same |
| Visible to Google | Hidden (`display:none`, `aria-hidden`) | same | same |
| Canonical | → redirecting URL | same | same |
| In sitemap | yes (via a different list) | yes | yes |
| Structured data | thin `LocalBusiness` | `LocalBusiness` | `WebPage` |

Other notes:
- Boats that moved between landings (27 boats have trips at >1 landing) get whichever
  landing the `SELECT DISTINCT` returns first. Use the most recent trip's landing.
- Half-day trips are mixed into boat stats, but CLAUDE.md says half-days are filtered out
  of the headline metric. Pages and app can disagree.
- `theme-color`, styles and the Clerk tag are copied from `index.html` at generation time ✅
  (stylesheet versions lag one deploy behind; harmless).
- 13 boats have <5 trips. Those pages are near-empty. `noindex` them (or skip generating
  them) until they reach 5 trips, to avoid thin-content signals sitewide.
- No OC/LA boat pages yet (the region is hidden). This is the next big programmatic set when
  OC/LA launches: Dana Wharf, Newport, Davey's Locker, 22nd Street and others, 65 boats.

**Verdict:** these pages are the right idea and the biggest opportunity: about 120 long-tail
"<boat> fish report" queries with low competition (the landings' own sites and
sportfishingreport.com are the competition). Today they're thin, hidden, stale-looking and
canonicalized to redirects. The fix is **template work, not new pages**: recent trips,
last-trip date, trip-length mix, best months, consistent metrics, sibling links, visible
fallback, BreadcrumbList + Dataset.

---

## 3. Content plan (keyword map)

No paid keyword tool was used (constraint). Intent is inferred from how SoCal anglers search
and from competitor coverage (sportfishingreport.com, 976-tuna.com, the landings' own
fish-count pages, fishdope, bloodydecks). Volumes are directional: H = head term,
M = mid, L = long tail. **Every page below is generated from `tracker.db`. No hand-written
filler, and no forecasts presented as predictions.**

| Cluster | Example queries | Vol | Page (URL) | Built from |
|---|---|---|---|---|
| Daily counts | san diego fish counts, sd fish report, fish counts today | H | `/sd/today` (prerendered) | today's trips table, by landing |
| Landing counts | h&m landing fish counts, fisherman's landing fish count, seaforth fish counts, point loma sportfishing fish counts | H/M | `/sd/landing/<slug>/` (exists, upgrade) | last 7 days of trips at that landing + fleet table |
| Boat reports | pegasus fish report, red rooster iii fish counts, \<boat\> sportfishing | L ×120 | `/sd/boat/<name>/` (exists, upgrade) | last 10 trips, last-trip date, trip mix |
| Weekly report | san diego fishing report this week, yellowfin tuna san diego this week | M | **new** `/sd/report/` (rolling 7-day) + `/sd/report/2026-w48/` archive | 7-day aggregates: per-species totals, best boats, trip lengths |
| Species × now | yellowfin tuna san diego, bluefin tuna fishing san diego, dorado fishing san diego, yellowtail fishing san diego | M | `/sd/species/<slug>/` (exists, upgrade) | add "last 14 days" block + top boats this season |
| Trip length | 1.5 day trip san diego, overnight fishing trip san diego, 3 day fishing trip san diego, full day fishing san diego | M | **new** `/sd/trips/<1-5-day>/` | catch per angler by trip length, boats that run it, typical species by month |
| Best boat | best sportfishing boat san diego, best san diego fishing boat for tuna | M | **new** `/sd/best-boats/` (+ per species/trip-length sections) | leaderboard with min-trip rules and a methodology note |
| Season | when is tuna season san diego, bluefin season san diego | M | species pages' month table, plus a "season" section | 10+ years of monthly catch rates (historical, not a forecast) |
| Landing info | h&m landing, fisherman's landing parking (navigational) | M | landing pages (fleet + link to the landing's own site) | — |

Rules for these pages:
- Each one needs **≥1 table of real numbers that changes over time** and a clear
  "updated <date>" line. If a page has no data in the window (e.g. dorado in January),
  say so and show the seasonal table rather than padding with filler.
- Define metrics once (`/sd/methodology` or a section on each page) and link to it.
- `noindex` any generated page with fewer than 5 trips behind it.
- Weekly archives: index the last 12 weeks; `noindex` older ones or fold them into
  monthly pages, so we don't pile up thousands of near-duplicate pages.

---

## 4. Off-site

### Search Console and Bing (user action; no accounts created by me)
1. **Google Search Console:** add a *Domain property* for `thetunatracker.com`, verified
   by DNS TXT record in Cloudflare. Submit `https://thetunatracker.com/sitemap.xml`.
   Then use **URL Inspection → "Test live URL" → "View tested page"** on `/sd/today` and
   `/sd/boat/Pegasus/`. That's the authoritative check of finding 1.1. Please share a
   screenshot of the rendered HTML/screenshot tab.
2. **Bing Webmaster Tools:** "Import from Google Search Console" (one click once GSC is
   set up). Bing also powers DuckDuckGo and ChatGPT search results.
3. Cloudflare → Pages → Custom domains: **add `www.thetunatracker.com`** (or a Redirect
   Rule `www` → apex, 301). It currently returns 522.

### Google Business Profile
**Don't create one.** GBP requires a physical location or in-person service area that
customers visit. A data website doesn't qualify, and a fake address risks suspension.
Revisit only if there's a real storefront or service.

### Backlinks (earned, no paid links)
- **Landings and boats:** offer each boat a "see our stats on The Tuna Tracker"
  badge/link for their site or Instagram bio. Boats with high win rates will want it.
- **Forums and community:** bloodydecks.com (trip-report threads, signature link),
  976-tuna/fishdope forums, the SoCal fishing Facebook groups. Post data-driven
  answers ("bluefin per angler by month since 2015"), not spam.
- **Local press and blogs:** San Diego Union-Tribune outdoors, Western Outdoor News
  (WON), San Diego Reader, NBC 7/Fox 5 fishing segments. Pitch a data story: "best
  month for yellowfin in 10 years", "how the 2026 season compares".
- **Data citations:** a public `/sd/methodology` + downloadable season CSV gives
  journalists and bloggers something to cite (Dataset schema helps Dataset Search).
- **Fishing-tackle shops** (Point Loma Tackle, Fisherman's Landing Tackle): link exchange
  for a "this week" widget.

---

## 5. Rename / domain-migration watch-list (coordinate with the Brand agent)

> **Update 2026-11-24:** the name is **Tunatracker**, staying on thetunatracker.com for now. Titles, OG and schema were updated on `claude/seo-d3e39f`. If tunatracker.com is acquired, follow [DOMAIN_MIGRATION.md](DOMAIN_MIGRATION.md).


If the site gets a new name or domain, these all change and **must** be done together:
- 301 every URL path-for-path (old domain → new), including `/sd/boat/*`, landing,
  species and sitemap. Keep the old domain's Cloudflare zone alive for at least 12 months.
- Search Console **Change of Address** tool (needs both domains verified first) and a
  new sitemap on the new property. Bing has its equivalent "Site Move".
- Hard-coded `https://thetunatracker.com` in: `web/seo.js` (`BASE`),
  `src/generate_pages.py` (canonical/og), `src/export.py::_write_sitemap` (`base`),
  `web/robots.txt` (`Sitemap:`), `web/index.html` (canonical, og:url, og:site_name,
  title/desc text), `web/CNAME`, the manifest, and the title suffix "| Tuna Tracker" in
  generated pages. **Next step:** centralize these into one `SITE_URL`/`SITE_NAME`
  constant so a rename is a one-line change.
- Brand name in titles: "Tuna Tracker" brand searches are tiny today, so a rename costs
  little brand equity now. **The cheapest time to rename is before backlinks build up.**
  Recommend deciding before the backlink push in section 4.
