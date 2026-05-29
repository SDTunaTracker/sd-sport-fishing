/**
 * vessel-tracker Cloudflare Worker
 *
 * Schedule (cron): every 5 min — opens AISStream.io WebSocket, collects
 * position reports for 28 seconds, merges with existing trail data, stores
 * in KV.
 *
 * GET  /vessels          → returns cached JSON array of vessel positions
 * PUT  /vessels          → Python script push (auth via X-Auth-Token header)
 *
 * Required env bindings (set in CF dashboard or wrangler.toml):
 *   VESSEL_POSITIONS     KV namespace
 *   AISSTREAM_API_KEY    AISStream.io key (secret)
 *   AUTH_TOKEN           Random token for PUT auth (secret)
 *   VESSEL_MMSI_JSON     JSON string: {"338123456": {"name":"Pacific Queen","landing":"Fisherman's Landing"}, ...}
 */

const ALLOWED_ORIGINS = [
  'https://thetunatracker.com',
  'https://www.thetunatracker.com',
  'http://localhost:8765',
];

const SOCAL_BOX = [[31.0, -121.0], [35.0, -117.0]];
const MAX_TRAIL  = 12; // positions — 12 × 5min = 1 hr of trail

export default {
  // ── HTTP handler ──────────────────────────────────────────────────────────
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const allowedOrigin = ALLOWED_ORIGINS.find(o => origin.startsWith(o)) || null;

    const cors = {
      'Access-Control-Allow-Origin': allowedOrigin || ALLOWED_ORIGINS[0],
      'Access-Control-Allow-Methods': 'GET, PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, X-Auth-Token',
    };

    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });

    const url = new URL(request.url);
    if (url.pathname !== '/vessels') {
      return new Response('Not found', { status: 404, headers: cors });
    }

    if (request.method === 'GET') {
      const data = await env.VESSEL_POSITIONS.get('positions') || '[]';
      return new Response(data, {
        headers: { ...cors, 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' },
      });
    }

    if (request.method === 'PUT') {
      if (request.headers.get('X-Auth-Token') !== env.AUTH_TOKEN) {
        return new Response('Unauthorized', { status: 401, headers: cors });
      }
      const body = await request.text();
      await mergeAndStore(env, JSON.parse(body));
      return new Response('OK', { headers: cors });
    }

    return new Response('Method not allowed', { status: 405, headers: cors });
  },

  // ── Cron handler ──────────────────────────────────────────────────────────
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(collectAIS(env));
  },
};

// ── AIS collection ────────────────────────────────────────────────────────────

async function collectAIS(env) {
  const knownMMSI = JSON.parse(env.VESSEL_MMSI_JSON || '{}');
  if (Object.keys(knownMMSI).length === 0) return;

  const fresh = {};

  await new Promise((resolve) => {
    const ws = new WebSocket('wss://stream.aisstream.io/v0/stream');
    const timer = setTimeout(() => { ws.close(); resolve(); }, 28000);

    ws.addEventListener('open', () => {
      ws.send(JSON.stringify({
        APIKey:             env.AISSTREAM_API_KEY,
        BoundingBoxes:      [SOCAL_BOX],
        FiltersShipMMSI:    Object.keys(knownMMSI),
        FilterMessageTypes: ['PositionReport', 'StandardClassBPositionReport'],
      }));
    });

    ws.addEventListener('message', (evt) => {
      try {
        const data = JSON.parse(evt.data);
        const meta = data.MetaData || {};
        const mmsi = String(meta.MMSI || '');
        if (!mmsi || !knownMMSI[mmsi]) return;

        const msg = (data.Message || {});
        const pos = msg.PositionReport || msg.StandardClassBPositionReport || {};
        const sog = pos.Sog ?? 0;
        const cog = pos.Cog ?? 0;

        fresh[mmsi] = {
          mmsi,
          name:       knownMMSI[mmsi].name,
          landing:    knownMMSI[mmsi].landing,
          lat:        meta.latitude,
          lng:        meta.longitude,
          sog,
          cog,
          heading:    pos.TrueHeading ?? cog,
          updated_at: meta.time_utc || new Date().toISOString(),
        };
      } catch (_) {}
    });

    ws.addEventListener('error',  () => { clearTimeout(timer); resolve(); });
    ws.addEventListener('close',  () => { clearTimeout(timer); resolve(); });
  });

  if (Object.keys(fresh).length > 0) {
    await mergeAndStore(env, Object.values(fresh));
  }
}

// ── Trail merge + KV write ────────────────────────────────────────────────────

async function mergeAndStore(env, newPositions) {
  const existing = JSON.parse(await env.VESSEL_POSITIONS.get('positions') || '[]');
  const byMMSI   = {};
  existing.forEach(p => { byMMSI[p.mmsi] = p; });

  newPositions.forEach(pos => {
    const prev  = byMMSI[pos.mmsi] || {};
    const trail = prev.trail || [];
    if (prev.lat != null) {
      trail.push({ lat: prev.lat, lng: prev.lng, t: prev.updated_at, sog: prev.sog });
    }
    pos.trail = trail.slice(-MAX_TRAIL);
    byMMSI[pos.mmsi] = pos;
  });

  await env.VESSEL_POSITIONS.put('positions', JSON.stringify(Object.values(byMMSI)), {
    expirationTtl: 600,
  });
}
