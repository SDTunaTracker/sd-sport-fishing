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
  const speciesMix = useMemo(() => SDA.speciesMix(trips), [trips]);
  const moonData = useMemo(() => SDA.moonAnalysis(trips, filters.species), [trips, filters.species]);
  const lengthData = useMemo(() => SDA.tripLengthBreakdown(trips, filters.species), [trips, filters.species]);
  const landings = useMemo(() => SDA.landingSummary(trips, filters.species), [trips, filters.species]);

  const topBoatLimit = tweaks.density === 'compact' ? 12 : 10;
  const topBoats = eligibleBoats.slice(0, topBoatLimit);
  // Bar widths and the right-hand number on the Top Boats panel use the
  // trip-length-normalised per-day metric so a 5-day trip doesn't auto-win.
  const maxTPAPerDay = topBoats[0]?.avgTPAPerDay || 1;
  const bestMoon = [...moonData].sort((a, b) => b.tpa - a.tpa)[0];
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

      {/* Top row: leaderboard + species mix */}
      <div style={{display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12, marginBottom: 12}}>
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

        <Panel title="Species Mix" meta={`${fmt.n(totalTuna)} total fish`}>
          <div style={{display: 'flex', gap: 16, alignItems: 'center'}}>
            <Donut size={140} thickness={22} data={[
              { value: speciesMix.Bluefin,    color: SPECIES_COLORS.Bluefin },
              { value: speciesMix.Yellowfin,  color: SPECIES_COLORS.Yellowfin },
              { value: speciesMix.Yellowtail, color: SPECIES_COLORS.Yellowtail },
              { value: speciesMix.Dorado,     color: SPECIES_COLORS.Dorado },
              { value: speciesMix.Skipjack,   color: SPECIES_COLORS.Skipjack },
              { value: speciesMix.Bigeye,     color: SPECIES_COLORS.Bigeye },
              { value: speciesMix.Albacore,   color: SPECIES_COLORS.Albacore },
            ]}/>
            <div className="donut-legend" style={{flex: 1}}>
              {Object.entries(speciesMix).map(([sp, v]) => {
                const pct = totalTuna ? v / totalTuna : 0;
                return (
                  <div key={sp} className="ll">
                    <span className="sw" style={{background: SPECIES_COLORS[sp]}}></span>
                    {sp}
                    <span className="pct">{fmt.n(v)} · {fmt.pct(pct, 1)}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <div style={{marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--ss-border-2)'}}>
            <div className="stat-row"><span className="lbl">Top species</span><span className="vl">
              {(() => {
                const top = Object.entries(speciesMix).sort((a,b)=>b[1]-a[1])[0];
                return top ? `${top[0]} · ${fmt.pct(top[1]/(totalTuna||1), 0)}` : '—';
              })()}
            </span></div>
            <div className="stat-row"><span className="lbl">Trips landing 10+ fish</span>
              <span className="vl">{fmt.n(trips.filter(t => t.totalTuna >= 10).length)}</span></div>
            <div className="stat-row"><span className="lbl">Skunked trips</span>
              <span className="vl">{fmt.n(trips.filter(t => t.totalTuna === 0).length)}</span></div>
          </div>
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

      {/* Bottom row: moon + landings */}
      <div style={{display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 12, marginBottom: 12}}>
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
            <i className="fa-solid fa-circle-info"></i> {' '}
            {(() => {
              const sorted = [...moonData].sort((a,b)=>b.tpa-a.tpa);
              const lift = sorted[0].tpa / (sorted[sorted.length-1].tpa || 0.001);
              return `${sorted[0].phase} produces ${lift.toFixed(1)}× the catch rate of ${sorted[sorted.length-1].phase}. Bigger fish run on darker nights — Bluefin tuna especially favor crescent and new moon.`;
            })()}
          </div>
        </Panel>

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
      </div>

      {/* Bottom: species seasonality stacked */}
      <Panel title="Species Seasonality"
             meta="Total catch by month, all approved boats">
        <div className="chart-legend" style={{marginBottom: 8}}>
          {Object.entries(SPECIES_COLORS).map(([sp, c]) => (
            <span key={sp} className="ll"><span className="sw" style={{background: c}}></span>{sp}</span>
          ))}
        </div>
        <StackedBarChart width={1080} height={220}
          data={monthly.map((m, i) => ({
            label: MONTH_NAMES[i],
            Bluefin: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Bluefin||0), 0),
            Yellowfin: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Yellowfin||0), 0),
            Yellowtail: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Yellowtail||0), 0),
            Dorado: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Dorado||0), 0),
            Skipjack: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Skipjack||0), 0),
            Bigeye: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Bigeye||0), 0),
            Albacore: trips.filter(t => t.month === i+1).reduce((s, t) => s + (t.Albacore||0), 0),
          }))}
          series={['Bluefin','Yellowfin','Yellowtail','Dorado','Skipjack','Bigeye','Albacore']}
          formatY={v => fmt.n(Math.round(v))}
        />
      </Panel>
    </Fragment>
  );
}

Object.assign(window, { Dashboard });
