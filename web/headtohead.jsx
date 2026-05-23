// Head-to-Head — leaderboard restricted to "apples-to-apples" matchups
// (same date + same trip length + ≥2 boats), so the ranking isolates skill
// from external factors like weather, moon, or whether the fish were biting.
function HeadToHead({ filters, setFilters, navigate }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const matchups = useMemo(() => SDA.peerMatchups(trips, filters.species), [trips, filters.species]);
  const rows = useMemo(() => SDA.peerLeaderboard(trips, filters.species), [trips, filters.species]);
  const eligible = rows.filter((r) => r.matchupCount >= (filters.minTrips || 1));

  // Sortable leaderboard state. Default: by winRate descending — boats that
  // most often top their same-date-same-length cohort sit at the top.
  const [sortBy, setSortBy] = useState('winRate');
  const [sortDir, setSortDir] = useState('desc');
  const toggleSort = (k) => {
    if (sortBy === k) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortBy(k); setSortDir(k === 'boat' || k === 'landing' ? 'asc' : 'desc'); }
  };
  const headerCell = (k, label, num) => (
    <th className={`${num ? 'num' : ''} ${sortBy === k ? 'active' : ''}`}
        style={{cursor: 'pointer', userSelect: 'none'}}
        onClick={() => toggleSort(k)}>
      {label}
      <span className="sortarrow" style={{marginLeft: 4, opacity: sortBy === k ? 1 : 0.4}}>
        {sortBy === k ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
      </span>
    </th>
  );
  const sortedEligible = useMemo(() => {
    const arr = [...eligible];
    arr.sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : (av - bv);
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return arr;
  }, [eligible, sortBy, sortDir]);
  const totalMatchups = matchups.length;
  const tripsInMatchups = matchups.reduce((s, m) => s + m.trips.length, 0);
  const bestDay = matchups[0];  // matchups already sorted desc by date

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Sportfish', onClick: () => navigate('today') },
        { label: 'Analyze' },
        { label: 'Head-to-Head' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Head-to-Head</h1>
          <div className="sub">
            Apples-to-apples ranking: only trips where 2+ boats ran the same trip length on the same date.
          </div>
        </div>
      </div>

      <FilterBar filters={filters} setFilters={setFilters}/>

      <div className="kpis">
        <KPI label="Matchups" value={fmt.n(totalMatchups)}
             ctx={`${fmt.n(tripsInMatchups)} trips compete`}/>
        <KPI label="Boats in matchups" value={fmt.n(eligible.length)}
             ctx={`min ${filters.minTrips} matchups`}/>
        <KPI label="Most recent matchup"
             value={bestDay ? fmt.date(bestDay.date) : '—'}
             ctx={bestDay ? `${bestDay.trips.length} boats · ${bestDay.tripLength}` : ''}/>
        <KPI label="Top performer"
             value={eligible[0]?.boat || '—'}
             ctx={eligible[0] ? `+${eligible[0].avgDelta.toFixed(2)} vs peer median` : ''}/>
      </div>

      <Panel title="Peer-Relative Leaderboard"
             meta={`Avg tuna/angler/day above (+) or below (−) the peer-group median across all matchups · ranked by avg delta`}
             padding={false}>
        {eligible.length === 0 ? (
          <div className="muted-block" style={{padding: 16}}>
            No boats meet the minimum matchup threshold. Try lowering "Min Trips" in the filter bar.
          </div>
        ) : (
          <div style={{maxHeight: 500, overflowY: 'auto'}}>
            <table className="dt">
              <thead><tr>
                <th style={{width: 36}}>#</th>
                {headerCell('boat', 'Boat')}
                {headerCell('landing', 'Landing')}
                {headerCell('matchupCount', 'Matchups', true)}
                {headerCell('wins', 'Wins', true)}
                {headerCell('winRate', 'Win rate', true)}
                {headerCell('avgDelta', 'Avg vs Peer Median', true)}
                {headerCell('bestWin', 'Best win', true)}
                {headerCell('worstLoss', 'Worst loss', true)}
              </tr></thead>
              <tbody>
                {sortedEligible.map((r, i) => (
                  <tr key={r.boat} className="clickable" onClick={() => navigate('boat', { boat: r.boat })}>
                    <td><span className="rank" style={{color: i < 3 ? 'var(--ss-orange-500)' : null, fontWeight: i < 3 ? 700 : 500}}>{i + 1}</span></td>
                    <td><b>{r.boat}</b></td>
                    <td>{r.landing}</td>
                    <td className="num">{r.matchupCount}</td>
                    <td className="num">{r.wins}</td>
                    <td className="num">{fmt.pct(r.winRate, 0)}</td>
                    <td className="num" style={{
                      color: r.avgDelta > 0 ? 'var(--ss-darkseagreen-500)'
                            : r.avgDelta < 0 ? 'var(--ss-orange-500)' : 'var(--ss-slate)',
                      fontWeight: 600,
                    }}>{(r.avgDelta >= 0 ? '+' : '') + r.avgDelta.toFixed(2)}</td>
                    <td className="num" style={{color: 'var(--ss-darkseagreen-500)'}}>+{r.bestWin.toFixed(2)}</td>
                    <td className="num" style={{color: 'var(--ss-orange-500)'}}>{r.worstLoss.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Recent Matchups"
             meta={`The actual side-by-side competitions · click a boat to drill into its detail page`}
             padding={false}>
        {matchups.length === 0 ? (
          <div className="muted-block" style={{padding: 16}}>
            No matchups found for these filters.
          </div>
        ) : (
          <div style={{maxHeight: 720, overflowY: 'auto'}}>
            {matchups.slice(0, 60).map((m) => (
              <MatchupCard key={`${m.date}-${m.tripLength}`} m={m} navigate={navigate}/>
            ))}
          </div>
        )}
      </Panel>
    </Fragment>
  );
}

function MatchupCard({ m, navigate }) {
  const top = m.trips[0]._tpapd;
  return (
    <div style={{
      borderBottom: '1px solid var(--ss-border-2)',
      padding: '12px 14px',
    }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8,
      }}>
        <span style={{font: '700 13px/16px var(--ss-font-sans)', color: 'var(--ss-black)'}}>
          {fmt.date(m.date)}
        </span>
        <span className="tag" style={{
          background: 'var(--ss-clay)', color: 'var(--ss-slate)',
          font: '600 10px/12px var(--ss-font-sans)',
          padding: '2px 6px', borderRadius: 4,
          textTransform: 'uppercase', letterSpacing: '.06em',
        }}>{m.tripLength}</span>
        <span style={{font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-slate)'}}>
          {m.trips.length} boats · peer median {m.peerMedianTPAPerDay.toFixed(2)} /angler/day
        </span>
      </div>
      <div>
        {m.trips.map((t, i) => {
          const isWinner = t._tpapd >= top - 1e-9;
          const vsMedian = t._tpapd - m.peerMedianTPAPerDay;
          return (
            <div key={`${t.boat}-${i}`} style={{
              display: 'grid',
              gridTemplateColumns: '24px 1fr 90px 70px 70px 100px',
              gap: 8,
              alignItems: 'center',
              padding: '4px 0',
              font: '400 12px/16px var(--ss-font-sans)',
            }}>
              <span style={{
                font: '700 11px/14px var(--ss-font-sans)',
                color: isWinner ? 'var(--ss-orange-500)' : 'var(--ss-slate)',
              }}>{isWinner ? <i className="fa-solid fa-trophy"></i> : (i + 1)}</span>
              <span style={{cursor: 'pointer', color: 'var(--ss-black)'}}
                    onClick={() => navigate('boat', { boat: t.boat })}>
                <b>{t.boat}</b>
                <span style={{color: 'var(--ss-slate)', marginLeft: 8, font: '400 11px/14px var(--ss-font-sans)'}}>
                  {t.landing.replace(' Sportfishing', '').replace(' Landing', '')}
                </span>
              </span>
              <span className="num" style={{color: 'var(--ss-slate)', textAlign: 'right', fontVariantNumeric: 'tabular-nums'}}>
                {t.anglers} anglers
              </span>
              <span className="num" style={{textAlign: 'right', fontVariantNumeric: 'tabular-nums'}}>
                {t.trophyCount} tuna
              </span>
              <span className="num" style={{
                textAlign: 'right',
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 600,
                color: isWinner ? 'var(--ss-orange-500)' : 'var(--ss-black)',
              }}>
                {t._tpapd.toFixed(2)}
              </span>
              <span className="num" style={{
                textAlign: 'right',
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 600,
                color: vsMedian > 0 ? 'var(--ss-darkseagreen-500)'
                      : vsMedian < 0 ? 'var(--ss-orange-500)' : 'var(--ss-slate)',
              }}>
                {(vsMedian >= 0 ? '+' : '') + vsMedian.toFixed(2)} vs med
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, { HeadToHead });
