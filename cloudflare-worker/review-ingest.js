/**
 * review-ingest Cloudflare Worker
 *
 * Replaces Formspree for boat-review submissions. Reviews land in KV and
 * the site fetches them on load, merging with any legacy reviews baked
 * into web/data.js.
 *
 *   POST /reviews         Submit a new review (JSON body). Auto-approved.
 *   GET  /reviews         Return every stored review as a JSON array.
 *   GET  /reviews/count   Return {count: N} — cheap health check.
 *
 * Required bindings (see review-ingest-wrangler.toml):
 *   REVIEWS               KV namespace holding one review per key + an
 *                         `index:all` aggregate for cheap reads.
 *
 * Rate limit: 5 submissions per IP per hour (KV key `rl:{ip}:{hour}`).
 */

const ALLOWED_ORIGINS = [
  'https://thetunatracker.com',
  'https://www.thetunatracker.com',
  'http://localhost:8765',
];

const RATE_LIMIT_PER_HOUR = 5;
const MAX_BODY_BYTES = 32 * 1024;  // JSON review with URLs — 32 kB is plenty

const REQUIRED_FIELDS = ['boat', 'overall_rating'];
const RATING_FIELDS = [
  'overall_rating', 'captain_rating', 'crew_rating',
  'fish_finding_rating', 'galley_rating', 'bunks_rating',
];

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const allowedOrigin = ALLOWED_ORIGINS.find(o => origin.startsWith(o)) || ALLOWED_ORIGINS[0];
    const cors = {
      'Access-Control-Allow-Origin': allowedOrigin,
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Max-Age': '86400',
    };

    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });

    const url = new URL(request.url);

    if (request.method === 'GET' && url.pathname === '/reviews') {
      const data = await env.REVIEWS.get('index:all') || '[]';
      return jsonResponse(data, cors, { 'Cache-Control': 'public, max-age=30' });
    }

    if (request.method === 'GET' && url.pathname === '/reviews/count') {
      const raw = await env.REVIEWS.get('index:all') || '[]';
      const arr = JSON.parse(raw);
      return jsonResponse({ count: arr.length }, cors);
    }

    if (request.method === 'POST' && url.pathname === '/reviews') {
      return ingest(request, env, cors);
    }

    return new Response('Not found', { status: 404, headers: cors });
  },
};

async function ingest(request, env, cors) {
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';

  // ── Rate limit ─────────────────────────────────────────────────────────────
  const hour = Math.floor(Date.now() / 3_600_000);
  const rlKey = `rl:${ip}:${hour}`;
  const rlCount = parseInt(await env.REVIEWS.get(rlKey) || '0', 10);
  if (rlCount >= RATE_LIMIT_PER_HOUR) {
    return errResponse(429, 'Too many submissions — try again later.', cors);
  }

  // ── Read + validate body ───────────────────────────────────────────────────
  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) {
    return errResponse(413, 'Review too large.', cors);
  }
  let body;
  try { body = JSON.parse(raw); }
  catch { return errResponse(400, 'Invalid JSON.', cors); }

  for (const field of REQUIRED_FIELDS) {
    if (body[field] == null || body[field] === '') {
      return errResponse(400, `Missing required field: ${field}`, cors);
    }
  }
  for (const field of RATING_FIELDS) {
    if (body[field] != null && body[field] !== '') {
      const n = Number(body[field]);
      if (!Number.isFinite(n) || n < 0 || n > 5) {
        return errResponse(400, `Invalid rating: ${field}`, cors);
      }
    }
  }

  // ── Build the stored review ────────────────────────────────────────────────
  const now = new Date().toISOString();
  const id = `${now}_${randomSuffix(6)}`;
  const ipHash = await sha256(ip);
  const review = {
    id,
    boat: String(body.boat).slice(0, 80),
    landing: String(body.landing || '').slice(0, 80),
    reviewer_name: String(body.reviewer_name || '').slice(0, 60) || 'Anonymous',
    trip_date: String(body.trip_date || '').slice(0, 10),
    trip_length: String(body.trip_length || '').slice(0, 30),
    overall_rating: intOrNull(body.overall_rating),
    captain_rating: intOrNull(body.captain_rating),
    crew_rating: intOrNull(body.crew_rating),
    fish_finding_rating: intOrNull(body.fish_finding_rating),
    galley_rating: intOrNull(body.galley_rating),
    bunks_rating: intOrNull(body.bunks_rating),
    title: String(body.title || '').slice(0, 200),
    body: String(body.body || '').slice(0, 3000),
    would_rebook: body.would_rebook === true || body.would_rebook === 'true' ? true
                : body.would_rebook === false || body.would_rebook === 'false' ? false
                : null,
    photos: Array.isArray(body.photos) ? body.photos.slice(0, 8).map(String) : [],
    submitted_at: now.slice(0, 10),
    source: 'worker',
    ip_hash: ipHash.slice(0, 16),
  };

  // ── Persist ────────────────────────────────────────────────────────────────
  // Store one canonical key per review + an aggregate list for cheap reads.
  await env.REVIEWS.put(`review:${id}`, JSON.stringify(review));

  const existing = JSON.parse(await env.REVIEWS.get('index:all') || '[]');
  existing.unshift(review);  // newest first
  await env.REVIEWS.put('index:all', JSON.stringify(existing));

  await env.REVIEWS.put(rlKey, String(rlCount + 1), { expirationTtl: 3900 });

  return jsonResponse({ ok: true, id }, cors);
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function jsonResponse(payload, cors, extra = {}) {
  const body = typeof payload === 'string' ? payload : JSON.stringify(payload);
  return new Response(body, {
    headers: { ...cors, 'Content-Type': 'application/json', ...extra },
  });
}

function errResponse(status, message, cors) {
  return jsonResponse({ error: message }, cors, { 'X-Error': message });
}

function intOrNull(v) {
  if (v == null || v === '') return null;
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}

function randomSuffix(len) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = crypto.getRandomValues(new Uint8Array(len));
  return Array.from(bytes, b => chars[b % chars.length]).join('');
}

async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('');
}
