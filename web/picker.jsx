// Simple answers: "Pick my trip", the answers at the top of Today, and the
// Simple / Detailed switch. All ranking lives in web/trip-picker.js
// (window.TTPicker), which uses observed catch counts only.
(function () {
  const { useState, useMemo, useEffect } = React;

  const SPECIES = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];
  const BUDGETS = [
    { v: '', label: 'Any price' }, { v: '200', label: 'Under $200' }, { v: '300', label: 'Under $300' },
    { v: '500', label: 'Under $500' }, { v: '1000', label: 'Under $1,000' },
  ];
  const MODE_KEY = 'tt-view-mode';
  const TYPE_KEY = 'tt-pick-type';

  function store(k, v) {
    try { if (v === undefined) return window.localStorage.getItem(k); window.localStorage.setItem(k, v); } catch (e) {}
    return null;
  }
  function regionOf(regions) {
    return (window.getEffectiveRegion && regions) ? window.getEffectiveRegion(regions) : 'san_diego';
  }
  function money(n) { return n == null ? '' : '$' + Math.round(n).toLocaleString(); }
  function rate(x) { return x == null ? '—' : (x >= 10 ? String(Math.round(x)) : x.toFixed(1)); }
  function seatsText(n) {
    if (n == null) return null;
    return n === 1 ? '1 seat left' : n + ' seats left';
  }
  // Kicker text for multi-selected days: "Fri, Nov 27 & Sun, Nov 29" or "4 days, Nov 27–Dec 6".
  function fmtDays(days) {
    const f = d => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    if (days.length <= 2) return days.map(f).join(' & ');
    return days.length + ' days, ' + fmtRange(days[0], days[days.length - 1]);
  }
  const DAY_GRID = 21;   // three weeks of tappable days

  // Multi-select calendar for "Pick dates": tap each day you could go.
  function DayGrid({ start, days, onChange }) {
    const P = window.TTPicker;
    const all = Array.from({ length: DAY_GRID }, (_, i) => P.addDays(start, i));
    const set = new Set(days);
    const toggle = d => onChange(set.has(d) ? days.filter(x => x !== d) : [...days, d].sort());
    const weekends = all.filter(d => [0, 5, 6].includes(new Date(d + 'T12:00:00').getDay()));
    const lead = new Date(start + 'T12:00:00').getDay();   // blank cells so columns run Sun..Sat
    const mon = d => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { month: 'short' });
    return (
      <div className="pk-days">
        <div className="pk-days-head">
          <span className="pk-days-hint" aria-live="polite">{days.length ? `${days.length} day${days.length === 1 ? '' : 's'} picked` : 'Tap the days you could go'}</span>
          <span className="pk-days-acts">
            <button type="button" onClick={() => onChange(weekends)}>Weekends</button>
            {days.length > 0 && <button type="button" onClick={() => onChange([])}>Clear</button>}
          </span>
        </div>
        <div className="pk-days-grid" role="group" aria-label="Days you could go">
          {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((w, i) => <span key={'h' + i} className="pk-days-wd" aria-hidden="true">{w}</span>)}
          {Array.from({ length: lead }, (_, i) => <span key={'b' + i}/>)}
          {all.map((d, i) => {
            const dt = new Date(d + 'T12:00:00');
            const on = set.has(d);
            const showMon = i === 0 || dt.getDate() === 1;
            return (
              <button key={d} type="button" aria-pressed={on} className={'pk-day' + (on ? ' on' : '')}
                      aria-label={dt.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
                      onClick={() => toggle(d)}>
                {showMon && <span className="pk-day-mon">{mon(d)}</span>}
                <span className="pk-day-n">{dt.getDate()}</span>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  function fmtRange(from, to) {
    const f = d => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return from === to ? f(from) : f(from) + '–' + f(to);
  }
  function typeNoun(id) {
    const t = (window.TTPicker?.TRIP_TYPES || []).find(x => x.id === id);
    return t ? t.noun : 'trip';
  }
  function useDataTick() {
    // Re-rank when a region's data file finishes merging into window.SD.
    const [tick, setTick] = useState(0);
    useEffect(() => {
      const on = () => setTick(t => t + 1);
      window.addEventListener('tt-region-data', on);
      return () => window.removeEventListener('tt-region-data', on);
    }, []);
    return tick;
  }

  function BookLink({ a, primary }) {
    if (!a.bookingUrl) return null;
    // ccBookingInfo tags links as Co-Captain traffic; these clicks come from
    // the Pick my trip card, so report them as such.
    const href = a.bookingUrl.replace('utm_medium=co_captain', 'utm_medium=pick_my_trip');
    return (
      <a className={primary ? 'pk-book' : 'pk-alt-book'} href={href} target="_blank" rel="noopener noreferrer"
         onClick={() => window.TTTrack?.chatLinkClick?.('PickBook', href, false)}>
        {primary ? 'Book this trip' : 'Book'}<span aria-hidden="true">{' ↗'}</span>
        <span className="sr-only"> on the landing's site (new tab)</span>
      </a>
    );
  }

  function Advisory({ a }) {
    if (!a.advisory) return null;
    return (
      <p className="pk-adv"><i aria-hidden="true"/>
        {a.advisory.event} in effect for this trip. Check with the landing before you go.
      </p>
    );
  }

  // ── Pick my trip ────────────────────────────────────────────────────────────
  // startEmpty (Today): no trip type chosen until the visitor picks one, so the
  // card doesn't repeat the answers already shown above it.
  function PickMyTrip({ regions, navigate, variant, startEmpty, initialQuick, initialType, compact }) {
    const P = window.TTPicker;
    const tick = useDataTick();
    const region = regionOf(regions);
    const presets = useMemo(() => P ? P.presets() : null, []);
    const validType = initialType && (P && P.TRIP_TYPES || []).some(t => t.id === initialType) ? initialType : null;
    const [type, setType] = useState(() => validType || (startEmpty ? null : (store(TYPE_KEY) || 'overnight')));
    const [when, setWhen] = useState('next7');
    const [days, setDays] = useState([]);
    const [species, setSpecies] = useState('');
    const [budget, setBudget] = useState('');
    const [quick, setQuick] = useState(null);

    // One-tap quick picks (same four as Co-Captain's starter buttons) just set
    // the inputs below; touching any input clears the highlight.
    const applyQuick = (id) => {
      const q = (P && P.QUICK_PICKS || []).find(x => x.id === id);
      if (!q) return;
      setQuick(id); setType(q.type); setWhen(q.range === 'weekend' ? 'weekend' : 'next7');
      setSpecies(q.species || ''); setBudget(q.maxPrice ? String(q.maxPrice) : '');
    };
    useEffect(() => { if (initialQuick) applyQuick(initialQuick); }, [initialQuick]);
    const manual = (fn) => (...args) => { setQuick(null); fn(...args); };

    const custom = when === 'custom';
    const range = custom ? (days.length ? { from: days[0], to: days[days.length - 1] } : {}) : (presets ? presets[when] : {});
    const needDays = custom && !days.length;
    const res = useMemo(() => (P && type && !needDays) ? P.pickTrips({
      type, from: range.from, to: range.to, days: custom ? days : undefined, region,
      species: species || undefined, maxPrice: budget ? +budget : undefined,
    }) : null, [type, range.from, range.to, days.join(','), custom, region, species, budget, tick]);

    if (!P) return null;
    const pickType = manual((id) => { setType(id); store(TYPE_KEY, id); });
    const best = res && res.best;
    const H = variant === 'page' ? 'h1' : 'h2';
    const regionLabel = window.getRegionSubtitle ? window.getRegionSubtitle(regions) : 'this region';
    const noSchedule = res && res.scheduled === 0;

    return (
      <section className={`pk${variant === 'page' ? ' pk-page' : ''}`} aria-labelledby="pk-title">
        <div className="pk-eyebrow">Pick my trip</div>
        <H className="pk-title" id="pk-title">What's the best trip to book?</H>

        <div className="pk-quick" role="group" aria-label="Quick picks">
          {P.QUICK_PICKS.map(q => (
            <button key={q.id} aria-pressed={quick === q.id} className={quick === q.id ? 'on' : ''}
                    onClick={() => applyQuick(q.id)}>{q.label}</button>
          ))}
        </div>

        {compact ? (
          <a className="pk-more" href={window.ttPathFromRoute ? window.ttPathFromRoute('pick', {}, regions) : '/sd/pick'}
             onClick={e => { if (navigate) { e.preventDefault(); navigate('pick'); } }}>
            Choose dates, trip type, species or budget<span aria-hidden="true">{' →'}</span>
          </a>
        ) : <div className="pk-inputs">
          <div className="pk-field" role="radiogroup" aria-label="Trip type">
            <span className="pk-label">Trip</span>
            <div className="pk-chips">
              {P.TRIP_TYPES.map(t => (
                <button key={t.id} role="radio" aria-checked={type === t.id}
                        className={type === t.id ? 'on' : ''} onClick={() => pickType(t.id)}>{t.label}</button>
              ))}
            </div>
          </div>
          <div className="pk-field" role="radiogroup" aria-label="When">
            <span className="pk-label">When</span>
            <div className="pk-chips">
              {[['weekend', 'This weekend'], ['next7', 'Next 7 days'], ['custom', 'Pick dates']].map(([k, l]) => (
                <button key={k} role="radio" aria-checked={when === k}
                        className={when === k ? 'on' : ''} onClick={manual(() => setWhen(k))}>{l}</button>
              ))}
            </div>
            {custom && presets && <DayGrid start={presets.next7.from} days={days} onChange={manual(setDays)}/>}
          </div>
          <div className="pk-field pk-opts">
            <span className="pk-label">Options</span>
            <div className="pk-selects">
              <select aria-label="Target species" value={species} onChange={manual(e => setSpecies(e.target.value))}>
                <option value="">Any fish</option>
                <option value="Tuna">Any tuna</option>
                {SPECIES.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <select aria-label="Budget" value={budget} onChange={manual(e => setBudget(e.target.value))}>
                {BUDGETS.map(b => <option key={b.v} value={b.v}>{b.label}</option>)}
              </select>
            </div>
          </div>
        </div>}

        <div className="pk-answer" aria-live="polite">
          {type && needDays ? (
            <p className="pk-prompt">Tap the days you could go, and we'll pick the best boat with open seats on any of them.</p>
          ) : !type ? (
            compact ? null : <p className="pk-prompt">Tap a quick pick or choose a trip type, and we'll pick the boat with open seats that has been catching best.</p>
          ) : noSchedule ? (
            <div className="pk-empty">
              <p>We don't have trip schedules for {regionLabel} yet, so we can't pick a trip here.</p>
              <div className="pk-empty-acts"><button onClick={() => navigate && navigate('boats')}>See the boats</button></div>
            </div>
          ) : res && res.reason === 'no-species' ? (
            <div className="pk-empty">
              <p>No boat with open seats has been landing many {species === 'Tuna' ? 'tuna' : species.toLowerCase()} lately.</p>
              <div className="pk-empty-acts">
                <button onClick={manual(() => setSpecies(''))}>Any fish</button>
                <button onClick={() => navigate && navigate('tripplanner')}>Browse every trip</button>
              </div>
            </div>
          ) : best ? (
            <React.Fragment>
              <div className="pk-best">
                <div className="pk-best-main">
                  <div className="pk-kicker">Best bet · {custom ? fmtDays(days) : fmtRange(range.from, range.to)}</div>
                  <div className="pk-boat">
                    <button className="pk-boat-link" onClick={() => navigate && navigate('boat', { boat: best.boat })}>{best.boat}</button>
                  </div>
                  <div className="pk-meta">{best.dateLabel} · {best.tripLength} · {best.landing}</div>
                  <p className="pk-why">{best.reason}</p>
                  <Advisory a={best}/>
                </div>
                <div className="pk-best-side">
                  <dl className="pk-facts">
                    <div><dt>Price</dt><dd>{money(best.price) || '—'}</dd></div>
                    <div><dt>Seats</dt><dd>{best.openSpots ?? '—'}</dd></div>
                    <div><dt>Fish/angler</dt><dd>{best.samples ? rate(best.rate) : '—'}</dd></div>
                  </dl>
                  <BookLink a={best} primary/>
                </div>
              </div>
              {res.alternates.length > 0 && (
                <div className="pk-alts">
                  <div className="pk-alts-h">Also good</div>
                  <ul>
                    {res.alternates.map(a => (
                      <li key={a.boat + a.departureAt} className="pk-alt">
                        <div className="pk-alt-main">
                          <button className="pk-alt-boat" onClick={() => navigate && navigate('boat', { boat: a.boat })}>{a.boat}</button>
                          <span className="pk-alt-meta">{a.dateLabel} · {[money(a.price), seatsText(a.openSpots)].filter(Boolean).join(' · ')}</span>
                          <span className="pk-alt-why">{a.samples ? `${rate(a.rate)} ${a.noun}/angler lately (fleet ${rate(a.fleetRate)})${a.samples < 3 ? ', few trips' : ''}` : 'No recent trips of this type'}</span>
                          {a.advisory && <span className="pk-alt-adv">{a.advisory.event}</span>}
                        </div>
                        <BookLink a={a}/>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </React.Fragment>
          ) : (
            <div className="pk-empty">
              <p>No open {Array.isArray(type) ? 'trip' : typeNoun(type)}s {when === 'weekend' ? 'this weekend' : custom ? (days.length === 1 ? 'that day' : 'on those days') : 'in those dates'}{budget ? ' in that budget' : ''}.</p>
              <div className="pk-empty-acts">
                {when === 'weekend' && <button onClick={manual(() => setWhen('next7'))}>Try the next 7 days</button>}
                {!custom && <button onClick={manual(() => { setDays(Array.from({ length: 14 }, (_, i) => P.addDays(presets.next7.from, i))); setWhen('custom'); })}>Try the next 2 weeks</button>}
                {custom && days.length < DAY_GRID && <button onClick={manual(() => setDays(Array.from({ length: DAY_GRID }, (_, i) => P.addDays(presets.next7.from, i))))}>Any day in the next 3 weeks</button>}
                {budget && <button onClick={manual(() => setBudget(''))}>Any price</button>}
                <button onClick={() => navigate && navigate('tripplanner')}>Browse every trip</button>
              </div>
            </div>
          )}
        </div>
        <p className="pk-note">Ranked on the fish counts the landings reported for each boat's recent trips, not a forecast. Seats and prices are from the landings' schedules and can change.</p>
      </section>
    );
  }

  // ── Answers first (top of Today) ────────────────────────────────────────────
  const ANSWER_TYPES = [['overnight', 'Best overnight'], ['full', 'Best full day'], ['1.5', 'Best 1.5 day']];

  function shortWhy(a) {
    if (!a.samples) return 'no recent trips of this type';
    const multi = !/Full Day|Overnight/.test(a.tripLength);
    return `${rate(a.rate)} ${a.noun} per angler${multi ? ' per day' : ''} lately, fleet ${rate(a.fleetRate)}`;
  }

  // Latest San Diego offshore water temps (window.SD.SST, ocean_temps table).
  // These spots are all off San Diego, so only the SD view shows them.
  const SST_SPOTS = [['Nearshore', 'Nearshore'], ['9-Mile Bank', '9-Mile'], ['60-Mile Bank', '60-Mile'], ['Cortez Bank', 'Cortez']];
  function waterTemps() {
    const h = window.SD && window.SD.SST && window.SD.SST.history;
    if (!Array.isArray(h) || !h.length) return null;
    const last = {};
    h.forEach(r => { if (r && r.sst != null && (!last[r.location] || r.date > last[r.location].date)) last[r.location] = r; });
    const spots = SST_SPOTS.filter(([k]) => last[k]).map(([k, l]) => ({ label: l, ...last[k] }));
    if (!spots.length) return null;
    const lead = spots[0];
    const today = window.TTPicker ? window.TTPicker.presets().next7.from : null;
    const stale = today && (Date.parse(today) - Date.parse(lead.date)) / 864e5 > 2;
    return { lead, rest: spots.slice(1), stale };
  }
  const fmtF = x => Math.round(x * 10) / 10 + '°F';
  const shortDate = d => new Date(d + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

  function TodayAnswers({ regions, navigate }) {
    const P = window.TTPicker;
    const tick = useDataTick();
    const region = regionOf(regions);
    const data = useMemo(() => {
      if (!P) return null;
      const answers = ANSWER_TYPES
        .map(([type, label]) => ({ type, label, r: P.pickTrips({ type, region }) }))
        .filter(x => x.r.best);
      return { answers: answers.slice(0, 2), biting: P.whatsBiting({ region }) };
    }, [region, tick]);
    if (!data) return null;
    const { answers, biting } = data;
    const top = biting.items.filter(x => x.perAngler >= 0.05).slice(0, 3);
    const temps = region === 'san_diego' ? waterTemps() : null;

    return (
      <section className="ta" aria-label="Quick answers">
        <ul className="ta-list">
          {answers.map(({ type, label, r }) => {
            const a = r.best;
            return (
              <li key={type} className="ta-item">
                <div className="ta-q">{label} this week</div>
                <div className="ta-a">
                  <button className="ta-boat" onClick={() => navigate('boat', { boat: a.boat })}>{a.boat}</button>
                  <span className="ta-meta">{a.dateLabel}{a.price != null ? ` · ${money(a.price)}` : ''}{a.openSpots != null ? ` · ${seatsText(a.openSpots)}` : ''}</span>
                </div>
                <div className="ta-why">{shortWhy(a)}{a.advisory ? ` · ${a.advisory.event}` : ''}</div>
                <BookLink a={a}/>
              </li>
            );
          })}
          {top.length > 0 && (
            <li className="ta-item ta-biting">
              <div className="ta-q">What's biting</div>
              <div className="ta-a">
                <span className="ta-species">{top[0].species}</span>
                <span className="ta-meta">{top[0].perAngler.toFixed(1)} per angler this week{top[0].change != null ? ` (${top[0].change >= 0 ? 'up' : 'down'} ${Math.abs(Math.round(top[0].change * 100))}%)` : ''}</span>
              </div>
              <div className="ta-why">
                {top.length > 1 ? 'Then ' + top.slice(1).map(x => `${x.species.toLowerCase()} ${x.perAngler.toFixed(1)}`).join(', ') + '. ' : ''}
                From {biting.trips} trips, {biting.anglers.toLocaleString()} anglers.
              </div>
            </li>
          )}
          {temps && (
            <li className="ta-item ta-temp">
              <div className="ta-q">Water temperature</div>
              <div className="ta-a">
                <span className="ta-species">{fmtF(temps.lead.sst)}</span>
                <span className="ta-meta">{temps.lead.label}{temps.lead.anomaly != null ? ` · ${Math.abs(Math.round(temps.lead.anomaly * 10) / 10)}° ${temps.lead.anomaly >= 0 ? 'above' : 'below'} normal` : ''}{temps.stale ? ` · ${shortDate(temps.lead.date)}` : ''}</span>
              </div>
              <div className="ta-why">
                {temps.rest.length ? temps.rest.map(s => `${s.label} ${fmtF(s.sst)}${s.date !== temps.lead.date ? ` (${shortDate(s.date)})` : ''}`).join(', ') + '. ' : ''}
                Satellite readings, not a forecast.
              </div>
              <button className="ta-link" onClick={() => navigate('charts')}>See the temperature map<span aria-hidden="true">{' →'}</span></button>
            </li>
          )}
        </ul>
      </section>
    );
  }

  // ── Simple / Detailed ───────────────────────────────────────────────────────
  function useViewMode() {
    const [mode, setMode] = useState(() => store(MODE_KEY) === 'detailed' ? 'detailed' : 'simple');
    const set = (m) => { setMode(m); store(MODE_KEY, m); };
    return [mode, set];
  }

  function ViewModeSwitch({ mode, onChange }) {
    return (
      <div className="vm" role="radiogroup" aria-label="How much detail">
        {[['simple', 'Simple'], ['detailed', 'Detailed']].map(([k, l]) => (
          <button key={k} role="radio" aria-checked={mode === k} className={mode === k ? 'on' : ''} onClick={() => onChange(k)}>{l}</button>
        ))}
      </div>
    );
  }

  // Few big numbers for Simple mode: this week's fleet catch.
  function SimpleNumbers({ regions }) {
    const P = window.TTPicker;
    const tick = useDataTick();
    const region = regionOf(regions);
    const w = useMemo(() => P ? P.whatsBiting({ region }) : null, [region, tick]);
    if (!w || !w.trips) return null;
    const fish = w.items.reduce((s, x) => s + x.fish, 0);
    return (
      <dl className="sn">
        <div><dt>Fish this week</dt><dd>{fish.toLocaleString()}</dd></div>
        <div><dt>Trips reported</dt><dd>{w.trips}</dd></div>
        <div><dt>Fish per angler</dt><dd>{w.anglers ? (fish / w.anglers).toFixed(1) : '—'}</dd></div>
      </dl>
    );
  }

  // Today: answers first, then (Simple) big numbers with the full report
  // behind "See the details", or (Detailed) the full report. Pick my trip
  // lives only on Home and the Trip Planner (owner, 2026-11-26).
  function TodaySimple({ regions, navigate, settings, Report }) {
    const [mode, setMode] = useViewMode();
    const [open, setOpen] = useState(false);
    const region = regionOf(regions);
    const label = window.getRegionSubtitle ? window.getRegionSubtitle(regions) : 'San Diego';
    const hasAnswers = !!window.TTPicker && region !== 'sf_bay';
    return (
      <div className={`tsim tsim-${mode}`}>
        <div className="tsim-head">
          {mode === 'simple' ? (
            <div>
              <div className="pk-eyebrow">This week · {label}</div>
              <h1 className="tsim-title">Where to fish this week</h1>
            </div>
          ) : <div className="pk-eyebrow">Quick answers · {label}</div>}
          <ViewModeSwitch mode={mode} onChange={setMode}/>
        </div>
        {hasAnswers && <TodayAnswers regions={regions} navigate={navigate}/>}
        {mode === 'simple' ? (
          <React.Fragment>
            <SimpleNumbers regions={regions}/>
            <div className="tsim-details">
              <button className="tsim-more" aria-expanded={open} onClick={() => setOpen(o => !o)}>
                {open ? 'Hide the details' : 'See the details'}<span aria-hidden="true">{open ? ' ↑' : ' ↓'}</span>
              </button>
              <span className="tsim-more-sub">Every boat's catch, by day</span>
            </div>
            {open && <Report navigate={navigate} settings={settings} regions={regions}/>}
          </React.Fragment>
        ) : (
          <Report navigate={navigate} settings={settings} regions={regions}/>
        )}
      </div>
    );
  }

  // Home, top of the page: the at-a-glance answers (best boats, what's
  // biting, water temp) and this week's numbers, in every region with a trip
  // schedule (SD, OC/LA). Observed counts only, no forecast. Pick my trip
  // sits lower on Home (HomePicker, after the counts), per owner 2026-11-26.
  function HomeAnswers({ regions, navigate }) {
    const region = regionOf(regions);
    const label = window.getRegionSubtitle ? window.getRegionSubtitle(regions) : 'San Diego';
    if (!window.TTPicker || region === 'sf_bay') return null;
    return (
      <section className="ha" aria-labelledby="ha-title">
        <div className="ha-in">
          <div className="pk-eyebrow">This week · {label}</div>
          <h2 className="ha-title" id="ha-title">Where to fish this week</h2>
          <TodayAnswers regions={regions} navigate={navigate}/>
          <SimpleNumbers regions={regions}/>
        </div>
      </section>
    );
  }

  // Pick my trip block (quick picks + link to /pick). Shown only on Home
  // (lower down, after the counts) and on the Trip Planner (bare: no Home
  // section wrapper). Owner, 2026-11-26: not on every page.
  function HomePicker({ regions, navigate, bare }) {
    const region = regionOf(regions);
    const tick = useDataTick();
    const hasPicker = useMemo(() => !!window.TTPicker && region !== 'sf_bay' &&
      window.TTPicker.pickTrips({ type: 'full', region }).scheduled > 0, [region, tick]);
    if (!hasPicker) return null;
    if (bare) return <div className="tp-pick"><PickMyTrip regions={regions} navigate={navigate} startEmpty compact/></div>;
    return (
      <section className="ha ha-pick" aria-label="Pick my trip">
        <div className="ha-in">
          <PickMyTrip regions={regions} navigate={navigate} startEmpty compact/>
        </div>
      </section>
    );
  }

  // Own route: /sd/pick
  function PickTripView({ regions, navigate }) {
    // Deep links: ?q=<quick pick id> or ?type=full|overnight|1.5|multi|long (next 7 days).
    const params = useMemo(() => { try { return new URLSearchParams(window.location.search); } catch (e) { return null; } }, []);
    const q = params && params.get('q');
    const t = params && params.get('type');
    return (
      <div className="pk-view">
        <PickMyTrip regions={regions} navigate={navigate} variant="page" initialQuick={q} initialType={t}/>
      </div>
    );
  }

  Object.assign(window, { PickMyTrip, TodayAnswers, TodaySimple, HomeAnswers, HomePicker, PickTripView, ViewModeSwitch });
})();
