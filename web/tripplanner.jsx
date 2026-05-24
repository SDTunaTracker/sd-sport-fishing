// Trip Planner — upcoming open-party trips

// ── Moon phase (synodic-month approximation, port of src/moon.py) ──────────
const _MOON_REF    = Date.UTC(2000, 0, 6, 18, 14, 0); // 2000-01-06 18:14 UTC
const _SYNODIC     = 29.53058867;
const _MOON_NAMES  = ['New','Waxing Crescent','First Quarter','Waxing Gibbous',
                      'Full','Waning Gibbous','Last Quarter','Waning Crescent'];
const _MOON_EMOJIS = ['🌑','🌒','🌓','🌔','🌕','🌖','🌗','🌘'];

function moonInfo(date) {
  const days  = (date.getTime() - _MOON_REF) / 86400000;
  const p     = ((days % _SYNODIC) + _SYNODIC) % _SYNODIC;
  const illum = Math.round(((1 - Math.cos((p / _SYNODIC) * 2 * Math.PI)) / 2) * 100);
  const idx   = Math.round((p / _SYNODIC) * 8) % 8;
  return { phase: _MOON_NAMES[idx], emoji: _MOON_EMOJIS[idx], illum };
}

function moonColor(illum) {
  if (illum >= 90) return '#FBBF24'; // full: gold
  if (illum <= 10) return '#38BDF8'; // new: sky blue
  if (illum >= 40 && illum <= 60) return '#34D399'; // quarter: green
  return '#94A3B8';
}

function MoonCell({ departureAt }) {
  const m = moonInfo(new Date(departureAt));
  const c = moonColor(m.illum);
  return (
    <div title="Full and new moons historically correlate with better tuna catches"
         style={{display:'flex', flexDirection:'column', alignItems:'center', gap:1, cursor:'default'}}>
      <span style={{fontSize:17, lineHeight:1}}>{m.emoji}</span>
      <span className="tp-moon-name" style={{font:'400 9px/12px var(--ss-font-sans)', color:c}}>{m.phase}</span>
      <span style={{font:'600 10px/13px var(--ss-font-sans)', color:c}}>{m.illum}%</span>
    </div>
  );
}

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

function fmtDepDate(d) {
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function fmtTime(d) {
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function winRateColor(wr) {
  if (wr >= 0.70) return 'var(--ss-darkseagreen-500)';
  if (wr >= 0.50) return 'var(--ss-slate)';
  return 'var(--ss-orange-500)';
}

function BestRow({ s }) {
  const dep = new Date(s.departureAt);
  const depStr = `${fmtDepDate(dep)} ${fmtTime(dep)}`;
  const price = s.price != null ? `$${s.price.toFixed(0)}` : '—';
  const wrPct = s._winRate != null ? Math.round(s._winRate * 100) : null;
  const wrLabel = wrPct != null ? `${wrPct}%` : '—';
  const wrColor = wrPct != null ? winRateColor(s._winRate) : 'var(--tb-gray-3)';
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
    <div className="tp-best-row" style={{
      padding: '10px 12px',
      borderBottom: '1px solid var(--ss-border-2)',
      font: '400 12px/16px var(--ss-font-sans)',
    }}>
      <div style={{minWidth: 0}}>
        <div style={{font: '600 13px/16px var(--ss-font-sans)', color: 'var(--ss-black)'}}>{boatLabel}</div>
        <div style={{font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-slate)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{s.tripLength} · {landingShort}</div>
      </div>
      <span className="tp-trip-col" style={{color: 'var(--ss-slate)'}}>{s.tripLength}</span>
      <span style={{textAlign: 'right', fontVariantNumeric: 'tabular-nums'}}>{depStr}</span>
      <MoonCell departureAt={s.departureAt}/>
      <div className="tp-wr-col" style={{textAlign: 'right'}}>
        <div style={{fontWeight: 600, color: wrColor}}>{wrLabel}</div>
        {s._trips > 0 && <div style={{font: '400 10px/13px var(--ss-font-sans)', color: 'var(--ss-slate)'}}>{s._trips}t</div>}
      </div>
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

function CheapestRow({ s }) {
  const dep = new Date(s.departureAt);
  const depStr = `${fmtDepDate(dep)} ${fmtTime(dep)}`;
  const price = s.price != null ? `$${s.price.toFixed(0)}` : '—';
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
    <div className="tp-cheapest-row" style={{
      padding: '10px 12px',
      borderBottom: '1px solid var(--ss-border-2)',
      font: '400 12px/16px var(--ss-font-sans)',
    }}>
      <div style={{minWidth: 0}}>
        <div style={{font: '600 13px/16px var(--ss-font-sans)', color: 'var(--ss-black)'}}>{boatLabel}</div>
        <div style={{font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-slate)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{s.tripLength} · {landingShort}</div>
      </div>
      <span className="tp-trip-col" style={{color: 'var(--ss-slate)'}}>{s.tripLength}</span>
      <span style={{textAlign: 'right', fontVariantNumeric: 'tabular-nums'}}>{depStr}</span>
      <MoonCell departureAt={s.departureAt}/>
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

// ---- Filter Trips modal ---------------------------------------------------

function FilterTripsModal({ open, onClose, filters, onApply }) {
  const [start, setStart] = useState(filters.start || '');
  const [end, setEnd] = useState(filters.end || '');
  const [landing, setLanding] = useState(filters.landing);
  const [tripLength, setTripLength] = useState(filters.tripLength);

  useEffect(() => {
    if (open) {
      setStart(filters.start || '');
      setEnd(filters.end || '');
      setLanding(filters.landing);
      setTripLength(filters.tripLength);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const handleReset = () => {
    setStart('');
    setEnd('');
    setLanding('all');
    setTripLength('all');
  };

  const handleApply = () => {
    onApply({ start: start || null, end: end || null, landing, tripLength });
    onClose();
  };

  if (!open) return null;

  const SECTION_LABEL = {
    font: '600 11px/14px var(--ss-font-sans)',
    textTransform: 'uppercase',
    letterSpacing: '.06em',
    color: 'var(--ss-slate)',
    marginBottom: 8,
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{maxWidth: 440}} onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <h2 style={{margin: 0, font: '600 18px/22px var(--ss-font-serif, Fraunces, serif)'}}>
            Filter Trips
          </h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body" style={{padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 20}}>
          <div>
            <div style={SECTION_LABEL}>Date Range</div>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8}}>
              <div className="filter">
                <label>From</label>
                <input type="date" value={start} onChange={e => setStart(e.target.value)}/>
              </div>
              <div className="filter">
                <label>To</label>
                <input type="date" value={end} onChange={e => setEnd(e.target.value)}/>
              </div>
            </div>
          </div>

          <div>
            <div style={SECTION_LABEL}>Landing</div>
            <MultiSelect options={window.SD.LANDINGS} value={landing}
                         onChange={setLanding} allLabel="All landings"/>
          </div>

          <div>
            <div style={SECTION_LABEL}>Trip Length</div>
            <MultiSelect options={window.SD.TRIP_LENGTHS} value={tripLength}
                         onChange={setTripLength} allLabel="Any length"/>
          </div>
        </div>

        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 20px',
          borderTop: '1px solid var(--ss-border-2)',
          background: 'var(--ss-clay)',
          borderRadius: '0 0 12px 12px',
        }}>
          <button className="btn ghost" onClick={handleReset}>Reset</button>
          <button className="btn primary" onClick={handleApply}
                  style={{background: '#0EA5E9', borderColor: '#0EA5E9'}}>
            Apply Filters
          </button>
        </div>
      </div>
    </div>
  );
}

function TripPlanner({ navigate }) {
  const _matches = (val, filter) => {
    if (filter == null || filter === 'all' || filter === '') return true;
    const sel = Array.isArray(filter) ? filter : [filter];
    return sel.length === 0 || sel.map(String).includes(String(val));
  };

  const [tpFilters, setTpFilters] = useState({ start: null, end: null, landing: 'all', tripLength: 'all' });

  const schedule = useMemo(() => {
    const now = new Date();
    return (window.SD.SCHEDULE || []).filter(s => {
      const dep = new Date(s.departureAt);
      if (dep < now) return false;
      if (tpFilters.start && dep < new Date(tpFilters.start + 'T00:00:00')) return false;
      if (tpFilters.end   && dep > new Date(tpFilters.end   + 'T23:59:59')) return false;
      if (!_matches(s.landing,    tpFilters.landing))    return false;
      if (!_matches(s.tripLength, tpFilters.tripLength)) return false;
      return true;
    });
  }, [tpFilters]);

  const winRates = useMemo(() => SDA.boatWinRates(), []);

  const bestSchedule = useMemo(() => {
    return [...schedule].map(s => {
      const wr = winRates[`${s.boat}|${s.tripLength}`];
      return { ...s, _winRate: wr ? wr.winRate : null, _trips: wr ? wr.total : 0 };
    }).sort((a, b) => {
      if (a._winRate === null && b._winRate === null) return (a.price || 0) - (b.price || 0);
      if (a._winRate === null) return 1;
      if (b._winRate === null) return -1;
      return b._winRate - a._winRate;
    });
  }, [schedule, winRates]);

  const cheapestSchedule = useMemo(() => {
    return [...schedule].sort((a, b) => {
      if (a.price == null && b.price == null) return 0;
      if (a.price == null) return 1;
      if (b.price == null) return -1;
      return a.price - b.price;
    });
  }, [schedule]);

  const [activeTab, setActiveTab] = useState('best');
  const [filterOpen, setFilterOpen] = useState(false);

  const minPrice = cheapestSchedule.find(s => s.price != null)?.price;

  const activeFilterCount =
    (tpFilters.start || tpFilters.end ? 1 : 0) +
    (Array.isArray(tpFilters.landing)    ? 1 : 0) +
    (Array.isArray(tpFilters.tripLength) ? 1 : 0);

  const HDR_STYLE = {
    padding: '8px 12px',
    background: 'var(--ss-clay)',
    borderBottom: '1px solid var(--ss-border-2)',
    font: '700 10px/12px var(--ss-font-sans)',
    textTransform: 'uppercase', letterSpacing: '.06em',
    color: 'var(--ss-slate)',
  };

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
          <div className="sub">{fmt.n(schedule.length)} upcoming open-party trips</div>
        </div>
        <div className="actions">
          <button className="btn primary" onClick={() => setFilterOpen(true)}>
            🔧 Filter Trips{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
          </button>
        </div>
      </div>

      <FilterTripsModal
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        filters={tpFilters}
        onApply={setTpFilters}
      />

      <Panel title="Upcoming Open-Party Trips"
             meta={`${schedule.length} bookable · sold-out hidden`}
             padding={false}>
        <div className="tp-tabs">
          <button className={`tp-tab${activeTab === 'best' ? ' active' : ''}`}
                  onClick={() => setActiveTab('best')}>
            <div className="tp-tab-main">
              Best <span className="tp-tab-info">ⓘ</span>
            </div>
            <div className="tp-tab-sub">Ranked by win rate &amp; performance</div>
          </button>
          <button className={`tp-tab${activeTab === 'cheapest' ? ' active' : ''}`}
                  onClick={() => setActiveTab('cheapest')}>
            <div className="tp-tab-main">
              Cheapest
              {minPrice != null && <span className="tp-tab-price"> from ${minPrice.toFixed(0)}</span>}
              <span className="tp-tab-info">ⓘ</span>
            </div>
            <div className="tp-tab-sub">Sorted by price</div>
          </button>
        </div>

        {schedule.length === 0 ? (
          <div className="muted-block" style={{padding: 16}}>
            No trips match your filters. Click "🔧 Filter Trips" to adjust.
          </div>
        ) : activeTab === 'best' ? (
          <Fragment>
            <div className="tp-best-row" style={HDR_STYLE}>
              <span>Boat</span>
              <span className="tp-trip-col">Trip</span>
              <span style={{textAlign: 'right'}}>Depart</span>
              <span style={{textAlign: 'center'}}>Moon</span>
              <span className="tp-wr-col" style={{textAlign: 'right'}}>Win Rate</span>
              <span style={{textAlign: 'right'}}>Price</span>
              <span style={{textAlign: 'right'}}>Open</span>
            </div>
            <div style={{maxHeight: 720, overflow: 'auto'}}>
              {bestSchedule.map(s => <BestRow key={`${s.landing}-${s.sourceId}`} s={s}/>)}
            </div>
          </Fragment>
        ) : (
          <Fragment>
            <div className="tp-cheapest-row" style={HDR_STYLE}>
              <span>Boat</span>
              <span className="tp-trip-col">Trip</span>
              <span style={{textAlign: 'right'}}>Depart</span>
              <span style={{textAlign: 'center'}}>Moon</span>
              <span style={{textAlign: 'right'}}>Price</span>
              <span style={{textAlign: 'right'}}>Open</span>
            </div>
            <div style={{maxHeight: 720, overflow: 'auto'}}>
              {cheapestSchedule.map(s => <CheapestRow key={`${s.landing}-${s.sourceId}`} s={s}/>)}
            </div>
          </Fragment>
        )}
      </Panel>
    </Fragment>
  );
}

Object.assign(window, { TripPlanner });
