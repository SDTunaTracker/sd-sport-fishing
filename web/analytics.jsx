// Analytics view — full filter controls, KPIs, charts, leaderboard

// Mobile-only filter modal — local state, syncs to real filters on Apply
function AnalyticsMobileFilterModal({ open, onClose, filters, onApply, regions }) {
  const { useState, useEffect, useMemo } = React;
  const df = window.DEFAULT_FILTERS;

  const [year,       setYear]       = useState(filters.year);
  const [month,      setMonth]      = useState(filters.month);
  const [landing,    setLanding]    = useState(filters.landing);
  const [boat,       setBoat]       = useState(filters.boat);
  const [tripLength, setTripLength] = useState(filters.tripLength);
  const [species,    setSpecies]    = useState(filters.species);
  const [minTrips,   setMinTrips]   = useState(filters.minTrips);

  useEffect(() => {
    if (open) {
      setYear(filters.year); setMonth(filters.month); setLanding(filters.landing);
      setBoat(filters.boat); setTripLength(filters.tripLength);
      setSpecies(filters.species); setMinTrips(filters.minTrips);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const handleReset = () => {
    setYear(df.year); setMonth(df.month); setLanding(df.landing);
    setBoat(df.boat); setTripLength(df.tripLength);
    setSpecies(df.species); setMinTrips(df.minTrips);
  };

  const handleApply = () => {
    onApply({ ...filters, year, month, landing, boat, tripLength, species, minTrips });
    onClose();
  };

  if (!open) return null;

  const SL = { font: '600 11px/14px var(--ss-font-sans)', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--tb-slate)', marginBottom: 8 };
  const YEARS = [...new Set(window.SD.TRIPS.map(t => t.year))].sort((a, b) => b - a).map(y => ({ value: String(y), label: String(y) }));
  const _rl = (() => {
    if (!regions || !window.getEffectiveRegion) return null;
    const eff = window.getEffectiveRegion(regions);
    return window.getLandingsForRegion ? window.getLandingsForRegion(eff) : null;
  })();
  const landingOptions = window.SD.LANDINGS.filter(l => !_rl || _rl.includes(l));
  const boatOptions = [...window.SD.BOATS].filter(b => !_rl || _rl.includes(b.landing)).sort((a, b) => a.name.localeCompare(b.name)).map(b => b.name);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 480 }} onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <h2 style={{ margin: 0, font: '600 18px/22px var(--ss-font-sans)' }}>Filters</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 20, maxHeight: '72vh', overflowY: 'auto' }}>
          <div><div style={SL}>Year</div>
            <MultiSelect options={YEARS} value={year} onChange={setYear} allLabel="All Years"/></div>
          <div><div style={SL}>Month</div>
            <MultiSelect options={MONTH_NAMES.map((m, i) => ({ value: String(i + 1), label: m }))}
                         value={month} onChange={setMonth} allLabel="All Months"/></div>
          <div><div style={SL}>Landing</div>
            <MultiSelect options={landingOptions} value={landing} onChange={setLanding} allLabel="All Landings"/></div>
          <div><div style={SL}>Boat</div>
            <MultiSelect options={boatOptions} value={boat} onChange={setBoat} allLabel="All Boats"/></div>
          <div><div style={SL}>Trip Length</div>
            <MultiSelect options={window.SD.TRIP_LENGTHS} value={tripLength} onChange={setTripLength} allLabel="All Lengths"/></div>
          <div><div style={SL}>Species</div>
            <MultiSelect options={window.SD.SPECIES} value={species} onChange={setSpecies} allLabel="All Tuna"/></div>
          <div><div style={SL}>Min Trips</div>
            <input type="number" min="0" max="100" value={minTrips} onChange={e => setMinTrips(+e.target.value || 0)}
                   style={{ height: 32, border: '1px solid var(--tb-border-2)', borderRadius: 6, padding: '0 8px', font: '500 12px/16px var(--ss-font-sans)', width: 80 }}/></div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', borderTop: '1px solid var(--tb-border-2)', background: 'var(--tb-foam)', borderRadius: '0 0 12px 12px' }}>
          <button className="btn ghost" onClick={handleReset}>Reset</button>
          <button className="btn primary" onClick={handleApply}>Apply</button>
        </div>
      </div>
    </div>
  );
}

// ── Streak Tracker ────────────────────────────────────────────────────────────
function _streakCfg(goodCount) {
  if (goodCount >= 9) return { emoji: '🔥', label: 'On Fire',     color: '#22C55E', bg: 'rgba(34,197,94,0.12)' };
  if (goodCount >= 7) return { emoji: '🔥', label: 'Hot',         color: '#10B981', bg: 'rgba(16,185,129,0.12)' };
  if (goodCount >= 5) return { emoji: '➡️', label: 'Steady',      color: '#94A3B8', bg: 'rgba(148,163,184,0.12)' };
  if (goodCount >= 3) return { emoji: '❄️', label: 'Cold',        color: '#60A5FA', bg: 'rgba(96,165,250,0.12)' };
  return                     { emoji: '❄️', label: 'Struggling',  color: '#EF4444', bg: 'rgba(239,68,68,0.12)' };
}

function StreakTracker({ navigate, regions }) {
  const { useMemo, useState } = React;
  const [tabFilter, setTabFilter] = useState('all');

  const streaks = useMemo(() => {
    const _ALL = { year:'all', species:'all', landing:'all', month:'all', minTrips:0, includeZero:true, boat:'all' };
    const all = SDA.boatStreaks(SDA.filterTrips(_ALL, regions));
    const cutoff = (() => { const d = new Date(); d.setMonth(d.getMonth() - 4); return d.toISOString().slice(0, 10); })();
    return all.filter(b => {
      const lastDate = b.last10.reduce((max, t) => (t.date && t.date > max ? t.date : max), '');
      return lastDate >= cutoff;
    });
  }, [regions]);

  const filtered = useMemo(() => {
    if (tabFilter === 'hot')  return streaks.filter(b => b.goodCount >= 7);
    if (tabFilter === 'cold') return streaks.filter(b => b.goodCount <= 4);
    return streaks;
  }, [streaks, tabFilter]);

  const tabs = [['all','All'],['hot','🔥 Hot'],['cold','❄️ Cold']];

  return (
    <Panel title="Recent Form"
           meta="Last 10 trips per boat — above (✅) or below (❌) fleet median for that trip length · min 10 trips"
           actions={
             <div className="row" style={{gap:4}}>
               {tabs.map(([val, lbl]) => (
                 <span key={val} className={`filter-pill ${tabFilter===val?'on':''}`}
                       onClick={() => setTabFilter(val)}>{lbl}</span>
               ))}
             </div>
           }>
      {filtered.length === 0 ? (
        <div className="muted-block">No boats with 10+ trips match this filter.</div>
      ) : (
        <div className="streak-list">
          {filtered.map(b => {
            const cfg = _streakCfg(b.goodCount);
            return (
              <div key={b.boat} className="streak-row" style={{cursor:'pointer'}}
                   onClick={() => navigate('boat', { boat: b.boat })}>
                <div className="streak-name" title={`${b.landing} · ${b.totalTrips} trips total`}>
                  {b.boat}
                </div>
                <div className="streak-dots">
                  {b.last10.map((d, i) => {
                    const mo = d.date ? new Date(d.date + 'T12:00:00').toLocaleString('en-US',{month:'short',day:'numeric'}) : d.date;
                    return (
                      <span key={i}
                            title={`${mo} · ${d.tpa.toFixed(2)} tpa`}
                            className="streak-dot"
                            style={{background: d.good ? '#10B981' : '#EF4444'}}/>
                    );
                  })}
                </div>
                <div className="streak-score">{b.goodCount}/10</div>
                <span className="streak-badge" style={{color: cfg.color, background: cfg.bg}}>
                  {cfg.emoji} {cfg.label}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function AnalyticsView({ filters, setFilters, navigate, tweaks, settings, regions, subtab = 'overview' }) {
  const { useMemo, useState } = React;

  const SUBTABS = [
    { id: 'overview',    label: 'Overview' },
    { id: 'headtohead',  label: 'Head-to-Head' },
    { id: 'seasonality', label: 'Seasonality' },
    { id: 'moon',        label: 'Moon Phase' },
  ];

  const [mobileFilterOpen, setMobileFilterOpen] = useState(false);
  const df = window.DEFAULT_FILTERS;
  const activeFilterCount = [
    filters.year !== df.year,
    filters.month !== df.month,
    filters.landing !== df.landing,
    filters.boat !== df.boat,
    filters.tripLength !== df.tripLength,
    filters.species !== df.species,
    filters.minTrips !== df.minTrips,
  ].filter(Boolean).length;

  const trips = useMemo(() => SDA.filterTrips(filters, regions), [filters, settings, regions]);
  const prevTrips = useMemo(() => {
    const f = { ...filters };
    if (f.year !== 'all') f.year = String(+f.year - 1);
    return SDA.filterTrips(f, regions);
  }, [filters, settings, regions]);

  const { rows: leaderboard } = useMemo(
    () => SDA.boatLeaderboard(trips, filters.species, filters.minTrips),
    [trips, filters.species, filters.minTrips]
  );
  const eligibleBoats = leaderboard.filter(r => r.tripCount >= filters.minTrips);

  const totalTuna    = trips.reduce((s, t) => s + (filters.species && filters.species !== 'all' ? (t[filters.species]||0) : t.totalTuna), 0);
  const totalAnglers = trips.reduce((s, t) => s + t.anglers, 0);
  const fleetTPA     = totalAnglers ? totalTuna / totalAnglers : 0;
  const prevTuna     = prevTrips.reduce((s, t) => s + (filters.species && filters.species !== 'all' ? (t[filters.species]||0) : t.totalTuna), 0);
  const prevAnglers  = prevTrips.reduce((s, t) => s + t.anglers, 0);
  const prevTPA      = prevAnglers ? prevTuna / prevAnglers : 0;
  const tpaDelta     = prevTPA > 0 ? ((fleetTPA - prevTPA) / prevTPA) * 100 : null;

  const monthly   = useMemo(() => SDA.monthlyTrend(trips, filters.species), [trips, filters.species]);
  const lengthData = useMemo(() => SDA.tripLengthBreakdown(trips, filters.species), [trips, filters.species]);
  const landings  = useMemo(() => SDA.landingSummary(trips, filters.species), [trips, filters.species]);

  const topBoatLimit = tweaks.density === 'compact' ? 12 : 10;
  const topBoats = eligibleBoats.slice(0, topBoatLimit);
  const maxTPAPerDay = topBoats[0]?.avgTPAPerDay || 1;
  const bestMonth = [...monthly].sort((a, b) => b.tpa - a.tpa)[0];

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel  = speciesActive ? filters.species : 'Tuna';

  const _defSp = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];
  const _selSp = settings && settings.trophySpecies;
  const isCustomSpecies = _selSp && (
    _selSp.length !== _defSp.length || !_defSp.every(s => _selSp.includes(s))
  );

  return (
    <Fragment>
      {/* Sub-tab bar — always visible */}
      <div className="tabbar analytics-subtabbar">
        {SUBTABS.map(t => (
          <a key={t.id} className={subtab === t.id ? 'sel' : ''}
             onClick={() => navigate('analytics', { subtab: t.id })}>{t.label}</a>
        ))}
      </div>

      {/* Overview sub-tab */}
      {subtab === 'overview' && <Fragment>
      <AnalyticsMobileFilterModal
        open={mobileFilterOpen}
        onClose={() => setMobileFilterOpen(false)}
        filters={filters}
        onApply={setFilters}
        regions={regions}/>

      <Crumbs items={[{ label: 'Analytics' }, { label: 'Overview' }]}/>
      <div className="pagehead">
        <div>
          <h1>Overview <span className="region-subtitle-badge">{(regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego'}</span></h1>
          <div className="sub analytics-sub">
            {fmt.n(trips.length)} trips · {eligibleBoats.length} boats · {landings.length} landings
            {' · '}{filters.year === 'all' ? 'All years' : filters.year}
            {filters.species !== 'all' ? ` · ${filters.species} only` : ''}
          </div>
        </div>
        <div className="actions">
          <button className="btn secondary analytics-mobile-filter-btn" onClick={() => setMobileFilterOpen(true)}>
            ⚙️ Filter{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
          </button>
        </div>
      </div>

      <div className="analytics-filterbar-desktop">
        <FilterBar filters={filters} setFilters={setFilters} regions={regions}/>
      </div>

      {isCustomSpecies && (
        <div className="custom-species-banner" title={`Counting: ${_selSp.join(', ')}`}>
          <i className="fa-solid fa-chart-bar"/> Custom species: <b>{_selSp.join(', ')}</b>
        </div>
      )}

      <div className="kpis">
        <KPI label={`Fleet ${speciesLabel} / Angler`}
             value={fmt.tpa(fleetTPA)}
             delta={tpaDelta}
             deltaLabel="vs prior year"
             ctx={`${eligibleBoats.length} boats · ${fmt.n(trips.length)} trips`}/>
        <KPI label={`Total ${speciesLabel}`}
             value={fmt.n(totalTuna)}
             ctx={`${fmt.n(totalAnglers)} anglers fished`}/>
        <KPI label="Best Boat" value={topBoats[0]?.boat || '—'}
             ctx={topBoats[0] ? `${fmt.tpa(topBoats[0].avgTPA)} ${speciesLabel.toLowerCase()}/angler · ${topBoats[0].landing}` : ''}/>
        <KPI label="Peak Month"
             value={bestMonth ? MONTH_NAMES[bestMonth.month - 1] : '—'}
             ctx={bestMonth ? `${fmt.tpa(bestMonth.tpa)} ${speciesLabel.toLowerCase()}/angler · ${fmt.n(bestMonth.tuna)} caught` : ''}/>
      </div>

      {/* Top Boats leaderboard */}
      <div style={{marginBottom: 12}}>
        <Panel title={`Top Boats — ${speciesLabel} per Angler per Day`}
               meta={`Ranked by avg ${speciesLabel.toLowerCase()}/angler/day · min ${filters.minTrips} trips`}
               actions={<button className="btn sm ghost" onClick={() => navigate('boats', {})}>View All →</button>}>
          {topBoats.length === 0 ? (
            <div className="muted-block">No boats meet the minimum trip threshold for these filters.</div>
          ) : (
            <Fragment>
              <div className="chart-legend" style={{marginBottom: 8}}>
                <span className="ll"><span className="sw" style={{background:'var(--ss-darkseagreen-500)'}}></span>Consistent</span>
                <span className="ll"><span className="sw" style={{background:'var(--ss-orange-500)'}}></span>Spike</span>
              </div>
              <div style={{position:'relative'}}>
                {topBoats.map((b, i) => {
                  const wpct = (b.avgTPAPerDay / maxTPAPerDay) * 100;
                  return (
                    <div key={b.boat} className={`bar-row ${b.label === 'Spike' ? 'spike' : 'consistent'}`}
                         style={{cursor:'pointer'}}
                         onClick={() => navigate('boat', { boat: b.boat })}>
                      <div className="label">
                        <span className="rank" style={{color: i < 3 ? 'var(--ss-orange-500)' : null, fontWeight: i < 3 ? 700 : 500}}>{i + 1}</span>
                        <div style={{minWidth:0, flex:1}}>
                          <div className="name">{b.boat}</div>
                          <div className="lan">{b.landing.replace(' Sportfishing','').replace(' Landing','')} · {b.tripCount} trips</div>
                        </div>
                      </div>
                      <div className="track" style={{position:'relative'}}>
                        <div className="fill" style={{width:`${wpct}%`}}></div>
                        {b.label && (
                          <span className={`tag ${b.label === 'Consistent' ? 'consistent' : 'spike'}`}
                                style={{position:'absolute', right:6, top:-2, fontSize:9}}>
                            {b.label}
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

      {/* Monthly trend + trip length */}
      <div className="two-col-grid" style={{display:'grid', gridTemplateColumns:'2fr 1fr', gap:12, marginBottom:12}}>
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

        <Panel title="By Trip Length" meta={`${speciesLabel.toLowerCase()}/angler`}>
          {lengthData.length === 0 ? <div className="muted-block">No data.</div> : (
            <div>
              {lengthData.sort((a,b) => b.tpa - a.tpa).map((r) => {
                const max = Math.max(...lengthData.map(x => x.tpa));
                return (
                  <div key={r.tripLength} style={{display:'grid', gridTemplateColumns:'88px 1fr 60px', gap:8, alignItems:'center', padding:'5px 0'}}>
                    <span style={{font:'500 11px/14px var(--ss-font-sans)', color:'var(--ss-slate)'}}>{r.tripLength}</span>
                    <div className="track" style={{height:14}}>
                      <div className="fill" style={{width:`${(r.tpa/max)*100}%`, background: r.tripLength === 'Long Range' ? 'var(--ss-orange-500)' : 'var(--ss-darkseagreen-500)'}}></div>
                    </div>
                    <span className="num" style={{font:'500 11px/14px var(--ss-font-sans)', textAlign:'right', fontVariantNumeric:'tabular-nums'}}>{fmt.tpa(r.tpa)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      </div>

      {/* By Landing */}
      <Panel title="By Landing"
             meta="Approved San Diego landings"
             >
        {landings.map((l) => {
          const max = Math.max(...landings.map(x => x.tpa));
          return (
            <div key={l.landing} style={{padding:'8px 0', borderBottom:'1px solid var(--ss-border-2)', cursor:'pointer'}}
                 onClick={() => navigate('landing', { landing: l.landing })}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:4}}>
                <span style={{font:'500 13px/16px var(--ss-font-sans)'}}>{l.landing}</span>
                <span style={{font:'700 13px/16px var(--ss-font-sans)', fontVariantNumeric:'tabular-nums'}}>{fmt.tpa(l.tpa)}</span>
              </div>
              <div style={{display:'flex', gap:8, alignItems:'center'}}>
                <div className="track" style={{height:8, flex:1}}>
                  <div className="fill" style={{width:`${(l.tpa/max)*100}%`}}></div>
                </div>
                <span style={{font:'400 10px/12px var(--ss-font-sans)', color:'var(--ss-gray-3)', minWidth:90, textAlign:'right'}}>
                  {l.boatCount} boats · {fmt.n(l.trips)} trips
                </span>
              </div>
            </div>
          );
        })}
      </Panel>

      <StreakTracker navigate={navigate} regions={regions}/>

      </Fragment>}

      {/* Head-to-Head sub-tab */}
      {subtab === 'headtohead' && <HeadToHead filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}

      {/* Seasonality sub-tab */}
      {subtab === 'seasonality' && <SeasonalityView filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}

      {/* Moon Phase sub-tab */}
      {subtab === 'moon' && <MoonView filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}
    </Fragment>
  );
}

Object.assign(window, { AnalyticsView });
