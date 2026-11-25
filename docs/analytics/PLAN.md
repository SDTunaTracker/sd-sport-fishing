# Owner traffic dashboard: audit and options

Status: **proposal, waiting for the owner to choose an option.** No code, Cloudflare settings, accounts or tracking have changed yet.
Branch: `claude/owner-dashboard-b97ab3`, based on `origin/main` @ `c45bbb23` (2026-11-25).

---

## 1. Audit: what exists today

### 1.1 `TTTrack` (`web/analytics-events.js`)

`window.TTTrack` loads before all JSX. **Every event goes to Google Analytics 4 only** (`gtag('event', …)`, property `G-6QDTY73V37`). There is no first-party endpoint. Nothing reaches our Workers or DB.

| Helper | GA4 event | Notable params |
|---|---|---|
| `tripClick` | `trip_click` | boat, landing, trip length, dates, price, spots, win rate, tab, list position |
| `boatView` | `boat_view` | boat, landing |
| `pageView` | `page_view` (custom) | page_name |
| `filterApplied`, `tabSwitch`, `forecastView` | same names | filter values, tab, score |
| `chatOpen`, `chatMessage`, `chatLimitHit` | `chat_*` | page, question length (no question text) |
| `chatLinkClick` | `chat_link_click` | link text, type, destination URL |
| `chatAction` | `chat_action` | action type and data |
| memory monitor | `high_memory_warning` | heap MB |
| `app.jsx` error boundary | `js_error_boundary` | error string |

- `TTTrack.buildUrl` adds `utm_source=thetunatracker&utm_medium=trip_planner&utm_campaign=<landing>&utm_content=<boat>&utm_term=<date>` to outbound booking links. Landings would see these in *their* analytics. We get nothing back.
- `TTTrack._logClick` stores the last 500 trip clicks in **the visitor's own `localStorage`** (`tt_clicks`). The admin "Traffic & Clicks" section reads it with `getClickStats()`. That only shows the clicks made **in the browser viewing the admin page**. It's not site traffic.
- **PR #4 (Co-Captain, open)** adds `chatRecommend`, `chatBookIntent`, `chatBookClick`, `chatCallClick`, `chatLiveCheck`, `chatShare`, `chatSave` and `chatBoatClick`. They also go to GA4 only, joined on `msg_index` and `trip_id`. `chatBookClick` also writes to `tt_clicks`. This is the Co-Captain → Book funnel the dashboard needs, so whichever option wins should add one sink inside `TTTrack` rather than changing call sites.

### 1.2 Admin page and `window.SD.ADMIN`

- Route `#admin` / `view === 'admin'` → `AdminView` in `web/admin.jsx`, compiled to `web/dist/admin.js` and loaded for **every visitor** from `index.html`.
- **Security problem:** the gate is a client-side password check. The `ADMIN_PASSWORD` constant (plaintext) is in the source and in the public `dist/admin.js`. I confirmed it's in the copy served from thetunatracker.com right now. Success only sets `sessionStorage.admin_auth = "1"`, so anyone can also bypass it from the console. **Treat that password as public. If it's reused anywhere else, change it there.**
- `window.SD.ADMIN` is built by `src/export.py::_admin_payload` and shipped inside the **public** `data.js`. It holds the scrape log, SST log, DB stats, backtests, model weights, recent predictions, forecast scores and review moderation stats. Review stats include `pendingReviews` with reviewer names and titles that haven't been approved. So the admin data is public no matter what the password does.
- The admin "User Stats" section only links out to the GA4 UI.
- **Conclusion: the existing admin auth isn't sound and can't be reused.** New traffic data must never go into `data.js` or any static file.

### 1.3 Sign-in and accounts

- **Clerk** (`web/clerk-init.js`, `web/use-auth.js`, `index.html`) handles user accounts and synced followed boats. The site uses a **development instance** (`pk_test_…`, `guided-gannet-98.clerk.accounts.dev`). Clerk development instances aren't meant for production: they have user caps and dev banners, and sessions are scoped differently. It works, but it's a separate follow-up.
- Nothing checks Clerk tokens on a server today, and there are no roles or admin flags.

### 1.4 Cloudflare setup

- **Pages:** `web/` deploys through the Git integration on push (see `.github/workflows/cf-cache-purge.yml`, which purges the zone cache and polls the Pages deployments API). The repo already has `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets. There's no `functions/` directory, so the site uses no Pages Functions.
- **Workers** in `cloudflare-worker/`, all on `*.workers.dev`:
  - `chat-proxy.js` → `chatbot.tylerjchristian.workers.dev`. It relays SSE to Anthropic and doesn't persist conversations. It has no wrangler.toml in the repo.
  - `review-ingest` (KV `REVIEWS`): stores a truncated IP hash per review and keeps an hourly IP rate-limit counter.
  - `scrape-trigger` (hourly cron → GitHub workflow dispatch).
  - `vessel-tracker` (5-minute cron, KV `VESSEL_POSITIONS`; the toml still has `REPLACE_WITH_…` IDs).
  - **None of them collects traffic data.**
- **Cloudflare Web Analytics: not on.** The live HTML has no `static.cloudflareinsights.com/beacon` script or `data-cf-beacon` attribute. It may be turned on in the dashboard with no beacon, but there's no sign of it.
- **Zaraz: not on.** `/cdn-cgi/zaraz/i.js` returns 404.
- The response headers do include Cloudflare NEL/Report-To (network error logging, Cloudflare's own), which is normal.
- **Google Analytics 4 is on** across the site (`index.html`, `privacy/index.html`, and the prerendered pages through `generate_pages.py`). It sets cookies and doesn't respect Do Not Track or Global Privacy Control. The SEO session notes that nobody has looked at GA4 data, and **there's no Search Console property yet.**

### 1.5 Privacy page (`web/privacy/index.html`, updated 2026-11-24)

What it says now, and what any option has to keep true:
- "We use Google Analytics… sets cookies… pages you visit, general location and device type, and some actions" (it gives trip-click details and filters as examples).
- Cloudflare receives IP addresses as the host.
- Reviews store a shortened one-way IP hash. Chat goes through a relay that doesn't save it.
- `localStorage` holds saved boats, waypoints, settings, recently viewed trips, **a log of trips you've clicked**, and the chat counter.
- Choices: clear site data, use tracking protection or GA opt-out, and email to request deletion.

**Any first-party collection needs a new section added in the same PR.** Dropping GA would remove the cookie language.

---

## 2. What the dashboard needs (from the brief)

1. Unique visitors (daily, weekly, monthly) and pageviews, with trends and comparison to the prior period
2. Live or recent activity
3. Top pages, top boat pages, referrers, search terms (from Search Console), and the device and mobile split
4. Funnels: visit → boat or trip view → Book click, and Co-Captain chat → Book click
5. App vs web, once the Expo app ships
6. Owner-only access with real authentication
7. Tunatracker design system (cream, pine, orange; Fraunces and DM Mono), works on the owner's phone, fast

---

## 3. Options

### Option A: Cloudflare Web Analytics, plus GA4 Data API, pulled into our own page

Turn on Cloudflare Web Analytics, a cookieless beacon, for pageviews, referrers, devices, countries and Core Web Vitals. Pull it through the Cloudflare GraphQL Analytics API. Uniques and the funnel events would still have to come from GA4 through the **GA4 Data API**, which also has a realtime endpoint. A small Worker calls both APIs and serves JSON to the owner page.

- **Cost:** $0.
- **Privacy:** no change. GA4 stays, with cookies and no DNT/GPC support.
- **Coverage:** Cloudflare Web Analytics **doesn't report unique visitors** (only visits and pageviews) and **has no custom events**, so funnels and Book clicks depend entirely on GA4. Visitors who block ads or trackers don't show up in GA4, often 20–40%.
- **Owner setup:** Cloudflare Web Analytics toggle, a Google Cloud project, a GA4 service account and JSON key, adding the service account to the GA4 property, and a Cloudflare API token (Account Analytics: Read).
- **Build:** about 1–2 days. GA4's JWT service-account signing inside a Worker is the fiddliest part.
- **Weak spots:** two vendors' quotas and schemas, GA4's thresholding and sampling on small numbers, and no app analytics without Firebase.

### Option B (recommended): first-party collector on a Worker + D1, behind Cloudflare Access

A new Worker, `cloudflare-worker/analytics.js`, on **same-origin routes** on the `thetunatracker.com` zone:

- `POST /a/e`: public collector that takes small JSON beacons through `navigator.sendBeacon`.
- `GET /owner/api/*`: stats API, protected by Cloudflare Access. The Worker also verifies the `Cf-Access-Jwt-Assertion` header against our Access team domain, so it fails closed if the Access app is ever removed.
- `/owner/`: a standalone HTML page in `web/owner/`. It has no data in it; everything loads from `/owner/api/*`. It's also behind Access.

**What one event holds.** No cookies, no raw IPs, no user IDs:

| Field | Source | Notes |
|---|---|---|
| `t` | event type | `pageview`, `boat_view`, `trip_view`, `book_click`, `chat_open`, `chat_message`, `chat_recommend`, `chat_book_click`, `signup` |
| `path` | `location.pathname` | Query string and hash dropped. Known SPA routes are normalized, e.g. `/sd/boat/<slug>`. |
| `ref` | `document.referrer` | **Origin only** (e.g. `google.com`), and blank for same-site referrers. `utm_source` if present. |
| `dev` | screen width bucket + UA family | `mobile` / `tablet` / `desktop`, plus browser and OS family. The raw UA isn't stored. |
| `cc` | `request.cf.country` | Country only, filled in by the Worker. |
| `src` | `web` / `app` / `pwa` | The Expo app sends `app` (see §5). |
| `boat`, `landing`, `trip_id` | event props | Public catalog data, not personal. |
| `nd` / `nw` / `nm` | **client flags** | "First visit today / this ISO week / this month" (see below). |
| `vh` | daily visitor hash | `sha256(daily_salt ‖ ip ‖ ua_family ‖ host)`, truncated to 8 bytes. The salt is random each UTC day, kept only in memory and KV, and **deleted after 48 h**, so a hash can't be linked across days or reversed. |

**How unique visitors work without cookies:**
- **Daily uniques** = distinct `vh` per day. This is Plausible's method.
- **Weekly and monthly uniques** can't come from a daily-rotating hash, because one person on two days would count twice. So the page keeps **one value** in `localStorage`, `tt_seen = "2026-11-25"` (the last visit date, no ID), and sends `nw=1` / `nm=1` the first time it sees the visitor in a new week or month. WAU/MAU is the sum of those flags. If storage is blocked, the Worker falls back to `nd` and `vh`, which counts high, and the dashboard labels that.
- Nothing that identifies a person leaves the device or gets stored.

**Do Not Track / GPC:** if `navigator.globalPrivacyControl` or `navigator.doNotTrack === "1"` is set, **send nothing**. I'd also suggest not loading GA for those visitors (see §4).

**Storage:** D1 database `tt_analytics`:
- `events` holds raw rows for **90 days**, then a daily cron deletes them.
- `daily_rollup` holds counts by day × path × ref × device × country × src. It's kept indefinitely and has no visitor hashes.
- The dashboard reads rollups for long ranges and raw rows for "last 30 minutes".

**Cost:**
- Workers Free has 100k requests a day. D1 Free has 5 GB, 100k row writes a day and 5M row reads a day. Cloudflare Zero Trust Free covers up to 50 users. **$0 at today's traffic.**
- Rough ceiling: about 30k pageviews a day (around 3 beacons each) before the Workers Free cap. Past that, **Workers Paid is $5 a month** with much higher limits. Nothing turns on automatically; the owner would choose to upgrade.
- To keep the cap safe: one batched beacon per page (events queue and flush on `pagehide`), bot user agents dropped, and per-hash rate limits.

**Privacy page:** add a "Visit statistics" section: what's sent, the daily-rotating hash, `tt_seen`, 90-day retention, the GPC/DNT opt-out, and that it's never shared or sold. Keep the GA section while GA stays.

**Coverage:** first-party same-origin `/a/e` gets blocked far less than GA. The funnel is exact because `TTTrack` already fires the events.

**Build:** about 2–3 days: Worker, schema, beacon in `TTTrack`, dashboard page, privacy copy, and tests.

**Weak spots:** we own the code and keep it running. Bot filtering is basic. We don't get GA's demographics, which we don't need.

### Option C: hosted privacy-friendly tool (Plausible, Umami Cloud or PostHog)

| Tool | Cost | Account the owner creates | Cookieless | Uniques W/M | Funnels | Owner dashboard |
|---|---|---|---|---|---|---|
| **Plausible** | from about $9/mo (10k pageviews/mo); about $19 for 100k | plausible.io | Yes | Yes (their own method) | Yes (paid tiers, custom events) | Their UI; shared link with a password or account login. Stats API for our own page. |
| **Umami Cloud** | Free hobby tier (about 100k events/mo); paid from about $20/mo | cloud.umami.is | Yes | Yes | Yes (funnel report) | Their UI, or self-host on a VPS, which isn't free |
| **PostHog** | Free up to about 1M events/mo | posthog.com | Uses cookies by default; cookieless mode exists | Yes | Strong (funnels, paths, session replay) | Their UI. More than this site needs, and replay is a privacy risk. |

- **Privacy:** better than GA (Plausible and Umami). It's still a third party, so the privacy page names it.
- **Build:** about half a day: script tag, `TTTrack` sink, and privacy page. The dashboard is theirs, so **it won't match the Tunatracker design system** unless we also build a page on their API (+1 day, and their API key then needs a Worker proxy behind Access).
- **Weak spots:** a monthly bill as traffic grows, one more vendor with our data, and ad blockers commonly block `plausible.io` and `umami` script URLs unless they're proxied.

### Side by side

| | A: CF WA + GA4 API | **B: Worker + D1** | C: Plausible / Umami |
|---|---|---|---|
| Monthly cost now | $0 | **$0** ($5 past about 30k PV/day) | $0–9+, grows with traffic |
| Accounts to create | Google Cloud SA, CF token | **None new** (Zero Trust is in the existing CF account) | Vendor account |
| Cookies / third party | GA cookies stay | **None, first-party** | None or few, third party |
| True D/W/M uniques | GA4 only | **Yes** | Yes |
| Funnels incl. Co-Captain | GA4 only | **Yes, exact** | Yes |
| Live activity | GA4 realtime | **Yes** | Yes |
| Ad-blocker undercount | High | **Low** | Medium |
| App vs web | Needs Firebase | **Same endpoint, `src=app`** | SDK or events API |
| Design-system dashboard | Yes (our page) | **Yes** | Their UI unless +1 day |
| Build effort | 1–2 days | 2–3 days | 0.5 day (+1 for custom page) |

**Recommendation: B.** It's the only option that hits every must-have at $0 with no new third party. It also lets the privacy page say the truth simply. Keep GA4 running for a 2–4 week overlap so the numbers can be sanity-checked. Then the owner decides whether to remove GA, which would drop cookies and the GA section from the privacy page.

---

## 4. Owner-only access (every option)

**Cloudflare Access (Zero Trust, free plan)** in front of `thetunatracker.com/owner*`, with the existing `/admin` moved behind it too:
- Policy: *Allow* → *Emails* → the owner's own address, with one-time PIN or Google login.
- The Worker also checks the Access JWT (`aud` tag + team certs), so the API refuses requests that skip Access.
- Nothing about this relies on the URL staying secret.

I considered Clerk JWT + an owner user-ID check instead. It's workable, but the site runs a Clerk **dev** instance, and it would mean hand-rolling JWKS verification. Access is stronger and has less code.

Fixes I recommend in the same or a following PR:
1. Delete `ADMIN_PASSWORD` and the sessionStorage gate. Serve admin at `/owner/admin` behind Access.
2. Move `SD.ADMIN` out of the public `data.js` into a file under `/owner/` behind Access, or into the stats Worker.
3. Optional: don't load GA when GPC or DNT is set, so the existing tracking respects the same signals.

---

## 5. Coordination

- **SEO session:** search terms come from **Search Console**, and there's no property yet. Once the owner verifies the `thetunatracker.com` domain property (DNS TXT through Cloudflare, about 2 minutes), the stats Worker can pull top queries, clicks, impressions and position through the Search Console API. That needs a Google Cloud service account with read access to the property, which is Option A's Google setup minus GA. Until then, the dashboard shows referrer `google.com` counts and a "Connect Search Console" card.
- **Co-Captain (PR #4):** its new `TTTrack.chat*` funnel helpers work as they are. Option B adds one `TTTrack._send(type, props)` call inside `_ccEvent`, `chatRecommend`, `tripClick`, `boatView` and `pageView`. **The PR that lands second rebases.** Neither needs to change its call sites.
- **Mobile app:** the Expo app posts the same schema to `https://thetunatracker.com/a/e` with `src: "app"` and an app version. It keeps `tt_seen` in AsyncStorage and respects the OS "limit ad tracking" signal. The app's privacy label and store listing should say "Analytics: not linked to identity". The dashboard adds a Web / App / PWA split once events arrive.

---

## 6. Dashboard spec (Option B)

`/owner/` is a single static HTML page with plain JS and no Babel, so it loads in under 100 ms of script on a phone. It's styled with the `design-system.css` tokens: cream background, pine ink, orange accent, Fraunces headings and DM Mono numbers and labels.

1. **Header strip:** range picker (Today, 7d, 30d, 90d, 12m) and "vs prior period".
2. **KPI tiles:** unique visitors, pageviews, views per visitor, Book clicks, Co-Captain chats. Each has Δ% vs the prior period and a sparkline.
3. **Live:** active in the last 5 and 30 minutes, plus a ticker of the last 20 events (path, country, device, time ago). Polls every 30 s while the tab is visible.
4. **Trend:** daily uniques and pageviews line chart, with the prior period ghosted behind it.
5. **Top pages / top boat pages / referrers / search terms:** ranked bars with counts and Δ.
6. **Devices and sources:** mobile, tablet and desktop split; web, PWA and app split; top countries.
7. **Funnels:** visit → boat or trip view → Book click, and chat open → recommendation → book intent → Book click. Shows step conversion and drop-off.
8. **Footer:** data freshness, retention note, and a link to the privacy page.

The layout is one column at 375 px and two to three columns from 900 px up. It works without hover, and tap targets are at least 44 px.

---

## 7. Next steps once the owner picks

**If B:**
1. I build the Worker, D1 schema, `TTTrack` sink, `/owner/` page, privacy update and tests in this PR. I don't deploy anything.
2. The owner does these steps in the Cloudflare dashboard (exact click paths go into `docs/analytics/SETUP.md` with the code):
   1. **Zero Trust → Settings:** pick a team name. Free plan, no card needed for under 50 users.
   2. **Zero Trust → Access → Applications → Add → Self-hosted:** domain `thetunatracker.com`, paths `owner` and `owner/*` (and `admin` later). Policy: Allow → Emails → the owner's email. Copy the **Application Audience (AUD) tag**.
   3. **Workers & Pages → D1 → Create:** `tt_analytics`. Copy the database ID.
   4. Run `wrangler login` locally, then `wrangler secret put ACCESS_AUD` and `wrangler secret put ACCESS_TEAM_DOMAIN`. Run the schema migration with the command in SETUP.md.
3. The owner gives an explicit OK in this session before anyone runs `wrangler deploy` or merges.

**If A:** I write the Google Cloud and Cloudflare token steps, then build the API Worker and page.

**If C:** the owner creates the vendor account and pastes the site snippet ID. I add the `TTTrack` sink, privacy copy and, optionally, the themed page.
