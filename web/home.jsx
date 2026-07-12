// home.jsx — Redesigned HomeView ("counts-first" home, approved design 3a/4a + mobile 5a)
// Drop-in: loads AFTER dist/dashboard.js and overrides window.HomeView.
// Uses existing globals: SDA, fmt, window.SD, TT_DATES, SHORT_NAMES-style shortening,
// design tokens from styles.css (--bg, --ink, --accent, --good, --serif, --mono, …).
// New CSS lives in home.css (th- prefix) — append to styles.css or link separately.

(function () {
  const { useMemo, useState } = React;

  const TH_TROPHY = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];
  const TH_SHORT = {
    'H&M Landing': 'H&M',
    "Fisherman's Landing": "Fisherman's",
    'Seaforth Sportfishing': 'Seaforth',
    'Point Loma Sportfishing': 'Point Loma',
    'Oceanside Sea Center': 'Oceanside',
  };
  const thShort = (n) => TH_SHORT[n] || n;
  const getTodayISO = () => window.TT_DATES.getPacificDate();

  function isoMinus(iso, days) {
    const d = new Date(iso + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10);
  }

  function fmtDayLabel(iso) {
    const d = new Date(iso + 'T12:00:00Z');
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).toUpperCase();
  }

  // Full species names — no acronyms (BFT/YT read as jargon to casual users).
  function thCatchLine(t) {
    const parts = [];
    TH_TROPHY.forEach(sp => { if ((t[sp] || 0) > 0) parts.push(`${t[sp]} ${sp}`); });
    return parts.join(' · ') || 'No trophy fish';
  }

  function regionTrips(regions) {
    const raw = window.SD_PROC_TRIPS || window.SD.TRIPS;
    const eff = window.getEffectiveRegion ? window.getEffectiveRegion(regions) : null;
    const rl = (eff && window.getLandingsForRegion) ? window.getLandingsForRegion(eff) : null;
    return rl ? raw.filter(t => rl.includes(t.landing)) : raw;
  }

  // ── 30-day comparisons ────────────────────────────────────────────────────
  // "Vs usual" = today's trophy/angler/day vs this boat's own same-length trips
  // over the prior 30 days. Needs ≥3 historical trips, else null (shown as "—").
  function boatDelta(trip, allTrips, selectedDate) {
    const cutoff = isoMinus(selectedDate, 30);
    const hist = allTrips.filter(t =>
      t.boat === trip.boat && t.tripLength === trip.tripLength &&
      t.date >= cutoff && t.date < selectedDate
    ).map(t => t.trophyPerAnglerPerDay || 0);
    if (hist.length < 3) return null;
    const avg = hist.reduce((a, b) => a + b, 0) / hist.length;
    if (avg <= 0) return null;
    return Math.round((((trip.trophyPerAnglerPerDay || 0) - avg) / avg) * 100);
  }

  // Daily fleet avg trophy/angler/day for the 30 days ending on selectedDate.
  function fleetTrend(allTrips, selectedDate) {
    const byDate = {};
    const cutoff = isoMinus(selectedDate, 29);
    allTrips.forEach(t => {
      if (t.date >= cutoff && t.date <= selectedDate) {
        (byDate[t.date] || (byDate[t.date] = [])).push(t.trophyPerAnglerPerDay || 0);
      }
    });
    const days = [];
    for (let i = 29; i >= 0; i--) {
      const d = isoMinus(selectedDate, i);
      const vals = byDate[d];
      days.push({ date: d, val: vals ? vals.reduce((a, b) => a + b, 0) / vals.length : null });
    }
    const prior = days.slice(0, 29).map(d => d.val).filter(v => v != null);
    const avg = prior.length ? prior.reduce((a, b) => a + b, 0) / prior.length : 0;
    const today = days[29].val;
    const pct = (today != null && avg > 0) ? Math.round(((today - avg) / avg) * 100) : null;
    return { days, avg, today, pct };
  }

  // Last 10 same-length trips for a boat (ending at selectedDate, inclusive).
  function boatHistory(trip, allTrips, selectedDate) {
    const past = allTrips
      .filter(t => t.boat === trip.boat && t.tripLength === trip.tripLength && t.date < selectedDate)
      .sort((a, b) => b.date.localeCompare(a.date))
      .slice(0, 9)
      .reverse();
    const bars = past.map(t => ({ val: t.trophyPerAnglerPerDay || 0, today: false, date: t.date }));
    bars.push({ val: trip.trophyPerAnglerPerDay || 0, today: true, date: selectedDate });
    const avg = past.length
      ? past.reduce((s, t) => s + (t.trophyPerAnglerPerDay || 0), 0) / past.length : null;
    return { bars, avg, startDate: past[0] ? past[0].date : selectedDate };
  }

  function nextDeparture(boat) {
    const sched = (window.SD && window.SD.SCHEDULE) || [];
    const now = Date.now();
    const up = sched
      .filter(t => t.boat === boat && t.departureAt && new Date(t.departureAt).getTime() > now)
      .sort((a, b) => new Date(a.departureAt) - new Date(b.departureAt));
    if (!up.length) return null;
    const t = up[0];
    const spots = t.openSpots != null ? t.openSpots
      : (t.capacity != null ? t.capacity - (t.reservedSpots || 0) : null);
    return { tripLength: t.tripLength, departureAt: t.departureAt, price: t.price, spots };
  }

  function fmtDep(iso) {
    return new Date(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }

  function DeltaCell({ pct }) {
    if (pct == null) return <span className="th-delta muted">—</span>;
    const up = pct >= 0;
    return (
      <span className={`th-delta ${up ? 'up' : 'down'}`}>
        {up ? '▲ +' : '▼ −'}{Math.abs(pct)}%
      </span>
    );
  }

  // ── Trend bars (shared: band + expanded rows) ─────────────────────────────
  function TrendBars({ bars, height }) {
    const max = Math.max(0.01, ...bars.map(b => (b.val == null ? 0 : b.val)));
    return (
      <div className="th-bars" style={{ height }}>
        {bars.map((b, i) => (
          <span key={i}
                className={`th-bar${b.today ? ' today' : ''}${b.val == null ? ' empty' : ''}`}
                style={{ height: b.val == null ? 2 : Math.max(3, Math.round((b.val / max) * height)) }}/>
        ))}
      </div>
    );
  }

  // ── Conditions + fleet trend band ─────────────────────────────────────────
  function ConditionsBand({ trend }) {
    const fc = window.SD && window.SD.FORECAST && window.SD.FORECAST.today;
    const sstRaw = fc && (fc.sst_offshore != null ? fc.sst_offshore : fc.sst_nearshore);
    const sstF = sstRaw != null ? Math.round(sstRaw) : null;
    const windKt = fc && fc.wind_speed != null ? Math.round(fc.wind_speed) : null;
    const windDir = (fc && fc.wind_direction) || '';
    const moonPct = fc && fc.moon_phase != null ? Math.round(fc.moon_phase) : null;
    const moonName = (fc && fc.moon_phase_name) || null;
    const label = (fc && fc.conditions_label) || null;
    const summary = (fc && fc.summary) || null;

    return (
      <div className="th-condband">
        <div className="th-cond-left">
          <div className="th-cond-toprow">
            {label && <span className="th-rating-chip">{label}</span>}
            {summary && <span className="th-cond-summary">{summary}</span>}
          </div>
          <div className="th-cond-stats">
            <span><b>{sstF != null ? `${sstF}°F` : '—'}</b> water</span>
            <span><b>{windKt != null ? `${windKt} kt ${windDir}` : '—'}</b> wind</span>
            <span><b>{moonPct != null ? `${moonPct}%` : '—'}</b> moon{moonName ? ` · ${moonName.toLowerCase()}` : ''}</span>
          </div>
        </div>
        <div className="th-cond-trend">
          <div className="th-trend-head">
            <span className="th-lbl">Fleet catch rate · last 30 days</span>
            {trend.today != null && (
              <span className={`th-trend-val ${trend.pct != null && trend.pct >= 0 ? 'up' : 'down'}`}>
                {fmt.tpa(trend.today)} fish per angler
                {trend.pct != null && ` · ${trend.pct >= 0 ? '▲' : '▼'} ${Math.abs(trend.pct)}% ${trend.pct >= 0 ? 'above' : 'below'} average`}
              </span>
            )}
          </div>
          <TrendBars bars={trend.days.map(d => ({ val: d.val, today: d.date === trend.days[29].date }))} height={36}/>
        </div>
      </div>
    );
  }

  // ── Expandable counts table ───────────────────────────────────────────────
  function CountsSection({ navigate, settings, regions }) {
    const TODAY = getTodayISO();
    const [openBoat, setOpenBoat] = useState(null);
    const [landing, setLanding] = useState('all');

    const allTrips = useMemo(() => regionTrips(regions), [regions, settings]);

    const dates = useMemo(() => {
      const set = [...new Set(allTrips.map(t => t.date))];
      return set.sort().reverse();
    }, [allTrips]);
    const [selectedDate, setSelectedDate] = useState(
      () => (dates.includes(TODAY) ? TODAY : (dates[0] || TODAY))
    );
    const dateIdx = dates.indexOf(selectedDate);
    const isToday = selectedDate === TODAY;

    const ratingData = useMemo(() => SDA.fishingRating(selectedDate, regions), [selectedDate, regions, settings]);
    const returned = isToday ? ratingData.boats.filter(b => !b.isPreliminary) : ratingData.boats;

    const landings = useMemo(() => {
      const eff = window.getEffectiveRegion ? window.getEffectiveRegion(regions) : 'san_diego';
      return (window.getLandingsForRegion && window.getLandingsForRegion(eff)) || [];
    }, [regions]);

    const visible = returned.filter(b => landing === 'all' || b.landing === landing);

    const totals = useMemo(() => {
      const out = { total: 0, Bluefin: 0, Yellowfin: 0, Yellowtail: 0, Dorado: 0 };
      visible.forEach(b => TH_TROPHY.forEach(sp => { out[sp] += b[sp] || 0; out.total += b[sp] || 0; }));
      return out;
    }, [visible]);

    const trend = useMemo(() => fleetTrend(allTrips, selectedDate), [allTrips, selectedDate]);

    // Season rank map (current year, min 5 trips)
    const rankMap = useMemo(() => {
      const year = String(window.TT_DATES.getPacificYear());
      const yearTrips = allTrips.filter(t => String(t.year) === year);
      const { rows } = SDA.boatLeaderboard(yearTrips, 'all', 5);
      const m = {};
      rows.forEach((r, i) => { m[r.boat] = { rank: i + 1, total: rows.length, trips: r.tripCount, best: r.bestTrip }; });
      return m;
    }, [allTrips]);

    const seasonLeaders = useMemo(() => {
      const trips = SDA.filterTrips(DEFAULT_FILTERS, regions);
      const { rows } = SDA.boatLeaderboard(trips, 'all', 5);
      return rows.filter(r => r.tripCount >= 5).slice(0, 4);
    }, [regions, settings]);

    const stillFishing = isToday ? ((window.SD && window.SD.TODAY && window.SD.TODAY.stillFishing) || []) : [];
    const topTrip = useMemo(() => (SDA.computeTopTripToBook && SDA.computeTopTripToBook()) || null, [settings]);

    return (
      <React.Fragment>
        <ConditionsBand trend={trend}/>

        <div className="th-wrap">
          {/* Title row: date stepper + landing chips */}
          <div className="th-titlerow">
            <h2 className="th-title">{isToday ? "Today's counts" : 'Counts'}</h2>
            <div className="th-datestep">
              <button aria-label="Earlier day" disabled={dateIdx >= dates.length - 1}
                      onClick={() => { setSelectedDate(dates[dateIdx + 1]); setOpenBoat(null); }}>‹</button>
              <span>{fmtDayLabel(selectedDate)}</span>
              <button aria-label="Later day" disabled={dateIdx <= 0}
                      onClick={() => { setSelectedDate(dates[dateIdx - 1]); setOpenBoat(null); }}>›</button>
            </div>
            <div className="th-spacer"/>
            <div className="th-chiprow">
              <button className={`th-chip${landing === 'all' ? ' on' : ''}`}
                      onClick={() => { setLanding('all'); setOpenBoat(null); }}>All</button>
              {landings.map(l => (
                <button key={l} className={`th-chip${landing === l ? ' on' : ''}`}
                        onClick={() => { setLanding(l); setOpenBoat(null); }}>{thShort(l)}</button>
              ))}
            </div>
          </div>

          {/* Species totals */}
          <div className="th-totals">
            <div className="th-total"><b>{fmt.n(totals.total)}</b><span>total fish</span></div>
            <div className="th-total"><b>{fmt.n(totals.Bluefin)}</b><span>bluefin</span></div>
            <div className="th-total"><b>{fmt.n(totals.Yellowtail)}</b><span>yellowtail</span></div>
            <div className="th-total"><b>{fmt.n(totals.Yellowfin)}</b><span>yellowfin</span></div>
            <div className="th-total"><b>{fmt.n(totals.Dorado)}</b><span>dorado</span></div>
            <div className="th-spacer"/>
            <div className="th-totals-note">{visible.length} boat{visible.length === 1 ? '' : 's'} reported · Click any boat for its recent history &amp; next departure</div>
          </div>

          {/* Table + rail */}
          <div className="th-grid">
            <div className="th-table">
              <div className="th-thead">
                <span/><span>Boat</span><span>Trip</span><span>Catch</span>
                <span className="r">Anglers</span><span className="r">Total</span>
                <span className="r">Fish/Angler</span><span className="r">Vs usual</span>
              </div>
              {visible.length === 0 && (
                <div className="th-empty">{isToday ? 'No reports yet today — check back later.' : 'No reports for this date.'}</div>
              )}
              {visible.map((b) => {
                const total = TH_TROPHY.reduce((s, sp) => s + (b[sp] || 0), 0);
                const fa = b.anglers > 0 ? total / b.anglers : 0;
                const pct = boatDelta(b, allTrips, selectedDate);
                const key = `${b.boat}|${b.landing}`;
                const open = openBoat === key;
                const hist = open ? boatHistory(b, allTrips, selectedDate) : null;
                const rank = rankMap[b.boat];
                const dep = open ? nextDeparture(b.boat) : null;
                return (
                  <div key={key} className={`th-rowwrap${open ? ' open' : ''}`}>
                    <div className="th-row" onClick={() => setOpenBoat(open ? null : key)}>
                      <span className={`th-chev${open ? ' on' : ''}`}>{open ? '▾' : '▸'}</span>
                      <span className="th-boat"><b>{b.boat}</b><i>{thShort(b.landing)}</i></span>
                      <span className="th-trip">{b.tripLength}</span>
                      <span className="th-catch">{thCatchLine(b)}</span>
                      <span className="r th-num muted">{fmt.n(b.anglers)}</span>
                      <span className="r th-num total">{fmt.n(total)}</span>
                      <span className="r th-num">{fa.toFixed(2)}</span>
                      <span className="r"><DeltaCell pct={pct}/></span>
                    </div>
                    {open && (
                      <div className="th-expand">
                        <div className="th-expand-hist">
                          <div className="th-expand-histhead">
                            <span className="th-lbl">Last 10 same-length trips · fish per angler</span>
                            {hist.avg != null && <span className="th-usually">usually <b>{hist.avg.toFixed(2)}</b></span>}
                          </div>
                          <TrendBars bars={hist.bars} height={40}/>
                          <div className="th-expand-axis"><span>{fmtDayLabel(hist.startDate)}</span><span>{isToday ? 'TODAY' : fmtDayLabel(selectedDate)}</span></div>
                          <div className="th-expand-stats">
                            {rank && <span>Season rank <b>#{rank.rank} of {rank.total}</b></span>}
                            {rank && <span>Trips <b>{rank.trips}</b></span>}
                          </div>
                        </div>
                        <div className="th-expand-dep">
                          <span className="th-lbl">Next departure</span>
                          {dep ? (
                            <React.Fragment>
                              <div className="th-dep-line">{dep.tripLength} · {fmtDep(dep.departureAt)}{dep.price ? ` · $${dep.price}` : ''}</div>
                              {dep.spots != null && <div className="th-dep-spots">{dep.spots} spots left</div>}
                            </React.Fragment>
                          ) : (
                            <div className="th-dep-line muted">No upcoming trips listed</div>
                          )}
                          <div className="th-expand-cta">
                            <button className="th-btn primary" onClick={(e) => { e.stopPropagation(); navigate('tripplanner'); }}>Book →</button>
                            <button className="th-btn" onClick={(e) => { e.stopPropagation(); navigate('boat', { boat: b.boat }); }}>Boat page</button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              <div className="th-foot">
                <span>“Vs usual” compares this trip’s catch rate to the boat’s own same-length trips over the last 30 days.</span>
                <div className="th-spacer"/>
                <button className="th-link" onClick={() => navigate('analytics', { subtab: 'overview' })}>Full season analytics →</button>
              </div>
            </div>

            <div className="th-rail">
              <div className="th-card">
                <div className="th-card-head"><span className="th-lbl">Season leaders</span><span className="th-lbl-soft">fish per angler, per day</span></div>
                {seasonLeaders.map((b, i) => (
                  <div key={b.boat} className="th-leader" onClick={() => navigate('boat', { boat: b.boat })}>
                    <span className="th-leader-rank">{i + 1}</span>
                    <span className="th-leader-info"><b>{b.boat}</b><i>{thShort(b.landing)} · {b.tripCount} trips</i></span>
                    <span className="th-leader-val">{fmt.tpa(b.avgTPAPerDay)}</span>
                  </div>
                ))}
              </div>

              {stillFishing.length > 0 && (
                <div className="th-card">
                  <div className="th-card-head"><span className="th-lbl">Still fishing</span></div>
                  {stillFishing.map((t, i) => {
                    const parts = Object.entries(t.catch || {}).filter(([, n]) => n > 0).map(([sp, n]) => `${n} ${sp}`);
                    return (
                      <div key={i} className="th-sf">
                        <span><b>{t.boat}</b><i>{thShort(t.landing)} · {t.tripLength}</i></span>
                        <span className="th-sf-catch">{parts.join(', ') || 'No count yet'}</span>
                      </div>
                    );
                  })}
                </div>
              )}

              {topTrip && (
                <div className="th-card book">
                  <span className="th-lbl light">Top trip to book</span>
                  <div className="th-book-boat">{topTrip.boat} · {topTrip.tripLength}</div>
                  <div className="th-book-meta">
                    {topTrip.departureAt ? `Departs ${fmtDep(topTrip.departureAt)}` : ''}
                    {topTrip.price ? ` · $${topTrip.price}` : ''}
                    {topTrip.openSpots != null ? ` · ${topTrip.openSpots} spots` : ''}
                  </div>
                  <button className="th-btn primary" onClick={() => navigate('tripplanner')}>Book this trip →</button>
                </div>
              )}
            </div>
          </div>
        </div>
      </React.Fragment>
    );
  }

  // ── Redesigned home ───────────────────────────────────────────────────────
  function HomeViewV2({ navigate, settings, regions }) {
    if (!window.SD_PROC_TRIPS) SDA.preprocessTrips(settings);
    const totalTrips = (window.SD && window.SD.META && window.SD.META.tripCount) || 0;
    const tripDisplay = (Math.floor(totalTrips / 100) * 100).toLocaleString() + '+';

    return (
      <React.Fragment>
        {/* Hero — unchanged markup/classes so existing ch-hero CSS + image apply */}
        <section className="ch-hero">
          <div className="ch-hero-in">
            <div className="ch-kick">★ San Diego's #1 Sportfishing Analytics</div>
            <h1 className="ch-h1">Stop guessing.<br/>Start catching.</h1>
            <p className="ch-by">
              See who's catching, compare fish counts, and book your next trip — every sportboat, in one place.{' '}
              <b>Trusted by {tripDisplay} trips since 2015.</b>
            </p>
          </div>
        </section>

        <CountsSection navigate={navigate} settings={settings} regions={regions}/>

        {/* Community + Reddit stay, but below the fold */}
        <div className="th-wrap th-below">
          <WeeklySummaryWidget/>
          <HotspotsWidget/>
          <CommunityReportsWidget/>
        </div>

        <footer className="ch-foot">
          <div className="ch-foot-in">
            <b>The Tuna Tracker</b>
            <span>· San Diego sportfishing analytics · H&amp;M · Fisherman's · Seaforth · Point Loma</span>
          </div>
        </footer>
      </React.Fragment>
    );
  }

  // Mobile bottom nav (≤720px). Rendered by HomeViewV2's host page via CSS-fixed bar.
  function BottomNav({ navigate, active }) {
    const items = [
      { id: 'home', label: 'Today' },
      { id: 'forecast', label: 'Forecast' },
      { id: 'charts', label: 'Charts' },
      { id: 'boats', label: 'Boats' },
      { id: 'tripplanner', label: 'Plan' },
    ];
    return (
      <nav className="th-bottomnav">
        {items.map(it => (
          <button key={it.id} className={active === it.id ? 'on' : ''} onClick={() => navigate(it.id)}>
            <span className="th-bn-dot"/>
            {it.label}
          </button>
        ))}
      </nav>
    );
  }

  // Override the home view. (Remove HomeView from dashboard.jsx once verified.)
  Object.assign(window, { HomeView: HomeViewV2, THBottomNav: BottomNav });
})();
