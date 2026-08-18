# Fishare teardown + best practices for The Tuna Tracker

What Fishare (fishare.app) built, and what's worth borrowing. Their moat is a **predictive bite forecast**; yours is **real boat catch-count analytics + booking** — so adapt, don't copy. The interesting part is their *patterns*: how they earn trust, structure content, and package it.

## What they built (feature inventory)

1. **One headline answer: a 0–100 "Bite" score** per spot/day, plus a second **"Access" score** (can you safely get there). "Two scores, not one" — bite ≠ green light if access is low.
2. **Per-species, per-spot personalization** — the forecast is cut to the species you target and your saved locations.
3. **Two forecast modes** — Inshore (tide/dawn-driven) vs Offshore/Pelagic (current + SST-gradient, midday plateau). Different priors per mode; honest that one model can't serve both.
4. **Conditions map, 12 overlays + 14-day time slider** — SST, SST-gradient, wind, waves, swell period, pressure isobars (marching-squares), currents, AIS vessels, closure polygons.
5. **14-day planning matrix** — saved spots × 14 days; each cell = verdict + peak window + swell; best cell auto-highlighted; **confidence visibly fades days 8–14**.
6. **30-day moon & species calendar** — lunar bite rating, solunar major peaks, in-season species rotation.
7. **Offshore pelagic HSI heatmap** — species habitat-suitability, **grounded in peer-reviewed literature** (thermal preference, shelf-break weighting, depth), top-10 ranked pins/day with score + SST + coords.
8. **Closures/regulations overlay** — polygons color-coded by type (no-take, finfish-only, safety), **verbatim official rule** on tap, "verified against the DPIRD guide."
9. **Content/SEO engine — long-form guides** — 14–19-min local guides: complete-area guide, regulations, safety, forecast literacy, seasonal playbooks, boat ramps; weekly bite report; species playbooks. "Written for anglers, not search engines."
10. **AI assistant** — trained on their guides + 10,000+ podcast-transcript chunks, **cites its sources**, does fish-photo ID.
11. **Methodology transparency** — a "Read the method" story: *tide first, moon second, pressure third*; "not a vibes-based map"; **validated against held-back catch data.**
12. **Freemium pricing** — free (today/tomorrow, limited) → Premium $4.99/mo (7-day forecast + alerts, 14-day matrix, 30-day calendar, all species, unlimited logging, CSV export). Beta = free-for-life hook. **No account required to try.**
13. **Scale/credibility framing** — "2.5M+ catches · 207 species · 4 coasts · 4.2× catches-per-trip among members who fish their peak windows."

## Best practices worth incorporating (prioritized for you)

### High impact — you already have the raw materials
1. **Publish a "Methodology / How it works" page (trust moat).** Fishare's biggest credibility lever is openly showing its method + accuracy. You have `backtest_report.json` and a real backtested forecast — *surface it*. Explain trophy-per-angler-per-day in plain English, how the forecast is built, and show backtested accuracy. This is exactly what FishDope's "trust me" approach can't match.
2. **Confidence honesty.** Wherever you show a forecast/score, show a confidence level and **fade far-out days** (Fishare grays out days 8–14). Honest uncertainty builds more trust than false precision.
3. **A single daily "answer" up top.** Fishare leads with one score. Your homepage already moved toward this (the hot-day status + top trip). Consider a small daily **fleet read / conditions score** as a recurring at-a-glance element across pages.
4. **Ground + cite the AI assistant.** You already call Claude (`cloudflare-worker/chat-proxy.js`). Borrow their pattern: ground it on *your* data (counts, boats, trends) + any guides you publish, make it **cite sources**, and add fish-photo ID. "Which boat should I book this weekend for bluefin?" answered from your data is a killer.

### High impact — net-new, big upside
5. **A San Diego content/SEO "guides" engine.** This is their most underrated growth play and it pairs perfectly with your crawlable-routing work. Publish evergreen, genuinely useful pages: per-boat profiles, per-landing guides, per-species playbooks (SD bluefin, yellowtail, dorado), seasonal playbooks, a **weekly bite report**, "how to read the counts." Each becomes a search entry point. Written for anglers, kept current. (Your boat/landing/species pages already exist as data — wrap them in real content.)
6. **Personalization: target species + favorite boats/landings.** Let signed-in users pick their species and follow boats/landings; tailor Today + alerts to them. You have Clerk auth + the data already.
7. **Alerts.** Notify when a followed boat scores big, a target species fires, or a top-performing trip opens spots. Converts the daily-check habit into retention. (Pairs with your scheduled-scrape pipeline.)
8. **Freemium model.** Free core analytics + counts (your acquisition engine and SEO surface); Premium for forecast detail, alerts, advanced charts, data export, head-to-head. Being the *modern, partly-free* option is a wedge against FishDope's $199 wall. "No account required to try" lowers friction.

### Medium — packaging & polish
9. **A "next 14 days" planning matrix** — adapt their spots×days grid to **boats/trips × upcoming days**, or a conditions-by-day forecast grid, with the best cell highlighted. A genuinely useful planning view.
10. **Closures / MPA overlay** — already in your charts brief (CDFW MPAs as the US equivalent of their NSW DPI layer).
11. **Confident, plain-language editorial voice + credibility stats** — you're already adopting this ("Stop guessing. Start catching.", "Trusted by 38,700+ trips"). Keep leaning in: scale numbers, plain-language verdicts, "know before you go" energy.
12. **Segment by trip type** (their inshore vs offshore idea) — half-day local vs full-day vs multi-day long-range behave differently; your `trophy_per_angler_per_day` already normalizes, but framing/filtering by trip type echoes their honest two-mode thinking.

## How this maps to your existing briefs
- Charts overlays, SST fronts, time slider, closures → `CHARTS_UPGRADE_HANDOFF.md`.
- Forecast score, accounts, alerts, freemium, content/SEO engine → `PRODUCT_ROADMAP_HANDOFF.md` (these reinforce and sharpen it).
- The **two genuinely new adds** to fold into the roadmap: a **public Methodology/accuracy page** (trust) and a **content/guides engine** (SEO + authority) — both low-tech, high-leverage, and uniquely credible for you because of your 11 years of real catch data.

## The honest framing
Fishare predicts *where/when fish will be*. You report *which boats actually caught them*, with a decade of receipts. Their best practices to steal are about **trust (show your method + accuracy), content (guides/SEO), and packaging (one daily answer, personalization, freemium, alerts)** — not their forecast model. Lead with the data only you have.
