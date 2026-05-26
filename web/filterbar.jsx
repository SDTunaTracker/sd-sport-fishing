// Filter bar — global filters across the app
const { useState, useMemo, useEffect, useRef, Fragment } = React;

// Dropdown that opens a checkbox panel, letting the user pick multiple options.
// `value` is either 'all' (no filter) or an array of selected option values.
// `options` accepts either plain strings ['a','b'] or objects [{value,label}].
function MultiSelect({ options, value, onChange, allLabel = 'All' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  // Normalise options so we can mix strings and {value,label} objects.
  const opts = options.map(o => typeof o === 'object' && o !== null ? o : { value: String(o), label: String(o) });
  const labelByValue = Object.fromEntries(opts.map(o => [o.value, o.label]));

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const isAll = value === 'all' || value == null || (Array.isArray(value) && value.length === 0);
  const selected = isAll ? [] : (Array.isArray(value) ? value : [value]);

  const toggle = (val) => {
    if (selected.includes(val)) {
      const next = selected.filter(v => v !== val);
      onChange(next.length === 0 ? 'all' : next);
    } else {
      onChange([...selected, val]);
    }
  };

  const display = isAll
    ? allLabel
    : selected.length === 1
      ? (labelByValue[selected[0]] || selected[0])
      : selected.length <= 2
        ? selected.map(v => labelByValue[v] || v).join(', ')
        : `${selected.length} selected`;

  return (
    <div ref={ref} className="multiselect">
      <button type="button" className="multiselect-trigger" onClick={() => setOpen(o => !o)}>
        <span className="ms-text">{display}</span>
        <span className="ms-caret">▾</span>
      </button>
      {open && (
        <div className="multiselect-panel">
          <label className="ms-row">
            <input type="checkbox" checked={isAll} onChange={() => onChange('all')}/>
            <span>{allLabel}</span>
          </label>
          <div className="ms-divider"></div>
          {opts.map(o => (
            <label key={o.value} className="ms-row">
              <input type="checkbox" checked={selected.includes(o.value)} onChange={() => toggle(o.value)}/>
              <span>{o.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterBar({ filters, setFilters, hideBoat }) {
  const update = (k, v) => setFilters({ ...filters, [k]: v });
  return (
    <div className="filterbar">
      <div className="filter">
        <label>Year</label>
        <MultiSelect
          options={[...new Set(window.SD.TRIPS.map(t => t.year))].sort((a,b) => b-a)
            .map(y => ({ value: String(y), label: String(y) }))}
          value={filters.year}
          onChange={v => update('year', v)}
          allLabel="All Years"/>
      </div>
      <div className="filter">
        <label>Month</label>
        <MultiSelect
          options={MONTH_NAMES.map((m, i) => ({ value: String(i+1), label: m }))}
          value={filters.month}
          onChange={v => update('month', v)}
          allLabel="All Months"/>
      </div>
      <div className="filter-divider"></div>
      <div className="filter">
        <label>Landing</label>
        <MultiSelect
          options={window.SD.LANDINGS}
          value={filters.landing}
          onChange={v => update('landing', v)}
          allLabel="All Landings"/>
      </div>
      {!hideBoat && (
        <div className="filter">
          <label>Boat</label>
          <MultiSelect
            options={[...window.SD.BOATS].sort((a,b) => a.name.localeCompare(b.name)).map(b => b.name)}
            value={filters.boat}
            onChange={v => update('boat', v)}
            allLabel="All Boats"/>
        </div>
      )}
      <div className="filter">
        <label>Trip Length</label>
        <MultiSelect
          options={window.SD.TRIP_LENGTHS}
          value={filters.tripLength}
          onChange={v => update('tripLength', v)}
          allLabel="All Lengths"/>
      </div>
      <div className="filter">
        <label>Species</label>
        <MultiSelect
          options={window.SD.SPECIES}
          value={filters.species}
          onChange={v => update('species', v)}
          allLabel="All Tuna"/>
      </div>
      <div className="filter-divider"></div>
      <div className="filter" style={{minWidth: 100}}>
        <label>Min Trips</label>
        <input type="number" min="0" max="100" value={filters.minTrips}
               onChange={e => update('minTrips', +e.target.value || 0)} />
      </div>
      <div className="spacer" style={{flex: 1}}></div>
      <div className="row" style={{alignSelf: 'flex-end', gap: 8}}>
        <span className="filter-pill" onClick={() => setFilters({ ...DEFAULT_FILTERS })}>
          <i className="fa-solid fa-rotate-left"></i> Reset
        </span>
      </div>
    </div>
  );
}

const DEFAULT_FILTERS = {
  year: String(new Date().getFullYear()),
  month: 'all',
  landing: 'all',
  boat: 'all',
  tripLength: 'all',
  species: 'all',
  minTrips: 1,
  includeZero: false,
};

Object.assign(window, { FilterBar, DEFAULT_FILTERS });
