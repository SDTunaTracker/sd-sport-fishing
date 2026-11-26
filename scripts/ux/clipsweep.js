// No-horizontal-clipping sweep (UX audit). Needs Playwright + Chrome:
//   set NODE_PATH to the repo node_modules, then: node scripts/ux/clipsweep.js http://localhost:8768 . [paths...]
// For each width, flags (a) page-level sideways scroll, (b) visible elements
// that run past the viewport's right edge, (c) text boxes cut off by an
// ancestor with overflow hidden/clip (scrollWidth > clientWidth) that are not
// deliberate ellipsis, and (d) fixed elements covering the page's last content.
const { chromium } = require('playwright');
const [,, base, out, ...rest] = process.argv;
const paths = rest.length ? rest : ['/', '/sd/today', '/sd/tripplanner', '/sd/boats', '/sd/boat/Producer', '/sd/analytics/overview', '/sd/pick',
  '/ocla', '/ocla/tripplanner', '/sfbay', '/sfbay/today'];
(async () => {
  const b = await chromium.launch({ channel: 'chrome' });
  for (const W of [375, 390, 430]) {
    const ctx = await b.newContext({ viewport: { width: W, height: 812 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    const p = await ctx.newPage();
    for (const path of paths) {
      await p.goto(base + path, { waitUntil: 'networkidle', timeout: 60000 }); await p.waitForTimeout(2500);
      const r = await p.evaluate(() => {
        const vw = innerWidth, issues = [];
        const name = e => (e.className && e.className.toString ? e.className.toString().split(' ')[0] : e.tagName) || e.tagName;
        const vis = e => { const s = getComputedStyle(e); const b = e.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && b.width > 0 && b.height > 0; };
        const inScroller = e => { for (let a = e.parentElement; a; a = a.parentElement) { const s = getComputedStyle(a); if (/(auto|scroll)/.test(s.overflowX) && a.scrollWidth > a.clientWidth + 1 && a !== document.documentElement && a !== document.body) return true; } return false; };
        const skip = e => e.closest('.leaflet-container, .charts-immersive, svg, canvas, .sr-only, [aria-hidden="true"]');
        for (const e of document.querySelectorAll('body *')) {
          if (skip(e) || !vis(e)) continue;
          const bx = e.getBoundingClientRect();
          if (bx.right > vw + 1 && !inScroller(e) && e.children.length === 0 && (e.textContent || '').trim()) issues.push('past-edge ' + name(e) + ' "' + e.textContent.trim().slice(0, 24) + '" r=' + Math.round(bx.right));
          const s = getComputedStyle(e);
          if (e.children.length === 0 && (e.textContent || '').trim() && e.scrollWidth > e.clientWidth + 1 && /(hidden|clip)/.test(s.overflowX) && s.textOverflow !== 'ellipsis')
            issues.push('cut ' + name(e) + ' "' + e.textContent.trim().slice(0, 24) + '"');
        }
        // fixed elements over the last content at the bottom of the page
        window.scrollTo(0, document.documentElement.scrollHeight);
        const fixed = [...document.querySelectorAll('body *')].filter(e => getComputedStyle(e).position === 'fixed' && vis(e) && e.getBoundingClientRect().top > innerHeight * 0.6);
        const footer = document.querySelector('footer');
        const main = document.querySelector('.main-content');
        const lastBottom = main ? main.getBoundingClientRect().bottom : 0;
        fixed.forEach(f => { const fb = f.getBoundingClientRect(); if (fb.top < lastBottom - 1 && !(footer && fb.top > footer.getBoundingClientRect().top)) issues.push('fixed-over-content ' + name(f)); });
        return { at: location.pathname, sw: document.documentElement.scrollWidth, issues: [...new Set(issues)].slice(0, 12) };
      });
      const bad = r.sw > W || r.issues.length;
      console.log((bad ? 'FAIL ' : 'ok   ') + W + ' ' + path.padEnd(22) + (r.sw > W ? ' sideways=' + r.sw : '') + (r.issues.length ? ' ' + JSON.stringify(r.issues) : ''));
    }
    await ctx.close();
  }
  await b.close();
})();
