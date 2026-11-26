// Co-Captain chat relay → Anthropic. Deployed as the "chatbot" worker
// (chatbot.tylerjchristian.workers.dev); see chat-proxy-wrangler.toml.

// Haiku is about 5x cheaper than Opus and fine for "which trip should I take".
// Override with the CHAT_MODEL var without a code change.
const DEFAULT_MODEL = 'claude-haiku-4-5';
const MAX_TOKENS = 1000;          // reply length cap
const MAX_MESSAGES = 8;           // last 4 back-and-forths of history
const MAX_MESSAGE_CHARS = 4000;
const MAX_SYSTEM_CHARS = 120000;  // the trip-data prompt the site builds; a backstop, not a trim
const PER_IP_HOURLY = 15;         // messages per visitor per hour
const DEFAULT_DAILY_CAP = 300;    // messages per day across everyone (needs CHAT_KV)

function clip(v, n) {
  if (typeof v !== 'string') return '';
  return v.length > n ? v.slice(0, n) : v;
}

// Per-isolate memory: best effort only (Cloudflare runs several isolates), but
// it stops one browser tab hammering the bot. The KV daily cap is the hard stop.
const hits = new Map();

async function overLimit(ip, env) {
  const now = Date.now();
  const hour = 3600000;
  const recent = (hits.get(ip) || []).filter(t => now - t < hour);
  if (recent.length >= PER_IP_HOURLY) {
    return 'You have hit the hourly chat limit. Please try again in a bit.';
  }
  recent.push(now);
  hits.set(ip, recent);
  if (hits.size > 5000) hits.clear();

  if (env.CHAT_KV) {
    const key = 'day:' + new Date().toISOString().slice(0, 10);
    const used = parseInt((await env.CHAT_KV.get(key)) || '0', 10);
    const cap = parseInt(env.DAILY_CAP || DEFAULT_DAILY_CAP, 10);
    if (used >= cap) return 'Co-Captain is resting for today. Please try again tomorrow.';
    await env.CHAT_KV.put(key, String(used + 1), { expirationTtl: 2 * 86400 });
  }
  return null;
}

export default {
  async fetch(request, env) {

    const origin = request.headers.get('Origin');
    const allowed = [
      'https://thetunatracker.com',
      'https://www.thetunatracker.com',
      'http://localhost:8765'
    ];

    // Exact match: startsWith() also let "https://thetunatracker.com.evil.example" through.
    const allowedOrigin = allowed.includes(origin) ? origin : null;

    if (!allowedOrigin) {
      return new Response('Forbidden', { status: 403 });
    }

    const corsHeaders = {
      'Access-Control-Allow-Origin': allowedOrigin,
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405, headers: corsHeaders });
    }

    let body;
    try {
      body = await request.json();
    } catch (e) {
      return new Response(JSON.stringify({ error: 'Invalid JSON body' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // ── Cost guards ──────────────────────────────────────────────────────────
    // The browser's request is untrusted: anyone can POST here with any model
    // or size. Rebuild the request server-side so cost per message is bounded.
    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    const limited = await overLimit(ip, env);
    if (limited) {
      return new Response(JSON.stringify({ error: limited }), {
        status: 429,
        headers: { ...corsHeaders, 'Content-Type': 'application/json', 'Retry-After': '3600' },
      });
    }

    const msgs = Array.isArray(body.messages) ? body.messages : [];
    const clean = msgs.slice(-MAX_MESSAGES).map(m => ({
      role: m && m.role === 'assistant' ? 'assistant' : 'user',
      content: clip(m && m.content, MAX_MESSAGE_CHARS),
    }));
    // Anthropic requires the first message to be from the user.
    while (clean.length && clean[0].role !== 'user') clean.shift();
    if (!clean.length) {
      return new Response(JSON.stringify({ error: 'No message' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    body = {
      model: env.CHAT_MODEL || DEFAULT_MODEL,
      max_tokens: Math.min(Number(body.max_tokens) || MAX_TOKENS, MAX_TOKENS),
      system: clip(body.system, MAX_SYSTEM_CHARS),
      messages: clean,
      // Always stream — the frontend expects SSE
      stream: true,
    };

    let anthropicResponse;
    try {
      anthropicResponse = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': env.ANTHROPIC_API_KEY,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify(body),
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: 'Failed to reach Anthropic API' }), {
        status: 502,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    if (!anthropicResponse.ok) {
      const errText = await anthropicResponse.text().catch(() => 'unknown error');
      return new Response(JSON.stringify({ error: errText }), {
        status: anthropicResponse.status,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // Pipe the SSE stream straight through to the client
    return new Response(anthropicResponse.body, {
      status: 200,
      headers: {
        ...corsHeaders,
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    });
  }
};
