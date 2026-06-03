// Analytics view — full filter controls, KPIs, charts, leaderboard

// ── URL ↔ analytics-filter serialization ─────────────────────────────────────

function _aFiltersToSearch(f) {
  const df = window.DEFAULT_FILTERS;
  const p  = new URLSearchParams();
  const s  = (v) => Array.isArray(v) ? v.join(',') : String(v);
  if (f.year       !== df.year)       p.set('year',    s(f.year));
  if (f.month      !== df.month)      p.set('month',   s(f.month));
  if (f.landing    !== df.landing)    p.set('landing', s(f.landing));
  if (f.boat       !== df.boat)       p.set('boat',    s(f.boat));
  if (f.tripLength !== df.tripLength) p.set('tripLen', s(f.tripLength));
  if (f.species    !== df.species)    p.set('species', s(f.species));
  if (f.minTrips   !== df.minTrips)   p.set('min',     String(f.minTrips));
  return p.toString();
}

function _aSearchToFilters(search) {
  const df = window.DEFAULT_FILTERS;
  const p  = new URLSearchParams(search);
  const r  = (k) => { const v = p.get(k); return v == null ? null : v.includes(',') ? v.split(',') : v; };
  return {
    ...df,
    year:       r('year')    ?? df.year,
    month:      r('month')   ?? df.month,
    landing:    r('landing') ?? df.landing,
    boat:       r('boat')    ?? df.boat,
    tripLength: r('tripLen') ?? df.tripLength,
    species:    r('species') ?? df.species,
    minTrips:   p.has('min') ? +p.get('min') : df.minTrips,
  };
}

// Hook: filter state owned by the analytics section, synced to the URL query
// string so filters survive subtab switches and page refresh. Propagates
// changes up via setPropFilters so the TweaksPanel quick-filters stay in sync.
function useAnalyticsFilters(propFilters, setPropFilters) {
  const { useState, useEffect, useRef, useCallback } = React;

  const [filters, setFiltersRaw] = useState(() =>
    window.location.search
      ? _aSearchToFilters(window.location.search)
      : { ...propFilters }
  );

  const prevPropRef = useRef(propFilters);

  // Accept field-level changes driven externally (e.g. TweaksPanel year/species).
  // Only applies the delta so URL-driven fields aren't overwritten wholesale.
  useEffect(() => {
    const prev = prevPropRef.current;
    if (propFilters === prev) return;
    prevPropRef.current = propFilters;
    const delta = {};
    Object.keys(propFilters).forEach(k => { if (propFilters[k] !== prev[k]) delta[k] = propFilters[k]; });
    if (Object.keys(delta).length) setFiltersRaw(f => ({ ...f, ...delta }));
  }, [propFilters]);

  const setFilters = useCallback((next) => {
    setFiltersRaw(prev => {
      const f = typeof next === 'function' ? next(prev) : next;
      const qs = _aFiltersToSearch(f);
      history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
      prevPropRef.current = f; // prevent the effect above from re-echoing this update
      setPropFilters(f);
      return f;
    });
  }, [setPropFilters]);

  return [filters, setFilters];
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

function AnalyticsView({ filters: propFilters, setFilters: setPropFilters, navigate, tweaks, settings, regions, subtab = 'overview' }) {
  const { useMemo, useState } = React;
  const [filters, setFilters] = useAnalyticsFilters(propFilters, setPropFilters);

  const SUBTABS = [
    { id: 'overview',    label: 'Overview' },
    { id: 'headtohead',  label: 'Head-to-Head' },
    { id: 'seasonality', label: 'Seasonality' },
    { id: 'moon',        label: 'Moon Phase' },
  ];

  const SUBTAB_FIELDS = {
    overview:    ['year', 'month', 'landing', 'boat', 'tripLength', 'species', 'minTrips'],
    headtohead:  ['year', 'month', 'landing', 'tripLength', 'species', 'minTrips'],
    seasonality: ['year', 'landing', 'tripLength'],
    moon:        ['year', 'landing', 'tripLength', 'species'],
  };

  // preprocessTrips runs in a useEffect in app.jsx (post-mount), so SD_PROC_TRIPS
  // is null on the first render. Guard synchronously so metrics are correct immediately.
  if (!window.SD_PROC_TRIPS) SDA.preprocessTrips(settings);

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

      {/* Shared filter bar — one instance for all subtabs */}
      <div style={{padding: '10px 16px 0'}}>
        <AnalyticsFilterBar
          filters={filters}
          setFilters={setFilters}
          fields={SUBTAB_FIELDS[subtab] || SUBTAB_FIELDS.overview}
          regions={regions}/>
      </div>

      {/* Overview sub-tab */}
      {subtab === 'overview' && <Fragment>
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
