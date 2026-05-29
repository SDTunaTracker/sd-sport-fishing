// Today view — Today's Report (with date picker) + Current Year Leaderboard
// ForecastWidget is intentionally above TodayCatch to surface conditions before catch data.
const { useMemo, useState: useS } = React;

function _fcScoreColor(s) {
  if (s == null) return 'var(--tb-gray-3)';
  if (s >= 8)   return 'var(--tb-lime)';
  if (s >= 6)   return 'var(--tb-accent)';
  if (s >= 4)   return 'var(--tb-gold)';
  return 'var(--tb-coral)';
}

function useFreshness(regions) {
  const status = window.SD?.SCRAPE_STATUS;
  if (!status) return null;
  const allLandings = status.landings || {};
  const keys = Object.keys(allLandings);
  if (!keys.length) return null;

  // Filter to landings relevant to the current region
  const regionLandings = (window.getLandingsForRegion && window.getEffectiveRegion)
    ? window.getLandingsForRegion(window.getEffectiveRegion(regions || ['san_diego']))
    : null;
  const relevant = regionLandings ? keys.filter(k => regionLandings.includes(k)) : keys;

  const fresh  = relevant.filter(k => allLandings[k].status === 'fresh').length;
  const stale  = relevant.filter(k => allLandings[k].status === 'stale').length;
  const failed = relevant.filter(k => allLandings[k].status === 'failed').length;

  return { fresh, stale, failed, total: relevant.length, relevant, allLandings };
}

function timeAgo(isoStr) {
  if (!isoStr) return 'never';
  const d = new Date(isoStr);
  const mins = Math.round((Date.now() - d) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  return `${hrs}h ago`;
}

function FreshnessWidget({ regions, compact }) {
  const [open, setOpen] = useS(false);
  const ref = React.useRef(null);
  const f = useFreshness(regions);

  React.useEffect(() => {
    if (!open) return;
    function onOutside(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', onOutside);
    return () => document.removeEventListener('mousedown', onOutside);
  }, [open]);

  if (!f) return null;

  const allFresh = f.stale === 0 && f.failed === 0;
  const hasFailed = f.failed > 0;
  const icon  = hasFailed ? '❌' : f.stale > 0 ? '⚠️' : '✓';
  const color = hasFailed ? '#EF4444' : f.stale > 0 ? '#F59E0B' : '#34D399';
  const label = allFresh
    ? `${f.total} landings fresh`
    : hasFailed
      ? `${f.fresh} of ${f.total} fresh, ${f.failed} down`
      : `${f.fresh} of ${f.total} fresh`;

  return (
    <span className={`freshness-widget${compact ? ' compact' : ''}`} ref={ref}>
      <button className="freshness-pill" style={{ color }} onClick={() => setOpen(o => !o)}
              title="Click for landing details">
        <span className="freshness-icon">{icon}</span>
        <span className="freshness-label">{label}</span>
      </button>
      {open && (
        <div className="freshness-popover">
          <div className="freshness-popover-title">Landing Update Status</div>
          {f.relevant.map(name => {
            const info = f.allLandings[name];
            const s = info.status;
            const ico = s === 'fresh' ? '✓' : s === 'stale' ? '⚠' : '✗';
            const c   = s === 'fresh' ? '#34D399' : s === 'stale' ? '#F59E0B' : '#EF4444';
            return (
              <div key={name} className="freshness-row">
                <span className="freshness-row-icon" style={{ color: c }}>{ico}</span>
                <span className="freshness-row-name">{name}</span>
                <span className="freshness-row-time">{timeAgo(info.lastSuccess)}</span>
              </div>
            );
          })}
        </div>
      )}
    </span>
  );
}

function ForecastWidget({ navigate }) {
  const fc = window.SD?.FORECAST?.today;
  if (!fc) return null;
  const score = fc.overall_score;
  const sst   = fc.sst_offshore ?? fc.sst_nearshore;
  const items = [
    { icon: '🌡️', val: sst != null ? `${Math.round(sst)}°F` : '—' },
    { icon: fc.moon_phase != null && fc.moon_phase >= 85 ? '🌕' : '🌓',
      val: fc.moon_phase_name || '—' },
    { icon: '💨', val: fc.wind_speed != null ? `${Math.round(fc.wind_speed)}kn` : '—' },
    { icon: '🌊', val: fc.swell_height != null ? `${fc.swell_height.toFixed(1)}ft` : '—' },
  ];
  return (
    <div className="fc-widget">
      <div className="fc-widget-left">
        <div className="fc-widget-label">{fc.conditions_label || '—'}</div>
        <div className="fc-widget-score" style={{color: _fcScoreColor(score)}}>
          {score != null ? score.toFixed(1) : '—'}
          <span className="fc-widget-denom">/10</span>
        </div>
        <div className="fc-widget-sub">Today's Forecast</div>
      </div>
      <div className="fc-widget-mid">
        <div className="fc-widget-conds">
          {items.map(({icon, val}, i) => (
            <span key={i} className="fc-widget-cond">{icon} {val}</span>
          ))}
        </div>
        {fc.summary && <div className="fc-widget-summary">{fc.summary}</div>}
      </div>
      <div className="fc-widget-right">
        <button className="btn sm ghost" onClick={() => navigate('forecast')}>
          7-Day Forecast →
        </button>
      </div>
    </div>
  );
}


const TODAY_ISO = new Date().toISOString().slice(0, 10);

// ── Community intelligence widgets ────────────────────────────────────────────

const BITE_STATUS = {
  hot:    { dots: 5, color: '#10B981', label: 'Hot' },
  active: { dots: 4, color: '#FBBF24', label: 'Active' },
  slow:   { dots: 2, color: '#F97316', label: 'Slow' },
  none:   { dots: 1, color: '#94A3B8', label: 'Quiet' },
};

function BiteStatusDots({ status }) {
  const cfg = BITE_STATUS[status] || BITE_STATUS.none;
  return (
    <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
      {[0,1,2,3,4].map(i => (
        <span key={i} style={{
          width: 7, height: 7, borderRadius: '50%',
          background: i < cfg.dots ? cfg.color : '#1E293B',
          display: 'inline-block', flexShrink: 0,
        }}/>
      ))}
      <span style={{ color: cfg.color, fontWeight: 700, fontSize: 11, marginLeft: 4 }}>
        {cfg.label}
      </span>
    </span>
  );
}

function BiteReportWidget() {
  const community = window.SD?.COMMUNITY;
  const bite = community?.biteReport;
  if (!bite || !bite.species || bite.species.length === 0) return null;
  // Filter to trophy + common species the user cares about
  const display = bite.species.filter(s =>
    ['Bluefin','Yellowfin','Yellowtail','Dorado','Albacore','Yellowtail','White Sea Bass'].includes(s.name)
  ).slice(0, 5);
  if (display.length === 0) return null;
  return (
    <div className="cm-widget">
      <div className="cm-widget-head">
        <div className="cm-widget-title">🎣 What's Biting</div>
        <div className="cm-widget-sub">Based on recent community reports</div>
      </div>
      <div className="cm-bite-list">
        {display.map(sp => (
          <div key={sp.name} className="cm-bite-row">
            <span className="cm-bite-name">{sp.name}</span>
            <BiteStatusDots status={sp.status}/>
            <span className="cm-bite-where">{sp.where || '—'}</span>
            <span className="cm-bite-reports">{sp.reports} report{sp.reports !== 1 ? 's' : ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function HotspotsWidget() {
  const community = window.SD?.COMMUNITY;
  const spots = community?.hotspots;
  if (!spots || spots.length === 0) return null;
  const maxMentions = spots[0]?.mentions || 1;
  return (
    <div className="cm-widget">
      <div className="cm-widget-head">
        <div className="cm-widget-title">📍 Where They're Biting</div>
        <div className="cm-widget-sub">Location mentions weighted by report quality</div>
      </div>
      <div className="cm-hotspot-list">
        {spots.slice(0, 5).map((spot, i) => (
          <div key={spot.location} className="cm-hotspot-row">
            <span className="cm-hotspot-rank">{i + 1}</span>
            <span className="cm-hotspot-name">{spot.location}</span>
            <div className="cm-hotspot-bar-wrap">
              <div className="cm-hotspot-bar"
                   style={{ width: `${(spot.mentions / maxMentions) * 100}%` }}/>
            </div>
            <span className="cm-hotspot-count">{spot.mentions}</span>
            {spot.species.length > 0 && (
              <span className="cm-hotspot-species">{spot.species.slice(0, 2).join(', ')}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function WeeklySummaryWidget() {
  const [collapsed, setCollapsed] = useS(false);
  const ws = window.SD?.COMMUNITY?.weeklySummary;
  if (!ws || !ws.text) return null;
  // Auto-collapse after 3 days
  const generatedDaysAgo = ws.generated_at
    ? Math.floor((Date.now() - new Date(ws.generated_at).getTime()) / 86400000)
    : 0;
  if (generatedDaysAgo > 7) return null;
  const moodEmoji = ws.mood === 'optimistic' ? '🟢' : ws.mood === 'pessimistic' ? '🔴' : '🟡';
  const weekLabel = ws.week_start && ws.week_end
    ? `${ws.week_start.slice(5).replace('-', '/')} – ${ws.week_end.slice(5).replace('-', '/')}`
    : 'This week';
  return (
    <div className="cm-widget cm-weekly">
      <div className="cm-widget-head cm-weekly-head" onClick={() => setCollapsed(c => !c)}
           style={{ cursor: 'pointer' }}>
        <div>
          <div className="cm-widget-title">📋 Week in Review — {weekLabel}</div>
          <div className="cm-widget-sub">
            {ws.report_count} reports · Community mood: {ws.mood} {moodEmoji}
          </div>
        </div>
        <span className="cm-collapse-btn">{collapsed ? '▼' : '▲'}</span>
      </div>
      {!collapsed && (
        <div className="cm-weekly-body">
          <p className="cm-weekly-text">{ws.text}</p>
          {ws.top_species && ws.top_species.length > 0 && (
            <div className="cm-weekly-meta">
              Top species: {ws.top_species.join(', ')}
              {ws.top_location && ` · Top spot: ${ws.top_location}`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const RATINGS = {
  fire:  { emoji: '🔥', label: 'On Fire',       short: 'On Fire',   color: '#F97316' },
  above: { emoji: '⬆️',  label: 'Above Average', short: 'Above Avg', color: '#22C55E' },
  avg:   { emoji: '➡️',  label: 'Average',        short: 'Average',   color: '#94A3B8' },
  below: { emoji: '⬇️',  label: 'Below Average', short: 'Below Avg', color: '#EAB308' },
  slow:  { emoji: '🧊', label: 'Slow Day',       short: 'Slow',      color: '#3B82F6' },
  new:   { emoji: '—',  label: 'New',            short: 'New',       color: '#94A3B8' },
};

function RatingBadge({ ratingKey }) {
  const r = RATINGS[ratingKey] || RATINGS.new;
  return (
    <span style={{ color: r.color, fontWeight: 600, whiteSpace: 'nowrap', fontSize: 11 }}>
      {r.emoji} {r.short}
    </span>
  );
}

function fmtDate(iso) {
  const [y, m, d] = iso.split('-');
  return `${+m}/${+d}/${String(+y).slice(-2)}`;
}

const TROPHY_SET = new Set(['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado']);

function CatchDetail({ fullCatch }) {
  if (!fullCatch || typeof fullCatch !== 'object') return null;
  const entries = Object.entries(fullCatch).filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) return null;
  return (
    <div className="catch-detail-row">
      {entries.map(([sp, n]) => (
        <span key={sp} className={`catch-species ${TROPHY_SET.has(sp) ? 'catch-species-trophy' : 'catch-species-other'}`}
              style={TROPHY_SET.has(sp) ? {color: SPECIES_COLORS[sp] || 'var(--tb-ink)'} : {}}>
          <span className="catch-count">{n}</span> {sp}
        </span>
      ))}
    </div>
  );
}

function TodayCatch({ navigate, settings, regions }) {
  const [expanded, setExpanded] = useS({});

  function toggleCatch(key) {
    setExpanded(prev => ({ ...prev, [key]: !prev[key] }));
  }

  // All dates with trip data for selected region, newest first.
  const dates = useMemo(() => {
    const raw = window.SD_PROC_TRIPS || window.SD.TRIPS;
    const eff = (regions && window.getEffectiveRegion) ? window.getEffectiveRegion(regions) : null;
    const rl = (eff && window.getLandingsForRegion) ? window.getLandingsForRegion(eff) : null;
    const filtered = rl ? raw.filter(t => rl.includes(t.landing)) : raw;
    const set = [...new Set(filtered.map(t => t.date))];
    return set.sort().reverse();
  }, [settings, regions]);

  const [selectedDate, setSelectedDate] = useS(
    () => dates.includes(TODAY_ISO) ? TODAY_ISO : (dates[0] || TODAY_ISO)
  );

  // Rating data for selected date (includes sorted boat rows + fleet rating key).
  const ratingData = useMemo(() => SDA.fishingRating(selectedDate, regions), [selectedDate, settings, regions]);

  const summary = useMemo(() => {
    const boats = ratingData.boats;
    return {
      trophyCount: boats.reduce((s, t) => s + (t.totalTuna || 0), 0),
      anglers:     boats.reduce((s, t) => s + t.anglers, 0),
      Bluefin:     boats.reduce((s, t) => s + (t.Bluefin || 0), 0),
      Yellowfin:   boats.reduce((s, t) => s + (t.Yellowfin || 0), 0),
      Yellowtail:  boats.reduce((s, t) => s + (t.Yellowtail || 0), 0),
      Dorado:      boats.reduce((s, t) => s + (t.Dorado || 0), 0),
    };
  }, [ratingData]);

  const isToday = selectedDate === TODAY_ISO;
  const lastScrape = window.SD?.META?.lastScrape;
  const timeStr = lastScrape
    ? new Date(lastScrape).toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        timeZone: 'America/Los_Angeles',
        timeZoneName: 'short'
      })
    : null;

  const activeSpecies = [
    { key: 'Bluefin',    color: SPECIES_COLORS.Bluefin },
    { key: 'Yellowfin',  color: SPECIES_COLORS.Yellowfin },
    { key: 'Yellowtail', color: SPECIES_COLORS.Yellowtail },
    { key: 'Dorado',     color: SPECIES_COLORS.Dorado },
  ].filter(s => summary[s.key] > 0);

  return (
    <Fragment>
      <div className="today-banner">
        <div className="today-left">
          <div className="today-head"><i className="fa-solid fa-fish-fins"></i> Today's Report</div>
          <div className="today-date">{fmtDate(selectedDate)}</div>
          {timeStr && (
            <div style={{fontSize:11, color:'#94A3B8', marginTop:2, display:'flex', alignItems:'center', gap:6, flexWrap:'wrap'}}>
              Updated {timeStr}
              <FreshnessWidget regions={regions} compact/>
            </div>
          )}
        </div>

        {ratingData.fleetRatingKey && (
          <div className="fleet-rating-badge">
            <span className="frb-emoji">{RATINGS[ratingData.fleetRatingKey].emoji}</span>
            <div>
              <div className="frb-label" style={{color: RATINGS[ratingData.fleetRatingKey].color}}>
                {RATINGS[ratingData.fleetRatingKey].label}
              </div>
              <div className="frb-sub">vs. last 30 days · same trip length</div>
            </div>
          </div>
        )}

        {/* Date picker */}
        <div style={{display:'flex', alignItems:'center'}}>
          <select value={selectedDate} onChange={e => setSelectedDate(e.target.value)}>
            {dates.map(dt => (
              <option key={dt} value={dt}>{fmtDate(dt)}{dt === TODAY_ISO ? ' (today)' : ''}</option>
            ))}
          </select>
        </div>

      </div>

      {ratingData.boats.length === 0 ? (
        <div style={{padding:'32px 0', textAlign:'center',
                     color:'var(--ss-slate)', font:'400 14px/20px var(--ss-font-sans)'}}>
          {isToday ? 'No reports yet today — check back later.' : 'No reports for this date.'}
        </div>
      ) : (
        <Panel title="Today's Report" meta="Sorted by tuna per angler (TPA) per day">
          <div className="today-boat-row today-boat-hd">
            <span>Boat</span>
            <span>Landing</span>
            <span>Trip</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Bluefin}}>Bluefin</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Yellowfin}}>Yellowfin</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Yellowtail}}>Yellowtail</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Dorado}}>Dorado</span>
            <span className="trophy-col">Tuna</span>
            <span className="anglers-col">Anglers</span>
            <span>TPA/Day</span>
            <span className="rating-col">Rating</span>
          </div>
          {ratingData.boats.map((b, i) => {
            const hasFc = b.fullCatch && Object.keys(b.fullCatch).length > 0;
            const expandKey = `${b.boat}|${b.landing}`;
            const isExpanded = expanded[expandKey];
            return (
              <div key={i} className="today-boat-wrap">
                <div className="today-boat-row" style={{cursor:'pointer'}}
                     onClick={() => navigate('boat', { boat: b.boat })}>
                  <span className="boat-name" style={{font:'600 12px/16px var(--ss-font-sans)', color:'var(--tb-ink)'}}>{b.boat}</span>
                  <span>{b.landing.replace(' Sportfishing','').replace(' Landing','')}</span>
                  <span>{b.tripLength}</span>
                  <span className="sp-col" style={{fontWeight: b.Bluefin > 0 ? 600 : 400, color: b.Bluefin > 0 ? SPECIES_COLORS.Bluefin : 'var(--tb-gray-3)'}}>{fmt.n(b.Bluefin)}</span>
                  <span className="sp-col" style={{fontWeight: b.Yellowfin > 0 ? 600 : 400, color: b.Yellowfin > 0 ? SPECIES_COLORS.Yellowfin : 'var(--tb-gray-3)'}}>{fmt.n(b.Yellowfin)}</span>
                  <span className="sp-col" style={{fontWeight: b.Yellowtail > 0 ? 600 : 400, color: b.Yellowtail > 0 ? SPECIES_COLORS.Yellowtail : 'var(--tb-gray-3)'}}>{fmt.n(b.Yellowtail)}</span>
                  <span className="sp-col" style={{fontWeight: b.Dorado > 0 ? 600 : 400, color: b.Dorado > 0 ? SPECIES_COLORS.Dorado : 'var(--tb-gray-3)'}}>{fmt.n(b.Dorado)}</span>
                  <span className="trophy-col" style={{fontWeight:600, color:'var(--tb-ink)'}}>{fmt.n(b.totalTuna)}</span>
                  <span className="anglers-col">{fmt.n(b.anglers)}</span>
                  <span style={{fontWeight:700, color: i === 0 ? 'var(--ss-orange-500)' : 'var(--tb-ink)'}}>{fmt.tpa(b.trophyPerAnglerPerDay)}</span>
                  <span className="rating-col"><RatingBadge ratingKey={b.ratingKey}/></span>
                  {hasFc && (
                    <span className="catch-expand-btn" title="Full catch"
                          onClick={e => { e.stopPropagation(); toggleCatch(expandKey); }}>
                      {isExpanded ? '▲' : '▼'}
                    </span>
                  )}
                  {selectedDate < TODAY_ISO && (
                    <span className="today-review-star" title="Review this trip"
                          onClick={e => {
                            e.stopPropagation();
                            const params = new URLSearchParams();
                            params.set('openReview', '1');
                            params.set('date', selectedDate);
                            params.set('length', b.tripLength || '');
                            history.replaceState(null, '', `?${params.toString()}`);
                            navigate('boat', { boat: b.boat });
                          }}>⭐</span>
                  )}
                </div>
                {isExpanded && hasFc && <CatchDetail fullCatch={b.fullCatch}/>}
              </div>
            );
          })}
        </Panel>
      )}
    </Fragment>
  );
}

function ReturnVisitToast({ navigate }) {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    try {
      if (sessionStorage.getItem('tt_toast_shown')) return;
      const today = new Date().toISOString().slice(0,10);
      const viewed = JSON.parse(localStorage.getItem('tt_viewed_trips') || '[]');
      const past = viewed.filter(v => v.date < today);
      if (!past.length) return;
      const pick = past[0];
      setToast(pick);
      sessionStorage.setItem('tt_toast_shown', '1');
      // Mark reviewed so it won't show again
      const updated = viewed.filter(v => !(v.boat === pick.boat && v.date === pick.date));
      localStorage.setItem('tt_viewed_trips', JSON.stringify(updated));
    } catch {}
  }, []);
  if (!toast) return null;
  const dismiss = () => setToast(null);
  const goReview = () => {
    const params = new URLSearchParams();
    params.set('openReview', '1');
    params.set('date', toast.date);
    if (toast.length) params.set('length', toast.length);
    history.replaceState(null, '', `?${params.toString()}`);
    navigate('boat', { boat: toast.boat });
    dismiss();
  };
  return (
    <div className="rv-toast">
      <span className="rv-toast-text">
        Welcome back! How was your trip on <strong>{toast.boat}</strong>?
      </span>
      <button className="rv-toast-review" onClick={goReview}>⭐ Leave a review</button>
      <button className="rv-toast-close" onClick={dismiss} aria-label="Dismiss">✕</button>
    </div>
  );
}

function TodayView({ navigate, settings, regions }) {
  const currentYear = String(new Date().getFullYear());

  const yearTrips = useMemo(
    () => SDA.filterTrips({ ...DEFAULT_FILTERS, year: currentYear }, regions),
    [settings, regions]
  );

  const { rows: leaderboard } = useMemo(
    () => SDA.boatLeaderboard(yearTrips, 'all', 5),
    [yearTrips]
  );

  const topBoats = leaderboard.slice(0, 10);
  const maxTPAPerDay = topBoats[0]?.avgTPAPerDay || 1;

  const regionLabel = (regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego';

  return (
    <Fragment>
      <ReturnVisitToast navigate={navigate}/>
      <div className="pagehead">
        <div>
          <h1>The Tuna Tracker <span className="region-subtitle-badge">{regionLabel}</span></h1>
          <p style={{fontSize:13, color:'#94A3B8', maxWidth:500, marginBottom:16, lineHeight:1.6}}>
            Real-time sportfishing analytics for {regionLabel} — daily fish counts, boat leaderboards, and trip stats.
            Compare boats, spot trends, plan your next trip.
          </p>
        </div>
      </div>

      <ForecastWidget navigate={navigate}/>

      <TodayCatch navigate={navigate} settings={settings} regions={regions}/>
      <WeeklySummaryWidget/>
      <BiteReportWidget/>
      <HotspotsWidget/>

      <CommunityReportsWidget/>

      <div style={{marginTop: 20}}>
        <Panel title={`Top Boats — ${currentYear} Season`}
               meta="Ranked by avg tuna/angler/day · min 5 trips"
               actions={<button className="btn sm ghost" onClick={() => navigate('analytics', { subtab: 'overview' })}>Full Analytics →</button>}>
          {topBoats.length === 0 ? (
            <div className="muted-block">No data yet for {currentYear}.</div>
          ) : (
            <Fragment>
              <div style={{position: 'relative'}}>
                {topBoats.map((b, i) => {
                  const wpct = (b.avgTPAPerDay / maxTPAPerDay) * 100;
                  return (
                    <div key={b.boat} className={`bar-row ${b.label === 'Spike' ? 'spike' : 'consistent'}`}
                         style={{cursor:'pointer'}}
                         onClick={() => navigate('boat', { boat: b.boat })}>
                      <div className="label">
                        <span className="rank" style={{color: i < 3 ? 'var(--ss-orange-500)' : null, fontWeight: i < 3 ? 700 : 500}}>{i + 1}</span>
                        <div style={{minWidth: 0, flex: 1}}>
                          <div className="name">{b.boat}</div>
                          <div className="lan">{b.landing.replace(' Sportfishing','').replace(' Landing','')} · {b.tripCount} trips</div>
                        </div>
                      </div>
                      <div className="track">
                        <div className="fill" style={{width: `${wpct}%`}}></div>
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
    </Fragment>
  );
}

// ── Home page ─────────────────────────────────────────────────────────────────

function HomeRatingBadge({ ratingKey }) {
  const MAP = {
    fire:  { bg: '#BBF7D0', color: '#14532D', text: 'On Fire'   },
    above: { bg: '#BBF7D0', color: '#14532D', text: 'Above Avg' },
    avg:   { bg: '#E2E8F0', color: '#334155', text: 'Average'   },
    below: { bg: '#FDE68A', color: '#78350F', text: 'Below Avg' },
    slow:  { bg: '#E2E8F0', color: '#334155', text: 'Slow'      },
    new:   { bg: '#E2E8F0', color: '#334155', text: 'New'       },
  };
  const r = MAP[ratingKey] || MAP.new;
  return (
    <span style={{ background: r.bg, color: r.color, fontWeight: 600, fontSize: 10, padding: '2px 8px', borderRadius: 20, whiteSpace: 'nowrap' }}>
      {r.text}
    </span>
  );
}

function HomeView({ navigate, settings, regions }) {
  // Trip count for credibility line
  const totalTrips = window.SD?.META?.tripCount || 0;
  const roundedTrips = Math.floor(totalTrips / 100) * 100;
  const tripDisplay = roundedTrips.toLocaleString() + '+';

  // Date list for the selected region
  const dates = useMemo(() => {
    const raw = window.SD_PROC_TRIPS || window.SD.TRIPS;
    const eff = (regions && window.getEffectiveRegion) ? window.getEffectiveRegion(regions) : null;
    const rl = (eff && window.getLandingsForRegion) ? window.getLandingsForRegion(eff) : null;
    const filtered = rl ? raw.filter(t => rl.includes(t.landing)) : raw;
    const set = [...new Set(filtered.map(t => t.date))];
    return set.sort().reverse();
  }, [regions, settings]);

  const [selectedDate, setSelectedDate] = useS(
    () => dates.includes(TODAY_ISO) ? TODAY_ISO : (dates[0] || TODAY_ISO)
  );

  const ratingData = useMemo(
    () => SDA.fishingRating(selectedDate, regions),
    [selectedDate, regions, settings]
  );

  const boats      = ratingData.boats;
  const trophyTotal = boats.reduce((s, b) => s + (b.totalTuna || 0), 0);
  const anglersTotal = boats.reduce((s, b) => s + b.anglers, 0);
  const landingCount = new Set(boats.map(b => b.landing)).size;
  const previewBoats = boats.slice(0, 8);

  const lastScrape = window.SD?.META?.lastScrape;
  const timeStr = lastScrape
    ? new Date(lastScrape).toLocaleTimeString('en-US', {
        hour: 'numeric', minute: '2-digit',
        timeZone: 'America/Los_Angeles', timeZoneName: 'short',
      })
    : null;

  const regionLabel = (regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego';

  return (
    <Fragment>
      {/* ── HERO ──────────────────────────────────────────────────────── */}
      <div className="home-hero">
        <div className="home-hero-content">
          <div className="home-hero-badge">SAN DIEGO'S #1 SPORTFISHING ANALYTICS</div>
          <h1 className="home-hero-h1">Stop guessing.<br/>Start catching.</h1>
          <p className="home-hero-sub">
            See who's catching, compare fish counts, and book your next trip — every sportboat, in one place.
          </p>
          <div className="home-cred">
            <span className="home-cred-star">★</span>
            {' Trusted data from '}
            <span className="home-cred-count">{tripDisplay} trips</span>
            {' since 2015'}
          </div>
        </div>
      </div>

      {/* ── STATS BAR ─────────────────────────────────────────────────── */}
      <div className="home-stats-bar">
        <div className="home-stat">
          <span className="home-stat-num lime">{fmt.n(trophyTotal)}</span>
          <span className="home-stat-lbl">Tuna Today</span>
        </div>
        <div className="home-stat">
          <span className="home-stat-num">{boats.length}</span>
          <span className="home-stat-lbl">Boats Out</span>
        </div>
        <div className="home-stat">
          <span className="home-stat-num">{fmt.n(anglersTotal)}</span>
          <span className="home-stat-lbl">Anglers</span>
        </div>
        <div className="home-stat">
          <span className="home-stat-num">{landingCount}</span>
          <span className="home-stat-lbl">Landings</span>
        </div>
        {timeStr && (
          <div className="home-stat-freshness">
            Updated {timeStr} · <FreshnessWidget regions={regions} compact/>
          </div>
        )}
      </div>

      {/* ── FEATURE CARDS ─────────────────────────────────────────────── */}
      <div className="home-cards">
        <div className="home-card" onClick={() => navigate('analytics', { subtab: 'overview' })}>
          <div className="home-card-title">Analytics <span className="home-card-arrow">→</span></div>
          <div className="home-card-desc">Boat leaderboards, head-to-head &amp; 11 years of trends</div>
        </div>
        <div className="home-card" onClick={() => navigate('tripplanner')}>
          <div className="home-card-title">Trip Planner <span className="home-card-arrow">→</span></div>
          <div className="home-card-desc">Compare &amp; find the best upcoming trips with open spots</div>
        </div>
      </div>

      {/* ── TODAY'S REPORT (inline preview) ───────────────────────────── */}
      <div className="home-section">
        <div className="home-report-hd">
          <div>
            <div className="home-report-title">Today's Report</div>
            <div className="home-report-sub">
              {fmtDate(selectedDate)}{timeStr ? ` · Updated ${timeStr}` : ''}
            </div>
          </div>
          <select className="home-date-sel"
                  value={selectedDate}
                  onChange={e => setSelectedDate(e.target.value)}>
            {dates.map(dt => (
              <option key={dt} value={dt}>
                {fmtDate(dt)}{dt === TODAY_ISO ? ' (today)' : ''}
              </option>
            ))}
          </select>
        </div>

        {previewBoats.length === 0 ? (
          <div className="home-report-empty">
            {selectedDate === TODAY_ISO ? 'No reports yet today — check back later.' : 'No reports for this date.'}
          </div>
        ) : (
          <div className="home-report-table-wrap">
            <table className="home-report-table">
              <thead>
                <tr>
                  <th>Boat</th>
                  <th className="hrt-trip">Trip</th>
                  <th className="hrt-bf">Bluefin</th>
                  <th>TPA/Day</th>
                  <th>Rating</th>
                </tr>
              </thead>
              <tbody>
                {previewBoats.map((b, i) => (
                  <tr key={i} className="hrt-row"
                      onClick={() => navigate('boat', { boat: b.boat })}>
                    <td>
                      <div className="hrt-boat-name">{b.boat}</div>
                      <div className="hrt-boat-landing">
                        {(b.landing || '').replace(' Sportfishing', '').replace(' Landing', '')}
                      </div>
                    </td>
                    <td className="hrt-trip">{b.tripLength}</td>
                    <td className="hrt-bf" style={{
                      color: b.Bluefin > 0 ? SPECIES_COLORS.Bluefin : 'var(--tb-gray-3)',
                      fontWeight: b.Bluefin > 0 ? 600 : 400,
                    }}>{fmt.n(b.Bluefin)}</td>
                    <td style={{
                      fontWeight: 700,
                      color: i === 0 ? '#38BDF8' : 'var(--tb-ink)',
                    }}>{fmt.tpa(b.trophyPerAnglerPerDay)}</td>
                    <td><HomeRatingBadge ratingKey={b.ratingKey}/></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="home-report-footer">
          <button className="home-full-report-btn" onClick={() => navigate('today')}>
            View full report &amp; all boats →
          </button>
        </div>
      </div>
    </Fragment>
  );
}

Object.assign(window, { TodayView, HomeView });
