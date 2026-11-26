// Google Places reviews proxy for boat and landing pages.
//
//   GET /v1/place/<place_id>  ->  { rating, count, mapsUri, name, reviews[<=5] }
//
// Why a proxy: the API key stays server-side, and we can enforce Google's
// rules and a spending cap in one place.
//
// Google rules this Worker follows (Places API policies + Maps Service Terms):
//   * Only place_id may be stored long term. Its source list is the public
//     web/api/v1/google_places.json. Review text, ratings and author data are
//     fetched fresh and never written to KV, D1 or the repo.
//   * At most 5 reviews (Google returns <=5, sorted by relevance), passed through
//     with author attribution (name, profile link, photo) so the page can
//     show it.
//   * CACHE_TTL_SECONDS (default 0, i.e. no edge cache) allows a short
//     performance cache only if the owner confirms the current policy permits it.
//
// Cost guard: only place_ids in the allowlist are fetched, and DAILY_CAP
// (default 30/day, about 900/month) keeps usage inside the 1,000 free
// Enterprise + Atmosphere calls a month. That gives a bill of $0 unless the
// cap is raised.
//
// Secrets / vars (see docs/research/OWNER_SETUP_KEYS.md):
//   wrangler secret put GOOGLE_PLACES_API_KEY
//   [vars] DAILY_CAP, CACHE_TTL_SECONDS, ALLOWLIST_URL in places-proxy-wrangler.toml

const ALLOWED_ORIGINS = [
  'https://thetunatracker.com',
  'https://www.thetunatracker.com',
  'http://localhost:8765',
];
const FIELD_MASK = 'id,displayName,rating,userRatingCount,googleMapsUri,reviews';
const PLACE_ID_RE = /^[A-Za-z0-9_-]{10,300}$/;

let _allow = null;          // { ids: Set, at: ms }
const ALLOW_TTL_MS = 3600_000;

async function loadAllowlist(env) {
  if (_allow && Date.now() - _allow.at < ALLOW_TTL_MS) return _allow.ids;
  const url = env.ALLOWLIST_URL || 'https://thetunatracker.com/api/v1/google_places.json';
  const ids = new Set();
  try {
    const r = await fetch(url, { cf: { cacheTtl: 600 } });
    if (r.ok) {
      const j = await r.json();
      for (const group of ['boats', 'landings']) {
        for (const v of Object.values(j[group] || {})) if (v && v.place_id) ids.add(v.place_id);
      }
    }
  } catch (_) { /* empty allowlist => everything refused */ }
  _allow = { ids, at: Date.now() };
  return ids;
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

// Trim Google's response to what the panel shows. Nothing here is persisted.
export function shapePlace(p) {
  const reviews = (p.reviews || []).slice(0, 5).map(r => ({
    rating: r.rating ?? null,
    text: (r.text && r.text.text) || (r.originalText && r.originalText.text) || '',
    when: r.relativePublishTimeDescription || '',
    publishTime: r.publishTime || null,
    author: {
      name: (r.authorAttribution && r.authorAttribution.displayName) || 'Google user',
      uri: (r.authorAttribution && r.authorAttribution.uri) || null,
      photo: (r.authorAttribution && r.authorAttribution.photoUri) || null,
    },
    uri: r.googleMapsUri || null,
  }));
  return {
    name: (p.displayName && p.displayName.text) || '',
    rating: p.rating ?? null,
    count: p.userRatingCount ?? 0,
    mapsUri: p.googleMapsUri || null,
    reviews,
    sort: 'relevance',
  };
}

async function underDailyCap(env) {
  if (!env.PLACES_KV) return true;  // no KV bound: rely on the Google Cloud quota cap
  const cap = parseInt(env.DAILY_CAP || '30', 10);
  const key = 'count:' + new Date().toISOString().slice(0, 10);
  const n = parseInt((await env.PLACES_KV.get(key)) || '0', 10);
  if (n >= cap) return false;
  await env.PLACES_KV.put(key, String(n + 1), { expirationTtl: 3 * 86400 });
  return true;
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get('Origin') || '';
    const allowedOrigin = ALLOWED_ORIGINS.find(a => origin.startsWith(a));
    const cors = allowedOrigin ? {
      'Access-Control-Allow-Origin': allowedOrigin,
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Vary': 'Origin',
    } : {};
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    if (request.method !== 'GET') return json({ error: 'method' }, 405, cors);
    if (!allowedOrigin) return json({ error: 'forbidden' }, 403, {});

    const m = new URL(request.url).pathname.match(/^\/v1\/place\/([^/]+)$/);
    if (!m) return json({ error: 'not_found' }, 404, cors);
    const placeId = decodeURIComponent(m[1]);
    if (!PLACE_ID_RE.test(placeId)) return json({ error: 'bad_id' }, 400, cors);
    if (!env.GOOGLE_PLACES_API_KEY) return json({ error: 'not_configured' }, 503, cors);

    const allow = await loadAllowlist(env);
    if (!allow.has(placeId)) return json({ error: 'unknown_place' }, 404, cors);

    const ttl = parseInt(env.CACHE_TTL_SECONDS || '0', 10);
    const cacheKey = new Request('https://places-proxy.cache/' + placeId);
    if (ttl > 0) {
      const hit = await caches.default.match(cacheKey);
      if (hit) {
        const h = new Headers(hit.headers);
        for (const [k, v] of Object.entries(cors)) h.set(k, v);
        return new Response(hit.body, { status: 200, headers: h });
      }
    }

    if (!(await underDailyCap(env))) return json({ error: 'daily_cap' }, 429, cors);

    let g;
    try {
      g = await fetch(`https://places.googleapis.com/v1/places/${encodeURIComponent(placeId)}?languageCode=en`, {
        headers: { 'X-Goog-Api-Key': env.GOOGLE_PLACES_API_KEY, 'X-Goog-FieldMask': FIELD_MASK },
      });
    } catch (_) {
      return json({ error: 'upstream' }, 502, cors);
    }
    if (!g.ok) return json({ error: 'upstream', status: g.status }, 502, cors);

    const body = JSON.stringify(shapePlace(await g.json()));
    const cacheHdr = ttl > 0 ? `public, max-age=${ttl}` : 'no-store';
    if (ttl > 0) {
      ctx.waitUntil(caches.default.put(cacheKey, new Response(body, {
        headers: { 'Content-Type': 'application/json', 'Cache-Control': cacheHdr },
      })));
    }
    return new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': cacheHdr, ...cors },
    });
  },
};
