// Moon & Tides view — lunar phase correlation with catch rates
function MoonView({ filters, setFilters }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const moonData = useMemo(() => SDA.moonAnalysis(trips, filters.species), [trips, filters.species]);
  const bestMoon = [...moonData].sort((a, b) => b.tpa - a.tpa)[0];

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Sportfish', onClick: () => {} },
        { label: 'Analyze', onClick: () => {} },
        { label: 'Moon & Tides' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Moon & Tides</h1>
          <div className="sub">Lunar phase correlation with catch rates across {fmt.n(trips.length)} trips</div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters}/>
      <Panel title="Moon Phase Correlation"
             meta={`Avg ${speciesLabel.toLowerCase()}/angler by lunar phase`}
             actions={<span className="meta">Best: <b style={{color:'var(--ss-black)'}}>{bestMoon?.phase}</b> ({fmt.tpa(bestMoon?.tpa)})</span>}>
        <div className="moon-grid">
          {moonData.map((m) => {
            const isBest = m.phase === bestMoon?.phase;
            return (
              <div key={m.phase} className={`moon-cell ${isBest ? 'best' : ''}`}>
                <MoonGlyph phase={m.phase}/>
                <div className="lab">{m.phase}</div>
                <div className="val">{fmt.tpa(m.tpa)}</div>
                <div className="sub">{m.trips} trips</div>
              </div>
            );
          })}
        </div>
        <div style={{marginTop: 8, paddingTop: 12, borderTop: '1px solid var(--ss-border-2)', font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-gray-3)'}}>
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

Object.assign(window, { MoonView });
