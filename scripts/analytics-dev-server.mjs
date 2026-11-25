// Local preview of the owner dashboard + collector, with no Cloudflare account.
//
//   node scripts/analytics-dev-server.mjs [--port 8787] [--seed]
//
// Serves web/ statically and routes /a/* and /owner/api/* to the real
// cloudflare-worker/analytics.js, backed by an in-memory SQLite D1 shim. It
// plays the part of Cloudflare Access by signing a short-lived JWT for every
// /owner/api request with a throwaway local key, so the Worker's real JWT
// verification runs. --seed fills ~120 days of synthetic traffic.
// Dev only: never deploy this.
import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { webcrypto } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createD1 } from '../tests/analytics/d1-shim.mjs';
import worker, { addDays, dayOf } from '../cloudflare-worker/analytics.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(root, 'web');
const args = process.argv.slice(2);
const port = Number(args[args.indexOf('--port') + 1]) || 8787;
const seed = args.includes('--seed');

const db = createD1(path.join(root, 'cloudflare-worker', 'analytics-schema.sql'));
const TEAM = 'dev-team.cloudflareaccess.com', AUD = 'dev-aud';
const env = {
  DB: db, TZ_NAME: 'America/Los_Angeles', ALLOWED_HOSTS: 'localhost,127.0.0.1',
  ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, OWNER_EMAILS: 'owner@localhost', ADMIN_INGEST_TOKEN: 'dev-token',
};

// Throwaway signing key standing in for Cloudflare Access.
const subtle = webcrypto.subtle;
const kp = await subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const jwk = { ...(await subtle.exportKey('jwk', kp.publicKey)), kid: 'dev', alg: 'RS256' };
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => String(url) === `https://${TEAM}/cdn-cgi/access/certs`
  ? new Response(JSON.stringify({ keys: [jwk] })) : realFetch(url, init);
const b64u = b => Buffer.from(b).toString('base64url');
async function accessJwt() {
  const h = b64u(JSON.stringify({ alg: 'RS256', kid: 'dev' }));
  const p = b64u(JSON.stringify({ aud: [AUD], email: 'owner@localhost', iss: `https://${TEAM}`, exp: Math.floor(Date.now() / 1000) + 300 }));
  const sig = await subtle.sign('RSASSA-PKCS1-v1_5', kp.privateKey, new TextEncoder().encode(`${h}.${p}`));
  return `${h}.${p}.${b64u(sig)}`;
}

function seedData() {
  const raw = db._raw;
  const ins = raw.prepare(`INSERT INTO events (ts, day, type, path, entry, ref, dev, os, br, cc, src, boat, landing, trip, kind, g, vh)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
  const boats = [['Pacific Queen', "Fisherman's Landing"], ['Excel', 'H&M Landing'], ['Red Rooster III', 'H&M Landing'],
    ['Polaris Supreme', 'Seaforth Sportfishing'], ['Tribute', 'Seaforth Sportfishing'], ['New Lo-An', 'Point Loma Sportfishing'],
    ['Liberty', "Fisherman's Landing"], ['American Angler', 'Point Loma Sportfishing']];
  const refs = ['', '', '', 'google.com', 'google.com', 'google.com', 'bing.com', 'facebook.com', 'bloodydecks.com', 'instagram.com', 'utm:newsletter'];
  const pages = ['/', '/sd/today', '/sd/boats', '/sd/tripplanner', '/sd/analytics/overview', '/sd/charts'];
  const rnd = a => a[Math.floor(Math.random() * a.length)];
  const today = dayOf(Date.now());
  raw.exec('BEGIN');
  for (let back = 119; back >= 0; back--) {
    const day = addDays(today, -back);
    const dow = new Date(day + 'T12:00:00Z').getUTCDay();
    const base = 40 + (120 - back) * 0.6 + (dow === 5 || dow === 6 ? 35 : 0);
    const visitors = Math.round(base * (0.8 + Math.random() * 0.4));
    const dayStart = Date.parse(day + 'T15:00:00Z');
    for (let v = 0; v < visitors; v++) {
      const vh = Math.random().toString(16).slice(2, 18);
      const dev = Math.random() < 0.68 ? 'mobile' : Math.random() < 0.15 ? 'tablet' : 'desktop';
      const os = dev === 'desktop' ? rnd(['Windows', 'macOS']) : rnd(['iOS', 'iOS', 'Android']);
      const br = os === 'iOS' ? 'Safari' : rnd(['Chrome', 'Chrome', 'Edge', 'Firefox']);
      const cc = Math.random() < 0.9 ? 'US' : rnd(['MX', 'CA', 'JP']);
      const src = back < 20 && Math.random() < 0.12 ? 'app' : Math.random() < 0.06 ? 'pwa' : 'web';
      const g = Math.random() < 0.45 ? 400 : Math.ceil(Math.random() * 20);
      let ts = back === 0 ? Date.now() - Math.random() * 3 * 3600e3 : dayStart + Math.random() * 14 * 3600e3;
      const n = 1 + Math.floor(Math.random() * 5);
      for (let i = 0; i < n; i++) {
        const [boat, landing] = rnd(boats);
        const p = Math.random() < 0.3 ? '/sd/boat/' + boat.toLowerCase().replace(/[^a-z0-9]+/g, '-') : rnd(pages);
        ins.run(ts, day, 'pageview', p, i === 0 ? 1 : 0, i === 0 ? rnd(refs) : null, dev, os, br, cc, src, null, null, null, null, i === 0 ? g : null, vh);
        if (p.includes('/boat/') || Math.random() < 0.2) ins.run(ts + 500, day, 'boat_view', p, 0, null, dev, os, br, cc, src, boat, landing, null, null, null, vh);
        if (Math.random() < 0.05) ins.run(ts + 900, day, 'book_click', '/sd/tripplanner', 0, null, dev, os, br, cc, src, boat, landing, 't' + v, 'planner', null, vh);
        ts += 20e3 + Math.random() * 60e3;
      }
      if (Math.random() < 0.1) {
        ins.run(ts, day, 'chat_open', '/', 0, null, dev, os, br, cc, src, null, null, null, null, null, vh);
        if (Math.random() < 0.7) ins.run(ts + 5e3, day, 'chat_message', '/', 0, null, dev, os, br, cc, src, null, null, null, null, null, vh);
        if (Math.random() < 0.2) { const [boat, landing] = rnd(boats); ins.run(ts + 9e3, day, 'chat_book_click', '/', 0, null, dev, os, br, cc, src, boat, landing, null, 'chat_card', null, vh); }
      }
    }
  }
  raw.exec('COMMIT');
  const n = raw.prepare('SELECT COUNT(*) AS n FROM events').get().n;
  console.log(`seeded ${n} synthetic events`);
}
if (seed) seedData();

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.jpg': 'image/jpeg', '.webmanifest': 'application/manifest+json' };

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${port}`);
  try {
    if (url.pathname.startsWith('/a/') || url.pathname.startsWith('/owner/api/')) {
      const headers = new Headers();
      for (const [k, v] of Object.entries(req.headers)) if (typeof v === 'string') headers.set(k, v);
      headers.set('CF-Connecting-IP', req.socket.remoteAddress || '127.0.0.1');
      headers.set('CF-IPCountry', 'US');
      if (url.pathname.startsWith('/owner/api/')) headers.set('Cf-Access-Jwt-Assertion', await accessJwt());
      const chunks = []; for await (const c of req) chunks.push(c);
      const body = ['GET', 'HEAD'].includes(req.method) ? undefined : Buffer.concat(chunks);
      const r = await worker.fetch(new Request(url, { method: req.method, headers, body }), env);
      res.writeHead(r.status, Object.fromEntries(r.headers));
      res.end(Buffer.from(await r.arrayBuffer()));
      return;
    }
    let p = decodeURIComponent(url.pathname);
    let file = path.join(WEB, p);
    if (!file.startsWith(WEB)) { res.writeHead(403); res.end(); return; }
    try { if ((await stat(file)).isDirectory()) file = path.join(file, 'index.html'); } catch (e) { file = path.join(WEB, 'index.html'); }
    let data = await readFile(file);
    const ext = path.extname(file);
    if (file === path.join(WEB, 'index.html')) {
      data = Buffer.from(String(data).replace('<head>', "<head>\n<script>window.TT_ANALYTICS_ENDPOINT='/a/e';</script>"));
    }
    res.writeHead(200, { 'Content-Type': TYPES[ext] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(data);
  } catch (e) {
    console.error(e);
    res.writeHead(500); res.end(String(e));
  }
}).listen(port, () => console.log(`analytics dev server: http://localhost:${port}/owner/`));
