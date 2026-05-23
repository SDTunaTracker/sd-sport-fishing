// Boats leaderboard view — full sortable ranked table with consistency labels
function BoatsView({ filters, setFilters, navigate, tweaks }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const { rows, fleetMedianTPA, fleetMedianTPAPerDay } = useMemo(
    () => SDA.boatLeaderboard(trips, filters.species, filters.minTrips),
    [trips, filters.species, filters.minTrips]
  );
  const eligible = rows.filter(r => r.tripCount >= filters.minTrips);

  const [sortBy, setSortBy] = useState('avgTPAPerDay');
  const [sortDir, setSortDir] = useState('desc');
  const [labelFilter, setLabelFilter] = useState('all');

  const sorted = useMemo(() => {
    let r = [...eligible];
    if (labelFilter !== 'all') {
      r = r.filter(x => labelFilter === 'consistent' ? x.label === 'Consistent' :
                        labelFilter === 'spike' ? x.label === 'Spike' : true);
    }
    r.sort((a, b) => {
      const va = a[sortBy], vb = b[sortBy];
      if (typeof va === 'string') return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      return sortDir === 'asc' ? va - vb : vb - va;
    });
    return r;
  }, [eligible, sortBy, sortDir, labelFilter]);

  const toggleSort = (k) => {
    if (sortBy === k) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortBy(k); setSortDir('desc'); }
  };

  const headerCell = (k, label, num) => (
    <th className={`${num ? 'num' : ''} ${sortBy === k ? 'active' : ''}`} onClick={() => toggleSort(k)}>
      {label}
      <span className="sortarrow">{sortBy === k ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}</span>
    </th>
  );

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  // Consistency scatter: median TPA (x) vs CV (y, inverted)
  const scatterMaxTPA = Math.max(...eligible.map(r => r.medTPA), 0.1) * 1.1;
  const scatterMaxCV = Math.max(...eligible.map(r => r.cv), 0.1) * 1.1;

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Sportfish', onClick: () => navigate('today') },
        { label: 'Analyze', onClick: () => navigate('today') },
        { label: 'Boat Leaderboard' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Boat Leaderboard</h1>
          <div className="sub">
            Ranked by {speciesLabel.toLowerCase()}/angler/day · {sorted.length} eligible boats
            · fleet median {fmt.tpa(fleetMedianTPAPerDay)}
          </div>
        </div>
        <div className="actions">
          <button className="btn ghost"><i className="fa-solid fa-bookmark"></i> Save View</button>
          <button className="btn secondary"><i className="fa-solid fa-download"></i> Export CSV</button>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters}/>

      <div className="two-col-grid" style={{display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12, marginBottom: 12}}>
        <Panel title="Consistent vs One-Off Spike"
               meta="Median catch rate vs trip-to-trip variance"
               actions={<div className="row" style={{gap:4}}>
                 <span className={`filter-pill ${labelFilter==='all'?'on':''}`} onClick={() => setLabelFilter('all')}>All</span>
                 <span className={`filter-pill ${labelFilter==='consistent'?'on':''}`} onClick={() => setLabelFilter('consistent')}>Consistent</span>
                 <span className={`filter-pill ${labelFilter==='spike'?'on':''}`} onClick={() => setLabelFilter('spike')}>Spike</span>
               </div>}>
          {/* Scatter plot */}
          <svg width="700" height="240" viewBox="0 0 700 240" style={{maxWidth: '100%'}}>
            <line x1="40" y1="210" x2="680" y2="210" stroke="#C9C6CE"/>
            <line x1="40" y1="20" x2="40" y2="210" stroke="#C9C6CE"/>
            {/* gridlines */}
            {[0.25, 0.5, 0.75, 1].map(p => (
              <line key={p} x1="40" y1={210 - p*190} x2="680" y2={210 - p*190} stroke="#EDEDED"/>
            ))}
            {/* fleet median crosshair */}
            <line x1={40 + (fleetMedianTPA / scatterMaxTPA) * 640} y1="20"
                  x2={40 + (fleetMedianTPA / scatterMaxTPA) * 640} y2="210"
                  stroke="#445460" strokeDasharray="4 4" strokeWidth="1"/>
            {/* axes labels */}
            <text x="360" y="232" textAnchor="middle" fontSize="10" fill="#90979F">Median {speciesLabel}/Angler →</text>
            <text x="14" y="115" textAnchor="middle" fontSize="10" fill="#90979F" transform="rotate(-90 14 115)">↑ More variable</text>
            <text x={40 + (fleetMedianTPA / scatterMaxTPA) * 640} y="14" textAnchor="middle" fontSize="9" fill="#445460">fleet median</text>

            {eligible.map((b) => {
              const x = 40 + (b.medTPA / scatterMaxTPA) * 640;
              const y = 210 - (b.cv / scatterMaxCV) * 190;
              const fill = b.label === 'Consistent' ? '#008566' : b.label === 'Spike' ? '#FF7705' : '#90979F';
              const r = b.label === 'Consistent' ? 6 : b.label === 'Spike' ? 6 : 4;
              return (
                <g key={b.boat} style={{cursor:'pointer'}} onClick={() => navigate('boat', { boat: b.boat })}>
                  <circle cx={x} cy={y} r={r} fill={fill} fillOpacity="0.85" stroke="#fff" strokeWidth="1"/>
                  {(b.label === 'Consistent' || b.label === 'Spike') && (
                    <text x={x + 8} y={y + 3} fontSize="9" fill="#191F23">{b.boat}</text>
                  )}
                </g>
              );
            })}
          </svg>
          <div className="chart-legend" style={{marginTop: 4}}>
            <span className="ll"><span className="sw" style={{background: '#008566', borderRadius:999}}></span>Consistent Outperformer</span>
            <span className="ll"><span className="sw" style={{background: '#FF7705', borderRadius:999}}></span>One-Off Spike</span>
            <span className="ll"><span className="sw" style={{background: '#90979F', borderRadius:999}}></span>Other</span>
          </div>
        </Panel>

        <Panel title="Definitions" meta="Label criteria">
          <div style={{font:'400 12px/18px var(--ss-font-sans)', color:'var(--ss-slate)'}}>
            <div style={{marginBottom: 12}}>
              <span className="tag consistent" style={{marginRight: 6}}>Consistent</span>
              <span style={{color:'var(--ss-black)', fontWeight:500}}>Outperformer</span>
              <ul style={{margin: '6px 0 0 16px', padding: 0}}>
                <li>≥ {filters.minTrips} trips</li>
                <li>Avg {speciesLabel.toLowerCase()}/angler &gt; fleet median</li>
                <li>Median &gt; fleet median</li>
                <li>Success rate &gt; 60%</li>
              </ul>
            </div>
            <div>
              <span className="tag spike" style={{marginRight: 6}}>Spike</span>
              <span style={{color:'var(--ss-black)', fontWeight:500}}>One-Off Performer</span>
              <ul style={{margin: '6px 0 0 16px', padding: 0}}>
                <li>Single best trip &gt; 40% of total catch</li>
                <li>Fewer than 25 trips logged</li>
              </ul>
            </div>
            <div style={{marginTop: 12, paddingTop: 12, borderTop:'1px solid var(--ss-border-2)', color:'var(--ss-gray-3)', font:'400 11px/15px var(--ss-font-sans)'}}>
              <i className="fa-solid fa-circle-info"></i> When choosing a boat, prefer Consistent labels. Spikes can be lucky one-offs.
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="All Eligible Boats" meta={`${sorted.length} boats · click to view detail`} padding={false}>
        <div style={{maxHeight: 540, overflow: 'auto'}}>
          <table className="dt">
            <thead>
              <tr>
                <th style={{width: 36}}>#</th>
                {headerCell('boat', 'Boat')}
                {headerCell('landing', 'Landing')}
                {headerCell('tripCount', 'Trips', true)}
                {headerCell('avgTPAPerDay', `Avg ${speciesLabel}/Angler/Day`, true)}
                {headerCell('medTPA', 'Median', true)}
                {headerCell('successRate', 'Success', true)}
                {headerCell('aboveAvgPct', '% Above Median', true)}
                {headerCell('cv', 'Variance (CV)', true)}
                {headerCell('totalTuna', `Total ${speciesLabel}`, true)}
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((b, i) => (
                <tr key={b.boat} className="clickable" onClick={() => navigate('boat', { boat: b.boat })}>
                  <td><span className="rank" style={{color: i < 3 ? 'var(--ss-orange-500)' : null, fontWeight: i < 3 ? 700 : 500}}>{i + 1}</span></td>
                  <td><b>{b.boat}</b></td>
                  <td>{b.landing}</td>
                  <td className="num">{fmt.n(b.tripCount)}</td>
                  <td className={`num ${b.avgTPAPerDay > fleetMedianTPAPerDay ? 'hi' : 'lo'}`}>{fmt.tpa(b.avgTPAPerDay)}</td>
                  <td className="num">{fmt.tpa(b.medTPA)}</td>
                  <td className="num">{fmt.pct(b.successRate, 0)}</td>
                  <td className="num">{fmt.pct(b.aboveAvgPct, 0)}</td>
                  <td className="num">{b.cv.toFixed(2)}</td>
                  <td className="num">{fmt.n(b.totalTuna)}</td>
                  <td>
                    {b.label === 'Consistent' && <span className="tag consistent">Consistent</span>}
                    {b.label === 'Spike' && <span className="tag spike">Spike</span>}
                    {!b.label && <span style={{color:'var(--ss-gray-2)'}}>—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </Fragment>
  );
}

Object.assign(window, { BoatsView });
