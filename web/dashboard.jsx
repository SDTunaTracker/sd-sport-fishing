function TodayCatch({ navigate }) {
  const today = window.SD?.TODAY;
  if (!today) return null;
  const species = [
    { key: 'Bluefin', color: SPECIES_COLORS.Bluefin },
    { key: 'Yellowfin', color: SPECIES_COLORS.Yellowfin },
    { key: 'Yellowtail', color: SPECIES_COLORS.Yellowtail },
    { key: 'Dorado', color: SPECIES_COLORS.Dorado },
  ].filter(s => today[s.key] > 0);
  return (
    <Fragment>
      <div className="today-banner">
        <div className="today-left">
          <div className="today-head"><i className="fa-solid fa-fish-fins"></i> Today's Catch</div>
          <div className="today-date">{(() => {
            const [y, m, d] = today.date.split('-');
            const scrape = window.SD?.META?.lastScrape;
            const timeStr = scrape ? new Date(scrape).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }) : null;
            return `${+m}/${+d}/${String(+y).slice(-2)}${timeStr ? ` · as of ${timeStr}` : ''}`;
          })()}</div>
        </div>
        <div className="today-stats">
          <div className="today-stat">
            <span className="ts-val">{fmt.n(today.trophyCount)}</span>
            <span className="ts-lbl">tuna</span>
          </div>
          <div className="today-stat">
            <span className="ts-val">{fmt.n(today.anglers)}</span>
            <span className="ts-lbl">anglers</span>
          </div>
          <div className="today-stat">
            <span className="ts-val">{fmt.n(today.boatCount)}</span>
            <span className="ts-lbl">boats</span>
          </div>
        </div>
        <div className="today-species">
          {species.map(s => (
            <div key={s.key} className="today-sp">
              <span className="sp-dot" style={{background: s.color}}></span>
              <span className="sp-name">{s.key}</span>
              <span className="sp-val">{fmt.n(today[s.key])}</span>
            </div>
          ))}
        </div>
      </div>
      <Panel title="Today's Report" meta="Sorted by tuna per angler per day">
        <div className="today-boat-row today-boat-hd">
          <span>Boat</span>
          <span>Landing</span>
          <span>Trip</span>
          <span>Trophy</span>
          <span>Anglers</span>
          <span>TPA/Day</span>
        </div>
        {today.boats.map((b, i) => (
          <div key={i} className="today-boat-row" style={{cursor:'pointer'}}
               onClick={() => navigate('boat', { boat: b.boat })}>
            <span style={{font:'600 12px/16px var(--ss-font-sans)', color:'var(--tb-ink)'}}>{b.boat}</span>
            <span>{b.landing.replace(' Sportfishing','').replace(' Landing','')}</span>
            <span>{b.tripLength}</span>
            <span style={{fontWeight:600}}>{fmt.n(b.trophyCount)}</span>
            <span>{fmt.n(b.anglers)}</span>
            <span style={{fontWeight:700, color: i === 0 ? 'var(--ss-orange-500)' : 'var(--tb-ink)'}}>{fmt.tpa(b.trophyPerAnglerPerDay)}</span>
          </div>
        ))}
      </Panel>
    </Fragment>
  );
}

// Dashboard view - main analytics screen
function Dashboard({ filters, setFilters, navigate, tweaks }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const prevTrips = useMemo(() => {
    const f = { ...filters };
    if (f.year !== 'all') f.year = String(+f.year - 1);
    return SDA.filterTrips(f);
  }, [filters]);

  const { rows: leaderboard, fleetMedianTPA, fleetMedianTPAPerDay } = useMemo(
    () => SDA.boatLeaderboard(trips, filters.species, filters.minTrips),
    [trips, filters.species, filters.minTrips]
  );
  const eligibleBoats = leaderboard.filter(r => r.tripCount >= filters.minTrips);

  const totalTuna = trips.reduce((s, t) => s + (filters.species && filters.species !== 'all' ? (t[filters.species]||0) : t.totalTuna), 0);
  const totalAnglers = trips.reduce((s, t) => s + t.anglers, 0);
  const fleetTPA = totalAnglers ? totalTuna / totalAnglers : 0;
  const prevTuna = prevTrips.reduce((s, t) => s + (filters.species && filters.species !== 'all' ? (t[filters.species]||0) : t.totalTuna), 0);
  const prevAnglers = prevTrips.reduce((s, t) => s + t.anglers, 0);
  const prevTPA = prevAnglers ? prevTuna / prevAnglers : 0;
  const tpaDelta = prevTPA > 0 ? ((fleetTPA - prevTPA) / prevTPA) * 100 : null;

  const monthly = useMemo(() => SDA.monthlyTrend(trips, filters.species), [trips, filters.species]);
  const lengthData = useMemo(() => SDA.tripLengthBreakdown(trips, filters.species), [trips, filters.species]);
  const landings = useMemo(() => SDA.landingSummary(trips, filters.species), [trips, filters.species]);

  const topBoatLimit = tweaks.density === 'compact' ? 12 : 10;
  const topBoats = eligibleBoats.slice(0, topBoatLimit);
  // Bar widths and the right-hand number on the Top Boats panel use the
  // trip-length-normalised per-day metric so a 5-day trip doesn't auto-win.
  const maxTPAPerDay = topBoats[0]?.avgTPAPerDay || 1;
  const bestMonth = [...monthly].sort((a, b) => b.tpa - a.tpa)[0];

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Sportfish', onClick: () => {} },
        { label: 'Analyze', onClick: () => {} },
        { label: 'Dashboard' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>San Diego Sportfishing — Tuna Tracker</h1>
          <div className="sub">
            Showing {fmt.n(trips.length)} trips across {eligibleBoats.length} boats and {landings.length} approved landings
            {' · '}{filters.year === 'all' ? 'All years' : filters.year}
            {filters.species !== 'all' ? ` · ${filters.species} only` : ''}
          </div>
        </div>
        <div className="actions">
          <button className="btn ghost"><i className="fa-solid fa-sliders"></i> Saved Views</button>
          <button className="btn secondary"><i className="fa-solid fa-download"></i> Export</button>
          <button className="btn primary" onClick={() => navigate('boats')}>
            <i className="fa-solid fa-trophy"></i> Open Leaderboard
          </button>
        </div>
      </div>

      <FilterBar filters={filters} setFilters={setFilters}/>

      <TodayCatch navigate={navigate}/>

      <div className="kpis">
        <KPI label={`Fleet ${speciesLabel} / Angler`}
             value={fmt.tpa(fleetTPA)}
             delta={tpaDelta}
             deltaLabel="vs prior year"
             ctx={`Median across boats: ${fmt.tpa(fleetMedianTPA)}`}/>
        <KPI label={`Total ${speciesLabel}`}
             value={fmt.n(totalTuna)}
             ctx={`${fmt.n(totalAnglers)} anglers fished`}/>
        <KPI label="Best Boat" value={topBoats[0]?.boat || '—'}
             ctx={topBoats[0] ? `${fmt.tpa(topBoats[0].avgTPA)} ${speciesLabel.toLowerCase()}/angler · ${topBoats[0].landing}` : ''}/>
        <KPI label="Peak Month"
             value={bestMonth ? MONTH_NAMES[bestMonth.month - 1] : '—'}
             ctx={bestMonth ? `${fmt.tpa(bestMonth.tpa)} ${speciesLabel.toLowerCase()}/angler · ${fmt.n(bestMonth.tuna)} caught` : ''}/>
      </div>

      {/* Top row: leaderboard */}
      <div style={{marginBottom: 12}}>
        <Panel title={`Top Boats — ${speciesLabel} per Angler per Day`}
               meta={`Ranked by avg ${speciesLabel.toLowerCase()}/angler/day · min ${filters.minTrips} trips · normalises trip length`}
               actions={<button className="btn sm ghost" onClick={() => navigate('boats')}>View All →</button>}>
          {topBoats.length === 0 ? <div className="muted-block">No boats meet the minimum trip threshold for these filters.</div> : (
            <Fragment>
              <div className="chart-legend" style={{marginBottom: 8}}>
                <span className="ll"><span className="sw" style={{background: 'var(--ss-darkseagreen-500)'}}></span>Consistent / Avg performer</span>
                <span className="ll"><span className="sw" style={{background: 'var(--ss-orange-500)'}}></span>One-off spike</span>
                <span className="median-mark"><span className="line"></span>Fleet median ({fmt.tpa(fleetMedianTPAPerDay)})</span>
              </div>
              <div style={{position: 'relative'}}>
                {topBoats.map((b, i) => {
                  const wpct = (b.avgTPAPerDay / maxTPAPerDay) * 100;
                  const medLinePct = (fleetMedianTPAPerDay / maxTPAPerDay) * 100;
                  return (
                    <div key={b.boat} className={`bar-row ${b.label === 'Spike' ? 'spike' : 'consistent'}`}
                         style={{cursor: 'pointer'}}
                         onClick={() => navigate('boat', { boat: b.boat })}>
                      <div className="label">
                        <span className="rank" style={{color: i < 3 ? 'var(--ss-orange-500)' : null, fontWeight: i < 3 ? 700 : 500}}>{i + 1}</span>
                        <div style={{minWidth: 0, flex: 1}}>
                          <div className="name">{b.boat}</div>
                          <div className="lan">{b.landing.replace(' Sportfishing','').replace(' Landing','')} · {b.tripCount} trips</div>
                        </div>
                      </div>
                      <div className="track" style={{position: 'relative'}}>
                        <div className="fill" style={{width: `${wpct}%`}}></div>
                        <div style={{position:'absolute', left: `${medLinePct}%`, top:-2, bottom:-2, width:0, borderLeft:'1.5px dashed #445460'}}></div>
                        {b.label && (
                          <span className={`tag ${b.label === 'Consistent' ? 'consistent' : 'spike'}`} style={{position:'absolute', right:6, top:-2, fontSize:9}}>
                            {b.label === 'Consistent' ? 'Consistent' : 'Spike'}
                          </span>
                        )}
                      </div>
                      <div className="num">{fmt.tpa(b.avgTPAPerDay)}</div>
                    </div>
                  );
                })}
              </div>
            </Fragment>
          )}
        </Panel>
      </div>

      {/* Mid row: monthly trend + trip length */}
      <div style={{display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12, marginBottom: 12}}>
        <Panel title="Monthly Catch Pattern"
               meta={`${speciesLabel}/angler by month`}
               actions={<div className="row" style={{gap:4}}>
                 <span className={`filter-pill ${tweaks.monthlyView === 'tpa' ? 'on' : ''}`}
                       onClick={() => window.__setTweak({ monthlyView: 'tpa' })}>Per Angler</span>
                 <span className={`filter-pill ${tweaks.monthlyView === 'total' ? 'on' : ''}`}
                       onClick={() => window.__setTweak({ monthlyView: 'total' })}>Total</span>
               </div>}>
          {tweaks.monthlyView === 'total' ? (
            <VBarChart width={680} height={220}
              data={monthly.map((m, i) => ({ label: MONTH_NAMES[i], value: m.tuna, color: m.tuna === Math.max(...monthly.map(x=>x.tuna)) ? '#FF7705' : '#008566' }))}
              valueKey="value" labelKey="label" formatY={v => fmt.n(Math.round(v))}/>
          ) : (
            <LineChart width={680} height={220}
              data={monthly.map((m, i) => ({ label: MONTH_NAMES[i], value: m.tpa }))}
              valueKey="value" labelKey="label" formatY={v => v.toFixed(1)}/>
          )}
        </Panel>

        <Panel title="By Trip Length"
               meta={`${speciesLabel.toLowerCase()}/angler`}>
          {lengthData.length === 0 ? <div className="muted-block">No data.</div> : (
            <div>
              {lengthData.sort((a,b)=>b.tpa-a.tpa).map((r) => {
                const max = Math.max(...lengthData.map(x => x.tpa));
                return (
                  <div key={r.tripLength} style={{display:'grid', gridTemplateColumns:'88px 1fr 60px', gap:8, alignItems:'center', padding:'5px 0'}}>
                    <span style={{font:'500 11px/14px var(--ss-font-sans)', color:'var(--ss-slate)'}}>{r.tripLength}</span>
                    <div className="track" style={{height: 14}}>
                      <div className="fill" style={{width: `${(r.tpa/max)*100}%`, background: r.tripLength === 'Long Range' ? 'var(--ss-orange-500)' : 'var(--ss-darkseagreen-500)'}}></div>
                    </div>
                    <span className="num" style={{font:'500 11px/14px var(--ss-font-sans)', textAlign:'right', fontVariantNumeric:'tabular-nums'}}>{fmt.tpa(r.tpa)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      </div>

      {/* Bottom row: landings */}
      <Panel title="By Landing"
             meta="Approved San Diego landings"
             actions={<button className="btn sm ghost" onClick={() => navigate('landings')}>Compare →</button>}>
        {landings.map((l) => {
          const max = Math.max(...landings.map(x => x.tpa));
          return (
            <div key={l.landing} style={{padding:'8px 0', borderBottom:'1px solid var(--ss-border-2)', cursor:'pointer'}}
                 onClick={() => navigate('landing', { landing: l.landing })}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom: 4}}>
                <span style={{font:'500 13px/16px var(--ss-font-sans)'}}>{l.landing}</span>
                <span style={{font:'700 13px/16px var(--ss-font-sans)', fontVariantNumeric:'tabular-nums'}}>{fmt.tpa(l.tpa)}</span>
              </div>
              <div style={{display:'flex', gap: 8, alignItems:'center'}}>
                <div className="track" style={{height: 8, flex: 1}}>
                  <div className="fill" style={{width: `${(l.tpa/max)*100}%`}}></div>
                </div>
                <span style={{font:'400 10px/12px var(--ss-font-sans)', color:'var(--ss-gray-3)', minWidth: 90, textAlign:'right'}}>
                  {l.boatCount} boats · {fmt.n(l.trips)} trips
                </span>
              </div>
            </div>
          );
        })}
      </Panel>
    </Fragment>
  );
}

Object.assign(window, { Dashboard });
