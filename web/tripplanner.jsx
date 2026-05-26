// Trip Planner — Expedia-style redesign
const { useState, useMemo, useEffect, Fragment } = React;

// ── Moon helpers (kept from original) ───────────────────────────────────────
const _MOON_REF    = Date.UTC(2000, 0, 6, 18, 14, 0);
const _SYNODIC     = 29.53058867;
const _MOON_NAMES  = ['New','Waxing Crescent','First Quarter','Waxing Gibbous',
                      'Full','Waning Gibbous','Last Quarter','Waning Crescent'];
const _MOON_EMOJIS = ['🌑','🌒','🌓','🌔','🌕','🌖','🌗','🌘'];

function moonInfo(date) {
  const days = (date.getTime() - _MOON_REF) / 86400000;
  const p    = ((days % _SYNODIC) + _SYNODIC) % _SYNODIC;
  const illum = Math.round(((1 - Math.cos((p / _SYNODIC) * 2 * Math.PI)) / 2) * 100);
  const idx   = Math.round((p / _SYNODIC) * 8) % 8;
  return { phase: _MOON_NAMES[idx], emoji: _MOON_EMOJIS[idx], illum };
}

function moonColor(illum) {
  if (illum >= 90) return '#FBBF24';
  if (illum <= 10) return '#38BDF8';
  if (illum >= 40 && illum <= 60) return '#34D399';
  return '#94A3B8';
}

// ── Per-landing booking URL (kept from original) ─────────────────────────────
function bookingUrl(s) {
  switch (s.landing) {
    case 'Point Loma Sportfishing':
      return `https://pointloma.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
    case 'Seaforth Sportfishing':
      return `https://seaforth.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
    case "Fisherman's Landing":
      return `https://fishermanslanding.fishingreservations.net/resos/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
    case 'H&M Landing': {
      const slug = (s.boat || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
      return slug ? `https://www.hmlanding.com/boat/${slug}#tab-open-trips` : null;
    }
    default: return null;
  }
}

function fmtDepDate(d) {
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
function fmtTime(d) {
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}
function shortLanding(name) {
  return (name || '').replace(' Sportfishing', '').replace(' Landing', '');
}

// ── Moon phase options ────────────────────────────────────────────────────────
const MOON_PHASE_OPTIONS = [
  { phase: 'New',             emoji: '🌑', label: 'New Moon',        note: '0–10%'  },
  { phase: 'Waxing Crescent', emoji: '🌒', label: 'Waxing Crescent', note: null     },
  { phase: 'First Quarter',   emoji: '🌓', label: 'First Quarter',   note: null     },
  { phase: 'Waxing Gibbous',  emoji: '🌔', label: 'Waxing Gibbous',  note: null     },
  { phase: 'Full',            emoji: '🌕', label: 'Full Moon',       note: '90–100%'},
  { phase: 'Waning Gibbous',  emoji: '🌖', label: 'Waning Gibbous',  note: null     },
  { phase: 'Last Quarter',    emoji: '🌗', label: 'Last Quarter',    note: null     },
  { phase: 'Waning Crescent', emoji: '🌘', label: 'Waning Crescent', note: null     },
];

// ── Badges ────────────────────────────────────────────────────────────────────
function WinRateBadge({ wr }) {
  if (wr == null) return <span className="tp-badge tp-wr-none">—</span>;
  const pct = Math.round(wr * 100);
  const cls = wr >= 0.60 ? 'tp-wr-green' : wr >= 0.40 ? 'tp-wr-yellow' : 'tp-wr-red';
  return <span className={`tp-badge ${cls}`}>{pct}%</span>;
}

function SpotsBadge({ spots }) {
  if (spots == null || spots === 0)
    return <span className="tp-badge tp-spots-full">Full</span>;
  if (spots < 5)
    return <span className="tp-badge tp-spots-red">{spots} left!</span>;
  if (spots < 10)
    return <span className="tp-badge tp-spots-yellow">{spots} spots left</span>;
  return <span className="tp-badge tp-spots-green">{spots} spots</span>;
}

function LengthBadge({ label }) {
  return <span className="tp-length-badge">{label}</span>;
}

// ── Trip card ─────────────────────────────────────────────────────────────────
function TripCard({ s, avgTpaByKey }) {
  const dep   = new Date(s.departureAt);
  const moon  = moonInfo(dep);
  const moonC = moonColor(moon.illum);
  const price = s.price != null ? `$${s.price.toFixed(0)}` : null;
  const url   = bookingUrl(s);
  const tpaKey = `${s.boat}|${s.tripLength}`;
  const avgTpa = avgTpaByKey ? avgTpaByKey[tpaKey] : null;

  const boatEl = url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className="tp-card-boat-link">
      {s.boat}
    </a>
  ) : <span className="tp-card-boat-name">{s.boat}</span>;

  return (
    <div className="tp-card">
      {/* LEFT — boat info */}
      <div className="tp-card-left">
        <div className="tp-card-boat">{boatEl}</div>
        <div className="tp-card-landing">{shortLanding(s.landing)}</div>
        <LengthBadge label={s.tripLength}/>
      </div>

      {/* MIDDLE — trip details */}
      <div className="tp-card-middle">
        <div className="tp-card-depart">
          <i className="fa-regular fa-calendar" style={{marginRight: 5, opacity: 0.5}}></i>
          {fmtDepDate(dep)} · {fmtTime(dep)}
        </div>
        <div className="tp-card-moon" style={{color: moonC}}>
          {moon.emoji} {moon.phase} · {moon.illum}%
        </div>
        <div className="tp-card-wr-row">
          <span className="tp-card-stat-label">Win Rate</span>
          <WinRateBadge wr={s._winRate}/>
          {s._trips > 0 && <span className="tp-card-trips-hint">{s._trips} trips</span>}
        </div>
        {avgTpa != null && (
          <div className="tp-card-tpa">
            Avg TPA: <strong>{avgTpa.toFixed(2)}</strong>/day
          </div>
        )}
      </div>

      {/* RIGHT — price + booking */}
      <div className="tp-card-right">
        {price
          ? <><div className="tp-card-price">{price}</div><div className="tp-card-per">per person</div></>
          : <div className="tp-card-price tp-card-price-na">—</div>
        }
        <SpotsBadge spots={s.openSpots}/>
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer" className="tp-card-book-btn">
            View Trip →
          </a>
        )}
      </div>

      {/* MOBILE bottom row */}
      <div className="tp-card-mobile-footer">
        <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
          <WinRateBadge wr={s._winRate}/>
          <SpotsBadge spots={s.openSpots}/>
          {price && <span className="tp-card-price-mobile">{price}</span>}
        </div>
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer" className="tp-card-book-btn tp-card-book-full">
            View Trip →
          </a>
        )}
      </div>
    </div>
  );
}

// ── Top search bar ────────────────────────────────────────────────────────────
function SearchInput({ icon, label, value, onClick, active }) {
  return (
    <button className={`tp-search-field${active ? ' tp-search-field-active' : ''}`} onClick={onClick}>
      <span className="tp-search-icon">{icon}</span>
      <div className="tp-search-field-body">
        <div className="tp-search-field-label">{label}</div>
        <div className="tp-search-field-value">{value}</div>
      </div>
    </button>
  );
}

function DatePopover({ start, end, onStart, onEnd, onClose }) {
  return (
    <div className="tp-popover tp-popover-date">
      <div className="tp-pop-row">
        <div className="tp-pop-field">
          <label className="tp-pop-label">From</label>
          <input type="date" className="tp-pop-date-input" value={start}
                 onChange={e => onStart(e.target.value)}/>
        </div>
        <div className="tp-pop-field">
          <label className="tp-pop-label">To</label>
          <input type="date" className="tp-pop-date-input" value={end}
                 onChange={e => onEnd(e.target.value)}/>
        </div>
      </div>
      <div className="tp-pop-footer">
        <button className="tp-pop-clear" onClick={() => { onStart(''); onEnd(''); }}>Clear</button>
        <button className="tp-pop-done" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}

function ChecklistPopover({ options, value, onChange, onClose, allLabel }) {
  const selected = value === 'all' ? options : (Array.isArray(value) ? value : []);
  const allSelected = value === 'all' || selected.length === options.length;

  const toggle = (opt) => {
    const next = selected.includes(opt)
      ? selected.filter(o => o !== opt)
      : [...selected, opt];
    onChange(next.length === 0 || next.length === options.length ? 'all' : next);
  };

  return (
    <div className="tp-popover tp-popover-check">
      <label className="tp-pop-check-row tp-pop-check-all">
        <input type="checkbox" checked={allSelected}
               onChange={() => onChange('all')}/>
        <span>{allLabel || 'All'}</span>
      </label>
      <div className="tp-pop-divider"/>
      {options.map(opt => (
        <label key={opt} className="tp-pop-check-row">
          <input type="checkbox"
                 checked={allSelected || selected.includes(opt)}
                 onChange={() => toggle(opt)}/>
          <span>{opt.replace(' Sportfishing', '').replace(' Landing', '')}</span>
        </label>
      ))}
      <div className="tp-pop-footer">
        <button className="tp-pop-done" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}

function TopSearchBar({ dateStart, dateEnd, setDateStart, setDateEnd,
                         selLandings, setSelLandings, selLengths, setSelLengths,
                         openPop, setOpenPop }) {
  const fmtDate = d => d ? new Date(d + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' }) : null;
  const dateLabel = dateStart || dateEnd
    ? [fmtDate(dateStart) || 'Start', fmtDate(dateEnd) || 'End'].join(' – ')
    : 'Any dates';
  const landingLabel = selLandings === 'all' ? 'All landings'
    : Array.isArray(selLandings) ? `${selLandings.length} selected` : 'All landings';
  const lengthLabel = selLengths === 'all' ? 'All lengths'
    : Array.isArray(selLengths) ? `${selLengths.length} selected` : 'All lengths';

  const closePop = () => setOpenPop(null);

  return (
    <div className="tp-search-bar">
      <div className="tp-search-field-wrap">
        <SearchInput icon="📅" label="Date Range" value={dateLabel}
                     active={openPop === 'date'}
                     onClick={() => setOpenPop(openPop === 'date' ? null : 'date')}/>
        {openPop === 'date' && (
          <DatePopover start={dateStart} end={dateEnd}
                       onStart={setDateStart} onEnd={setDateEnd} onClose={closePop}/>
        )}
      </div>
      <div className="tp-search-divider"/>
      <div className="tp-search-field-wrap">
        <SearchInput icon="⚓" label="Landing" value={landingLabel}
                     active={openPop === 'landing'}
                     onClick={() => setOpenPop(openPop === 'landing' ? null : 'landing')}/>
        {openPop === 'landing' && (
          <ChecklistPopover options={window.SD.LANDINGS} value={selLandings}
                            onChange={setSelLandings} allLabel="All landings" onClose={closePop}/>
        )}
      </div>
      <div className="tp-search-divider"/>
      <div className="tp-search-field-wrap">
        <SearchInput icon="🎣" label="Trip Length" value={lengthLabel}
                     active={openPop === 'length'}
                     onClick={() => setOpenPop(openPop === 'length' ? null : 'length')}/>
        {openPop === 'length' && (
          <ChecklistPopover options={window.SD.TRIP_LENGTHS} value={selLengths}
                            onChange={setSelLengths} allLabel="All lengths" onClose={closePop}/>
        )}
      </div>
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function SidebarSection({ title, children }) {
  return (
    <div className="tp-sb-section">
      <div className="tp-sb-title">{title}</div>
      {children}
    </div>
  );
}

function SidebarFilters({ moonPhases, setMoonPhases, minWinRate, setMinWinRate,
                          minPrice, setMinPrice, maxPrice, setMaxPrice, onReset }) {
  const togglePhase = (phase) => {
    const all = moonPhases === 'all';
    const sel = all ? MOON_PHASE_OPTIONS.map(o => o.phase) : [...moonPhases];
    const next = sel.includes(phase) ? sel.filter(p => p !== phase) : [...sel, phase];
    setMoonPhases(next.length === 0 || next.length === MOON_PHASE_OPTIONS.length ? 'all' : next);
  };

  return (
    <div className="tp-sidebar">
      <div className="tp-sb-head">
        Filter by
        <button className="tp-sb-reset" onClick={onReset}>Reset all</button>
      </div>

      <SidebarSection title="Moon Phase">
        {MOON_PHASE_OPTIONS.map(opt => {
          const isBest = opt.phase === 'New' || opt.phase === 'Full';
          const checked = moonPhases === 'all' || (Array.isArray(moonPhases) && moonPhases.includes(opt.phase));
          return (
            <label key={opt.phase} className="tp-sb-check-row">
              <input type="checkbox" checked={checked} onChange={() => togglePhase(opt.phase)}/>
              <span className="tp-sb-moon-emoji">{opt.emoji}</span>
              <span className="tp-sb-check-label">{opt.label}</span>
              {opt.note && <span className="tp-sb-check-note">{opt.note}</span>}
              {isBest && <span className="tp-sb-best-dot">★</span>}
            </label>
          );
        })}
        <div className="tp-sb-hint">★ New and full moons historically produce better fishing</div>
      </SidebarSection>

      <SidebarSection title="Min Win Rate">
        {[['Any', 0], ['40%+', 0.40], ['60%+', 0.60], ['80%+', 0.80]].map(([label, val]) => (
          <label key={label} className="tp-sb-radio-row">
            <input type="radio" name="minWinRate" checked={minWinRate === val}
                   onChange={() => setMinWinRate(val)}/>
            <span>{label}</span>
          </label>
        ))}
      </SidebarSection>

      <SidebarSection title="Price Range">
        <div className="tp-sb-price-row">
          <div className="tp-sb-price-field">
            <span className="tp-sb-price-prefix">$</span>
            <input type="number" className="tp-sb-price-input" placeholder="Min"
                   value={minPrice} min="0" onChange={e => setMinPrice(e.target.value)}/>
          </div>
          <span className="tp-sb-price-dash">—</span>
          <div className="tp-sb-price-field">
            <span className="tp-sb-price-prefix">$</span>
            <input type="number" className="tp-sb-price-input" placeholder="Max"
                   value={maxPrice} min="0" onChange={e => setMaxPrice(e.target.value)}/>
          </div>
        </div>
      </SidebarSection>
    </div>
  );
}

// ── Mobile filter sheet ───────────────────────────────────────────────────────
function MobileFilterSheet({ open, onClose, ...filterProps }) {
  useEffect(() => {
    if (!open) return;
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="tp-sheet-backdrop" onClick={onClose}>
      <div className="tp-sheet" onClick={e => e.stopPropagation()}>
        <div className="tp-sheet-head">
          <span className="tp-sheet-title">Filters</span>
          <button className="tp-sheet-close" onClick={onClose}>✕</button>
        </div>
        <div className="tp-sheet-body">
          <SidebarFilters {...filterProps}/>
        </div>
        <div className="tp-sheet-foot">
          <button className="btn ghost" onClick={() => { filterProps.onReset(); onClose(); }}>Reset</button>
          <button className="tp-apply-btn" onClick={onClose}>Apply</button>
        </div>
      </div>
    </div>
  );
}

// ── Main TripPlanner ──────────────────────────────────────────────────────────
function TripPlanner({ navigate }) {
  // Top bar filter state
  const [dateStart, setDateStart]   = useState('');
  const [dateEnd, setDateEnd]       = useState('');
  const [selLandings, setSelLandings] = useState('all');
  const [selLengths, setSelLengths]   = useState('all');
  const [openPop, setOpenPop]         = useState(null);

  // Sidebar filter state
  const [moonPhases, setMoonPhases]   = useState('all');
  const [minWinRate, setMinWinRate]   = useState(0);
  const [minPrice, setMinPrice]       = useState('');
  const [maxPrice, setMaxPrice]       = useState('');

  // Display state
  const [activeTab, setActiveTab]         = useState('best');
  const [sortBy, setSortBy]               = useState('recommended');
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  // Close popovers on outside click
  useEffect(() => {
    if (!openPop) return;
    const handler = () => setOpenPop(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [openPop]);

  const winRates = useMemo(() => SDA.boatWinRates(), []);

  // Avg TPA per boat+length from historical trip data
  const avgTpaByKey = useMemo(() => {
    const acc = {};
    (window.SD.TRIPS || []).forEach(t => {
      if (t.trophyPerAnglerPerDay == null) return;
      const k = `${t.boat}|${t.tripLength}`;
      acc[k] = acc[k] || { sum: 0, n: 0 };
      acc[k].sum += t.trophyPerAnglerPerDay;
      acc[k].n++;
    });
    const out = {};
    for (const [k, v] of Object.entries(acc)) {
      if (v.n >= 3) out[k] = Math.round((v.sum / v.n) * 100) / 100;
    }
    return out;
  }, []);

  const _matches = (val, filter) => {
    if (filter == null || filter === 'all' || filter === '') return true;
    const sel = Array.isArray(filter) ? filter : [filter];
    return sel.length === 0 || sel.map(String).includes(String(val));
  };

  // Filter schedule
  const filtered = useMemo(() => {
    const now = new Date();
    const DAY_MS = 86400000;
    const selPhases = Array.isArray(moonPhases) ? moonPhases : null;
    const minP = minPrice !== '' ? parseFloat(minPrice) : null;
    const maxP = maxPrice !== '' ? parseFloat(maxPrice) : null;

    return (window.SD.SCHEDULE || []).filter(s => {
      const dep = new Date(s.departureAt);
      if (dep < now) return false;
      if (dateStart && dep < new Date(dateStart + 'T00:00:00')) return false;
      if (dateEnd   && dep > new Date(dateEnd   + 'T23:59:59')) return false;
      if (!_matches(s.landing,    selLandings)) return false;
      if (!_matches(s.tripLength, selLengths))  return false;
      if (minP != null && s.price != null && s.price < minP) return false;
      if (maxP != null && s.price != null && s.price > maxP) return false;
      if (selPhases && selPhases.length > 0) {
        const nearby = [
          moonInfo(dep).phase,
          moonInfo(new Date(dep.getTime() - DAY_MS)).phase,
          moonInfo(new Date(dep.getTime() + DAY_MS)).phase,
        ];
        if (!nearby.some(p => selPhases.includes(p))) return false;
      }
      if (minWinRate > 0) {
        const wr = winRates[`${s.boat}|${s.tripLength}`];
        if (!wr || wr.winRate < minWinRate) return false;
      }
      return true;
    });
  }, [dateStart, dateEnd, selLandings, selLengths, moonPhases, minWinRate, minPrice, maxPrice, winRates]);

  // Enrich with win rate + sort
  const displayed = useMemo(() => {
    const enriched = filtered.map(s => {
      const wr = winRates[`${s.boat}|${s.tripLength}`];
      return { ...s, _winRate: wr ? wr.winRate : null, _trips: wr ? wr.total : 0 };
    });
    const copy = [...enriched];
    switch (sortBy) {
      case 'price-asc':
        return copy.sort((a, b) => a.price == null ? 1 : b.price == null ? -1 : a.price - b.price);
      case 'price-desc':
        return copy.sort((a, b) => a.price == null ? 1 : b.price == null ? -1 : b.price - a.price);
      case 'date':
        return copy.sort((a, b) => new Date(a.departureAt) - new Date(b.departureAt));
      case 'spots':
        return copy.sort((a, b) => (b.openSpots ?? 0) - (a.openSpots ?? 0));
      case 'win-rate':
      case 'recommended':
      default:
        return copy.sort((a, b) => {
          if (a._winRate == null && b._winRate == null) return a.price == null ? 1 : b.price == null ? -1 : a.price - b.price;
          if (a._winRate == null) return 1;
          if (b._winRate == null) return -1;
          return b._winRate - a._winRate;
        });
    }
  }, [filtered, sortBy, winRates]);

  const minPriceVal = useMemo(() => {
    const prices = filtered.map(s => s.price).filter(p => p != null);
    return prices.length ? Math.min(...prices) : null;
  }, [filtered]);

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    setSortBy(tab === 'best' ? 'recommended' : 'price-asc');
  };

  const handleReset = () => {
    setDateStart(''); setDateEnd('');
    setSelLandings('all'); setSelLengths('all');
    setMoonPhases('all'); setMinWinRate(0);
    setMinPrice(''); setMaxPrice('');
  };

  const activeFilterCount =
    (dateStart || dateEnd ? 1 : 0) +
    (Array.isArray(selLandings) ? 1 : 0) +
    (Array.isArray(selLengths)  ? 1 : 0) +
    (Array.isArray(moonPhases)  ? 1 : 0) +
    (minWinRate > 0 ? 1 : 0) +
    (minPrice || maxPrice ? 1 : 0);

  const sidebarProps = { moonPhases, setMoonPhases, minWinRate, setMinWinRate,
                         minPrice, setMinPrice, maxPrice, setMaxPrice, onReset: handleReset };

  return (
    <Fragment>
      <Crumbs items={[
        { label: 'Sportfish', onClick: () => navigate('today') },
        { label: 'Plan' },
        { label: 'Trip Planner' },
      ]}/>

      {/* Page title */}
      <div className="pagehead">
        <div>
          <h1>Trip Planner</h1>
          <div className="sub">Find and book upcoming open-party fishing trips</div>
        </div>
      </div>

      {/* Top search bar — stop click from propagating to doc (would close popovers) */}
      <div className="tp-search-wrap" onClick={e => e.stopPropagation()}>
        <TopSearchBar
          dateStart={dateStart} dateEnd={dateEnd}
          setDateStart={setDateStart} setDateEnd={setDateEnd}
          selLandings={selLandings} setSelLandings={setSelLandings}
          selLengths={selLengths}   setSelLengths={setSelLengths}
          openPop={openPop} setOpenPop={setOpenPop}
        />
      </div>

      {/* Body: sidebar + results */}
      <div className="tp-body">
        {/* Desktop sidebar */}
        <div className="tp-sidebar-wrap">
          <SidebarFilters {...sidebarProps}/>
        </div>

        {/* Results */}
        <div className="tp-results">
          {/* Results header */}
          <div className="tp-results-head">
            <div className="tp-results-count">
              <strong>{fmt.n(displayed.length)}</strong> upcoming trip{displayed.length !== 1 ? 's' : ''}
            </div>
            <div className="tp-results-controls">
              {/* Mobile filter button */}
              <button className="tp-mobile-filter-btn" onClick={() => setMobileFiltersOpen(true)}>
                <i className="fa-solid fa-sliders"></i>
                Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
              </button>
              {/* Sort dropdown */}
              <div className="tp-sort-wrap">
                <label className="tp-sort-label">Sort:</label>
                <select className="tp-sort-select" value={sortBy} onChange={e => setSortBy(e.target.value)}>
                  <option value="recommended">Recommended</option>
                  <option value="price-asc">Price: Low to High</option>
                  <option value="price-desc">Price: High to Low</option>
                  <option value="date">Departure Date</option>
                  <option value="win-rate">Win Rate</option>
                  <option value="spots">Open Spots</option>
                </select>
              </div>
            </div>
          </div>

          {/* Best / Cheapest tabs */}
          <div className="tp-tabs2">
            <button className={`tp-tab2${activeTab === 'best' ? ' active' : ''}`}
                    onClick={() => handleTabChange('best')}>
              <span className="tp-tab2-main">Best <span className="tp-tab2-info">ⓘ</span></span>
              <span className="tp-tab2-sub">Ranked by win rate</span>
            </button>
            <button className={`tp-tab2${activeTab === 'cheapest' ? ' active' : ''}`}
                    onClick={() => handleTabChange('cheapest')}>
              <span className="tp-tab2-main">
                Cheapest
                {minPriceVal != null && <span className="tp-tab2-price"> from ${minPriceVal.toFixed(0)}</span>}
                <span className="tp-tab2-info">ⓘ</span>
              </span>
              <span className="tp-tab2-sub">Sorted by price</span>
            </button>
          </div>

          {/* Trip list */}
          {displayed.length === 0 ? (
            <div className="tp-empty">
              <i className="fa-solid fa-fish" style={{fontSize:24, opacity:0.3}}></i>
              <div>No trips match your filters.</div>
              <button className="tp-empty-reset" onClick={handleReset}>Clear all filters</button>
            </div>
          ) : (
            <div className="tp-card-list">
              {displayed.map(s => (
                <TripCard key={`${s.landing}-${s.sourceId}`} s={s} avgTpaByKey={avgTpaByKey}/>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Mobile filter sheet */}
      <MobileFilterSheet open={mobileFiltersOpen} onClose={() => setMobileFiltersOpen(false)}
                         {...sidebarProps}/>
    </Fragment>
  );
}

Object.assign(window, { TripPlanner });
