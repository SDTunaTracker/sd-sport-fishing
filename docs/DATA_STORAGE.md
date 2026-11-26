# Private data storage (Cloudflare R2)

The GitHub repo `SDTunaTracker/sd-sport-fishing` is **public**, so anything committed is
published. The databases used to be committed. They now live in a **private Cloudflare
R2 bucket**. Only public outputs (the website files) are committed.

## What moves, and why

| File | Size | Written by | Why it's private |
|---|---|---|---|
| `tracker.db` | ~46 MB | `daily-scrape.yml` (hourly) | review submissions with `ip_hash` and pending reviews, scrape logs, job/host records, alert state; everything the site is built from |
| `data/paddies.db` | ~3 MB | `paddies.yml` (every 3 h) | **full text of BloodyDecks forum posts with author names** (third-party content) |
| `data/ais-discoveries.json` | ~2 MB | `ais-discovery.yml` (twice daily) | last positions of every vessel aisstream saw (~5,800), not just ours |

These stay in git because they're public by design:
- `web/data.js`, `web/data-region-*.js`, `web/api/v1/*.json`, `web/sd/**`, `web/sitemap.xml`, `web/sst_grid.json`
- `web/ais_positions.json` (our boats' current positions; see the note at the end)
- `data/paddies_ingest_state.json` (fetch cursor)
- `data/vessel_mmsi.json`, `data/boat-mmsi*.json`

The owner dashboard data (`SD.ADMIN`) is already out of `data.js`: it goes to
`build/admin.json` and is pushed to the analytics Worker behind Cloudflare Access (PR #5).

Readers of the private files:
- the three workflows above (paddies reads `tracker.db` read-only)
- every `src/`, `scraper/`, `forecast/` and `scripts/` tool, which still read the same local paths
- the laptop's scheduled tasks (`run-daily.ps1`, `run-full.ps1`, the forecast shadow task)

The code is unchanged: jobs download the files before running and upload them after.

## How it works (`scripts/r2db.py`)

- **pull** downloads the object and records its ETag in `.r2-state.json` (gitignored).
- **push** uploads with `If-Match: <that ETag>`. If anything else wrote the object since the pull, R2 answers 412 and the job fails (exit 3) instead of overwriting. The public outputs from that run are not committed either.
- Each workflow also has a `concurrency:` group, so runs of one workflow never overlap.
- **Guards before every upload:** SQLite `integrity_check`, a WAL checkpoint, and a refusal to replace the remote file with one less than half its size (a fresh empty DB from a job that failed to pull). `--force` overrides the size guard only.
- **Backups:** every push also writes `backups/<key>/<UTC date>.<ext>` (one per day) and deletes backups older than 30 days.
- **Not configured** (no R2 secrets): every command is a no-op and the workflows use the repo copy, exactly as before. So the PR can merge before setup.
- **After the cutover,** a job that finds neither R2 nor a local DB fails rather than starting from an empty database.

## Owner setup (one time, about 10 minutes)

### 1. Create the bucket
1. Sign in at https://dash.cloudflare.com and pick the account that hosts thetunatracker.com.
2. Left sidebar: **R2 Object Storage**. If it's your first time, click **Get started / Enable R2**. Cloudflare asks for a payment method even on the free plan; nothing is charged within the free tier.
3. Click **Create bucket**.
   - Bucket name: `tunatracker-private`
   - Location: **Automatic**. Default storage class: **Standard**.
   - Click **Create bucket**.
4. In the bucket's **Settings**, leave **Public access** off: no r2.dev subdomain and no custom domain.

### 2. Create an API token for just that bucket
1. Go back to **R2 Object Storage** (overview). On the right, under **Account details**, note the **Account ID**. You can also find it in the S3 endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
2. Click **Manage API tokens** (also labelled "API" > "Manage R2 API Tokens"), then **Create API token**. Choose the **Account API token** type if asked.
   - Token name: `github-actions-tunatracker`
   - Permissions: **Object Read & Write**
   - Specify bucket(s): **Apply to specific buckets only** > `tunatracker-private`
   - TTL: **Forever**. Client IP filtering: none.
   - Click **Create API Token**.
3. Copy the **Access Key ID** and **Secret Access Key** now; the secret is shown only once. Ignore the "Token value". These are passwords: paste them only into the GitHub and `.env` fields below, never into chat or a file in the repo.

### 3. Add them to GitHub
This is step 1 of the cutover below; read that section first.
1. Open https://github.com/SDTunaTracker/sd-sport-fishing > **Settings** > **Secrets and variables** > **Actions**.
2. Click **New repository secret** four times:

| Name | Value |
|---|---|
| `R2_ACCOUNT_ID` | the Account ID |
| `R2_ACCESS_KEY_ID` | the Access Key ID |
| `R2_SECRET_ACCESS_KEY` | the Secret Access Key |
| `R2_BUCKET` | `tunatracker-private` |

### 4. Add them to the laptop
In the gitignored `.env` at the repo root, add the same four lines (`R2_ACCOUNT_ID=...` and so on), typed by you.

**Cost:** the R2 free tier covers 10 GB-month of storage, 1M writes, 10M reads and free egress per month. Our files total about 50 MB; with 30 daily backups that's about 2 GB, and about 5k writes a month. Expected cost is $0.

## Cutover

Do these steps in order. Each one is safe to stop after.

0. **Merge the R2 PR.** Nothing changes yet: without the secrets the workflows behave exactly as before.
1. **Add the four GitHub secrets** (setup step 3). From now on, each workflow run stops at "Pull private data from R2", because the bucket is still empty. That's intended: no run can commit a newer `tracker.db` while you seed, so nothing is lost. Do steps 2–3 promptly, since hourly data is not collected while runs stop.
2. **Seed R2 from the latest committed files** on the laptop (with `.env` filled in):
   ```powershell
   git fetch origin
   git checkout origin/main -- tracker.db data/paddies.db data/ais-discoveries.json
   .venv\Scripts\python.exe scripts\r2db.py seed tracker.db data/paddies.db data/ais-discoveries.json
   .venv\Scripts\python.exe scripts\r2db.py status
   ```
   `seed` refuses to overwrite an object that already exists. The `git checkout` replaces your local `tracker.db` with production's; `scripts\db.ps1 pull` makes a backup first if you want to keep the old one.
3. **Run each workflow once.** Go to GitHub > **Actions**, pick **Daily Scrape** > **Run workflow** (mode `full`), then **Paddies** and **AIS Vessel Discovery**. Check:
   - The log shows `pull tracker.db: … bytes, etag …`, then `push tracker.db: …`.
   - The "Scrape:" commit no longer includes `tracker.db`.
   - `scripts\r2db.py status` shows a newer LastModified.
   - thetunatracker.com shows the new scrape time.
4. **Stop tracking the files in git** (the second PR, opened only after step 3 passes):
   ```
   git rm --cached tracker.db data/paddies.db data/ais-discoveries.json
   ```
   Add them to `.gitignore`. Then tell every session that `tracker.db` comes from `scripts\db.ps1 pull`.

### Rollback
- **Before step 4:**
  1. Run `scripts\db.ps1 pull` to get the newest data.
  2. Commit `tracker.db` (and the others) and push.
  3. Delete the four GitHub secrets.

  The workflows then use the repo copy again.
- **After step 4:** revert the untrack commit first, then do the same three steps.
- **If a bad DB was pushed:** download a daily copy from `backups/db/tracker.db/` in the R2 dashboard, put it in place locally, then run `r2db.py pull` (to take the lock) and `r2db.py push --force`. Do this between the hourly runs.
- **A job failing with "R2 lock" (exit 3)** means another writer pushed in between. Re-run the job; it starts from the newer copy.

## Local development
```powershell
scripts\db.ps1 status
scripts\db.ps1 pull                  # tracker.db; backs up your local copy first
scripts\db.ps1 pull data/paddies.db
scripts\db.ps1 push                  # deliberate local backfills only
```
GitHub Actions is the normal writer of `tracker.db`. If you push from the laptop:
- pull right before,
- do it between the hourly runs (they start about :37 past the hour),
- expect exit 3 if a run wrote in the meantime. Pull again and redo the backfill.

The laptop's own scheduled scrapes (Task Scheduler) keep writing the laptop's local copy. They never push. It's the same separate copy as today, used for alerts and testing.

## Old copies in git history

Removing the files from the latest commit does **not** remove them from history. Anyone can still check out an old commit. What's there today:

| File | Versions in history | Since | Sensitive contents |
|---|---|---|---|
| `tracker.db` | 1,423 | 2026-05-21 | Mostly public data: fish counts, schedules, conditions. Also scrape logs and CI runner host names. One review, approved and public, with no `ip_hash`. |
| `data/paddies.db` | 7 | Nov 2026 | **Full BloodyDecks forum posts and author names** |
| `data/ais-discoveries.json` | 314 | 2026 | Last-seen positions of ~5,800 vessels |

The repo's packed history is about 200 MB, mostly these files.

**Options:**
1. **Leave history as is (recommended for now).** The data is stale and much of it was public anyway. Nothing breaks.
2. **Rewrite history** with `git filter-repo --path tracker.db --path data/paddies.db --path data/ais-discoveries.json --invert-paths`, then force-push `main`.
   - This removes the files and shrinks the repo, but it is **destructive**: every commit hash changes, every clone, agent worktree and branch must be re-cloned or rebased, and open PRs (#5, #6, #7 and the agent branches) break.
   - GitHub may keep cached views of old commits until GitHub Support purges them, and existing forks keep their copies.
   - If you want it, do it once at a quiet moment with no open PRs, and only if BloodyDecks or a user asks for removal, or the repo size becomes a problem.

## Notes for the owner
- **`web/ais_positions.json` is public today.** It holds our boats' current positions from aisstream, whose terms are unclear (the `/terms` page returns 404). The private archive rule covers historical tracks. This live file is an existing site feature, so whether to keep publishing it is your call.
- **CLAUDE.md** still says `tracker.db` and `data.js` are gitignored. That was wrong before this change, and `tracker.db` only becomes gitignored at step 4. Suggested text is in the PR description. I haven't edited CLAUDE.md because the request came through another agent.
