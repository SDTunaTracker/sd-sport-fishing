# Design-system rollout — apply the Coastal look to every page

Goal: every page (Today, Forecast, Charts, Boats, Analytics, Trip Planner, boat/landing detail, Head-to-Head, Seasonality, Moon, Account) feels like one product, matching the homepage redesign. Source of truth: `homepage_coastal.html` + `HOMEPAGE_REDESIGN_HANDOFF.md`. **Do it by centralizing shared styles/components first, then sweeping pages — don't restyle each page from scratch.** Verify every page in a real browser (desktop **and** 390px mobile) before deploy; keep the compiled build working.

## Step 1 — Centralize the system (do this first; most pages inherit it)

**Tokens →** put the homepage tokens in `web/styles.css` `:root` (single source of truth) and add the fonts to `index.html` (`Fraunces`, `Inter`, `DM Mono`, `display=swap`):
```
--bg:#FCFBF8; --surface:#FFFFFF; --ink:#1B3A33; --muted:#5C7068; --faint:#8A8275;
--line:#EDEAE2; --band:#F5F2EB; --accent:#CF6A3C; --accent-ink:#B4572D; --good:#2E7D5B;
--serif:'Fraunces'; --sans:'Inter'; --mono:'DM Mono';
--radius:14px; --shadow:0 1px 2px rgba(16,30,46,.05),0 8px 22px rgba(16,30,46,.05);
```
Typography rule everywhere: **headlines / page titles / section titles / wordmark = Fraunces; numbers, metrics, labels, timestamps = DM Mono; body/UI = Inter.**

**Standardize the shared primitives in `web/ui.jsx`** (these are used across pages, so fixing them propagates the look):
- `AppHeader` / nav — Fraunces wordmark, Inter links, active-tab underline in `--accent`, light `--bg` with `--line` border. **Mobile: hamburger menu** (already present — restyle to match).
- `AppFooter` — editorial footer from the mockup.
- **Page header pattern** — a small mono eyebrow + Fraunces page title + muted subline (use on every page for a consistent top).
- `Panel` / card — `--surface`, `1px var(--line)`, `--radius`, `--shadow`; one card style site-wide.
- `KPI` / **StatTile** — big mono value + mono uppercase label (as in the conditions band).
- **Table** — mono headers (uppercase, `--faint`), mono numeric cells, `--line` row dividers, hover `--band`; right-align numbers, left-align names.
- **Chip / Badge** — rating chips (Top/Above avg/Average/Slow) and status pills, colors per mockup.
- **Buttons** — primary = coral (`--accent`, white text, `--radius`, hover lift); ghost = `--surface` + `--line` border.
- **Section header** — eyebrow + Fraunces `h2` + "link →" affordance (the `Latest reports` / `Season leaders` pattern).
- **States** — shared Skeleton (reuse existing `SkeletonRows`), EmptyState, error — all in the new palette.

Once these are updated, most page content re-skins automatically. Then sweep each page for page-specific pieces below.

## Step 2 — Per page

- **Today (`dashboard.jsx`)** — the redesigned homepage (already briefed). Make sure the full report / day views below the fold use the shared Table + chips.
- **Boats (`boats.jsx`)** — leaderboard uses the shared Table + rank styling + rating chips + mono values; sparklines in `--accent`/`--ink`. Add the standard page header.
- **Analytics (`analytics.jsx`, `headtohead.jsx`, `seasonality.jsx`, `moon.jsx`)** — wrap each in `Panel`s with the section-header pattern; charts recolored to the palette (`--accent` primary series, `--good`/muted secondaries, `--line` gridlines, mono axis labels). Tabs styled to match the nav's active treatment.
- **Trip Planner (`tripplanner.jsx`)** — filter controls restyled (inputs/selects/chips on `--surface` with `--line`, coral active state); trip cards use `Panel`; primary action = coral button; reuse the homepage "Top trip" performance framing where it fits.
- **Forecast (`forecast.jsx`)** — page header + `Panel`s; any score/gauge visuals use `--accent`; keep mono for all numbers. Consistent with the conditions language from the homepage.
- **Charts (`charts.jsx`)** — page chrome (header, layer panel, legend, controls) adopts the Coastal system, but the **map stays a dark ocean canvas on purpose** (see `CHARTS_UPGRADE_HANDOFF.md`). Treat the dark map as an intentional inset within the light page — float light controls over it; don't make the whole page dark. This is the one allowed dark zone.
- **Boat / Landing detail (`drilldown.jsx`)** — hero strip with boat photo + Fraunces name + mono stats; tables/chips/cards all shared; tie in reviews (`boat-reviews.jsx`) styled to match.
- **Account (`account.jsx`)** — forms/inputs use the shared input styling; buttons coral/ghost; `Panel` sections.

## Step 3 — Mobile (every page, test at 390px; no horizontal scroll)
- **Nav** → hamburger everywhere (shared `AppHeader`); wordmark + Sign In stay; tap targets ≥44px.
- **Tables** → on phones, reflow wide tables to stacked cards or horizontal-scroll **with a sticky first column** (boat name); never let numbers get clipped. Use one shared responsive-table approach so it's consistent.
- **Filter bars / tabs** (Trip Planner, Analytics) → collapse into a scrollable chip row or a "Filters" sheet; don't wrap into a tall mess.
- **Charts page** → map goes full-bleed; layer controls become a bottom sheet / collapsible panel; legend compact.
- **Multi-column layouts** (detail pages, analytics grids) → single column; cards full-width; side padding ~18–20px.
- **Section headers** → keep eyebrow + title + "link →" but let the link wrap below on narrow widths.

## Guardrails
- Centralize first (tokens + `ui.jsx` primitives), then sweep — don't duplicate styles per page.
- Match `homepage_coastal.html` for color/type/spacing; keep the existing data plumbing, routing, and compiled build intact.
- Don't hand-edit generated files (`data.js`). Small, page-by-page commits; verify each page on desktop + mobile before moving on.
- Accessibility: real `<a>` links, AA contrast (palette passes), correct heading order per page, focus states, `prefers-reduced-motion`.
- Decide once: Fraunces wordmark/titles **site-wide** (recommended) so the brand reads consistently across pages.
