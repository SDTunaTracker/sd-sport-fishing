# Homepage redesign — Claude Code build brief

Implement the new **Coastal editorial** homepage. The pixel reference is `homepage_coastal.html` (open it — it's the source of truth for layout, color, type, spacing). This brief maps that mockup onto the real app and its data. **Hand Claude Code this file + `homepage_coastal.html` together.**

## Where it lives
- The home view is `HomeView` in `web/dashboard.jsx` (rendered by `app.jsx` for the `home` route). Rebuild `HomeView`'s markup to match the mockup. Keep routing, `window.SD` data plumbing, and the compiled build (`--format=iife` + window exports) intact — verify it renders in a real browser before deploying (this codebase only fails at render time).
- Styles go in `web/styles.css`. Add the design tokens below as CSS variables and scope new homepage classes (avoid collisions with existing global styles).
- Add fonts in `web/index.html` `<head>`: Google Fonts **Fraunces** (headlines + wordmark), **Inter** (UI/body), **DM Mono** (numbers, labels, meta). Use `display=swap`.

## Design tokens (from the mockup)
```
--bg:#FCFBF8;  --surface:#FFFFFF;  --ink:#1B3A33;  --muted:#5C7068;
--faint:#8A8275;  --line:#EDEAE2;  --band:#F5F2EB;
--accent:#CF6A3C;  --accent-ink:#B4572D;  --good:#2E7D5B;
--serif:'Fraunces';  --sans:'Inter';  --mono:'DM Mono';
```
Numbers/metrics/labels/timestamps → mono. Headlines + boat-of-section titles + wordmark → Fraunces. Body → Inter. (Decide whether Fraunces wordmark applies site-wide or homepage only — recommend site-wide for consistency.)

## Sections, in order (match the mockup)

### 1. Hero
- Background: existing `hero-sunrise.jpg` with a left→right dark wash so left-aligned text stays legible (`linear-gradient(96deg, rgba(10,22,18,.86), …)` over `url(...) center 38%/cover`), plus a subtle bottom darken. ~440px tall.
- Content, **left-aligned, vertically centered**: eyebrow `★ San Diego's #1 Sportfishing Analytics` (mono, coral-tint); H1 `Stop guessing.<br>Start catching.` (Fraunces 900); subhead = current value-prop + `Trusted by 38,700+ trips since 2015` (cap subhead width ~560px so it doesn't straggle).

### 2. "Latest reports" + "Season leaders" (two-column strip)
**Left — Latest reports · across all four landings.** The N most-recent trips (≈5) across all landings, newest first. Each row:
- Boat name (Inter 700, ink) + a rating chip on the right (Top today / Above avg / Average / Slow — reuse existing rating logic; chip colors per mockup).
- Detail line (mono, `--muted`): `Landing · Trip length · NN anglers · time-ago`. **Anglers are required.**
- Catch line (mono, `--ink`, ~14px): **exact per-species counts**, e.g. `26 Bluefin · 11 Yellowtail · 4 Dorado`. **No TPA/Day** anywhere in this section.
- Footer link: `View all reports →`.
- Data: `window.SD.TRIPS` (or TODAY) sorted by date desc; species counts already exist per trip in the DB export; angler count is on each trip; compute "time ago" from the trip date/scrape time.

**Right — Season leaders.** Top ~4 boats by `trophy_per_angler_per_day` (2026 season, min 5 trips) — this metric already exists in `analytics.js`. Row: rank (Fraunces, coral), boat, `Landing · NN trips`, value (mono).

### 3. "On the water today" (conditions band — tinted `--band`)
Three stats only (drop bite forecast & best break):
- **Water temp** — current SST + **trend**: an up/down caret + `Warming · +1.4° this week` (or `Cooling · −0.9°`). Compute from `window.SD.SST` history (current vs ~7 days ago); caret coral for warming, blue for cooling.
- **Wind** — current (kt + direction) from the Open-Meteo wind data already fetched (`weather.py` → export).
- **Moon** — illumination % + phase name (you already compute moon; `src/moon.py`).

### 4. "Top trip to book" (dark teal feature band — the focal CTA)
Full-width dark band (`radial coral glow over linear teal gradient`), high contrast, the page's energy moment. Surfaces the **best upcoming trip with open spots, ranked by boat performance**:
- Eyebrow `★ Top trip to book · picked by the data`; boat name big (Fraunces 40px, white); meta line `Landing · Trip length · departs <date> · <time> · $price`.
- Three bold stats (mono, white; first in coral) with plain-language labels:
  - `3.2` — *fish per angler over its last 10 trips*
  - `78%` — *outfished comparable boats this season*
  - `#3` — *ranked boat of 62 this season*
- Right: `● N spots left` (teal), a coral **Book this trip →** button, and `Free to compare every open trip`.
- Data + ranking logic to implement:
  - Candidate trips = upcoming trips with open spots from the schedule (`window.SD.SCHEDULE` / trip planner data).
  - Rank candidates by the boat's recent performance. Metrics to compute per boat:
    - **fish per angler, last 10 trips** = mean(trip total trophy fish ÷ anglers) over that boat's last 10 trips.
    - **% outfished comparable boats** = share of this boat's comparable-length trips that beat the fleet median for the same trip length (reuse the comparable-trip logic behind the existing ratings).
    - **season rank** = its position by `trophy_per_angler_per_day` among all boats (the leaderboard already computes this).
  - Pick the top-ranked candidate; link the button to that trip in the Trip Planner.
  - Be honest if data is thin (e.g. fewer than 10 trips → "last N trips").

### 5. Explore cards + footer
- Two cards: **Analytics** and **Trip Planner** (Fraunces title, arrow, hover lift). Optionally give them a bit more life (icon/hover) so the page finishes strong.
- Editorial footer (Fraunces wordmark + landings line), matching the mockup.

## Data summary (what feeds what)
| Section | Source |
|---|---|
| Latest reports | `SD.TRIPS`/`TODAY` — recent rows, per-species counts, anglers, trip length, landing |
| Season leaders | existing leaderboard (`trophy_per_angler_per_day`, season, min trips) in `analytics.js` |
| Water temp + trend | `SD.SST` history (current vs ~7d ago) |
| Wind / Moon | wind from `weather.py` export; moon from `src/moon.py` |
| Top trip to book | upcoming trips w/ open spots (`SD.SCHEDULE`) × computed boat performance (fish/angler last 10, % outfished, season rank) |

## Mobile view (≤640px) — treat as first-class, not an afterthought
Most users check this on a phone at the dock. Build and test mobile alongside desktop (test at **390px** width; no horizontal scroll anywhere).

- **Nav:** collapse the link row into a hamburger menu (the app's `AppHeader` already has a mobile menu pattern — reuse it). Keep the wordmark + Sign In visible. Tap targets ≥44px.
- **Hero:** reduce height (~340–380px) and scale H1 down (Fraunces ~40px); keep it left-aligned and vertically centered, text still legible over the photo (the dark wash should cover the left/lower area at narrow widths — verify the gradient/focal point holds when the image is cropped tighter).
- **Latest reports + Season leaders:** stack to one column — **reports first, then season leaders**. Report rows stay full-width; if a boat name + rating chip gets tight, let the chip wrap below the name. Keep the per-species catch line fully visible (don't truncate).
- **On the water today:** stack the three conditions (1 per row, or 2-up) and drop the vertical dividers; keep the water-temp trend caret/label.
- **Top trip to book (dark band):** stack vertically — eyebrow → boat → meta → stats (let the 3 stats wrap, ~2 per row) → then `spots left` + a **full-width** "Book this trip" button. Don't let it become a cramped row.
- **Explore cards:** single column, full-width.
- **General:** body text ≥14px, generous line-height, comfortable padding (the desktop 32px side padding should reduce to ~18–20px on phones), and confirm the dark feature band + hero still read well on small screens.

The mockup's media query (`@media(max-width:640px)`) shows the intended stacking, but tighten the real build per the above — especially the nav menu and the trip band, which the static mockup only roughly handles.

## Guardrails
- Use **real data** from `window.SD`, not the mockup's placeholder numbers. If a metric (e.g. % outfished, fish/angler last 10) isn't already computed, add it to `analytics.js` alongside the existing aggregations.
- Match the mockup closely for layout/color/type/spacing; keep it fully responsive (stacking rules are in the mockup's media query) and accessible (real `<a>` links, AA contrast — the palette already passes, heading order, alt text on the hero if it becomes an `<img>`).
- Don't hand-edit `web/data.js` (generated). Small commits; verify the rendered page (desktop + mobile) before deploy.
