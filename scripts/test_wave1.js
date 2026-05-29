const { chromium } = require('playwright');
const PASS = '\x1b[32m✓\x1b[0m', FAIL = '\x1b[31m✗\x1b[0m';
let failures = 0;
function assert(c, l) { console.log((c ? PASS : FAIL) + ' ' + l); if (!c) failures++; }

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const jsErrors = [];
  page.on('pageerror', e => jsErrors.push(e.message));

  await page.goto('http://localhost:8765/index.html#charts', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  const tabs = await page.locator('.chart-tab').all();
  assert(tabs.length === 8, 'All 8 chart tabs present (got ' + tabs.length + ')');

  // Wind tab
  await page.locator('.chart-tab', { hasText: 'Wind' }).click();
  await page.waitForTimeout(600);
  assert(await page.locator('.chart-map').isVisible(), 'Map visible on Wind tab');
  const condOverlayVisible = await page.locator('.cond-loading-overlay').isVisible().catch(() => false);
  const condIconCount = await page.locator('.cond-icon').count();
  assert(condOverlayVisible || condIconCount > 0, 'Wind: loading pill or condition arrows present');
  const windLegend = await page.locator('.chart-legend-bar').isVisible().catch(() => false);
  assert(windLegend, 'Wind: legend bar visible');

  // Waves tab
  await page.locator('.chart-tab', { hasText: 'Waves' }).click();
  await page.waitForTimeout(600);
  assert(await page.locator('.chart-map').isVisible(), 'Map visible on Waves tab');
  const wavesLegend = await page.locator('.chart-legend-bar').isVisible().catch(() => false);
  assert(wavesLegend, 'Waves: legend bar visible');

  // Tides tab
  await page.locator('.chart-tab', { hasText: 'Tides' }).click();
  await page.waitForTimeout(5000); // NOAA fetch
  const mapHidden = !(await page.locator('.chart-map').isVisible().catch(() => true));
  assert(mapHidden, 'Map hidden on Tides tab');
  assert(await page.locator('.tides-panel').isVisible(), 'TidesPanel rendered');
  const stationText = await page.locator('.tides-station').textContent().catch(() => '');
  assert(stationText.includes('NOAA'), 'Station header shows NOAA (got: "' + stationText + '")');
  const tideRows = await page.locator('.tide-row').count();
  assert(tideRows >= 2, 'At least 2 tide rows (got ' + tideRows + ')');
  const summaryItems = await page.locator('.tides-summary-item').count();
  assert(summaryItems >= 2, 'Summary cards rendered (got ' + summaryItems + ')');
  const tidesLegend = await page.locator('.chart-legend-bar').isVisible().catch(() => false);
  assert(!tidesLegend, 'No legend on Tides tab');

  // Back to SST
  await page.locator('.chart-tab', { hasText: 'Sea Surface' }).click();
  await page.waitForTimeout(1000);
  assert(await page.locator('.chart-map').isVisible(), 'Map visible on SST tab');
  assert(await page.locator('.chart-legend-bar').isVisible(), 'Legend shown on SST tab');

  // Boats Live tab
  await page.locator('.chart-tab', { hasText: 'Boats Live' }).click();
  await page.waitForTimeout(2000);
  assert(await page.locator('.chart-map').isVisible(), 'Map visible on Boats tab');
  const liveBadge = await page.locator('.tab-live-badge').isVisible().catch(() => false);
  assert(liveBadge, 'LIVE badge visible on Boats tab button');
  // No boats yet (no Worker URL configured) — should show map without crash
  const boatsJsError = jsErrors.filter(e => e.includes('boat')).length;
  assert(boatsJsError === 0, 'No JS errors on Boats tab');

  assert(jsErrors.length === 0, 'No JS errors throughout (' + (jsErrors.join('; ') || 'none') + ')');

  await browser.close();
  console.log('\n' + (failures === 0
    ? '\x1b[32m  ALL WAVE 1 CHECKS PASSED\x1b[0m'
    : '\x1b[31m  ' + failures + ' CHECK(S) FAILED\x1b[0m'));
  process.exit(failures > 0 ? 1 : 0);
})();
