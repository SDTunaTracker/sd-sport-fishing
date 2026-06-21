// Cloudflare Worker — reliable hourly trigger for the "Daily Scrape" workflow.
//
// GitHub's built-in `schedule:` cron is best-effort and silently drops a large
// share of runs (worst at the top of the hour). This Worker's Cron Trigger is
// reliable; every hour it calls the GitHub REST API to dispatch the workflow,
// guaranteeing the scrape actually runs ~hourly. The workflow's own `:37` cron
// remains as a second independent path.
//
// ── Setup ────────────────────────────────────────────────────────────────────
//   1. Create a fine-grained GitHub PAT scoped to ONLY the sd-sport-fishing
//      repo, with permission:  Actions → Read and write.
//   2. Store it as a Worker secret:
//        wrangler secret put GH_DISPATCH_TOKEN --config scrape-trigger-wrangler.toml
//   3. (optional) protect the manual test endpoint:
//        wrangler secret put AUTH_TOKEN --config scrape-trigger-wrangler.toml
//   4. Deploy:
//        wrangler deploy --config scrape-trigger-wrangler.toml
//
// Manual test:  curl "https://scrape-trigger.<subdomain>.workers.dev/?key=<AUTH_TOKEN>"

const GH_OWNER    = 'sdtunatracker';
const GH_REPO     = 'sd-sport-fishing';
const GH_WORKFLOW = 'daily-scrape.yml';
const GH_REF      = 'main';

async function dispatchWorkflow(env) {
  if (!env.GH_DISPATCH_TOKEN) {
    return { ok: false, status: 0, body: 'GH_DISPATCH_TOKEN secret not set' };
  }
  const url = `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}` +
              `/actions/workflows/${GH_WORKFLOW}/dispatches`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GH_DISPATCH_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'thetunatracker-scrape-trigger',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: GH_REF }),
  });
  // GitHub returns 204 No Content on a successful dispatch.
  const body = resp.status === 204 ? '' : await resp.text();
  return { ok: resp.status === 204, status: resp.status, body };
}

export default {
  // Hourly Cron Trigger → dispatch the workflow.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      dispatchWorkflow(env).then((r) => {
        console.log('scrape dispatch:', r.status, r.ok ? 'ok' : r.body);
      })
    );
  },

  // Manual trigger for testing, protected by the optional AUTH_TOKEN secret.
  async fetch(request, env) {
    const url = new URL(request.url);
    if (env.AUTH_TOKEN && url.searchParams.get('key') !== env.AUTH_TOKEN) {
      return new Response('Unauthorized', { status: 401 });
    }
    const r = await dispatchWorkflow(env);
    return new Response(JSON.stringify(r), {
      status: r.ok ? 200 : 502,
      headers: { 'Content-Type': 'application/json' },
    });
  },
};
