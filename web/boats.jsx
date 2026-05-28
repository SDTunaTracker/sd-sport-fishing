// Boats — top-level destination page: search, sort, win rate, recent form
function BoatsView({ filters, setFilters, navigate, tweaks, settings, regions }) {
  const trips = useMemo(() => SDA.filterTrips(filters, regions), [filters, regions]);
  const { rows } = useMemo(
    () => SDA.boatLeaderboard(trips, filters.species, filters.minTrips),
    [trips, filters.species, filters.minTrips]
  );
  const eligible = rows.filter(r => r.tripCount >= filters.minTrips);

  const [sortBy, setSortBy]         = useState('avgTPAPerDay');
  const [sortDir, setSortDir]       = useState('desc');
  const [labelFilter, setLabelFilter] = useState('all');
  const [search, setSearch]         = useState('');

  // Win rate per boat — average across all trip lengths
  const boatWinMap = useMemo(() => {
    try {
      const raw = SDA.boatWinRates ? SDA.boatWinRates() : {};
      const acc = {};
      for (const [key, val] of Object.entries(raw)) {
        const boat = key.split('|')[0];
        if (!acc[boat]) acc[boat] = { sum: 0, n: 0 };
        acc[boat].sum += val.winRate;
        acc[boat].n   += 1;
      }
      const out = {};
      for (const [boat, { sum, n }] of Object.entries(acc)) out[boat] = sum / n;
      return out;
    } catch(e) { return {}; }
  }, []);

  // Recent form per boat from streak data
  const formMap = useMemo(() => {
    try {
      const _ALL = { year:'all', species:'all', landing:'all', month:'all', minTrips:0, includeZero:true, boat:'all' };
      const streaks = SDA.boatStreaks(SDA.filterTrips(_ALL, regions));
      const out = {};
      for (const s of streaks) out[s.boat] = s.goodCount;
      return out;
    } catch(e) { return {}; }
  }, [regions]);

  const sorted = useMemo(() => {
    let r = [...eligible];
    if (search) {
      const q = search.toLowerCase();
      r = r.filter(x => x.boat.toLowerCase().includes(q) || (x.landing||'').toLowerCase().includes(q));
    }
    if (labelFilter !== 'all') {
      r = r.filter(x => labelFilter === 'consistent' ? x.label === 'Consistent' :
                        labelFilter === 'spike' ? x.label === 'Spike' : true);
    }
    r.sort((a, b) => {
      let va, vb;
      if (sortBy === 'winRate') {
        va = boatWinMap[a.boat] ?? -1;
        vb = boatWinMap[b.boat] ?? -1;
      } else if (sortBy === 'form') {
        va = formMap[a.boat] ?? -1;
        vb = formMap[b.boat] ?? -1;
      } else {
        va = a[sortBy];
        vb = b[sortBy];
      }
      if (typeof va === 'string') return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      return sortDir === 'asc' ? va - vb : vb - va;
    });
    return r;
  }, [eligible, sortBy, sortDir, labelFilter, search, boatWinMap, formMap]);

  const toggleSort = (k) => {
    if (sortBy === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortBy(k); setSortDir('desc'); }
  };

  const headerCell = (k, label, num) => (
    <th className={`${num ? 'num' : ''} ${sortBy === k ? 'active' : ''}`} onClick={() => toggleSort(k)}
        style={{cursor:'pointer', whiteSpace:'nowrap'}}>
      {label}
      <span className="sortarrow">{sortBy === k ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}</span>
    </th>
  );

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  const regionLabel = (regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego';

  function formBadge(boat) {
    const g = formMap[boat];
    if (g == null) return <span style={{color:'var(--ss-gray-2)'}}>—</span>;
    if (g >= 7) return <span className="boats-form-badge hot">🔥 Hot</span>;
    if (g <= 3) return <span className="boats-form-badge cold">❄️ Cold</span>;
    return <span style={{color:'var(--tb-slate)', fontSize:11}}>{g}/10</span>;
  }

  return (
    <Fragment>
      <div className="pagehead">
        <div>
          <h1>Boats <span className="region-subtitle-badge">{regionLabel}</span></h1>
          <div className="sub">
            Research and compare every boat — {sorted.length} eligible · click any row for the full profile
          </div>
        </div>
      </div>

      {/* Search + label filter */}
      <div className="boats-search-bar">
        <div className="boats-search-input-wrap">
          <i className="fa-solid fa-magnifying-glass boats-search-icon"/>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search boats or landings…"
            className="boats-search-input"
          />
          {search && (
            <button onClick={() => setSearch('')} className="boats-search-clear">×</button>
          )}
        </div>
        <div className="row" style={{gap:4}}>
          {[['all','All'],['consistent','Consistent'],['spike','Spike']].map(([val, lbl]) => (
            <span key={val} className={`filter-pill ${labelFilter===val?'on':''}`}
                  onClick={() => setLabelFilter(val)}>{lbl}</span>
          ))}
        </div>
      </div>

      <FilterBar filters={filters} setFilters={setFilters} regions={regions}/>

      <Panel title="All Boats" meta={`${sorted.length} boats · sorted by ${sortBy === 'avgTPAPerDay' ? speciesLabel+'/angler/day' : sortBy}`} padding={false}>
        <div style={{overflowX:'auto'}}>
          <table className="dt">
            <thead>
              <tr>
                <th style={{width:36}}>#</th>
                {headerCell('boat', 'Boat', false)}
                {headerCell('landing', 'Landing', false)}
                {headerCell('tripCount', 'Trips', true)}
                {headerCell('avgTPAPerDay', speciesLabel+'/Day', true)}
                {headerCell('winRate', 'Win Rate', true)}
                {headerCell('form', 'Form', false)}
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((b, i) => {
                const wr = boatWinMap[b.boat];
                return (
                  <tr key={b.boat} className="clickable" onClick={() => {
                    if (window.TTTrack) TTTrack.boatView(b.boat, b.landing || '');
                    navigate('boat', { boat: b.boat });
                  }}>
                    <td>
                      <span className="rank" style={{
                        color: i < 3 ? 'var(--ss-orange-500)' : undefined,
                        fontWeight: i < 3 ? 700 : 500,
                      }}>{i + 1}</span>
                    </td>
                    <td><b>{b.boat}</b></td>
                    <td>{b.landing}</td>
                    <td className="num">{fmt.n(b.tripCount)}</td>
                    <td className="num">{fmt.tpa(b.avgTPAPerDay)}</td>
                    <td className="num">{wr != null ? `${Math.round(wr * 100)}%` : '—'}</td>
                    <td>{formBadge(b.boat)}</td>
                    <td>
                      {b.label === 'Consistent' && <span className="tag consistent">Consistent</span>}
                      {b.label === 'Spike'      && <span className="tag spike">Spike</span>}
                      {!b.label && <span style={{color:'var(--ss-gray-2)'}}>—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </Fragment>
  );
}

Object.assign(window, { BoatsView });
