# Account, settings & free-account gating — Claude Code build brief

Visual reference: `settings_profile_mockup.html` (Coastal style). Build onto the existing `web/account.jsx` + `web/settings.jsx` + `web/user-prefs.js` (Clerk). **Everything is currently free.** A **free account** is the unlock for personal/sticky features, to drive sign-ups. Keep the whole product fully usable logged-out (SEO + first impression); gate only the things that only make sense when they're *yours*.

**Future-proofing:** a paid tier may be introduced for some features later. **Don't build billing now, and don't promise "free forever" / "no card ever" in copy.** But keep feature-gating flag-driven (an `entitlements`/`plan` concept) so a `pro` flag can be layered on later without rework. For now there are two states only: **anonymous** vs **free account**.

## Gating model (anonymous vs free account; paid tier possible later)

**Anonymous / logged-out (no account):** full browse access — Today, reports, leaderboards, boat/landing detail, charts, forecast, analytics, trip-planner browsing. Settings that don't need persistence (region, units, density) work locally via localStorage. This stays crawlable/SEO-friendly.

**Free account unlocks (the sign-up hook):**
- **Follow boats & landings** → personalized Today
- **Target species saved** across devices (logged-out can set locally; account persists it)
- **Alerts / notifications** (the main reason to come back)
- **Watchlist / saved** boats & trips
- **Saved filter/views** in Trip Planner & Analytics
- **CSV export** of leaderboards/history

When a logged-out user taps a gated action (Follow, set an alert, save, export), show a light inline prompt: **"Create a free account to follow boats — takes 10 seconds."** → Clerk sign-up. (Don't say "free forever / no card.") Never a hard wall on browsing.

## Settings screen (rebuild `account.jsx`)
Single-column cards, in this order (match the mockup):

1. **Identity** — avatar (initials), name, email (from Clerk), a `● Free account` badge, Sign out. Sub line: *"Your account saves your followed boats, species, and alerts across all your devices."* (No "free forever" language.)
2. **Boats you follow** — followed boats as removable chips + `＋ Follow a boat` (search/add). **Your landings** — the four landings as toggle chips (focus Today/leaderboards).
3. **Target species** — the 7 species as selectable chips (Bluefin, Yellowfin, Yellowtail, Dorado, Bigeye, Skipjack, Albacore); drives the "trophy" metric and highlights. (Extends existing `trophySpecies`.)
4. **Alerts & notifications** — toggle rows:
   - *A boat you follow finished a trip* — push the fish counts as soon as a followed boat reports in.
   - *A boat you follow scheduled a new trip* — when a followed boat posts a new bookable trip.
   - *A top trip opens spots* — open spots on a high-performing upcoming trip.
   - *Weekly bite report* — Friday digest.

   Plus a delivery `Email | Push` segmented control (frequency if useful).
5. **Preferences** — Region select; **Trip-type focus** `All | Local/day | Multi-day` (extends `tripLengthMethod`); **Water temp** `°F | °C`; **Wind** `kt | mph`; **Density** `Comfortable | Compact` (fold in the existing Tweaks-panel options here).
6. **Your data** — `Export CSV` (free).

## Persistence
- Account-scoped prefs (follows, species, alerts, watchlist) → Clerk user metadata via the existing `getUserPref`/`setUserPref` (`user-prefs.js`). They already round-trip species/region/method on sign-in (`app.jsx`).
- Logged-out: local prefs (region, units, density, and a *provisional* species/follow set) in localStorage; on sign-in, merge local → account (don't lose what they set before signing up).
- Migrate the existing Tweaks panel settings into this Preferences card so there's one settings home (keep the quick Tweaks panel if useful, but it reads/writes the same store).

## Components (reuse the design system — `DESIGN_SYSTEM_ROLLOUT_HANDOFF.md`)
- Toggle switch (coral when on), selectable chip (selected = teal-tint), segmented control, styled select, ghost/coral buttons, the standard `Panel` card and section header. Add these as shared primitives in `ui.jsx` so other pages can reuse them.

## Mobile (test 390px)
- Single column, full-width cards; comfortable spacing; tap targets ≥44px.
- Segmented controls may wrap; chips wrap naturally; toggles stay right-aligned.
- The gated-action prompt is a bottom sheet / inline card, not a modal that traps.

## Guardrails
- No billing UI now (nothing is paid yet) — the only states are *anonymous vs free account*. But keep gating flag-driven (an `entitlements`/`plan` field) so a future `pro` tier can gate features without a refactor. Don't promise "free forever" in any copy.
- Don't gate browsing or anything SEO-relevant. Gate only personal/persistent actions, with a friendly free-account prompt.
- Accessibility: real form controls, labels, focus states, AA contrast.
- Small commits; verify logged-out and logged-in flows on desktop + mobile; don't break the compiled build.
