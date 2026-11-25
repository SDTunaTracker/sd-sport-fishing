// Tests for cloudflare-worker/analytics.js against a real SQLite (node:sqlite).
// Run: node --test tests/analytics/
import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createD1 } from './d1-shim.mjs';
import worker, {
  normalizePath, normalizeRef, parseUA, deviceOf, dayOf, addDays,
  buildStats, buildLive, maintain, verifyAccess, _resetSaltCache, _resetCertCache,
} from '../../cloudflare-worker/analytics.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const SCHEMA = path.join(here, '..', '..', 'cloudflare-worker', 'analytics-schema.sql');
const UA_IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
const UA_WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';

let env, realNow, clock;
beforeEach(() => {
  env = { DB: createD1(SCHEMA), TZ_NAME: 'America/Los_Angeles' };
  _resetSaltCache();
  _resetCertCache();
  realNow = Date.now;
  clock = Date.parse('2026-11-20T18:00:00Z');
  Date.now = () => clock;
});
afterEach(() => { Date.now = realNow; });

function setDay(day, hourUtc = 18) { clock = Date.parse(`${day}T${String(hourUtc).padStart(2, '0')}:00:00Z`); _resetSaltCache(); }

function beacon(body, { ip = '203.0.113.7', ua = UA_IPHONE, origin = 'https://thetunatracker.com', headers = {} } = {}) {
  const h = { 'Content-Type': 'application/json', 'User-Agent': ua, 'CF-Connecting-IP': ip, 'CF-IPCountry': 'US', ...headers };
  if (origin) h.Origin = origin;
  return worker.fetch(new Request('https://thetunatracker.com/a/e', { method: 'POST', headers: h, body: JSON.stringify(body) }), env);
}
const pv = (p, extra = {}) => ({ t: 'pageview', p, ...extra });
const rows = () => env.DB._raw.prepare('SELECT * FROM events ORDER BY ts').all();

// ─── Normalizers ─────────────────────────────────────────────────────────────

test('normalizePath strips query/hash and slugs', () => {
  assert.equal(normalizePath('/sd/boat/Pacific%20Queen/?x=1#y'), '/sd/boat/pacific-queen');
  assert.equal(normalizePath("/sd/boat/Fisherman's"), '/sd/boat/fishermans');
  assert.equal(normalizePath('/'), '/');
  assert.equal(normalizePath('http://evil'), null);
});

test('normalizeRef keeps host only, drops self-referrals', () => {
  const hosts = ['thetunatracker.com', 'www.thetunatracker.com'];
  assert.equal(normalizeRef('https://www.google.com/search?q=secret', hosts), 'google.com');
  assert.equal(normalizeRef('https://thetunatracker.com/sd/today', hosts), '');
  assert.equal(normalizeRef('', hosts), '');
  assert.equal(normalizeRef('utm:Newsletter', hosts), 'utm:newsletter');
});

test('parseUA / deviceOf', () => {
  assert.deepEqual(parseUA(UA_IPHONE), { os: 'iOS', br: 'Safari' });
  assert.deepEqual(parseUA(UA_WIN), { os: 'Windows', br: 'Chrome' });
  assert.equal(deviceOf(390, UA_IPHONE), 'mobile');
  assert.equal(deviceOf(1440, UA_WIN), 'desktop');
  assert.equal(deviceOf(null, UA_IPHONE), 'mobile');
});

test('dayOf uses Pacific time; addDays', () => {
  assert.equal(dayOf(Date.parse('2026-11-21T05:00:00Z')), '2026-11-20');
  assert.equal(addDays('2026-03-01', -1), '2026-02-28');
});

// ─── Collector ───────────────────────────────────────────────────────────────

test('stores an event without IP or user agent', async () => {
  const r = await beacon({ src: 'web', w: 390, ev: [pv('/sd/today', { e: 1, r: 'https://www.google.com/x?q=1', g: 400 })] });
  assert.equal(r.status, 204);
  const all = rows();
  assert.equal(all.length, 1);
  const e = all[0];
  assert.equal(e.path, '/sd/today');
  assert.equal(e.ref, 'google.com');
  assert.equal(e.dev, 'mobile');
  assert.equal(e.cc, 'US');
  assert.equal(e.g, 400);
  assert.match(e.vh, /^[0-9a-f]{16}$/);
  const blob = JSON.stringify(all);
  assert.ok(!blob.includes('203.0.113.7'), 'raw IP must not be stored');
  assert.ok(!blob.includes('iPhone OS'), 'raw UA must not be stored');
});

test('drops DNT, GPC, bots, foreign origins, missing origin, unknown types', async () => {
  const ev = [pv('/')];
  await beacon({ ev }, { headers: { DNT: '1' } });
  await beacon({ ev }, { headers: { 'Sec-GPC': '1' } });
  await beacon({ ev }, { ua: 'Mozilla/5.0 (compatible; Googlebot/2.1)' });
  await beacon({ ev }, { origin: 'https://evil.example' });
  await beacon({ ev }, { origin: null });
  await beacon({ ev: [{ t: 'steal_cookies', p: '/' }] });
  assert.equal(rows().length, 0);
});

test('app source may omit Origin', async () => {
  await beacon({ src: 'app', ev: [pv('/app/home')] }, { origin: null, ua: 'Tunatracker/1.0 Expo okhttp' });
  assert.equal(rows()[0].src, 'app');
});

test('caps events per beacon and ignores g on non-pageviews', async () => {
  const ev = Array.from({ length: 40 }, () => ({ t: 'boat_view', p: '/sd/boat/x', boat: 'X', g: 5 }));
  await beacon({ ev });
  const all = rows();
  assert.equal(all.length, 25);
  assert.ok(all.every(r => r.g === null));
});

test('visitor hash is stable within a day and rotates across days', async () => {
  setDay('2026-11-20');
  await beacon({ ev: [pv('/')] });
  await beacon({ ev: [pv('/a')] });
  setDay('2026-11-21');
  await beacon({ ev: [pv('/')] });
  const [a, b, c] = rows();
  assert.equal(a.vh, b.vh);
  assert.notEqual(a.vh, c.vh);
});

// ─── Stats ───────────────────────────────────────────────────────────────────

test('range uniques count each visitor once using the visit gap', async () => {
  const A = { ip: '198.51.100.1' }, B = { ip: '198.51.100.2' };
  setDay('2026-11-18'); await beacon({ ev: [pv('/', { g: 400 })] }, A);
  setDay('2026-11-19'); await beacon({ ev: [pv('/', { g: 400 })] }, B);
  setDay('2026-11-20');
  await beacon({ ev: [pv('/', { g: 2 }), pv('/sd/today')] }, A);
  await beacon({ ev: [pv('/', { g: 1 })] }, B);

  const s = await buildStats(env.DB, '7d');
  assert.equal(s.range.to, '2026-11-20');
  assert.equal(s.current.uv, 2, '7-day uniques');
  assert.equal(s.current.pv, 5);
  const today = await buildStats(env.DB, 'today');
  assert.equal(today.current.uv, 2, 'today: both visited');
  assert.equal(today.current.pv, 3);
  // 2-day window (19th–20th): B on the 19th, A on the 20th (gap 2 reaches back before the 19th).
  const series = s.current.series.filter(d => d.day >= '2026-11-19');
  assert.deepEqual(series.map(d => d.uv), [1, 2]);
});

test('funnels and top lists', async () => {
  setDay('2026-11-20');
  await beacon({ ev: [pv('/', { e: 1, r: 'https://www.google.com/', g: 400 }),
    { t: 'boat_view', p: '/sd/boat/pacific-queen', boat: 'Pacific Queen' },
    { t: 'book_click', p: '/sd/tripplanner', boat: 'Pacific Queen', k: 'planner' }] }, { ip: '1.1.1.1' });
  await beacon({ ev: [pv('/sd/boat/pacific-queen', { e: 1, g: 400 })] }, { ip: '2.2.2.2', ua: UA_WIN });
  await beacon({ ev: [pv('/', { e: 1, g: 400 }), { t: 'chat_open', p: '/' }, { t: 'chat_message', p: '/' },
    { t: 'chat_book_click', p: '/', boat: 'Excel' }] }, { ip: '3.3.3.3' });
  await beacon({ ev: [pv('/', { e: 1, g: 400 })] }, { ip: '4.4.4.4' });

  const s = await buildStats(env.DB, 'today');
  assert.deepEqual(s.current.funnel.site, [4, 2, 1]);
  assert.deepEqual(s.current.funnel.chat, [1, 1, 1]);
  assert.equal(s.current.book, 2);
  assert.equal(s.current.chatters, 1);
  assert.equal(s.top.boat[0].key, 'Pacific Queen');
  assert.deepEqual(s.top.ref.map(r => r.key).sort(), ['', 'google.com']);
  assert.deepEqual(new Set(s.top.dev.map(r => r.key)), new Set(['mobile', 'desktop']));
  assert.equal(s.top.book_boat.length, 2);
});

test('past days are finalised; today re-rolls', async () => {
  setDay('2026-11-19'); await beacon({ ev: [pv('/', { g: 400 })] });
  setDay('2026-11-20'); await beacon({ ev: [pv('/', { g: 400 })] });
  await buildStats(env.DB, '7d');
  const rd = env.DB._raw.prepare('SELECT day, final FROM rolled_days WHERE day >= ? ORDER BY day').all('2026-11-19');
  assert.deepEqual(rd.map(r => [r.day, r.final]), [['2026-11-19', 1], ['2026-11-20', 0]]);
  // new event today shows after the 5-minute re-roll window
  await beacon({ ev: [pv('/x')] }, { ip: '9.9.9.9' });
  clock += 6 * 60e3;
  const s = await buildStats(env.DB, 'today');
  assert.equal(s.current.pv, 2);
});

test('live counts recent visitors', async () => {
  setDay('2026-11-20');
  await beacon({ ev: [pv('/')] }, { ip: '1.1.1.1' });
  clock += 10 * 60e3;
  await beacon({ ev: [pv('/b')] }, { ip: '2.2.2.2' });
  const l = await buildLive(env.DB);
  assert.equal(l.active5, 1);
  assert.equal(l.active30, 2);
  assert.equal(l.recent.length, 2);
  assert.equal(l.perMinute.reduce((a, b) => a + b, 0), 2);
  assert.ok(!('vh' in l.recent[0]), 'live feed must not expose hashes');
});

test('maintain drops raw events after retention and old salts, keeps rollups', async () => {
  setDay('2026-08-01'); await beacon({ ev: [pv('/', { g: 400 })] });
  setDay('2026-11-20'); await beacon({ ev: [pv('/', { g: 400 })] });
  await maintain(env);
  const ev = rows();
  assert.equal(ev.length, 1);
  const salts = env.DB._raw.prepare('SELECT day FROM salts').all().map(r => r.day);
  assert.deepEqual(salts, ['2026-11-20']);
  const roll = env.DB._raw.prepare("SELECT day FROM rollup WHERE dim='total'").all().map(r => r.day);
  assert.ok(roll.includes('2026-08-01'));
});

// ─── Owner API + Access ──────────────────────────────────────────────────────

const subtle = webcrypto.subtle;
const b64u = buf => Buffer.from(buf).toString('base64url');
async function accessFixture() {
  const kp = await subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const jwk = { ...(await subtle.exportKey('jwk', kp.publicKey)), kid: 'k1', alg: 'RS256' };
  const realFetch = globalThis.fetch;
  globalThis.fetch = async url => {
    assert.equal(String(url), 'https://tunatracker.cloudflareaccess.com/cdn-cgi/access/certs');
    return new Response(JSON.stringify({ keys: [jwk] }));
  };
  const sign = async (claims, key = kp.privateKey, kid = 'k1') => {
    const h = b64u(JSON.stringify({ alg: 'RS256', kid }));
    const p = b64u(JSON.stringify(claims));
    const sig = await subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(`${h}.${p}`));
    return `${h}.${p}.${b64u(sig)}`;
  };
  return { sign, restore: () => { globalThis.fetch = realFetch; } };
}
const ownerReq = (p, tok) => new Request('https://thetunatracker.com' + p, { headers: tok ? { 'Cf-Access-Jwt-Assertion': tok } : {} });

test('owner API fails closed when Access is not configured', async () => {
  const r = await worker.fetch(ownerReq('/owner/api/stats'), env);
  assert.equal(r.status, 503);
});

test('owner API verifies the Access JWT', async () => {
  const fx = await accessFixture();
  try {
    Object.assign(env, { ACCESS_TEAM_DOMAIN: 'tunatracker', ACCESS_AUD: 'aud-123', OWNER_EMAILS: 'owner@example.com' });
    const exp = Math.floor(clock / 1000) + 600;
    const good = await fx.sign({ aud: ['aud-123'], email: 'owner@example.com', exp, iss: 'https://tunatracker.cloudflareaccess.com' });
    assert.equal((await worker.fetch(ownerReq('/owner/api/stats?range=7d'), env)).status, 401, 'no token');
    const ok = await worker.fetch(ownerReq('/owner/api/stats?range=7d', good), env);
    assert.equal(ok.status, 200);
    assert.equal(ok.headers.get('Cache-Control'), 'private, no-store');
    const body = await ok.json();
    assert.equal(body.range.days, 7);

    const wrongAud = await fx.sign({ aud: ['other'], email: 'owner@example.com', exp });
    assert.equal((await worker.fetch(ownerReq('/owner/api/live', wrongAud), env)).status, 403);
    const expired = await fx.sign({ aud: ['aud-123'], email: 'owner@example.com', exp: Math.floor(clock / 1000) - 5 });
    assert.equal((await worker.fetch(ownerReq('/owner/api/live', expired), env)).status, 401);
    const stranger = await fx.sign({ aud: ['aud-123'], email: 'someone@example.com', exp });
    assert.equal((await worker.fetch(ownerReq('/owner/api/live', stranger), env)).status, 403);
    const other = await subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign']);
    const forged = await fx.sign({ aud: ['aud-123'], email: 'owner@example.com', exp }, other.privateKey);
    assert.equal((await worker.fetch(ownerReq('/owner/api/live', forged), env)).status, 401);
    const tampered = good.split('.'); tampered[1] = b64u(JSON.stringify({ aud: ['aud-123'], email: 'owner@example.com', exp: exp + 9999 }));
    assert.equal((await worker.fetch(ownerReq('/owner/api/live', tampered.join('.')), env)).status, 401);
  } finally { fx.restore(); }
});

test('admin payload: ingest needs the token; read needs Access', async () => {
  const fx = await accessFixture();
  try {
    Object.assign(env, { ADMIN_INGEST_TOKEN: 's3cret-token', ACCESS_TEAM_DOMAIN: 'tunatracker.cloudflareaccess.com', ACCESS_AUD: 'aud-1' });
    const post = tok => worker.fetch(new Request('https://thetunatracker.com/a/admin', {
      method: 'POST', headers: { Authorization: `Bearer ${tok}` }, body: JSON.stringify({ ADMIN: { dbStats: { total: 3 } }, META: {} }) }), env);
    assert.equal((await post('wrong')).status, 401);
    assert.equal((await post('s3cret-token')).status, 200);
    assert.equal((await worker.fetch(ownerReq('/owner/api/admin'), env)).status, 401);
    const tok = await fx.sign({ aud: 'aud-1', exp: Math.floor(clock / 1000) + 60 });
    const r = await worker.fetch(ownerReq('/owner/api/admin', tok), env);
    assert.equal(r.status, 200);
    assert.equal((await r.json()).data.ADMIN.dbStats.total, 3);
  } finally { fx.restore(); }
});

test('verifyAccess rejects non-RS256 tokens', async () => {
  Object.assign(env, { ACCESS_TEAM_DOMAIN: 't', ACCESS_AUD: 'a' });
  const none = `${b64u(JSON.stringify({ alg: 'none' }))}.${b64u(JSON.stringify({ aud: 'a', exp: 9e9 }))}.`;
  const r = await verifyAccess(ownerReq('/owner/api/me', none), env);
  assert.equal(r.ok, false);
});
