// Paddle Tracker: race list, race page, course map and race-day forecast.
//
// Portable on purpose (a separate Paddle Tracker site is planned). Needs only
// React, Leaflet (lazy-loaded) and its own files:
//   /api/v1/paddle_races.json            hand-maintained race list (PaddleGuru forbids scraping)
//   /api/v1/paddle_courses/<id>.geojson  course per race distance
//   /api/v1/paddle_race_forecast.json    src/paddle/forecast.py
//   paddle-races.css                     styles, prefix `pr-`
// Mount: <window.PaddleRaces raceId="" hrefFor={id => url} go={id => navigate}/>
// (today inside Surftracker's Paddle mode at /sd/surf/races[/<id>]).
const { useState: usePrState, useEffect: usePrEffect, useRef: usePrRef } = React;

const PR_TZ = 'America/Los_Angeles';
const PR_API = '/api/v1/';
const PR_COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const PR_REL = { tail: 'Downwind', light: 'Light', cross: 'Side wind', head: 'Headwind' };
const PR_SWELL = { with: 'with you', against: 'against you', side: 'side-on' };
const PR_COLORS = { great: '#1E6B47', good: '#3E8E5E', fair: '#D9A23A', poor: '#D9722E', hard: '#B23A3A', none: '#8C9A9C' };

// Stylesheet: linked from index.html; added here too for pages that don't link it.
const PR_V = (() => { try { return (document.currentScript.src.split('?v=')[1] || ''); } catch (e) { return ''; } })();
function prEnsureCss() {
  if (document.querySelector('link[href*="paddle-races.css"]')) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = '/paddle-races.css' + (PR_V ? '?v=' + PR_V : '');
  document.head.appendChild(l);
}

function prDir(d) { return d == null ? '' : PR_COMPASS[Math.round((((d % 360) + 360) % 360) / 22.5) % 16]; }
function prKey(label) { return label ? label.toLowerCase() : 'none'; }
function prToday() { return new Date().toLocaleDateString('en-CA', { timeZone: PR_TZ }); }
function prDate(day, opts) {
  return new Date(day + 'T12:00:00Z').toLocaleDateString('en-US', Object.assign({ timeZone: 'UTC' }, opts));
}
function prClock(iso) {
  return new Date(iso).toLocaleTimeString('en-US', { timeZone: PR_TZ, hour: 'numeric', minute: '2-digit' });
}
function prHhmm(s) {
  if (!s) return '';
  const [h, m] = s.split(':').map(Number);
  return ((h + 11) % 12 + 1) + ':' + String(m).padStart(2, '0') + (h < 12 ? ' AM' : ' PM');
}
function prMiles(m, leg) {
  if (m == null) return '';
  if (!leg && m < 1) return (Math.round(m * 1609 / 100) * 100) + ' m';
  return (Math.round(m * 10) / 10) + ' mi';
}

const _prCache = {};
function prFetch(name) {
  if (!_prCache[name]) {
    _prCache[name] = fetch(PR_API + name + (name.endsWith('forecast.json') ? '?h=' + new Date().toISOString().slice(0, 13) : ''))
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .catch(e => { delete _prCache[name]; throw e; });
  }
  return _prCache[name];
}
function usePrJson(name) {
  const [st, setSt] = usePrState({ data: null, error: null });
  usePrEffect(() => {
    if (!name) return undefined;
    let alive = true;
    setSt({ data: null, error: null });
    prFetch(name).then(d => alive && setSt({ data: d, error: null }), e => alive && setSt({ data: null, error: e }));
    return () => { alive = false; };
  }, [name]);
  return st;
}

function PrPill({ label, big }) {
  return <span className={`pr-pill pr-${prKey(label)}${big ? ' pr-pill-big' : ''}`}>{label || 'No forecast'}</span>;
}
function PrLink({ hrefFor, go, id, className, children }) {
  return (
    <a className={className} href={hrefFor(id)}
       onClick={e => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; e.preventDefault(); go(id); }}>
      {children}
    </a>
  );
}

// ── race list ───────────────────────────────────────────────────────────────
function prGroups(races, today) {
  const up = races.filter(r => r.date && r.date >= today).sort((a, b) => a.date.localeCompare(b.date));
  const past = races.filter(r => r.date && r.date < today);
  const years = [...new Set(past.map(r => r.year))].sort((a, b) => b - a);
  const groups = [];
  if (up.length) groups.push({ key: 'up', title: 'Upcoming', races: up });
  years.forEach(y => groups.push({ key: 'y' + y, title: String(y), past: true,
    races: past.filter(r => r.year === y).sort((a, b) => a.date.localeCompare(b.date)) }));
  const tbc = races.filter(r => !r.date);
  if (tbc.length) groups.push({ key: 'tbc', title: 'Date TBC', races: tbc });
  return groups;
}

function PrRaceRow({ r, fc, past, hrefFor, go }) {
  const f = fc && fc.races && fc.races[r.id];
  const main = f && f[Object.keys(f)[0]];
  return (
    <li>
      <PrLink className={`pr-row${past ? ' pr-past' : ''}`} hrefFor={hrefFor} go={go} id={r.id}>
        <span className="pr-row-date">
          {r.date ? <><b>{prDate(r.date, { month: 'short', day: 'numeric' })}</b><i>{prDate(r.date, { weekday: 'short' })}</i></> : <b>TBC</b>}
        </span>
        <span className="pr-row-main">
          <span className="pr-row-name">{r.name}{r.status && r.status.startsWith('draft') && <em className="pr-draft">draft</em>}</span>
          <span className="pr-row-sub">{r.location.name} · {r.distances.map(d => prMiles(d.miles)).join(' · ')}</span>
          <span className="pr-chips">{(r.divisions || []).map(d => <span key={d} className="pr-chip">{d}</span>)}</span>
        </span>
        {main && <span className="pr-row-fc"><PrPill label={main.label}/></span>}
      </PrLink>
    </li>
  );
}

function PrList({ doc, fc, hrefFor, go }) {
  const groups = prGroups(doc.races || [], prToday());
  return (
    <div className="pr-wrap">
      <h1 className="pr-title">Races</h1>
      <p className="pr-muted">San Diego paddle races. Course map and race-day forecast for each.</p>
      {groups.map(g => (
        <section key={g.key} className="pr-group" aria-labelledby={'pr-g-' + g.key}>
          <h2 className="pr-h2" id={'pr-g-' + g.key}>{g.title}</h2>
          <ul className="pr-list">
            {g.races.map(r => <PrRaceRow key={r.id} r={r} fc={fc} past={g.past} hrefFor={hrefFor} go={go}/>)}
          </ul>
        </section>
      ))}
      {!groups.length && <p className="pr-muted">No races listed yet.</p>}
      <p className="pr-foot">Race details from each race's PaddleGuru page, entered by hand.</p>
    </div>
  );
}

// ── course map ──────────────────────────────────────────────────────────────
let _prLeaflet = null;
function prEnsureLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (_prLeaflet) return _prLeaflet;
  _prLeaflet = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js'; s.crossOrigin = 'anonymous';
    s.onload = () => resolve(window.L); s.onerror = reject;
    document.head.appendChild(s);
    if (!document.querySelector('link[href*="leaflet.css"]')) {
      const l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css'; l.crossOrigin = 'anonymous';
      document.head.appendChild(l);
    }
  });
  return _prLeaflet;
}

function prWaypoints(geo) {
  return geo.features.filter(f => f.properties.kind === 'waypoint').sort((a, b) => a.properties.i - b.properties.i);
}

function PrCourseMap({ geo, legs, sel, onSel }) {
  const box = usePrRef(null);
  const map = usePrRef(null);
  const layer = usePrRef(null);
  const [failed, setFailed] = usePrState(false);
  usePrEffect(() => {
    let alive = true;
    prEnsureLeaflet().then(L => {
      if (!alive || !box.current || map.current) return;
      const m = L.map(box.current, { scrollWheelZoom: false, attributionControl: true });
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 16, attribution: 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors',
      }).addTo(m);
      map.current = m;
      layer.current = L.layerGroup().addTo(m);
      draw(true);
      setTimeout(() => { m.invalidateSize(); }, 250);
    }).catch(() => alive && setFailed(true));
    return () => { alive = false; if (map.current) { map.current.remove(); map.current = null; } };
  }, [geo]);
  usePrEffect(() => { draw(false); }, [legs, sel]);
  function draw(fit) {
    const L = window.L, m = map.current;
    if (!L || !m || !layer.current) return;
    layer.current.clearLayers();
    const pts = prWaypoints(geo);
    const ll = pts.map(f => [f.geometry.coordinates[1], f.geometry.coordinates[0]]);
    for (let i = 0; i < ll.length - 1; i++) {
      const lg = legs && legs[i];
      const key = lg ? prKey(lg.label) : 'none';
      const on = !!(sel && sel.indexOf(i) >= 0);
      L.polyline([ll[i], ll[i + 1]], { color: '#fff', weight: on ? 11 : 8, opacity: 0.9 }).addTo(layer.current);
      L.polyline([ll[i], ll[i + 1]], { color: PR_COLORS[key], weight: on ? 7 : 5, opacity: 1,
        dashArray: lg && lg.label ? null : '6 6', className: 'pr-leg' })
        .bindTooltip(`<b>${i + 1}. ${pts[i].properties.leg}</b>${lg && lg.label ? ' · ' + lg.label + (lg.windRel ? ' · ' + PR_REL[lg.windRel] : '') : ''}`,
                     { sticky: true, className: 'pr-tip' })
        .on('click', () => onSel(i))
        .addTo(layer.current);
      // heading arrow at the middle of the leg
      const a = ll[i], b = ll[i + 1];
      const p1 = m.project(a), p2 = m.project(b);
      const deg = Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180 / Math.PI;
      L.marker([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], { interactive: false, keyboard: false,
        icon: L.divIcon({ className: 'pr-arrow-wrap', iconSize: [14, 14], iconAnchor: [7, 7],
          html: `<svg class="pr-arrow" viewBox="0 0 14 14" style="transform:rotate(${deg}deg)"><path d="M3 2l8 5-8 5z" fill="${PR_COLORS[key]}" stroke="#fff" stroke-width="1.2"/></svg>` }) })
        .addTo(layer.current);
    }
    pts.forEach((f, i) => {
      const role = f.properties.role;
      if (role === 'via') return;
      const txt = role === 'start' ? 'S' : role === 'finish' ? 'F' : '';
      L.marker(ll[i], { keyboard: false, title: f.properties.name,
        icon: L.divIcon({ className: 'pr-wp-wrap', iconSize: [20, 20], iconAnchor: [10, 10],
          html: `<span class="pr-wp pr-wp-${role}">${txt}</span>` }) })
        .bindTooltip(f.properties.name, { direction: 'top', offset: [0, -8], className: 'pr-tip' })
        .addTo(layer.current);
    });
    if (fit) m.fitBounds(ll, { padding: [24, 24] });
  }
  if (failed) return <div className="pr-map pr-map-fail">Map unavailable.</div>;
  return <div className="pr-map" ref={box} role="img" aria-label="Race course map"/>;
}

// ── race page ───────────────────────────────────────────────────────────────
// Rows = named legs (consecutive segments with the same `leg` name). sel = row index.
function prLegGroups(pts, legs) {
  const groups = [];
  pts.slice(0, -1).forEach((p, i) => {
    const name = p.properties.leg;
    const g = groups.length && groups[groups.length - 1].name === name ? groups[groups.length - 1] : null;
    if (g) g.idx.push(i); else groups.push({ name, idx: [i] });
  });
  groups.forEach(g => {
    const ls = legs ? g.idx.map(i => legs[i]).filter(Boolean) : [];
    g.miles = ls.reduce((t, l) => t + l.miles, 0);
    g.first = ls[0] || null;
    g.long = ls.slice().sort((a, b) => b.miles - a.miles)[0] || null;
    const scored = ls.filter(l => l.score != null);
    g.worst = scored.sort((a, b) => a.score - b.score)[0] || null;
    g.swell = ls.filter(l => l.swellFt != null).sort((a, b) => b.swellFt - a.swellFt)[0] || null;
    g.cur = ls.filter(l => l.currentKt != null).sort((a, b) => Math.abs(b.currentKt) - Math.abs(a.currentKt))[0] || null;
  });
  return groups;
}

function PrLegTable({ groups, sel, onSel }) {
  return (
    <div className="pr-legs" role="table" aria-label="Leg by leg forecast">
      <div className="pr-leg-row pr-leg-head" role="row">
        <span role="columnheader">Leg</span><span role="columnheader">On it</span>
        <span role="columnheader">Wind</span><span role="columnheader">Swell / current</span><span role="columnheader"></span>
      </div>
      {groups.map((g, n) => {
        const w = g.worst || g.first, L1 = g.long;
        return (
          <button type="button" key={n} role="row" className={`pr-leg-row${sel === n ? ' on' : ''}`} onClick={() => onSel(sel === n ? null : n)}>
            <span role="cell" className="pr-leg-name">
              <i className={`pr-dot pr-${prKey(w && w.label)}`}/>{n + 1}. {g.name}
              <small>{L1 ? `heading ${prDir(L1.bearing)} · ${prMiles(g.miles, true)}` : ''}</small>
            </span>
            <span role="cell">{g.first ? prClock(g.first.eta) : ''}</span>
            <span role="cell">
              {w && w.windKt != null ? <>{prDir(w.windFrom)} {Math.round(w.windKt)} kt{w.gustKt && w.gustKt >= w.windKt + 3 ? <span className="pr-g"> g{Math.round(w.gustKt)}</span> : ''}<small>{PR_REL[w.windRel]}</small></> : '—'}
            </span>
            <span role="cell">
              {g.swell ? <>{g.swell.swellFt} ft {g.swell.swellS ? Math.round(g.swell.swellS) + 's' : ''}<small>swell {g.swell.swellRel ? PR_SWELL[g.swell.swellRel] : prDir(g.swell.swellFrom)}</small></>
                : g.cur ? <>{Math.abs(g.cur.currentKt).toFixed(1)} kt<small>{g.cur.currentKt > 0.2 ? 'current with you' : g.cur.currentKt < -0.2 ? 'current against you' : 'slack'}</small></>
                : '—'}
            </span>
            <span role="cell">{w && <PrPill label={w.label}/>}</span>
          </button>
        );
      })}
    </div>
  );
}

function PrStartWindow({ b }) {
  if (!b) return null;
  const max = 4;
  return (
    <div className="pr-best">
      <div className="pr-best-h"><b>Best start {prHhmm(b.from)}{b.to !== b.from ? '–' + prHhmm(b.to) : ''}</b> <PrPill label={b.label}/></div>
      <div className="pr-bars" aria-hidden="true">
        {b.byStart.map(s => (
          <span key={s.start} className={`pr-bar pr-${prKey(prLabelOf(s.score))}`} style={{ height: (8 + 36 * s.score / max) + 'px' }}
                title={prHhmm(s.start) + ' · ' + prLabelOf(s.score)}/>
        ))}
      </div>
      <div className="pr-bars-x"><span>{prHhmm(b.byStart[0].start)}</span><span>{prHhmm(b.byStart[b.byStart.length - 1].start)}</span></div>
    </div>
  );
}
function prLabelOf(s) { return s >= 3.5 ? 'Great' : s >= 2.5 ? 'Good' : s >= 1.5 ? 'Fair' : s >= 0.5 ? 'Poor' : 'Hard'; }

function PrRacePage({ race, fc, hrefFor, go }) {
  const dists = race.distances || [];
  const [distId, setDistId] = usePrState((dists.find(d => d.courseId) || dists[0] || {}).id);
  const [sel, setSel] = usePrState(null);
  usePrEffect(() => { window.scrollTo(0, 0); }, [race.id]);
  const dist = dists.find(d => d.id === distId) || dists[0] || {};
  const geoSt = usePrJson(dist.courseId ? 'paddle_courses/' + dist.courseId + '.geojson' : null);
  const geo = geoSt.data;
  const f = fc && fc.races && fc.races[race.id] && fc.races[race.id][dist.id];
  const today = prToday();
  const past = race.date && race.date < today;
  const daysOut = race.date ? Math.round((Date.parse(race.date) - Date.parse(today)) / 864e5) : null;
  const pts = geo ? prWaypoints(geo) : [];
  const groups = prLegGroups(pts, f && f.legs);
  const draft = race.status && race.status.startsWith('draft');
  return (
    <div className="pr-wrap">
      <PrLink className="pr-crumb" hrefFor={hrefFor} go={go} id="">← All races</PrLink>
      <h1 className="pr-title">{race.name} {race.year ? <span className="pr-year">{race.year}</span> : null}</h1>
      <p className="pr-meta">
        {race.date ? prDate(race.date, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) : 'Date TBC'}
        {race.startLocal ? ' · start ' + prHhmm(race.startLocal) : ''} · {race.location.name}
      </p>
      {draft && <p className="pr-flag">Draft: details and course not yet confirmed.</p>}

      {dists.length > 1 && (
        <div className="pr-tabs" role="tablist" aria-label="Distance">
          {dists.map(d => (
            <button key={d.id} type="button" role="tab" aria-selected={d.id === dist.id}
                    className={`pr-tab${d.id === dist.id ? ' on' : ''}`} onClick={() => { setDistId(d.id); setSel(null); }}>
              {d.label} <small>{prMiles(d.miles)}</small>
            </button>
          ))}
        </div>
      )}

      <section className="pr-call" aria-label="Race-day forecast">
        {f ? (
          <>
            <div className="pr-call-top"><PrPill big label={f.label}/><span className="pr-call-reason">{f.reason}</span></div>
            <p className="pr-muted pr-small">
              {f.preview ? 'Preview: scored as if the race were ' + prDate(f.date, { weekday: 'short', month: 'short', day: 'numeric' }) + '. ' : ''}
              Start {prHhmm(f.start)}{f.startAssumed ? ' (assumed)' : ''} · {f.paceMph} mph pace
              {fc.waterTemp ? ' · water ' + fc.waterTemp.f + '°F' : ''}
            </p>
            <PrStartWindow b={f.bestStart}/>
          </>
        ) : (
          <p className="pr-muted">
            {past ? 'Past race.' : !race.date ? 'Forecast once the date is set.'
              : !dist.courseId ? 'Forecast once the course is mapped.'
              : daysOut != null && daysOut > ((fc && fc.horizonDays) || 7) ? `Forecast opens ${(fc && fc.horizonDays) || 7} days out.`
              : 'No forecast yet.'}
          </p>
        )}
      </section>

      {dist.courseId ? (
        geo ? (
          <>
            <PrCourseMap geo={geo} legs={f && f.legs} sel={sel != null && groups[sel] ? groups[sel].idx : null}
                         onSel={i => setSel(groups.findIndex(g => g.idx.indexOf(i) >= 0))}/>
            <p className="pr-muted pr-small">{geo.properties.summary}{geo.properties.status && geo.properties.status.startsWith('draft') ? ' Course is a draft, drawn from the written description.' : ''}</p>
            <PrLegTable groups={groups} sel={sel} onSel={setSel}/>
          </>
        ) : geoSt.error ? <p className="pr-muted">Course map unavailable.</p> : <p className="pr-muted">Loading course…</p>
      ) : <p className="pr-muted">Course not mapped yet.</p>}

      <section className="pr-details" aria-labelledby="pr-det-h">
        <h2 className="pr-h2" id="pr-det-h">Race details</h2>
        <dl className="pr-dl">
          <dt>Date</dt><dd>{race.date ? prDate(race.date, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }) : 'TBC'}</dd>
          <dt>Start</dt><dd>{race.startLocal ? prHhmm(race.startLocal) : 'TBC'}</dd>
          <dt>Location</dt><dd>{race.location.name}</dd>
          <dt>Distances</dt><dd>{dists.map(d => d.label + ' ' + prMiles(d.miles)).join(' · ')}</dd>
          <dt>Divisions</dt><dd>{(race.divisions || []).join(', ') || 'TBC'}</dd>
          {race.organiser && <><dt>Organiser</dt><dd>{race.organiser}</dd></>}
          {race.course && <><dt>Course</dt><dd>{race.course}</dd></>}
          {race.notes && <><dt>Notes</dt><dd>{race.notes}</dd></>}
          {race.registration && <><dt>Register</dt><dd><a href={race.registration} target="_blank" rel="noopener">Registration →</a></dd></>}
        </dl>
        {race.paddleguru
          ? <a className="pr-pg" href={race.paddleguru} target="_blank" rel="noopener">Race page on PaddleGuru →</a>
          : <p className="pr-muted pr-small">PaddleGuru link to come.</p>}
        {race.sources && race.sources.length > 0 && <p className="pr-src">Sources: {race.sources.join('; ')}.</p>}
      </section>
    </div>
  );
}

function PaddleRaces({ raceId, hrefFor, go }) {
  usePrEffect(prEnsureCss, []);
  const races = usePrJson('paddle_races.json');
  const fc = usePrJson('paddle_race_forecast.json');
  if (races.error) return <div className="pr-wrap"><h1 className="pr-title">Races</h1><p className="pr-muted">The race list is unavailable right now.</p></div>;
  if (!races.data) return <div className="pr-wrap"><h1 className="pr-title">Races</h1><p className="pr-muted">Loading races…</p></div>;
  const props = { fc: fc.data, hrefFor, go };
  if (raceId) {
    const race = (races.data.races || []).find(r => r.id === raceId);
    if (!race) return <div className="pr-wrap"><h1 className="pr-title">Race not found</h1><PrLink className="pr-crumb" hrefFor={hrefFor} go={go} id="">← All races</PrLink></div>;
    return <PrRacePage key={race.id} race={race} {...props}/>;
  }
  return <PrList doc={races.data} {...props}/>;
}

window.PaddleRaces = PaddleRaces;
