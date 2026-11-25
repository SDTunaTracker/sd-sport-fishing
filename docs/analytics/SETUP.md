# Owner dashboard: setup steps

These are the steps only the owner can do: they need your Cloudflare and GitHub logins. Nothing here costs money at today's traffic. Allow about 20 minutes.

When you're done you'll have:
- **https://thetunatracker.com/owner/**: the traffic dashboard (visitors, pages, funnels, live activity)
- **https://thetunatracker.com/owner/admin/**: the old admin page (scrape health, backtests, review queue), now behind the same sign-in

Only the email address you allow in step 2 can open either page. Cloudflare checks your email (it sends you a one-time code) before the page loads. The Worker then checks Cloudflare's signed token again before it returns any data.

> **Order matters a little.** Do steps 1–5 before the PR is merged. If the PR is merged first, nothing breaks: the site keeps working and the dashboard just shows "couldn't load stats" until the Worker is deployed. The old `#admin` link will already point to `/owner/admin/`, though, so do steps 1–2 first so that page is protected from the start.

---

## 1. Turn on Cloudflare Zero Trust (free)

1. Go to **https://dash.cloudflare.com** and sign in.
2. In the left sidebar, click **Zero Trust**.
3. If this is your first time, Cloudflare asks for a **team name**. Enter something like `tunatracker`. Your team domain becomes `tunatracker.cloudflareaccess.com`. **Write it down**: you'll need it in step 4.
4. Choose the **Free** plan (up to 50 users).
   - Cloudflare may ask for a payment method even for the $0 Free plan. You won't be charged unless you change plans later.
5. To find your team domain later: **Zero Trust → Settings → Custom Pages** (or **Settings → General**), under **Team domain**.

## 2. Create the Access application (the lock on /owner)

1. In **Zero Trust**, go to **Access → Applications** and click **Add an application**.
2. Choose **Self-hosted**.
3. **Application name:** `Tunatracker owner`
4. **Session duration:** `24 hours`. If you'd rather sign in less often on your phone, choose `1 week`.
5. Under **Public hostname** (it may be called **Application domain**), add two entries:
   - Domain: `thetunatracker.com`, Path: `owner`
   - Click **Add public hostname** again. Domain: `thetunatracker.com`, Path: `owner/*`
6. Under **Policies**, click **Add a policy** (or **Create new policy**):
   - **Policy name:** `Owner only`
   - **Action:** `Allow`
   - **Include → Selector:** `Emails`, **Value:** the email address you'll sign in with
   - Save the policy and make sure it's attached to the application.
7. Under **Login methods** (or **Authentication**), make sure **One-time PIN** is on. You can also add Google if you prefer.
8. Click **Save** (or **Add application**).
9. Open the application again. On its **Overview** (or **Basic information**) tab, copy the **Application Audience (AUD) Tag**. It's a long string of letters and numbers. **Keep it for step 4.**

**Check:** open https://thetunatracker.com/owner/ in a private window. You should see a Cloudflare sign-in page asking for your email. Enter it, type the code from your inbox, and the page loads. Its numbers will be empty until step 5.

## 3. Create the D1 database

1. In the main Cloudflare dashboard (not Zero Trust), go to **Storage & Databases → D1 SQL Database** (in some layouts, **Workers & Pages → D1**).
2. Click **Create** (or **Create database**).
3. **Name:** `tt_analytics`. **Location:** `Western North America` if it asks. Click **Create**.
4. Copy the **Database ID** shown on the database's page.
5. Send me the Database ID, or paste it yourself into `cloudflare-worker/analytics-wrangler.toml` in place of `REPLACE_WITH_D1_DATABASE_ID`. It isn't a secret.

## 4. Create the tables and set the secrets

Run these from the repo folder in PowerShell. The first command opens a browser so you can approve access to your Cloudflare account. Skip it if you've already logged in to wrangler on this computer.

```powershell
npx wrangler login
```

Create the tables. The schema is idempotent, so running it twice is safe.

```powershell
npx wrangler d1 execute tt_analytics --remote --file cloudflare-worker/analytics-schema.sql --config cloudflare-worker/analytics-wrangler.toml
```

Make a random token for the admin data push. This prints one line; copy it.

```powershell
node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"
```

Set the Worker's secrets. Each command asks for the value; paste it and press Enter.
- `ACCESS_TEAM_DOMAIN`: your team domain from step 1, e.g. `tunatracker.cloudflareaccess.com`
- `ACCESS_AUD`: the AUD tag from step 2
- `OWNER_EMAILS`: the same email as the Access policy. Separate several emails with commas.
- `ADMIN_INGEST_TOKEN`: the random token you just made

```powershell
npx wrangler secret put ACCESS_TEAM_DOMAIN --config cloudflare-worker/analytics-wrangler.toml
```

```powershell
npx wrangler secret put ACCESS_AUD --config cloudflare-worker/analytics-wrangler.toml
```

```powershell
npx wrangler secret put OWNER_EMAILS --config cloudflare-worker/analytics-wrangler.toml
```

```powershell
npx wrangler secret put ADMIN_INGEST_TOKEN --config cloudflare-worker/analytics-wrangler.toml
```

If wrangler asks whether to create a new Worker named `tt-analytics`, answer **yes**.

Then put the **same** `ADMIN_INGEST_TOKEN` value in GitHub, so the daily scrape can push admin data:
1. Go to **https://github.com/SDTunaTracker/sd-sport-fishing → Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. **Name:** `ADMIN_INGEST_TOKEN`. **Secret:** paste the token. Click **Add secret**.

## 5. Deploy the Worker

**I won't deploy it without your OK in this session.** You can run it yourself, or tell me "deploy the analytics Worker" and I'll run this exact command:

```powershell
npx wrangler deploy --config cloudflare-worker/analytics-wrangler.toml
```

This creates the Worker `tt-analytics` with two routes on thetunatracker.com, `/a/*` and `/owner/api/*`, plus a daily cron at 00:15 Pacific. Every other path stays on Cloudflare Pages, exactly as today.

**Checks.** Each should print the status shown.

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" -X POST https://thetunatracker.com/a/e
```
Expected: `204` (the collector quietly ignores an empty request).

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" https://thetunatracker.com/owner/api/stats
```
Expected: `302` or `403` (Cloudflare Access blocks you without signing in). If you see `200`, stop and tell me: Access isn't covering `/owner/*`.

## 6. Merge the PR

Merging deploys the site changes through Cloudflare Pages:
- the cookieless counter starts sending from thetunatracker.com
- `/owner/` and `/owner/admin/` go live
- the admin data leaves the public `data.js`
- the old password page goes away

The next scrape run pushes admin data to `/owner/admin/`. Look for **"admin push: HTTP 200"** in the workflow log under **Push admin data to the owner dashboard**. If it shows `403` with a challenge page, Cloudflare's Bot Fight Mode is blocking GitHub's servers; tell me and I'll switch the push to a route that isn't challenged.

Then, on your phone, open **https://thetunatracker.com/owner/**, sign in with the email code, and use **Share → Add to Home Screen**.

Your own visits aren't counted: any browser that has opened `/owner/` is skipped by the counter.

## 7. Optional: search terms (Google Search Console)

The "Search terms" card needs Search Console. This is shared with the SEO work.
1. Go to **https://search.google.com/search-console**, click **Add property**, choose **Domain**, and enter `thetunatracker.com`.
2. Choose **Verify with Cloudflare** if it's offered. Otherwise copy the TXT record into **Cloudflare → DNS → Records → Add record** (Type `TXT`, Name `@`).
3. Tell me when it's verified. Pulling search terms into the dashboard needs a Google Cloud service account with read-only access to the property. I'll write those steps when you're ready; it isn't built yet.

## 8. In 2–4 weeks: decide about Google Analytics

Both counters run side by side for now. Once you're happy with the dashboard's numbers, you can remove Google Analytics. The privacy page can then drop the cookie wording, and the site loads one fewer third-party script. Just say the word.

---

## Reference

| What | Where |
|---|---|
| Collector, stats API, Access check | `cloudflare-worker/analytics.js` |
| Worker config (routes, cron, D1 binding) | `cloudflare-worker/analytics-wrangler.toml` |
| Tables | `cloudflare-worker/analytics-schema.sql` |
| Browser side (beacon, GPC/DNT opt-out) | `web/analytics-events.js` (bottom section) |
| Dashboard | `web/owner/index.html` |
| Admin page | `web/owner/admin/index.html`, source `web/owner/admin.jsx` (`npm run build:owner`) |
| Tests | `npm run test:analytics` |
| Local preview with fake data | `npm run dev:analytics`, then open http://localhost:8787/owner/ |

**Costs and limits (Workers Free + D1 Free):**
- 100k Worker requests a day, which is roughly 30k pageviews a day.
- 100k D1 row writes a day and 5M row reads a day.
- If traffic passes that, the collector starts failing quietly; the site itself is unaffected. **Workers Paid ($5/month)** raises every limit. Nothing upgrades automatically.

**Rotating secrets:** rerun the matching `wrangler secret put` command. For `ADMIN_INGEST_TOKEN`, update the GitHub secret too.

**Removing everything:**
1. Delete the Worker (Workers & Pages → `tt-analytics` → Settings → Delete).
2. Delete the D1 database.
3. Delete the Access application.
4. Revert the PR.
