// Seasonality view — species catch patterns by month
function SeasonalityView({ filters, setFilters, navigate }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const monthly = useMemo(() => SDA.monthlyTrend(trips, filters.species), [trips, filters.species]);

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'seasonality' }) },
        { label: 'Seasonality' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Species Seasonality</h1>
          <div className="sub">Monthly catch patterns across {fmt.n(trips.length)} trips</div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters}/>
      <Panel title="Species Seasonality" meta="Total catch by month, all approved boats">
        <div className="chart-legend" style={{marginBottom: 8}}>
          {Object.entries(SPECIES_COLORS).map(([sp, c]) => (
            <span key={sp} className="ll"><span className="sw" style={{background: c}}></span>{sp}</span>
          ))}
        </div>
        <StackedBarChart width={1080} height={220}
          data={monthly.map((m, i) => ({
            label: MONTH_NAMES[i],
            Bluefin:    trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Bluefin||0), 0),
            Yellowfin:  trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Yellowfin||0), 0),
            Yellowtail: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Yellowtail||0), 0),
            Dorado:     trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Dorado||0), 0),
            Skipjack:   trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Skipjack||0), 0),
            Bigeye:     trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Bigeye||0), 0),
            Albacore:   trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Albacore||0), 0),
          }))}
          series={['Bluefin','Yellowfin','Yellowtail','Dorado','Skipjack','Bigeye','Albacore']}
          formatY={v => fmt.n(Math.round(v))}
        />
      </Panel>
    </Fragment>
  );
}

Object.assign(window, { SeasonalityView });
