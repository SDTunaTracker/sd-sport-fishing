# Domain migration plan: thetunatracker.com → tunatracker.com

Status: **contingency.** The brand is now "Tunatracker" (decided 2026-11-24) and the
site stays on `thetunatracker.com`. `tunatracker.com` is in registrar redemption and may
drop around late December 2026; the user may backorder it. Run this plan only if the
domain is acquired **and** the user decides to move.

Why it's cheap now: the site has ~6 months of history, near-zero organic traffic
(Googlebot couldn't render it until the SEO fixes) and no known backlinks. Every month
of outreach makes a later move more expensive.

## 0. Before the move (any time after acquiring the domain)
1. Add `tunatracker.com` to Cloudflare as a zone. Until the switch, **301 everything to
   `https://thetunatracker.com$path$query`** so nobody can squat on the name.
2. In Search Console, add `tunatracker.com` as a **Domain property** (DNS TXT, done by
   the user). Keep the `thetunatracker.com` property; both must be verified for the
   Change of Address tool.
3. Confirm all of the following in the current branch, so the code change is one line each:
   - `web/seo.js`: `BASE`, `SITE_NAME`
   - `src/generate_pages.py`: `SITE_URL`, `SITE_NAME`
   - `web/index.html`: canonical, `og:url`, `og:image`, `twitter:image`, JSON-LD `url`/`logo`
   - `web/robots.txt`: `Sitemap:` line
   - `web/CNAME`
   - `src/export.py` reads `SITE_URL` from `generate_pages` (sitemap)
   - Other hard-coded mentions: run `grep -rn "thetunatracker.com" web src scripts .github cloudflare-worker`
     (Clerk allowed origins, the CORS allowlists of the review-ingest and chat API workers,
     which today allow only `https://thetunatracker.com`, OAuth redirect URIs, GA4 stream
     URL and email links all need checking)

## 1. Switch day
1. Cloudflare Pages → Custom domains: add `tunatracker.com` and `www.tunatracker.com`.
   Fix `www` on both domains (currently `www.thetunatracker.com` returns 522).
2. Merge the one-line code changes above. Let the deploy finish and regenerate
   `sitemap.xml` and `web/sd/**` (or run `python -m src.main --export-only`) so every
   canonical points to the new domain.
3. On the **old** zone, replace the Pages custom domain with a **Bulk Redirect**:
   `thetunatracker.com/*` → `https://tunatracker.com/${1}`, **301**, preserve the query
   string and the path suffix. Same for `www.thetunatracker.com`. Path-for-path, never to
   the home page.
4. Spot-check with curl (each must be one 301 hop to the identical path on the new
   domain, then 200):
   ```
   /  /sd/today  /sd/boats  /sd/boat/Pegasus/  /sd/boat/Pegasus  /sd/landing/hm-landing/
   /sd/species/bluefin-tuna/  /sitemap.xml  /robots.txt  /sd/forecast (→ /sd/charts on new)
   ```
5. Search Console on the **old** property: Settings → **Change of address** → new
   property. Submit `https://tunatracker.com/sitemap.xml` on the new property. Keep the old
   sitemap reachable (it 301s) for a few weeks; Google uses it to discover the redirects.
6. Bing Webmaster Tools: **Site Move** tool; submit the new sitemap.
7. Update off-site links we control: social bios, forum signatures, GBP (if ever created),
   any landing or boat that linked to us.

## 2. After the move
- Keep the 301s for **at least 12 months** (Google's guidance is 180 days minimum; longer
  is safer). Keep both domains registered for at least 2 years.
- Watch GSC Pages/Indexing on both properties for ~8 weeks: old URLs should drop as
  "Page with redirect", new ones climb. Expect some ranking turbulence for 2–6 weeks.
- GA4: update the stream URL; annotate the switch date.

## What does NOT need doing
- No content or URL-structure changes on the same day (one change at a time).
- No hreflang, no "moved" interstitial, no `rel=canonical` cross-domain hacks: 301s +
  Change of Address are the whole mechanism.
