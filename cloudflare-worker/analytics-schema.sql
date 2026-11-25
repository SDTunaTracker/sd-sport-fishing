-- Tunatracker first-party analytics (D1 database "tt_analytics").
-- Apply with:
--   npx wrangler d1 execute tt_analytics --remote --file cloudflare-worker/analytics-schema.sql
--     --config cloudflare-worker/analytics-wrangler.toml
-- Every statement is idempotent, so re-running is safe.
--
-- PRIVACY: no cookies, no raw IP addresses, no user agents and no account ids
-- are stored. `vh` is a truncated SHA-256 of (daily salt | ip | user agent | host).
-- The salt is random per Pacific day and deleted after 2 days, so a vh can't be
-- recomputed from an IP or linked across days.

-- Raw events, kept 90 days (deleted by the daily cron).
CREATE TABLE IF NOT EXISTS events (
  ts      INTEGER NOT NULL,       -- ms since epoch (server clock)
  day     TEXT    NOT NULL,       -- YYYY-MM-DD, America/Los_Angeles
  type    TEXT    NOT NULL,       -- pageview, boat_view, book_click, chat_*, signup
  path    TEXT,                   -- pathname only (no query or hash)
  entry   INTEGER NOT NULL DEFAULT 0, -- 1 = first pageview of a page load
  ref     TEXT,                   -- referrer host or "utm:<source>", '' = direct (entry only)
  dev     TEXT,                   -- mobile, tablet or desktop
  os      TEXT,                   -- iOS, Android, Windows, macOS, Linux, Other
  br      TEXT,                   -- Chrome, Safari, Firefox, Edge, Samsung, Other
  cc      TEXT,                   -- ISO country (Cloudflare)
  src     TEXT,                   -- web, pwa or app
  boat    TEXT,                   -- public catalog data
  landing TEXT,
  trip    TEXT,
  kind    TEXT,                   -- e.g. planner, chat_card, chat_link
  g       INTEGER,                -- first visit of the day: days since previous visit (400 = new)
  vh      TEXT    NOT NULL        -- daily visitor hash (see header)
);
CREATE INDEX IF NOT EXISTS idx_events_day ON events(day);
CREATE INDEX IF NOT EXISTS idx_events_ts  ON events(ts);

-- One random salt per day. Rows older than 2 days are deleted.
CREATE TABLE IF NOT EXISTS salts (
  day  TEXT PRIMARY KEY,
  salt TEXT NOT NULL
);

-- Daily rollups, kept indefinitely. No visitor hashes.
-- dim: total, path, ref, dev, os, br, cc, src, type, boat, book_boat
CREATE TABLE IF NOT EXISTS rollup (
  day TEXT NOT NULL, dim TEXT NOT NULL, key TEXT NOT NULL,
  pv INTEGER NOT NULL DEFAULT 0,  -- pageviews (or events for type/boat dims)
  uv INTEGER NOT NULL DEFAULT 0,  -- distinct daily visitors (hash method)
  PRIMARY KEY (day, dim, key)
);

-- Histogram of "days since previous visit" for first-visits-of-the-day.
-- Unique visitors for any range [from, to] = SUM(n) WHERE day IN range
-- AND gap > day - from. A visitor counts once: on their first visit in the range.
CREATE TABLE IF NOT EXISTS rollup_gap (
  day TEXT NOT NULL, gap INTEGER NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (day, gap)
);

-- Funnel step counts per day (visitor-days).
CREATE TABLE IF NOT EXISTS rollup_funnel (
  day TEXT NOT NULL, funnel TEXT NOT NULL, step INTEGER NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (day, funnel, step)
);

-- Which days have been rolled up; final = 1 once the day is over.
CREATE TABLE IF NOT EXISTS rolled_days (
  day TEXT PRIMARY KEY, at INTEGER NOT NULL, final INTEGER NOT NULL DEFAULT 0
);

-- Owner admin payload (scrape health, backtests, review queue), pushed by the
-- daily scrape workflow so it never ships in the public data.js.
CREATE TABLE IF NOT EXISTS admin_blob (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  json TEXT NOT NULL,
  at INTEGER NOT NULL
);
