// Main app — routing and tweaks wiring
const { useState: useS, useEffect: useE } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "comfortable",
  "monthlyView": "tpa",
  "showSpike": true,
  "includeZero": false
}/*EDITMODE-END*/;

// URL-hash routing: the hash is the source of truth for the active route,
// so refreshing or bookmarking keeps you on the same page.
// Format: #<region-prefix>/<view>[/<params>]  e.g. #sd/today, #ocla/analytics/overview
const HASH_VIEWS = {
  today: 'today', tripplanner: 'tripplanner',
  settings: 'account', admin: 'admin', forecast: 'forecast',
  account: 'account',
};

const ANALYTICS_SUBTABS = ['overview', 'boats', 'landings', 'headtohead', 'seasonality', 'moon'];

function extractRegionFromHash(raw) {
  if (!raw) return { regionIds: null, rest: '' };
  var slash = raw.indexOf('/');
  var first = slash === -1 ? raw : raw.slice(0, slash);
  var ids = window.REGION_HASH_TO_IDS && window.REGION_HASH_TO_IDS[first];
  if (ids) return { regionIds: ids, rest: slash === -1 ? '' : raw.slice(slash + 1) };
  return { regionIds: null, rest: raw };
}

function routeFromHash() {
  const raw = window.location.hash.replace(/^#/, '');
  const { regionIds, rest } = extractRegionFromHash(raw);
  if (!rest) return { view: 'today', params: {}, hashRegions: regionIds };
  const [seg, ...parts] = rest.split('/');
  const detail = parts.length ? decodeURIComponent(parts.join('/')) : '';

  if (seg === 'boat' && detail) return { view: 'boat', params: { boat: detail }, hashRegions: regionIds };
  if (seg === 'landing' && detail) return { view: 'landing', params: { landing: detail }, hashRegions: regionIds };

  if (seg === 'analytics') {
    const subtab = ANALYTICS_SUBTABS.includes(detail) ? detail : 'overview';
    return { view: 'analytics', params: { subtab }, hashRegions: regionIds };
  }
  // Legacy URL redirects
  if (seg === 'seasonality') {
    const sub = detail === 'moon' ? 'moon' : 'seasonality';
    return { view: 'analytics', params: { subtab: sub }, hashRegions: regionIds };
  }
  if (seg === 'boats')      return { view: 'analytics', params: { subtab: 'boats' },      hashRegions: regionIds };
  if (seg === 'landings')   return { view: 'analytics', params: { subtab: 'landings' },   hashRegions: regionIds };
  if (seg === 'headtohead') return { view: 'analytics', params: { subtab: 'headtohead' }, hashRegions: regionIds };
  if (seg === 'moon')       return { view: 'analytics', params: { subtab: 'moon' },       hashRegions: regionIds };

  if (HASH_VIEWS[seg]) return { view: HASH_VIEWS[seg], params: {}, hashRegions: regionIds };
  return { view: 'today', params: {}, hashRegions: regionIds };
}

function hashFromRoute(view, params = {}, regions = ['san_diego']) {
  const prefix = window.regionsToHashPrefix ? window.regionsToHashPrefix(regions) : 'sd';
  let route;
  if (view === 'boat' && params.boat) route = 'boat/' + encodeURIComponent(params.boat);
  else if (view === 'landing' && params.landing) route = 'landing/' + encodeURIComponent(params.landing);
  else if (view === 'analytics') route = 'analytics/' + (params.subtab || 'overview');
  else route = view;
  return prefix + '/' + route;
}

function App() {
  const [route, setRoute] = useS(() => routeFromHash());
  const [filters, setFilters] = useS({ ...DEFAULT_FILTERS });
  const [tweaks, setTweaksState] = useTweaks(TWEAK_DEFAULTS);
  const [pageContext, setPageContext] = useS({ page: 'today', boat: null, date: null });

  // Clerk auth state — hook must be at top level.
  const { user, isSignedIn } = useAuth();

  const [regions, setRegions] = useS(() => {
    const initial = routeFromHash();
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
    const savedRegion = window.getUserPref('primary_region', null);
    if (savedRegion && savedRegion !== regions[0]) {
      setRegionsDirect([savedRegion]);
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
  }, [isSignedIn, user && user.id]);

  // Sync effective region to global so filterTrips picks it up automatically.
  useE(() => {
    window.CURRENT_REGION = window.getEffectiveRegion
      ? window.getEffectiveRegion(regions)
      : regions[0];
  }, [regions]);

  // Update the region prefix in the URL hash without triggering a hashchange loop.
  useE(() => {
    const currentHash = window.location.hash.replace(/^#/, '');
    const { rest } = extractRegionFromHash(currentHash);
    const prefix = window.regionsToHashPrefix ? window.regionsToHashPrefix(regions) : 'sd';
    const viewPart = rest || 'today';
    const newHash = prefix + '/' + viewPart;
    if (currentHash !== newHash) {
      history.replaceState(null, '', '#' + newHash);
    }
  }, [regions]);

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

  // Keep route in sync when the hash changes; also update regions if hash has prefix.
  useE(() => {
    const onHashChange = () => {
      const parsed = routeFromHash();
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
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // Fire page view tracking on every route change.
  useE(() => {
    if (window.TTTrack) TTTrack.pageView(route.view);
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

  // Admin is a fully standalone page — no header, no nav, no shared state used.
  // Must be after all hooks (React rules: no conditional hooks).
  if (route.view === 'admin') return <AdminView />;

  const navigate = (view, params = {}) => {
    const nextHash = hashFromRoute(view, params, regions);
    if (window.location.hash.replace(/^#/, '') === nextHash) {
      setRoute({ view, params }); // hash unchanged (e.g. re-click same tab) — update directly
    } else {
      window.location.hash = nextHash; // triggers hashchange -> setRoute
    }
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  // Map nav tab id -> navigate() view
  const navMap = {
    today: 'today', forecast: 'forecast', analytics: 'analytics',
    tripplanner: 'tripplanner', account: 'account',
  };

  let content;
  if (route.view === 'today') {
    content = <TodayView navigate={navigate} settings={settings} regions={regions}/>;
  } else if (route.view === 'analytics') {
    content = <AnalyticsView filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks} settings={settings} regions={regions} subtab={route.params.subtab || 'overview'}/>;
  } else if (route.view === 'boat') {
    content = <BoatDetail filters={filters} setFilters={setFilters} navigate={navigate} boat={route.params.boat} regions={regions}/>;
  } else if (route.view === 'landing') {
    content = <LandingDetail filters={filters} setFilters={setFilters} navigate={navigate} landing={route.params.landing} regions={regions}/>;
  } else if (route.view === 'tripplanner') {
    content = <TripPlanner filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks} regions={regions}/>;
  } else if (route.view === 'forecast') {
    content = <ForecastView navigate={navigate}/>;
  } else if (route.view === 'account') {
    content = <MyAccountView settings={settings} onSettingsChange={onSettingsChange}
                              regions={regions} onRegionsDirect={setRegionsDirect}/>;
  }

  const headerActive = (route.view === 'boat' || route.view === 'landing') ? 'analytics' : route.view;

  return (
    <Fragment>
      <AppHeader active={headerActive} onNavigate={(id) => navigate(navMap[id] || 'today')}
                 regions={regions} onRegionToggle={toggleRegion}/>
      <main className="main-content" data-screen-label={route.view}>{content}</main>

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
    </Fragment>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
