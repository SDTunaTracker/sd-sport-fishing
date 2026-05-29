# Contributing to SD Sport Fishing / The Tuna Tracker

## Adding a new component file

When you add a new `web/something.jsx` file:

1. **Create the file** — export its top-level component to `window`:
   ```javascript
   window.SomethingView = SomethingView;
   ```

2. **Reference it in `web/index.html`** — add a `<script>` tag with today's
   version string before `app.jsx`:
   ```html
   <script type="text/babel" src="something.jsx?v=YYYYMMDD-1"></script>
   ```
   Order matters: scripts load sequentially. Shared utilities (ui.jsx) must
   appear before files that use them.

3. **Wire it into routing** (if it's a nav view) — in `web/app.jsx`:
   - Add to `HASH_VIEWS` and `navMap`
   - Add a branch in the content switch

4. **Add nav entry** (if applicable) — in `web/ui.jsx`, add to the `NAV` array:
   ```javascript
   { id: 'something', label: 'Something', icon: 'fa-icon-name' },
   ```

5. **Run the pre-commit check** — it runs automatically on `git commit`, or
   manually:
   ```powershell
   python scripts/verify-deploy.py
   ```
   This catches missing `index.html` references and stale version strings.

## Bumping cache-bust versions

After editing any `web/*.jsx` or `web/styles.css`:

```powershell
python scripts/bump-versions.py
```

This auto-increments `?v=YYYYMMDD-N` for files modified today. The pre-commit
hook runs it automatically — you only need to call it manually for a dry run
(`--dry-run`) or after editing outside normal commit flow.

## Running the post-deploy smoke test

After pushing to main and waiting for CI to finish:

```powershell
python scripts/smoke-test.py
# Or against the GitHub Pages origin directly:
python scripts/smoke-test.py --base-url=https://sdtunatracker.github.io
```

## CI pipeline overview

**Cloudflare Pages** is the production host for thetunatracker.com. It
deploys automatically from every push to `main` with no build step — raw
`web/` files are served as-is (Babel handles JSX in the browser).

**GitHub Actions** (`deploy-pages.yml`) runs separately and deploys the
esbuild-compiled version to GitHub Pages (`sdtunatracker.github.io`) for
performance validation. On every push it also:
1. Compiles `web/*.jsx` → `web/dist/*.js` via esbuild
2. Patches `web/index.html` — removes Babel CDN, rewrites `.jsx` refs to `dist/*.js`, stamps `?v=` strings
3. Injects `<meta name="build-time">` and `<meta name="build-commit">` for deployment tracing
4. Purges Cloudflare edge cache (requires `CLOUDFLARE_ZONE_ID` + `CLOUDFLARE_API_TOKEN` secrets)
5. Polls Cloudflare Pages API to verify the CF Pages build succeeded (requires `CLOUDFLARE_ACCOUNT_ID` secret)
6. Runs a smoke test against thetunatracker.com

## Deployment failure modes & diagnostics

### File too large for Cloudflare Pages
- **Symptom:** CF Pages build fails with `"Pages only supports files up to 25 MiB"`
- **Most likely cause:** `web/data.js` grew beyond 25 MiB — happens as the DB accumulates more trips
- **Fix:** `python -m src.main --export-only` re-runs the export with all size reductions
- **Prevention:** pre-commit hook (`scripts/verify-deploy.py`) blocks commits with files > 24 MiB;
  `src/export.py` raises immediately if data.js exceeds 24 MiB after export

### Stale content on thetunatracker.com
- **Symptom:** new commits pushed, old features still visible in browser
- **First check:** Cloudflare Pages dashboard → sd-sport-fishing → Deployments —
  are recent commits marked "Failed" (red)?
- **Diagnose:**
  ```powershell
  curl -A "Mozilla/5.0" https://thetunatracker.com/ | grep build-commit
  ```
  If no `build-commit` tag, CF Pages has no build step (expected).
  If Babel + old version strings appear, a recent CF Pages build failed.
- **Fix:** Resolve the build error, push a new commit, or manually retry the
  deployment in the Cloudflare Pages dashboard

### How to verify thetunatracker.com is up to date
1. Open thetunatracker.com in Incognito
2. F12 → Console:
   ```javascript
   // Check for known-recent feature (e.g. Charts tab, Co-Captain)
   document.querySelector('nav').textContent  // should include "Charts"
   ```
3. Run the smoke test:
   ```powershell
   python scripts/smoke-test.py
   ```

### Cloudflare Pages dashboard
- URL: `https://dash.cloudflare.com/` → Workers & Pages → sd-sport-fishing
- Build settings: Settings → Builds & deployments
  - Build command: *(empty — no build step)*
  - Build output directory: `web`
- Enable email alerts: Settings → Notifications → "Deployment Failed"

### Required GitHub Actions secrets
| Secret | Purpose |
|---|---|
| `CLOUDFLARE_ZONE_ID` | Cache purge after GitHub Pages deploy |
| `CLOUDFLARE_API_TOKEN` | Cache purge + CF Pages status polling |
| `CLOUDFLARE_ACCOUNT_ID` | CF Pages build status verification |

## Security

**Never commit `.env`** — it contains `ANTHROPIC_API_KEY`. It is gitignored,
but double-check before committing new files in the project root.
