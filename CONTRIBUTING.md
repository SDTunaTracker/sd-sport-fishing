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

On every push to `main`, GitHub Actions:
1. Compiles `web/*.jsx` → `web/dist/*.js` via esbuild
2. Patches `web/index.html` — removes Babel CDN, rewrites `.jsx` refs to `dist/*.js`, stamps `?v=` strings
3. Injects `<meta name="build-time">` and `<meta name="build-commit">` for deployment tracing
4. Uploads `web/` and deploys to GitHub Pages
5. Runs a smoke test against thetunatracker.com (non-blocking — `continue-on-error: true`)

## Security

**Never commit `.env`** — it contains `ANTHROPIC_API_KEY`. It is gitignored,
but double-check before committing new files in the project root.
