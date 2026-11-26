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

  // Headline metric for the page being rendered (SDA.metricFor). San Diego:
  // trophy fish (TH_TROPHY) and the exported trophyPerAnglerPerDay, exactly as
  // before. OC/LA: every landed species (owner decision D1). Set at the top of
  // each counts component's render via thUseMetric(regions, settings).
  let THM = null;
  function thUseMetric(regions, settings) {
    const eff = window.getEffectiveRegion ? window.getEffectiveRegion(regions) : 'san_diego';
    THM = (window.SDA && SDA.metricFor) ? SDA.metricFor(eff, settings) : null;
    return THM || { allSpecies: false };
  }
  const thAll = () => !!(THM && THM.allSpecies);
  // Target species the visitor picked in Settings (null = the default four).
  const thCustom = () => (THM && THM.species && THM.noun === 'target fish') ? THM.species : null;
  const thSpecies = () => thCustom() || TH_TROPHY;
  const thFish = (t) => thAll() ? SDA.allFish(t) : thSpecies().reduce((s, sp) => s + SDA.speciesCount(t, sp), 0);
  const thRate = (t) => (thAll() || thCustom()) ? THM.rate(t) : (t.trophyPerAnglerPerDay || 0);
  // [species, count] pairs with fish, biggest first.
  function thSpeciesList(t) {
    if (!thAll()) return thSpecies().map(sp => [sp, SDA.speciesCount(t, sp)]).filter(x => x[1] > 0);
    const c = SDA.catchBySpecies(t);
    return Object.keys(c).map(sp => [sp, c[sp]]).sort((a, b) => b[1] - a[1]);
  }
  // Totals over a list of trips: {total, trophy, bySp: {species: n}, ranked: [[sp, n]...]}
  function thTotals(list) {
    const out = { total: 0, trophy: 0, bySp: {} };
    list.forEach(b => {
      thSpeciesList(b).forEach(([sp, n]) => { out.bySp[sp] = (out.bySp[sp] || 0) + n; out.total += n; });
      out.trophy += TH_TROPHY.reduce((s, sp) => s + (b[sp] || 0), 0);
    });
    out.ranked = Object.keys(out.bySp).map(sp => [sp, out.bySp[sp]]).sort((a, b) => b[1] - a[1]);
    return out;
  }

  // Full species names — no acronyms (BFT/YT read as jargon to casual users).
  // All-species pages list the top three species and how many more.
  function thCatchLine(t) {
    const list = thSpeciesList(t);
    if (!list.length) return thAll() ? 'No fish reported' : 'No trophy fish';
    const shown = thAll() ? list.slice(0, 3) : list;
    const parts = shown.map(([sp, n]) => `${n} ${sp}`);
    if (list.length > shown.length) parts.push(`+${list.length - shown.length} more`);
    return parts.join(' · ');
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
    ).map(thRate);
    if (hist.length < 3) return null;
    const avg = hist.reduce((a, b) => a + b, 0) / hist.length;
    if (avg <= 0) return null;
    return Math.round(((thRate(trip) - avg) / avg) * 100);
  }

  // Daily fleet avg trophy/angler/day for the 30 days ending on selectedDate.
  function fleetTrend(allTrips, selectedDate) {
    const byDate = {};
    const cutoff = isoMinus(selectedDate, 29);
    allTrips.forEach(t => {
      if (t.date >= cutoff && t.date <= selectedDate) {
        (byDate[t.date] || (byDate[t.date] = [])).push(thRate(t));
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
    const bars = past.map(t => ({ val: thRate(t), today: false, date: t.date }));
    bars.push({ val: thRate(trip), today: true, date: selectedDate });
    const avg = past.length
      ? past.reduce((s, t) => s + thRate(t), 0) / past.length : null;
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
    return new Date(iso).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'America/Los_Angeles' });
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
  // San Diego-only inputs: the forecast/conditions model is SD-offshore R&D
  // (60-Mile Bank, Cortez…) and the schedule feed covers SD landings only.
  // For an OC/LA-only view we hide them rather than show San Diego numbers.
  function isOclaOnly(regions) {
    return !!(regions && window.getEffectiveRegion && window.getEffectiveRegion(regions) === 'oc_la');
  }
  function regionLandingList(regions) {
    if (!regions || !window.getEffectiveRegion || !window.getLandingsForRegion) return null;
    return window.getLandingsForRegion(window.getEffectiveRegion(regions));
  }

  function ConditionsBand({ trend, regions }) {
    const fc = isOclaOnly(regions) ? null : (window.SD && window.SD.FORECAST && window.SD.FORECAST.today);
    const sstRaw = fc && (fc.sst_nearshore != null ? fc.sst_nearshore : fc.sst_offshore);
    const sstF = sstRaw != null ? Math.round(sstRaw) : null;
    const windKt = fc && fc.wind_speed != null ? Math.round(fc.wind_speed) : null;
    const windDir = (fc && fc.wind_direction) || '';
    const moonPct = fc && fc.moon_phase != null ? Math.round(fc.moon_phase) : null;
    const moonName = (fc && fc.moon_phase_name) || null;
    const label = (fc && fc.conditions_label) || null;
    const summary = (fc && fc.summary) || null;

    return (
      <div className="th-condband">
        {fc && <div className="th-cond-left">
          <div className="th-cond-toprow">
            {label && <span className="th-rating-chip">{label}</span>}
            {summary && <span className="th-cond-summary">{summary}</span>}
          </div>
          <div className="th-cond-stats">
            <span><b>{sstF != null ? `${sstF}°F` : '—'}</b> water</span>
            <span><b>{windKt != null ? `${windKt} kt ${windDir}` : '—'}</b> wind</span>
            <span><b>{moonPct != null ? `${moonPct}%` : '—'}</b> moon{moonName ? ` · ${moonName.toLowerCase()}` : ''}</span>
          </div>
        </div>}
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
    const metric = thUseMetric(regions, settings);
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

    const totals = useMemo(() => thTotals(visible), [visible, metric.allSpecies, settings]);

    const trend = useMemo(() => fleetTrend(allTrips, selectedDate), [allTrips, selectedDate, metric.allSpecies, settings]);

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

    const stillFishing = (isToday ? ((window.SD && window.SD.TODAY && window.SD.TODAY.stillFishing) || []) : [])
      .filter(t => { const rl = regionLandingList(regions); return !rl || rl.includes(t.landing); });
    const topTrip = useMemo(() => (SDA.computeTopTripToBook && SDA.computeTopTripToBook(regionLandingList(regions))) || null, [settings, regions]);

    return (
      <React.Fragment>
        <ConditionsBand trend={trend} regions={regions}/>

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
            {metric.allSpecies ? (
              <React.Fragment>
                <div className="th-total"><b>{fmt.n(totals.trophy)}</b><span>trophy fish</span></div>
                {totals.ranked.slice(0, 4).map(([sp, n]) => (
                  <div key={sp} className="th-total"><b>{fmt.n(n)}</b><span>{sp.toLowerCase()}</span></div>
                ))}
              </React.Fragment>
            ) : (thCustom() || ['Bluefin', 'Yellowtail', 'Yellowfin', 'Dorado']).map(sp => (
              <div key={sp} className="th-total"><b>{fmt.n(totals.bySp[sp] || 0)}</b><span>{sp.toLowerCase()}</span></div>
            ))}
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
                const total = thFish(b);
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

  // ── Today's report (v2) ───────────────────────────────────────────────────
  // Calm, data-first page: the date is the title, one sentence summarises the
  // day, species totals are a quiet strip (zero species hidden), then a ranked
  // boat list. Reuses the counts helpers above so "vs usual", the fleet trend
  // and the expandable row details match Home exactly. No season leaderboard
  // here (it lives on Home and Analytics) — just a link to it.
  const TD2_SPECIES = { Yellowfin: '#C9A227', Bluefin: '#2F5D8A', Yellowtail: '#4F8A5B', Dorado: '#2F7F86' };

  function fmtLongDay(iso) {
    const d = new Date(iso + 'T12:00:00Z');
    return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'UTC' });
  }

  function speciesPhrase(totals) {
    const ranked = totals.ranked.map(r => r[0]);
    if (!ranked.length || !totals.total) return '';
    const top = ranked[0].toLowerCase();
    if (totals.bySp[ranked[0]] / totals.total >= 0.9) return `, almost all ${top}`;
    if (ranked.length === 1) return `, all ${top}`;
    return `, mostly ${top} and ${ranked[1].toLowerCase()}`;
  }

  function TodayReport({ navigate, settings, regions }) {
    const metric = thUseMetric(regions, settings);
    const TODAY = getTodayISO();
    const [openBoat, setOpenBoat] = useState(null);
    const [landing, setLanding] = useState('all');

    const allTrips = useMemo(() => regionTrips(regions), [regions, settings]);
    const dates = useMemo(() => [...new Set(allTrips.map(t => t.date))].sort().reverse(), [allTrips]);
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

    // Ranked by fish per angler (the region's headline fish), highest first.
    const visible = useMemo(() => returned
      .filter(b => landing === 'all' || b.landing === landing)
      .map(b => {
        const total = thFish(b);
        return { b, total, fa: b.anglers > 0 ? total / b.anglers : 0 };
      })
      .sort((x, y) => y.fa - x.fa), [returned, landing, metric.allSpecies, settings]);

    const totals = useMemo(() => thTotals(visible.map(v => v.b)), [visible, metric.allSpecies, settings]);

    const trend = useMemo(() => fleetTrend(allTrips, selectedDate), [allTrips, selectedDate, metric.allSpecies, settings]);
    const rankMap = useMemo(() => {
      const year = String(window.TT_DATES.getPacificYear());
      const { rows } = SDA.boatLeaderboard(allTrips.filter(t => String(t.year) === year), 'all', 5);
      const m = {};
      rows.forEach((r, i) => { m[r.boat] = { rank: i + 1, total: rows.length, trips: r.tripCount }; });
      return m;
    }, [allTrips]);

    const stillFishing = (isToday ? ((window.SD && window.SD.TODAY && window.SD.TODAY.stillFishing) || []) : [])
      .filter(t => { const rl = regionLandingList(regions); return !rl || rl.includes(t.landing); });
    const topTrip = useMemo(() => (SDA.computeTopTripToBook && SDA.computeTopTripToBook(regionLandingList(regions))) || null, [settings, regions]);

    const fc = isOclaOnly(regions) ? null : (window.SD && window.SD.FORECAST && window.SD.FORECAST.today);
    // The forecast label can carry an emoji prefix (e.g. "⬆️ Excellent"); keep the words only.
    const condLabel = fc && fc.conditions_label
      ? (String(fc.conditions_label).replace(/[^A-Za-z\s-]/g, '').trim().toLowerCase() || null) : null;
    const condSummary = fc && fc.summary ? fc.summary : null;

    const lastScrape = window.SD && window.SD.META && window.SD.META.lastScrape;
    const updated = lastScrape ? new Date(lastScrape).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/Los_Angeles',
    }) : null;

    const regionLabel = (regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego';
    const boatsN = visible.length;
    const step = (i) => { setSelectedDate(dates[i]); setOpenBoat(null); };

    return (
      <div className="td2">
        <p className="td2-eyebrow">{isToday ? "Today's report" : 'Daily report'} · {regionLabel}</p>
        <div className="td2-head">
          <h1 className="td2-title">{fmtLongDay(selectedDate)}</h1>
          <div className="td2-step">
            <button aria-label="Earlier day" disabled={dateIdx >= dates.length - 1} onClick={() => step(dateIdx + 1)}>‹</button>
            <button aria-label="Later day" disabled={dateIdx <= 0} onClick={() => step(dateIdx - 1)}>›</button>
          </div>
          {updated && <span className="td2-asof">Updated {updated}</span>}
        </div>

        <p className="td2-lede">
          {boatsN === 0
            ? (isToday ? 'No boats have reported yet today. Counts usually arrive in the afternoon.' : 'No boats reported on this day.')
            : (<React.Fragment>
                <strong>{boatsN} boat{boatsN === 1 ? '' : 's'} brought in {fmt.n(totals.total)} fish</strong>{speciesPhrase(totals)}.
                {landing === 'all' && trend.today != null && (
                  <React.Fragment>
                    {' '}The fleet averaged {fmt.tpa(trend.today)} fish per angler
                    {trend.pct != null && (
                      <React.Fragment>, <span className={trend.pct >= 0 ? 'td2-up' : 'td2-down'}>{Math.abs(trend.pct)}% {trend.pct >= 0 ? 'above' : 'below'}</span> the last 30 days</React.Fragment>
                    )}.
                  </React.Fragment>
                )}
              </React.Fragment>)}
        </p>

        <div className="td2-strip">
          <div className="td2-stat"><b>{fmt.n(totals.total)}</b><span>total fish</span></div>
          {metric.allSpecies && (
            <div className="td2-stat"><b>{fmt.n(totals.trophy)}</b><span>trophy fish</span></div>
          )}
          {totals.ranked.slice(0, metric.allSpecies ? 4 : 99).map(([sp, n]) => (
            <div key={sp} className="td2-stat">
              <b>{fmt.n(n)}</b>
              <span>{TD2_SPECIES[sp] && <i className="td2-dot" style={{ background: TD2_SPECIES[sp] }}/>}{sp.toLowerCase()}</span>
            </div>
          ))}
          {(condLabel || condSummary) && (
            <div className="td2-cond">
              {condLabel && <div>Conditions <b>{condLabel}</b></div>}
              {condSummary && <div>{condSummary}</div>}
            </div>
          )}
        </div>

        <div className="td2-grid">
          <div className="td2-main">
            <div className="td2-bar">
              <h2>Boats</h2>
              <div className="td2-chips" role="group" aria-label="Filter by landing">
                <button className={landing === 'all' ? 'on' : ''} aria-pressed={landing === 'all'}
                        onClick={() => { setLanding('all'); setOpenBoat(null); }}>All</button>
                {landings.map(l => (
                  <button key={l} className={landing === l ? 'on' : ''} aria-pressed={landing === l}
                          onClick={() => { setLanding(l); setOpenBoat(null); }}>{thShort(l)}</button>
                ))}
              </div>
            </div>

            <div className="td2-list">
              <div className="td2-row td2-thead" aria-hidden="true">
                <span/><span>Boat</span><span>Trip</span><span>Catch</span>
                <span className="r">Anglers</span><span className="r">Fish/angler</span><span className="r">Vs usual</span><span/>
              </div>
              {boatsN === 0 && <div className="td2-empty">{isToday ? 'No reports yet today.' : 'No reports for this date.'}</div>}
              {visible.map(({ b, fa }, i) => {
                const pct = boatDelta(b, allTrips, selectedDate);
                const key = `${b.boat}|${b.landing}`;
                const open = openBoat === key;
                const hist = open ? boatHistory(b, allTrips, selectedDate) : null;
                const rank = rankMap[b.boat];
                const dep = open ? nextDeparture(b.boat) : null;
                return (
                  <div key={key} className={`td2-item${open ? ' open' : ''}`}>
                    <button className="td2-row" aria-expanded={open} onClick={() => setOpenBoat(open ? null : key)}>
                      <span className="td2-rank">{i + 1}</span>
                      <span className="td2-boat"><b>{b.boat}</b><i>{thShort(b.landing)}</i></span>
                      <span className="td2-trip">{b.tripLength}</span>
                      <span className="td2-catch">{thCatchLine(b).toLowerCase()}</span>
                      <span className="td2-sub">{b.tripLength} · {thCatchLine(b).toLowerCase().replace(/ · /g, ', ')}</span>
                      <span className="r td2-num td2-ang">{fmt.n(b.anglers)}</span>
                      <span className="r td2-num td2-fa">{fa.toFixed(2)}</span>
                      <span className="r td2-vs">
                        {pct == null ? <span className="td2-muted">—</span>
                          : <span className={pct >= 0 ? 'td2-up' : 'td2-down'}>{pct >= 0 ? '▲' : '▼'} {Math.abs(pct)}%</span>}
                      </span>
                      <span className="td2-chev" aria-hidden="true">{open ? '⌃' : '›'}</span>
                    </button>
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
                            <button className="th-btn primary" onClick={() => navigate('tripplanner')}>Book →</button>
                            <button className="th-btn" onClick={() => navigate('boat', { boat: b.boat })}>Boat page</button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="td2-note">Ranked by fish per angler. “Vs usual” compares each trip with the same boat’s same-length trips over the last 30 days. Tap a boat for its recent history and next departure.</p>
          </div>

          <aside className="td2-rail">
            {stillFishing.length > 0 && (
              <div className="td2-card">
                <p className="td2-eyebrow">Still fishing</p>
                {stillFishing.map((t, j) => {
                  const parts = Object.entries(t.catch || {}).filter(([, n]) => n > 0).map(([sp, n]) => `${n} ${sp.toLowerCase()}`);
                  return (
                    <div key={j} className="td2-sf">
                      <b>{t.boat}</b> <i>{thShort(t.landing)} · {t.tripLength}</i>
                      <div>{parts.join(', ') || 'No count yet'}</div>
                    </div>
                  );
                })}
              </div>
            )}
            {topTrip && (
              <div className="td2-book">
                <p className="td2-eyebrow">Book next</p>
                <div className="td2-book-boat">{topTrip.boat} · {topTrip.tripLength}</div>
                <div className="td2-book-meta">
                  {topTrip.departureAt ? `Departs ${fmtDep(topTrip.departureAt)}` : ''}
                  {topTrip.price ? ` · $${topTrip.price}` : ''}
                  {topTrip.openSpots != null ? ` · ${topTrip.openSpots} spots left` : ''}
                </div>
                <button className="td2-book-btn" onClick={() => navigate('tripplanner')}>Book this trip →</button>
              </div>
            )}
            <button className="td2-link" onClick={() => navigate('analytics', { subtab: 'overview' })}>See the season leaderboard →</button>
          </aside>
        </div>
      </div>
    );
  }

  // ── Redesigned home ───────────────────────────────────────────────────────
  function HomeViewV2({ navigate, settings, regions }) {
    if (!window.SD_PROC_TRIPS) SDA.preprocessTrips(settings);
    const totalTrips = (window.ttRegionData ? window.ttRegionData.totalTripCount() : ((window.SD && window.SD.META && window.SD.META.tripCount) || 0));
    const tripDisplay = (Math.floor(totalTrips / 100) * 100).toLocaleString() + '+';

    return (
      <React.Fragment>
        {/* Hero — unchanged markup/classes so existing ch-hero CSS + image apply */}
        <section className="ch-hero">
          <div className="ch-hero-in">
            <div className="ch-kick">{isOclaOnly(regions) ? 'Orange County, LA & Ventura' : (regions && regions.length > 1 ? 'Southern California' : 'San Diego')} sportboat counts, ranked fairly</div>
            <h1 className="ch-h1">Stop guessing.<br/>Start catching.</h1>
            <p className="ch-by">
              See who's catching, compare fish counts, and book your next trip — every sportboat, in one place.{' '}
              <b>Trusted by data from {tripDisplay} trips.</b>
            </p>
          </div>
        </section>

        <CountsSection navigate={navigate} settings={settings} regions={regions}/>

        {/* The extra brand band that sat here repeated the site footer directly below it. */}
      </React.Fragment>
    );
  }

  // Mobile bottom nav (≤720px). Rendered by HomeViewV2's host page via CSS-fixed bar.
  function BottomNav({ navigate, active }) {
    const items = [
      { id: 'home', label: 'Today' },
      // Forecast entry removed 2026-09-06 (soft-retire); route redirects to Charts.
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
  // THCountsSection is also Today's report, so both pages share one date
  // control, one row design and the same "vs usual" comparison.
  Object.assign(window, { HomeView: HomeViewV2, THBottomNav: BottomNav, THCountsSection: CountsSection, THTodayReport: TodayReport });
})();
