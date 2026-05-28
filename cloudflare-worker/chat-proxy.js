export default {
  async fetch(request, env) {

    const origin = request.headers.get('Origin');
    const allowed = [
      'https://thetunatracker.com',
      'https://www.thetunatracker.com',
      'http://localhost:8765'
    ];

    const allowedOrigin = allowed.find(a => origin?.startsWith(a)) ? origin : null;

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

    // Always stream — the frontend expects SSE
    body.stream = true;

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
