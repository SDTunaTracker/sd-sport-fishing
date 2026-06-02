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

function FilterBar({ filters, setFilters, hideBoat, regions }) {
  const update = (k, v) => setFilters({ ...filters, [k]: v });

  // Compute region-scoped landing and boat options
  const regionLandings = useMemo(() => {
    if (!regions || !window.getEffectiveRegion) return null;
    const eff = window.getEffectiveRegion(regions);
    return window.getLandingsForRegion ? window.getLandingsForRegion(eff) : null;
  }, [regions]);

  const landingOptions = useMemo(() => {
    const all = window.SD.LANDINGS;
    return regionLandings ? all.filter(l => regionLandings.includes(l)) : all;
  }, [regionLandings]);

  const boatOptions = useMemo(() => {
    return [...window.SD.BOATS]
      .filter(b => !regionLandings || regionLandings.includes(b.landing))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(b => b.name);
  }, [regionLandings]);

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
          options={landingOptions}
          value={filters.landing}
          onChange={v => update('landing', v)}
          allLabel="All Landings"/>
      </div>
      {!hideBoat && (
        <div className="filter">
          <label>Boat</label>
          <MultiSelect
            options={boatOptions}
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
  includeZero: true,
};

// ── AnalyticsFilterBar ────────────────────────────────────────────────────────
// Unified collapsed-chips + expandable panel FilterBar for the Analytics section
// and Trip Planner.
//
//   filters / setFilters — the committed filter state
//   fields              — which fields to show in the panel; ALL active fields
//                         still appear as chips regardless
//   regions             — for scoping landing/boat options

const _CHIP_ORDER = ['year', 'month', 'landing', 'boat', 'tripLength', 'species', 'minTrips'];

function _fieldLabel(key, val) {
  const df = window.DEFAULT_FILTERS;
  // Not active
  if (val === 'all' || val === df[key] || val == null) return null;
  if (Array.isArray(val) && val.length === 0) return null;
  if (key === 'minTrips' && +val === +df.minTrips) return null;

  const shorten = (v) => String(v).replace(' Sportfishing', '').replace(' Landing', '');
  const fmtArr  = (arr) => {
    const a = Array.isArray(arr) ? arr : [arr];
    const labels = a.map(shorten);
    if (labels.length <= 2) return labels.join(', ');
    return `${labels.slice(0, 2).join(', ')} +${labels.length - 2}`;
  };

  if (key === 'month') {
    const a = Array.isArray(val) ? val : [val];
    const names = a.map(m => (MONTH_NAMES[+m - 1] || m));
    if (names.length <= 2) return names.join(', ');
    return `${names.slice(0, 2).join(', ')} +${names.length - 2}`;
  }
  if (key === 'minTrips') return `min ${val}`;
  return fmtArr(val);
}

function AnalyticsFilterBar({ filters, setFilters, fields, regions }) {
  const { useState, useEffect, useRef, useMemo } = React;
  const [expanded, setExpanded]   = useState(false);
  const [draft,    setDraft]       = useState(null);
  const wrapRef                    = useRef(null);
  const df                         = window.DEFAULT_FILTERS;

  // Active chips — all fields, not just visible ones
  const chips = useMemo(() => _CHIP_ORDER.flatMap(k => {
    const lbl = _fieldLabel(k, filters[k]);
    return lbl ? [{ key: k, label: lbl }] : [];
  }), [filters]);

  // Close panel on outside click (desktop)
  useEffect(() => {
    if (!expanded) return;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) close();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [expanded]);

  // Lock body scroll while bottom sheet is open on mobile
  useEffect(() => {
    if (!expanded) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [expanded]);

  function open()  { setDraft({ ...filters }); setExpanded(true);  }
  function close() { setExpanded(false); setDraft(null); }

  function apply() {
    if (draft) setFilters(draft);
    close();
  }

  function reset() {
    setDraft({ ...df, includeZero: filters.includeZero });
  }

  function removeChip(key) {
    setFilters({ ...filters, [key]: df[key] });
  }

  function clearAll() {
    setFilters({ ...df, includeZero: filters.includeZero });
  }

  // Region-scoped options
  const regionLandings = useMemo(() => {
    if (!regions || !window.getEffectiveRegion) return null;
    const eff = window.getEffectiveRegion(regions);
    return window.getLandingsForRegion ? window.getLandingsForRegion(eff) : null;
  }, [regions]);

  const landingOpts = useMemo(() => {
    const all = window.SD.LANDINGS;
    return regionLandings ? all.filter(l => regionLandings.includes(l)) : all;
  }, [regionLandings]);

  const boatOpts = useMemo(() => [...window.SD.BOATS]
    .filter(b => !regionLandings || regionLandings.includes(b.landing))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(b => b.name), [regionLandings]);

  const yearOpts = useMemo(() =>
    [...new Set(window.SD.TRIPS.map(t => t.year))].sort((a, b) => b - a)
      .map(y => ({ value: String(y), label: String(y) })), []);

  const cur = draft || filters;
  const upd = (k, v) => setDraft(d => ({ ...d, [k]: v }));
  const fld = (k) => (fields || []).includes(k);
  const hasActive = chips.length > 0;

  return (
    <div className="afb-wrap" ref={wrapRef}>

      {/* ── Collapsed bar ───────────────────────────────────────────── */}
      <div className="afb-bar">
        <button
          className={`afb-toggle${hasActive ? ' active' : ''}${expanded ? ' open' : ''}`}
          onClick={expanded ? close : open}
          aria-expanded={expanded}>
          <i className="fa-solid fa-sliders" aria-hidden="true"/>
          {' '}Filters{chips.length > 0 ? ` (${chips.length})` : ''}
        </button>

        {chips.length > 0 && (
          <Fragment>
            <div className="afb-chips">
              {chips.map(c => (
                <span key={c.key} className="afb-chip">
                  {c.label}
                  <button className="afb-chip-x" aria-label={`Remove ${c.key} filter`}
                          onClick={() => removeChip(c.key)}>×</button>
                </span>
              ))}
            </div>
            <button className="afb-clear" onClick={clearAll}>Clear all</button>
          </Fragment>
        )}
      </div>

      {/* ── Expanded panel (overlay + panel; CSS toggles sheet vs popover) */}
      {expanded && (
        <Fragment>
          <div className="afb-overlay" onClick={close} aria-hidden="true"/>
          <div className="afb-panel" role="dialog" aria-label="Filters">
            <div className="afb-panel-hd">
              <span className="afb-panel-title">Filters</span>
              <button className="afb-panel-close" onClick={close} aria-label="Close filters">
                <i className="fa-solid fa-xmark"/>
              </button>
            </div>

            <div className="afb-panel-body">
              {fld('year') && (
                <div className="afb-field">
                  <label className="afb-label">Year</label>
                  <MultiSelect options={yearOpts} value={cur.year}
                    onChange={v => upd('year', v)} allLabel="All Years"/>
                </div>
              )}
              {fld('month') && (
                <div className="afb-field">
                  <label className="afb-label">Month</label>
                  <MultiSelect
                    options={MONTH_NAMES.map((m, i) => ({ value: String(i + 1), label: m }))}
                    value={cur.month} onChange={v => upd('month', v)} allLabel="All Months"/>
                </div>
              )}
              {fld('landing') && (
                <div className="afb-field">
                  <label className="afb-label">Landing</label>
                  <MultiSelect options={landingOpts} value={cur.landing}
                    onChange={v => upd('landing', v)} allLabel="All Landings"/>
                </div>
              )}
              {fld('boat') && (
                <div className="afb-field">
                  <label className="afb-label">Boat</label>
                  <MultiSelect options={boatOpts} value={cur.boat}
                    onChange={v => upd('boat', v)} allLabel="All Boats"/>
                </div>
              )}
              {fld('tripLength') && (
                <div className="afb-field">
                  <label className="afb-label">Trip Length</label>
                  <MultiSelect options={window.SD.TRIP_LENGTHS} value={cur.tripLength}
                    onChange={v => upd('tripLength', v)} allLabel="All Lengths"/>
                </div>
              )}
              {fld('species') && (
                <div className="afb-field">
                  <label className="afb-label">Species</label>
                  <MultiSelect options={window.SD.SPECIES} value={cur.species}
                    onChange={v => upd('species', v)} allLabel="All Tuna"/>
                </div>
              )}
              {fld('minTrips') && (
                <div className="afb-field afb-field-inline">
                  <label className="afb-label">Min Trips</label>
                  <input type="number" min="0" max="100" className="afb-number"
                         value={cur.minTrips}
                         onChange={e => upd('minTrips', +e.target.value || 0)}/>
                </div>
              )}
            </div>

            <div className="afb-panel-footer">
              <button className="btn sm ghost" onClick={reset}>Reset</button>
              <button className="btn sm primary" onClick={apply}>Apply</button>
            </div>
          </div>
        </Fragment>
      )}
    </div>
  );
}

Object.assign(window, { FilterBar, AnalyticsFilterBar, DEFAULT_FILTERS, MultiSelect });
