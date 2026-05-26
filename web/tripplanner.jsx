// Trip Planner — Expedia-style redesign
const { useState, useMemo, useEffect, Fragment } = React;

// ── Moon helpers ─────────────────────────────────────────────────────────────
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

// ── Per-landing booking URL (with UTM params via TTTrack.buildUrl) ────────────
function bookingUrl(s) {
  let base = null;
  switch (s.landing) {
    case 'Point Loma Sportfishing':
      base = `https://pointloma.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
      break;
    case 'Seaforth Sportfishing':
      base = `https://seaforth.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
      break;
    case "Fisherman's Landing":
      base = `https://fishermanslanding.fishingreservations.net/resos/user.php?trip_id=${encodeURIComponent(s.sourceId)}`;
      break;
    case 'H&M Landing': {
      const slug = (s.boat || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
      base = slug ? `https://www.hmlanding.com/boat/${slug}` : null;
      break;
    }
    default: break;
  }
  if (!base) return null;
  if (window.TTTrack?.buildUrl) {
    const dep = s.departureAt ? s.departureAt.slice(0, 10) : '';
    return TTTrack.buildUrl(base, s.boat, s.landing, dep);
  }
  return base;
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

const MONTH_NAMES_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const MONTH_NAMES_FULL  = ['January','February','March','April','May','June',
                            'July','August','September','October','November','December'];

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

function SpotsBadge({ spots, capacity }) {
  if (capacity != null) {
    if (spots == null || spots === 0)
      return <span className="tp-badge tp-spots-full">Full</span>;
    const pct = spots / capacity;
    const cls = pct >= 0.3 ? 'tp-spots-green' : pct >= 0.15 ? 'tp-spots-yellow' : 'tp-spots-red';
    return <span className={`tp-badge ${cls}`}>{spots} / {capacity} open</span>;
  }
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

function StatusBadge({ status }) {
  if (!status) return null;
  const cls = status === 'Definite Go' ? 'tp-status-go'
            : status === 'Cancelled'   ? 'tp-status-cancelled'
            : 'tp-status-scheduled';
  const icon = status === 'Definite Go' ? '✓' : status === 'Cancelled' ? '✕' : '•';
  return <span className={`tp-status-badge ${cls}`}>{icon} {status}</span>;
}

// Highlights species, included, additional, required keywords inline
const _HL_RE = /\b(NOT\s+required|tuna|bluefin|yellowfin|yellowtail|dorado|albacore|skipjack|includes?|included|additional|extra|required)\b/gi;

function HighlightedNote({ text }) {
  if (!text) return null;
  const parts = [];
  let last = 0;
  _HL_RE.lastIndex = 0;
  let m;
  while ((m = _HL_RE.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const w = m[0].toLowerCase();
    const cls = /tuna|bluefin/.test(w)     ? 'tp-hl-bluefin'
              : /yellowfin/.test(w)         ? 'tp-hl-yellowfin'
              : /yellowtail/.test(w)        ? 'tp-hl-yellowtail'
              : /dorado/.test(w)            ? 'tp-hl-dorado'
              : /albacore|skipjack/.test(w) ? 'tp-hl-albacore'
              : /not\s+required/.test(w)    ? 'tp-hl-ok'
              : /includes?|included/.test(w)? 'tp-hl-ok'
              : /additional|extra/.test(w)  ? 'tp-hl-warn'
              : /required/.test(w)          ? 'tp-hl-warn'
              : '';
    parts.push(<mark key={m.index} className={`tp-hl ${cls}`}>{m[0]}</mark>);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

// ── Trip card ─────────────────────────────────────────────────────────────────
const NOTE_LINES = 2; // lines visible when collapsed

function TripCard({ s, avgTpaByKey, context }) {
  const [noteOpen, setNoteOpen] = useState(false);

  const dep    = new Date(s.departureAt);
  const ret    = s.returnAt ? new Date(s.returnAt) : null;
  const moon   = moonInfo(dep);
  const moonC  = moonColor(moon.illum);
  const price  = s.price != null ? `$${s.price.toFixed(0)}` : null;
  const url    = bookingUrl(s);
  const tpaKey = `${s.boat}|${s.tripLength}`;
  const avgTpa = avgTpaByKey ? avgTpaByKey[tpaKey] : null;

  const trackClick = () => {
    if (window.TTTrack) TTTrack.tripClick({ ...s, moonPhase: moon.phase }, context || {});
  };

  const capPct      = s.capacity ? Math.round((s.openSpots / s.capacity) * 100) : null;
  const capBarColor = capPct >= 30 ? '#34D399' : capPct >= 15 ? '#FBBF24' : '#F87171';
  const hasNote     = !!(s.note || s.tripStatus || s.targetSpecies || s.whatsIncluded);

  const boatEl = url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className="tp-card-boat-link">
      {s.boat}
    </a>
  ) : <span className="tp-card-boat-name">{s.boat}</span>;

  const TimeRow = ({ label, dt }) => (
    <div className="tp-card-time-row">
      <span className="tp-card-time-label">{label}</span>
      <span className="tp-card-depart-date">{fmtDepDate(dt)}</span>
      <span className="tp-card-depart-sep"> · </span>
      <span className="tp-card-depart-time">{fmtTime(dt)}</span>
    </div>
  );

  return (
    <div className="tp-card">
      {/* LEFT — boat info */}
      <div className="tp-card-left">
        <div className="tp-card-boat">{boatEl}</div>
        <div className="tp-card-landing">{shortLanding(s.landing)}</div>
        <LengthBadge label={s.tripLength}/>
      </div>

      {/* MIDDLE — times + stats */}
      <div className="tp-card-middle">
        <div className="tp-card-times">
          <TimeRow label="Dep" dt={dep}/>
          {ret && <TimeRow label="Ret" dt={ret}/>}
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
          <div className="tp-card-tpa">Avg TPA: <strong>{avgTpa.toFixed(2)}</strong>/day</div>
        )}
        {s.capacity != null && (
          <div className="tp-card-cap-row">
            <div className="tp-card-cap-bar-wrap">
              <div className="tp-card-cap-bar-fill" style={{width:`${capPct}%`, background:capBarColor}}/>
            </div>
            <span className="tp-card-cap-label">{s.openSpots} of {s.capacity} open</span>
          </div>
        )}
      </div>

      {/* RIGHT — price + booking */}
      <div className="tp-card-right">
        {s.tripStatus && <StatusBadge status={s.tripStatus}/>}
        {price
          ? <><div className="tp-card-price">{price}</div><div className="tp-card-per">per person</div></>
          : <div className="tp-card-price tp-card-price-na">—</div>
        }
        <SpotsBadge spots={s.openSpots} capacity={s.capacity}/>
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer" className="tp-card-book-btn"
             onClick={trackClick}>
            View Trip →
          </a>
        )}
      </div>

      {/* NOTES STRIP — full width, collapsible */}
      {hasNote && (
        <div className={`tp-card-notes-strip${noteOpen ? ' open' : ''}`}>
          <button className="tp-card-notes-toggle" onClick={() => setNoteOpen(o => !o)}>
            <i className={`fa-solid fa-chevron-${noteOpen ? 'up' : 'down'} tp-card-notes-chevron`}/>
            {noteOpen ? 'Hide details' : 'Trip details'}
          </button>
          {noteOpen && (
            <div className="tp-card-notes-body">
              {s.tripStatus && (
                <div className="tp-card-notes-status"><StatusBadge status={s.tripStatus}/></div>
              )}
              {s.targetSpecies && (
                <div className="tp-card-notes-row">
                  <span className="tp-card-notes-key">Targeting</span>
                  <span className="tp-card-notes-val">{s.targetSpecies}</span>
                </div>
              )}
              {s.whatsIncluded && (
                <div className="tp-card-notes-row">
                  <span className="tp-card-notes-key">Includes</span>
                  <span className="tp-card-notes-val tp-hl-ok">{s.whatsIncluded}</span>
                </div>
              )}
              {s.note && (
                <div className="tp-card-notes-text">
                  <HighlightedNote text={s.note}/>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* MOBILE footer row */}
      <div className="tp-card-mobile-footer">
        <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
          {s.tripStatus && <StatusBadge status={s.tripStatus}/>}
          <WinRateBadge wr={s._winRate}/>
          <SpotsBadge spots={s.openSpots} capacity={s.capacity}/>
          {price && <span className="tp-card-price-mobile">{price}</span>}
        </div>
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer" className="tp-card-book-btn tp-card-book-full"
             onClick={trackClick}>
            View Trip →
          </a>
        )}
      </div>
    </div>
  );
}

// ── Month popover ─────────────────────────────────────────────────────────────
function MonthPopover({ selMonth, onSelect, onClose, tripMonths }) {
  const now = new Date();
  const curYear  = now.getFullYear();
  const curMonth = now.getMonth();

  // 12 months starting from current
  const months = [];
  for (let i = 0; i < 12; i++) {
    const totalMonth = curMonth + i;
    const m = totalMonth % 12;
    const y = curYear + Math.floor(totalMonth / 12);
    const key = `${y}-${String(m + 1).padStart(2, '0')}`;
    months.push({ year: y, month: m, key, hasTrips: tripMonths.has(key) });
  }

  return (
    <div className="tp-popover tp-popover-month">
      <div className="tp-pop-month-grid">
        {months.map(m => {
          const isSel = selMonth && selMonth.year === m.year && selMonth.month === m.month;
          return (
            <button
              key={m.key}
              className={`tp-pop-month-cell${isSel ? ' selected' : ''}${!m.hasTrips ? ' disabled' : ''}`}
              disabled={!m.hasTrips}
              onClick={() => { onSelect({ year: m.year, month: m.month }); onClose(); }}
            >
              <div className="tp-pop-month-abbr">{MONTH_NAMES_SHORT[m.month]}</div>
              <div className="tp-pop-month-yr">{m.year !== curYear ? m.year : ''}</div>
            </button>
          );
        })}
      </div>
      <div className="tp-pop-footer">
        <button className="tp-pop-clear" onClick={() => { onSelect(null); onClose(); }}>Any month</button>
        <button className="tp-pop-done" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}

// ── SearchInput pill ──────────────────────────────────────────────────────────
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

// ── Checklist popover (landing / trip length) ─────────────────────────────────
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
        <input type="checkbox" checked={allSelected} onChange={() => onChange('all')}/>
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

// ── Top search bar ────────────────────────────────────────────────────────────
function TopSearchBar({ selMonth, setSelMonth, tripMonths,
                        selLandings, setSelLandings, selLengths, setSelLengths,
                        openPop, setOpenPop }) {
  const monthLabel = selMonth
    ? `${MONTH_NAMES_FULL[selMonth.month]} ${selMonth.year}`
    : 'Any Month';
  const landingLabel = selLandings === 'all' ? 'All Landings'
    : Array.isArray(selLandings) ? `${selLandings.length} selected` : 'All Landings';
  const lengthLabel = selLengths === 'all' ? 'All Lengths'
    : Array.isArray(selLengths) ? `${selLengths.length} selected` : 'All Lengths';

  const closePop = () => setOpenPop(null);

  return (
    <div className="tp-search-bar">
      <div className="tp-search-field-wrap">
        <SearchInput icon="📅" label="When" value={monthLabel}
                     active={openPop === 'month'}
                     onClick={() => setOpenPop(openPop === 'month' ? null : 'month')}/>
        {openPop === 'month' && (
          <MonthPopover selMonth={selMonth} onSelect={setSelMonth}
                        onClose={closePop} tripMonths={tripMonths}/>
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

function RefineDatesSection({ selMonth, refineStart, setRefineStart, refineEnd, setRefineEnd }) {
  if (!selMonth) return null;

  const firstDay = `${selMonth.year}-${String(selMonth.month + 1).padStart(2, '0')}-01`;
  const lastDay  = new Date(selMonth.year, selMonth.month + 1, 0).toISOString().slice(0, 10);

  return (
    <SidebarSection title="Refine Dates">
      <div className="tp-sb-refine-hint">Optional — narrow by specific dates</div>
      <div className="tp-sb-refine-row">
        <div className="tp-sb-refine-field">
          <label className="tp-sb-refine-label">From</label>
          <input type="date" className="tp-sb-refine-input"
                 value={refineStart} min={firstDay} max={lastDay}
                 onChange={e => setRefineStart(e.target.value)}/>
        </div>
        <div className="tp-sb-refine-field">
          <label className="tp-sb-refine-label">To</label>
          <input type="date" className="tp-sb-refine-input"
                 value={refineEnd} min={firstDay} max={lastDay}
                 onChange={e => setRefineEnd(e.target.value)}/>
        </div>
      </div>
      {(refineStart || refineEnd) && (
        <button className="tp-sb-refine-clear"
                onClick={() => { setRefineStart(''); setRefineEnd(''); }}>
          Clear dates
        </button>
      )}
    </SidebarSection>
  );
}

function SidebarFilters({ selMonth, refineStart, setRefineStart, refineEnd, setRefineEnd,
                          moonPhases, setMoonPhases, minWinRate, setMinWinRate,
                          minPrice, setMinPrice, maxPrice, setMaxPrice, onReset }) {
  const togglePhase = (phase) => {
    const sel = moonPhases === 'all' ? MOON_PHASE_OPTIONS.map(o => o.phase) : [...moonPhases];
    const next = sel.includes(phase) ? sel.filter(p => p !== phase) : [...sel, phase];
    setMoonPhases(next.length === 0 || next.length === MOON_PHASE_OPTIONS.length ? 'all' : next);
  };

  return (
    <div className="tp-sidebar">
      <div className="tp-sb-head">
        Filter by
        <button className="tp-sb-reset" onClick={onReset}>Reset all</button>
      </div>

      <RefineDatesSection selMonth={selMonth}
                          refineStart={refineStart} setRefineStart={setRefineStart}
                          refineEnd={refineEnd} setRefineEnd={setRefineEnd}/>

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
  const _now = new Date();

  // Top bar filters
  const [selMonth, setSelMonthRaw] = useState({ year: _now.getFullYear(), month: _now.getMonth() });
  const [selLandings, setSelLandings] = useState('all');
  const [selLengths,  setSelLengths]  = useState('all');
  const [openPop, setOpenPop]         = useState(null);

  // Sidebar filters
  const [refineStart, setRefineStart] = useState('');
  const [refineEnd,   setRefineEnd]   = useState('');
  const [moonPhases,  setMoonPhases]  = useState('all');
  const [minWinRate,  setMinWinRate]  = useState(0);
  const [minPrice,    setMinPrice]    = useState('');
  const [maxPrice,    setMaxPrice]    = useState('');

  // Display state
  const [activeTab,         setActiveTab]         = useState('best');
  const [sortBy,            setSortBy]            = useState('recommended');
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  // Clear refine dates when month changes; fire filter tracking
  const setSelMonth = (m) => {
    setSelMonthRaw(m);
    setRefineStart('');
    setRefineEnd('');
    if (m && window.TTTrack) TTTrack.filterApplied('month', `${MONTH_NAMES_SHORT[m.month]} ${m.year}`);
  };

  // Tracked filter setters
  const setSelLandingsTracked = (v) => {
    setSelLandings(v);
    if (window.TTTrack) TTTrack.filterApplied('landing', v);
  };
  const setSelLengthsTracked = (v) => {
    setSelLengths(v);
    if (window.TTTrack) TTTrack.filterApplied('trip_length', v);
  };
  const setMoonPhasesTracked = (v) => {
    setMoonPhases(v);
    if (window.TTTrack) TTTrack.filterApplied('moon_phase', v);
  };
  const setMinWinRateTracked = (v) => {
    setMinWinRate(v);
    if (window.TTTrack && v > 0) TTTrack.filterApplied('win_rate', `${Math.round(v * 100)}%+`);
  };

  // Close popovers on outside click
  useEffect(() => {
    if (!openPop) return;
    const handler = () => setOpenPop(null);
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [openPop]);

  const winRates = useMemo(() => SDA.boatWinRates(), []);

  // Set of 'YYYY-MM' keys that have upcoming trips
  const tripMonths = useMemo(() => {
    const now = new Date();
    const s = new Set();
    (window.SD.SCHEDULE || []).forEach(t => {
      const dep = new Date(t.departureAt);
      if (dep >= now) {
        s.add(`${dep.getFullYear()}-${String(dep.getMonth() + 1).padStart(2, '0')}`);
      }
    });
    return s;
  }, []);

  // Avg TPA per boat+length key
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

  const filtered = useMemo(() => {
    const now = new Date();
    const DAY_MS = 86400000;
    const selPhases = Array.isArray(moonPhases) ? moonPhases : null;
    const minP = minPrice !== '' ? parseFloat(minPrice) : null;
    const maxP = maxPrice !== '' ? parseFloat(maxPrice) : null;

    return (window.SD.SCHEDULE || []).filter(s => {
      const dep = new Date(s.departureAt);
      if (dep < now) return false;

      // Month filter
      if (selMonth) {
        if (dep.getFullYear() !== selMonth.year || dep.getMonth() !== selMonth.month) return false;
      }
      // Refine date range within selected month
      if (refineStart && dep < new Date(refineStart + 'T00:00:00')) return false;
      if (refineEnd   && dep > new Date(refineEnd   + 'T23:59:59')) return false;

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
  }, [selMonth, refineStart, refineEnd, selLandings, selLengths, moonPhases, minWinRate, minPrice, maxPrice, winRates]);

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
    if (window.TTTrack) TTTrack.tabSwitch(tab);
  };

  const handleReset = () => {
    const n = new Date();
    setSelMonth({ year: n.getFullYear(), month: n.getMonth() });
    setSelLandings('all'); setSelLengths('all');
    setMoonPhases('all'); setMinWinRate(0);
    setMinPrice(''); setMaxPrice('');
    // refineStart/End cleared by setSelMonth above
  };

  const activeFilterCount =
    (!selMonth ? 1 : (selMonth.year !== _now.getFullYear() || selMonth.month !== _now.getMonth() ? 1 : 0)) +
    (refineStart || refineEnd ? 1 : 0) +
    (Array.isArray(selLandings) ? 1 : 0) +
    (Array.isArray(selLengths)  ? 1 : 0) +
    (Array.isArray(moonPhases)  ? 1 : 0) +
    (minWinRate > 0 ? 1 : 0) +
    (minPrice || maxPrice ? 1 : 0);

  const sidebarProps = {
    selMonth, refineStart, setRefineStart, refineEnd, setRefineEnd,
    moonPhases, setMoonPhases: setMoonPhasesTracked,
    minWinRate, setMinWinRate: setMinWinRateTracked,
    minPrice, setMinPrice, maxPrice, setMaxPrice, onReset: handleReset,
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
          <div className="sub">Find and book upcoming open-party fishing trips</div>
        </div>
      </div>

      {/* Top search bar */}
      <div className="tp-search-wrap" onClick={e => e.stopPropagation()}>
        <TopSearchBar
          selMonth={selMonth} setSelMonth={setSelMonth} tripMonths={tripMonths}
          selLandings={selLandings} setSelLandings={setSelLandingsTracked}
          selLengths={selLengths}   setSelLengths={setSelLengthsTracked}
          openPop={openPop} setOpenPop={setOpenPop}
        />
      </div>

      {/* Body: sidebar + results */}
      <div className="tp-body">
        <div className="tp-sidebar-wrap">
          <SidebarFilters {...sidebarProps}/>
        </div>

        <div className="tp-results">
          <div className="tp-results-head">
            <div className="tp-results-count">
              <strong>{fmt.n(displayed.length)}</strong> upcoming trip{displayed.length !== 1 ? 's' : ''}
              {selMonth && <span className="tp-results-month"> in {MONTH_NAMES_FULL[selMonth.month]}</span>}
            </div>
            <div className="tp-results-controls">
              <button className="tp-mobile-filter-btn" onClick={() => setMobileFiltersOpen(true)}>
                <i className="fa-solid fa-sliders"></i>
                Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
              </button>
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

          {displayed.length === 0 ? (
            <div className="tp-empty">
              <i className="fa-solid fa-fish" style={{fontSize:24, opacity:0.3}}></i>
              <div>No trips match your filters.</div>
              <button className="tp-empty-reset" onClick={handleReset}>Clear all filters</button>
            </div>
          ) : (
            <div className="tp-card-list">
              {displayed.map((s, idx) => (
                <TripCard key={`${s.landing}-${s.sourceId}`} s={s} avgTpaByKey={avgTpaByKey}
                          context={{
                            tab:      activeTab,
                            position: idx + 1,
                            filters:  activeFilterCount,
                            month:    selMonth ? `${MONTH_NAMES_SHORT[selMonth.month]} ${selMonth.year}` : null,
                          }}/>
              ))}
            </div>
          )}
        </div>
      </div>

      <MobileFilterSheet open={mobileFiltersOpen} onClose={() => setMobileFiltersOpen(false)}
                         {...sidebarProps}/>
    </Fragment>
  );
}

Object.assign(window, { TripPlanner });
