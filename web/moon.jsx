// Moon Phase view — lunar phase correlation with catch rates
function MoonView({ filters, setFilters, navigate }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const moonData = useMemo(() => SDA.moonAnalysis(trips, filters.species), [trips, filters.species]);
  const bestMoon = [...moonData].sort((a, b) => b.tpa - a.tpa)[0];

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Seasonality & Moon', onClick: () => navigate('seasonality', { subtab: 'seasonality' }) },
        { label: 'Moon Phase' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Moon Phase</h1>
          <div className="sub">Lunar phase correlation with catch rates across {fmt.n(trips.length)} trips</div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters}/>
      <Panel title="Moon Phase Correlation"
             meta={`Avg ${speciesLabel.toLowerCase()}/angler by lunar phase`}
             className="moon-panel"
             actions={<span className="meta">Best: <b style={{color:'#34D399'}}>{bestMoon?.phase}</b> ({fmt.tpa(bestMoon?.tpa)})</span>}>
        <div className="moon-grid">
          {moonData.map((m) => {
            const isBest = m.phase === bestMoon?.phase;
            return (
              <div key={m.phase} className={`moon-cell ${isBest ? 'best' : ''}`}>
                <MoonGlyph phase={m.phase}/>
                <div className="moon-connector"></div>
                <div className="lab">{m.phase}</div>
                <div className="val">{fmt.tpa(m.tpa)}</div>
                <div className="sub">{m.trips} trips</div>
              </div>
            );
          })}
        </div>
        <div style={{marginTop: 8, paddingTop: 12, borderTop: '1px solid rgba(52,211,153,0.2)', font: '400 11px/14px var(--ss-font-sans)', color: 'rgba(255,255,255,0.5)'}}>
          <i className="fa-solid fa-circle-info"></i>{' '}
          {(() => {
            const sorted = [...moonData].sort((a,b)=>b.tpa-a.tpa);
            const lift = sorted[0].tpa / (sorted[sorted.length-1].tpa || 0.001);
            return `${sorted[0].phase} produces ${lift.toFixed(1)}× the catch rate of ${sorted[sorted.length-1].phase}. Bigger fish run on darker nights — Bluefin tuna especially favor crescent and new moon.`;
          })()}
        </div>
      </Panel>
    </Fragment>
  );
}

// Seasonality & Moon container — sub-tab wrapper
function SeasonalityMoonView({ filters, setFilters, navigate, subtab = 'seasonality' }) {
  const SUBTABS = [
    { id: 'seasonality', label: 'Seasonality' },
    { id: 'moon',        label: 'Moon Phase' },
  ];
  return (
    <Fragment>
      <div className="tabbar analytics-subtabbar">
        {SUBTABS.map(t => (
          <a key={t.id} className={subtab === t.id ? 'sel' : ''}
             onClick={() => navigate('seasonality', { subtab: t.id })}>{t.label}</a>
        ))}
      </div>
      {subtab === 'seasonality' && <SeasonalityView filters={filters} setFilters={setFilters} navigate={navigate}/>}
      {subtab === 'moon'        && <MoonView        filters={filters} setFilters={setFilters} navigate={navigate}/>}
    </Fragment>
  );
}

Object.assign(window, { MoonView, SeasonalityMoonView });
