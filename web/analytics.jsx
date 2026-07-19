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
    const cutoff = (() => { const d = new Date(); d.setMonth(d.getMonth() - 4); return window.TT_DATES.getPacificDate(d); })();
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
           meta="Last 10 trips per boat — above (✅) or below (❌) the median of boats fishing the same day & trip length (all-time median when <3 boats out) · min 10 trips"
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

// ── Boat Finder ────────────────────────────────────────────────────────────────

function FinpanelPill({ label, value, options, onChange }) {
  return (
    <label className="finder-param">
      <span className="finder-param-label">{label}</span>
      <select className="finder-param-select" value={value}
              onChange={function(e) { onChange(e.target.value); }}>
        {options.map(function(o) { return <option key={o.value} value={o.value}>{o.label}</option>; })}
      </select>
    </label>
  );
}

function BoatFinderCard({ rank, row, winRates, streakMap, navigate }) {
  const { useState, useEffect } = React;
  const [saved, setSaved] = useState(function() {
    return !!(window.getSavedBoats && window.getSavedBoats().has(row.boat));
  });
  useEffect(function() {
    function sync() { setSaved(!!(window.getSavedBoats && window.getSavedBoats().has(row.boat))); }
    window.addEventListener('tt-saved-boats-changed', sync);
    return function() { window.removeEventListener('tt-saved-boats-changed', sync); };
  }, [row.boat]);

  var streak = streakMap[row.boat];
  var wrWins = 0, wrTotal = 0;
  Object.entries(winRates).forEach(function(kv) {
    if (kv[0].split('|')[0] === row.boat && kv[1].winRate != null) {
      wrWins  += kv[1].wins;
      wrTotal += kv[1].matchupCount;
    }
  });
  var wrPct = wrTotal > 0 ? Math.round(100 * wrWins / wrTotal) : null;
  var cfg = streak ? _streakCfg(streak.goodCount) : null;

  return (
    <div className="finder-card">
      <div className={'finder-rank' + (rank <= 3 ? ' top3' : '')}>{rank}</div>
      <div className="finder-card-main">
        <div className="finder-card-head">
          <button className="finder-boat-name"
                  onClick={function() { navigate('boat', { boat: row.boat }); }}>
            {row.boat}
          </button>
          <span className="finder-landing">
            {row.landing.replace(' Sportfishing','').replace(' Landing','')}
          </span>
        </div>
        <div className="finder-stats">
          <span className="finder-stat-primary">{fmt.tpa(row.avgTPA)} <span className="finder-stat-unit">tpa</span></span>
          {wrPct != null && <span className="finder-stat">{wrPct}% win rate</span>}
          <span className="finder-stat-dim">{row.tripCount} matching trip{row.tripCount !== 1 ? 's' : ''}</span>
        </div>
        {streak && (
          <div className="finder-streak">
            {streak.last10.map(function(d, i) {
              return <span key={i} className="streak-dot"
                           style={{background: d.good ? '#10B981' : '#EF4444'}}/>;
            })}
            {cfg && <span className="finder-streak-badge" style={{color: cfg.color}}>{cfg.emoji} {cfg.label}</span>}
          </div>
        )}
      </div>
      <div className="finder-card-actions">
        <button className={'finder-save-btn' + (saved ? ' saved' : '')}
                title={saved ? 'Remove from saved' : 'Save boat'}
                onClick={function() { window.toggleSavedBoat && window.toggleSavedBoat(row.boat); }}>
          {saved ? '✓' : '⭐'}
        </button>
        <a className="finder-view-btn"
           href={`/sd/boat/${encodeURIComponent(row.boat)}`}
           onClick={function(e) { e.preventDefault(); navigate('boat', { boat: row.boat }); }}>
          View →
        </a>
      </div>
    </div>
  );
}

function BoatFinder({ navigate, regions }) {
  const { useState, useMemo } = React;
  const MIN_TRIPS = 3;

  var curMonth = String(window.TT_DATES.getPacificMonth());
  const [selSpecies, setSelSpecies] = useState('all');
  const [selLength,  setSelLength]  = useState('all');
  const [selMonth,   setSelMonth]   = useState(curMonth);

  var SPECIES_OPTS = [
    { value: 'all',        label: 'Any trophy fish' },
    { value: 'Bluefin',    label: 'Bluefin Tuna' },
    { value: 'Yellowfin',  label: 'Yellowfin Tuna' },
    { value: 'Yellowtail', label: 'Yellowtail' },
    { value: 'Dorado',     label: 'Dorado' },
  ];
  var LENGTH_OPTS = [{ value: 'all', label: 'Any length' }].concat(
    (window.SD.TRIP_LENGTHS || []).map(function(l) { return { value: l, label: l }; })
  );
  var MONTH_OPTS = [{ value: 'all', label: 'Any month' }].concat(
    MONTH_NAMES.map(function(m, i) { return { value: String(i+1), label: m }; })
  );

  var _ALL = { year:'all', species:'all', landing:'all', month:'all', minTrips:0, includeZero:true, boat:'all' };

  var matchingTrips = useMemo(function() {
    return SDA.filterTrips(Object.assign({}, _ALL, {
      species: selSpecies, tripLength: selLength, month: selMonth,
    }), regions);
  }, [selSpecies, selLength, selMonth, regions]);

  var ranked = useMemo(function() {
    return SDA.boatLeaderboard(matchingTrips, selSpecies, MIN_TRIPS).rows;
  }, [matchingTrips, selSpecies]);

  var eligible = ranked.filter(function(r) { return r.tripCount >= MIN_TRIPS; });

  var streakMap = useMemo(function() {
    var all = SDA.filterTrips(_ALL, regions);
    var list = SDA.boatStreaks ? SDA.boatStreaks(all) : [];
    var map = {};
    list.forEach(function(b) { map[b.boat] = b; });
    return map;
  }, [regions]);

  var winRates = useMemo(function() {
    try { return SDA.boatWinRates ? SDA.boatWinRates() : {}; } catch(e) { return {}; }
  }, []);

  var matchLabel = [
    selSpecies !== 'all' ? selSpecies : null,
    selLength  !== 'all' ? selLength  : null,
    selMonth   !== 'all' ? MONTH_NAMES[+selMonth - 1] : null,
  ].filter(Boolean).join(' · ') || 'all trips';

  return (
    <React.Fragment>
      <Crumbs items={[{ label: 'Analytics' }, { label: 'Find My Boat' }]}/>
      <div className="pagehead">
        <div>
          <h1>Find My Boat</h1>
          <div className="sub">Which boats historically perform best for your target trip?</div>
        </div>
      </div>

      <div className="finder-panel">
        <div className="finder-panel-title">I'm planning a trip to catch…</div>
        <div className="finder-params">
          <FinpanelPill label="Target species" value={selSpecies}
                        options={SPECIES_OPTS} onChange={setSelSpecies}/>
          <FinpanelPill label="Trip length" value={selLength}
                        options={LENGTH_OPTS} onChange={setSelLength}/>
          <FinpanelPill label="Month" value={selMonth}
                        options={MONTH_OPTS} onChange={setSelMonth}/>
        </div>
      </div>

      <div className="finder-summary">
        <strong>{eligible.length}</strong> boat{eligible.length !== 1 ? 's' : ''} with {MIN_TRIPS}+ trips matching <em>{matchLabel}</em>
        {matchingTrips.length > 0 && (
          <span className="finder-summary-dim"> · {matchingTrips.length} qualifying trips in database</span>
        )}
      </div>

      {eligible.length === 0 ? (
        <div className="muted-block" style={{margin:'24px 16px'}}>
          No boats have {MIN_TRIPS}+ trips matching these filters. Try widening your criteria (e.g., "Any month").
        </div>
      ) : (
        <div className="finder-results">
          {eligible.map(function(row, i) {
            return (
              <BoatFinderCard key={row.boat} rank={i+1} row={row}
                winRates={winRates} streakMap={streakMap} navigate={navigate}/>
            );
          })}
        </div>
      )}
    </React.Fragment>
  );
}

// ── HalfDayView ───────────────────────────────────────────────────────────────
// Dedicated Analytics subtab for half-day boat performance. Uses window.SD.HALF_DAY_TRIPS
// (populated separately from the trophy-tuna TRIPS array) and the SDA.halfDay*
// functions in analytics.js. Deliberately self-contained: renders its own filter
// bar, KPIs, and panels rather than reusing AnalyticsFilterBar — half-day filters
// (slot, extended species multi-select, metric) are different enough that reusing
// would push half-day-only logic into every other subtab.
function HalfDayView({ navigate, regions, settings }) {
  const { useMemo, useState } = React;

  const SLOT_OPTS = [
    { value: 'all',      label: 'All slots' },
    { value: 'AM',       label: 'AM' },
    { value: 'PM',       label: 'PM' },
    { value: 'Twilight', label: 'Twilight' },
    { value: 'Full',     label: 'Full half-day' },
  ];
  const METRIC_OPTS = [
    { value: 'fpa',     label: 'Fish / Angler',        desc: 'All landed species' },
    { value: 'tpad',    label: 'Tuna / Angler / Day',  desc: 'Trophy species only' },
    { value: 'species', label: 'Selected species',     desc: 'Sum of species below / angler' },
  ];
  // Species list mirrors SDA.HD_ALL_SPECIES, dropping tuna species that are ~0
  // on half-day trips (Bluefin/Yellowfin/Skipjack/Bigeye/Albacore/Dorado).
  const SPECIES_OPTS = [
    'Yellowtail', 'White Sea Bass', 'Halibut', 'Lingcod',
    'Rockfish', 'Sheephead', 'Calico Bass', 'Sand Bass',
    'Whitefish', 'Bonito', 'Barracuda',
  ];

  const YEAR_OPTS = useMemo(() => {
    const yrs = new Set((window.SD.HALF_DAY_TRIPS || []).map(t => t.year));
    return ['all', ...[...yrs].sort((a, b) => b - a)];
  }, []);
  const MONTH_OPTS = ['all', ...Array.from({ length: 12 }, (_, i) => String(i + 1))];

  // Ensure preprocess ran (mirrors the AnalyticsView guard).
  if (!window.SD_HD_TRIPS) SDA.preprocessHalfDayTrips(settings);

  const [year,     setYear]     = useState('all');
  const [month,    setMonth]    = useState('all');
  const [landing,  setLanding]  = useState('all');
  const [slot,     setSlot]     = useState('all');
  const [metric,   setMetric]   = useState('fpa');
  const [selSpecies, setSelSpecies] = useState([]);    // multi-select, empty = all
  const [minTrips, setMinTrips] = useState(5);

  const filters = { year, month, landing, boat: 'all', slot,
                    species: selSpecies.length ? selSpecies : 'all' };

  const filtered = useMemo(() => SDA.filterHalfDayTrips(filters, regions),
                            [year, month, landing, slot, selSpecies, regions, settings]);

  const leaderboard = useMemo(
    () => SDA.halfDayLeaderboard(filtered, { metric, species: selSpecies.length ? selSpecies : 'all', minTrips }),
    [filtered, metric, selSpecies, minTrips]
  );

  const winRates = useMemo(
    () => SDA.halfDayWinRates(filtered, { metric, species: selSpecies.length ? selSpecies : 'all', minMatchups: 5 }),
    [filtered, metric, selSpecies]
  );

  const amVsPm = useMemo(() => SDA.halfDayAMvsPM(filtered, { minTripsPerSlot: 3 }), [filtered]);

  const rareCatch = useMemo(() => SDA.halfDayRareCatchRate(filtered, { minTrips: 5 }), [filtered]);

  // Streaks operate on the full half-day universe (region-filtered) so "last 10
  // trips" is always chronological, not gated by year/month.
  const streaks = useMemo(() => {
    const universe = SDA.filterHalfDayTrips(
      { year: 'all', month: 'all', landing: 'all', boat: 'all', slot: 'all', species: 'all' },
      regions
    );
    return SDA.halfDayStreaks(universe, { minTrips: 10 });
  }, [regions, settings]);

  // KPI values
  const totalTrips   = filtered.length;
  const totalAnglers = filtered.reduce((s, t) => s + (t.anglers || 0), 0);
  const totalFish    = filtered.reduce((s, t) => s + (t.totalFish || 0), 0);
  const totalTrophy  = filtered.reduce((s, t) => s + (t.totalTuna || 0), 0);
  const fleetFpa     = totalAnglers ? totalFish   / totalAnglers : 0;
  const fleetTpad    = totalAnglers ? totalTrophy / totalAnglers : 0;
  const topBoat      = leaderboard.rows[0];

  const metricLabel = METRIC_OPTS.find(o => o.value === metric)?.label || 'Metric';

  function toggleSpecies(sp) {
    setSelSpecies(prev => prev.includes(sp) ? prev.filter(x => x !== sp) : [...prev, sp]);
  }

  // Bar-chart max for the leaderboard
  const maxSort = leaderboard.rows.length ? leaderboard.rows[0].sortValue : 1;

  return (
    <React.Fragment>
      <Crumbs items={[{ label: 'Analytics' }, { label: 'Half Day' }]}/>
      <div className="pagehead">
        <div>
          <h1>Half Day Reports <span className="region-subtitle-badge">{(regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego'}</span></h1>
          <div className="sub analytics-sub">
            {fmt.n(totalTrips)} trips · {fmt.n(totalAnglers)} anglers · {fmt.n(totalFish)} fish landed
          </div>
        </div>
      </div>

      {/* Custom filter panel — half-day-specific (slot, extended species) */}
      <div className="finder-panel">
        <div className="finder-panel-title">Filter half-day trips</div>
        <div className="finder-params">
          <label className="finder-param">
            <span className="finder-param-label">Year</span>
            <select className="finder-param-select" value={year} onChange={e => setYear(e.target.value)}>
              {YEAR_OPTS.map(y => <option key={y} value={y}>{y === 'all' ? 'All years' : y}</option>)}
            </select>
          </label>
          <label className="finder-param">
            <span className="finder-param-label">Month</span>
            <select className="finder-param-select" value={month} onChange={e => setMonth(e.target.value)}>
              {MONTH_OPTS.map(m => <option key={m} value={m}>{m === 'all' ? 'Any month' : MONTH_NAMES[+m - 1]}</option>)}
            </select>
          </label>
          <label className="finder-param">
            <span className="finder-param-label">Landing</span>
            <select className="finder-param-select" value={landing} onChange={e => setLanding(e.target.value)}>
              <option value="all">All landings</option>
              {(window.SD.LANDINGS || []).map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
          <label className="finder-param">
            <span className="finder-param-label">Slot</span>
            <select className="finder-param-select" value={slot} onChange={e => setSlot(e.target.value)}>
              {SLOT_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="finder-param">
            <span className="finder-param-label">Rank by</span>
            <select className="finder-param-select" value={metric} onChange={e => setMetric(e.target.value)}
                    title={METRIC_OPTS.find(o => o.value === metric)?.desc}>
              {METRIC_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="finder-param">
            <span className="finder-param-label">Min trips</span>
            <select className="finder-param-select" value={minTrips} onChange={e => setMinTrips(+e.target.value)}>
              {[1, 3, 5, 10, 20].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        <div style={{marginTop: 10}}>
          <div className="finder-param-label" style={{marginBottom: 6}}>
            Species (multi-select — filters trips + drives the "Selected species" metric)
          </div>
          <div className="row" style={{gap: 6, flexWrap: 'wrap'}}>
            {SPECIES_OPTS.map(sp => (
              <span key={sp}
                    className={`filter-pill ${selSpecies.includes(sp) ? 'on' : ''}`}
                    style={{cursor: 'pointer'}}
                    onClick={() => toggleSpecies(sp)}>
                {sp}
              </span>
            ))}
            {selSpecies.length > 0 && (
              <span className="filter-pill" style={{cursor: 'pointer', opacity: 0.6}}
                    onClick={() => setSelSpecies([])}>Clear</span>
            )}
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="kpis">
        <KPI label="Half-Day Trips" value={fmt.n(totalTrips)}
             ctx={`${fmt.n(totalAnglers)} anglers · ${fmt.n(totalFish)} fish landed`}/>
        <KPI label="Fleet Fish / Angler" value={fleetFpa.toFixed(2)}
             ctx="All landed species"/>
        <KPI label="Fleet Tuna / Angler / Day" value={fleetTpad.toFixed(2)}
             ctx="Trophy species only (mostly yellowtail on half-days)"/>
        <KPI label={`Top Boat by ${metricLabel}`}
             value={topBoat?.boat || '—'}
             ctx={topBoat ? `${topBoat.sortValue.toFixed(2)} · ${topBoat.landing}` : ''}/>
      </div>

      {/* Universal AM/PM insight banner — shown when data supports it */}
      {amVsPm.length >= 3 && (() => {
        const pmBias = amVsPm.filter(r => r.preferredSlot === 'PM').length;
        const amBias = amVsPm.filter(r => r.preferredSlot === 'AM').length;
        const majority = pmBias > amBias ? 'PM' : (amBias > pmBias ? 'AM' : null);
        if (!majority) return null;
        const majCount = majority === 'PM' ? pmBias : amBias;
        return (
          <div className="custom-species-banner"
               title="Boats that ran ≥3 trips in each slot with matching filters">
            <i className="fa-solid fa-sun"/> {majCount}/{amVsPm.length} boats fish better in the {majority}
            {' '}under current filters
          </div>
        );
      })()}

      {/* Main leaderboard */}
      <div style={{marginBottom: 12}}>
        <Panel title={`Top Half-Day Boats — ${metricLabel}`}
               meta={`Min ${minTrips} trips${selSpecies.length && metric === 'species' ? ` · counting ${selSpecies.join(', ')}` : ''}`}>
          {leaderboard.rows.length === 0 ? (
            <div className="muted-block">No boats meet the {minTrips}-trip threshold for these filters.</div>
          ) : (
            <div>
              {leaderboard.rows.slice(0, 15).map((r, i) => {
                const wpct = maxSort > 0 ? (r.sortValue / maxSort) * 100 : 0;
                return (
                  <div key={r.boat} className="bar-row consistent"
                       style={{cursor: 'pointer'}}
                       onClick={() => navigate('boat', { boat: r.boat })}>
                    <div className="label">
                      <span className="rank"
                            style={{color: i < 3 ? 'var(--ss-orange-500)' : null,
                                    fontWeight: i < 3 ? 700 : 500}}>{i + 1}</span>
                      <div style={{minWidth: 0, flex: 1}}>
                        <div className="name">{r.boat}</div>
                        <div className="lan">
                          {r.landing.replace(' Sportfishing', '').replace(' Landing', '')}
                          {' · '}{r.tripCount} trips · {r.avgAnglers.toFixed(0)} avg anglers
                        </div>
                      </div>
                    </div>
                    <div className="track" style={{position: 'relative'}}>
                      <div className="fill" style={{width: `${wpct}%`}}></div>
                    </div>
                    <div className="num">{r.sortValue.toFixed(2)}</div>
                  </div>
                );
              })}
              {/* Column glossary row */}
              <div style={{marginTop: 12, padding: '10px 4px 0', borderTop: '1px solid var(--ss-border-2)',
                          fontSize: 11, color: 'var(--ss-gray-3)'}}>
                Also computed per boat: fish/angler ({metric === 'fpa' ? '↑ ranking metric' : 'shown for reference'}),
                tuna/angler/day, rare-catch rate/100, AM vs PM fish/angler.
              </div>
            </div>
          )}
        </Panel>
      </div>

      {/* Two-column: Win Rate | AM vs PM */}
      <div className="two-col-grid"
           style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12}}>
        <Panel title="Head-to-Head Win Rate"
               meta="% of same-day, same-slot matchups this boat wins · min 5 matchups">
          {winRates.filter(r => r.winRate != null).length === 0 ? (
            <div className="muted-block">Not enough overlapping matchups under these filters.</div>
          ) : (
            <div>
              {winRates.filter(r => r.winRate != null).slice(0, 12).map((r, i) => (
                <div key={r.boat + r.landing}
                     style={{display: 'grid', gridTemplateColumns: '24px 1fr 60px 50px',
                             gap: 8, alignItems: 'center', padding: '6px 0',
                             borderBottom: '1px solid var(--ss-border-2)', cursor: 'pointer'}}
                     onClick={() => navigate('boat', { boat: r.boat })}>
                  <span style={{fontWeight: i < 3 ? 700 : 500,
                                color: i < 3 ? 'var(--ss-orange-500)' : null}}>{i + 1}</span>
                  <div style={{minWidth: 0}}>
                    <div style={{font: '500 12px/15px var(--ss-font-sans)'}}>{r.boat}</div>
                    <div style={{font: '400 10px/13px var(--ss-font-sans)', color: 'var(--ss-gray-3)'}}>
                      {r.trips} trips · {r.matchups} matchups
                    </div>
                  </div>
                  <div className="track" style={{height: 8}}>
                    <div className="fill" style={{width: `${r.winRate * 100}%`}}></div>
                  </div>
                  <span style={{font: '600 12px/15px var(--ss-font-sans)', textAlign: 'right',
                                fontVariantNumeric: 'tabular-nums'}}>
                    {Math.round(r.winRate * 100)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="AM vs PM per Boat"
               meta="Boats that ran ≥3 trips in each slot · positive delta = AM better">
          {amVsPm.length === 0 ? (
            <div className="muted-block">No boats have enough trips in both slots yet.</div>
          ) : (
            <div>
              {amVsPm.slice(0, 12).map(r => {
                const barW = Math.min(50, Math.abs(r.delta) * 15);
                const rightBias = r.delta > 0;   // AM > PM → bar leans right of center
                return (
                  <div key={r.boat + r.landing}
                       style={{padding: '8px 0', borderBottom: '1px solid var(--ss-border-2)'}}>
                    <div style={{display: 'flex', justifyContent: 'space-between',
                                 alignItems: 'baseline', marginBottom: 4}}>
                      <span style={{font: '500 12px/15px var(--ss-font-sans)', cursor: 'pointer'}}
                            onClick={() => navigate('boat', { boat: r.boat })}>{r.boat}</span>
                      <span style={{font: '600 11px/14px var(--ss-font-sans)',
                                    color: r.preferredSlot === 'AM' ? 'var(--ss-orange-500)' : 'var(--ss-darkseagreen-500)'}}>
                        Prefers {r.preferredSlot} ({r.delta > 0 ? '+' : ''}{r.delta.toFixed(2)})
                      </span>
                    </div>
                    <div style={{display: 'grid', gridTemplateColumns: '1fr 6px 1fr', gap: 0,
                                 fontSize: 10, color: 'var(--ss-gray-3)', alignItems: 'center'}}>
                      <div style={{textAlign: 'right', paddingRight: 6}}>
                        AM {r.amFpa.toFixed(2)} <span style={{opacity: 0.6}}>({r.amTrips}t)</span>
                      </div>
                      <div style={{width: 2, height: 12, background: 'var(--ss-border-2)'}}></div>
                      <div style={{paddingLeft: 6}}>
                        PM {r.pmFpa.toFixed(2)} <span style={{opacity: 0.6}}>({r.pmTrips}t)</span>
                      </div>
                    </div>
                    <div style={{position: 'relative', height: 6, background: 'var(--ss-border-2)',
                                 borderRadius: 3, marginTop: 4}}>
                      <div style={{position: 'absolute', left: '50%', top: 0, height: '100%',
                                   width: `${barW}%`, background: rightBias ? 'var(--ss-orange-500)' : 'var(--ss-darkseagreen-500)',
                                   transform: rightBias ? 'none' : 'translateX(-100%)',
                                   borderRadius: 3}}></div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      </div>

      {/* Rare-catch panel */}
      <div style={{marginBottom: 12}}>
        <Panel title="Rare-Catch Rate"
               meta="Yellowtail + White Sea Bass + Halibut + Lingcod per 100 anglers · min 5 trips">
          {rareCatch.length === 0 ? (
            <div className="muted-block">No boats meet the threshold under these filters.</div>
          ) : (
            <div>
              {rareCatch.slice(0, 10).map((r, i) => (
                <div key={r.boat + r.landing}
                     style={{padding: '8px 0', borderBottom: '1px solid var(--ss-border-2)', cursor: 'pointer'}}
                     onClick={() => navigate('boat', { boat: r.boat })}>
                  <div style={{display: 'flex', justifyContent: 'space-between',
                               alignItems: 'baseline', marginBottom: 4}}>
                    <span style={{font: '500 13px/16px var(--ss-font-sans)'}}>
                      <span style={{marginRight: 8, color: i < 3 ? 'var(--ss-orange-500)' : 'var(--ss-slate)',
                                    fontWeight: 700}}>{i + 1}</span>
                      {r.boat}
                      <span style={{marginLeft: 8, color: 'var(--ss-gray-3)', fontWeight: 400, fontSize: 11}}>
                        {r.landing.replace(' Sportfishing', '').replace(' Landing', '')}
                      </span>
                    </span>
                    <span style={{font: '700 13px/16px var(--ss-font-sans)',
                                  fontVariantNumeric: 'tabular-nums'}}>
                      {r.ratePer100.toFixed(1)} <span style={{fontSize: 10, color: 'var(--ss-gray-3)', fontWeight: 400}}>/100 anglers</span>
                    </span>
                  </div>
                  <div style={{font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-gray-3)'}}>
                    YT {r.counts.Yellowtail} · WSB {r.counts['White Sea Bass']} · Halibut {r.counts.Halibut} · Lingcod {r.counts.Lingcod}
                    <span style={{marginLeft: 12, opacity: 0.7}}>({r.trips} trips · {r.anglers} anglers)</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* Streak tracker (universe: all half-day trips in region, ignores filters
          so "last 10 trips" is always chronological) */}
      <Panel title="Recent Form — Half Day"
             meta="Last 10 half-day trips per boat vs same-day/same-slot fleet median · min 10 total trips">
        {streaks.length === 0 ? (
          <div className="muted-block">No boats with 10+ half-day trips in this region.</div>
        ) : (
          <div className="streak-list">
            {streaks.slice(0, 12).map(s => (
              <div key={s.boat} className="streak-row" style={{cursor: 'pointer'}}
                   onClick={() => navigate('boat', { boat: s.boat })}>
                <div className="streak-name" title={`${s.landing} · ${s.totalTrips} half-day trips total`}>
                  {s.boat}
                </div>
                <div className="streak-dots">
                  {s.last10.map((d, i) => {
                    const mo = d.date ? new Date(d.date + 'T12:00:00')
                      .toLocaleString('en-US', { month: 'short', day: 'numeric' }) : d.date;
                    return (
                      <span key={i}
                            title={`${mo} · ${d.slot} · ${d.fpa.toFixed(2)} fish/angler`}
                            className="streak-dot"
                            style={{background: d.good ? '#10B981' : '#EF4444'}}/>
                    );
                  })}
                </div>
                <div className="streak-score">{s.goodCount}/10</div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </React.Fragment>
  );
}

// ── AnalyticsView ─────────────────────────────────────────────────────────────

function AnalyticsView({ filters: propFilters, setFilters: setPropFilters, navigate, tweaks, settings, regions, subtab = 'overview' }) {
  const { useMemo, useState } = React;
  const [filters, setFilters] = useAnalyticsFilters(propFilters, setPropFilters);

  const SUBTABS = [
    { id: 'overview',    label: 'Overview' },
    { id: 'finder',      label: 'Find My Boat' },
    { id: 'headtohead',  label: 'Head-to-Head' },
    { id: 'seasonality', label: 'Seasonality' },
    { id: 'moon',        label: 'Moon Phase' },
    { id: 'halfday',     label: 'Half Day' },
  ];

  const SUBTAB_FIELDS = {
    overview:    ['year', 'month', 'landing', 'boat', 'tripLength', 'species', 'minTrips'],
    finder:      [], // finder manages its own filters inline
    headtohead:  ['year', 'month', 'landing', 'tripLength', 'species', 'minTrips'],
    seasonality: ['year', 'landing', 'tripLength'],
    moon:        ['year', 'landing', 'tripLength', 'species'],
    halfday:     [], // half-day view manages its own inline filter panel
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
    <React.Fragment>
      {/* Sub-tab bar — always visible */}
      <div className="tabbar analytics-subtabbar">
        {SUBTABS.map(t => (
          <a key={t.id} className={subtab === t.id ? 'sel' : ''}
             onClick={() => navigate('analytics', { subtab: t.id })}>{t.label}</a>
        ))}
      </div>

      {/* Shared filter bar — one instance for all subtabs EXCEPT half-day
          (which uses its own extended filter panel: slot, extended species
          multi-select, metric selector). Skipping avoids a confusing double
          filter bar on that subtab. */}
      {subtab !== 'halfday' && (
        <div style={{padding: '10px 16px 0'}}>
          <AnalyticsFilterBar
            filters={filters}
            setFilters={setFilters}
            fields={SUBTAB_FIELDS[subtab] || SUBTAB_FIELDS.overview}
            regions={regions}/>
        </div>
      )}

      {/* Overview sub-tab */}
      {subtab === 'overview' && <React.Fragment>
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
            <React.Fragment>
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
            </React.Fragment>
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

      </React.Fragment>}

      {/* Find My Boat sub-tab */}
      {subtab === 'finder' && <BoatFinder navigate={navigate} regions={regions}/>}

      {/* Head-to-Head sub-tab */}
      {subtab === 'headtohead' && <HeadToHead filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}

      {/* Seasonality sub-tab */}
      {subtab === 'seasonality' && <SeasonalityView filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}

      {/* Moon Phase sub-tab */}
      {subtab === 'moon' && <MoonView filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}

      {/* Half Day sub-tab */}
      {subtab === 'halfday' && <HalfDayView navigate={navigate} regions={regions} settings={settings}/>}
    </React.Fragment>
  );
}

Object.assign(window, { AnalyticsView, HalfDayView });
