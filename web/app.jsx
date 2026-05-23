// Main app — routing and tweaks wiring
const { useState: useS, useEffect: useE } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "comfortable",
  "monthlyView": "tpa",
  "showSpike": true,
  "includeZero": false
}/*EDITMODE-END*/;

function App() {
  const [route, setRoute] = useS({ view: 'dashboard', params: {} });
  const [filters, setFilters] = useS({ ...DEFAULT_FILTERS });
  const [tweaks, setTweaksState] = useTweaks(TWEAK_DEFAULTS);

  // Settings: trophy species + trip length methodology, persisted to localStorage.
  const [settings, setSettingsState] = useS(() => loadSettings());
  function onSettingsChange(next) {
    saveSettings(next);
    SDA.preprocessTrips(next);
    setSettingsState(next);
  }
  // Initialize processed trips on first render.
  useE(() => { SDA.preprocessTrips(settings); }, []);

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

  const navigate = (view, params = {}) => {
    setRoute({ view, params });
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  // Map sidebar -> internal view
  const navMap = {
    dashboard: 'dashboard', boats: 'boats', landings: 'landings',
    tripplanner: 'tripplanner',
    headtohead: 'headtohead',
    seasonality: 'seasonality', moon: 'moon', watchlist: 'dashboard',
    recent: 'dashboard', settings: 'settings',
  };

  let content;
  if (route.view === 'dashboard') {
    content = <Dashboard filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks}/>;
  } else if (route.view === 'boats') {
    content = <BoatsView filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks}/>;
  } else if (route.view === 'landings') {
    content = <LandingsView filters={filters} setFilters={setFilters} navigate={navigate}/>;
  } else if (route.view === 'boat') {
    content = <BoatDetail filters={filters} setFilters={setFilters} navigate={navigate} boat={route.params.boat}/>;
  } else if (route.view === 'landing') {
    content = <LandingDetail filters={filters} setFilters={setFilters} navigate={navigate} landing={route.params.landing}/>;
  } else if (route.view === 'tripplanner') {
    content = <TripPlanner filters={filters} setFilters={setFilters} navigate={navigate} tweaks={tweaks}/>;
  } else if (route.view === 'headtohead') {
    content = <HeadToHead filters={filters} setFilters={setFilters} navigate={navigate}/>;
  } else if (route.view === 'seasonality') {
    content = <SeasonalityView filters={filters} setFilters={setFilters} navigate={navigate}/>;
  } else if (route.view === 'moon') {
    content = <MoonView filters={filters} setFilters={setFilters} navigate={navigate}/>;
  } else if (route.view === 'settings') {
    content = <SettingsView settings={settings} onSettingsChange={onSettingsChange}/>;
  }

  const sidebarActive = route.view === 'boat' ? 'boats' : route.view === 'landing' ? 'landings' : route.view;

  return (
    <Fragment>
      <AppHeader section="Analytics" tab={route.view === 'boats' || route.view === 'boat' ? 'Boats' : route.view === 'landings' || route.view === 'landing' ? 'Landings' : 'Dashboard'}/>
      <div className="shell">
        <SideNav active={sidebarActive} onNavigate={(id) => navigate(navMap[id] || 'dashboard')}/>
        <main data-screen-label={route.view}>{content}</main>
      </div>

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
