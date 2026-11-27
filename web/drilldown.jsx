// Boat detail drill-down
const { useEffect, useMemo } = React;
// Next departures with the NWS sea-conditions forecast for each (web/marine.js).
// Hidden when no upcoming trip falls inside the NWS forecast or it is stale.
function BoatSeaPanel({ boat }) {
  const M = window.TTMarine;
  const marine = window.SD && window.SD.MARINE;
  if (!M || !marine) return null;
  const now = Date.now();
  const rows = (window.SD.SCHEDULE || [])
    .filter(t => t.boat === boat && t.departureAt && Date.parse(t.departureAt) > now)
    .sort((a, b) => Date.parse(a.departureAt) - Date.parse(b.departureAt))
    .map(t => ({ t, sea: M.forTrip(marine, t, now) }))
    .filter(r => r.sea)
    .slice(0, 4);
  if (!rows.length) return null;
  const day = (iso) => new Date(iso).toLocaleDateString('en-US',
    { timeZone: 'America/Los_Angeles', weekday: 'short', month: 'short', day: 'numeric' });
  return (
    <div style={{marginBottom: 12}}>
    <Panel title="Next trips · sea conditions" meta="NWS forecast" padding={false}>
      <ul className="dd-sea">
        {rows.map(({ t, sea }) => (
          <li key={t.departureAt + t.tripLength} className={sea.rough ? 'rough' : ''}>
            <span className="dd-sea-when">{day(t.departureAt)} · {t.tripLength}</span>
            <span className="dd-sea-line">
              {sea.atDeparture ? 'At departure: ' : ''}{M.line(sea)}
              {sea.advisory ? ` · ${sea.advisory.event}` : sea.rough ? ' · rough' : ''}
            </span>
          </li>
        ))}
      </ul>
      <div className="dd-sea-foot">National Weather Service coastal waters forecast:
        inshore 0–10 nm for half-day trips, offshore 10–60 nm for overnight and longer.</div>
    </Panel>
    </div>
  );
}

function BoatDetail({ filters, setFilters, navigate, boat, regions }) {
  const [detailTab, setDetailTab] = React.useState('overview');
  const [reviewOpenSignal, setReviewOpenSignal] = React.useState(0);
  const [isSaved, setIsSaved] = React.useState(function() { return window.getSavedBoats().has(boat); });
  useEffect(function() {
    function sync() { setIsSaved(window.getSavedBoats().has(boat)); }
    window.addEventListener('tt-saved-boats-changed', sync);
    return function() { window.removeEventListener('tt-saved-boats-changed', sync); };
  }, [boat]);
  // Boat detail shows all history — no global filters applied here.
  const _ALL = { year: 'all', species: 'all', landing: 'all', month: 'all', minTrips: 0, includeZero: true, boat: 'all' };
  const allTrips = useMemo(() => SDA.filterTrips(_ALL).filter(t => t.boat === boat), [boat]);
  const fleetTrips = useMemo(() => SDA.filterTrips(_ALL, regions), [regions]);
  const meta = window.SD.BOATS.find(b => b.name === boat);
  useEffect(() => {
    if (meta && window.TTTrack) TTTrack.boatView(boat, meta.landing || '');
  }, [boat]);
  if (!meta) return <div className="muted-block">Boat not found.</div>;

  const sf = SDA.speciesField('all');
  const totalTuna = allTrips.reduce((s,t) => s + (t[sf]||0), 0);
  const totalAnglers = allTrips.reduce((s,t) => s + t.anglers, 0);
  const tpa = totalAnglers ? totalTuna/totalAnglers : 0;
  const tpas = allTrips.map(t => (t[sf]||0)/Math.max(1,t.anglers));
  const medTPA = SDA.median(tpas);
  const successRate = allTrips.length ? allTrips.filter(t => (t[sf]||0)>0).length/allTrips.length : 0;

  const fleetMedTPA = SDA.median(fleetTrips.map(t => (t[sf]||0)/Math.max(1,t.anglers)));

  // Per-species breakdown
  const speciesBreakdown = window.SD.SPECIES.map(sp => {
    const total = allTrips.reduce((s,t) => s + (t[sp]||0), 0);
    const tpa = totalAnglers ? total/totalAnglers : 0;
    return { species: sp, total, tpa };
  }).sort((a,b)=>b.tpa-a.tpa);

  // Monthly
  const monthly = SDA.monthlyTrend(allTrips, 'all');
  // All this boat's trips, newest first. (Was previously "top 12 by TPA"; now
  // we show the full history so anglers can scan past performance.)
  const sortedTrips = [...allTrips].sort((a, b) => {
    if (a.date !== b.date) return b.date.localeCompare(a.date);
    return (b.id || 0) - (a.id || 0);
  });

  // Trip length mix
  const lengthMix = SDA.tripLengthBreakdown(allTrips, 'all');

  // Determine label
  const bestTripCatch = Math.max(0, ...allTrips.map(t => t[sf]||0));
  const bestPct = totalTuna ? bestTripCatch/totalTuna : 0;
  let label = null;
  if (allTrips.length >= 3) {
    if (tpa > fleetMedTPA && medTPA > fleetMedTPA && successRate > 0.6) label = 'Consistent';
    else if (bestPct > 0.4 && allTrips.length < 25) label = 'Spike';
  }

  const profile = window.SD?.BOAT_PROFILES?.[boat];

  // H2H win rate: aggregate across all trip lengths with sufficient matchup data
  const h2hWinRate = useMemo(() => {
    try {
      const raw = SDA.boatWinRates ? SDA.boatWinRates() : {};
      let wins = 0, matchupCount = 0;
      for (const [key, val] of Object.entries(raw)) {
        if (key.split('|')[0] !== boat || val.winRate == null) continue;
        wins         += val.wins;
        matchupCount += val.matchupCount;
      }
      return matchupCount > 0 ? { winRate: wins / matchupCount, matchupCount } : null;
    } catch(e) { return null; }
  }, [boat]);

  const tpRateData = useMemo(() => {
    try { return SDA.boatTopPerformerRates ? SDA.boatTopPerformerRates()[boat] ?? null : null; }
    catch(e) { return null; }
  }, [boat]);

  return (
    <React.Fragment>
      <Crumbs items={[
        { label: 'Boats', onClick: () => navigate('boats', {}) },
        { label: boat },
      ]}/>

      {/* ── Hero photo (when profile data exists) ── */}
      {profile?.photoUrl && (
        <div className="boat-hero">
          <img src={profile.photoUrl} alt={boat} className="boat-hero-img"/>
          <div className="boat-hero-overlay">
            <div className="boat-hero-name">
              {boat}
              {label === 'Consistent' && <span className="tag consistent" style={{marginLeft:8, verticalAlign:'middle'}}>Consistent</span>}
              {label === 'Spike' && <span className="tag spike" style={{marginLeft:8, verticalAlign:'middle'}}>One-Off Spike</span>}
            </div>
            {profile.captains?.length > 0 && (
              <div className="boat-hero-captains">
                Captains: {profile.captains.join(' · ')}
              </div>
            )}
            <div className="boat-hero-badges">
              <ReviewBadge boat={boat}/>
            </div>
          </div>
        </div>
      )}

      <div className={`pagehead boat-pagehead${profile?.photoUrl ? ' has-hero' : ''}`}>
        <div>
          <div style={{display:'flex', alignItems:'center', gap: 12, flexWrap:'wrap'}}>
            {/* With a hero photo the name is already on the photo; the h1 stays
                for screen readers and search but is not shown twice. */}
            <h1 style={{margin:0}} className={profile?.photoUrl ? 'sr-only' : ''}>{boat}</h1>
            {!profile?.photoUrl && label === 'Consistent' && <span className="tag consistent">Consistent Outperformer</span>}
            {!profile?.photoUrl && label === 'Spike' && <span className="tag spike">One-Off Spike</span>}
            {!profile?.photoUrl && <ReviewBadge boat={boat}/>}
          </div>
          <div className="sub">
            <button className="sub-landing-link" onClick={() => navigate('landing', { landing: meta.landing })}>
              {meta.landing}
            </button>
            {' · '}{meta.lengths.join(', ')} · {allTrips.length} trips in scope
            {profile?.lengthFt && ` · ${profile.lengthFt} ft`}
            {profile?.yearBuilt && ` · Built ${profile.yearBuilt}`}
          </div>
        </div>
        {/* One primary action (book), secondary outline actions, and a quiet
            compare link. "Upcoming Trips" went to the same page as Book. */}
        <div className="actions boat-actions">
          <button className="btn ghost" onClick={() => navigate('analytics', { subtab: 'headtohead' })}>
            <i className="fa-solid fa-code-compare"></i> Compare
          </button>
          <button className={`btn secondary${isSaved ? ' is-on' : ''}`} aria-pressed={isSaved}
                  onClick={function() { window.toggleSavedBoat(boat); }}>
            <i className={`${isSaved ? 'fa-solid' : 'fa-regular'} fa-bookmark`}></i> {isSaved ? 'Saved' : 'Save'}
          </button>
          <button className="btn secondary"
                  onClick={() => { setDetailTab('reviews'); setReviewOpenSignal(s => s + 1); }}>
            <i className="fa-regular fa-pen-to-square"></i> Write a review
          </button>
          {/* OC/LA landings have no schedule feed: link to the landing's own booking page. */}
          {window.OCLA_LANDING_SITES && window.OCLA_LANDING_SITES[meta.landing] ? (
            <a className="btn primary" href={window.OCLA_LANDING_SITES[meta.landing]} target="_blank" rel="noopener">
              Book with {meta.landing} <i className="fa-solid fa-arrow-up-right-from-square"></i>
            </a>
          ) : (
            <button className="btn primary" onClick={() => navigate('tripplanner')}>
              Book a trip <i className="fa-solid fa-arrow-right"></i>
            </button>
          )}
        </div>
      </div>

      {/* ── Boat description (when available) ── */}
      {profile?.description && (
        <div className="boat-profile-desc">{profile.description}</div>
      )}
      <div className="kpis">
        <KPI label="Tuna / Angler" value={fmt.tpa(tpa)} ctx={`${fmt.n(totalAnglers)} anglers · ${allTrips.length} trips`}/>
        <KPI label="Total Fish" value={fmt.n(totalTuna)} ctx={`All tracked species`}/>
        {h2hWinRate && (
          <KPI
            label={<MetricLabel {...METRIC_DEFINITIONS.winRate} />}
            value={`${Math.round(h2hWinRate.winRate * 100)}%`}
            ctx={`${h2hWinRate.matchupCount} matchups`}
          />
        )}
        {tpRateData && (
          <KPI
            label={<MetricLabel {...METRIC_DEFINITIONS.topPerformerRate} />}
            value={<TopPerformerBadge tier={tpRateData.tier} pct={tpRateData.rate} />}
            ctx={`${tpRateData.wins}/${tpRateData.total} trips`}
          />
        )}
      </div>

      <div className="detail-grid" style={{marginBottom: 12}}>
        <Panel title="Catch Rate Through the Year" meta="Tuna/angler by month, this boat vs landing average">
          {/* Combined bar+line: this boat vs landing avg */}
          {(() => {
            const landingAvg = window.SD.TRIPS.filter(t => t.landing === meta.landing);
            const landingMonthly = SDA.monthlyTrend(landingAvg, 'all');
            const max = Math.max(...monthly.map(m=>m.tpa), ...landingMonthly.map(m=>m.tpa), 0.001);
            return (
              <React.Fragment>
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
              </React.Fragment>
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

      <BoatSeaPanel boat={boat}/>

      {/* ── Bottom tabs: Trip History / Reviews ── */}
      <div className="dd-tabs">
        {[['overview','Trip History'],['reviews','Reviews']].map(([id,lbl]) => (
          <button key={id}
            className={`dd-tab${detailTab === id ? ' active' : ''}`}
            onClick={() => setDetailTab(id)}>
            {lbl}
            {id === 'reviews' && (() => {
              const n = window.SD.REVIEWS?.summary?.[boat]?.total_reviews;
              return n ? <span className="dd-tab-count">{n}</span> : null;
            })()}
          </button>
        ))}
      </div>

      {detailTab === 'reviews' && (
        <>
          <ReviewsSection boat={boat} landing={meta.landing} openSignal={reviewOpenSignal}/>
          {window.ForumReportsSection && <ForumReportsSection boat={boat}/>}
          {window.LandingNotesSection && <LandingNotesSection boat={boat}/>}
          {window.GoogleReviewsSection && <GoogleReviewsSection boat={boat} landing={meta.landing}/>}
          {window.BoatVideosSection && <BoatVideosSection boat={boat}/>}
        </>
      )}

      {detailTab === 'overview' && <TripHistory trips={sortedTrips} boat={boat}/>}
    </React.Fragment>
  );
}

// ── Trip history (boat page) ─────────────────────────────────────────────────
// A compact list, newest first, grouped by month, 10 trips at a time. Each row
// reads as a sentence: date, trip, anglers, moon; then everything landed
// (headline species first) and the boat's fish per angler for that trip. Was a
// 9-column, 720px-min table in a 480px scroll box that scrolled both ways
// on phones and showed only the four trophy columns (OC/LA rockfish trips read
// as all dashes next to a non-zero rate).
const TH_STEP = 10;
const TH_HEAD = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];
function thCatch(t, allSpecies) {
  const by = (SDA.catchBySpecies ? SDA.catchBySpecies(t) : null) ||
    TH_HEAD.reduce((o, sp) => { if (t[sp] > 0) o[sp] = t[sp]; return o; }, {});
  return Object.keys(by).map(sp => ({ sp, n: by[sp], head: TH_HEAD.indexOf(sp) >= 0 }))
    .sort((a, b) => (allSpecies ? 0 : b.head - a.head) || (b.n - a.n));
}
function thRate(x) { return x >= 10 ? String(Math.round(x)) : x.toFixed(1); }
function TripHistory({ trips, boat }) {
  const [shown, setShown] = React.useState(TH_STEP);
  // Owner wording (#13): "fish". On San Diego the count is the four headline species.
  const noun = 'fish';
  const allSpecies = !!(window.SD_METRIC && window.SD_METRIC.allSpecies);
  const visible = trips.slice(0, shown);
  // Month groups over the visible rows; totals cover the whole month.
  const monthStats = {};
  trips.forEach(t => {
    const k = t.date.slice(0, 7);
    const m = monthStats[k] || (monthStats[k] = { n: 0, fish: 0, anglers: 0 });
    m.n++; m.fish += t.totalTuna || 0; m.anglers += t.anglers || 0;
  });
  const groups = [];
  visible.forEach(t => {
    const k = t.date.slice(0, 7);
    if (!groups.length || groups[groups.length - 1].k !== k) groups.push({ k, trips: [] });
    groups[groups.length - 1].trips.push(t);
  });
  const monthLabel = k => new Date(k + '-15T12:00:00').toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
  const dayLabel = d => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  const left = trips.length - shown;
  return (
    <section className="tph" aria-labelledby="tph-title">
      <div className="tph-head">
        <h3 className="tph-title" id="tph-title">Trip history</h3>
        <div className="tph-sub">{trips.length.toLocaleString()} trip{trips.length === 1 ? '' : 's'} for {boat}, newest first. The number on the right is {noun} per angler.</div>
      </div>
      {trips.length === 0 && <p className="tph-empty">No trips logged yet.</p>}
      {groups.map(g => {
        const m = monthStats[g.k];
        return (
          <div key={g.k} className="tph-month">
            <div className="tph-month-h">
              <span className="tph-month-name">{monthLabel(g.k)}</span>
              <span className="tph-month-meta">{m.n} trip{m.n === 1 ? '' : 's'} · {m.anglers ? thRate(m.fish / m.anglers) : '—'} per angler</span>
            </div>
            <ol className="tph-list">
              {g.trips.map(t => {
                const c = thCatch(t, allSpecies);
                const rate = t.anglers ? (t.totalTuna || 0) / t.anglers : 0;
                const more = c.length > 4 ? c.length - 4 : 0;
                return (
                  <li key={t.id} className="tph-row">
                    <div className="tph-when">
                      <span className="tph-date">{dayLabel(t.date)}</span>
                      <span className="tph-meta">{[t.tripLength, t.anglers ? `${t.anglers} anglers` : null, t.moonPhase ? `${t.moonPhase.toLowerCase()} moon` : null].filter(Boolean).join(' · ')}</span>
                    </div>
                    <div className="tph-catch">
                      {c.length === 0 ? <span className="tph-none">No fish reported</span> : (
                        <React.Fragment>
                          {c.slice(0, 4).map(x => (
                            <span key={x.sp} className={'tph-sp' + (x.head || allSpecies ? '' : ' tph-sp-minor')}>
                              {x.head && <i style={{ background: SPECIES_COLORS[x.sp] }} aria-hidden="true"/>}
                              <b>{x.n.toLocaleString()}</b> {x.sp.toLowerCase()}
                            </span>
                          ))}
                          {more > 0 && <span className="tph-sp tph-sp-minor" title={c.slice(4).map(x => `${x.n} ${x.sp.toLowerCase()}`).join(', ')}>+{more} more</span>}
                        </React.Fragment>
                      )}
                    </div>
                    <div className={'tph-rate' + (rate > 0 ? '' : ' zero')} aria-label={`${thRate(rate)} ${noun} per angler`}>
                      <b>{thRate(rate)}</b><span>per angler</span>
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        );
      })}
      {left > 0 && (
        <div className="tph-more">
          <button type="button" onClick={() => setShown(n => n + 25)}>Show {Math.min(25, left)} more</button>
          <span className="tph-count">Showing {shown.toLocaleString()} of {trips.length.toLocaleString()}</span>
          {left > 25 && <button type="button" className="tph-all" onClick={() => setShown(trips.length)}>Show all</button>}
        </div>
      )}
    </section>
  );
}

// Landing detail drill-down
function LandingDetail({ filters, setFilters, navigate, landing, regions }) {
  const trips = useMemo(() => SDA.filterTrips({ ...filters, landing }), [filters, landing]);
  const { rows: boats } = useMemo(
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
    <React.Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'overview' }) },
        { label: landing },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>{landing}</h1>
          <div className="sub">{boats.length} boats · {fmt.n(trips.length)} trips · {fmt.n(anglers)} anglers in scope</div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters} regions={regions}/>

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
                <th className="num">{SDA.rankLabel()}/Angler</th><th>Label</th>
              </tr></thead>
              <tbody>
                {boats.map((b, i) => (
                  <tr key={b.boat} className="clickable" onClick={() => navigate('boat', { boat: b.boat })}>
                    <td><span className="rank" style={{color: i<3?'var(--ss-orange-500)':null, fontWeight: i<3?700:500}}>{i+1}</span></td>
                    <td><b>{b.boat}</b></td>
                    <td className="num">{b.tripCount}</td>
                    <td className="num">{fmt.tpa(b.avgTPA)}</td>
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
      {window.BaitNowPanel && <BaitNowPanel landing={landing}/>}
      {window.GoogleReviewsSection && <GoogleReviewsSection boat={null} landing={landing}/>}
    </React.Fragment>
  );
}

// Landings overview
function LandingsView({ filters, setFilters, navigate, regions }) {
  const trips = useMemo(() => SDA.filterTrips(filters, regions), [filters, regions]);
  const landings = useMemo(() => SDA.landingSummary(trips, filters.species), [trips, filters.species]);
  const sf = SDA.speciesField(filters.species);
  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : SDA.headlineLabel();

  return (
    <React.Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'overview' }) },
        { label: 'Landings' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Landings Comparison <span className="region-subtitle-badge">{(regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego'}</span></h1>
          <div className="sub">{(regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego'} sportfishing landings</div>
        </div>
      </div>
      <FilterBar filters={filters} setFilters={setFilters} regions={regions}/>

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
            <th className="num">{speciesLabel}/Angler</th>
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
    </React.Fragment>
  );
}

Object.assign(window, { BoatDetail, LandingDetail, LandingsView });
