// Trip Planner — Top Boats leaderboard (left) + upcoming open-party trips (right)

// Per-landing booking URL pattern. Returns null if we can't build a usable link
// (e.g. unknown landing). Discovered by inspecting the booking buttons on each
// landing's schedule page during scraper development.
function bookingUrl(s) {
  switch (s.landing) {
    case 'Point Loma Sportfishing':
      return `https://pointloma.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
    case 'Seaforth Sportfishing':
      return `https://seaforth.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
    case "Fisherman's Landing":
      return `https://fishermanslanding.fishingreservations.net/resos/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
    case 'H&M Landing': {
      // H&M's xola integration doesn't give per-trip URLs, so we link to the
      // boat page where the "Book" widget for upcoming trips lives.
      const slug = (s.boat || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
      return slug ? `https://www.hmlanding.com/boat/${slug}#tab-open-trips` : null;
    }
    default:
      return null;
  }
}
// Boat stats lookup: for each boat with any history, compute its career
// trophy/angler/day. The Trip Finder uses this to rank upcoming trips by
// expected catch-per-dollar. Computed once from window.SD.TRIPS.
function buildBoatStats() {
  const out = {};
  for (const t of (window.SD.TRIPS || [])) {
    const days = t.tripLengthDays > 0 ? t.tripLengthDays : 1;
    const s = out[t.boat] || (out[t.boat] = { trophy: 0, anglerDays: 0, trips: 0 });
    s.trophy += t.totalTuna || 0;
    s.anglerDays += (t.anglers || 0) * days;
    s.trips++;
  }
  Object.values(out).forEach(s => {
    s.avgTPAPerDay = s.anglerDays > 0 ? s.trophy / s.anglerDays : 0;
  });
  return out;
}

function TripPlanner({ filters, setFilters, navigate, tweaks }) {
  const trips = useMemo(() => SDA.filterTrips(filters), [filters]);
  const { rows: leaderboard, fleetMedianTPAPerDay } = useMemo(
    () => SDA.boatLeaderboard(trips, filters.species, filters.minTrips),
    [trips, filters.species, filters.minTrips]
  );
  const eligibleBoats = leaderboard.filter(r => r.tripCount >= filters.minTrips);
  const topBoatLimit = tweaks.density === 'compact' ? 15 : 12;
  const topBoats = eligibleBoats.slice(0, topBoatLimit);
  const maxTPAPerDay = topBoats[0]?.avgTPAPerDay || 1;

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  // Filter the schedule: only future trips that respect any relevant filters.
  // Year, Species, and Min Trips don't apply to scheduled trips (year is always
  // forward, schedule has no species data, min-trips is a leaderboard concept).
  const SEASONS = { spring: [3,4,5], summer: [6,7,8], fall: [9,10,11], winter: [12,1,2] };
  // Filter value may be 'all', a single string, or an array of strings (multi-select).
  const _matches = (val, filter) => {
    if (filter == null || filter === 'all' || filter === '') return true;
    const sel = Array.isArray(filter) ? filter : [filter];
    return sel.length === 0 || sel.map(String).includes(String(val));
  };
  const schedule = useMemo(() => {
    const now = new Date();
    const all = (window.SD.SCHEDULE || []).filter(s => {
      const dep = new Date(s.departureAt);
      if (dep < now) return false;
      if (!_matches(s.landing, filters.landing)) return false;
      if (!_matches(s.boat, filters.boat)) return false;
      if (!_matches(s.tripLength, filters.tripLength)) return false;
      if (!_matches(dep.getMonth() + 1, filters.month)) return false;
      if (filters.season && filters.season !== 'all') {
        const sel = Array.isArray(filters.season) ? filters.season : [filters.season];
        const months = sel.flatMap(s2 => SEASONS[s2] || []);
        if (months.length > 0 && !months.includes(dep.getMonth() + 1)) return false;
      }
      return true;
    });
    all.sort((a, b) => a.departureAt.localeCompare(b.departureAt));
    return all;
  }, [filters]);

  // Group by departure date so the column has subtle date dividers.
  const grouped = useMemo(() => {
    const out = [];
    let lastDate = null;
    for (const s of schedule) {
      const d = s.departureAt.slice(0, 10);
      if (d !== lastDate) {
        out.push({ kind: 'header', date: d });
        lastDate = d;
      }
      out.push({ kind: 'trip', s });
    }
    return out;
  }, [schedule]);

  const [finderOpen, setFinderOpen] = useState(false);

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Sportfish', onClick: () => navigate('today') },
        { label: 'Plan' },
        { label: 'Trip Planner' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Trip Planner</h1>
          <div className="sub">
            Top performing boats matched against {fmt.n(schedule.length)} upcoming open-party trips
          </div>
        </div>
        <div className="actions">
          <button className="btn primary" onClick={() => setFinderOpen(true)}>
            <i className="fa-solid fa-magnifying-glass-dollar"></i> Find Best Deals
          </button>
        </div>
      </div>
      <TripFinderModal open={finderOpen} onClose={() => setFinderOpen(false)}/>

      <FilterBar filters={filters} setFilters={setFilters}/>

      <div className="two-col-grid" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12}}>
        {/* LEFT: Top Boats panel (mirrors the dashboard widget) */}
        <Panel title={`Top Boats — ${speciesLabel} per Angler per Day`}
               meta={`Ranked by avg ${speciesLabel.toLowerCase()}/angler/day · min ${filters.minTrips} trips`}
               actions={<button className="btn sm ghost" onClick={() => navigate('boats')}>View All →</button>}>
          {topBoats.length === 0 ? (
            <div className="muted-block">No boats meet the minimum trip threshold for these filters.</div>
          ) : (
            <Fragment>
              <div className="chart-legend" style={{marginBottom: 8}}>
                <span className="ll"><span className="sw" style={{background: 'var(--ss-darkseagreen-500)'}}></span>Consistent / Avg performer</span>
                <span className="ll"><span className="sw" style={{background: 'var(--ss-orange-500)'}}></span>One-off spike</span>
                <span className="median-mark"><span className="line"></span>Fleet median ({fmt.tpa(fleetMedianTPAPerDay)})</span>
              </div>
              <div style={{position: 'relative'}}>
                {topBoats.map((b, i) => {
                  const wpct = (b.avgTPAPerDay / maxTPAPerDay) * 100;
                  const medLinePct = (fleetMedianTPAPerDay / maxTPAPerDay) * 100;
                  return (
                    <div key={b.boat} className={`bar-row ${b.label === 'Spike' ? 'spike' : 'consistent'}`}
                         style={{cursor: 'pointer'}}
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
                        <div style={{position:'absolute', left: `${medLinePct}%`, top:-2, bottom:-2, width:0, borderLeft:'1.5px dashed #445460'}}></div>
                        {b.label && (
                          <span className={`tag ${b.label === 'Consistent' ? 'consistent' : 'spike'}`} style={{position:'absolute', right:6, top:-2, fontSize:9}}>
                            {b.label === 'Consistent' ? 'Consistent' : 'Spike'}
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

        {/* RIGHT: Upcoming Trips */}
        <Panel title="Upcoming Open-Party Trips"
               meta={`${schedule.length} bookable · sold-out hidden · filters apply`}
               padding={false}>
          {schedule.length === 0 ? (
            <div className="muted-block" style={{padding: 16}}>
              No upcoming trips match these filters. Try clearing landing or trip-length.
            </div>
          ) : (
            <Fragment>
              {/* Column header row, sticky at the top of the scroll panel. */}
              <div style={{
                ...SCHEDULE_GRID,
                padding: '8px 12px',
                background: 'var(--ss-clay)',
                borderBottom: '1px solid var(--ss-border-2)',
                font: '700 10px/12px var(--ss-font-sans)',
                textTransform: 'uppercase', letterSpacing: '.06em',
                color: 'var(--ss-slate)',
                position: 'sticky', top: 0, zIndex: 2,
              }}>
                <span>Boat</span>
                <span style={{textAlign: 'right'}}>Depart</span>
                <span style={{textAlign: 'right'}}>Return</span>
                <span style={{textAlign: 'right'}}>Load</span>
                <span style={{textAlign: 'right'}}>Price</span>
                <span style={{textAlign: 'right'}}>Open</span>
              </div>
              <div style={{maxHeight: 720, overflow: 'auto'}}>
                {grouped.map((item, idx) => item.kind === 'header' ? (
                  <div key={`h-${item.date}`} style={{
                    padding: '6px 12px',
                    background: 'var(--tb-foam, #F5F8FA)',
                    borderTop: idx > 0 ? '1px solid var(--ss-border-2)' : 'none',
                    borderBottom: '1px solid var(--ss-border-2)',
                    font: '700 11px/14px var(--ss-font-sans)',
                    color: 'var(--ss-black)',
                  }}>
                    {fmt.date(item.date)}
                  </div>
                ) : (
                  <ScheduleRow key={`${item.s.landing}-${item.s.sourceId}`} s={item.s}/>
                ))}
              </div>
            </Fragment>
          )}
        </Panel>
      </div>
    </Fragment>
  );
}

// Shared grid template so the header row and data rows always line up.
const SCHEDULE_GRID = {
  display: 'grid',
  gridTemplateColumns: '1fr 92px 110px 50px 64px 48px',
  gap: 8,
  alignItems: 'center',
};

function fmtDateShort(d) {
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function fmtTime(d) {
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function ScheduleRow({ s }) {
  const dep = new Date(s.departureAt);
  const ret = s.returnAt ? new Date(s.returnAt) : null;
  const depStr = `${fmtDateShort(dep)} ${fmtTime(dep)}`;
  const retStr = ret ? `${fmtDateShort(ret)} ${fmtTime(ret)}` : '—';
  const price = s.price != null ? `$${s.price.toFixed(0)}` : '—';
  const load = s.capacity != null ? String(s.capacity) : '—';
  const landingShort = s.landing.replace(' Sportfishing', '').replace(' Landing', '');
  const url = bookingUrl(s);
  const boatLabel = url ? (
    <a href={url} target="_blank" rel="noopener noreferrer"
       style={{color: 'var(--ss-black)', textDecoration: 'none'}}
       onMouseEnter={e => e.currentTarget.style.color = 'var(--ss-darkseagreen-500)'}
       onMouseLeave={e => e.currentTarget.style.color = 'var(--ss-black)'}>
      {s.boat} <i className="fa-solid fa-arrow-up-right-from-square" style={{fontSize: 10, opacity: 0.5, marginLeft: 2}}></i>
    </a>
  ) : s.boat;
  return (
    <div style={{
      ...SCHEDULE_GRID,
      padding: '10px 12px',
      borderBottom: '1px solid var(--ss-border-2)',
      font: '400 12px/16px var(--ss-font-sans)',
    }}>
      <div style={{minWidth: 0}}>
        <div style={{font: '600 13px/16px var(--ss-font-sans)', color: 'var(--ss-black)'}}>{boatLabel}</div>
        <div style={{font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-slate)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>
          {s.tripLength} · {landingShort}
        </div>
      </div>
      <span style={{textAlign: 'right', fontVariantNumeric: 'tabular-nums'}}>{depStr}</span>
      <span style={{textAlign: 'right', fontVariantNumeric: 'tabular-nums'}}>{retStr}</span>
      <span style={{textAlign: 'right', color: 'var(--ss-slate)', fontVariantNumeric: 'tabular-nums'}}>{load}</span>
      <span style={{font: '600 13px/16px var(--ss-font-sans)', textAlign: 'right', fontVariantNumeric: 'tabular-nums'}}>{price}</span>
      <span style={{
        font: '600 13px/16px var(--ss-font-sans)',
        textAlign: 'right',
        color: s.openSpots <= 2 ? 'var(--ss-orange-500)' : 'var(--ss-darkseagreen-500)',
        fontVariantNumeric: 'tabular-nums',
      }}>{s.openSpots}</span>
    </div>
  );
}

// ---- Trip Finder modal ----------------------------------------------------
// Lets the user enter a target departure date range + trip lengths and shows
// a ranked list of upcoming open-party trips. Ranking metric:
//   value = (boat's career trophy/angler/day) × tripLengthDays / price
// i.e. "expected tuna caught per dollar spent". Higher = better. Boats with no
// history fall to the bottom (their value defaults to 0).

const TOMORROW_ISO = () => {
  const d = new Date(); d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
};
const PLUS_DAYS_ISO = (n) => {
  const d = new Date(); d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};

function TripFinderModal({ open, onClose }) {
  const [start, setStart] = useState(TOMORROW_ISO());
  const [end, setEnd] = useState(PLUS_DAYS_ISO(30));
  const [lengths, setLengths] = useState('all');
  const [submitted, setSubmitted] = useState(false);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Reset the "submitted" state when reopening the modal.
  useEffect(() => { if (open) setSubmitted(false); }, [open]);

  const boatStats = useMemo(buildBoatStats, []);

  const results = useMemo(() => {
    if (!submitted) return [];
    const startD = new Date(start + 'T00:00:00');
    const endD = new Date(end + 'T23:59:59');
    const selLens = Array.isArray(lengths) ? lengths : (lengths === 'all' ? [] : [lengths]);
    const out = [];
    for (const s of (window.SD.SCHEDULE || [])) {
      const dep = new Date(s.departureAt);
      if (dep < startD || dep > endD) continue;
      if (selLens.length > 0 && !selLens.includes(s.tripLength)) continue;
      const stats = boatStats[s.boat] || { avgTPAPerDay: 0, trips: 0 };
      const expected = stats.avgTPAPerDay * (s.tripLengthDays || 1);
      const valuePer$ = (s.price && s.price > 0) ? expected / s.price : 0;
      out.push({ ...s, _expected: expected, _value: valuePer$, _stats: stats });
    }
    // Rank desc by value. Boats with no history (_value=0) go to the bottom.
    out.sort((a, b) => b._value - a._value);
    return out;
  }, [submitted, start, end, lengths, boatStats]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2 style={{margin: 0, font: '600 18px/22px var(--ss-font-serif, Fraunces, serif)'}}>
              Find Best Deals
            </h2>
            <div style={{font: '400 12px/16px var(--ss-font-sans)', color: 'var(--ss-slate)', marginTop: 2}}>
              Trips ranked by expected catch per dollar — boat's historical trophy/angler/day × trip length ÷ price.
            </div>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          {/* Filter form */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr 2fr auto', gap: 12,
            alignItems: 'end', padding: '12px 16px',
            background: 'var(--ss-clay)', borderBottom: '1px solid var(--ss-border-2)',
          }}>
            <div className="filter">
              <label>Depart on or after</label>
              <input type="date" value={start} onChange={e => setStart(e.target.value)}/>
            </div>
            <div className="filter">
              <label>Depart on or before</label>
              <input type="date" value={end} onChange={e => setEnd(e.target.value)}/>
            </div>
            <div className="filter">
              <label>Trip length</label>
              <MultiSelect options={window.SD.TRIP_LENGTHS} value={lengths}
                           onChange={setLengths} allLabel="Any length"/>
            </div>
            <button className="btn primary" onClick={() => setSubmitted(true)}>
              <i className="fa-solid fa-magnifying-glass"></i> Search
            </button>
          </div>

          {/* Results */}
          {!submitted ? (
            <div className="muted-block" style={{padding: 24, textAlign: 'center'}}>
              Pick a date range and trip length(s) above, then click <b>Search</b>.
            </div>
          ) : results.length === 0 ? (
            <div className="muted-block" style={{padding: 24, textAlign: 'center'}}>
              No open-party trips match your criteria in that date range.
            </div>
          ) : (
            <Fragment>
              <div style={{
                padding: '8px 16px', borderBottom: '1px solid var(--ss-border-2)',
                font: '400 12px/16px var(--ss-font-sans)', color: 'var(--ss-slate)',
              }}>
                <b>{results.length}</b> bookable trips. Top of the list = best expected catch for the price.
              </div>
              <div style={{maxHeight: '55vh', overflowY: 'auto'}}>
                <table className="dt" style={{width: '100%'}}>
                  <thead><tr>
                    <th style={{width: 36}}>#</th>
                    <th>Boat</th>
                    <th>Trip Length</th>
                    <th>Depart</th>
                    <th>Return</th>
                    <th className="num">Price</th>
                    <th className="num">Open</th>
                    <th className="num">Boat avg/day</th>
                    <th className="num">Expected</th>
                    <th className="num">Value</th>
                  </tr></thead>
                  <tbody>
                    {results.map((s, i) => {
                      const dep = new Date(s.departureAt);
                      const ret = s.returnAt ? new Date(s.returnAt) : null;
                      const url = bookingUrl(s);
                      const fmtDate = (d) => d.toLocaleDateString([], { month: 'short', day: 'numeric' });
                      const fmtTime = (d) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
                      const valueLabel = s._value > 0 ? s._value.toFixed(4) : '—';
                      const expectedLabel = s._expected > 0 ? s._expected.toFixed(2) : '—';
                      const avgLabel = s._stats.trips > 0
                        ? `${s._stats.avgTPAPerDay.toFixed(2)} (${s._stats.trips}t)`
                        : 'no history';
                      return (
                        <tr key={`${s.landing}-${s.sourceId}`}>
                          <td><span className="rank" style={{
                            color: i < 3 ? 'var(--ss-orange-500)' : null,
                            fontWeight: i < 3 ? 700 : 500,
                          }}>{i + 1}</span></td>
                          <td>
                            {url ? (
                              <a href={url} target="_blank" rel="noopener noreferrer"
                                 style={{color: 'var(--ss-black)', textDecoration: 'none', fontWeight: 600}}>
                                {s.boat} <i className="fa-solid fa-arrow-up-right-from-square" style={{fontSize: 10, opacity: 0.5, marginLeft: 2}}></i>
                              </a>
                            ) : <b>{s.boat}</b>}
                            <div style={{font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-slate)'}}>
                              {s.landing.replace(' Sportfishing','').replace(' Landing','')}
                            </div>
                          </td>
                          <td>{s.tripLength}</td>
                          <td style={{fontVariantNumeric: 'tabular-nums'}}>{fmtDate(dep)} {fmtTime(dep)}</td>
                          <td style={{fontVariantNumeric: 'tabular-nums'}}>{ret ? `${fmtDate(ret)} ${fmtTime(ret)}` : '—'}</td>
                          <td className="num">{s.price != null ? `$${s.price.toFixed(0)}` : '—'}</td>
                          <td className="num" style={{
                            color: s.openSpots <= 2 ? 'var(--ss-orange-500)' : 'var(--ss-darkseagreen-500)',
                            fontWeight: 600,
                          }}>{s.openSpots}</td>
                          <td className="num" style={{color: 'var(--ss-slate)', fontVariantNumeric: 'tabular-nums'}}>{avgLabel}</td>
                          <td className="num" style={{fontVariantNumeric: 'tabular-nums'}}>{expectedLabel} tuna</td>
                          <td className="num" style={{
                            fontVariantNumeric: 'tabular-nums',
                            fontWeight: 600,
                            color: s._value > 0 ? 'var(--ss-darkseagreen-500)' : 'var(--ss-gray-2)',
                          }}>{valueLabel}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Fragment>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { TripPlanner, TripFinderModal });
