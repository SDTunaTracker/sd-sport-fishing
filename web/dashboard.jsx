// Today view — Today's Report (with date picker) + Current Year Leaderboard
// ForecastWidget is intentionally above TodayCatch to surface conditions before catch data.
const { useMemo, useState, useState: useS, useEffect } = React;

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

const SHORT_NAMES = {
  'H&M Landing': 'H&M',
  "Fisherman's Landing": "Fisherman's",
  'Seaforth Sportfishing': 'Seaforth',
  'Point Loma Sportfishing': 'Point Loma',
  'Oceanside Sea Center': 'Oceanside',
  '22nd Street Landing': '22nd Street',
};
function shortName(n) { return SHORT_NAMES[n] || n; }

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

  // Map backend status (fresh/stale/failed) → user-facing terminology
  const STATUS_MAP = { fresh: 'updated', stale: 'waiting', failed: 'delayed' };
  const landings = f.relevant.map(name => ({
    name,
    status: STATUS_MAP[f.allLandings[name].status] || 'delayed',
    info: f.allLandings[name],
  }));

  const total      = landings.length;
  const updatedLs  = landings.filter(l => l.status === 'updated');
  const waitingLs  = landings.filter(l => l.status === 'waiting');
  const delayedLs  = landings.filter(l => l.status === 'delayed');
  const updCount   = updatedLs.length;

  let icon, label, color;

  if (updCount === total) {
    icon = '✓'; label = 'All landings updated'; color = '#10B981';
  } else if (waitingLs.length === 1 && delayedLs.length === 0) {
    icon = '⌛'; label = `Waiting on ${shortName(waitingLs[0].name)}`; color = '#F59E0B';
  } else if (waitingLs.length === 2 && delayedLs.length === 0) {
    icon = '⌛'; label = `Waiting on ${shortName(waitingLs[0].name)} and ${shortName(waitingLs[1].name)}`; color = '#F59E0B';
  } else if (waitingLs.length > 0 && delayedLs.length === 0) {
    icon = '⌛'; label = `${updCount} of ${total} updated`; color = '#F59E0B';
  } else if (delayedLs.length === 1) {
    icon = '⌛'; label = `${shortName(delayedLs[0].name)} delayed`; color = '#F59E0B';
  } else {
    icon = '⌛'; label = `${updCount} of ${total} updated`; color = '#F59E0B';
  }

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
          {landings.map(({ name, status, info }) => {
            const ico = status === 'updated' ? '✓' : '⌛';
            const c   = status === 'updated' ? '#34D399' : '#F59E0B';
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


// Pacific calendar date — recomputed each render-time use so a long-lived tab
// crossing midnight Pacific still gets the right "today".
const getTodayISO = () => window.TT_DATES.getPacificDate();
const TODAY_ISO   = getTodayISO();

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
  const key = RATINGS[ratingKey] ? ratingKey : 'new';
  return (
    <span className={`rating-badge rb-${key}`}>
      {r.emoji} {r.short}
    </span>
  );
}

const RATING_ORDER = ['fire', 'above', 'avg', 'below', 'slow'];

function RatingLegend() {
  return (
    <div className="rating-legend" aria-label="Rating legend">
      <span className="rating-legend-label">Rating:</span>
      {RATING_ORDER.map(key => {
        const r = RATINGS[key];
        return (
          <span key={key} className="rating-legend-item" style={{ color: r.color }}>
            {r.emoji} {r.short}
          </span>
        );
      })}
      <span className="rating-legend-note">vs. same-length trips · last 30 days</span>
    </div>
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

// ── Today performance summary ────────────────────────────────────────────────

function _avgArr(arr) {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function getTodayPerformanceSummary(todayTrips, allTrips, selectedDate) {
  if (!todayTrips || todayTrips.length === 0) {
    return { status: 'no_data', tone: 'neutral', message: null };
  }
  const todayAvgTPA = _avgArr(todayTrips.map(t => t.trophyPerAnglerPerDay || 0));
  const boatCount = todayTrips.length;

  // Early-day heuristic: before 4pm Pacific (San Diego local) with only 1-2 boats back
  if (selectedDate === getTodayISO() && window.TT_DATES.getPacificHour() < 16 && boatCount <= 2) {
    return {
      status: 'early', tone: 'neutral',
      message: `Early reports — ${boatCount} boat${boatCount > 1 ? 's' : ''} back so far`,
      boatContext: null, todayAvg: todayAvgTPA, historicalAvg: null,
    };
  }

  // 30-day historical baseline for the same trip lengths represented today
  const cutoff = new Date(new Date(selectedDate + 'T12:00:00Z').getTime() - 30 * 24 * 60 * 60 * 1000)
    .toISOString().slice(0, 10);
  const lengths = new Set(todayTrips.map(t => t.tripLength));
  const historical = (allTrips || []).filter(t =>
    t.date >= cutoff && t.date < selectedDate && lengths.has(t.tripLength)
  );

  const boatCtx = `${boatCount} boat${boatCount > 1 ? 's' : ''} returned`;
  if (historical.length < 5) {
    return {
      status: 'insufficient_history', tone: 'neutral',
      message: `${boatCtx} today`, boatContext: null,
      todayAvg: todayAvgTPA, historicalAvg: null,
    };
  }

  const histAvgTPA = _avgArr(historical.map(t => t.trophyPerAnglerPerDay || 0));
  const pct = histAvgTPA > 0 ? ((todayAvgTPA - histAvgTPA) / histAvgTPA) * 100 : 0;

  // Dominant species: ≥80% of today's trophy catch from one species
  const totals = { Bluefin: 0, Yellowfin: 0, Yellowtail: 0, Dorado: 0 };
  let catchTotal = 0;
  todayTrips.forEach(t => {
    Object.keys(totals).forEach(sp => { totals[sp] += (t[sp] || 0); catchTotal += (t[sp] || 0); });
  });
  let dominant = null;
  if (catchTotal > 0) {
    const [sp, n] = Object.entries(totals).sort((a, b) => b[1] - a[1])[0];
    if (n / catchTotal >= 0.8) dominant = sp;
  }

  let status, message, tone, cssExtra = '';
  if (pct >= 50) {
    status = 'on_fire'; tone = 'hot'; cssExtra = 'on-fire';
    message = dominant
      ? `🔥 ${dominant} on fire! Today is ${Math.round(pct)}% above the 30-day avg.`
      : `🔥 ON FIRE! Today is ${Math.round(pct)}% above the 30-day average.`;
  } else if (pct >= 20) {
    status = 'hot'; tone = 'hot';
    message = dominant
      ? `🔥 ${dominant} are hot — ${Math.round(pct)}% above the 30-day avg.`
      : `🔥 Hot day — ${Math.round(pct)}% above the 30-day average.`;
  } else if (pct >= -15) {
    status = 'average'; tone = 'neutral';
    message = 'Today is in line with the last 30 days.';
  } else if (pct >= -40) {
    status = 'below_average'; tone = 'cool';
    message = `Today is ${Math.round(Math.abs(pct))}% below the 30-day average.`;
  } else {
    status = 'slow'; tone = 'cool';
    message = `Slow day — ${Math.round(Math.abs(pct))}% below the 30-day average.`;
  }

  return { status, tone, cssExtra, message, boatContext: boatCtx, todayAvg: todayAvgTPA, historicalAvg: histAvgTPA, pct };
}

function TodaySummaryBanner({ summary }) {
  if (!summary || !summary.message) return null;
  const cls = ['summary-banner', summary.tone, summary.cssExtra].filter(Boolean).join(' ');
  return (
    <div className={cls}>
      <span className="summary-message">{summary.message}</span>
      {summary.boatContext && (
        <span className="summary-context">
          {summary.boatContext} · {fmt.tpa(summary.todayAvg)} avg
        </span>
      )}
    </div>
  );
}

function StillFishingSection({ trips }) {
  if (!trips || trips.length === 0) return null;
  return (
    <div className="still-fishing-section">
      <div className="sf-header">
        <div>
          <h3 className="sf-title">Still Fishing</h3>
          <div className="sf-subtitle">Mid-trip reports — final counts post when boats return</div>
        </div>
      </div>
      <div className="sf-list">
        {trips.map((t, i) => {
          const catchParts = Object.entries(t.catch || {})
            .filter(([, n]) => n > 0)
            .map(([sp, n]) => `${n} ${sp}`);
          const catchStr = catchParts.length > 0 ? catchParts.join(', ') : 'No count yet';
          const ago = t.reportedAt ? timeAgo(t.reportedAt) : null;
          const landing = (t.landing || '').replace(' Sportfishing', '').replace(' Landing', '');
          return (
            <div key={i} className="sf-row">
              <div className="sf-boat">
                <span className="sf-boat-name">{t.boat}</span>
                <span className="sf-boat-sub">{landing} · {t.tripLength} · {t.anglers} anglers</span>
              </div>
              <div className="sf-catch">
                <span className="sf-catch-summary">{catchStr}</span>
                {ago && <span className="sf-reported">Called in {ago}</span>}
              </div>
            </div>
          );
        })}
      </div>
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

  const isToday = selectedDate === TODAY_ISO;

  // For today: split returned boats (final) from still-fishing (preliminary).
  const returnedBoats = isToday
    ? ratingData.boats.filter(b => !b.isPreliminary)
    : ratingData.boats;
  const stillFishing = isToday ? (window.SD?.TODAY?.stillFishing || []) : [];

  const summary = useMemo(() => {
    const boats = returnedBoats;
    return {
      trophyCount: boats.reduce((s, t) => s + (t.totalTuna || 0), 0),
      anglers:     boats.reduce((s, t) => s + t.anglers, 0),
      Bluefin:     boats.reduce((s, t) => s + (t.Bluefin || 0), 0),
      Yellowfin:   boats.reduce((s, t) => s + (t.Yellowfin || 0), 0),
      Yellowtail:  boats.reduce((s, t) => s + (t.Yellowtail || 0), 0),
      Dorado:      boats.reduce((s, t) => s + (t.Dorado || 0), 0),
    };
  }, [ratingData, isToday]);

  const perfSummary = useMemo(() => {
    const boats = isToday ? ratingData.boats.filter(b => !b.isPreliminary) : ratingData.boats;
    return getTodayPerformanceSummary(boats, window.SD_PROC_TRIPS || window.SD.TRIPS, selectedDate);
  }, [ratingData, selectedDate]);
  const activeSpecies = [
    { key: 'Bluefin',    color: SPECIES_COLORS.Bluefin },
    { key: 'Yellowfin',  color: SPECIES_COLORS.Yellowfin },
    { key: 'Yellowtail', color: SPECIES_COLORS.Yellowtail },
    { key: 'Dorado',     color: SPECIES_COLORS.Dorado },
  ].filter(s => summary[s.key] > 0);

  return (
    <React.Fragment>
      <div className="today-banner">
        <div className="today-left">
          <h2 className="today-head">{isToday ? 'Today' : 'Report for'}</h2>
          <div className="today-date">{fmtDate(selectedDate)}</div>
          <div className="today-meta-row">
            <LastUpdated isoStr={window.SD?.META?.lastScrape}/>
            <FreshnessWidget regions={regions} compact/>
          </div>
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
        <div className="today-date-pick">
          <label htmlFor="today-date-select">Date</label>
          <select id="today-date-select" value={selectedDate} onChange={e => setSelectedDate(e.target.value)}>
            {dates.map(dt => (
              <option key={dt} value={dt}>{fmtDate(dt)}{dt === TODAY_ISO ? ' (today)' : ''}</option>
            ))}
          </select>
        </div>

      </div>

      {returnedBoats.length === 0 && stillFishing.length === 0 ? (
        <div style={{padding:'32px 0', textAlign:'center',
                     color:'var(--ss-slate)', font:'400 14px/20px var(--ss-font-sans)'}}>
          {isToday ? 'No reports yet today — check back later.' : 'No reports for this date.'}
        </div>
      ) : returnedBoats.length > 0 ? (
        <Panel title="Boats reporting" meta={`${returnedBoats.length} boat${returnedBoats.length === 1 ? '' : 's'} · sorted by tuna per angler per day`}>
          <TodaySummaryBanner summary={perfSummary}/>
          <div className="today-boat-row today-boat-hd">
            <span>Boat</span>
            <span>Landing</span>
            <span>Trip</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Bluefin}}>Bluefin</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Yellowfin}}>Yellowfin</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Yellowtail}}>Yellowtail</span>
            <span className="sp-col" style={{color: SPECIES_COLORS.Dorado}}>Dorado</span>
            <span className="trophy-col">Trophy</span>
            <span className="anglers-col">Anglers</span>
            <MetricLabel name="TPA/Day" tooltip="Tuna Per Angler per Day — normalizes catches across trip lengths so a 1-day local trip and a 3-day offshore trip are on the same scale. Higher is better." />
            <span className="rating-col">Rating</span>
            <span className="row-actions" aria-hidden="true"></span>
          </div>
          {returnedBoats.map((b, i) => {
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
                  <span style={{display:'inline-flex', alignItems:'center', gap:4, fontWeight:700, color: i === 0 ? 'var(--ss-orange-500)' : 'var(--tb-ink)'}}>
                    {fmt.tpa(b.trophyPerAnglerPerDay)}
                    {i === 0 && <span className="top-boat-chip" aria-label="Top boat by TPA/Day">★ Top</span>}
                  </span>
                  <span className="rating-col"><RatingBadge ratingKey={b.ratingKey}/></span>
                  {/* One trailing cell keeps the row on a single grid line; the
                      expand and review controls used to wrap onto a second row. */}
                  <span className="row-actions">
                    {selectedDate < TODAY_ISO && (
                      <button type="button" className="today-review-star" title="Review this trip"
                              aria-label={`Review ${b.boat}`}
                              onClick={e => {
                                e.stopPropagation();
                                const params = new URLSearchParams();
                                params.set('openReview', '1');
                                params.set('date', selectedDate);
                                params.set('length', b.tripLength || '');
                                history.replaceState(null, '', `?${params.toString()}`);
                                navigate('boat', { boat: b.boat });
                              }}><i className="fa-regular fa-star"></i></button>
                    )}
                    {hasFc && (
                      <button type="button" className="catch-expand-btn" title="Full catch"
                              aria-expanded={!!isExpanded} aria-label="Show full catch"
                              onClick={e => { e.stopPropagation(); toggleCatch(expandKey); }}>
                        <i className={`fa-solid fa-chevron-${isExpanded ? 'up' : 'down'}`}></i>
                      </button>
                    )}
                  </span>
                </div>
                {isExpanded && hasFc && <CatchDetail fullCatch={b.fullCatch}/>}
              </div>
            );
          })}
          <RatingLegend />
        </Panel>
      ) : null}

      {isToday && <StillFishingSection trips={stillFishing}/>}
    </React.Fragment>
  );
}

function ReturnVisitToast({ navigate }) {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    try {
      if (sessionStorage.getItem('tt_toast_shown')) return;
      const today = window.TT_DATES.getPacificDate();
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
  const regionLabel = (regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego';

  // Today v2 (web/home.jsx → TodayReport): the date is the title, a one-line
  // summary, a quiet species strip, then the ranked boat list. It shares the
  // "vs usual" logic and row details with Home's counts block. No season
  // leaderboard here (Home rail + Analytics have it), just a link.
  // Simple answers (web/picker.jsx): plain "best trip" answers first, with a
  // Simple / Detailed switch; Detailed is the full Today v2 report.
  if (window.THTodayReport && window.TodaySimple) {
    return (
      <React.Fragment>
        <ReturnVisitToast navigate={navigate}/>
        <window.TodaySimple navigate={navigate} settings={settings} regions={regions} Report={window.THTodayReport}/>
      </React.Fragment>
    );
  }
  if (window.THTodayReport) {
    return (
      <React.Fragment>
        <ReturnVisitToast navigate={navigate}/>
        <window.THTodayReport navigate={navigate} settings={settings} regions={regions}/>
      </React.Fragment>
    );
  }
  return (
    <React.Fragment>
      <ReturnVisitToast navigate={navigate}/>
      <div className="pagehead">
        <div>
          <h1>Today's Report <span className="region-subtitle-badge">{regionLabel}</span></h1>
        </div>
      </div>
      <TodayCatch navigate={navigate} settings={settings} regions={regions}/>
    </React.Fragment>
  );
}

// ── Home page ─────────────────────────────────────────────────────────────────

const HOME_RATING_MAP = {
  fire:  { bg: '#BBF7D0', color: '#14532D', text: 'On Fire'   },
  above: { bg: '#BBF7D0', color: '#14532D', text: 'Above Avg' },
  avg:   { bg: '#E2E8F0', color: '#334155', text: 'Average'   },
  below: { bg: '#FDE68A', color: '#78350F', text: 'Below Avg' },
  slow:  { bg: '#FEE2E2', color: '#9B1C1C', text: 'Slow'      },
  new:   { bg: '#E2E8F0', color: '#334155', text: 'New'       },
};
function HomeRatingBadge({ ratingKey }) {
  const r = HOME_RATING_MAP[ratingKey] || HOME_RATING_MAP.new;
  return (
    <Badge style={{ background: r.bg, color: r.color, fontWeight: 600, border: 'none', whiteSpace: 'nowrap' }}>
      {r.text}
    </Badge>
  );
}

function HomeTop5({ navigate, settings, regions }) {
  const currentYear = String(window.TT_DATES.getPacificYear());

  // preprocessTrips runs in a useEffect in app.jsx (post-mount), so SD_PROC_TRIPS
  // is null on the first render. Guard synchronously so the leaderboard is correct immediately.
  if (!window.SD_PROC_TRIPS) SDA.preprocessTrips(settings);

  const top5 = useMemo(() => {
    const trips = SDA.filterTrips(DEFAULT_FILTERS, regions);
    const { rows } = SDA.boatLeaderboard(trips, 'all', 5);
    return rows.filter(r => r.tripCount >= 5).slice(0, 5);
  }, [regions, settings]);

  return (
    <div className="home-section">
      <div className="home-report-hd">
        <div>
          <h2 className="home-report-title">Top Boats</h2>
          <div className="home-report-sub">
            <MetricLabel {...METRIC_DEFINITIONS.tpaDay} /> ranking · {currentYear} season · min 5 trips
          </div>
        </div>
        <button className="home-full-report-btn" style={{whiteSpace:'nowrap'}}
                onClick={() => navigate('boats')}>
          View full leaderboard →
        </button>
      </div>

      {top5.length === 0 ? (
        <EmptyState>Not enough data yet</EmptyState>
      ) : (
        <div className="home-top5-list">
          {top5.map((b, i) => (
            <div key={b.boat} className="home-top5-row"
                 onClick={() => navigate('boat', { boat: b.boat })}>
              <span className={`home-top5-rank${i < 3 ? ' top3' : ''}`}>{i + 1}</span>
              <div className="home-top5-info">
                <div className="home-top5-boat">{b.boat}</div>
                <div className="home-top5-meta">
                  {(b.landing || '').replace(' Sportfishing', '').replace(' Landing', '')}
                  {' · '}
                  {b.tripCount} {b.tripCount === 1 ? 'trip' : 'trips'}
                </div>
              </div>
              <span className="home-top5-val">
                {b.avgTPAPerDay > 0 ? fmt.tpa(b.avgTPAPerDay) : '—'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HomeView({ navigate, settings, regions }) {
  const totalTrips = (window.ttRegionData ? window.ttRegionData.totalTripCount() : ((window.SD && window.SD.META && window.SD.META.tripCount) || 0));
  const tripDisplay = (Math.floor(totalTrips / 100) * 100).toLocaleString() + '+';

  // Most-recent date with data for this region
  const reportDate = useMemo(() => {
    const raw = window.SD_PROC_TRIPS || window.SD.TRIPS;
    const eff = (regions && window.getEffectiveRegion) ? window.getEffectiveRegion(regions) : null;
    const rl  = (eff && window.getLandingsForRegion) ? window.getLandingsForRegion(eff) : null;
    const filtered = rl ? raw.filter(t => rl.includes(t.landing)) : raw;
    const dates = [...new Set(filtered.map(t => t.date))].sort().reverse();
    return dates.includes(TODAY_ISO) ? TODAY_ISO : (dates[0] || TODAY_ISO);
  }, [regions]);

  const ratingData = useMemo(
    () => SDA.fishingRating(reportDate, regions),
    [reportDate, regions, settings]
  );
  const latestBoats = ratingData.boats.filter(b => !b.isPreliminary).slice(0, 5);

  // Season leaders (current year, min 5 trips)
  const seasonLeaders = useMemo(() => {
    if (!window.SD_PROC_TRIPS) SDA.preprocessTrips(settings);
    const trips = SDA.filterTrips(DEFAULT_FILTERS, regions);
    const { rows } = SDA.boatLeaderboard(trips, 'all', 5);
    return rows.filter(r => r.tripCount >= 5).slice(0, 4);
  }, [regions, settings]);

  // Conditions from today's forecast
  const fc = window.SD?.FORECAST?.today;
  // Same-location 7-day trend per pill — compares Nearshore-today to Nearshore-7d-ago
  // and 60-Mile-today to 60-Mile-7d-ago. Previous single-pill code mixed the two
  // (today's offshore vs 7d-ago nearshore) and produced a bogus warming/cooling.
  const _sstHistoryAll = window.SD?.SST?.history || [];
  const _weekAgoISO = window.TT_DATES.pacificDateOffsetDays(-7);
  function sstPill(location, current) {
    if (current == null) return null;
    const past = _sstHistoryAll
      .filter(h => h.location === location)
      .sort((a, b) => b.date.localeCompare(a.date))
      .find(h => h.date <= _weekAgoISO);
    const delta = past?.sst != null
      ? parseFloat((current - past.sst).toFixed(1)) : null;
    return { valueF: Math.round(current), delta,
             dataDate: fc?.sst_dates?.[location] || null };
  }
  const sstNearshore = sstPill('Nearshore',    fc?.sst_nearshore);
  const sstOffshore  = sstPill('60-Mile Bank', fc?.sst_offshore);
  // Kept for the "hot" heat color threshold on the primary display.
  const sstF = sstNearshore?.valueF ?? sstOffshore?.valueF ?? null;
  const windKt  = fc?.wind_speed  != null ? Math.round(fc.wind_speed)  : null;
  const moonPct = fc?.moon_phase  != null ? Math.round(fc.moon_phase)  : null;
  const moonName = fc?.moon_phase_name || null;

  // Top trip to book
  const topTrip = useMemo(() => SDA.computeTopTripToBook?.() || null, [settings]);

  function catchLine(b) {
    const parts = [];
    if (b.Bluefin    > 0) parts.push(`${b.Bluefin} Bluefin`);
    if (b.Yellowfin  > 0) parts.push(`${b.Yellowfin} Yellowfin`);
    if (b.Yellowtail > 0) parts.push(`${b.Yellowtail} Yellowtail`);
    if (b.Dorado     > 0) parts.push(`${b.Dorado} Dorado`);
    return parts.join(' · ') || 'No trophy fish';
  }

  function repChipClass(ratingKey, isFirst) {
    if (isFirst) return 'hot';
    if (ratingKey === 'fire' || ratingKey === 'above') return 'good';
    if (ratingKey === 'slow') return 'slow';
    return 'avg';
  }

  function repChipLabel(ratingKey, isFirst) {
    if (isFirst) return '★ Top today';
    return { fire: 'On fire', above: 'Above avg', avg: 'Average', below: 'Average', slow: 'Slow', new: 'Average' }[ratingKey] || 'Average';
  }

  function fmtDep(isoStr) {
    if (!isoStr) return '';
    return new Date(isoStr).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'America/Los_Angeles' });
  }

  return (
    <React.Fragment>
      {/* ── HERO ──────────────────────────────────────────────────────── */}
      <section className="ch-hero">
        <div className="ch-hero-in">
          <div className="ch-kick">San Diego sportboat counts, ranked fairly</div>
          <h1 className="ch-h1">Stop guessing.<br/>Start catching.</h1>
          <p className="ch-by">
            See who's catching, compare fish counts, and book your next trip — every sportboat, in one place.{' '}
            <b>Trusted by data from {tripDisplay} trips.</b>
          </p>
        </div>
      </section>

      {/* ── STRIP: Latest reports + Season leaders ───────────────────── */}
      <div className="ch-wrap">
        <div className="ch-strip">
          {/* Left: Latest reports */}
          <div className="ch-feature">
            <div className="ch-seclbl">
              Latest reports <span className="ch-soft">· across all landings</span>
              <LastUpdated isoStr={window.SD?.META?.lastScrape} compact/>
            </div>
            {latestBoats.length === 0 ? (
              <div style={{padding:'24px 0', color:'var(--ch-muted)', fontSize:14}}>
                No reports yet today — check back later.
              </div>
            ) : latestBoats.map((b, i) => (
              <div key={b.boat + i} className="ch-rep"
                   style={{cursor:'pointer'}}
                   onClick={() => navigate('boat', { boat: b.boat })}>
                <div className="ch-rep-l">
                  <div className="ch-rep-nm">{b.boat}</div>
                  <div className="ch-rep-sub">
                    {shortName(b.landing)} · {b.tripLength} · {fmt.n(b.anglers)} anglers
                    {' · '}<span className="ch-rep-tpa">{fmt.tpa(b.trophyPerAnglerPerDay)} tuna/person/day</span>
                    {b.reportedAt ? ` · ${timeAgo(b.reportedAt)}` : ''}
                  </div>
                  <div className="ch-rep-catch">{catchLine(b)}</div>
                </div>
                <span className={`ch-chip ${repChipClass(b.ratingKey, i === 0)}`}>
                  {repChipLabel(b.ratingKey, i === 0)}
                </span>
              </div>
            ))}
            <button className="ch-more" onClick={() => navigate('today')}>
              View all reports →
            </button>
          </div>

          {/* Right: Season leaders */}
          <div className="ch-lead">
            <div className="ch-ll">Season leaders</div>
            {seasonLeaders.length === 0 ? (
              <div style={{color:'var(--ch-muted)', fontSize:13, paddingTop:12}}>Not enough data yet</div>
            ) : seasonLeaders.map((b, i) => (
              <div key={b.boat} className="ch-row"
                   onClick={() => navigate('boat', { boat: b.boat })}>
                <span className="ch-rk">{i + 1}</span>
                <div>
                  <div className="ch-row-nm">{b.boat}</div>
                  <div className="ch-row-s">
                    {(b.landing || '').replace(' Sportfishing', '').replace(' Landing', '')}
                    {' · '}{b.tripCount} {b.tripCount === 1 ? 'trip' : 'trips'}
                  </div>
                </div>
                <span className="ch-row-v">{fmt.tpa(b.avgTPAPerDay)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── CONDITIONS BAND ──────────────────────────────────────────── */}
      <div className="ch-band">
        <div className="ch-band-in">
          <div className="ch-seclbl">On the water today</div>
          <div className="ch-conds">
            <div className="ch-cond ch-cond-sst">
              <div className="ch-cond-sst-pair">
                {[['Nearshore', sstNearshore, 'Buoy · Point Loma'],
                  ['60-Mile Bank', sstOffshore, 'Offshore satellite']].map(([label, p, hint]) => (
                  <div key={label} className="ch-cond-sst-loc">
                    <div className="ch-cond-sst-lbl">{label}</div>
                    <div className={`ch-cond-v${p?.valueF != null && p.valueF >= 67 ? ' hot' : ''}`}>
                      {p?.valueF != null ? `${p.valueF}°F` : '—'}
                      {p?.delta != null && (
                        <span className={`ch-trend ${p.delta > 0 ? 'up' : 'dn'}`}>
                          {p.delta > 0 ? ' ▲' : ' ▼'}
                        </span>
                      )}
                    </div>
                    <div className="ch-cond-sub">
                      {p?.delta != null
                        ? `${p.delta > 0 ? '+' : ''}${p.delta}° · 7d`
                        : hint}
                    </div>
                  </div>
                ))}
              </div>
              <div className="ch-cond-k">Water temp</div>
            </div>
            <div className="ch-cond">
              <div className="ch-cond-v">{windKt != null ? `${windKt}kt` : '—'}</div>
              <div className="ch-cond-k">Wind</div>
              <div className="ch-cond-sub">
                {windKt == null ? 'No forecast data'
                  : windKt <= 5  ? 'Calm · glassy'
                  : windKt <= 10 ? 'Light · small chop'
                  : windKt <= 15 ? 'Moderate · chop'
                  : 'Windy · rough seas'}
              </div>
            </div>
            <div className="ch-cond">
              <div className="ch-cond-v">{moonPct != null ? `${moonPct}%` : '—'}</div>
              <div className="ch-cond-k">Moon</div>
              <div className="ch-cond-sub">{moonName || 'Moon phase'}</div>
            </div>
          </div>
        </div>
      </div>

      {/* ── TOP TRIP TO BOOK ──────────────────────────────────────────── */}
      {topTrip && (
        <div className="ch-bookband">
          <div className="ch-bookband-in">
            <div className="ch-bb-left">
              <div className="ch-bb-eyebrow">★ Top trip to book · picked by the data</div>
              <div className="ch-bb-boat">{topTrip.boat}</div>
              <div className="ch-bb-meta">
                {shortName(topTrip.landing)} · {topTrip.tripLength}
                {topTrip.departureAt ? ` · departs ${fmtDep(topTrip.departureAt)}` : ''}
                {topTrip.price ? ` · $${topTrip.price}` : ''}
              </div>
              <div className="ch-bb-stats">
                <div>
                  <div className="ch-bb-stat-v coral">{topTrip.recentTpa.toFixed(1)}</div>
                  <div className="ch-bb-stat-k">fish per angler<br/>over last 10 trips</div>
                </div>
                {topTrip.winRate != null && (
                  <div>
                    <div className="ch-bb-stat-v">{topTrip.winRate}%</div>
                    <div className="ch-bb-stat-k">outfished comparable<br/>boats this season</div>
                  </div>
                )}
                <div>
                  <div className="ch-bb-stat-v">#{topTrip.rank}</div>
                  <div className="ch-bb-stat-k">ranked boat<br/>of {topTrip.total} this season</div>
                </div>
              </div>
            </div>
            <div className="ch-bb-right">
              {topTrip.openSpots != null && topTrip.openSpots > 0 && (
                <div className="ch-bb-spots">
                  ● {topTrip.openSpots} spot{topTrip.openSpots === 1 ? '' : 's'} left
                </div>
              )}
              <button className="ch-bb-cta" onClick={() => navigate('tripplanner')}>
                Book this trip →
              </button>
              <button className="ch-bb-sub ch-bb-research" onClick={() => navigate('boat', { boat: topTrip.boat })}>
                Research {topTrip.boat} →
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── EXPLORE CARDS ────────────────────────────────────────────── */}
      <div className="ch-wrap">
        <div className="ch-explore">
          <div className="ch-ec" onClick={() => navigate('analytics', { subtab: 'overview' })}>
            <h3>Analytics <span className="ch-ec-ar">→</span></h3>
            <p>Boat leaderboards, head-to-head matchups, and 11 years of catch trends.</p>
          </div>
          <div className="ch-ec" onClick={() => navigate('tripplanner')}>
            <h3>Trip Planner <span className="ch-ec-ar">→</span></h3>
            <p>Compare upcoming trips and find the best boats with open spots.</p>
          </div>
        </div>
      </div>

      {/* ── EDITORIAL FOOTER ─────────────────────────────────────────── */}
      <footer className="ch-foot">
        <div className="ch-foot-in">
          <b>Tunatracker</b>
          <span>· San Diego sportfishing analytics · H&amp;M · Fisherman's · Seaforth · Point Loma</span>
        </div>
      </footer>
    </React.Fragment>
  );
}

Object.assign(window, { TodayView, HomeView });
