// SF Bay Area region (behind FEATURES.SHOW_SFBAY).
//
// Data: web/data-region-sfbay.js (window.SFBAY), written by src/export_sfbay.py and
// lazy-loaded the first time the region is opened, so San Diego visitors
// download nothing extra. SoCal components never render in this region.
//
// Headline metric (owner decision 2026-11-25): LIMIT RATE BY TARGET. Each
// trip's target (rockfish & lingcod, salmon, crab & rockfish, halibut, ...) is
// inferred from its label + catch. Limit rate = fish landed per angler as a
// share of that target's daily bag limit, capped at 100% per trip, and averaged
// across trips weighted by anglers. Six-packs are shown but never ranked.
// No forecasts for this region (forecasting is R&D only).

const SFB_TARGET_ORDER = ['rockfish', 'salmon', 'crab_combo', 'crab', 'halibut', 'striper', 'bay_mixed', 'sturgeon', 'albacore', 'bluefin'];
const SFB_TARGET_COLORS = {
  rockfish: '#C2410C', salmon: '#E11D48', crab_combo: '#B45309', crab: '#D97706',
  halibut: '#0E7490', striper: '#475569', bay_mixed: '#0F766E', sturgeon: '#6D28D9',
  albacore: '#1D4ED8', bluefin: '#1E3A8A', unknown: '#94A3B8',
};
const SFB_PERIODS = [
  { id: '30', label: '30 days', days: 30 },
  { id: '90', label: '90 days', days: 90 },
  { id: 'year', label: 'This year' },
  { id: 'all', label: 'All time' },
];
const SFB_MIN_TRIPS = 3;

function sfbLoad() {
  if (window.SFBAY) return Promise.resolve(window.SFBAY);
  if (window.__sfbayLoading) return window.__sfbayLoading;
  window.__sfbayLoading = new Promise(function (resolve, reject) {
    var s = document.createElement('script');
    s.src = '/data-region-sfbay.js?v=' + (window.SFBAY_DATA_VERSION || Date.now().toString().slice(0, 7));
    s.onload = function () { window.SFBAY ? resolve(window.SFBAY) : reject(new Error('no data')); };
    s.onerror = function () { window.__sfbayLoading = null; reject(new Error('load failed')); };
    document.head.appendChild(s);
  });
  return window.__sfbayLoading;
}

function useSfbayData() {
  const [state, setState] = React.useState(() => ({ data: window.SFBAY ? sfbPrepare(window.SFBAY) : null, error: null }));
  React.useEffect(() => {
    if (state.data) return;
    let alive = true;
    sfbLoad().then(d => alive && setState({ data: sfbPrepare(d), error: null }))
             .catch(e => alive && setState({ data: null, error: String(e.message || e) }));
    return () => { alive = false; };
  }, []);
  return state;
}

// Expand the compact rows once and register the landings with regions.js.
function sfbPrepare(d) {
  if (d.__prepared) return d.__prepared;
  const F = d.TRIP_FIELDS;
  const ix = name => F.indexOf(name);
  const iD = ix('date'), iB = ix('boat'), iT = ix('trip'), iA = ix('anglers'), iG = ix('target'),
        iR = ix('limitRate'), iH = ix('halfDay'), iC = ix('catch');
  const trips = d.TRIPS.map(r => {
    const b = d.BOATS[r[iB]];
    return { date: r[iD], boat: b.name, slug: b.slug, landing: b.landing, port: b.port, sixpack: !!b.sixpack,
             trip: r[iT], anglers: r[iA], target: r[iG], rate: r[iR], half: !!r[iH], catch: r[iC] || {} };
  });
  const out = { ...d, trips, bySlug: Object.fromEntries(d.BOATS.map(b => [b.slug, b])) };
  const region = (window.REGIONS || []).find(r => r.id === 'sf_bay');
  if (region) region.landings = d.LANDINGS.map(L => L.name);
  d.__prepared = out;
  return out;
}

function sfbTargetLabel(d, t) { return (d.TARGETS[t] || d.TARGETS.unknown || { label: t }).label; }
function sfbPct(r) { return r == null ? '—' : Math.round(r * 100) + '%'; }
function sfbFmtDate(iso, opts) {
  const [y, m, dd] = iso.split('-').map(Number);
  return new Date(y, m - 1, dd).toLocaleDateString('en-US', opts || { weekday: 'short', month: 'short', day: 'numeric' });
}
function sfbTotalFish(c) { return Object.values(c).reduce((a, b) => a + b, 0); }
function sfbCatchText(c) {
  const e = Object.entries(c).sort((a, b) => b[1] - a[1]);
  return e.length ? e.map(([k, v]) => v + ' ' + k).join(', ') : 'No fish reported';
}

// Angler-weighted limit rate over trips that have one.
// Tie-breakers, because rockfish and crab limits are common (many boats sit
// at 100%): share of trips at full limits (>= 95%), then lingcod per angler.
function sfbAgg(trips) {
  let a = 0, w = 0, fish = 0, anglers = 0, rated = 0, full = 0, ling = 0;
  for (const t of trips) {
    anglers += t.anglers; fish += sfbTotalFish(t.catch); ling += t.catch.Lingcod || 0;
    if (t.rate != null) { a += t.rate * t.anglers; w += t.anglers; rated++; if (t.rate >= 0.95) full++; }
  }
  return { trips: trips.length, anglers, fish, rate: w ? a / w : null, rated, fpa: anglers ? fish / anglers : 0,
           fullShare: rated ? full / rated : null, lingPA: anglers ? ling / anglers : 0 };
}

function sfbPeriodStart(period, latest) {
  if (period === 'all' || !latest) return '0000';
  const [y, m, dd] = latest.split('-').map(Number);
  if (period === 'year') return y + '-01-01';
  const days = (SFB_PERIODS.find(p => p.id === period) || {}).days || 30;
  const dt = new Date(y, m - 1, dd - days + 1);
  return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
}

function SfbTargetChip({ d, target, on, onClick, count }) {
  return (
    <button className={'sfb-chip' + (on ? ' on' : '')} onClick={onClick}
            style={on ? { borderColor: SFB_TARGET_COLORS[target], background: SFB_TARGET_COLORS[target], color: '#fff' } : null}>
      <span className="sfb-dot" style={{ background: on ? '#fff' : SFB_TARGET_COLORS[target] }}/>
      {sfbTargetLabel(d, target)}{count != null && <span className="sfb-chip-n">{count}</span>}
    </button>
  );
}

function SfbRateBar({ rate, target }) {
  if (rate == null) return <span className="sfb-muted">n/a</span>;
  return (
    <span className="sfb-rate">
      <span className="sfb-rate-track"><span className="sfb-rate-fill" style={{ width: Math.round(rate * 100) + '%', background: SFB_TARGET_COLORS[target] || 'var(--accent)' }}/></span>
      <b>{sfbPct(rate)}</b>
    </span>
  );
}

function SfbHead({ title, sub }) {
  return (
    <div className="pagehead">
      <div>
        <h1>{title} <span className="region-subtitle-badge">SF Bay Area</span></h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
    </div>
  );
}

function SfbMetricNote({ d }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="sfb-note">
      <button className="sfb-linkbtn" onClick={() => setOpen(o => !o)}>
        <i className="fa-solid fa-circle-info"/> How "limit rate" works {open ? '▲' : '▼'}
      </button>
      {open && (
        <div className="sfb-note-body">
          <p>Each trip's target is worked out from its trip label and catch. Its <b>limit rate</b> is the fish landed per angler as a share of the daily bag limit for that target, capped at 100%. Crab & rockfish trips average the two. Boat and fleet rates weight each trip by its anglers. Counts are as posted by the landing, and may include crew fish.</p>
          <table className="sfb-table sfb-table-compact">
            <thead><tr><th>Bag limit used</th><th className="num">Per angler</th></tr></thead>
            <tbody>
              {Object.entries(d.BAG_LIMITS).map(([g, v]) => (
                <tr key={g}><td>{v.note}</td><td className="num">{v.limit == null ? 'C&R only' : v.limit}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="sfb-muted">Regulations change. Always check the current <a href="https://wildlife.ca.gov/Fishing/Ocean/Regulations/Sport-Fishing" target="_blank" rel="noopener">CDFW ocean sport fishing regulations</a> before you go. Six-pack charters (6 anglers or fewer) are listed but not ranked.</p>
        </div>
      )}
    </div>
  );
}

function SfbSlowSeason({ d }) {
  const month = new Date().getMonth() + 1;
  const now = SFB_TARGET_ORDER.filter(t => d.SEASONS[t] && d.SEASONS[t].months.indexOf(month) !== -1);
  return (
    <div className="sfb-slow">
      <div className="sfb-slow-title"><i className="fa-solid fa-snowflake"/> Slow season on the Bay</div>
      <div>Only {d.META.openTrips7d} open-party trip{d.META.openTrips7d === 1 ? '' : 's'} posted in the last 7 days. Weather, bar conditions and closed seasons keep boats in.
        {now.length > 0 && <> Usually fishing this month: {now.map(t => sfbTargetLabel(d, t)).join(', ')}.</>}</div>
    </div>
  );
}

// Live conditions from window.SFBAY.MARINE (src.marine) when present.
const SFB_ZONE_NAMES = { PZZ545: 'Coast, Pt Reyes to Pigeon Pt (0–10 nm)', PZZ571: 'Offshore (10–60 nm)',
  PZZ530: 'SF Bay north of the Bay Bridge', PZZ531: 'SF Bay south of the Bay Bridge' };
const SFB_BUOY_NAMES = { '46026': 'SF buoy (18 nm W)', '46237': 'SF Bar', '142': 'SF Bar (CDIP)', '46012': 'Half Moon Bay' };
function sfbFt(m) { return m == null ? null : (m * 3.281).toFixed(1); }
function sfbTime(iso) {
  return new Date(iso).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'America/Los_Angeles' });
}
function SfbMarine({ m }) {
  const nowIso = new Date().toISOString();
  const tides = ((m.tides && m.tides.events) || []).filter(e => e.t >= nowIso).slice(0, 4);
  const zone = (m.zones && (m.zones.PZZ545 || m.zones[Object.keys(m.zones)[0]])) || null;
  const zoneId = m.zones && (m.zones.PZZ545 ? 'PZZ545' : Object.keys(m.zones)[0]);
  const p = zone && zone.periods && zone.periods[0];
  const buoys = Object.entries(m.buoys || {}).filter(([, b]) => b && b.waveM != null);
  return (
    <React.Fragment>
      {m.smallCraftAdvisory && <div className="sfb-alert"><i className="fa-solid fa-triangle-exclamation"/> Small Craft Advisory in effect{(m.alerts || [])[0] && m.alerts[0].ends ? ' until ' + sfbTime(m.alerts[0].ends) : ''}. Bar and coastal trips may cancel.</div>}
      <div className="sfb-cond-grid">
        {buoys.map(([id, b]) => (
          <div key={id} className="sfb-cond">
            <div className="sfb-target-name">{SFB_BUOY_NAMES[id] || 'Buoy ' + id}</div>
            <div className="sfb-cond-val">{sfbFt(b.waveM)} ft{b.periodS ? ' @ ' + Math.round(b.periodS) + 's' : ''}</div>
            <div className="sfb-muted">{b.waterC != null ? Math.round(b.waterC * 9 / 5 + 32) + '°F water · ' : ''}{b.t ? sfbTime(b.t) : ''}</div>
          </div>
        ))}
        {tides.length > 0 && (
          <div className="sfb-cond">
            <div className="sfb-target-name">SF tides</div>
            {tides.map((e, i) => <div key={i} className="sfb-cond-tide"><b>{e.type === 'H' ? 'High' : 'Low'}</b> {e.ft != null ? e.ft.toFixed(1) + ' ft' : ''} <span className="sfb-muted">{sfbTime(e.t)}</span></div>)}
          </div>
        )}
      </div>
      {p && <div className="sfb-cond-fc"><b>{SFB_ZONE_NAMES[zoneId] || zoneId}, {p.name}:</b> {p.text}</div>}
    </React.Fragment>
  );
}

function SfbConditions({ d }) {
  return (
    <div className="sfb-card">
      <div className="sfb-card-title"><i className="fa-solid fa-water"/> Conditions & the bar</div>
      {d.MARINE ? <SfbMarine m={d.MARINE}/> :
        <div className="sfb-muted" style={{ marginBottom: 8 }}>Check the Golden Gate bar and swell before you book. These open the official sources.</div>}
      <div className="sfb-links">
        {d.CONDITIONS.map(c => <a key={c.id} className="sfb-link" href={c.url} target="_blank" rel="noopener">{c.label} <i className="fa-solid fa-arrow-up-right-from-square"/></a>)}
      </div>
    </div>
  );
}

function SfbLoading({ state }) {
  return (
    <div className="sfb-card" style={{ marginTop: 24 }}>
      {state.error ? <>SF Bay data didn't load ({state.error}). <a href="" onClick={() => location.reload()}>Reload</a></> : 'Loading SF Bay counts…'}
    </div>
  );
}

// ── Today ────────────────────────────────────────────────────────────────
function SfbToday({ d, navigate }) {
  const days = React.useMemo(() => [...new Set(d.trips.map(t => t.date))].sort(), [d]);
  const [day, setDay] = React.useState(days[days.length - 1]);
  const [showSix, setShowSix] = React.useState(false);
  const di = days.indexOf(day);
  const dayTrips = d.trips.filter(t => t.date === day);
  const open = dayTrips.filter(t => !t.sixpack);
  const all = sfbAgg(open);
  const byTarget = {};
  open.forEach(t => (byTarget[t.target] = byTarget[t.target] || []).push(t));
  const targets = SFB_TARGET_ORDER.filter(t => byTarget[t]).concat(byTarget.unknown ? ['unknown'] : []);
  const rows = (showSix ? dayTrips : open).slice().sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1) || b.anglers - a.anglers);
  const nSix = dayTrips.length - open.length;

  return (
    <React.Fragment>
      <SfbHead title="Today" sub={`Open-party fish counts from ${d.META.ports.join(', ')}`}/>
      {d.META.slowSeason && <SfbSlowSeason d={d}/>}
      <div className="sfb-daynav">
        <button className="sfb-navbtn" disabled={di <= 0} onClick={() => setDay(days[di - 1])} aria-label="Previous day">‹</button>
        <div className="sfb-day">{day ? sfbFmtDate(day, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) : 'No reports yet'}
          {di === days.length - 1 && <span className="sfb-latest">latest report</span>}</div>
        <button className="sfb-navbtn" disabled={di >= days.length - 1} onClick={() => setDay(days[di + 1])} aria-label="Next day">›</button>
      </div>

      <div className="sfb-headline">
        <b>{open.length}</b> open-party boat{open.length === 1 ? '' : 's'} took <b>{all.anglers}</b> anglers out and landed <b>{all.fish.toLocaleString()}</b> fish, at <b>{sfbPct(all.rate)}</b> of limits.
      </div>

      <div className="sfb-target-grid">
        {targets.map(t => {
          const a = sfbAgg(byTarget[t]);
          const best = byTarget[t].slice().sort((x, y) => (y.rate ?? -1) - (x.rate ?? -1))[0];
          return (
            <div key={t} className="sfb-target-card" style={{ borderTopColor: SFB_TARGET_COLORS[t] }}>
              <div className="sfb-target-name">{sfbTargetLabel(d, t)}</div>
              <div className="sfb-target-rate">{t === 'sturgeon' || a.rate == null ? a.fpa.toFixed(1) : sfbPct(a.rate)}</div>
              <div className="sfb-muted">{t === 'sturgeon' || a.rate == null ? 'fish per angler' : 'of limits'} · {a.trips} trip{a.trips === 1 ? '' : 's'} · {a.anglers} anglers</div>
              {best && <div className="sfb-target-best">Top: <a href={pathFor('boat', best.boat)} onClick={spa(() => navigate('boat', { boat: best.boat }))}>{best.boat}</a> {best.rate != null && sfbPct(best.rate)}</div>}
            </div>
          );
        })}
      </div>

      <div className="sfb-card">
        <div className="sfb-card-head">
          <div className="sfb-card-title">Every boat, {day ? sfbFmtDate(day) : ''}</div>
          {nSix > 0 && <label className="sfb-toggle"><input type="checkbox" checked={showSix} onChange={e => setShowSix(e.target.checked)}/> Show {nSix} six-pack{nSix === 1 ? '' : 's'}</label>}
        </div>
        <div className="sfb-table-wrap">
          <table className="sfb-table">
            <thead><tr><th>Boat</th><th>Target</th><th className="num">Anglers</th><th>Limit rate</th><th className="sfb-hide-sm">Catch</th></tr></thead>
            <tbody>
              {rows.map((t, i) => (
                <tr key={i} className={t.sixpack ? 'sfb-six' : ''}>
                  <td><a href={pathFor('boat', t.boat)} onClick={spa(() => navigate('boat', { boat: t.boat }))}><b>{t.boat}</b></a>
                    <div className="sfb-muted">{t.landing} · {t.port}{t.sixpack ? ' · six-pack' : ''}</div>
                    <div className="sfb-show-sm sfb-muted">{sfbCatchText(t.catch)}</div></td>
                  <td><span className="sfb-dot" style={{ background: SFB_TARGET_COLORS[t.target] }}/> {sfbTargetLabel(d, t.target)}<div className="sfb-muted">{t.trip}</div></td>
                  <td className="num">{t.anglers}</td>
                  <td><SfbRateBar rate={t.rate} target={t.target}/></td>
                  <td className="sfb-hide-sm">{sfbCatchText(t.catch)}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan="5" className="sfb-muted">No counts posted this day.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <SfbMetricNote d={d}/>
      <SfbConditions d={d}/>
    </React.Fragment>
  );
}

// ── Boats leaderboard ────────────────────────────────────────────────────
function SfbBoats({ d, navigate }) {
  const latest = d.META.latestDate;
  const [period, setPeriod] = React.useState('90');
  const start = sfbPeriodStart(period, latest);
  const inPeriod = d.trips.filter(t => t.date >= start && !t.sixpack);
  const counts = {};
  inPeriod.forEach(t => { counts[t.target] = (counts[t.target] || 0) + 1; });
  const targets = SFB_TARGET_ORDER.filter(t => counts[t]);
  const [target, setTarget] = React.useState(null);
  const tgt = target && counts[target] ? target : targets.slice().sort((a, b) => counts[b] - counts[a])[0];

  const byBoat = {};
  inPeriod.filter(t => t.target === tgt).forEach(t => (byBoat[t.slug] = byBoat[t.slug] || []).push(t));
  const rows = Object.entries(byBoat).map(([slug, ts]) => ({ slug, boat: d.bySlug[slug], ...sfbAgg(ts), last: ts[ts.length - 1].date }));
  const ranked = rows.filter(r => r.trips >= SFB_MIN_TRIPS)
    .sort((a, b) => (b.rate ?? b.fpa / 100) - (a.rate ?? a.fpa / 100)
      || (b.fullShare ?? 0) - (a.fullShare ?? 0) || b.lingPA - a.lingPA || b.trips - a.trips);
  const showLing = tgt === 'rockfish' || tgt === 'crab_combo';
  const few = rows.filter(r => r.trips < SFB_MIN_TRIPS).sort((a, b) => b.trips - a.trips);
  const fleet = sfbAgg(inPeriod.filter(t => t.target === tgt));
  const sixBoats = d.BOATS.filter(b => b.sixpack);
  const useFpa = tgt === 'sturgeon';

  return (
    <React.Fragment>
      <SfbHead title="Boats" sub="Open-party boats ranked by limit rate within each target"/>
      <div className="sfb-controls">
        <div className="sfb-chips">{SFB_PERIODS.map(p => <button key={p.id} className={'sfb-chip' + (period === p.id ? ' on dark' : '')} onClick={() => setPeriod(p.id)}>{p.label}</button>)}</div>
        <div className="sfb-chips">{targets.map(t => <SfbTargetChip key={t} d={d} target={t} count={counts[t]} on={t === tgt} onClick={() => setTarget(t)}/>)}</div>
      </div>
      {!tgt ? <div className="sfb-card sfb-muted">No open-party trips in this period. Try a longer period.</div> : (
        <div className="sfb-card">
          <div className="sfb-card-head">
            <div className="sfb-card-title">{sfbTargetLabel(d, tgt)} · fleet {useFpa ? fleet.fpa.toFixed(1) + ' fish/angler' : sfbPct(fleet.rate) + ' of limits'}</div>
            <div className="sfb-muted">{fleet.trips} trips · {fleet.anglers.toLocaleString()} anglers · min {SFB_MIN_TRIPS} trips to rank · ties broken by full-limit trips{showLing ? ', then lingcod per angler' : ''}</div>
          </div>
          <div className="sfb-table-wrap">
            <table className="sfb-table">
              <thead><tr><th className="num">#</th><th>Boat</th><th className="num">Trips</th><th className="num sfb-hide-sm">Anglers</th><th>{useFpa ? 'Fish / angler' : 'Limit rate'}</th>{!useFpa && <th className="num sfb-hide-sm" title="Share of trips at 95%+ of limits">Full-limit trips</th>}{showLing && <th className="num sfb-hide-sm">Lingcod / angler</th>}<th className="sfb-hide-sm">Last trip</th></tr></thead>
              <tbody>
                {ranked.map((r, i) => (
                  <tr key={r.slug}>
                    <td className="num">{i + 1}</td>
                    <td><a href={pathFor('boat', r.boat.name)} onClick={spa(() => navigate('boat', { boat: r.boat.name }))}><b>{r.boat.name}</b></a><div className="sfb-muted">{r.boat.landing} · {r.boat.port}</div></td>
                    <td className="num">{r.trips}</td>
                    <td className="num sfb-hide-sm">{r.anglers.toLocaleString()}</td>
                    <td>{useFpa ? r.fpa.toFixed(1) : <SfbRateBar rate={r.rate} target={tgt}/>}</td>
                    {!useFpa && <td className="num sfb-hide-sm">{sfbPct(r.fullShare)}</td>}
                    {showLing && <td className="num sfb-hide-sm">{r.lingPA.toFixed(2)}</td>}
                    <td className="sfb-hide-sm">{sfbFmtDate(r.last)}</td>
                  </tr>
                ))}
                {!ranked.length && <tr><td colSpan="8" className="sfb-muted">No boat has {SFB_MIN_TRIPS}+ {sfbTargetLabel(d, tgt).toLowerCase()} trips in this period.</td></tr>}
              </tbody>
            </table>
          </div>
          {few.length > 0 && <div className="sfb-muted sfb-few">Fewer than {SFB_MIN_TRIPS} trips (not ranked): {few.map(r => r.boat.name + ' (' + r.trips + ')').join(', ')}</div>}
        </div>
      )}
      {sixBoats.length > 0 && <div className="sfb-muted sfb-few">Six-pack charters, not ranked: {sixBoats.map(b => b.name).join(', ')}.</div>}
      <SfbMetricNote d={d}/>
    </React.Fragment>
  );
}

// ── Boat detail ──────────────────────────────────────────────────────────
function SfbBoat({ d, navigate, name }) {
  const boat = d.BOATS.find(b => b.name === name) || d.BOATS.find(b => b.slug === name);
  if (!boat) return <React.Fragment><SfbHead title="Boat not found"/><div className="sfb-card">No SF Bay boat called “{name}”. <a href={pathFor('boats')} onClick={spa(() => navigate('boats'))}>See all boats</a></div></React.Fragment>;
  const trips = d.trips.filter(t => t.slug === boat.slug);
  const recent = trips.slice(-60).reverse();
  const byTarget = {};
  trips.forEach(t => (byTarget[t.target] = byTarget[t.target] || []).push(t));
  const L = d.LANDINGS.find(x => x.name === boat.landing) || {};
  return (
    <React.Fragment>
      <SfbHead title={boat.name} sub={`${boat.landing} · ${boat.port}${boat.sixpack ? ' · six-pack charter (not ranked)' : ''}`}/>
      <div className="sfb-actions">
        {L.booking ? <a className="sfb-btn" href={L.booking} target="_blank" rel="noopener"><i className="fa-solid fa-calendar-check"/> Book with {boat.landing}</a>
                   : <span className="sfb-muted">Booking link coming soon.</span>}
        <a className="sfb-link" href={`https://www.norcalfishreports.com/charter_boats/${boat.slug}.php`} target="_blank" rel="noopener">Source counts <i className="fa-solid fa-arrow-up-right-from-square"/></a>
      </div>
      <div className="sfb-target-grid">
        {SFB_TARGET_ORDER.filter(t => byTarget[t]).map(t => {
          const a = sfbAgg(byTarget[t]);
          return (
            <div key={t} className="sfb-target-card" style={{ borderTopColor: SFB_TARGET_COLORS[t] }}>
              <div className="sfb-target-name">{sfbTargetLabel(d, t)}</div>
              <div className="sfb-target-rate">{a.rate == null ? a.fpa.toFixed(1) : sfbPct(a.rate)}</div>
              <div className="sfb-muted">{a.rate == null ? 'fish per angler' : 'of limits'} · {a.trips} trips since {sfbFmtDate(byTarget[t][0].date, { month: 'short', year: 'numeric' })}</div>
            </div>
          );
        })}
      </div>
      <div className="sfb-card">
        <div className="sfb-card-title">Recent trips</div>
        <div className="sfb-table-wrap">
          <table className="sfb-table">
            <thead><tr><th>Date</th><th>Target</th><th className="num">Anglers</th><th>Limit rate</th><th className="sfb-hide-sm">Catch</th></tr></thead>
            <tbody>{recent.map((t, i) => (
              <tr key={i}><td>{sfbFmtDate(t.date, { month: 'short', day: 'numeric', year: 'numeric' })}<div className="sfb-show-sm sfb-muted">{sfbCatchText(t.catch)}</div></td>
                <td><span className="sfb-dot" style={{ background: SFB_TARGET_COLORS[t.target] }}/> {sfbTargetLabel(d, t.target)}</td>
                <td className="num">{t.anglers}</td><td><SfbRateBar rate={t.rate} target={t.target}/></td>
                <td className="sfb-hide-sm">{sfbCatchText(t.catch)}</td></tr>))}
            </tbody>
          </table>
        </div>
      </div>
      <SfbMetricNote d={d}/>
    </React.Fragment>
  );
}

// ── Landings ─────────────────────────────────────────────────────────────
function SfbLandings({ d, navigate }) {
  const ports = d.META.ports;
  return (
    <React.Fragment>
      <SfbHead title="Landings" sub={`${d.LANDINGS.length} landings across ${ports.length} ports`}/>
      {ports.map(p => {
        const Ls = d.LANDINGS.filter(L => L.port === p);
        if (!Ls.length) return null;
        return (
          <div key={p} className="sfb-card">
            <div className="sfb-card-title">{p}</div>
            {Ls.map(L => {
              const boats = d.BOATS.filter(b => b.landing === L.name);
              return (
                <div key={L.name} className="sfb-landing-row">
                  <div><b>{L.name}</b> {L.booking && <a className="sfb-link" href={L.booking} target="_blank" rel="noopener">Book</a>}</div>
                  <div className="sfb-landing-boats">{boats.map(b => (
                    <a key={b.slug} href={pathFor('boat', b.name)} onClick={spa(() => navigate('boat', { boat: b.name }))} className={'sfb-chip' + (b.sixpack ? ' six' : '')}>{b.name}{b.sixpack ? ' · 6-pk' : ''}</a>))}</div>
                </div>
              );
            })}
          </div>
        );
      })}
    </React.Fragment>
  );
}

function SfbUnsupported({ navigate, view }) {
  return (
    <React.Fragment>
      <SfbHead title="Not available for SF Bay yet"/>
      <div className="sfb-card">
        {view === 'tripplanner' ? 'Trip schedules for SF Bay landings aren’t on Tunatracker yet. ' : 'This page covers San Diego and OC / LA for now. '}
        See <a href={pathFor('today')} onClick={spa(() => navigate('today'))}>today’s SF Bay counts</a> or the <a href={pathFor('boats')} onClick={spa(() => navigate('boats'))}>boat leaderboard</a>.
      </div>
    </React.Fragment>
  );
}

function pathFor(view, boat) {
  return window.ttPathFromRoute ? window.ttPathFromRoute(view, boat ? { boat } : {}, ['sf_bay']) : '#';
}
function spa(fn) {
  return function (e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) return;
    e.preventDefault(); fn();
  };
}

function SFBayView({ view, params, navigate }) {
  const state = useSfbayData();
  if (!state.data) return <SfbLoading state={state}/>;
  const d = state.data;
  if (view === 'home' || view === 'today') return <SfbToday d={d} navigate={navigate}/>;
  if (view === 'boats') return <SfbBoats d={d} navigate={navigate}/>;
  if (view === 'boat') return <SfbBoat d={d} navigate={navigate} name={params.boat}/>;
  if (view === 'landing' || view === 'landings') return <SfbLandings d={d} navigate={navigate}/>;
  return <SfbUnsupported navigate={navigate} view={view}/>;
}

function SFBayFooter() {
  return (
    <footer className="sfb-footer">
      <div>Tunatracker · SF Bay Area counts from norcalfishreports.com, as posted by each landing. Not affiliated with any landing.</div>
      <div className="sfb-muted">Check current CDFW regulations before fishing. Limit rates are estimates from posted counts.</div>
    </footer>
  );
}

Object.assign(window, { SFBayView, SFBayFooter, useSfbayData, sfbAgg, sfbPrepare });
