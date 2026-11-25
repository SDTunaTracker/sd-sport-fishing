// Tunatracker first-party analytics Worker.
//
// Routes (see analytics-wrangler.toml):
//   POST thetunatracker.com/a/e            public collector (sendBeacon from TTTrack)
//   POST thetunatracker.com/a/admin        scrape workflow pushes the admin payload (bearer token)
//   GET  thetunatracker.com/owner/api/*    owner stats API, behind Cloudflare Access
//
// Privacy, matching web/privacy/index.html:
//   - No cookies, no raw IP addresses, no user agents and no account ids are stored.
//   - Visitors are counted with a daily-rotating salted hash (vh). The salt is random
//     per Pacific day and deleted after 2 days, so a hash can't be reversed or linked
//     across days.
//   - Multi-day unique visitors come from `g` ("days since your previous visit"),
//     computed in the browser from one stored date (localStorage tt_seen).
//   - Do Not Track / Global Privacy Control: the browser sends nothing, and this
//     Worker drops anything that arrives with DNT: 1 or Sec-GPC: 1 anyway.
//   - Raw events are deleted after 90 days. Daily rollups contain no hashes.
//
// The owner API fails closed: it verifies the Cloudflare Access JWT itself
// (signature, audience, expiry, and optional email allow-list), so removing the
// Access application never exposes data.

const EVENT_TYPES = new Set([
  'pageview', 'boat_view', 'book_click', 'signup',
  'chat_open', 'chat_message', 'chat_recommend', 'chat_book_intent', 'chat_book_click',
]);
const SOURCES = new Set(['web', 'pwa', 'app']);
const MAX_BODY = 16 * 1024;
const MAX_EVENTS = 25;
const MAX_ADMIN_BODY = 1500 * 1024;
const BOT_RE = /bot|crawl|spider|slurp|headless|lighthouse|pagespeed|preview|facebookexternalhit|embedly|quora link|whatsapp|telegram|discord|curl|wget|python|httpclient|go-http|axios|node-fetch|monitor|uptime|pingdom/i;
// (okhttp is deliberately absent: React Native / Expo on Android sends it.)
const RANGES = { today: 1, '7d': 7, '30d': 30, '90d': 90, '12m': 365 };
const TODAY_REROLL_MS = 5 * 60 * 1000;

// ─── Small utilities ─────────────────────────────────────────────────────────

const _fmt = new Map();
export function dayOf(ms, tz) {
  tz = tz || 'America/Los_Angeles';
  let f = _fmt.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' });
    _fmt.set(tz, f);
  }
  return f.format(new Date(ms));
}

export function addDays(day, n) {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

function daysBetween(a, b) {
  const p = s => { const [y, m, d] = s.split('-').map(Number); return Date.UTC(y, m - 1, d); };
  return Math.round((p(b) - p(a)) / 864e5);
}

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'private, no-store', ...extra },
  });
}

function noContent() {
  return new Response(null, { status: 204, headers: { 'Cache-Control': 'no-store' } });
}

function clean(v, max) {
  if (v == null) return null;
  const s = String(v).replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, max);
  return s || null;
}

// "/sd/boat/Pacific%20Queen/?x=1#y" → "/sd/boat/pacific-queen"
export function normalizePath(p) {
  if (typeof p !== 'string' || p[0] !== '/') return null;
  p = p.split(/[?#]/)[0];
  try { p = decodeURIComponent(p); } catch (e) { /* keep raw */ }
  p = p.toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9/._-]+/g, '-').replace(/-+/g, '-').replace(/\/+/g, '/');
  if (p.length > 1) p = p.replace(/\/$/, '');
  return p.slice(0, 160) || '/';
}

export function normalizeRef(r, allowedHosts) {
  if (r == null) return null;
  r = String(r).trim();
  if (r === '') return '';
  if (r.startsWith('utm:')) return 'utm:' + (clean(r.slice(4).toLowerCase(), 48) || '?');
  let host = r;
  try { host = new URL(r.includes('://') ? r : 'https://' + r).hostname; } catch (e) { return '?'; }
  host = host.toLowerCase().replace(/^www\./, '').replace(/^m\./, '');
  if (allowedHosts.some(h => h.replace(/^www\./, '') === host)) return '';
  if (/^(android-app:|com\.google\.android)/.test(r)) return 'google.com';
  return host.slice(0, 64);
}

export function parseUA(ua) {
  ua = ua || '';
  let os = 'Other';
  if (/iPhone|iPad|iPod/.test(ua)) os = 'iOS';
  else if (/Android/.test(ua)) os = 'Android';
  else if (/Windows/.test(ua)) os = 'Windows';
  else if (/Mac OS X|Macintosh/.test(ua)) os = 'macOS';
  else if (/CrOS/.test(ua)) os = 'ChromeOS';
  else if (/Linux/.test(ua)) os = 'Linux';
  let br = 'Other';
  if (/SamsungBrowser/.test(ua)) br = 'Samsung';
  else if (/Edg\//.test(ua)) br = 'Edge';
  else if (/Firefox|FxiOS/.test(ua)) br = 'Firefox';
  else if (/CriOS|Chrome\//.test(ua)) br = 'Chrome';
  else if (/Safari\//.test(ua)) br = 'Safari';
  else if (/Expo|okhttp|CFNetwork/.test(ua)) br = 'App';
  return { os, br };
}

export function deviceOf(width, ua) {
  const w = Number(width);
  if (w > 0) return w < 768 ? 'mobile' : w < 1100 ? 'tablet' : 'desktop';
  if (/iPad|Tablet/.test(ua || '') || (/Android/.test(ua || '') && !/Mobile/.test(ua || ''))) return 'tablet';
  if (/Mobi|iPhone|Android/.test(ua || '')) return 'mobile';
  return 'desktop';
}

function hostsOf(env) {
  return String(env.ALLOWED_HOSTS || 'thetunatracker.com,www.thetunatracker.com')
    .split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}

function hex(buf) {
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

async function sha256Hex(s) {
  return hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
}

function timingSafeEqual(a, b) {
  a = String(a || ''); b = String(b || '');
  if (!a || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

// ─── Daily salt ──────────────────────────────────────────────────────────────

const _salt = { day: null, salt: null };
export function _resetSaltCache() { _salt.day = null; _salt.salt = null; }

async function getSalt(db, day) {
  if (_salt.day === day && _salt.salt) return _salt.salt;
  const fresh = hex(crypto.getRandomValues(new Uint8Array(16)));
  await db.prepare('INSERT OR IGNORE INTO salts(day, salt) VALUES (?1, ?2)').bind(day, fresh).run();
  const row = await db.prepare('SELECT salt FROM salts WHERE day = ?1').bind(day).first();
  _salt.day = day; _salt.salt = row.salt;
  return row.salt;
}

// ─── Collector ───────────────────────────────────────────────────────────────

export async function collect(req, env) {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });
  if (!env.DB) return noContent();
  const h = req.headers;
  if (h.get('DNT') === '1' || h.get('Sec-GPC') === '1') return noContent();
  const ua = h.get('User-Agent') || '';
  if (!ua || BOT_RE.test(ua)) return noContent();

  const len = Number(h.get('Content-Length') || 0);
  if (len > MAX_BODY) return noContent();
  let body;
  try {
    const text = await req.text();
    if (text.length > MAX_BODY) return noContent();
    body = JSON.parse(text);
  } catch (e) { return noContent(); }
  if (!body || !Array.isArray(body.ev) || body.ev.length === 0) return noContent();

  const src = SOURCES.has(body.src) ? body.src : 'web';
  const hosts = hostsOf(env);
  const origin = h.get('Origin');
  if (origin) {
    let oh = '';
    try { oh = new URL(origin).hostname.toLowerCase(); } catch (e) { /* invalid */ }
    if (!hosts.includes(oh)) return noContent();
  } else if (src !== 'app') {
    return noContent();
  }

  const now = Date.now();
  const tz = env.TZ_NAME || 'America/Los_Angeles';
  const day = dayOf(now, tz);
  const ip = h.get('CF-Connecting-IP') || '';
  const salt = await getSalt(env.DB, day);
  const vh = (await sha256Hex(`${salt}|${ip}|${ua}|${src === 'app' ? 'app' : hosts[0]}`)).slice(0, 16);
  const { os, br } = parseUA(ua);
  const dev = deviceOf(body.w, ua);
  const cc = clean((req.cf && req.cf.country) || h.get('CF-IPCountry'), 2) || 'XX';

  const stmt = env.DB.prepare(
    'INSERT INTO events (ts, day, type, path, entry, ref, dev, os, br, cc, src, boat, landing, trip, kind, g, vh)' +
    ' VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17)'
  );
  const rows = [];
  for (const e of body.ev.slice(0, MAX_EVENTS)) {
    if (!e || !EVENT_TYPES.has(e.t)) continue;
    const isPv = e.t === 'pageview';
    const entry = isPv && e.e === 1 ? 1 : 0;
    let g = null;
    if (isPv && e.g != null) {
      const gi = Math.floor(Number(e.g));
      if (gi >= 1) g = Math.min(gi, 400);
    }
    rows.push(stmt.bind(
      now, day, e.t, normalizePath(e.p), entry,
      entry ? normalizeRef(e.r == null ? '' : e.r, hosts) : null,
      dev, os, br, cc, src,
      clean(e.boat, 80), clean(e.landing, 60), clean(e.trip, 60), clean(e.k, 24),
      g, vh,
    ));
  }
  if (rows.length) await env.DB.batch(rows);
  return noContent();
}

// ─── Admin payload ingest (scrape workflow) ─────────────────────────────────

export async function ingestAdmin(req, env) {
  if (req.method !== 'POST') return new Response('Method not allowed', { status: 405 });
  if (!env.ADMIN_INGEST_TOKEN || !env.DB) return json({ error: 'not configured' }, 503);
  const auth = req.headers.get('Authorization') || '';
  if (!timingSafeEqual(auth.replace(/^Bearer\s+/i, ''), env.ADMIN_INGEST_TOKEN)) return json({ error: 'unauthorized' }, 401);
  const text = await req.text();
  if (text.length > MAX_ADMIN_BODY) return json({ error: 'too large' }, 413);
  try { JSON.parse(text); } catch (e) { return json({ error: 'invalid json' }, 400); }
  await env.DB.prepare('INSERT OR REPLACE INTO admin_blob (id, json, at) VALUES (1, ?1, ?2)').bind(text, Date.now()).run();
  return json({ ok: true, bytes: text.length });
}

// ─── Cloudflare Access verification ──────────────────────────────────────────

const _certs = { team: null, at: 0, keys: null };
export function _resetCertCache() { _certs.team = null; _certs.at = 0; _certs.keys = null; }

function teamHost(v) {
  v = String(v || '').trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
  if (!v) return '';
  return v.includes('.') ? v : `${v}.cloudflareaccess.com`;
}

function b64urlBytes(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function accessKeys(team, force) {
  if (!force && _certs.keys && _certs.team === team && Date.now() - _certs.at < 3600e3) return _certs.keys;
  const r = await fetch(`https://${team}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error('certs ' + r.status);
  const j = await r.json();
  _certs.team = team; _certs.at = Date.now(); _certs.keys = j.keys || [];
  return _certs.keys;
}

export async function verifyAccess(req, env) {
  const team = teamHost(env.ACCESS_TEAM_DOMAIN);
  const aud = String(env.ACCESS_AUD || '').trim();
  if (!team || !aud) return { ok: false, status: 503, error: 'Cloudflare Access is not configured for this Worker' };
  const tok = req.headers.get('Cf-Access-Jwt-Assertion');
  if (!tok) return { ok: false, status: 401, error: 'missing access token' };
  const parts = tok.split('.');
  if (parts.length !== 3) return { ok: false, status: 401, error: 'malformed token' };
  let header, payload;
  try {
    const dec = new TextDecoder();
    header = JSON.parse(dec.decode(b64urlBytes(parts[0])));
    payload = JSON.parse(dec.decode(b64urlBytes(parts[1])));
  } catch (e) { return { ok: false, status: 401, error: 'malformed token' }; }
  if (header.alg !== 'RS256') return { ok: false, status: 401, error: 'bad alg' };

  let keys = await accessKeys(team, false);
  let jwk = keys.find(k => k.kid === header.kid);
  if (!jwk) { keys = await accessKeys(team, true); jwk = keys.find(k => k.kid === header.kid); }
  if (!jwk) return { ok: false, status: 401, error: 'unknown key' };

  const key = await crypto.subtle.importKey('jwk', { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: 'RS256', ext: true },
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const valid = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64urlBytes(parts[2]),
    new TextEncoder().encode(parts[0] + '.' + parts[1]));
  if (!valid) return { ok: false, status: 401, error: 'bad signature' };

  const now = Date.now() / 1000;
  const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!auds.includes(aud)) return { ok: false, status: 403, error: 'wrong audience' };
  if (!payload.exp || payload.exp < now) return { ok: false, status: 401, error: 'expired' };
  if (payload.nbf && payload.nbf > now + 60) return { ok: false, status: 401, error: 'not yet valid' };
  if (payload.iss && payload.iss !== `https://${team}`) return { ok: false, status: 401, error: 'wrong issuer' };
  const allow = String(env.OWNER_EMAILS || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  if (allow.length && !allow.includes(String(payload.email || '').toLowerCase())) {
    return { ok: false, status: 403, error: 'not an owner' };
  }
  return { ok: true, email: payload.email || null };
}

// ─── Rollups ─────────────────────────────────────────────────────────────────

const DIM_COLS = ['dev', 'os', 'br', 'cc', 'src'];

export function rollupStatements(db, day, final) {
  const s = [];
  const p = sql => db.prepare(sql);
  s.push(p('DELETE FROM rollup WHERE day = ?1').bind(day));
  s.push(p(`INSERT INTO rollup (day, dim, key, pv, uv)
    SELECT ?1, 'total', '', COALESCE(SUM(type = 'pageview'), 0), COUNT(DISTINCT vh)
    FROM events WHERE day = ?1 HAVING COUNT(*) > 0`).bind(day));
  s.push(p(`INSERT INTO rollup (day, dim, key, pv, uv)
    SELECT ?1, 'path', COALESCE(path, '?'), COUNT(*), COUNT(DISTINCT vh)
    FROM events WHERE day = ?1 AND type = 'pageview' GROUP BY COALESCE(path, '?')`).bind(day));
  s.push(p(`INSERT INTO rollup (day, dim, key, pv, uv)
    SELECT ?1, 'ref', COALESCE(ref, ''), COUNT(*), COUNT(DISTINCT vh)
    FROM events WHERE day = ?1 AND type = 'pageview' AND entry = 1 GROUP BY COALESCE(ref, '')`).bind(day));
  for (const c of DIM_COLS) {
    s.push(p(`INSERT INTO rollup (day, dim, key, pv, uv)
      SELECT ?1, '${c}', COALESCE(${c}, '?'), COUNT(*), COUNT(DISTINCT vh)
      FROM events WHERE day = ?1 AND type = 'pageview' GROUP BY COALESCE(${c}, '?')`).bind(day));
  }
  s.push(p(`INSERT INTO rollup (day, dim, key, pv, uv)
    SELECT ?1, 'type', type, COUNT(*), COUNT(DISTINCT vh)
    FROM events WHERE day = ?1 GROUP BY type`).bind(day));
  s.push(p(`INSERT INTO rollup (day, dim, key, pv, uv)
    SELECT ?1, 'boat', boat, COUNT(*), COUNT(DISTINCT vh)
    FROM events WHERE day = ?1 AND type = 'boat_view' AND boat IS NOT NULL GROUP BY boat`).bind(day));
  s.push(p(`INSERT INTO rollup (day, dim, key, pv, uv)
    SELECT ?1, 'book_boat', boat, COUNT(*), COUNT(DISTINCT vh)
    FROM events WHERE day = ?1 AND type IN ('book_click', 'chat_book_click') AND boat IS NOT NULL GROUP BY boat`).bind(day));
  s.push(p('DELETE FROM rollup_gap WHERE day = ?1').bind(day));
  s.push(p(`INSERT INTO rollup_gap (day, gap, n)
    SELECT ?1, g, COUNT(*) FROM events WHERE day = ?1 AND g IS NOT NULL GROUP BY g`).bind(day));
  s.push(p('DELETE FROM rollup_funnel WHERE day = ?1').bind(day));
  s.push(p(`WITH v AS (
      SELECT vh,
        MAX(type = 'pageview') AS s1,
        MAX(type = 'boat_view' OR (type = 'pageview' AND (path LIKE '%/boat/%' OR path LIKE '%/tripplanner%'))) AS s2,
        MAX(type IN ('book_click', 'chat_book_click')) AS s3,
        MAX(type IN ('chat_open', 'chat_message')) AS c1,
        MAX(type = 'chat_message') AS c2,
        MAX(type = 'chat_book_click') AS c3
      FROM events WHERE day = ?1 GROUP BY vh)
    INSERT INTO rollup_funnel (day, funnel, step, n)
    SELECT ?1, 'site', 1, COALESCE(SUM(s1), 0) FROM v
    UNION ALL SELECT ?1, 'site', 2, COALESCE(SUM(s1 * s2), 0) FROM v
    UNION ALL SELECT ?1, 'site', 3, COALESCE(SUM(s1 * s2 * s3), 0) FROM v
    UNION ALL SELECT ?1, 'chat', 1, COALESCE(SUM(c1), 0) FROM v
    UNION ALL SELECT ?1, 'chat', 2, COALESCE(SUM(c1 * c2), 0) FROM v
    UNION ALL SELECT ?1, 'chat', 3, COALESCE(SUM(c1 * c3), 0) FROM v`).bind(day));
  s.push(p('INSERT OR REPLACE INTO rolled_days (day, at, final) VALUES (?1, ?2, ?3)').bind(day, Date.now(), final ? 1 : 0));
  return s;
}

export async function rollupDay(db, day, final) {
  await db.batch(rollupStatements(db, day, final));
}

// Roll several days per db.batch(). On Workers Free a batch counts as one of the
// 50 D1 queries allowed per invocation, so 90 days costs 9 queries, not 90.
const DAYS_PER_BATCH = 10;
async function rollupDays(db, list) {
  for (let i = 0; i < list.length; i += DAYS_PER_BATCH) {
    const stmts = [];
    for (const [day, final] of list.slice(i, i + DAYS_PER_BATCH)) stmts.push(...rollupStatements(db, day, final));
    await db.batch(stmts);
  }
}

// Make sure every day in [from, to] has an up-to-date rollup.
// Past days are rolled once and marked final. Today is re-rolled at most every 5 minutes.
export async function ensureRolled(db, from, to, today) {
  const rolled = await db.prepare('SELECT day, at, final FROM rolled_days WHERE day BETWEEN ?1 AND ?2')
    .bind(from, to).all();
  const byDay = new Map((rolled.results || []).map(r => [r.day, r]));
  const pending = [];
  for (let d = from; d <= to; d = addDays(d, 1)) {
    const r = byDay.get(d);
    if (r && r.final) continue;
    if (d === today) {
      if (!r || Date.now() - r.at > TODAY_REROLL_MS) pending.push(d);
    } else if (d < today) {
      pending.push(d);
    }
  }
  if (!pending.length) return;
  const past = pending.filter(d => d < today);
  const hasEvents = new Set();
  if (past.length) {
    const checks = past.map(d => db.prepare('SELECT ?1 AS day FROM events WHERE day = ?1 LIMIT 1').bind(d));
    const res = await db.batch(checks);
    res.forEach(r => (r.results || []).forEach(x => hasEvents.add(x.day)));
    const empty = past.filter(d => !hasEvents.has(d));
    if (empty.length) {
      await db.batch(empty.map(d =>
        db.prepare('INSERT OR REPLACE INTO rolled_days (day, at, final) VALUES (?1, ?2, 1)').bind(d, Date.now())));
    }
  }
  const work = [];
  for (const d of pending) {
    if (d === today) work.push([d, false]);
    else if (hasEvents.has(d)) work.push([d, true]);
  }
  await rollupDays(db, work);
}

// ─── Stats ───────────────────────────────────────────────────────────────────

function rangeBounds(range, today) {
  const n = RANGES[range] || 7;
  const to = today;
  const from = addDays(today, -(n - 1));
  return { from, to, days: n, prevFrom: addDays(from, -n), prevTo: addDays(from, -1) };
}

async function periodStats(db, from, to) {
  const q = (sql, ...b) => db.prepare(sql).bind(...b);
  const [totals, gaps, uniq, types, funnel] = await db.batch([
    q(`SELECT day, pv, uv FROM rollup WHERE dim = 'total' AND day BETWEEN ?1 AND ?2`, from, to),
    q(`SELECT day, SUM(n) AS n FROM rollup_gap WHERE day BETWEEN ?1 AND ?2 GROUP BY day`, from, to),
    q(`SELECT COALESCE(SUM(n), 0) AS n FROM rollup_gap
       WHERE day BETWEEN ?1 AND ?2 AND gap > (julianday(day) - julianday(?1))`, from, to),
    q(`SELECT day, key, pv, uv FROM rollup WHERE dim = 'type' AND day BETWEEN ?1 AND ?2`, from, to),
    q(`SELECT funnel, step, SUM(n) AS n FROM rollup_funnel WHERE day BETWEEN ?1 AND ?2 GROUP BY funnel, step`, from, to),
  ]);
  const byDay = {};
  for (let d = from; d <= to; d = addDays(d, 1)) byDay[d] = { day: d, uv: 0, pv: 0, hashUv: 0, book: 0, chat: 0 };
  for (const r of totals.results || []) { if (byDay[r.day]) { byDay[r.day].pv = r.pv; byDay[r.day].hashUv = r.uv; } }
  for (const r of gaps.results || []) { if (byDay[r.day]) byDay[r.day].uv = r.n; }
  let book = 0, chatters = 0, chatMsgs = 0, signups = 0;
  for (const r of types.results || []) {
    const b = byDay[r.day];
    if (r.key === 'book_click' || r.key === 'chat_book_click') { book += r.pv; if (b) b.book += r.pv; }
    if (r.key === 'chat_message') { chatters += r.uv; chatMsgs += r.pv; if (b) b.chat += r.uv; }
    if (r.key === 'signup') signups += r.pv;
  }
  const series = Object.values(byDay);
  const pv = series.reduce((a, b) => a + b.pv, 0);
  const f = { site: [0, 0, 0], chat: [0, 0, 0] };
  for (const r of funnel.results || []) if (f[r.funnel]) f[r.funnel][r.step - 1] = r.n;
  return {
    uv: (uniq.results && uniq.results[0] && uniq.results[0].n) || 0,
    pv, book, chatters, chatMsgs, signups,
    series, funnel: f,
  };
}

async function topDims(db, from, to, prevFrom, prevTo) {
  const dims = { path: 12, boat: 12, book_boat: 10, ref: 12, dev: 4, os: 8, br: 8, cc: 10, src: 3 };
  const stmts = [];
  for (const [dim, lim] of Object.entries(dims)) {
    stmts.push(db.prepare(`SELECT key, SUM(pv) AS pv, SUM(uv) AS uv FROM rollup
      WHERE dim = ?1 AND day BETWEEN ?2 AND ?3 GROUP BY key ORDER BY pv DESC LIMIT ?4`).bind(dim, from, to, lim));
    stmts.push(db.prepare(`SELECT key, SUM(pv) AS pv FROM rollup
      WHERE dim = ?1 AND day BETWEEN ?2 AND ?3 GROUP BY key`).bind(dim, prevFrom, prevTo));
  }
  const res = await db.batch(stmts);
  const out = {};
  Object.keys(dims).forEach((dim, i) => {
    const prev = new Map((res[i * 2 + 1].results || []).map(r => [r.key, r.pv]));
    out[dim] = (res[i * 2].results || []).map(r => ({ key: r.key, pv: r.pv, uv: r.uv, prev: prev.get(r.key) || 0 }));
  });
  return out;
}

export async function buildStats(db, range, tz) {
  const today = dayOf(Date.now(), tz);
  const b = rangeBounds(range, today);
  await ensureRolled(db, b.prevFrom, b.to, today);
  const [cur, prev, top] = await Promise.all([
    periodStats(db, b.from, b.to),
    periodStats(db, b.prevFrom, b.prevTo),
    topDims(db, b.from, b.to, b.prevFrom, b.prevTo),
  ]);
  const first = await db.prepare(`SELECT MIN(d) AS d FROM (
      SELECT MIN(day) AS d FROM events UNION ALL SELECT MIN(day) FROM rollup WHERE dim = 'total')`).first();
  return {
    range: { key: RANGES[range] ? range : '7d', ...b, today, tz },
    current: cur, previous: prev, top,
    collectingSince: first ? first.d : null,
    generatedAt: new Date().toISOString(),
  };
}

export async function buildLive(db, nowMs) {
  const now = nowMs || Date.now();
  const q = (sql, ...b) => db.prepare(sql).bind(...b);
  const [a5, a30, perMin, recent] = await db.batch([
    q('SELECT COUNT(DISTINCT vh) AS n FROM events WHERE ts > ?1', now - 5 * 60e3),
    q('SELECT COUNT(DISTINCT vh) AS n FROM events WHERE ts > ?1', now - 30 * 60e3),
    q(`SELECT CAST((?2 - ts) / 60000 AS INTEGER) AS ago, COUNT(*) AS n FROM events
       WHERE ts > ?1 AND type = 'pageview' GROUP BY ago`, now - 30 * 60e3, now),
    q(`SELECT ts, type, path, boat, cc, dev, src FROM events WHERE ts > ?1 ORDER BY ts DESC LIMIT 20`, now - 24 * 3600e3),
  ]);
  const mins = new Array(30).fill(0);
  for (const r of perMin.results || []) if (r.ago >= 0 && r.ago < 30) mins[29 - r.ago] = r.n;
  return {
    active5: a5.results[0].n, active30: a30.results[0].n,
    perMinute: mins, recent: recent.results || [], now,
  };
}

async function ownerApi(req, env, url) {
  if (req.method !== 'GET') return json({ error: 'method not allowed' }, 405);
  const auth = await verifyAccess(req, env);
  if (!auth.ok) return json({ error: auth.error }, auth.status);
  if (!env.DB) return json({ error: 'D1 binding DB missing' }, 503);
  const tz = env.TZ_NAME || 'America/Los_Angeles';
  const route = url.pathname.replace(/^\/owner\/api\//, '');
  try {
    if (route === 'stats') return json(await buildStats(env.DB, url.searchParams.get('range') || '7d', tz));
    if (route === 'live') return json(await buildLive(env.DB));
    if (route === 'admin') {
      const row = await env.DB.prepare('SELECT json, at FROM admin_blob WHERE id = 1').first();
      if (!row) return json({ error: 'no admin data yet' }, 404);
      return new Response(`{"at":${row.at},"data":${row.json}}`,
        { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'private, no-store' } });
    }
    if (route === 'me') return json({ email: auth.email });
    return json({ error: 'not found' }, 404);
  } catch (e) {
    console.error('owner api', route, e && e.stack || e);
    return json({ error: 'internal error' }, 500);
  }
}

// ─── Daily maintenance (cron) ────────────────────────────────────────────────

export async function maintain(env, nowMs) {
  const db = env.DB;
  const tz = env.TZ_NAME || 'America/Los_Angeles';
  const today = dayOf(nowMs || Date.now(), tz);
  const keep = Number(env.RETENTION_DAYS || 90);
  const open = await db.prepare(`SELECT DISTINCT day FROM events WHERE day < ?1
    AND day NOT IN (SELECT day FROM rolled_days WHERE final = 1)`).bind(today).all();
  await rollupDays(db, (open.results || []).map(r => [r.day, true]));
  await db.batch([
    db.prepare('DELETE FROM events WHERE day < ?1').bind(addDays(today, -keep)),
    db.prepare('DELETE FROM salts WHERE day < ?1').bind(addDays(today, -1)),
  ]);
}

// ─── Entry ───────────────────────────────────────────────────────────────────

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    try {
      if (url.pathname === '/a/e') return await collect(req, env);
      if (url.pathname === '/a/admin') return await ingestAdmin(req, env);
      if (url.pathname.startsWith('/owner/api/')) return await ownerApi(req, env, url);
    } catch (e) {
      console.error('analytics', url.pathname, e && e.stack || e);
      if (url.pathname === '/a/e') return noContent();
      return json({ error: 'internal error' }, 500);
    }
    return new Response('Not found', { status: 404 });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(maintain(env));
  },
};
