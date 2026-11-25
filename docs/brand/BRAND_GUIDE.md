# Brand Guide (draft)

Status: Phase 3 proposal, 2026-11-24. Assumes direction **A · Tail & Tally** and the name **Tuna Tracker**. Nothing here is live until the owner approves. Mockups: `docs/brand/mockups/` (`brand-review.html` shows everything together).

---

## 1. Name in use

- **Product name:** Tuna Tracker. Drop "The" in the logo, app name, headings and copy.
- **Domain stays** thetunatracker.com. Writing "The Tuna Tracker" in running text is fine during the transition.
- **Descriptor** (when scope needs saying): *SoCal sportboat fish counts*. Regional pages: *Tuna Tracker · San Diego*, *Tuna Tracker · OC / LA*.
- **App-store name:** `Tuna Tracker: Fish Counts` (25 chars); subtitle `SoCal sportboat counts & boats`.
- **Assistant:** Co-Captain (always capitalised, hyphenated).

## 2. Logo

**Parts.** The *symbol* (three rising count bars running into a tuna's crescent tail) and the *wordmark* ("Tuna Tracker" in Fraunces 600, tracking −0.025em).

| Asset | File | Use |
|---|---|---|
| Horizontal lockup | `mockups/wordmark-horizontal.svg` | Site header, footer, docs, email |
| Stacked lockup | in `brand-review.html` | Merch, About page, square spaces |
| Symbol | `mockups/symbol.svg` | App icon, avatars, 48 px and up |
| Small symbol (tail only) | `mockups/symbol-small.svg` | Favicon and anything under 48 px |
| Favicon | `mockups/favicon.svg` | Browser tab (plus 16/32/48 ICO and 180 px apple-touch PNG) |
| App icon | `mockups/app-icon.svg` | iOS/Android/PWA, full-bleed (OS applies the mask) |

**Before production:** outline the wordmark text to paths (the mockups use live Fraunces text), and export PNGs at 16, 32, 48, 180, 192, 512 and 1024 px.

**Colorways.** Orange symbol + pine wordmark on cream (default). Orange symbol + cream wordmark on pine. All-pine or all-cream one-color. Never orange wordmark text.

**Clear space** = the height of the tallest count bar on every side. **Minimum size:** lockup 120 px wide; symbol 48 px; below that use the small symbol.

**Don't:** stretch, rotate, recolor outside the palette, add shadows, outline, put it on busy photos without a pine scrim, re-add "The" to the mark, or bring back the badge for anything but merch.

## 3. Color tokens

These already exist in `web/design-system.css`; the guide gives them roles. No new colors.

| Token | Hex | Role |
|---|---|---|
| `--pine` / `--ink` | #17332C | Brand color, text, dark surfaces, theme-color |
| `--pine-2` | #1F4A3F | Hover on pine, gradients |
| `--accent` | #CF6A3C | **Actions and the symbol only.** One orange thing per view where possible |
| `--accent-ink` | #B0542A | Orange text on light backgrounds, hover |
| `--bg` | #FBFAF6 | Page paper |
| `--band` | #F4F1E9 | Section bands |
| `--surface` | #FFFFFF | Cards |
| `--sea` | #2F7F86 | Data highlights, links in data views |
| `--muted` / `--faint` | #5A6E66 / #8C978F | Secondary text |
| `--good` / `--warn` / `--bad` | #2E7D5B / #B7791F / #B8432F | State only, never decoration |
| Species | Bluefin #2F5D8A · Yellowfin #C9A227 · Yellowtail #4F8A5B · Dorado #2F7F86 | Charts and species chips only |

**Retire:** sky blue #0ea5e9 and slate #0f172a (still in `web/manifest.webmanifest` and `<meta name="theme-color">` in `web/index.html`), and the navy/yellow badge colors.

Contrast: pine on cream ≈ 13:1; orange #CF6A3C on cream ≈ 3.5:1, so use orange for large text, icons and button fills with white text (white on orange ≈ 3.6:1 fails WCAG AA for the 13.5 px button labels; `--accent-ink` #B0542A gives ≈ 5:1 and is the safer button fill if accessibility review flags it).

## 4. Type

| Role | Face | Weights | Use |
|---|---|---|---|
| Display | Fraunces | 600 (500 for long titles) | Headlines, page titles, the wordmark, boat names in heroes |
| UI and body | Inter | 400, 500, 600 | Everything people read or click |
| Numbers and labels | DM Mono | 400, 500 | Every number in tables and stat tiles (tabular), eyebrows in 11 px uppercase tracked .14em |

Scale (px, web): 56 / 36 / 28 / 20 / 17 / 15 / 13.5 / 11. App uses the same families (Fraunces + DM Mono already landing on the app branch).

Rules: sentence case everywhere; no ALL CAPS except mono eyebrows; numbers always in DM Mono with `tabular-nums`.

## 5. Iconography

- Font Awesome is already in use; standardise on **one style** (solid, 1em, `--muted` by default, `--ink` when active).
- Species get colored dots or chips, not fish clip-art.
- The tail symbol is the only fish drawing in the system. Don't add illustrated fish to UI.

## 6. Photography

**Licensing first.** Boat photos in `web/images/boats/` were taken from landing websites and are not licensed. Before they're used more widely (OG images, the app store, ads):

1. Ask each landing or boat owner for written permission (a short email template can be drafted on request) with credit "Photo: [Boat] / [Landing]".
2. Commission or license a small owned set: 20–30 shots across the four landings (boats at the dock at dawn, the rail during a bite, the fish counts board, hands and gear).
3. Until then, use the typographic placeholder (boat initials on pine/sand) that the website UX backlog already proposes.

**Direction:** real SoCal light (dawn, overcast marine layer, late gold), people at the rail rather than posed grip-and-grins, the landings themselves, the count board. Slightly warm and desaturated to sit with cream and pine. **Avoid:** stock "fisherman smiling" shots, freshwater, tropical-resort clichés, heavy HDR, AI-generated fish.

## 7. Voice

A sharp deckhand who also keeps a spreadsheet. Direct, specific, a little salty, never cute.

| Do | Don't |
|---|---|
| "2.41 trophy fish per angler per day" | "Epic bite!!" |
| "Ranked fairly across trip lengths" | "#1 sportfishing analytics" |
| "No counts posted yet. Landings usually report by 7 PM." | "Oops! Something went wrong 😢" |
| "Experimental: based on past seasons" | "Our forecast shows where the fish will be" |
| Name the boat and the landing | "Top vessels" |

Forecast copy is always labeled experimental and never says predict, guarantee or know.

## 8. Templates

- **Link preview (static):** `mockups/og-static.svg`, 1200×630, for every page without its own card.
- **Link preview (daily):** `mockups/og-daily-template.svg`, with `{DATE} {BOAT} {TRIP} {ANGLERS} {LANDING} {TPAD}` filled by the export step and rendered to PNG. Only show real numbers; never forecast numbers.
- **Social square (1080×1080):** same as daily, stacked; for Instagram and the Facebook groups.

## 9. Applying it (after approval)

Website, on the brand branch, through the design system, coordinated with the website UX session:
1. `web/index.html`: theme-color → #17332C; favicon.svg + ICO + apple-touch PNG; `og:image`/`twitter:image` → the static card; titles use "Tuna Tracker".
2. `web/manifest.webmanifest`: name/short_name, theme #17332C, background #FBFAF6, separate 192/512 maskable icons.
3. `web/ui.jsx` header: add the symbol before the wordmark, drop "The".
4. `web/home.jsx`: replace "★ San Diego's #1 Sportfishing Analytics" kicker.
5. Keep `web/logo.png` available for any existing references until they're switched.

App (handed to the app UX session, not changed directly): icon and adaptive icon from `app-icon.svg`, splash on pine with the symbol, store name and subtitle above.
