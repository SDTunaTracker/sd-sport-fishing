// Moon Phase view — lunar phase correlation with catch rates
const { useMemo } = React;
function MoonView({ filters, setFilters, navigate, regions }) {
  const trips = useMemo(() => SDA.filterTrips(filters, regions), [filters, regions]);
  const moonData = useMemo(() => SDA.moonAnalysis(trips, filters.species), [trips, filters.species]);
  const bestMoon = [...moonData].sort((a, b) => b.tpa - a.tpa)[0];
  const fmWindows = useMemo(() => SDA.recentFullMoonWindows(trips, filters.species, { n: 3 }), [trips, filters.species]);
  const waxWan = useMemo(() => SDA.waxingVsWaning(trips, filters.species), [trips, filters.species]);

  const speciesActive = filters.species && filters.species !== 'all';
  const speciesLabel = speciesActive ? filters.species : 'Tuna';

  return (
    <React.Fragment>
      <Crumbs items={[
        { label: 'Analytics', onClick: () => navigate('analytics', { subtab: 'moon' }) },
        { label: 'Moon Phase' },
      ]}/>
      <div className="pagehead">
        <div>
          <h1>Moon Phase <span className="region-subtitle-badge">{(regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego'}</span></h1>
          <div className="sub">Lunar phase correlation with catch rates across {fmt.n(trips.length)} trips</div>
        </div>
      </div>
      <Panel title="Moon Phase Correlation"
             meta={`Avg ${speciesLabel.toLowerCase()}/angler by lunar phase`}
             className="moon-panel"
             actions={<span className="meta">Best: <b style={{color:'#34D399'}}>{bestMoon?.phase}</b> ({fmt.tpa(bestMoon?.tpa)})</span>}>
        <div className="moon-grid">
          {moonData.map((m) => {
            const isBest = m.phase === bestMoon?.phase;
            return (
              <div key={m.phase} className={`moon-cell ${isBest ? 'best' : ''}`}>
                <MoonGlyph phase={m.phase}/>
                <div className="moon-connector"></div>
                <div className="lab">{m.phase}</div>
                <div className="val">{fmt.tpa(m.tpa)}</div>
                <div className="sub">{m.trips} trips</div>
              </div>
            );
          })}
        </div>
        <div style={{marginTop: 8, paddingTop: 12, borderTop: '1px solid rgba(52,211,153,0.2)', font: '400 11px/14px var(--ss-font-sans)', color: 'rgba(255,255,255,0.5)'}}>
          <i className="fa-solid fa-circle-info"></i>{' '}
          {(() => {
            const sorted = [...moonData].sort((a,b)=>b.tpa-a.tpa);
            const lift = sorted[0].tpa / (sorted[sorted.length-1].tpa || 0.001);
            return `${sorted[0].phase} produces ${lift.toFixed(1)}× the catch rate of ${sorted[sorted.length-1].phase}. Bigger fish run on darker nights — Bluefin tuna especially favor crescent and new moon.`;
          })()}
        </div>
      </Panel>

      <FullMoonWindowsPanel windows={fmWindows} speciesLabel={speciesLabel}/>
      <WaxingVsWaningPanel bands={waxWan} speciesLabel={speciesLabel}/>
    </React.Fragment>
  );
}

function _fmtTpad(v) { return (v == null || !isFinite(v)) ? '—' : v.toFixed(2); }
function _fmtDate(iso) {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function FullMoonWindowsPanel({ windows, speciesLabel }) {
  if (!windows || windows.length === 0) {
    return (
      <Panel title="Recent Full Moon Windows" meta="Not enough data in current filter to show recent full moons">
        <div style={{padding: 12, color: 'var(--muted)', font: '400 12px/16px var(--ss-font-sans)'}}>
          Widen your date range or trip-length filter to see full-moon window comparisons.
        </div>
      </Panel>
    );
  }
  const label = speciesLabel.toLowerCase();
  return (
    <Panel title="Recent Full Moon Windows"
           meta={`Week-before vs on-full-moon vs week-after ${label}/angler/day`}
           actions={<span className="meta" style={{color: 'var(--muted)'}}>
             <i className="fa-solid fa-circle-info"></i> Reports on FM or FM+1 = fished on the full moon (1.5-day trips post the morning after)
           </span>}>
        <div className="fm-windows">
          {windows.map((w) => {
            const cells = [
              { key: 'before', label: 'Week before', data: w.before },
              { key: 'onFm',   label: 'On full moon', data: w.onFm },
              { key: 'after',  label: 'Week after', data: w.after },
            ];
            const nums = cells.map((c) => c.data.tpaPerDay).filter((n) => isFinite(n) && n > 0);
            const bestVal = nums.length ? Math.max(...nums) : null;
            return (
              <div key={w.fullMoonDate} className="fm-window">
                <div className="fm-window-head">
                  <span className="fm-window-icon">🌕</span>
                  <span className="fm-window-date">{_fmtDate(w.fullMoonDate)}</span>
                </div>
                <div className="fm-window-cells">
                  {cells.map((c) => {
                    const isBest = bestVal != null && c.data.tpaPerDay === bestVal;
                    return (
                      <div key={c.key} className={`fm-window-cell${isBest ? ' best' : ''}`}>
                        <div className="fm-window-cell-lab">{c.label}</div>
                        <div className="fm-window-cell-val">{_fmtTpad(c.data.tpaPerDay)}</div>
                        <div className="fm-window-cell-sub">
                          {c.data.trips} trip{c.data.trips === 1 ? '' : 's'}
                          {c.data.totalTrophy > 0 ? ` · ${c.data.totalTrophy} fish` : ''}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
    </Panel>
  );
}

function WaxingVsWaningPanel({ bands, speciesLabel }) {
  const anyData = bands && bands.some((b) => b.before.trips > 0 || b.after.trips > 0);
  if (!anyData) {
    return (
      <Panel title="Before vs After Full Moon" meta="Not enough data in current filter">
        <div style={{padding: 12, color: 'var(--muted)', font: '400 12px/16px var(--ss-font-sans)'}}>
          Widen your filters to compare waxing (before full) vs waning (after full) fishing.
        </div>
      </Panel>
    );
  }
  const label = speciesLabel.toLowerCase();
  // Global max across all before/after values for consistent bar scaling.
  const allVals = bands.flatMap((b) => [b.before.tpaPerDay, b.after.tpaPerDay]).filter((n) => isFinite(n) && n > 0);
  const maxV = allVals.length ? Math.max(...allVals) : 1;
  return (
    <Panel title="Before vs After Full Moon"
           meta={`${label.charAt(0).toUpperCase() + label.slice(1)}/angler/day by distance from full`}
           actions={<span className="meta" style={{color: 'var(--muted)'}}>Waxing = building toward full · Waning = past full</span>}>
      <div className="ww-table">
        <div className="ww-row ww-head">
          <div>Distance from full</div>
          <div>Before (waxing)</div>
          <div>After (waning)</div>
          <div>Post-FM lift</div>
        </div>
        {bands.map((b) => {
          const bef = b.before.tpaPerDay;
          const aft = b.after.tpaPerDay;
          const lift = (bef > 0 && isFinite(aft)) ? (aft / bef) : null;
          return (
            <div key={b.label} className="ww-row">
              <div className="ww-lab">{b.label}</div>
              <div className="ww-cell">
                <div className="ww-bar-wrap">
                  <div className="ww-bar ww-bar-before" style={{width: `${Math.min(100, (bef / maxV) * 100)}%`}}></div>
                </div>
                <div className="ww-val">{_fmtTpad(bef)} <span className="ww-n">({b.before.trips})</span></div>
              </div>
              <div className="ww-cell">
                <div className="ww-bar-wrap">
                  <div className="ww-bar ww-bar-after" style={{width: `${Math.min(100, (aft / maxV) * 100)}%`}}></div>
                </div>
                <div className="ww-val">{_fmtTpad(aft)} <span className="ww-n">({b.after.trips})</span></div>
              </div>
              <div className={`ww-lift${lift != null && lift >= 1.1 ? ' pos' : ''}${lift != null && lift < 0.9 ? ' neg' : ''}`}>
                {lift == null ? '—' : `${lift.toFixed(2)}×`}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{marginTop: 8, paddingTop: 12, borderTop: '1px solid var(--line)', font: '400 11px/15px var(--ss-font-sans)', color: 'var(--muted)'}}>
        <i className="fa-solid fa-lightbulb"></i>{' '}
        Classic pattern: bright FM nights let bait & tuna feed all night, dulling the morning bite.
        Once the moon starts rising later (2–5 days after full), predictable dawn bite windows tend to return.
      </div>
    </Panel>
  );
}

// Seasonality & Moon container — sub-tab wrapper
function SeasonalityMoonView({ filters, setFilters, navigate, subtab = 'moon', regions }) {
  const SUBTABS = [
    { id: 'moon',        label: 'Moon Phase' },
    { id: 'seasonality', label: 'Seasonality' },
  ];
  return (
    <React.Fragment>
      <div className="tabbar analytics-subtabbar">
        {SUBTABS.map(t => (
          <a key={t.id} className={subtab === t.id ? 'sel' : ''}
             onClick={() => navigate('seasonality', { subtab: t.id })}>{t.label}</a>
        ))}
      </div>
      {subtab === 'seasonality' && <SeasonalityView filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}
      {subtab === 'moon'        && <MoonView        filters={filters} setFilters={setFilters} navigate={navigate} regions={regions}/>}
    </React.Fragment>
  );
}

Object.assign(window, { MoonView, SeasonalityMoonView, FullMoonWindowsPanel, WaxingVsWaningPanel });
