// Boats leaderboard view — full sortable ranked table with consistency labels
function BoatsView({ filters, setFilters, navigate, tweaks, settings, regions }) {
  const trips = useMemo(() => SDA.filterTrips(filters, regions), [filters, regions]);
  const { rows } = useMemo(
    () => SDA.boatLeaderboard(trips, filters.species, filters.minTrips),
    [trips, filters.species, filters.minTrips]
  );
  const eligible = rows.filter(r => r.tripCount >= filters.minTrips);

  const [sortBy, setSortBy]       = useState('avgTPAPerDay');
  const [sortDir, setSortDir]     = useState('desc');
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

  const defaultTrophySp = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];
  const customSp = settings && settings.trophySpecies;
  const isCustomSp = customSp && (
    customSp.length !== defaultTrophySp.length ||
    !defaultTrophySp.every(sp => customSp.includes(sp))
  );

  const labelPills = (
    <div className="row" style={{gap:4}}>
      <span className={`filter-pill ${labelFilter==='all'?'on':''}`} onClick={() => setLabelFilter('all')}>All</span>
      <span className={`filter-pill ${labelFilter==='consistent'?'on':''}`} onClick={() => setLabelFilter('consistent')}>Consistent</span>
      <span className={`filter-pill ${labelFilter==='spike'?'on':''}`} onClick={() => setLabelFilter('spike')}>Spike</span>
    </div>
  );

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'overview' }) },
        { label: 'Boats' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Boat Leaderboard <span className="region-subtitle-badge">{(regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego'}</span></h1>
          <div className="sub">
            Ranked by {speciesLabel.toLowerCase()}/angler/day · {sorted.length} eligible boats
          </div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters} regions={regions}/>

      {isCustomSp && (
        <div className="custom-species-banner" title={`Counting: ${customSp.join(', ')}`}>
          <i className="fa-solid fa-chart-bar"/> Custom species: <b>{customSp.join(', ')}</b>
        </div>
      )}

      <Panel title="Label Definitions" meta="How boats earn a performance label" style={{marginBottom: 12}}>
        <div style={{display:'flex', gap:24, flexWrap:'wrap', font:'400 12px/18px var(--ss-font-sans)', color:'var(--ss-slate)'}}>
          <div>
            <span className="tag consistent" style={{marginRight: 6}}>Consistent</span>
            <span style={{color:'var(--ss-black)', fontWeight:500}}>Outperformer</span>
            <ul style={{margin: '4px 0 0 16px', padding: 0}}>
              <li>≥ {filters.minTrips} trips logged</li>
              <li>Consistently strong catch rate across multiple trips</li>
            </ul>
          </div>
          <div>
            <span className="tag spike" style={{marginRight: 6}}>Spike</span>
            <span style={{color:'var(--ss-black)', fontWeight:500}}>One-Off Performer</span>
            <ul style={{margin: '4px 0 0 16px', padding: 0}}>
              <li>Single best trip &gt; 40% of total catch</li>
              <li>Fewer than 25 trips logged</li>
            </ul>
          </div>
          <div style={{alignSelf:'flex-end', color:'var(--ss-gray-3)', font:'400 11px/15px var(--ss-font-sans)'}}>
            <i className="fa-solid fa-circle-info"></i> Prefer Consistent boats. Spikes can be lucky one-offs.
          </div>
        </div>
      </Panel>

      <Panel title="All Eligible Boats" meta={`${sorted.length} boats · click to view detail`} padding={false}
             actions={labelPills}>
        <div style={{maxHeight: 540, overflow: 'auto'}}>
          <table className="dt">
            <thead>
              <tr>
                <th style={{width: 36}}>#</th>
                {headerCell('boat', 'Boat')}
                {headerCell('landing', 'Landing')}
                {headerCell('tripCount', 'Trips', true)}
                {headerCell('avgTPAPerDay', `Avg ${speciesLabel}/Angler/Day`, true)}
                {headerCell('totalTuna', `Total ${speciesLabel}`, true)}
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((b, i) => (
                <tr key={b.boat} className="clickable" onClick={() => { if (window.TTTrack) TTTrack.boatView(b.boat, b.landing || ''); navigate('boat', { boat: b.boat }); }}>
                  <td><span className="rank" style={{color: i < 3 ? 'var(--ss-orange-500)' : null, fontWeight: i < 3 ? 700 : 500}}>{i + 1}</span></td>
                  <td><b>{b.boat}</b></td>
                  <td>{b.landing}</td>
                  <td className="num">{fmt.n(b.tripCount)}</td>
                  <td className="num">{fmt.tpa(b.avgTPAPerDay)}</td>
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
