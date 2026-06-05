// Main app — routing and tweaks wiring
const { useState: useS, useEffect: useE } = React;

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
      if (document.querySelector('script[src="' + src + '"]:not([type])')) { resolve(); return; }
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
  home: 'home', today: 'today', tripplanner: 'tripplanner',
  settings: 'account', admin: 'admin', forecast: 'forecast',
  account: 'account', boats: 'boats', charts: 'charts',
};

const ANALYTICS_SUBTABS = ['overview', 'finder', 'headtohead', 'seasonality', 'moon'];

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
  else route = view;
  return '/' + prefix + '/' + route;
}
window.ttPathFromRoute = pathFromRoute;

function App() {
  const [route, setRoute] = useS(() => routeFromLocation());
  const [filters, setFilters] = useS({ ...DEFAULT_FILTERS });
  const [tweaks, setTweaksState] = useTweaks(TWEAK_DEFAULTS);
  const [chartsReady, setChartsReady] = useS(function() {
    return !!(window.L && window.L.velocityLayer);
  });
  const [pageContext, setPageContext] = useS({ page: 'today', boat: null, date: null });

  // Clerk auth state — hook must be at top level.
  const { user, isSignedIn } = useAuth();

  const [regions, setRegions] = useS(() => {
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
    if (old === 'all_socal') return ['san_diego', 'oc_la'];
    return ['san_diego'];
  });

  // Strip any oc_la that leaked in from localStorage/hash when flag is off.
  useE(() => {
    if (!window.FEATURES || !window.FEATURES.SHOW_OCLA) {
      if (regions.includes('oc_la')) {
        const next = ['san_diego'];
        setRegions(next);
        try { localStorage.setItem('tt_regions', JSON.stringify(next)); } catch(e) {}
      }
    }
  }, [regions]);

  // Settings: trophy species + trip length methodology, persisted to localStorage.
  const [settings, setSettingsState] = useS(() => loadSettings());
  function onSettingsChange(next) {
    saveSettings(next);
    SDA.preprocessTrips(next);
    setSettingsState(next);
  }
  // Initialize processed trips on first render.
  useE(() => { SDA.preprocessTrips(settings); }, []);

  // When a user signs in, pull their saved region and species from Clerk metadata.
  useE(() => {
    if (!isSignedIn || !window.getUserPref) return;
    const CHOICE_MAP = { san_diego: ['san_diego'], oc_la: ['oc_la'], all_socal: ['san_diego', 'oc_la'] };
    const savedChoice = window.getUserPref('region_choice', null);
    if (savedChoice && CHOICE_MAP[savedChoice]) {
      setRegionsDirect(CHOICE_MAP[savedChoice]);
    }
    const savedSpecies = window.getUserPref('trophySpecies', null);
    if (savedSpecies && Array.isArray(savedSpecies)) {
      const next = { ...settings, trophySpecies: savedSpecies };
      saveSettings(next);
      SDA.preprocessTrips(next);
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
    const cleaned = Array.isArray(newRegions) && newRegions.length > 0 ? newRegions : ['san_diego'];
    setRegions(cleaned);
    try { localStorage.setItem('tt_regions', JSON.stringify(cleaned)); } catch(e) {}
    setFilters(f => ({ ...f, landing: 'all', boat: 'all' }));
  }

  function toggleRegion(regionId) {
    setRegions(prev => {
      let next;
      if (prev.includes(regionId)) {
        if (prev.length === 1) return prev; // at-least-one constraint
        next = prev.filter(r => r !== regionId);
      } else {
        // Keep consistent order matching REGIONS array order
        const order = (window.REGIONS || []).map(r => r.id);
        next = [...prev, regionId].sort((a, b) => order.indexOf(a) - order.indexOf(b));
      }
      localStorage.setItem('tt_regions', JSON.stringify(next));
      return next;
    });
    setFilters(f => ({ ...f, landing: 'all', boat: 'all' }));
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
      setRoute({ view: parsed.view, params: parsed.params });
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
    var id = ric(function() { _ensureChartsLoaded(); warmData(); }, { timeout: 4000 });
    return function() { try { cancel(id); } catch (e) {} };
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
  }, [route.view, route.params?.boat, route.params?.subtab]);

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

  // Admin is a fully standalone page — no header, no nav, no shared state used.
  // Must be after all hooks (React rules: no conditional hooks).
  if (route.view === 'admin') return <AdminView />;

  const navigate = (view, params = {}) => {
    const nextPath = pathFromRoute(view, params, regions);
    if (window.location.pathname !== nextPath) {
      history.pushState(null, '', nextPath); // pushState does not fire popstate
    }
    setRoute({ view, params });
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  // Map nav tab id -> navigate() view
  const navMap = {
    home: 'home', today: 'today', forecast: 'forecast', analytics: 'analytics',
    tripplanner: 'tripplanner', account: 'account', boats: 'boats', charts: 'charts',
  };

  let content;
  if (route.view === 'home') {
    content = <HomeView navigate={navigate} settings={settings} regions={regions}/>;
  } else if (route.view === 'today') {
    content = <TodayView navigate={navigate} settings={settings} regions={regions}/>;
  } else if (route.view === 'analytics') {
    content = <AnalyticsView filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks} settings={settings} regions={regions} subtab={route.params.subtab || 'overview'}/>;
  } else if (route.view === 'boats') {
    content = <BoatsView filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks} settings={settings} regions={regions}/>;
  } else if (route.view === 'boat') {
    content = <BoatDetail filters={filters} setFilters={setFilters} navigate={navigate} boat={route.params.boat} regions={regions}/>;
  } else if (route.view === 'landing') {
    content = <LandingDetail filters={filters} setFilters={setFilters} navigate={navigate} landing={route.params.landing} regions={regions}/>;
  } else if (route.view === 'tripplanner') {
    content = <TripPlanner filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks} regions={regions}/>;
  } else if (route.view === 'forecast') {
    content = <ForecastView navigate={navigate}/>;
  } else if (route.view === 'charts') {
    content = chartsReady
      ? <ChartsView navigate={navigate} settings={settings}/>
      : <div className="charts-map-loading"><div className="charts-map-loading-text">Loading map…</div></div>;
  } else if (route.view === 'account') {
    content = <MyAccountView settings={settings} onSettingsChange={onSettingsChange}
                              regions={regions} onRegionsDirect={setRegionsDirect} navigate={navigate}/>;
  }

  const headerActive = route.view === 'boat' ? 'boats'
    : route.view === 'landing' ? 'analytics'
    : route.view;

  return (
    <React.Fragment>
      <AppHeader active={headerActive} onNavigate={(id) => navigate(navMap[id] || 'today')}
                 hrefFor={(id) => pathFromRoute(navMap[id] || 'today', {}, regions)}
                 regions={regions} onRegionToggle={toggleRegion} onRegionsDirect={setRegionsDirect}/>
      <main className="main-content" data-screen-label={route.view}>{content}</main>
      <AppFooter/>

      <ChatBot pageContext={pageContext}/>

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
                       options={[{value:'all',label:'All Tuna'},{value:'Bluefin',label:'Bluefin'},{value:'Yellowfin',label:'Yellowfin'},{value:'Yellowtail',label:'Yellowtail'},{value:'Dorado',label:'Dorado'},{value:'Skipjack',label:'Skipjack'},{value:'Bigeye',label:'Bigeye'},{value:'Albacore',label:'Albacore'}]}
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
