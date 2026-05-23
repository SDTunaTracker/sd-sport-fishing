// Dashboard — Today's Catch (with date picker) + Current Year Leaderboard
const { useMemo, useState: useS } = React;

const TODAY_ISO = new Date().toISOString().slice(0, 10);

function fmtDate(iso) {
  const [y, m, d] = iso.split('-');
  return `${+m}/${+d}/${String(+y).slice(-2)}`;
}

function TodayCatch({ navigate, settings }) {
  // All dates with trip data, newest first.
  const dates = useMemo(() => {
    const raw = window.SD_PROC_TRIPS || window.SD.TRIPS;
    const set = [...new Set(raw.map(t => t.date))];
    return set.sort().reverse();
  }, [settings]);

  const [selectedDate, setSelectedDate] = useS(
    () => dates.includes(TODAY_ISO) ? TODAY_ISO : (dates[0] || TODAY_ISO)
  );

  // Trips for selected date, sorted by trophyPerAnglerPerDay desc.
  const dateTrips = useMemo(() => {
    const raw = window.SD_PROC_TRIPS || window.SD.TRIPS;
    return raw
      .filter(t => t.date === selectedDate)
      .slice()
      .sort((a, b) => (b.trophyPerAnglerPerDay || 0) - (a.trophyPerAnglerPerDay || 0));
  }, [selectedDate, settings]);

  const summary = useMemo(() => ({
    trophyCount: dateTrips.reduce((s, t) => s + (t.totalTuna || 0), 0),
    anglers:     dateTrips.reduce((s, t) => s + t.anglers, 0),
    Bluefin:     dateTrips.reduce((s, t) => s + (t.Bluefin || 0), 0),
    Yellowfin:   dateTrips.reduce((s, t) => s + (t.Yellowfin || 0), 0),
    Yellowtail:  dateTrips.reduce((s, t) => s + (t.Yellowtail || 0), 0),
    Dorado:      dateTrips.reduce((s, t) => s + (t.Dorado || 0), 0),
  }), [dateTrips]);

  const isToday = selectedDate === TODAY_ISO;
  const scrape = window.SD?.META?.lastScrape;
  const timeStr = isToday && scrape
    ? ` · as of ${new Date(scrape).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`
    : '';

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
          <div className="today-head"><i className="fa-solid fa-fish-fins"></i> Today's Catch</div>
          <div className="today-date">{fmtDate(selectedDate)}{timeStr}</div>
        </div>

        {/* Date picker */}
        <div style={{display:'flex', alignItems:'center'}}>
          <select value={selectedDate} onChange={e => setSelectedDate(e.target.value)}
                  style={{font:'500 12px/16px var(--ss-font-sans)', padding:'5px 10px',
                          borderRadius:6, border:'1px solid var(--ss-border)',
                          background:'var(--ss-surface)', color:'var(--ss-ink)', cursor:'pointer'}}>
            {dates.map(dt => (
              <option key={dt} value={dt}>{fmtDate(dt)}{dt === TODAY_ISO ? ' (today)' : ''}</option>
            ))}
          </select>
        </div>

        <div className="today-stats">
          <div className="today-stat">
            <span className="ts-val">{fmt.n(summary.trophyCount)}</span>
            <span className="ts-lbl">tuna</span>
          </div>
          <div className="today-stat">
            <span className="ts-val">{fmt.n(summary.anglers)}</span>
            <span className="ts-lbl">anglers</span>
          </div>
          <div className="today-stat">
            <span className="ts-val">{fmt.n(dateTrips.length)}</span>
            <span className="ts-lbl">boats</span>
          </div>
        </div>

        <div className="today-species">
          {activeSpecies.map(s => (
            <div key={s.key} className="today-sp">
              <span className="sp-dot" style={{background: s.color}}></span>
              <span className="sp-name">{s.key}</span>
              <span className="sp-val">{fmt.n(summary[s.key])}</span>
            </div>
          ))}
        </div>
      </div>

      {dateTrips.length === 0 ? (
        <div style={{padding:'32px 0', textAlign:'center',
                     color:'var(--ss-slate)', font:'400 14px/20px var(--ss-font-sans)'}}>
          {isToday ? 'No reports yet today — check back later.' : 'No reports for this date.'}
        </div>
      ) : (
        <Panel title="Today's Report" meta="Sorted by tuna per angler per day">
          <div className="today-boat-row today-boat-hd">
            <span>Boat</span>
            <span>Landing</span>
            <span>Trip</span>
            <span style={{color: SPECIES_COLORS.Bluefin}}>Bluefin</span>
            <span style={{color: SPECIES_COLORS.Yellowfin}}>Yellowfin</span>
            <span style={{color: SPECIES_COLORS.Yellowtail}}>Yellowtail</span>
            <span style={{color: SPECIES_COLORS.Dorado}}>Dorado</span>
            <span>Anglers</span>
            <span>TPA/Day</span>
          </div>
          {dateTrips.map((b, i) => (
            <div key={i} className="today-boat-row" style={{cursor:'pointer'}}
                 onClick={() => navigate('boat', { boat: b.boat })}>
              <span style={{font:'600 12px/16px var(--ss-font-sans)', color:'var(--tb-ink)'}}>{b.boat}</span>
              <span>{b.landing.replace(' Sportfishing','').replace(' Landing','')}</span>
              <span>{b.tripLength}</span>
              <span style={{fontWeight: b.Bluefin > 0 ? 600 : 400, color: b.Bluefin > 0 ? SPECIES_COLORS.Bluefin : 'var(--tb-gray-3)'}}>{fmt.n(b.Bluefin)}</span>
              <span style={{fontWeight: b.Yellowfin > 0 ? 600 : 400, color: b.Yellowfin > 0 ? SPECIES_COLORS.Yellowfin : 'var(--tb-gray-3)'}}>{fmt.n(b.Yellowfin)}</span>
              <span style={{fontWeight: b.Yellowtail > 0 ? 600 : 400, color: b.Yellowtail > 0 ? SPECIES_COLORS.Yellowtail : 'var(--tb-gray-3)'}}>{fmt.n(b.Yellowtail)}</span>
              <span style={{fontWeight: b.Dorado > 0 ? 600 : 400, color: b.Dorado > 0 ? SPECIES_COLORS.Dorado : 'var(--tb-gray-3)'}}>{fmt.n(b.Dorado)}</span>
              <span>{fmt.n(b.anglers)}</span>
              <span style={{fontWeight:700, color: i === 0 ? 'var(--ss-orange-500)' : 'var(--tb-ink)'}}>{fmt.tpa(b.trophyPerAnglerPerDay)}</span>
            </div>
          ))}
        </Panel>
      )}
    </Fragment>
  );
}

function Dashboard({ navigate, settings }) {
  const currentYear = String(new Date().getFullYear());

  const yearTrips = useMemo(
    () => SDA.filterTrips({ ...DEFAULT_FILTERS, year: currentYear }),
    [settings]
  );

  const { rows: leaderboard, fleetMedianTPAPerDay } = useMemo(
    () => SDA.boatLeaderboard(yearTrips, 'all', 5),
    [yearTrips]
  );

  const topBoats = leaderboard.slice(0, 10);
  const maxTPAPerDay = topBoats[0]?.avgTPAPerDay || 1;

  return (
    <Fragment>
      <div className="pagehead">
        <div>
          <h1>San Diego Sportfishing — Tuna Tracker</h1>
        </div>
      </div>

      <TodayCatch navigate={navigate} settings={settings}/>

      <div style={{marginTop: 20}}>
        <Panel title={`Top Boats — ${currentYear} Season`}
               meta="Ranked by avg tuna/angler/day · min 5 trips"
               actions={<button className="btn sm ghost" onClick={() => navigate('analytics')}>Full Analytics →</button>}>
          {topBoats.length === 0 ? (
            <div className="muted-block">No data yet for {currentYear}.</div>
          ) : (
            <Fragment>
              <div className="chart-legend" style={{marginBottom: 8}}>
                <span className="median-mark"><span className="line"></span>Fleet median ({fmt.tpa(fleetMedianTPAPerDay)})</span>
              </div>
              <div style={{position: 'relative'}}>
                {topBoats.map((b, i) => {
                  const wpct = (b.avgTPAPerDay / maxTPAPerDay) * 100;
                  const medLinePct = (fleetMedianTPAPerDay / maxTPAPerDay) * 100;
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
                      <div className="track" style={{position: 'relative'}}>
                        <div className="fill" style={{width: `${wpct}%`}}></div>
                        <div style={{position:'absolute', left:`${medLinePct}%`, top:-2, bottom:-2, width:0, borderLeft:'1.5px dashed #445460'}}></div>
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

Object.assign(window, { Dashboard });
