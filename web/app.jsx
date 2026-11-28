// Main app — routing and tweaks wiring
const { useState: useS, useEffect: useE } = React;

// Run fn after the browser has painted the current frame (so a tap's pressed /
// active state shows first). rAF alone runs before the paint; the timeout
// covers background tabs, where rAF doesn't fire.
function ttAfterPaint(fn) {
  let done = false;
  const go = () => { if (!done) { done = true; fn(); } };
  requestAnimationFrame(() => setTimeout(go, 0));
  setTimeout(go, 120);
}
window.ttAfterPaint = ttAfterPaint;

// Lazy-load Leaflet + leaflet-velocity only when the charts route is first entered.
// The script tags in index.html use type="text/javascript-deferred" so browsers
// skip execution; we inject them dynamically here on first visit to charts.
var _chartsLoadPromise = null;
function _ensureChartsLoaded() {
  if (_chartsLoadPromise) return _chartsLoadPromise;
  if (window.L && window.L.velocityLayer) {
    _chartsLoadPromise = Promise.resolve();
    return _chartsLoadPromise;
  }
  function loadScript(id) {
    return new Promise(function(resolve, reject) {
      var el = document.getElementById(id);
      if (!el) { resolve(); return; }
      var src = el.getAttribute('src');
      if (!src) { resolve(); return; }
      var existing = document.querySelector('script[src="' + src + '"]:not([type])');
      if (existing) {
        // Surftracker adds its own Leaflet <script>; if it is still loading,
        // wait for it, or leaflet-velocity runs before window.L exists.
        if (id !== 'tt-leaflet-js' || window.L) { resolve(); return; }
        existing.addEventListener('load', function() { resolve(); });
        existing.addEventListener('error', reject);
        return;
      }
      var s = document.createElement('script');
      s.src = src;
      var co = el.getAttribute('crossorigin');
      if (co) s.crossOrigin = co;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  _chartsLoadPromise = loadScript('tt-leaflet-js')
    .then(function() { return loadScript('tt-leaflet-vel-js'); })
    .catch(function() {});
  return _chartsLoadPromise;
}

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "comfortable",
  "monthlyView": "tpa",
  "showSpike": true,
  "includeZero": true
}/*EDITMODE-END*/;

// Path-based routing: the URL pathname is the source of truth for the active
// route (e.g. /sd/today, /sd/analytics/overview, /sd/boat/<name>), so it is
// crawlable by search engines and each view is its own real URL.
// Legacy #hash URLs (old bookmarks, chatbot deep links) are auto-upgraded to
// clean paths for backward compatibility.
// Format: /<region-prefix>/<view>[/<params>]  e.g. /sd/today, /ocla/analytics/overview
const HASH_VIEWS = {
  home: 'home', today: 'today', tripplanner: 'tripplanner', pick: 'pick',
  settings: 'account', admin: 'admin', forecast: 'forecast',
  account: 'account', boats: 'boats', charts: 'charts', surf: 'surf',
};

const ANALYTICS_SUBTABS = ['overview', 'finder', 'headtohead', 'seasonality', 'moon', 'halfday'];

function extractRegionFromHash(raw) {
  if (!raw) return { regionIds: null, rest: '' };
  var slash = raw.indexOf('/');
  var first = slash === -1 ? raw : raw.slice(0, slash);
  var ids = window.REGION_HASH_TO_IDS && window.REGION_HASH_TO_IDS[first];
  if (ids) return { regionIds: ids, rest: slash === -1 ? '' : raw.slice(slash + 1) };
  return { regionIds: null, rest: raw };
}

// Parse a route string (no leading '/' or '#'). A trailing ?query is preserved
// in params.query but ignored for view detection.
function parseRoute(raw) {
  if (!raw) return { view: 'home', params: {}, hashRegions: null };
  const qIdx = raw.indexOf('?');
  const query = qIdx === -1 ? '' : raw.slice(qIdx + 1);
  if (qIdx !== -1) raw = raw.slice(0, qIdx);
  const { regionIds, rest } = extractRegionFromHash(raw);
  if (!rest || rest === 'home') return { view: 'home', params: query ? { query } : {}, hashRegions: regionIds };
  const [seg, ...parts] = rest.split('/');
  const detail = parts.length ? decodeURIComponent(parts.join('/')) : '';

  if (seg === 'boat' && detail) return { view: 'boat', params: { boat: detail }, hashRegions: regionIds };
  // Surftracker (discreet surf mode): /sd/surf[/forecast|/map|/cams[/<cam>]|/break/<id>|/paddle[/<spot>]|/races[/<race>]]
  if (seg === 'surf') {
    const sub = ['forecast', 'map', 'break', 'cams', 'paddle', 'races'].includes(parts[0]) ? parts[0] : 'report';
    const spot = (sub === 'break' || sub === 'cams' || sub === 'paddle' || sub === 'races') && parts[1] ? decodeURIComponent(parts[1]) : '';
    return { view: 'surf', params: spot ? { sub, spot } : { sub }, hashRegions: regionIds };
  }
  if (seg === 'landing' && detail) return { view: 'landing', params: { landing: detail }, hashRegions: regionIds };

  if (seg === 'analytics') {
    // Legacy: analytics/boats → top-level boats page
    if (detail === 'boats') return { view: 'boats', params: {}, hashRegions: regionIds };
    // Legacy: analytics/landings → overview (landings is now just a filter)
    const subtab = ANALYTICS_SUBTABS.includes(detail) ? detail : 'overview';
    return { view: 'analytics', params: { subtab }, hashRegions: regionIds };
  }
  // Legacy URL redirects
  if (seg === 'seasonality') {
    const sub = detail === 'moon' ? 'moon' : 'seasonality';
    return { view: 'analytics', params: { subtab: sub }, hashRegions: regionIds };
  }
  if (seg === 'boats')      return { view: 'boats',     params: {},                        hashRegions: regionIds };
  if (seg === 'landings' && regionIds && regionIds[0] === 'sf_bay') return { view: 'landings', params: {}, hashRegions: regionIds };
  if (seg === 'landings')   return { view: 'analytics', params: { subtab: 'overview' },    hashRegions: regionIds };
  if (seg === 'headtohead') return { view: 'analytics', params: { subtab: 'headtohead' },  hashRegions: regionIds };
  if (seg === 'moon')       return { view: 'analytics', params: { subtab: 'moon' },        hashRegions: regionIds };

  if (HASH_VIEWS[seg]) return { view: HASH_VIEWS[seg], params: query ? { query } : {}, hashRegions: regionIds };
  return { view: 'today', params: {}, hashRegions: regionIds };
}

// Read the current route from the URL — prefer the pathname; fall back to a
// legacy #hash so old bookmarked URLs still resolve.
function rawFromLocation() {
  const path = window.location.pathname.replace(/^\/+/, '').replace(/\/+$/, '');
  if (path) return path + (window.location.search || '');
  return window.location.hash.replace(/^#/, '');
}
function routeFromLocation() { return parseRoute(rawFromLocation()); }

// Build a clean path (e.g. /sd/today) from a route, including the region prefix.
function pathFromRoute(view, params = {}, regions = ['san_diego']) {
  const prefix = window.regionsToHashPrefix ? window.regionsToHashPrefix(regions) : 'sd';
  let route;
  if (view === 'home') route = 'home';
  else if (view === 'boat' && params.boat) route = 'boat/' + encodeURIComponent(params.boat);
  else if (view === 'landing' && params.landing) route = 'landing/' + encodeURIComponent(params.landing);
  else if (view === 'analytics') route = 'analytics/' + (params.subtab || 'overview');
  else if (view === 'boats') route = 'boats';
  else if (view === 'surf') route = 'surf' + (params.sub && params.sub !== 'report' ? '/' + params.sub : '')
    + ((params.sub === 'break' || params.sub === 'cams' || params.sub === 'paddle' || params.sub === 'races') && params.spot ? '/' + encodeURIComponent(params.spot) : '');
  else route = view;
  return '/' + prefix + '/' + route;
}
window.ttPathFromRoute = pathFromRoute;

// Views that only read recent trips (30-120 day windows, this season), all of
// which data.js carries. Every other view waits for data-history.js.
const HISTORY_FREE_VIEWS = { home: 1, today: 1, charts: 1, forecast: 1, surf: 1, pick: 1, account: 1 };

// Shown while a region's data file (web/region-data.js) loads on first use,
// and (history) while San Diego's older seasons load.
function RegionLoading({ regions, error, onRetry, history }) {
  const label = window.getRegionSubtitle ? window.getRegionSubtitle(regions) : 'this region';
  if (error) {
    return (
      <div className="region-loading" role="alert">
        <div className="region-loading-title">Couldn't load {history ? 'past seasons of ' : ''}{label} fish counts.</div>
        <div className="region-loading-sub">Check your connection and try again.</div>
        <button className="btn primary" onClick={onRetry}>Try again</button>
      </div>
    );
  }
  return (
    <div className="region-loading" role="status" aria-live="polite" aria-busy="true">
      <div className="region-loading-title"><span className="region-loading-spinner" aria-hidden="true"></span>Loading {history ? 'past seasons of ' : ''}{label} fish counts…</div>
      <div className="region-loading-sub">{history ? 'Older trips download once, then stay on this device.' : 'One-time download for this region.'}</div>
      {window.SkeletonRows && <SkeletonRows count={6}/>}
    </div>
  );
}

// Views kept mounted by App's keep-alive. Hidden ones are display:none and
// never re-render; the active one re-renders only when its props (or the
// region-data tick) change, not on every App render (tab highlight, busy bar).
const KEEP_ALIVE_MAX = 6;
function _shallowSame(a, b) {
  const ka = Object.keys(a), kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  for (const k of ka) if (a[k] !== b[k]) return false;
  return true;
}
// Inner part: renders the view. Skips while hidden, and on show when nothing
// it reads changed, so switching back to a kept tab only flips display.
const KeptInner = React.memo(function KeptInner({ type, props }) {
  return React.createElement(type, props);
}, (prev, next) => next.hidden || (prev.type === next.type && prev.tick === next.tick
  && _shallowSame(prev.props, next.props)));
function KeptView({ active, type, props, tick }) {
  return (
    <div className="tt-kept" style={active ? undefined : { display: 'none' }}>
      <KeptInner type={type} props={props} tick={tick} hidden={!active}/>
    </div>
  );
}

function App() {
  const [route, setRoute] = useS(() => routeFromLocation());
  const [navBusy, setNavBusy] = useS(false);
  const [filters, setFilters] = useS({ ...DEFAULT_FILTERS });
  const [tweaks, setTweaksState] = useTweaks(TWEAK_DEFAULTS);
  const [chartsReady, setChartsReady] = useS(function() {
    return !!(window.L && window.L.velocityLayer);
  });
  const [pageContext, setPageContext] = useS({ page: 'today', boat: null, date: null });

  // Clerk auth state — hook must be at top level.
  const { user, isSignedIn } = useAuth();

  // One region at a time: normalizeRegions (regions.js) turns any combination,
  // e.g. a saved or linked "All SoCal", into San Diego.
  const _norm = (ids) => (window.normalizeRegions ? window.normalizeRegions(ids) : ids);
  const [regions, setRegions] = useS(() => _norm((() => {
    // SF Bay Area (behind SHOW_SFBAY): a /sfbay/... URL or a saved choice wins.
    if (window.FEATURES && window.FEATURES.SHOW_SFBAY) {
      const r0 = routeFromLocation();
      if (r0.hashRegions && r0.hashRegions[0] === 'sf_bay') return ['sf_bay'];
      if (!r0.hashRegions) {
        try {
          const saved = JSON.parse(localStorage.getItem('tt_regions'));
          if (Array.isArray(saved) && saved[0] === 'sf_bay') return ['sf_bay'];
        } catch(e) {}
      }
    }
    // Feature flag: OC/LA is not public yet — lock to SD-only.
    if (!window.FEATURES || !window.FEATURES.SHOW_OCLA) return ['san_diego'];
    const initial = routeFromLocation();
    if (initial.hashRegions) return initial.hashRegions;
    try {
      const saved = JSON.parse(localStorage.getItem('tt_regions'));
      if (Array.isArray(saved) && saved.length > 0) return saved;
    } catch(e) {}
    // Migrate old single-region localStorage key
    const old = localStorage.getItem('tt_region');
    if (old === 'oc_la')     return ['oc_la'];
    return ['san_diego'];
  })()));

  // Replace a retired combined selection in localStorage so it doesn't come back.
  useE(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('tt_regions'));
      if (Array.isArray(saved) && saved.length > 1) localStorage.setItem('tt_regions', JSON.stringify(regions));
    } catch(e) {}
  }, []);

  // Strip any oc_la / sf_bay that leaked in from localStorage/hash when its flag is off.
  useE(() => {
    if (regions.includes('sf_bay') && !(window.FEATURES && window.FEATURES.SHOW_SFBAY)) {
      const next = ['san_diego'];
      setRegions(next);
      try { localStorage.setItem('tt_regions', JSON.stringify(next)); } catch(e) {}
      return;
    }
    if (regions.includes('sf_bay')) return;
    if (!window.FEATURES || !window.FEATURES.SHOW_OCLA) {
      if (regions.includes('oc_la')) {
        const next = ['san_diego'];
        setRegions(next);
        try { localStorage.setItem('tt_regions', JSON.stringify(next)); } catch(e) {}
      }
    }
  }, [regions]);

  // Settings: trophy species + trip length methodology, persisted to localStorage.
  // Trips are preprocessed (totalTuna, calcDays) synchronously, before the first
  // render. When this ran in a post-mount effect, any page without its own guard
  // (Boats, boat detail, landing detail) memoized the raw trips on first render
  // and showed 0.00 tuna/angler and an empty catch-rate chart.
  const [settings, setSettingsState] = useS(() => {
    const s = loadSettings();
    SDA.preprocessTrips(s);
    SDA.preprocessHalfDayTrips(s);
    return s;
  });
  // Non-base regions (OC/LA, ...) ship in their own data file, loaded the first
  // time the visitor selects them. Until it's merged into window.SD, the page
  // shows RegionLoading instead of rendering with that region missing.
  const [regionDataTick, setRegionDataTick] = useS(0);
  const [regionLoadError, setRegionLoadError] = useS(null);
  const regionDataReady = !window.ttRegionData || window.ttRegionData.isLoaded(regions);
  // The headline metric depends on the region (OC/LA counts all species, see
  // SDA.metricFor), so re-derive SD_PROC_TRIPS synchronously, before this
  // render's children read it, whenever the effective region changes.
  const metricRegion = window.getEffectiveRegion ? window.getEffectiveRegion(regions) : 'san_diego';
  if (window.SD_METRIC_REGION !== metricRegion) {
    SDA.preprocessTrips(settings, metricRegion);
    SDA.preprocessHalfDayTrips(settings, metricRegion);
  }
  useE(() => {
    if (regionDataReady) return;
    setRegionLoadError(null);
    window.ttRegionData.ensure(regions).then(() => {
      // Re-derive SD_PROC_TRIPS with the merged rows (current saved settings).
      const s = loadSettings();
      SDA.preprocessTrips(s);
      SDA.preprocessHalfDayTrips(s);
      setRegionDataTick(t => t + 1);
    }).catch(e => setRegionLoadError((e && e.message) || String(e)));
  }, [regions, regionDataReady, regionDataTick]);

  // Older San Diego trips (data-history.js) download right after data.js.
  // Views in HISTORY_FREE_VIEWS render without them; the rest show
  // RegionLoading until they're merged. Either way SD_PROC_TRIPS is re-derived
  // once they arrive, so every page ends up with every year.
  const [historyTick, setHistoryTick] = useS(0);
  const [historyRetry, setHistoryRetry] = useS(0);
  const [historyError, setHistoryError] = useS(null);
  const historyReady = !window.ttRegionData || !window.ttRegionData.historyLoaded
    || window.ttRegionData.historyLoaded();
  useE(() => {
    if (!window.ttRegionData || !window.ttRegionData.ensureHistory) return;
    let live = true;
    setHistoryError(null);
    window.ttRegionData.ensureHistory().then(() => {
      if (!live) return;
      // Skip the re-derive when history was merged before the first one ran.
      if (window.SD_PROC_SRC_LEN !== window.SD.TRIPS.length) SDA.preprocessTrips(loadSettings());
      setHistoryTick(t => t + 1);
    }).catch(e => { if (live) setHistoryError((e && e.message) || String(e)); });
    return () => { live = false; };
  }, [historyRetry]);

  function onSettingsChange(next) {
    saveSettings(next);
    SDA.preprocessTrips(next);
    SDA.preprocessHalfDayTrips(next);
    setSettingsState(next);
  }

  // When a user signs in, pull their saved region and species from Clerk metadata.
  useE(() => {
    if (!isSignedIn || !window.getUserPref) return;
    const CHOICE_MAP = { san_diego: ['san_diego'], oc_la: ['oc_la'], all_socal: ['san_diego'] };
    if (window.FEATURES && window.FEATURES.SHOW_SFBAY) CHOICE_MAP.sf_bay = ['sf_bay'];
    const savedChoice = window.getUserPref('region_choice', null);
    if (savedChoice && CHOICE_MAP[savedChoice]) {
      setRegionsDirect(CHOICE_MAP[savedChoice]);
    }
    const savedSpecies = window.getUserPref('trophySpecies', null);
    if (savedSpecies && Array.isArray(savedSpecies)) {
      const next = { ...settings, trophySpecies: savedSpecies };
      saveSettings(next);
      SDA.preprocessTrips(next);
    SDA.preprocessHalfDayTrips(next);
      setSettingsState(next);
    }
    const savedMethod = window.getUserPref('tripLengthMethod', null);
    if (savedMethod) {
      const next = { ...settings, tripLengthMethod: savedMethod };
      saveSettings(next);
      setSettingsState(next);
    }
    const savedUnits = window.getUserPref('unitSystem', null);
    if (savedUnits) {
      const next = { ...settings, unitSystem: savedUnits };
      saveSettings(next);
      setSettingsState(next);
    }
    // Six-pack toggle: null = never set → keep default (OFF). Explicit true/false wins.
    const savedSixpack = window.getUserPref('includeSixPackCharters', null);
    if (savedSixpack !== null) {
      const next = { ...settings, includeSixPackCharters: !!savedSixpack };
      saveSettings(next);
      SDA.preprocessTrips(next);
    SDA.preprocessHalfDayTrips(next);  // re-run — toggle changes analytics universe
      setSettingsState(next);
    }
  }, [isSignedIn, user && user.id]);

  // Sync effective region to global so filterTrips picks it up automatically.
  useE(() => {
    window.CURRENT_REGION = window.getEffectiveRegion
      ? window.getEffectiveRegion(regions)
      : regions[0];
  }, [regions]);

  // Keep the URL path in sync with the active route + region prefix. navigate()
  // already pushes the right path, so this is a no-op except when the region
  // toggles (which changes the prefix without a navigation).
  useE(() => {
    const newPath = pathFromRoute(route.view, route.params || {}, regions);
    if (window.location.pathname !== newPath) {
      history.replaceState(null, '', newPath);
    }
  }, [regions, route]);

  function setRegionsDirect(newRegions) {
    const cleaned = _norm(Array.isArray(newRegions) && newRegions.length > 0 ? newRegions : ['san_diego']);
    setRegions(cleaned);
    try { localStorage.setItem('tt_regions', JSON.stringify(cleaned)); } catch(e) {}
    setFilters(f => ({ ...f, landing: 'all', boat: 'all' }));
  }

  // Regions are single-select (no combined "All SoCal" view since 2026-11-26).
  function toggleRegion(regionId) {
    setRegionsDirect([regionId]);
  }

  // expose tweak setter for inline buttons in dashboard
  window.__setTweak = (patch) => setTweaksState(patch);

  // Sync filter.includeZero with tweak
  useE(() => {
    if (filters.includeZero !== tweaks.includeZero) {
      setFilters(f => ({ ...f, includeZero: tweaks.includeZero }));
    }
  }, [tweaks.includeZero]);

  // Density on body
  useE(() => {
    document.body.classList.toggle('compact', tweaks.density === 'compact');
  }, [tweaks.density]);

  // Keep route in sync with browser navigation (back/forward = popstate) and
  // bridge any legacy #hash navigation to a clean path.
  useE(() => {
    const applyParsed = (parsed) => {
      // Same page (e.g. back out of the Charts layers sheet's history entry,
      // or navigate()'s belt-and-braces popstate): keep the same route object
      // so the whole app doesn't re-render. That cost ~0.5 s on a mid phone.
      React.startTransition(() => setRoute(prev => (prev && prev.view === parsed.view &&
        JSON.stringify(prev.params || {}) === JSON.stringify(parsed.params || {}))
        ? prev : { view: parsed.view, params: parsed.params }));
      if (parsed.hashRegions) {
        setRegions(prev => {
          const same = parsed.hashRegions.length === prev.length &&
            parsed.hashRegions.every(x => prev.includes(x));
          if (same) return prev;
          localStorage.setItem('tt_regions', JSON.stringify(parsed.hashRegions));
          return parsed.hashRegions;
        });
      }
    };
    // On mount: if we arrived via a legacy #hash URL, upgrade it to a clean path.
    if (window.location.hash) {
      const h = window.location.hash.replace(/^#/, '');
      if (h) {
        const p = parseRoute(h);
        history.replaceState(null, '', pathFromRoute(p.view, p.params, p.hashRegions || regions));
      }
    }
    const onPop = () => applyParsed(routeFromLocation());
    // Legacy bridge: other code (chatbot, account link) still does
    // `window.location.hash = '#boat/X'`. Catch it, upgrade to a path, route.
    const onHash = () => {
      const h = window.location.hash.replace(/^#/, '');
      if (!h) return;
      const parsed = parseRoute(h);
      history.replaceState(null, '', pathFromRoute(parsed.view, parsed.params, parsed.hashRegions || regions));
      applyParsed(parsed);
      window.scrollTo({ top: 0, behavior: 'instant' });
    };
    window.addEventListener('popstate', onPop);
    window.addEventListener('hashchange', onHash);
    return () => {
      window.removeEventListener('popstate', onPop);
      window.removeEventListener('hashchange', onHash);
    };
  }, []);

  // Lazy-load Leaflet when charts route is first visited.
  useE(function() {
    if (route.view !== 'charts' || chartsReady) return;
    _ensureChartsLoaded().then(function() { setChartsReady(true); });
  }, [route.view, chartsReady]);

  // Pre-warm the Charts view during idle time so it appears instantly when
  // first opened — no "Loading map…" wait. We (1) load the Leaflet library
  // (cached by the service worker for repeat visits) and (2) prime the SST
  // grid + basemap tiles for the default San Diego view.
  useE(function() {
    var warmData = function() { if (window.__ttPrewarmCharts) window.__ttPrewarmCharts(); };
    if (window.L && window.L.velocityLayer) { warmData(); return; }
    var ric = window.requestIdleCallback || function(fn) { return setTimeout(fn, 1500); };
    var cancel = window.cancelIdleCallback || clearTimeout;
    // Not before the page's load event: that waits for data-history.js, and
    // the prewarm's ~250 KB (Leaflet, tiles, SST grid) would otherwise share a
    // phone's bandwidth with it (measured: history finished 10.1 s -> later).
    var id = null, gone = false;
    var start = function() { if (!gone) id = ric(function() { _ensureChartsLoaded(); warmData(); }, { timeout: 4000 }); };
    if (document.readyState === 'complete') start();
    else window.addEventListener('load', start, { once: true });
    return function() {
      gone = true;
      window.removeEventListener('load', start);
      try { if (id != null) cancel(id); } catch (e) {}
    };
  }, []);

  // Fire page view tracking on every route change.
  useE(() => {
    if (window.TTTrack) TTTrack.pageView(route.view);
  }, [route.view]);

  // Update SEO meta tags on every route change — more reliable than hashchange
  // alone because React sometimes updates route state without touching the hash
  // (replaceState for region prefix, or same-hash re-navigation).
  // TODO: per-route canonical — update <link rel="canonical"> here once hash
  // routing is migrated to path-based routes (see links/routing spec).
  useE(() => {
    if (window.__updateMetaTags) window.__updateMetaTags(route.view, route.params || {});
    // regions: switching region on the same view (SD Today -> SF Bay Today) changes the URL and title.
  }, [route.view, route.params?.boat, route.params?.subtab, regionDataTick, regions.join(',')]);

  // Lock the document scroll context when the full-bleed Charts map is active.
  useE(() => {
    const root = document.documentElement;
    if (route.view === 'charts') {
      root.classList.add('charts-open');
    } else {
      root.classList.remove('charts-open');
    }
    return () => root.classList.remove('charts-open');
  }, [route.view]);

  // Keep pageContext in sync with route and regions for the chatbot.
  useE(() => {
    setPageContext({
      page: route.view,
      boat: route.params?.boat || null,
      date: null,
      region: window.getEffectiveRegion ? window.getEffectiveRegion(regions) : regions[0],
      regions,
    });
  }, [route, regions]);

  // Admin moved to /owner/admin/ behind Cloudflare Access (no client-side password,
  // no admin data in data.js). Old #admin / /sd/admin links redirect there.
  // Must be after all hooks (React rules: no conditional hooks).
  // Tab switching (see navigate() below). Hooks live here, above the admin
  // early return.
  const [pendingRoute, setPendingRoute] = useS(null);
  const keepAlive = React.useRef(new Map());   // App's keep-alive (KeptView)
  // One function for every render, so views kept mounted (KeepAlive) don't
  // re-render just because App did.
  const navigateRef = React.useRef(null);
  const stableNavigate = React.useCallback((v, p) => navigateRef.current(v, p), []);
  // When the new view has committed: drop the pending highlight and the bar,
  // and show it from the top (not on the first render).
  const routeSeen = React.useRef(false);
  React.useLayoutEffect(() => {
    setPendingRoute(null);
    setNavBusy(false);
    window.clearTimeout(window.__ttNavBusyTimer);
    if (routeSeen.current) window.scrollTo({ top: 0, behavior: 'instant' });
    routeSeen.current = true;
  }, [route]);

  if (route.view === 'admin') { window.location.replace('/owner/admin/'); return null; }

  // Tab and page switches answer the tap in the next frame: navigate() first
  // sets only pendingRoute (the tab highlight) and the top progress bar, the
  // browser paints that, and only then is the new view rendered, as a React
  // transition so a long render yields to further taps. Measured on a 4x
  // throttled phone, the tap used to wait for the whole new view (up to
  // seconds on Boats or Analytics) before anything on screen changed.
  const navigate = (view, params = {}) => {
    const nextPath = pathFromRoute(view, params, regions);
    const changing = nextPath !== window.location.pathname || view !== route.view;
    if (changing) {
      setPendingRoute({ view, params });
      setNavBusy(true);
      window.clearTimeout(window.__ttNavBusyTimer);
      // Safety net only; the route effect below clears it when the view commits.
      window.__ttNavBusyTimer = window.setTimeout(() => setNavBusy(false), 8000);
    }
    if (window.location.pathname !== nextPath) {
      history.pushState(null, '', nextPath); // pushState does not fire popstate
      // Charts' "Exit map" goes back only when the previous entry is ours.
      window.__ttInAppNavs = (window.__ttInAppNavs || 0) + 1;
    }
    ttAfterPaint(() => {
      // Belt-and-suspenders: some mobile browsers dropped the setRoute() call
      // when it came right after a preventDefault()+pushState on an <a href>
      // touch click, leaving the URL updated but the view stale until a
      // manual refresh. Firing popstate makes the router's onPop handler
      // (applyParsed) a second, independent path, so the view can't stay
      // behind the URL. Both now run after the tap's feedback has painted.
      try { window.dispatchEvent(new PopStateEvent('popstate')); }
      catch (e) { /* PopStateEvent unsupported on very old browsers; ignore */ }
      React.startTransition(() => setRoute(prev => (prev && prev.view === view &&
        JSON.stringify(prev.params || {}) === JSON.stringify(params || {})) ? prev : { view, params }));
    });
  };
  navigateRef.current = navigate;

  // Map nav tab id -> navigate() view
  const navMap = {
    home: 'home', today: 'today', forecast: 'forecast', analytics: 'analytics',
    tripplanner: 'tripplanner', account: 'account', boats: 'boats', charts: 'charts',
    landings: 'landings', pick: 'pick', surf: 'surf',
  };

  const isSfbay = regions[0] === 'sf_bay';
  // Surftracker: /sd/surf/* swaps the header and footer for the surf mode's own.
  const isSurf = route.view === 'surf' && !isSfbay;
  let content;
  if (isSfbay && route.view !== 'account') {
    content = <SFBayView view={route.view} params={route.params || {}} navigate={stableNavigate}/>;
  } else if (route.view === 'home') {
    content = <HomeView navigate={stableNavigate} settings={settings} regions={regions}/>;
  } else if (route.view === 'today') {
    content = <TodayView navigate={stableNavigate} settings={settings} regions={regions}/>;
  } else if (route.view === 'surf' && window.SurfView) {
    content = <SurfView navigate={stableNavigate} sub={route.params.sub || 'report'} spot={route.params.spot || ''}/>;
  } else if (route.view === 'pick' && window.PickTripView) {
    content = <PickTripView navigate={stableNavigate} regions={regions}/>;
  } else if (route.view === 'analytics') {
    content = <AnalyticsView filters={filters} setFilters={setFilters} navigate={stableNavigate} tweaks={tweaks} settings={settings} regions={regions} subtab={route.params.subtab || 'overview'}/>;
  } else if (route.view === 'boats') {
    content = <BoatsView filters={filters} setFilters={setFilters} navigate={stableNavigate} tweaks={tweaks} settings={settings} regions={regions}/>;
  } else if (route.view === 'boat') {
    content = <BoatDetail filters={filters} setFilters={setFilters} navigate={stableNavigate} boat={route.params.boat} regions={regions}/>;
  } else if (route.view === 'landing') {
    content = <LandingDetail filters={filters} setFilters={setFilters} navigate={stableNavigate} landing={route.params.landing} regions={regions}/>;
  } else if (route.view === 'tripplanner') {
    content = <TripPlanner filters={filters} setFilters={setFilters} navigate={stableNavigate} tweaks={tweaks} regions={regions}/>;
  } else if (route.view === 'forecast') {
    // Forecast page soft-retired (2026-09-06). Rewrite the URL hash to
    // #charts and render Charts. Route entry + ForecastView import kept
    // so `git revert` restores the page in one line.
    if (typeof window !== 'undefined' && window.history && window.history.replaceState) {
      try { window.history.replaceState(null, '', '#charts'); } catch (e) {}
    }
    content = chartsReady
      ? <ChartsView navigate={stableNavigate} settings={settings} regions={regions}/>
      : <div className="charts-map-loading"><div className="charts-map-loading-text">Loading map…</div></div>;
  } else if (route.view === 'charts') {
    content = chartsReady
      ? <ChartsView navigate={stableNavigate} settings={settings} regions={regions}/>
      : <div className="charts-map-loading"><div className="charts-map-loading-text">Loading map…</div></div>;
  } else if (route.view === 'account') {
    content = <MyAccountView settings={settings} onSettingsChange={onSettingsChange}
                              regions={regions} onRegionsDirect={setRegionsDirect} navigate={stableNavigate}/>;
  }

  if (!regionDataReady && route.view !== 'account' && route.view !== 'surf') {
    content = <RegionLoading regions={regions} error={regionLoadError}
                             onRetry={() => setRegionDataTick(t => t + 1)}/>;
  } else if (!historyReady && !HISTORY_FREE_VIEWS[route.view] && regions.includes('san_diego')) {
    content = <RegionLoading regions={regions} history error={historyError}
                             onRetry={() => setHistoryRetry(t => t + 1)}/>;
  }

  // The header highlights the tab being opened right away (pendingRoute),
  // before the view itself has rendered.
  const shown = pendingRoute || route;
  const headerActive = shown.view === 'boat' ? 'boats'
    : shown.view === 'pick' ? 'today'
    : (isSfbay && shown.view === 'home') ? 'today'
    : shown.view === 'landing' ? (isSfbay ? 'landings' : 'analytics')
    : shown.view;

  // Keep the last few views mounted (hidden) so switching back is instant:
  // no recompute over every trip, no new Leaflet map. Loading panels, the
  // account page and SF Bay render as before.
  const keepKey = (content && typeof content.type === 'function'
    && content.type !== RegionLoading
    && !(typeof MyAccountView !== 'undefined' && content.type === MyAccountView)
    && !(typeof SFBayView !== 'undefined' && content.type === SFBayView))
    // Region and settings are part of the key: several views compute things
    // once per mount (useMemo with []), so a different region or new settings
    // gets a fresh instance, as a remount always did.
    ? [route.view, JSON.stringify(route.params || {}), regions.join(','), JSON.stringify(settings)].join(' ') : null;
  // ...and a 15-minute slot: Surftracker / Paddle read hourly files and work
  // out "now" when they render, so a view older than that is remounted (fresh
  // data, fresh clock) instead of shown; its old copy is dropped.
  const keepSlot = Math.floor(Date.now() / (15 * 60000));
  if (keepKey) {
    const m = keepAlive.current;
    const old = m.get(keepKey);
    // Only when switching to it: a view you're looking at is never remounted.
    const stale = !!old && m.__active !== keepKey && old.slot !== keepSlot;
    m.delete(keepKey);
    m.set(keepKey, { type: content.type, props: content.props,
                     slot: !old || stale ? keepSlot : old.slot,
                     gen: !old ? 0 : old.gen + (stale ? 1 : 0) });
    m.__active = keepKey;
    // One kept copy per route: drop copies of this route kept for another
    // region or settings. Two live copies of a Surftracker page would also
    // hand its cached Leaflet map (surf.jsx _sfMaps) back and forth.
    const base = route.view + ' ' + JSON.stringify(route.params || {}) + ' ';
    for (const k of [...m.keys()]) if (k !== keepKey && k.startsWith(base)) m.delete(k);
    while (m.size > KEEP_ALIVE_MAX) m.delete(m.keys().next().value);
  }
  if (!keepKey) keepAlive.current.__active = null;
  // Kept views stay mounted (hidden) even while a loading panel or an
  // uncached page (Account) is showing.
  const mainBody = [...keepAlive.current.entries()].map(([k, v]) => (
    <KeptView key={k + ' #' + v.gen} active={k === keepKey} type={v.type} props={v.props} tick={regionDataTick}/>));
  if (!keepKey && content) mainBody.push(<React.Fragment key="tt-uncached">{content}</React.Fragment>);

  return (
    <React.Fragment>
      <div className={`tt-nav-progress${navBusy ? ' on' : ''}`} aria-hidden="true"/>
      {isSurf && window.SurftrackerHeader
        ? <SurftrackerHeader sub={(shown.view === 'surf' ? shown.params : route.params).sub || 'report'} navigate={stableNavigate}/>
        : <AppHeader active={headerActive} onNavigate={(id) => navigate(navMap[id] || 'today')}
                     hrefFor={(id) => pathFromRoute(navMap[id] || 'today', {}, regions)}
                     regions={regions} onRegionToggle={toggleRegion} onRegionsDirect={setRegionsDirect}/>}
      <main className={`main-content${isSurf ? ' st-main' : ''}`} data-screen-label={route.view}>{mainBody}</main>
      {isSurf && window.SurftrackerFooter ? <SurftrackerFooter navigate={navigate}/>
        : isSfbay ? <SFBayFooter/> : <AppFooter regions={regions}/>}

      {route.view === 'tripplanner' && !isSfbay && regionDataReady && <ChatBot pageContext={pageContext}/>}
      {route.view === 'tripplanner' && window.PickFab && !isSfbay && regionDataReady && <PickFab navigate={navigate} regions={regions}/>}

      <TweaksPanel title="Tweaks">
        <TweakSection title="Display">
          <TweakRadio label="Density" value={tweaks.density} options={[
            { value: 'comfortable', label: 'Comfortable' },
            { value: 'compact', label: 'Compact' },
          ]} onChange={v => setTweaksState({ density: v })}/>
        </TweakSection>
        <TweakSection title="Charts">
          <TweakRadio label="Monthly chart shows" value={tweaks.monthlyView} options={[
            { value: 'tpa', label: 'Per Angler' },
            { value: 'total', label: 'Total Catch' },
          ]} onChange={v => setTweaksState({ monthlyView: v })}/>
          <TweakToggle label="Show spike-trip warnings" value={tweaks.showSpike}
                       onChange={v => setTweaksState({ showSpike: v })}/>
        </TweakSection>
        <TweakSection title="Data">
          <TweakToggle label="Include zero-tuna trips" value={tweaks.includeZero}
                       onChange={v => setTweaksState({ includeZero: v })}/>
        </TweakSection>
        <TweakSection title="Quick Filters">
          <TweakSelect label="Year" value={filters.year}
                       options={[{value:'all',label:'All'}, ...[...new Set(window.SD.TRIPS.map(t => t.year))].sort((a,b) => b-a).map(y => ({value:String(y),label:String(y)}))]}
                       onChange={v => setFilters({ ...filters, year: v })}/>
          <TweakSelect label="Species focus" value={filters.species}
                       options={[{value:'all',label:SDA.headlineIsAllSpecies() ? 'All species' : 'All Tuna'},{value:'Bluefin',label:'Bluefin'},{value:'Yellowfin',label:'Yellowfin'},{value:'Yellowtail',label:'Yellowtail'},{value:'Dorado',label:'Dorado'},{value:'Skipjack',label:'Skipjack'},{value:'Bigeye',label:'Bigeye'},{value:'Albacore',label:'Albacore'}]}
                       onChange={v => setFilters({ ...filters, species: v })}/>
        </TweakSection>
      </TweaksPanel>
    </React.Fragment>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(err) {
    return { error: err };
  }
  componentDidCatch(err, info) {
    if (window.gtag) gtag('event', 'js_error_boundary', { description: String(err), fatal: false });
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{padding:'32px 24px',maxWidth:480,margin:'60px auto',fontFamily:'system-ui,sans-serif'}}>
          <div style={{fontSize:18,fontWeight:700,color:'#0F2A4A',marginBottom:8}}>Something went wrong</div>
          <div style={{fontSize:14,color:'#64748B',marginBottom:20,lineHeight:1.5}}>
            {String(this.state.error.message || this.state.error)}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{background:'#38BDF8',color:'white',border:'none',borderRadius:8,padding:'10px 20px',fontSize:14,cursor:'pointer'}}
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary><App/></ErrorBoundary>
);
