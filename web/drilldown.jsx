// Boat detail drill-down
function BoatDetail({ filters, setFilters, navigate, boat }) {
  const [detailTab, setDetailTab] = React.useState('overview');
  const allTrips = useMemo(() => SDA.filterTrips({ ...filters, boat: 'all' }).filter(t => t.boat === boat), [filters, boat]);
  const fleetTrips = useMemo(() => SDA.filterTrips({ ...filters, boat: 'all' }), [filters]);
  const meta = window.SD.BOATS.find(b => b.name === boat);
  useEffect(() => {
    if (meta && window.TTTrack) TTTrack.boatView(boat, meta.landing || '');
  }, [boat]);
  if (!meta) return <div className="muted-block">Boat not found.</div>;

  const sf = SDA.speciesField(filters.species);
  const totalTuna = allTrips.reduce((s,t) => s + (t[sf]||0), 0);
  const totalAnglers = allTrips.reduce((s,t) => s + t.anglers, 0);
  const tpa = totalAnglers ? totalTuna/totalAnglers : 0;
  const tpas = allTrips.map(t => (t[sf]||0)/Math.max(1,t.anglers));
  const medTPA = SDA.median(tpas);
  const successRate = allTrips.length ? allTrips.filter(t => (t[sf]||0)>0).length/allTrips.length : 0;
  const cv = SDA.mean(tpas) > 0 ? SDA.stddev(tpas)/SDA.mean(tpas) : 0;

  const fleetMedTPA = SDA.median(fleetTrips.map(t => (t[sf]||0)/Math.max(1,t.anglers)));

  // Per-species breakdown
  const speciesBreakdown = window.SD.SPECIES.map(sp => {
    const total = allTrips.reduce((s,t) => s + (t[sp]||0), 0);
    const tpa = totalAnglers ? total/totalAnglers : 0;
    return { species: sp, total, tpa };
  }).sort((a,b)=>b.tpa-a.tpa);

  // Monthly
  const monthly = SDA.monthlyTrend(allTrips, filters.species);
  // All this boat's trips, newest first. (Was previously "top 12 by TPA"; now
  // we show the full history so anglers can scan past performance.)
  const sortedTrips = [...allTrips].sort((a, b) => {
    if (a.date !== b.date) return b.date.localeCompare(a.date);
    return (b.id || 0) - (a.id || 0);
  });

  // Trip length mix
  const lengthMix = SDA.tripLengthBreakdown(allTrips, filters.species);

  // Determine label
  const bestTripCatch = Math.max(0, ...allTrips.map(t => t[sf]||0));
  const bestPct = totalTuna ? bestTripCatch/totalTuna : 0;
  let label = null;
  if (allTrips.length >= filters.minTrips) {
    if (tpa > fleetMedTPA && medTPA > fleetMedTPA && successRate > 0.6) label = 'Consistent';
    else if (bestPct > 0.4 && allTrips.length < 25) label = 'Spike';
  }

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'boats' }) },
        { label: 'Boats', onClick: () => navigate('analytics', { subtab: 'boats' }) },
        { label: boat },
      ]}/>
      <div className="pagehead">
        <div>
          <div style={{display:'flex', alignItems:'center', gap: 12, flexWrap:'wrap'}}>
            <h1 style={{margin:0}}>{boat}</h1>
            {label === 'Consistent' && <span className="tag consistent">Consistent Outperformer</span>}
            {label === 'Spike' && <span className="tag spike">One-Off Spike</span>}
            <ReviewBadge boat={boat}/>
          </div>
          <div className="sub">
            {meta.landing} · {meta.lengths.join(', ')} · {allTrips.length} trips in scope
          </div>
        </div>
        <div className="actions">
          <button className="btn primary"><i className="fa-solid fa-arrow-up-right-from-square"></i> Book Trip</button>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters} hideBoat={true}/>

      <div className="kpis">
        <KPI label="Tuna / Angler" value={fmt.tpa(tpa)} ctx={`Fleet median ${fmt.tpa(fleetMedTPA)} · ${tpa > fleetMedTPA ? 'Above' : 'Below'}`}
             accent={tpa > fleetMedTPA ? 'var(--ss-darkseagreen-500)' : null}/>
        <KPI label="Median / Angler" value={fmt.tpa(medTPA)} ctx="Trip-by-trip median"/>
        <KPI label="Success Rate" value={fmt.pct(successRate, 0)} ctx={`${allTrips.filter(t=>(t[sf]||0)>0).length} of ${allTrips.length} trips`}/>
        <KPI label="Variance (CV)" value={cv.toFixed(2)} ctx={cv < 0.6 ? 'Tight, predictable' : cv < 1 ? 'Moderate variance' : 'High variance'}
             accent={cv < 0.6 ? 'var(--ss-darkseagreen-500)' : cv > 1 ? 'var(--ss-orange-500)' : null}/>
      </div>

      <div className="detail-grid" style={{marginBottom: 12}}>
        <Panel title="Catch Rate Through the Year" meta="Tuna/angler by month, this boat vs landing average">
          {/* Combined bar+line: this boat vs landing avg */}
          {(() => {
            const landingAvg = window.SD.TRIPS
              .filter(t => t.landing === meta.landing && (filters.year === 'all' || t.year === +filters.year));
            const landingMonthly = SDA.monthlyTrend(landingAvg, filters.species);
            const max = Math.max(...monthly.map(m=>m.tpa), ...landingMonthly.map(m=>m.tpa), 0.001);
            return (
              <Fragment>
                <div className="chart-legend" style={{marginBottom:6}}>
                  <span className="ll"><span className="sw" style={{background:'#008566'}}></span>{boat}</span>
                  <span className="ll"><span className="sw" style={{background:'#C9C6CE'}}></span>{meta.landing} avg</span>
                </div>
                <svg width="640" height="220" viewBox="0 0 640 220" style={{maxWidth:'100%'}}>
                  {[0,1,2,3,4].map(i => {
                    const y = 20 + (170 * i / 4);
                    const v = max * (1 - i/4);
                    return (
                      <g key={i}>
                        <line x1="40" y1={y} x2="630" y2={y} stroke="#EDEDED"/>
                        <text x="34" y={y+3} textAnchor="end" fontSize="9" fill="#90979F">{v.toFixed(1)}</text>
                      </g>
                    );
                  })}
                  {monthly.map((m, i) => {
                    const x = 40 + i * 49 + 5;
                    const bw = 18;
                    const bh = (m.tpa/max) * 170;
                    const lh = (landingMonthly[i].tpa/max) * 170;
                    return (
                      <g key={i}>
                        <rect x={x} y={190-bh} width={bw} height={bh} fill="#008566" rx="2"/>
                        <rect x={x+bw+2} y={190-lh} width={bw} height={lh} fill="#C9C6CE" rx="2"/>
                        <text x={x+bw} y="208" textAnchor="middle" fontSize="9" fill="#445460">{MONTH_NAMES[i]}</text>
                      </g>
                    );
                  })}
                </svg>
              </Fragment>
            );
          })()}
        </Panel>

        <Panel title="By Species" meta="Catch/angler (all 7 tracked species)">
          {speciesBreakdown.map(s => {
            const max = Math.max(...speciesBreakdown.map(x=>x.tpa), 0.01);
            return (
              <div key={s.species} style={{display:'grid', gridTemplateColumns:'80px 1fr 60px', gap:8, alignItems:'center', padding:'7px 0'}}>
                <span style={{display:'flex', alignItems:'center', gap:6, font:'500 12px/16px var(--ss-font-sans)'}}>
                  <span className="sp-pill" style={{background: SPECIES_COLORS[s.species]}}></span>
                  {s.species}
                </span>
                <div className="track" style={{height:12}}>
                  <div className="fill" style={{width:`${(s.tpa/max)*100}%`, background: SPECIES_COLORS[s.species]}}></div>
                </div>
                <span className="num" style={{font:'500 12px/16px var(--ss-font-sans)', textAlign:'right', fontVariantNumeric:'tabular-nums'}}>{fmt.tpa(s.tpa)}</span>
              </div>
            );
          })}
          <div style={{marginTop:10, paddingTop: 10, borderTop:'1px solid var(--ss-border-2)'}}>
            <div className="stat-row"><span className="lbl">Total fish landed</span><span className="vl">{fmt.n(totalTuna)}</span></div>
            <div className="stat-row"><span className="lbl">Total anglers</span><span className="vl">{fmt.n(totalAnglers)}</span></div>
          </div>
        </Panel>
      </div>

      {/* ── Community Buzz ── */}
      {(() => {
        const buzz = window.SD?.COMMUNITY?.boatMentions?.[boat];
        if (!buzz || buzz.mentions === 0) return null;
        const sentColor = buzz.sentiment === 'positive' ? '#10B981' : buzz.sentiment === 'negative' ? '#EF4444' : '#94A3B8';
        const sentLabel = buzz.sentiment === 'positive' ? '👍 Positive' : buzz.sentiment === 'negative' ? '👎 Negative' : '😐 Neutral';
        return (
          <div className="cm-widget" style={{marginBottom:12}}>
            <div className="cm-widget-head">
              <span className="cm-widget-title">Community Buzz</span>
              <span className="cm-widget-sub">from Reddit fishing reports · last 7 days</span>
            </div>
            <div style={{display:'flex', alignItems:'center', gap:16, padding:'10px 0', borderBottom:'1px solid var(--ss-border-2)', marginBottom:10}}>
              <div style={{textAlign:'center'}}>
                <div style={{fontSize:22, fontWeight:700, color:'var(--tb-ink)'}}>{buzz.mentions}</div>
                <div style={{fontSize:10, color:'var(--ss-slate)', textTransform:'uppercase', letterSpacing:'.06em'}}>Mentions</div>
              </div>
              <div style={{textAlign:'center'}}>
                <div style={{fontSize:16, fontWeight:600, color:sentColor}}>{sentLabel}</div>
                <div style={{fontSize:10, color:'var(--ss-slate)', textTransform:'uppercase', letterSpacing:'.06em'}}>Sentiment</div>
              </div>
              <div style={{display:'flex', gap:8, fontSize:12, color:'var(--ss-slate)'}}>
                {buzz.positive > 0 && <span style={{color:'#10B981'}}>+{buzz.positive}</span>}
                {buzz.negative > 0 && <span style={{color:'#EF4444'}}>−{buzz.negative}</span>}
                {buzz.neutral > 0 && <span>{buzz.neutral} neutral</span>}
              </div>
            </div>
            {(buzz.recent_quotes || []).map((q, i) => (
              <div key={i} style={{marginBottom:8, paddingBottom:8, borderBottom: i < buzz.recent_quotes.length-1 ? '1px solid var(--ss-border-2)' : 'none'}}>
                <div style={{fontSize:12, color:'var(--tb-ink)', lineHeight:1.5}}>{q.text}</div>
                <div style={{fontSize:10, color:'var(--ss-slate)', marginTop:2}}>
                  {q.date} · <a href={q.url} target="_blank" rel="noreferrer" style={{color:'var(--ss-blue)'}}>source</a>
                </div>
              </div>
            ))}
          </div>
        );
      })()}

      {/* ── Bottom tabs: Overview / Reviews / Reddit ── */}
      <div className="dd-tabs">
        {[['overview','Trip History'],['reviews','Reviews'],['reddit','Reddit Reports']].map(([id,lbl]) => (
          <button key={id}
            className={`dd-tab${detailTab === id ? ' active' : ''}`}
            onClick={() => setDetailTab(id)}>
            {lbl}
            {id === 'reviews' && (() => {
              const n = window.SD.REVIEWS?.summary?.[boat]?.total_reviews;
              return n ? <span className="dd-tab-count">{n}</span> : null;
            })()}
            {id === 'reddit' && (() => {
              const n = (window.SD.REDDIT?.reports || []).filter(p =>
                p.boat_mentioned === boat ||
                (p.title || '').toLowerCase().includes(boat.toLowerCase())
              ).length;
              return n ? <span className="dd-tab-count">{n}</span> : null;
            })()}
          </button>
        ))}
      </div>

      {detailTab === 'reviews' && (
        <ReviewsSection boat={boat} landing={meta.landing}/>
      )}

      {detailTab === 'reddit' && (
        <BoatRedditPanel boat={boat}/>
      )}

      {detailTab === 'overview' && <Panel title="Trip History" meta={`All ${sortedTrips.length} past trips for ${boat} · newest first`} padding={false}>
        {(() => {
          // 4 trophy-species columns replace the single Trophy total.
          // Grid: Date | Species Mix bar | Trip Length | Anglers | BF | YF | YT | D | T/A | Moon
          // Species columns sized so "Yellowtail" (longest header) fits without truncation.
          const gridCols = '100px 1fr 80px 56px 80px 80px 88px 70px 60px 84px';
          const headerStyle = {
            padding:'8px 12px', borderBottom:'1px solid var(--ss-border-2)',
            display:'grid', gridTemplateColumns: gridCols, gap:8,
            font:'700 10px/12px var(--ss-font-sans)', textTransform:'uppercase', letterSpacing:'.06em',
            color:'var(--ss-slate)', background:'var(--ss-clay)',
            position:'sticky', top:0, zIndex:1,
          };
          const numStyle = { textAlign:'right' };
          const speciesHeaderStyle = (sp) => ({ ...numStyle, color: SPECIES_COLORS[sp] });
          return (
            <Fragment>
              <div style={headerStyle}>
                <span>Date</span>
                <span>Species Mix</span>
                <span>Trip Length</span>
                <span style={numStyle}>Anglers</span>
                <span style={speciesHeaderStyle('Bluefin')}>Bluefin</span>
                <span style={speciesHeaderStyle('Yellowfin')}>Yellowfin</span>
                <span style={speciesHeaderStyle('Yellowtail')}>Yellowtail</span>
                <span style={speciesHeaderStyle('Dorado')}>Dorado</span>
                <span style={numStyle}>T/A</span>
                <span>Moon</span>
              </div>
              <div style={{maxHeight: 480, overflow: 'auto'}}>
                {sortedTrips.length === 0 && (
                  <div className="muted-block" style={{padding:'12px'}}>No trips logged yet.</div>
                )}
                {sortedTrips.map(t => {
                  const trTotal = t.totalTuna || 1;
                  const rowStyle = {
                    padding:'8px 12px', borderBottom:'1px solid var(--ss-border-2)',
                    display:'grid', gridTemplateColumns: gridCols, gap:8, alignItems:'center',
                    font:'400 12px/16px var(--ss-font-sans)',
                  };
                  const cell = (v, sp) => (
                    <span className="num" style={{
                      textAlign:'right', fontVariantNumeric:'tabular-nums',
                      fontWeight: v > 0 ? 500 : 400,
                      color: v > 0 ? SPECIES_COLORS[sp] : 'var(--ss-gray-2)',
                    }}>{v > 0 ? v : '—'}</span>
                  );
                  return (
                    <div key={t.id} style={rowStyle}>
                      <span>{fmt.date(t.date)}</span>
                      <span style={{display:'flex', height: 8, borderRadius: 2, overflow:'hidden', background:'var(--ss-border-2)'}}>
                        {window.SD.SPECIES.map(sp => {
                          const w = (t[sp]||0)/trTotal*100;
                          return w > 0 ? <span key={sp} title={`${sp}: ${t[sp]}`} style={{width: `${w}%`, background: SPECIES_COLORS[sp]}}></span> : null;
                        })}
                      </span>
                      <span style={{font:'400 11px/14px var(--ss-font-sans)', color:'var(--ss-slate)'}}>{t.tripLength}</span>
                      <span className="num" style={{textAlign:'right', fontVariantNumeric:'tabular-nums'}}>{t.anglers}</span>
                      {cell(t.Bluefin, 'Bluefin')}
                      {cell(t.Yellowfin, 'Yellowfin')}
                      {cell(t.Yellowtail, 'Yellowtail')}
                      {cell(t.Dorado, 'Dorado')}
                      <span className="num" style={{textAlign:'right', fontVariantNumeric:'tabular-nums', color:'var(--ss-darkseagreen-500)', fontWeight:700}}>{fmt.tpa(t.totalTuna/Math.max(1,t.anglers))}</span>
                      <span style={{display:'flex', alignItems:'center', gap:6, font:'400 11px/14px var(--ss-font-sans)', color:'var(--ss-slate)'}}>
                        <span style={{transform:'scale(0.5)', transformOrigin:'left center', display:'inline-block'}}>
                          <MoonGlyph phase={t.moonPhase}/>
                        </span>
                        {t.moonIllum}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </Fragment>
          );
        })()}
      </Panel>}
    </Fragment>
  );
}

// Landing detail drill-down
function LandingDetail({ filters, setFilters, navigate, landing }) {
  const trips = useMemo(() => SDA.filterTrips({ ...filters, landing }), [filters, landing]);
  const { rows: boats, fleetMedianTPA } = useMemo(
    () => SDA.boatLeaderboard(trips, filters.species, Math.min(filters.minTrips, 3)),
    [trips, filters.species, filters.minTrips]
  );
  const sf = SDA.speciesField(filters.species);
  const total = trips.reduce((s,t)=>s + (t[sf]||0), 0);
  const anglers = trips.reduce((s,t)=>s + t.anglers, 0);
  const tpa = anglers ? total/anglers : 0;
  const monthly = SDA.monthlyTrend(trips, filters.species);
  const speciesMix = SDA.speciesMix(trips);
  const lengthData = SDA.tripLengthBreakdown(trips, filters.species);
  const bestMonth = [...monthly].sort((a,b)=>b.tpa-a.tpa)[0];
  const bestLen = [...lengthData].sort((a,b)=>b.tpa-a.tpa)[0];
  const topBoat = boats[0];

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'landings' }) },
        { label: 'Landings', onClick: () => navigate('analytics', { subtab: 'landings' }) },
        { label: landing },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>{landing}</h1>
          <div className="sub">{boats.length} boats · {fmt.n(trips.length)} trips · {fmt.n(anglers)} anglers in scope</div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters}/>

      <div className="kpis">
        <KPI label="Tuna / Angler" value={fmt.tpa(tpa)}/>
        <KPI label="Total Tuna" value={fmt.n(total)} ctx={`${fmt.n(anglers)} anglers`}/>
        <KPI label="Best Boat" value={topBoat?.boat || '—'} ctx={topBoat ? `${fmt.tpa(topBoat.avgTPA)} t/a` : ''}/>
        <KPI label="Peak Month" value={bestMonth ? MONTH_NAMES[bestMonth.month-1] : '—'} ctx={bestLen ? `Best length: ${bestLen.tripLength}` : ''}/>
      </div>

      <div className="detail-grid" style={{marginBottom: 12}}>
        <Panel title="Boats at this Landing" meta="Click to drill in" padding={false}>
          <div style={{overflowX: 'auto'}}>
            <table className="dt">
              <thead><tr>
                <th style={{width: 36}}>#</th><th>Boat</th><th className="num">Trips</th>
                <th className="num">Tuna/Angler</th><th className="num">Median</th><th className="num">Success</th><th>Label</th>
              </tr></thead>
              <tbody>
                {boats.map((b, i) => (
                  <tr key={b.boat} className="clickable" onClick={() => navigate('boat', { boat: b.boat })}>
                    <td><span className="rank" style={{color: i<3?'var(--ss-orange-500)':null, fontWeight: i<3?700:500}}>{i+1}</span></td>
                    <td><b>{b.boat}</b></td>
                    <td className="num">{b.tripCount}</td>
                    <td className={`num ${b.avgTPA > fleetMedianTPA ? 'hi' : ''}`}>{fmt.tpa(b.avgTPA)}</td>
                    <td className="num">{fmt.tpa(b.medTPA)}</td>
                    <td className="num">{fmt.pct(b.successRate, 0)}</td>
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

        <div style={{display:'flex', flexDirection:'column', gap: 12}}>
          <Panel title="Species Mix">
            <div style={{display:'flex', gap:12, alignItems:'center'}}>
              <Donut size={120} thickness={20} data={Object.entries(speciesMix).map(([k,v]) => ({ value: v, color: SPECIES_COLORS[k] }))}/>
              <div className="donut-legend" style={{flex: 1}}>
                {Object.entries(speciesMix).map(([sp, v]) => (
                  <div key={sp} className="ll">
                    <span className="sw" style={{background: SPECIES_COLORS[sp]}}></span>{sp}
                    <span className="pct">{fmt.pct(v/(total||1), 0)}</span>
                  </div>
                ))}
              </div>
            </div>
          </Panel>
          <Panel title="By Trip Length">
            {lengthData.sort((a,b)=>b.tpa-a.tpa).map(r => {
              const max = Math.max(...lengthData.map(x=>x.tpa), 0.01);
              return (
                <div key={r.tripLength} style={{display:'grid', gridTemplateColumns:'80px 1fr 50px', gap:8, alignItems:'center', padding:'5px 0'}}>
                  <span style={{font:'500 11px/14px var(--ss-font-sans)'}}>{r.tripLength}</span>
                  <div className="track" style={{height:10}}><div className="fill" style={{width:`${(r.tpa/max)*100}%`}}></div></div>
                  <span className="num" style={{font:'500 11px/14px var(--ss-font-sans)', textAlign:'right'}}>{fmt.tpa(r.tpa)}</span>
                </div>
              );
            })}
          </Panel>
        </div>
      </div>

      <Panel title="Monthly Catch Pattern" meta="Total tuna per month at this landing">
        <VBarChart width={1080} height={200}
          data={monthly.map((m,i) => ({ label: MONTH_NAMES[i], value: m.tuna, color: m === bestMonth ? '#FF7705' : '#008566' }))}
          formatY={v => fmt.n(Math.round(v))}/>
      </Panel>
    </Fragment>
  );
}

// Landings overview
function LandingsView({ filters, setFilters, navigate }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const landings = useMemo(() => SDA.landingSummary(trips, filters.species), [trips, filters.species]);
  const sf = SDA.speciesField(filters.species);
  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'overview' }) },
        { label: 'Landings' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Landings Comparison</h1>
          <div className="sub">All four approved San Diego sportfishing landings</div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters}/>

      <div className="landings-grid" style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:12, marginBottom: 12}}>
        {landings.map(l => {
          const max = Math.max(...landings.map(x => x.tpa), 0.01);
          return (
            <div key={l.landing} className="kpi" style={{cursor:'pointer'}} onClick={() => navigate('landing', { landing: l.landing })}>
              <div className="k">{l.landing}</div>
              <div className="v">{fmt.tpa(l.tpa)} <span className="u">{speciesLabel.toLowerCase()}/angler</span></div>
              <div className="track" style={{height: 6, marginTop: 8}}>
                <div className="fill" style={{width: `${(l.tpa/max)*100}%`}}></div>
              </div>
              <div className="ctx" style={{marginTop: 8, display:'flex', justifyContent:'space-between'}}>
                <span>{l.boatCount} boats · {fmt.n(l.trips)} trips</span>
                <span style={{color:'var(--ss-darkseagreen-500)'}}>View →</span>
              </div>
            </div>
          );
        })}
      </div>

      <Panel title="Side-by-Side Comparison" padding={false}>
        <table className="dt">
          <thead><tr>
            <th>Landing</th><th className="num">Boats</th><th className="num">Trips</th>
            <th className="num">Anglers</th><th className="num">Total {speciesLabel}</th>
            <th className="num">{speciesLabel}/Angler</th><th className="num">Success Rate</th>
            <th>Species Mix</th>
          </tr></thead>
          <tbody>
            {landings.map((l, i) => {
              const total = Object.values(l.bySpecies).reduce((a,b)=>a+b,0) || 1;
              return (
                <tr key={l.landing} className="clickable" onClick={() => navigate('landing', { landing: l.landing })}>
                  <td><b>{l.landing}</b></td>
                  <td className="num">{l.boatCount}</td>
                  <td className="num">{fmt.n(l.trips)}</td>
                  <td className="num">{fmt.n(l.anglers)}</td>
                  <td className="num">{fmt.n(l.tuna)}</td>
                  <td className={`num ${i === 0 ? 'hi' : ''}`}>{fmt.tpa(l.tpa)}</td>
                  <td className="num">{fmt.pct(l.successRate, 0)}</td>
                  <td>
                    <div style={{display:'flex', height: 12, width: 200, borderRadius: 2, overflow:'hidden'}}>
                      {window.SD.SPECIES.map(sp => {
                        const w = (l.bySpecies[sp]||0)/total*100;
                        return w > 0.5 ? <span key={sp} title={`${sp}: ${l.bySpecies[sp]}`} style={{width:`${w}%`, background:SPECIES_COLORS[sp]}}></span> : null;
                      })}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
    </Fragment>
  );
}

Object.assign(window, { BoatDetail, LandingDetail, LandingsView });
