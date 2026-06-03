/**
 * P1.2 verification: test every view against the compiled (esbuild IIFE) build.
 * Uses hash-based routing since the local Python dev server has no SPA fallback.
 * Run: node scripts/verify-compiled.js
 */
const { chromium } = require('playwright');

const BASE = 'http://localhost:8765';

// All views: navigate to root, then push the hash to trigger the router.
const VIEWS = [
  { name: 'Home',             hash: '' },
  { name: 'Today',            hash: 'sd/today' },
  { name: 'Forecast',         hash: 'sd/forecast' },
  { name: 'Charts',           hash: 'sd/charts' },
  { name: 'Boats',            hash: 'sd/boats' },
  { name: 'Analytics Ovw',    hash: 'sd/analytics/overview' },
  { name: 'Analytics H2H',    hash: 'sd/analytics/headtohead' },
  { name: 'Analytics Season', hash: 'sd/analytics/seasonality' },
  { name: 'Analytics Moon',   hash: 'sd/analytics/moon' },
  { name: 'Trip Planner',     hash: 'sd/tripplanner' },
  { name: 'Account',          hash: 'sd/account' },
  { name: '404-fallback',     hash: 'sd/totally-unknown-path' },
];

// Errors to always ignore (3rd party, network)
const IGNORE_PATTERNS = [
  /favicon/i, /googletagmanager/i, /clerk/i, /CORS/i,
  /net::ERR/i, /Failed to load resource/i, /unpkg\.com/i,
  /cdnjs\.cloudflare/i, /Content Security Policy/i,
  /aisstream/i, /gibs\.earthdata/i, /leaflet/i,
];

function isIgnored(msg) {
  return IGNORE_PATTERNS.some(re => re.test(msg));
}

(async () => {
  const browser = await chromium.launch({ headless: true });

  let allPassed = true;
  const results = [];

  for (const view of VIEWS) {
    const page = await browser.newPage();
    const errors = [];

    page.on('console', msg => {
      const txt = msg.text();
      if ((msg.type() === 'error' || /is not defined/i.test(txt)) && !isIgnored(txt)) {
        errors.push(`[${msg.type()}] ${txt}`);
      }
    });
    page.on('pageerror', err => {
      if (!isIgnored(err.message)) errors.push(`[pageerror] ${err.message}`);
    });

    try {
      const url = view.hash ? `${BASE}/#${view.hash}` : `${BASE}/`;
      await page.goto(url, { waitUntil: 'networkidle', timeout: 25000 });
      await page.waitForTimeout(2500);

      const rootText = await page.$eval('#root', el => el.textContent).catch(() => '');
      const rootHasContent = rootText.replace(/\s+/g, '').length > 30;

      // For 404-fallback, app falls back to today view — just needs some content
      const passed = errors.length === 0 && rootHasContent;
      if (!passed) allPassed = false;

      results.push({ name: view.name, passed, rootHasContent, errors });
    } catch (e) {
      results.push({ name: view.name, passed: false, rootHasContent: false, errors: [`NAV: ${e.message}`] });
      allPassed = false;
    } finally {
      await page.close();
    }
  }

  await browser.close();

  console.log('\n=== P1.2 Compiled Build Verification ===\n');
  for (const r of results) {
    const icon = r.passed ? '✅' : '❌';
    console.log(`${icon} ${r.name}`);
    if (!r.rootHasContent) console.log(`   (root has no content)`);
    r.errors.forEach(e => console.log(`   ${e}`));
  }

  console.log(`\n${allPassed ? '✅ ALL VIEWS PASS' : '❌ FAILURES — fix missing window exports and re-run'}`);
  process.exit(allPassed ? 0 : 1);
})();
