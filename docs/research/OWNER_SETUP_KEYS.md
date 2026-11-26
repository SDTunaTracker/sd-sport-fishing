# Owner setup: keys and accounts for the new data sources

*Written 2026-11-25. You (the owner) do every step here. Claude didn't create any account, key or project. Console menus move around, so if a name differs slightly, search for it in the console's top search bar. Each key goes in one secret store only and is never pasted into chat, code or a doc.*

| Feature | What you create | Where the key goes | Expected cost |
|---|---|---|---|
| Google reviews on boat/landing pages | Google Cloud project + billing + Places API (New) key | Cloudflare Worker secret `GOOGLE_PLACES_API_KEY` | **$0** with the built-in cap (≤30 calls/day ≈ 900/month vs 1,000 free) |
| Real ocean currents on Charts | Copernicus Marine account (free) | GitHub secrets `COPERNICUSMARINE_SERVICE_USERNAME`, `COPERNICUSMARINE_SERVICE_PASSWORD` | **$0** (free, including commercial use with credit) |
| YouTube trip videos (optional) | YouTube Data API v3 key (same Google project, no billing used) | GitHub secret `YOUTUBE_API_KEY` | **$0** (10,000 units/day free; it never bills) |

Everything stays **off** on the live site until the matching flag in `web/feature-flags.js` is flipped in a PR you approve. You can preview first with `?preview_google=true` or `?preview_videos=true`.

---

## A. Google Places API key (about 15 minutes)

1. Go to **https://console.cloud.google.com/** and sign in with the Google account that should own the bill.
2. Top bar → **project picker** (next to "Google Cloud") → **New project**. Name it `tunatracker`. Organization: "No organization" is fine. Click **Create**, then select it in the project picker.
3. **Billing:** ☰ menu → **Billing** → **Link a billing account** → **Create billing account**. Enter the card; Google requires one even for the free tier. Make sure the new project shows this billing account.
4. **Budget alert (do this before enabling anything):** Billing → **Budgets & alerts** → **Create budget**.
   - Name: `tunatracker cap`. Scope: project `tunatracker`.
   - Amount: **$5**. Alerts at 50%, 90% and 100% (email).
   - Note: a budget sends alerts but doesn't stop spending. The hard stop is step 6 plus the Worker's daily cap.
5. **Enable the API:** ☰ → **APIs & Services** → **Library** → search **"Places API (New)"**. Open it and click **Enable**. Not the legacy "Places API".
6. **Hard quota cap:** APIs & Services → **Enabled APIs & services** → **Places API (New)** → **Quotas & System Limits**.
   - Find the per-day limit for **Place Details** requests (named like "GetPlace requests per day").
   - Click ✏️ and set it to **40**.
   - If there is a Text Search per-day limit, set it to **300**. It's only used once, for matching.
   - This guarantees you stay inside the free tier even if something misbehaves.
7. **Create the key:** APIs & Services → **Credentials** → **+ Create credentials** → **API key**. Copy it once into a password manager.
8. **Restrict the key:** on the key's page, click **Edit API key**:
   - Name: `places-proxy`.
   - **Application restrictions:** None. The key is only used server-side, inside the Cloudflare Worker, and Worker IPs aren't fixed.
   - **API restrictions:** **Restrict key** → tick only **Places API (New)** → **Save**.
9. **Put it in Cloudflare.** From the repo folder in PowerShell:

   ```powershell
   cd cloudflare-worker
   ```

   ```powershell
   npx wrangler deploy --config places-proxy-wrangler.toml
   ```

   ```powershell
   npx wrangler secret put GOOGLE_PLACES_API_KEY --config places-proxy-wrangler.toml
   ```

   Paste the key when wrangler asks. The deploy prints the Worker URL, e.g. `https://places-proxy.<your-subdomain>.workers.dev`.
10. *(Optional, for an exact daily cap in the Worker too)* Cloudflare dashboard → **Workers & Pages → KV** → **Create namespace** `PLACES_KV`. Paste its id into `places-proxy-wrangler.toml` (uncomment the block) and deploy again.
11. **Match boats to Google listings (one time).** In PowerShell from the repo folder:

    ```powershell
    $env:GOOGLE_PLACES_API_KEY = "<paste key>"; .venv\Scripts\python.exe scripts\match_google_places.py --apply
    ```

    It fills `web/api/v1/google_places.json` with confident matches only (about 190 searches, inside the free 5,000 a month). **Check the list by hand.** Many party boats have no Google listing of their own; those then show their landing's reviews, clearly labelled. Delete any wrong match.
12. Tell the data-sources session the Worker URL. It will set `window.PLACES_WORKER_URL` and give you a preview link (`?preview_google=true`). After you've looked, it flips `GOOGLE_REVIEWS: true` in a PR for you to approve.

**What it costs.**
- Each review panel view is one "Place Details Enterprise + Atmosphere" call.
- Google gives **1,000 of those free a month**, then about **$25 per 1,000**. The quota in step 6 and the Worker's `DAILY_CAP=30` keep you under 1,000, so **expect $0**.
- If you later want reviews on every page view with no cap, budget roughly $25 per extra 1,000 views and raise both caps together.

**Rules we follow** (Google's, built into the code):
- Only `place_id` is stored.
- Reviews are fetched live each time.
- At most 5 reviews are shown, in Google's "most relevant" order, with the author's name and profile link.
- "Google Maps" is credited as the source, with a link to the listing.
- Google ratings are never mixed into our own angler-review average.

## B. Copernicus Marine account (about 5 minutes)

1. Go to **https://data.marine.copernicus.eu/register** and fill in the form. Use type of use: "Commercial" or "Other", and describe it as "surface currents layer on a sportfishing website".
2. Confirm the email link. Choose a **unique** password, not reused anywhere.
3. GitHub → the repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, twice:
   - `COPERNICUSMARINE_SERVICE_USERNAME` = your Copernicus username
   - `COPERNICUSMARINE_SERVICE_PASSWORD` = your Copernicus password
4. Done. The next **full** daily run (around 14:00 UTC) installs the `copernicusmarine` tool and writes `web/currents_grid.json`. The Charts "Currents" layer then loses its **DEMO** badge and shows the credit line "Generated using E.U. Copernicus Marine Service Information" (required by their licence). If the file is ever more than 4 days old, the map falls back to DEMO automatically.

**Cost:** free, including commercial use, as long as we show the credit. The service is funded through mid-2028. We'll get notice if that changes.

## C. YouTube Data API key (optional, about 5 minutes)

1. Same Google Cloud project → **APIs & Services** → **Library** → **"YouTube Data API v3"** → **Enable**.
2. **Credentials** → **+ Create credentials** → **API key** → **Edit API key**:
   - Name `youtube-videos`.
   - API restrictions: **Restrict key** → only **YouTube Data API v3**.
   - Save.
3. GitHub → repo → Settings → Secrets and variables → Actions → **New repository secret** `YOUTUBE_API_KEY`.
4. **Privacy policy update (required by YouTube's API policies before we show videos):** add one line to the site's privacy page, e.g.:

   > "Some boat pages show YouTube videos using YouTube API Services; see the [YouTube Terms of Service](https://www.youtube.com/t/terms) and the [Google Privacy Policy](https://policies.google.com/privacy)."

5. Tell the data-sources session. After a few daily runs have filled `web/api/v1/boat_videos.json`, it sends you a preview (`?preview_videos=true`) and then a PR to turn it on.

**Cost:** $0. The YouTube API has a free daily quota and no billing. Each daily run uses at most about 4,100 of the 10,000 units.

## D. Recommendation: retire the old `ocean_currents` table

The HYCOM data in `ocean_currents` ends in November 2018, and the daily run already skips the fetch (P0-1). Today the only reader is the 2014–2018 backtest (`src/backtest.py`); `src/completeness.py` already marks the table as historical. The Charts map never read it (it used a synthetic grid).

Once the Copernicus layer has run cleanly for **7 days**:
- **retire `src/currents.py`** (the dead fetcher)
- **keep the `ocean_currents` table** read-only for that backtest, rather than dropping it
- remove the synthetic DEMO fallback text from Charts in a follow-up PR
