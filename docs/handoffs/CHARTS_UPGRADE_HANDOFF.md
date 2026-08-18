# Charts upgrade — Claude Code handoff

Goal: bring the ocean-conditions map up to (and past) Fishare/FishTrack polish, reusing what already exists. **Do not rebuild what's there.** Verify every change in a real browser (`scripts\serve.ps1`) — render-time only.

> **START HERE — this is mostly a *styling* job, not a feature job.** A live side-by-side (our charts page vs Fishare) found we already have the layers (SST/Canvas+Fronts, Pressure, Swell, Currents, Catches, Boats LIVE). The professional gap is almost entirely visual rendering. Do the "Make it look professional" section below **first** — it's the highest-impact, lowest-effort work — then the feature tasks (A–E) further down.

## Make it look professional (do this first)

Observed gap: our map renders on a **light road-map base** (cream land, inland city/freeway labels — Barstow, Palm Springs, San Bernardino, Yuma, Mexicali) with **empty light-blue water** and a few faint dots. Fishare renders a **dark, minimal, ocean-focused** map where the water is painted with glowing data. Close that:

1. **Dark, ocean-focused basemap (single biggest win).** Replace the light tiles with a dark, minimal basemap and strip inland clutter:
   - Options: **CartoDB Dark Matter** (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`), Stadia/Stamen "toner"/dark, or a **MapLibre GL dark ocean style** if moving off raster tiles. Prefer a style where land is muted and labels are minimal (no freeways/desert towns).
   - Land should recede (dark/desaturated); the ocean is the canvas. On dark, warm SST + cyan contours pop; on light they wash out.
2. **Paint the water by default.** On load the SST/Canvas+Fronts raster must actually fill the ocean as a **bold, smooth, color-ramped field** (cool blue/purple inshore → warm orange/red offshore), not faint dots. If the canvas raster is currently rendering only sample points or near-transparent, fix the fill + opacity (~0.7) and color ramp. The glowing temperature field IS the product — show it without the user toggling anything.
3. **Frame on the fishing grounds.** Default center/zoom to the **offshore SoCal–Baja zone** (the banks/canyons: 9-Mile, 425, 371, Coronados, lower 500s), land minimized — not zoomed out to Arizona. Set sensible `maxBounds` around the fishable ocean.
4. **Thermal fronts as glowing contours.** Draw the SST gradient as smooth contour lines + front arrows (Fishare's cyan isobars / orange fronts) with minimal **mono** labels (e.g. `2.4°F/10km`), instead of raw dots. (Pairs with the marching-squares task D.)
5. **Premium UI chrome.** Replace default Leaflet `+/−` and the boxy "My Waypoints" popup with a sleek dark control panel floating **over** the map; group layers (Temperature / Water color / Motion / Weather / Vessels). Add a **temperature legend / color scale** and a hover-readout (`64.2°F · 2.1°F/10km front · 32.8,-117.6`) styled small + mono + glowing, matching the dark theme.
6. **Tokens:** dark navy canvas, one warm accent (SST), one cool accent (cyan contours/labels), DM-Mono-style numerals for readouts. Keep it minimal — few labels, high contrast, lots of dark space.

Acceptance: open the charts page cold → a dark, ocean-centered map with the SST field already glowing on the water, a legend, and a clean floating layer panel — reads as a pro fishing chart at a glance, before any interaction.

## What already exists (build on this)

`web/charts.jsx` is already a capable Leaflet map:
- **SST tiles:** NASA GIBS WMTS — MODIS Aqua day/night + GHRSST MUR L4 (`SST_SOURCES`, `getOverlayLayer`).
- **Chlorophyll:** GIBS VIIRS tiles. **Bathymetry:** GEBCO WMS. **Tides/currents:** NOAA tidesandcurrents.
- **Animated wind field** and **animated ocean-current field** via **`lib/leaflet-velocity`** (particle grids; currents fetched from HYCOM/ERDDAP with a synthetic fallback).
- **Live AIS vessels** via aisstream.io (`BoatsSetupOverlay` already onboards an API key).
- Layer toggles already exist (sst, chlorophyll, …).

Backend already produces the data: `src/sst.py` (ERDDAP MUR/OSTIA), `src/currents.py` (HYCOM), `src/chlorophyll.py`, `src/upwelling.py`, and **`src/weather.py` already calls Open-Meteo** (`api.open-meteo.com/v1/forecast` for wind, `marine-api.open-meteo.com/v1/marine` for swell). `src/forecast.py` already computes `_sst_gradient_score` and `_wind_direction_score`. Data reaches the front end via `export.py` → `window.SD.SST` / `window.SD.FORECAST`.

## What Fishare/FishTrack do that we don't yet

1. **Cloud-free SST + a thermal-front (SST-gradient) overlay.** Our SST is satellite tiles with cloud gaps; the killer offshore layer is a smooth, gap-free SST raster *plus* a gradient layer that lights up temperature breaks where fish stack. We already compute the gradient for scoring — we just don't draw it.
2. **A time slider** to scrub forecast-driven layers (wind, swell, currents, SST) across ~14 days. Today the layers are mostly "latest only."
3. **Animated swell/wave field** (we have the swell data from Open-Meteo, but don't render it as a field like wind).
4. **Pressure isobars** (marching-squares contours) for at-a-glance synoptic read.
5. **Unified polish:** one clean layer panel + legend + a "what the water's doing here" readout, and the map module lazy-loaded so it doesn't slow other pages.

## Tasks (priority order)

### A. Cloud-free SST raster + thermal-front overlay  *(highest value for offshore)*
- Add a gridded SST source for the SoCal bbox from **Open-Meteo** (`marine-api.open-meteo.com` / forecast API — free, no key) or reuse the ERDDAP MUR grid already fetched in `src/sst.py`. Render it as a smooth colored canvas raster via `L.imageOverlay` (paint the grid to an offscreen canvas, color-ramp by °F).
- Add an **SST-gradient ("front") layer**: compute |∇SST| per cell (the same quantity behind `_sst_gradient_score`) and draw the strongest breaks as highlighted contour/heat. This is the single most useful offshore overlay.
- Add a legend + a tap/hover readout (SST value, gradient strength, coords).

### B. Time slider (14-day) for forecast layers
- Fetch the full Open-Meteo time series once (wind, swell, SST, pressure on the SoCal grid) and cache it client-side (the codebase already caches grids, e.g. `_CURR_CACHE_KEY`).
- Add a scrubber (now → +14d, hourly/3-hourly steps) that re-renders the velocity/raster layers for the selected timestep. Reuse the existing leaflet-velocity setData pattern; just swap the grid per timestep.
- Confidence cue: visually fade/annotate days 8–14 (Open-Meteo skill drops), like Fishare.

### C. Animated swell/wave field
- Reuse the **leaflet-velocity** wind/current pattern with a third instance fed by Open-Meteo marine swell (direction + height → u/v components). Color-ramp by wave height; period as a secondary readout.

### D. Pressure isobars (marching-squares)
- Pull MSL pressure grid from Open-Meteo; compute isobar contours with **`d3-contour`** (or `marchingsquares.js`) and draw as `L.polyline`/SVG overlay with hPa labels. Light, cheap, high "pro" signal.

### E. Polish & performance
- One consolidated layer control (grouped: Temperature / Water color / Motion / Weather / Vessels / Closures) with a legend per active layer.
- **Lazy-load the whole map module** (Leaflet + leaflet-velocity + chart code) only on the charts route so it doesn't bloat first paint elsewhere.
- Mobile: full-bleed map, bottom-sheet layer panel, ≥44px controls.
- Our **catch-data differentiator:** optionally overlay recent landing/catch markers so anglers see conditions *and* where boats scored — neither competitor can do this.

## Data additions (the only two worth borrowing from competitors)

A source-by-source comparison vs Fishare (Open-Meteo · NASA GIBS · SunCalc · NSW DPI · Claude AI) found we already use Open-Meteo (`weather.py`), NASA GIBS (`charts.jsx`), and Claude (chatbot worker → `api.anthropic.com`). Two gaps worth filling:

1. **SunCalc — solunar / sun + moon times.** Add the `suncalc` JS library (tiny, free, no API, deterministic). We currently compute moon phase only (`src/moon.py` → `moon_info`). SunCalc adds sunrise/sunset, golden hour, sun altitude, moon illumination %, moonrise/moonset — which unlocks **solunar major/minor feeding windows** anglers expect. Surface it on the forecast/charts (e.g. a "best windows today: dawn + moon-overhead" readout) and feed sun-altitude into the offshore forecast's time-of-day weighting if useful. Keep `moon.py` as the source of truth for phase; use SunCalc for the sun/solunar extras.

2. **California closures / Marine Protected Areas overlay (the US equivalent of their NSW DPI layer).** `charts.jsx` already references closure/MPA — finish it with US sources: **CDFW (CA Dept. of Fish & Wildlife) Marine Protected Areas** polygons, plus NOAA Fisheries seasonal closures and bag/size limits where available. Draw closure polygons on the dark map (color by type: no-take vs restricted), tap-to-read the verbatim rule + season/limits. This is a trust/utility feature competitors charge for; pair it with the boat/catch data nobody else has.

Note: we already have sources the competitors don't — NOAA tides & currents, HYCOM currents, GEBCO bathymetry, live AIS (aisstream), upwelling, and 11 years of structured boat catch counts. The data stack is ahead; these two are additive polish, not catch-up.

## Data-source notes
- **Open-Meteo** (`api.open-meteo.com`, `marine-api.open-meteo.com`): free, no API key, ~25 km marine grid, hourly, ~14-day. Already used in `weather.py` — extend it to return full grids (multiple lat/lon) rather than single points. Respect rate limits; cache aggressively (you already do).
- Keep existing ERDDAP/GIBS sources as alternate SST/chl layers (satellite "true look" vs model "cloud-free").
- AIS stays on aisstream.io (already wired).
- Attribute sources in a map credit (Open-Meteo, NOAA/CoastWatch, NASA GIBS, GEBCO).

## Guardrails
- Reuse existing patterns (`getOverlayLayer`, the velocity grids, the grid cache keys); don't introduce a second map library.
- Grids can be large — render to canvas, throttle on slider drag, cache per timestep; never block the main thread on the full 14-day fetch.
- Free data only, with attribution; no keys committed to the repo (use the existing aisstream key-entry pattern for anything that needs one).
- `web/data.js` is generated — if SST/forecast grids should be precomputed server-side, add them in `export.py`, don't hand-edit `data.js`.
- Small commits; verify each layer renders on desktop + mobile before moving on.
