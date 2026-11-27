// San Diego surf forecast page (/sd/surf). Reads api/v1/surf.json, written by
// src/surf/forecast.py (+ display-only fields from src/surf/extras.py):
// CDIP MOP per break, our breaking step, Open-Meteo wind, NOAA tides, a 0–5
// rating, sun times, buoy water temperature and the NWS Surf Zone Forecast.
//
// Labelled "Model forecast" everywhere. Face heights and ratings are model
// estimates (no surf observations yet); the only accuracy numbers shown are
// the held-out buoy scores in surf.json's `verification` block.
//
// Layout (glance → detail), after Surfline / Surf-forecast.com:
//   conditions (sun, water, tide curve) + break map
//   per break: today's AM/PM, best window, 7-day strip (rating + height / 3 h)
//   expanded: tide curve with the break's tide window, hourly table
const { useState: useSfState, useEffect: useSfEffect, useMemo: useSfMemo, useRef: useSfRef } = React;

const SF_TZ = 'America/Los_Angeles';
const SF_STALE_H = 12;
const SF_FT = 3.281;

function sfLocal(iso, opts) {
  return new Date(iso).toLocaleString('en-US', Object.assign({ timeZone: SF_TZ }, opts));
}
function sfDayKey(iso) { return sfLocal(iso, { year: 'numeric', month: '2-digit', day: '2-digit' }); }
function sfHour(iso) { return Number(sfLocal(iso, { hour: 'numeric', hour12: false })) % 24; }
// Local time of day in hours (e.g. 6.5 = 6:30 AM).
function sfFrac(iso) {
  return sfHour(iso) + Number(sfLocal(iso, { minute: 'numeric' })) / 60;
}
function sfClock(iso) {
  return sfLocal(iso, { hour: 'numeric', minute: '2-digit' }).replace(':00', '').replace(' AM', 'a').replace(' PM', 'p');
}
function sfFracClock(f) {
  const h = Math.floor(f), m = Math.round((f - h) * 60);
  const hh = ((h + 11) % 12) + 1;
  return hh + (m ? ':' + String(m).padStart(2, '0') : '') + (h < 12 ? ' AM' : ' PM');
}

const SF_COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
function sfDir(d) { return d == null ? '' : SF_COMPASS[Math.round(((d % 360) + 360) % 360 / 22.5) % 16]; }

// "Sets to X ft": hours[].setsFt is the H1/10 bigger-waves height (1.27 x breaking
// height), the same statistic as NWS San Diego's "with sets to X ft". Shown only
// when it tops the band.
function sfSets(h) { return h && h.setsFt != null && h.faceFt && h.setsFt > h.faceFt[1] ? h.setsFt : null; }
function sfSetsTxt(h, unit) { const x = sfSets(h); return x == null ? '' : ` · sets to ${x}${unit === false ? '' : ' ft'}`; }

function sfBand(lo, hi) {
  const m = (lo + hi) / 2;
  if (m < 1) return 'flat';
  if (m < 2) return 'ankle–knee';
  if (m < 3) return 'knee–waist';
  if (m < 4) return 'waist–chest';
  if (m < 5) return 'chest–shoulder';
  if (m < 6) return 'head high';
  if (m < 8) return 'overhead';
  return 'well overhead';
}

function sfRateKey(label) { return String(label || 'flat').toLowerCase().replace(/[^a-z]+/g, '-'); }
function sfRatingClass(label) { return 'sf-rate sf-rate-' + sfRateKey(label); }
function sfTitle(label) {
  return String(label || '').toLowerCase().replace(/(^|[–-])([a-z])/g, (m, a, b) => a + b.toUpperCase());
}

// The step closest to a local hour on a given day, within 2 h (steps are
// 3-hourly); none when that time has passed or isn't in the forecast.
function sfPick(hours, dayKey, localHour) {
  let best = null, bestD = 99;
  hours.forEach(h => {
    if (sfDayKey(h.t) !== dayKey) return;
    const d = Math.abs(sfHour(h.t) - localHour);
    if (d < bestD) { best = h; bestD = d; }
  });
  return bestD <= 2 ? best : null;
}

function sfSunFor(sun, dayKey) {
  return (sun || []).find(s => s.sunrise && sfDayKey(s.sunrise) === dayKey) || null;
}
// Daylight test for a step: between first light and last light that day.
// Without sun data, 6 AM–6 PM.
function sfIsDay(iso, sun) {
  const s = sfSunFor(sun, sfDayKey(iso));
  const t = Date.parse(iso);
  if (!s || !s.firstLight || !s.lastLight) { const h = sfHour(iso); return h >= 6 && h <= 18; }
  return t >= Date.parse(s.firstLight) && t <= Date.parse(s.lastLight);
}

// Best window on a day: the highest-rated daylight step (each step stands for
// about 3 h of model time), shown as ±1.5 h around it, clipped to first light
// and sunset. Ties go to the earlier step (morning wind is usually lighter).
function sfBestWindow(hours, dayKey, sun) {
  const nowMs = Date.now() - 90 * 60000;
  const s = sfSunFor(sun, dayKey);
  const steps = hours.filter(h => sfDayKey(h.t) === dayKey && Date.parse(h.t) >= nowMs && sfIsDay(h.t, sun));
  if (!steps.length) return null;
  let best = steps[0];
  steps.forEach(h => { if (h.score > best.score + 0.05) best = h; });
  let a = sfFrac(best.t) - 1.5, b = sfFrac(best.t) + 1.5;
  if (s && s.firstLight) a = Math.max(a, sfFrac(s.firstLight));
  if (s && s.sunset) b = Math.min(b, sfFrac(s.sunset));
  a = Math.ceil(a * 2) / 2; b = Math.floor(b * 2) / 2;
  return { h: best, from: a, to: Math.max(b, a + 0.5) };
}

// More county spots (src/surf/spots.py, default settings), optional: the page
// works without it and drops it when it is older than its staleAfterHours.
function useSurfSpots() {
  const [spots, setSpots] = useSfState(null);
  useSfEffect(() => {
    let alive = true;
    const hour = Math.floor(Date.now() / 3600000);
    fetch('/api/v1/surf_spots.json?h=' + hour)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!alive || !d || !Array.isArray(d.spots)) return;
        const ageH = (Date.now() - Date.parse(d.generatedAt)) / 3600000;
        if (ageH <= (d.staleAfterHours || 30)) setSpots(d);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  return spots;
}

// Areas, north to south (same limits as src/surf/spots.py AREAS).
const SF_AREAS = [[32.975, 'North County'], [32.81, 'Del Mar–La Jolla'], [32.70, 'PB–Point Loma'], [-90, 'Coronado–Imperial Beach']];
function sfArea(lat) { return SF_AREAS.find(a => lat > a[0])[1]; }

function useSurfData() {
  const [state, setState] = useSfState({ data: null, error: false });
  useSfEffect(() => {
    let alive = true;
    const hour = Math.floor(Date.now() / 3600000);
    fetch('/api/v1/surf.json?h=' + hour)
      .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(d => { if (alive) setState({ data: d, error: false }); })
      .catch(() => { if (alive) setState({ data: null, error: true }); });
    return () => { alive = false; };
  }, []);
  return state;
}

// Width of an element, kept current (SVG charts draw at real pixel width so
// their text stays readable on a phone).
function useSfWidth(fallback) {
  const ref = useSfRef(null);
  const [w, setW] = useSfState(fallback);
  useSfEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const set = () => { const v = Math.round(el.getBoundingClientRect().width); if (v > 0) setW(v); };
    set();
    if (typeof ResizeObserver === 'undefined') { window.addEventListener('resize', set); return () => window.removeEventListener('resize', set); }
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

// ── Tide curve ────────────────────────────────────────────────────────────
// Hourly NOAA predictions for the local day, hi/lo labels, night shading and,
// for a break, its tide window shaded with the in-window part of the curve
// drawn heavier.
function SurfTide({ tides, dayKey, sun, win, marks, compact }) {
  const [ref, W] = useSfWidth(600);
  const H = compact ? 118 : 132;
  const pad = { l: 30, r: 8, t: 16, b: 20 };
  const hourly = (tides && tides.hourly) || [];
  const pts = [];
  let last = -1;
  hourly.forEach(([t, ft], i) => {
    if (sfDayKey(t) === dayKey) { pts.push([sfFrac(t), ft]); last = i; }
  });
  // close the day with the next local midnight
  if (last >= 0 && hourly[last + 1]) pts.push([24, hourly[last + 1][1]]);
  if (pts.length < 6) return null;
  pts.sort((a, b) => a[0] - b[0]);
  const hilo = ((tides && tides.hilo) || []).filter(x => sfDayKey(x.t) === dayKey);
  const vals = pts.map(p => p[1]).concat(win ? win : []);
  const lo = Math.floor(Math.min(-1, ...vals) - 0.8), hi = Math.ceil(Math.max(6, ...vals) + 0.6);
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const x = f => pad.l + f / 24 * iw;
  const y = ft => pad.t + (hi - ft) / (hi - lo) * ih;
  const line = pts.map((p, i) => (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[1]).toFixed(1)).join(' ');
  const area = line + ` L${x(pts[pts.length - 1][0]).toFixed(1)} ${y(lo)} L${x(pts[0][0]).toFixed(1)} ${y(lo)} Z`;
  const s = sfSunFor(sun, dayKey);
  const dawn = s && s.firstLight ? sfFrac(s.firstLight) : null;
  const dusk = s && s.lastLight ? sfFrac(s.lastLight) : null;
  const isToday = dayKey === sfDayKey(new Date().toISOString());
  const nowF = isToday ? sfFrac(new Date().toISOString()) : null;
  const clipId = 'sfclip-' + Math.random().toString(36).slice(2, 8);
  const gridFt = [];
  for (let v = Math.ceil(lo / 2) * 2; v <= hi; v += 2) gridFt.push(v);
  const label = win
    ? `Tide at La Jolla on this day, with this break's best tide (${win[0]} to ${win[1]} ft) shaded`
    : 'Tide at La Jolla on this day';
  return (
    <div className="sf-tide" ref={ref}>
      <svg width={W} height={H} role="img" aria-label={label}>
        {dawn != null && <rect className="sf-tide-night" x={pad.l} y={pad.t} width={Math.max(0, x(dawn) - pad.l)} height={ih}/>}
        {dusk != null && <rect className="sf-tide-night" x={x(dusk)} y={pad.t} width={Math.max(0, x(24) - x(dusk))} height={ih}/>}
        {gridFt.map(v => (
          <g key={v}>
            <line className="sf-tide-grid" x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)}/>
            <text className="sf-tide-ax" x={pad.l - 5} y={y(v) + 3.5} textAnchor="end">{v}</text>
          </g>
        ))}
        {win && <rect className="sf-tide-win" x={pad.l} width={iw} y={y(win[1])} height={Math.max(1, y(win[0]) - y(win[1]))}/>}
        <path className="sf-tide-area" d={area}/>
        <path className="sf-tide-line" d={line}/>
        {win && (
          <>
            <clipPath id={clipId}><rect x={pad.l} width={iw} y={y(win[1])} height={Math.max(1, y(win[0]) - y(win[1]))}/></clipPath>
            <path className="sf-tide-line-in" d={line} clipPath={`url(#${clipId})`}/>
          </>
        )}
        {(marks || []).map(f => <line key={f} className="sf-tide-mark" x1={x(f)} x2={x(f)} y1={y(lo)} y2={y(lo) - 4}/>)}
        {nowF != null && <line className="sf-tide-now" x1={x(nowF)} x2={x(nowF)} y1={pad.t} y2={y(lo)}/>}
        {hilo.map(p => {
          const f = sfFrac(p.t), px = x(f), py = y(p.ft);
          const up = p.type === 'H';
          const anchor = px < pad.l + 26 ? 'start' : px > W - pad.r - 26 ? 'end' : 'middle';
          return (
            <g key={p.t}>
              <circle className="sf-tide-dot" cx={px} cy={py} r="3"/>
              <text className="sf-tide-lbl" x={px} y={up ? py - 6 : py + 13} textAnchor={anchor}>
                {p.ft} ft {sfClock(p.t)}
              </text>
            </g>
          );
        })}
        {[0, 6, 12, 18].map(f => (
          <text key={f} className="sf-tide-ax" x={x(f) + (f === 0 ? 0 : 0)} y={H - 5} textAnchor={f === 0 ? 'start' : 'middle'}>
            {f === 0 ? '12a' : f === 12 ? '12p' : f < 12 ? f + 'a' : (f - 12) + 'p'}
          </text>
        ))}
        <text className="sf-tide-ax" x={W - pad.r} y={H - 5} textAnchor="end">ft MLLW</text>
      </svg>
    </div>
  );
}

// ── Conditions: sun, water temperature, tide ─────────────────────────────
function SurfConditions({ data, dayKey }) {
  const s = sfSunFor(data.sun, dayKey);
  const wt = data.waterTemp;
  const nwsWater = data.nws && data.nws.periods && data.nws.periods[0] && data.nws.periods[0].water;
  return (
    <section className="sf-cond" aria-label="Conditions">
      <div className="sf-cond-tiles">
        <div className="sf-tile"><span>First light</span><b>{s && s.firstLight ? sfLocal(s.firstLight, { hour: 'numeric', minute: '2-digit' }) : '—'}</b></div>
        <div className="sf-tile"><span>Sunrise</span><b>{s && s.sunrise ? sfLocal(s.sunrise, { hour: 'numeric', minute: '2-digit' }) : '—'}</b></div>
        <div className="sf-tile"><span>Sunset</span><b>{s && s.sunset ? sfLocal(s.sunset, { hour: 'numeric', minute: '2-digit' }) : '—'}</b></div>
        <div className="sf-tile" title={wt ? `CDIP buoy ${wt.station}, ${sfLocal(wt.t, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}` : ''}>
          <span>Water</span>
          <b>{wt ? `${wt.f}°F` : nwsWater ? nwsWater.replace(' degrees', '°F') : '—'}</b>
          <i>{wt ? `${sfWetsuit(wt.f)} · buoy ${wt.station}` : nwsWater ? 'NWS' : ''}</i>
        </div>
      </div>
      <div className="sf-cond-tide">
        <div className="sf-sec-h">Tide · La Jolla</div>
        <SurfTide tides={data.tides} dayKey={dayKey} sun={data.sun} compact/>
      </div>
    </section>
  );
}

// ── Break map (Leaflet, lazy-loaded like the Charts page) ────────────────
let _sfLeaflet = null;
function sfEnsureLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (_sfLeaflet) return _sfLeaflet;
  _sfLeaflet = new Promise((resolve, reject) => {
    const el = document.getElementById('tt-leaflet-js');
    const src = (el && el.getAttribute('src')) || 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js';
    const s = document.createElement('script');
    s.src = src; s.crossOrigin = 'anonymous';
    s.onload = () => resolve(window.L);
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return _sfLeaflet;
}

function SurfMap({ breaks, best, open, onPick }) {
  const box = useSfRef(null);
  const map = useSfRef(null);
  const layer = useSfRef(null);
  const labels = useSfRef(null);
  const placeRef = useSfRef(null);   // latest placeLabels (fresh breaks/best/open) for map events
  const [failed, setFailed] = useSfState(false);
  useSfEffect(() => {
    let alive = true;
    sfEnsureLeaflet().then(L => {
      if (!alive || !box.current || map.current) return;
      const m = L.map(box.current, { scrollWheelZoom: false, zoomControl: true, attributionControl: true });
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 16, attribution: 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors',
      }).addTo(m);
      const fit = () => { m.invalidateSize(); m.fitBounds(breaks.map(b => [b.lat, b.lon]), { padding: [18, 18] }); };
      fit();
      setTimeout(fit, 250);   // the grid cell settles its height after first paint
      map.current = m;
      m.createPane('sfLabels').style.zIndex = 590;   // under the pins (600), over tiles
      layer.current = L.layerGroup().addTo(m);
      labels.current = L.layerGroup().addTo(m);
      m.on('zoomend moveend resize', () => placeRef.current && placeRef.current());
      draw();
    }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; if (map.current) { map.current.remove(); map.current = null; } };
  }, []);
  function draw() {
    const L = window.L;
    if (!L || !layer.current) return;
    layer.current.clearLayers();
    breaks.forEach(b => {
      const bw = best[b.id];
      const key = bw ? sfRateKey(bw.h.label) : 'none';
      const txt = bw ? (bw.h.faceFt[0] === bw.h.faceFt[1] ? bw.h.faceFt[0] : bw.h.faceFt[0] + '–' + bw.h.faceFt[1]) : '·';
      const icon = L.divIcon({
        className: 'sf-pin-wrap',
        html: `<span class="sf-pin sf-pin-${key}${b.defaults ? ' def' : ''}${open === b.id ? ' on' : ''}"></span>`,
        iconSize: b.defaults ? [11, 11] : [16, 16], iconAnchor: b.defaults ? [5.5, 5.5] : [8, 8],
      });
      L.marker([b.lat, b.lon], { icon, title: b.name, keyboard: true, zIndexOffset: open === b.id ? 1000 : 0 })
        .bindTooltip(`<b>${b.name}</b> surf ${txt} ft${bw ? sfSetsTxt(bw.h, false) : ''}${bw ? ' · ' + sfTitle(bw.h.label) : ''}${b.defaults ? ' · default settings' : ''}`,
                     { direction: 'left', offset: [-8, 0], className: 'sf-tip' })
        .on('click', () => onPick(b.id))
        .addTo(layer.current);
    });
    placeLabels();
  }
  // Spot names next to the pins once zoomed in: tuned breaks from zoom 11, every
  // spot from 12. Greedy placement (right, left, above, below the pin) that
  // never covers a pin or another label; a name with no free spot is skipped
  // until the map is zoomed further in.
  function placeLabels() {
    const L = window.L, m = map.current;
    if (!L || !m || !labels.current) return;
    labels.current.clearLayers();
    const z = m.getZoom();
    if (z < 11) return;
    const size = m.getSize();
    const font = '600 12px ' + getComputedStyle(box.current).fontFamily;
    const ctx = (placeLabels.cv || (placeLabels.cv = document.createElement('canvas'))).getContext('2d');
    ctx.font = font;
    const pts = breaks.map(b => ({ b, p: m.latLngToContainerPoint([b.lat, b.lon]), r: b.defaults ? 6.5 : 9 }))
      .filter(o => o.p.x > -60 && o.p.y > -30 && o.p.x < size.x + 60 && o.p.y < size.y + 30);
    const boxes = pts.map(o => ({ x0: o.p.x - o.r, y0: o.p.y - o.r, x1: o.p.x + o.r, y1: o.p.y + o.r }));
    // the zoom buttons and the tile credits are obstacles too
    const mr = box.current.getBoundingClientRect();
    box.current.querySelectorAll('.leaflet-control').forEach(c => {
      const r = c.getBoundingClientRect();
      if (r.width) boxes.push({ x0: r.left - mr.left - 3, y0: r.top - mr.top - 3, x1: r.right - mr.left + 3, y1: r.bottom - mr.top + 3 });
    });
    const hit = (r, list) => list.some(q => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0);
    const rank = o => (o.b.id === open ? 0 : 10) + (o.b.defaults ? 5 : 0)
      - ['flat', 'poor', 'poor-fair', 'fair', 'fair-good', 'good'].indexOf(best[o.b.id] ? sfRateKey(best[o.b.id].h.label) : 'flat') / 10;
    const placed = [];
    pts.filter(o => z >= 12 || !o.b.defaults).sort((a, c) => rank(a) - rank(c)).forEach(o => {
      const w = Math.ceil(ctx.measureText(o.b.name).width) + 10, h = 18, { x, y } = o.p, g = o.r + 3;
      const spots = [[x + g, y - h / 2], [x - g - w, y - h / 2], [x - w / 2, y - g - h], [x - w / 2, y + g]];
      for (const [x0, y0] of spots) {
        const r = { x0, y0, x1: x0 + w, y1: y0 + h };
        if (r.x0 < 2 || r.y0 < 2 || r.x1 > size.x - 2 || r.y1 > size.y - 2) continue;
        if (hit(r, boxes) || hit(r, placed)) continue;
        placed.push({ x0: x0 - 2, y0: y0 - 2, x1: r.x1 + 2, y1: r.y1 + 2 });
        L.marker([o.b.lat, o.b.lon], {
          pane: 'sfLabels', keyboard: false, interactive: true,
          icon: L.divIcon({ className: 'sf-lbl-wrap', iconSize: [w, h], iconAnchor: [x - x0, y - y0],
                            html: `<span class="sf-lbl${o.b.defaults ? ' def' : ''}">${o.b.name.replace(/[&<>"]/g, c => '&#' + c.charCodeAt(0) + ';')}</span>` }),
        }).on('click', () => onPick(o.b.id)).addTo(labels.current);
        break;
      }
    });
  }
  placeRef.current = placeLabels;
  useSfEffect(() => { draw(); }, [breaks, best, open]);
  if (failed) return null;
  return (
    <section className="sf-map-wrap" aria-label="Map of surf breaks">
      <div className="sf-map" ref={box}/>
      <div className="sf-map-cap">Coloured by each break's best model rating for the day. Tap a dot to open the break.</div>
    </section>
  );
}

// ── 7-day strip: rating bar + height bar per 3 h step ────────────────────
// Each strip is scaled to its own break's biggest day (at least 6 ft), the way
// Surfline scales per spot; the top line is labelled so sizes stay readable.
function SurfStrip({ b, days, dayKey, sun, onDay }) {
  const keys = days.map(d => d.key);
  let top = 0;
  b.hours.forEach(h => { if (keys.indexOf(sfDayKey(h.t)) >= 0 && h.faceFt[1] > top) top = h.faceFt[1]; });
  const scaleFt = Math.max(6, Math.ceil(top / 2) * 2);
  return (
    <div className="sf-strip" role="group" aria-label={`${b.name}, 7-day outlook`}>
      {days.map(d => {
        const steps = b.hours.filter(h => sfDayKey(h.t) === d.key);
        return (
          <button key={d.key} type="button" className={`sf-sday${d.key === dayKey ? ' on' : ''}`}
                  onClick={e => { e.stopPropagation(); onDay(d.key); }}
                  aria-label={`${d.label}: surf up to ${Math.max(0, ...steps.map(h => h.faceFt[1]))} ft`}>
            <span className="sf-sday-lbl">{d.wd}<span className="sf-sday-n"> {d.dn}</span></span>
            <span className="sf-bars">
              {steps.map(h => {
                const night = !sfIsDay(h.t, sun);
                // faceMidFt (round 8) is the unrounded mid face; older files fall back to the band mid
                const mid = h.faceMidFt != null ? h.faceMidFt : (h.faceFt[0] + h.faceFt[1]) / 2;
                const pMid = Math.min(100, mid / scaleFt * 100);
                const pHi = Math.min(100, h.faceFt[1] / scaleFt * 100);
                const key = sfRateKey(h.label);
                return (
                  <span key={h.t} className={`sf-bar${night ? ' night' : ''}`}
                        title={`${sfLocal(h.t, { weekday: 'short', hour: 'numeric' })} · ${h.faceFt[0]}–${h.faceFt[1]} ft${sfSetsTxt(h, false)} · ${sfTitle(h.label)}${h.windKt != null ? ` · wind ${h.windKt} kt ${h.windType}` : ''}`}>
                    <span className={`sf-bar-hi sf-c-${key}`} style={{ height: pHi + '%' }}/>
                    <span className={`sf-bar-mid sf-c-${key}`} style={{ height: Math.max(pMid, mid > 0 ? 3 : 0) + '%' }}/>
                  </span>
                );
              })}
            </span>
            <span className="sf-rbar">
              {steps.map(h => <span key={h.t} className={`sf-c-${sfRateKey(h.label)}${sfIsDay(h.t, sun) ? '' : ' night'}`}/>)}
            </span>
          </button>
        );
      })}
      <span className="sf-strip-scale" aria-hidden="true">bars to {scaleFt} ft</span>
    </div>
  );
}

function SurfSlot({ h, label, def }) {
  if (!h) return <div className="sf-slot sf-slot-empty"><span className="sf-slot-lbl">{label}</span>—</div>;
  const [lo, hi] = h.faceFt;
  return (
    <div className="sf-slot">
      <span className="sf-slot-lbl">{label}</span>
      <span className="sf-face" title="Surf height: breaking wave face at the beach">{lo === hi ? lo : `${lo}–${hi}`}<small> ft</small>
        {h.energyKj != null && <em className="sf-kj" title="Wave energy at the model point, kJ (Surf-forecast.com scale: about 100 small, 200–1000 punchy)">{h.energyKj} kJ</em>}
      </span>
      <span className="sf-band">{sfBand(lo, hi)}{sfSets(h) != null && <span className="sf-sets"> · sets to {sfSets(h)} ft</span>}</span>
      <span className={sfRatingClass(h.label)}>{sfTitle(h.label)}{h.faded ? ' · wind' : ''}</span>
      {def && <span className="sf-def-tag" title="Generic break settings, not tuned for this spot; rating capped at Fair">default settings</span>}
    </div>
  );
}

function SurfBest({ bw, isToday, dayLabel }) {
  if (!bw) return null;
  const h = bw.h;
  const when = `${sfFracClock(bw.from)}–${sfFracClock(bw.to)}`.replace(/ AM–(\d[\d:]*) AM/, '–$1 AM').replace(/ PM–(\d[\d:]*) PM/, '–$1 PM');
  if (h.score < 0.5) {
    return <div className="sf-best sf-best-none"><b>{isToday ? 'Best window today' : `Best window ${dayLabel}`}:</b> none. Flat or near flat all day.</div>;
  }
  return (
    <div className={`sf-best sf-best-${sfRateKey(h.label)}`}>
      <span className="sf-best-k">{isToday ? 'Best window today' : `Best window ${dayLabel}`}</span>
      <span className="sf-best-t">{when}</span>
      <span className="sf-best-d">
        {h.faceFt[0]}–{h.faceFt[1]} ft{sfSetsTxt(h, false)} · <b>{sfTitle(h.label)}</b>
        {h.windKt != null ? ` · ${h.windKt} kt ${h.windType}` : ''}
        {h.tideFt != null ? ` · tide ${h.tideFt} ft` : ''}
      </span>
    </div>
  );
}

function SurfBreakRow({ b, days, dayKey, dayLabel, sun, tides, buoy, bw, open, onToggle, onDay, fav, onFav, navigate }) {
  const am = sfPick(b.hours, dayKey, 7);
  const pm = sfPick(b.hours, dayKey, 13);
  const ref = am || pm;
  const steps = b.hours.filter(h => sfDayKey(h.t) === dayKey);
  const isToday = days[0] && days[0].key === dayKey;
  return (
    <li className={`sf-break${open ? ' open' : ''}`} id={`sf-${b.id}`}>
      <button className="sf-break-head" onClick={onToggle} aria-expanded={open}>
        <span className="sf-break-name">{b.name}
          <i>{b.type === 'reef' ? 'reef' : 'beach'} · faces {sfDir(b.shoreNormal)}</i>
        </span>
        <SurfSlot h={am} label="Morning" def={b.defaults}/>
        <SurfSlot h={pm} label="Afternoon" def={b.defaults}/>
        <span className="sf-chev" aria-hidden="true">{open ? '–' : '+'}</span>
      </button>
      {b.note && <div className="sf-note" role="note">{b.note}</div>}
      <div className="sf-break-glance">
        <SurfBest bw={bw} isToday={isToday} dayLabel={dayLabel}/>
        <SurfStrip b={b} days={days} dayKey={dayKey} sun={sun} onDay={onDay}/>
      </div>
      {ref && (
        <div className="sf-break-sub">
          Swell (offshore, not surf height) {(ref.hsM * SF_FT).toFixed(1)} ft @ {Math.round(ref.tpS)} s {sfDir(ref.dpDeg)} ({ref.dpDeg}°)
          {am && am.windKt != null ? ` · AM wind ${am.windKt} kt ${am.windType}` : ''}
          {pm && pm.windKt != null ? ` · PM ${pm.windKt} kt ${pm.windType}` : ''}
          {ref.conf !== 'high' ? ` · ${ref.conf} confidence` : ''}
          {ref.modelsDisagree ? ' · models disagree' : ''}
        </div>
      )}
      {open && (
        <div className="sf-detail">
          <div className="sf-actions">
            {onFav && <SurfStar on={fav} onClick={() => onFav(b.id)} name={b.name}/>}
            {navigate && <a className="sf-go" {...sfLinkProps(navigate, { sub: 'break', spot: b.id })}>Open {b.name} →</a>}
          </div>
          <div className="sf-detail-tide">
            <div className="sf-sec-h">Tide · best for this break {b.tideWindow ? `${b.tideWindow[0]} to ${b.tideWindow[1]} ft` : ''}</div>
            <SurfTide tides={tides} dayKey={dayKey} sun={sun} win={b.tideWindow} marks={steps.map(h => sfFrac(h.t))}/>
          </div>
          <div className="sf-steps" role="table" aria-label={`${b.name} by time of day`}>
            <div className="sf-step sf-step-h" role="row">
              <span>Time</span><span>Surf</span><span className="sf-nocase">kJ</span><span>Wind</span><span>Tide</span><span>Rating</span>
            </div>
            {steps.map(h => (
              <div key={h.t} className={`sf-step${sfIsDay(h.t, sun) ? '' : ' night'}`} role="row">
                <span>{sfClock(h.t)}</span>
                <span>{h.faceFt[0]}–{h.faceFt[1]} ft{sfSets(h) != null && <small className="sf-sets"> · sets {sfSets(h)}</small>}</span>
                <span>{h.energyKj != null ? h.energyKj : '—'}</span>
                <span>{h.windKt == null ? '—' : `${h.windKt} kt ${sfDir(h.windFrom)}`}</span>
                <span>{h.tideFt == null ? '—' : h.tideFt}</span>
                <span className={sfRatingClass(h.label)}>{h.score.toFixed(1)}</span>
              </div>
            ))}
          </div>
          {b.defaults && (
            <div className="sf-def-box">
              <b>Default settings.</b> This spot uses the same wave model as the main breaks, but with generic
              settings: its break type is a guess, any tide is scored the same, and its swell window
              ({b.swellWindow ? `${Math.round(((b.swellWindow[0] % 360) + 360) % 360)}° to ${Math.round(((b.swellWindow[1] % 360) + 360) % 360)}°` : 'generic'}) comes from the
              direction the beach faces. Its rating is capped at Fair until the spot is tuned against observations.
            </div>
          )}
          <div className="sf-detail-notes">
            MOP point {b.mop} at {b.mopDepthM} m, beach faces {Math.round(b.shoreNormal)}°.
            {b.swellWindow ? ` Works best on swell from ${b.swellWindow[0]}° to ${b.swellWindow[1]}°.` : ''}
            {ref && ref.kgM ? ` Model breaker-height check: Hb ${ref.hbM.toFixed(1)} m (Komar–Gaughan ${ref.kgM.toFixed(1)} m), an internal step, not the surf height shown.` : ''}
            {buoy ? ` Nearest buoy (CDIP ${buoy.station}) now, wave height offshore (not surf height): ${buoy.hsFt} ft @ ${Math.round(buoy.tpS)} s from ${sfDir(buoy.dpDeg)}, ${sfLocal(buoy.t, { hour: 'numeric', minute: '2-digit' })}.` : ''}
            {' '}Energy is the swell's power at the model point (Surf-forecast.com scale: about 100 kJ is small, 200–1000 kJ punchy).
          </div>
        </div>
      )}
    </li>
  );
}

function SurfNws({ nws }) {
  if (!nws || !nws.periods || !nws.periods.length) return null;
  const p = nws.periods[0];
  return (
    <section className="sf-nws" aria-label="National Weather Service surf zone forecast">
      <div className="sf-nws-h">NWS Surf Zone Forecast · San Diego County</div>
      {nws.headlines && nws.headlines.length > 0 && (
        <ul className="sf-nws-heads">{nws.headlines.map(h => <li key={h}>{h}</li>)}</ul>
      )}
      <div className="sf-nws-row">
        <span><b>{p.name}</b></span>
        {p.ripRisk && <span>Rip current risk: <b className={/high/i.test(p.ripRisk) ? 'sf-hi' : ''}>{p.ripRisk}</b></span>}
        {p.surf && <span>Surf: {p.surf}</span>}
        {p.water && <span>Water {p.water}</span>}
      </div>
      <div className="sf-nws-src">Issued {nws.issued ? sfLocal(nws.issued, { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : ''} by the National Weather Service. Shown as issued.</div>
    </section>
  );
}

function SurfLegend() {
  return (
    <div className="sf-legend" aria-label="Rating colours">
      {['FLAT', 'POOR', 'POOR–FAIR', 'FAIR', 'FAIR–GOOD'].map(l => (
        <span key={l}><i className={`sf-c-${sfRateKey(l)}`}/>{sfTitle(l)}</span>
      ))}
      <span className="sf-legend-note">Bars: surf (face) height per 3 h · faded = dark</span>
    </div>
  );
}


// ════════════════════════════════════════════════════════════════════════
// Surftracker: the discreet surf mode of the site (/sd/surf/*). Its own
// header, nav (Report · Forecast · Map · Cams) and footer, with a way back to
// Tunatracker. Reached only from a quiet link on Charts and in the footer.
// ════════════════════════════════════════════════════════════════════════

function sfPath(params) {
  const fn = window.ttPathFromRoute;
  return fn ? fn('surf', params || {}) : '/sd/surf';
}
// <a> props for in-app links: real hrefs (open in new tab, crawlable), SPA nav on click.
function sfLinkProps(navigate, params) {
  return {
    href: sfPath(params),
    onClick: e => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
      e.preventDefault();
      navigate('surf', params);
    },
  };
}

function SurfWave({ size }) {
  const z = size || 22;
  return (
    <svg width={z} height={z} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M2 15c2.2 0 3.3-1.6 4.5-3.4C8 9.3 9.6 6.5 13.4 6.5c3.1 0 5 2 5 4.3 0 1.8-1.3 3-2.9 3-1.2 0-2.1-.8-2.1-1.9"
            fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <path d="M2 19.5c1.7 0 2.6-.9 3.8-.9s2.1.9 3.8.9 2.6-.9 3.8-.9 2.1.9 3.8.9 2.6-.9 3.8-.9"
            fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
    </svg>
  );
}

function SurftrackerHeader({ sub, navigate }) {
  const tabs = [['report', 'Report'], ['forecast', 'Forecast'], ['map', 'Map'], ['cams', 'Cams']];
  const active = sub === 'break' ? 'forecast' : sub;
  return (
    <header className="st-header">
      <div className="st-head-inner">
        <a className="st-brand" {...sfLinkProps(navigate, { sub: 'report' })} aria-label="Surftracker home">
          <span className="st-brand-mark"><SurfWave size={22}/></span>
          <span className="st-brand-text">Surftracker<small>San Diego</small></span>
        </a>
        <nav className="st-nav" aria-label="Surftracker">
          {tabs.map(([id, label]) => (
            <a key={id} className={`st-tab${active === id ? ' on' : ''}`} aria-current={active === id ? 'page' : undefined}
               {...sfLinkProps(navigate, { sub: id })}>{label}</a>
          ))}
        </nav>
        <a className="st-back" href="/sd/today"
           onClick={e => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); navigate('today'); }}>
          <span aria-hidden="true">←</span> Tunatracker
        </a>
      </div>
    </header>
  );
}

function SurftrackerFooter({ navigate }) {
  return (
    <footer className="st-footer">
      <div className="st-foot-inner">
        <span><b>Surftracker</b> is the surf side of Tunatracker: free, no ads, and it shows how accurate it is.</span>
        <span className="st-foot-links">
          <a href="/sd/today" onClick={e => { e.preventDefault(); navigate('today'); }}>← Back to Tunatracker</a>
          <span aria-hidden="true">·</span>
          <a href="/privacy/">Privacy</a>
        </span>
      </div>
    </footer>
  );
}
window.SurftrackerHeader = SurftrackerHeader;
window.SurftrackerFooter = SurftrackerFooter;

// ── favourites ("My spots"), per viewer, in this browser only ───────────
const SF_FAV_KEY = 'tt_surf_favs';
function useSurfFavs() {
  const [favs, setFavs] = useSfState(() => {
    try { const v = JSON.parse(localStorage.getItem(SF_FAV_KEY) || '[]'); return Array.isArray(v) ? v : []; }
    catch (e) { return []; }
  });
  const toggle = id => setFavs(f => {
    const next = f.indexOf(id) >= 0 ? f.filter(x => x !== id) : f.concat([id]);
    try { localStorage.setItem(SF_FAV_KEY, JSON.stringify(next)); } catch (e) {}
    return next;
  });
  return [favs, toggle];
}
function SurfStar({ on, onClick, name, compact }) {
  return (
    <button type="button" className={`sf-star${on ? ' on' : ''}${compact ? ' compact' : ''}`} aria-pressed={!!on}
            aria-label={on ? `Remove ${name} from my spots` : `Add ${name} to my spots`}
            onClick={e => { e.stopPropagation(); e.preventDefault(); onClick(); }}>
      <span aria-hidden="true">{on ? '★' : '☆'}</span>{compact ? null : (on ? ' My spot' : ' Add to my spots')}
    </button>
  );
}

// ── shared data: main breaks + county spots, day list ─────────────────
function useSurfAll() {
  const { data, error } = useSurfData();
  const extra = useSurfSpots();
  const all = useSfMemo(() => {
    if (!data) return [];
    const have = {};
    const list = data.breaks.map(b => { have[b.id] = 1; return Object.assign({}, b, { area: sfArea(b.lat), key: true }); });
    ((extra && extra.spots) || []).forEach(b => { if (!have[b.id]) list.push(Object.assign({}, b, { area: b.area || sfArea(b.lat) })); });
    return list.sort((a, b) => b.lat - a.lat);
  }, [data, extra]);
  const days = useSfMemo(() => {
    if (!data || !data.breaks[0]) return [];
    const now = Date.now() - 3 * 3600000;
    const keys = [];
    data.breaks[0].hours.forEach(h => {
      if (Date.parse(h.t) < now) return;
      const k = sfDayKey(h.t);
      if (keys.indexOf(k) < 0) keys.push(k);
    });
    return keys.map(k => {
      const h = data.breaks[0].hours.find(x => sfDayKey(x.t) === k);
      return { key: k, label: sfLocal(h.t, { weekday: 'short', month: 'short', day: 'numeric' }),
               dn: sfLocal(h.t, { day: 'numeric' }), wd: sfLocal(h.t, { weekday: 'short' }) };
    });
  }, [data]);
  return { data, error, extra, all, days };
}

function sfWetsuit(f) {
  if (f == null) return null;
  if (f >= 72) return 'Boardshorts or a spring suit';
  if (f >= 66) return 'Spring suit or 2 mm';
  if (f >= 61) return '3/2 full suit';
  if (f >= 56) return '4/3 full suit';
  return '5/4 with booties';
}

// The step nearest to now (within ~1.5 h) and the one after it.
function sfNowNext(hours) {
  const t = Date.now();
  let i = -1, best = 1e15;
  hours.forEach((h, k) => { const d = Math.abs(Date.parse(h.t) - t); if (d < best) { best = d; i = k; } });
  if (i < 0 || best > 1.6 * 3600000) return [null, null];
  return [hours[i], hours[i + 1] || null];
}

function sfIsDarkNow(sun) {
  return !sfIsDay(new Date().toISOString(), sun);
}

function SurfAreaChips({ value, onChange, counts, withKey, total }) {
  const opts = (withKey ? [['key', 'Main breaks']] : []).concat(SF_AREAS.map(a => [a[1], a[1]]), [['all', 'All']]);
  return (
    <div className="sf-areas" role="tablist" aria-label="Area">
      {opts.map(([id, lbl]) => (
        <button key={id} type="button" role="tab" aria-selected={value === id} className={`sf-area${value === id ? ' on' : ''}`}
                onClick={() => onChange(id)}>
          {lbl}{counts ? <span className="sf-area-n"> {id === 'all' ? total : id === 'key' ? counts.key : (counts[id] || 0)}</span> : null}
        </button>
      ))}
    </div>
  );
}
function sfInArea(b, area) { return area === 'all' || (area === 'key' ? b.key : b.area === area); }
function sfCounts(all) {
  const c = { key: 0 };
  all.forEach(b => { c[b.area] = (c[b.area] || 0) + 1; if (b.key) c.key += 1; });
  return c;
}

function SurfTopBar({ title, data, children }) {
  const ageH = (Date.now() - Date.parse(data.generatedAt)) / 3600000;
  const stale = ageH > (data.staleAfterHours || SF_STALE_H);
  return (
    <React.Fragment>
      <div className="sf-top">
        <h1 className="sf-title">{title}</h1>
        <span className="sf-chip">Model forecast</span>
        <span className="sf-muted">Updated {sfLocal(data.generatedAt, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</span>
        {children}
      </div>
      {stale && <p className="sf-stale">This forecast is {Math.round(ageH)} hours old. It may be out of date.</p>}
    </React.Fragment>
  );
}

function SurfDays({ days, day, setDay }) {
  return (
    <div className="sf-days" role="tablist" aria-label="Day">
      {days.map(d => (
        <button key={d.key} role="tab" aria-selected={day === d.key}
                className={`sf-day${day === d.key ? ' on' : ''}`} onClick={() => setDay(d.key)}>{d.label}</button>
      ))}
    </div>
  );
}

// ── Report: where to surf now, my spots, conditions ─────────────────────
function SurfReport({ ctx, navigate, favs, toggleFav }) {
  const { data, all, days, extra } = ctx;
  const [area, setArea] = useSfState('all');
  const [more, setMore] = useSfState(false);
  const today = days[0] ? days[0].key : null;
  const dark = sfIsDarkNow(data.sun);
  // After dark, rank by tomorrow's best daylight window instead of "now".
  const tomorrow = days[1] ? days[1].key : null;
  const rows = all.filter(b => sfInArea(b, area)).map(b => {
    const [now, next] = sfNowNext(b.hours);
    const bwToday = today ? sfBestWindow(b.hours, today, data.sun) : null;
    const bwTom = tomorrow ? sfBestWindow(b.hours, tomorrow, data.sun) : null;
    const rankBy = dark ? (bwTom ? bwTom.h.score : -1)
      : Math.max(now ? now.score : -1, next ? next.score - 0.05 : -1);
    return { b, now, next, bw: dark ? bwTom : bwToday, rankBy };
  }).sort((x, y) => y.rankBy - x.rankBy || y.b.lat - x.b.lat);
  const shown = more ? rows : rows.slice(0, 12);
  const mine = favs.map(id => all.find(b => b.id === id)).filter(Boolean);
  const counts = sfCounts(all);
  return (
    <div className="sf-wrap">
      <SurfTopBar title="Surf report" data={data}/>
      <SurfNws nws={data.nws}/>
      {window.SurfNwsNotes && <window.SurfNwsNotes notes={data.nwsNotes}/>}

      {mine.length > 0 && (
        <section className="st-sec" aria-label="My spots">
          <h2 className="st-h2">My spots</h2>
          <div className="st-cards">
            {mine.map(b => {
              const [now] = sfNowNext(b.hours);
              const bw = today ? sfBestWindow(b.hours, today, data.sun) : null;
              const h = now || (bw && bw.h);
              return (
                <a key={b.id} className={`st-card st-card-${h ? sfRateKey(h.label) : 'none'}`} {...sfLinkProps(navigate, { sub: 'break', spot: b.id })}>
                  <span className="st-card-name">{b.name}</span>
                  <span className="st-card-h" title="Surf height: breaking wave face at the beach">{h ? `${h.faceFt[0]}–${h.faceFt[1]}` : '—'}<small> ft</small>{sfSets(h) != null && <small className="st-sets">sets to {sfSets(h)} ft</small>}</span>
                  <span className={h ? sfRatingClass(h.label) : 'sf-rate'}>{h ? sfTitle(h.label) : '—'}</span>
                  {bw && bw.h.score >= 0.5 && <span className="st-card-bw">Best {sfFracClock(bw.from)}–{sfFracClock(bw.to)}</span>}
                </a>
              );
            })}
          </div>
        </section>
      )}

      <section className="st-sec" aria-labelledby="st-now-h">
        <div className="st-sec-head">
          <h2 className="st-h2" id="st-now-h">{dark ? 'Best bets for tomorrow' : 'Where to surf now'}</h2>
          <span className="sf-muted">{dark
            ? `Ranked by each spot's best daylight window ${days[1] ? days[1].wd : 'tomorrow'}.`
            : 'Ranked by the model rating now and over the next 3 hours.'}</span>
        </div>
        {extra && <SurfAreaChips value={area} onChange={id => { setArea(id); setMore(false); }} counts={counts} total={all.length}/>}
        <ol className="st-rank">
          {shown.map(({ b, now, next, bw }, i) => {
            const h = dark ? (bw && bw.h) : now;
            return (
              <li key={b.id} className="st-rank-row">
                <a className="st-rank-link" {...sfLinkProps(navigate, { sub: 'break', spot: b.id })}>
                  <span className="st-rank-n">{i + 1}</span>
                  <span className="st-rank-name">{b.name}
                    <i>{b.area}{b.defaults ? <em className="sf-def"> · default settings</em> : null}</i>
                  </span>
                  <span className="st-rank-h" title="Surf height: breaking wave face at the beach">{h ? `${h.faceFt[0]}–${h.faceFt[1]}` : '—'}<small> ft</small>{sfSets(h) != null && <small className="st-sets">sets to {sfSets(h)} ft</small>}</span>
                  <span className="st-rank-r">
                    {h ? <span className={sfRatingClass(h.label)}>{sfTitle(h.label)}</span> : '—'}
                    {!dark && next && h && sfRateKey(next.label) !== sfRateKey(h.label)
                      ? <small className="st-rank-next">→ {sfTitle(next.label)}</small> : null}
                  </span>
                  <span className="st-rank-w">{h && h.windKt != null ? `${h.windKt} kt ${h.windType}` : ''}
                    {!dark && bw && bw.h.score >= 0.5 ? <small>Best {sfFracClock(bw.from)}–{sfFracClock(bw.to)}</small> : null}
                    {dark && bw ? <small>{sfFracClock(bw.from)}–{sfFracClock(bw.to)}</small> : null}
                  </span>
                </a>
                <SurfStar on={favs.indexOf(b.id) >= 0} onClick={() => toggleFav(b.id)} name={b.name} compact/>
              </li>
            );
          })}
        </ol>
        {rows.length > 12 && (
          <button type="button" className="st-more" onClick={() => setMore(!more)}>
            {more ? 'Show top 12' : `Show all ${rows.length} spots`}
          </button>
        )}
      </section>

      {today && (
        <section className="st-sec" aria-label="Today's conditions">
          <h2 className="st-h2">Today</h2>
          <SurfConditions data={data} dayKey={today}/>
        </section>
      )}
      <SurfAbout data={data} extra={extra}/>
    </div>
  );
}

// ── Forecast: day tabs + every break with its 7-day strip ───────────────
function SurfForecastPage({ ctx, navigate, favs, toggleFav }) {
  const { data, all, days, extra } = ctx;
  const [day, setDay] = useSfState(null);
  const [open, setOpen] = useSfState(null);
  const [area, setArea] = useSfState('key');
  useSfEffect(() => { if (!day && days.length) setDay(days[0].key); }, [days]);
  const best = useSfMemo(() => {
    const out = {};
    if (day) all.forEach(b => { out[b.id] = sfBestWindow(b.hours, day, data.sun); });
    return out;
  }, [all, day]);
  const dayObj = days.find(d => d.key === day);
  const shown = all.filter(b => sfInArea(b, area));
  const pick = id => {
    const b = all.find(x => x.id === id);
    if (b && !sfInArea(b, area)) setArea(b.area);
    setOpen(id);
    setTimeout(() => { const el = document.getElementById('sf-' + id); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 30);
  };
  return (
    <div className="sf-wrap">
      <SurfTopBar title="Surf forecast" data={data}/>
      <SurfDays days={days} day={day} setDay={setDay}/>
      {day && (
        <div className="sf-overview">
          <SurfConditions data={data} dayKey={day}/>
          <SurfMap breaks={all} best={best} open={open} onPick={pick}/>
        </div>
      )}
      {extra && <SurfAreaChips value={area} onChange={id => { setArea(id); setOpen(null); }} counts={sfCounts(all)} withKey total={all.length}/>}
      <SurfLegend/>
      <ul className="sf-list">
        {shown.map(b => (
          <SurfBreakRow key={b.id} b={b} days={days} dayKey={day} dayLabel={dayObj ? dayObj.wd : ''}
                        sun={data.sun} tides={data.tides} buoy={data.buoys && data.buoys[b.buoy]}
                        bw={best[b.id]} open={open === b.id}
                        onToggle={() => setOpen(open === b.id ? null : b.id)} onDay={setDay}
                        fav={favs.indexOf(b.id) >= 0} onFav={toggleFav} navigate={navigate}/>
        ))}
      </ul>
      <SurfAbout data={data} extra={extra}/>
    </div>
  );
}

// ── Map: every spot, coloured by the day's best rating ─────────────────
function SurfMapPage({ ctx, navigate }) {
  const { data, all, days } = ctx;
  const [day, setDay] = useSfState(null);
  useSfEffect(() => { if (!day && days.length) setDay(days[0].key); }, [days]);
  const best = useSfMemo(() => {
    const out = {};
    if (day) all.forEach(b => { out[b.id] = sfBestWindow(b.hours, day, data.sun); });
    return out;
  }, [all, day]);
  return (
    <div className="sf-wrap">
      <SurfTopBar title="Surf map" data={data}/>
      <SurfDays days={days} day={day} setDay={setDay}/>
      <div className="st-bigmap">
        <SurfMap breaks={all} best={best} open={null} onPick={id => navigate('surf', { sub: 'break', spot: id })}/>
      </div>
      <SurfLegend/>
      <div className="st-maplist">
        {SF_AREAS.map(([, a]) => {
          const list = all.filter(b => b.area === a);
          if (!list.length) return null;
          return (
            <section key={a} className="st-maplist-area">
              <h2 className="st-h3">{a}</h2>
              <ul>
                {list.map(b => {
                  const bw = best[b.id];
                  return (
                    <li key={b.id}>
                      <a {...sfLinkProps(navigate, { sub: 'break', spot: b.id })}>
                        <i className={`st-dot sf-c-${bw ? sfRateKey(bw.h.label) : 'flat'}`}/>
                        <span>{b.name}{b.defaults ? <em className="sf-def"> *</em> : null}</span>
                        <b>{bw ? `${bw.h.faceFt[0]}–${bw.h.faceFt[1]} ft` : '—'}</b>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>
      <p className="sf-muted">* Default settings: generic break settings, rating capped at Fair until the spot is tuned.</p>
    </div>
  );
}

// ── Wind timeline for one day: arrow + speed per 3 h, shaded by type ────
function sfWindClass(t) {
  if (t === 'glassy' || t === 'offshore') return 'good';
  if (t === 'light onshore' || t === 'cross') return 'ok';
  if (!t || t === 'unknown') return 'none';
  return 'bad';
}
function SurfWind({ steps, sun }) {
  if (!steps.length) return null;
  return (
    <div className="st-wind" role="table" aria-label="Wind by time of day">
      {steps.map(h => (
        <div key={h.t} role="row" className={`st-wind-c st-w-${sfWindClass(h.windType)}${sfIsDay(h.t, sun) ? '' : ' night'}`}>
          <span className="st-wind-t">{sfClock(h.t)}</span>
          {h.windFrom != null
            ? <span className="st-wind-a" style={{ transform: `rotate(${(h.windFrom + 180) % 360}deg)` }}
                    title={`From ${sfDir(h.windFrom)}`} aria-label={`from ${sfDir(h.windFrom)}`}>↑</span>
            : <span className="st-wind-a" aria-hidden="true">·</span>}
          <span className="st-wind-s">{h.windKt == null ? '—' : h.windKt}<small> kt</small></span>
          <span className="st-wind-k">{h.windType === 'unknown' ? '' : h.windType}</span>
        </div>
      ))}
    </div>
  );
}

// ── Break page ────────────────────────────────────────────────────────
function SurfBreakPage({ ctx, navigate, spot, favs, toggleFav }) {
  const { data, all, days, extra } = ctx;
  const [day, setDay] = useSfState(null);
  useSfEffect(() => { if (!day && days.length) setDay(days[0].key); }, [days]);
  useSfEffect(() => { window.scrollTo(0, 0); }, [spot]);
  const b = all.find(x => x.id === spot);
  if (!b) {
    if (!extra && !ctx.spotsTried) return <div className="sf-wrap"><p className="sf-muted">Loading…</p></div>;
    return (
      <div className="sf-wrap">
        <h1 className="sf-title">Spot not found</h1>
        <p className="sf-muted">We don't have a forecast for “{spot}”. <a {...sfLinkProps(navigate, { sub: 'forecast' })}>See all breaks →</a></p>
      </div>
    );
  }
  const dk = day || (days[0] && days[0].key);
  const dayObj = days.find(d => d.key === dk);
  const am = sfPick(b.hours, dk, 7), pm = sfPick(b.hours, dk, 13);
  const ref = am || pm;
  const steps = b.hours.filter(h => sfDayKey(h.t) === dk);
  const bw = dk ? sfBestWindow(b.hours, dk, data.sun) : null;
  const buoy = data.buoys && data.buoys[b.buoy];
  const near = all.filter(x => x.id !== b.id).map(x => ({ x, d: Math.abs(x.lat - b.lat) + Math.abs(x.lon - b.lon) }))
    .sort((p, q) => p.d - q.d).slice(0, 4).map(p => p.x);
  const swellTxt = w => `${Math.round(((w % 360) + 360) % 360)}°`;
  return (
    <div className="sf-wrap st-break">
      <a className="st-crumb" {...sfLinkProps(navigate, { sub: 'forecast' })}>← All breaks</a>
      <div className="sf-top">
        <h1 className="sf-title">{b.name}</h1>
        <span className="sf-chip">Model forecast</span>
        {b.defaults && <span className="sf-chip sf-chip-warn">Default settings</span>}
        <SurfStar on={favs.indexOf(b.id) >= 0} onClick={() => toggleFav(b.id)} name={b.name}/>
      </div>
      <p className="sf-muted st-sub">{b.area} · {b.type === 'reef' ? 'reef' : 'beach'} · faces {sfDir(b.shoreNormal)} ({Math.round(b.shoreNormal)}°)
        · updated {sfLocal(data.generatedAt, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</p>
      {b.note && <div className="sf-note st-note" role="note">{b.note}</div>}
      <SurfBreakCams spot={b.id} navigate={navigate}/>

      <SurfDays days={days} day={dk} setDay={setDay}/>
      <div className="st-break-top">
        <div className="st-slots">
          <SurfSlot h={am} label="Morning" def={b.defaults}/>
          <SurfSlot h={pm} label="Afternoon" def={b.defaults}/>
        </div>
        <SurfBest bw={bw} isToday={days[0] && days[0].key === dk} dayLabel={dayObj ? dayObj.wd : ''}/>
      </div>
      <div className="st-panel">
        <div className="sf-sec-h">7-day outlook</div>
        <SurfStrip b={b} days={days} dayKey={dk} sun={data.sun} onDay={setDay}/>
        <SurfLegend/>
      </div>

      <div className="st-two">
        <div className="st-panel">
          <div className="sf-sec-h">Wind · {dayObj ? dayObj.label : ''}</div>
          <SurfWind steps={steps} sun={data.sun}/>
          <p className="st-fine">Green: glassy or offshore. Amber: cross or light onshore. Red: onshore. Arrows point where the wind blows.</p>
        </div>
        <div className="st-panel">
          <div className="sf-sec-h">Tide · La Jolla{!b.defaults && b.tideWindow ? ` · best ${b.tideWindow[0]} to ${b.tideWindow[1]} ft` : ''}</div>
          <SurfTide tides={data.tides} dayKey={dk} sun={data.sun} win={b.defaults ? null : b.tideWindow} marks={steps.map(h => sfFrac(h.t))}/>
        </div>
      </div>

      <div className="st-panel">
        <div className="sf-sec-h">By time of day</div>
        <div className="sf-steps" role="table" aria-label={`${b.name} by time of day`}>
          <div className="sf-step sf-step-h" role="row">
            <span>Time</span><span>Surf</span><span className="sf-nocase">kJ</span><span>Wind</span><span>Tide</span><span>Rating</span>
          </div>
          {steps.map(h => (
            <div key={h.t} className={`sf-step${sfIsDay(h.t, data.sun) ? '' : ' night'}`} role="row">
              <span>{sfClock(h.t)}</span>
              <span>{h.faceFt[0]}–{h.faceFt[1]} ft{sfSets(h) != null && <small className="sf-sets"> · sets {sfSets(h)}</small>}</span>
              <span>{h.energyKj != null ? h.energyKj : '—'}</span>
              <span>{h.windKt == null ? '—' : `${h.windKt} kt ${sfDir(h.windFrom)}`}</span>
              <span>{h.tideFt == null ? '—' : h.tideFt}</span>
              <span className={sfRatingClass(h.label)}>{h.score.toFixed(1)}</span>
            </div>
          ))}
        </div>
        {ref && (
          <p className="st-fine">
            Swell at the model point (not surf height): {(ref.hsM * SF_FT).toFixed(1)} ft @ {Math.round(ref.tpS)} s from {sfDir(ref.dpDeg)} ({ref.dpDeg}°)
            {ref.energyKj != null ? `, ${ref.energyKj} kJ` : ''}.
            {ref.conf !== 'high' ? ` ${ref.conf[0].toUpperCase() + ref.conf.slice(1)} confidence this far out.` : ''}
            {ref.modelsDisagree ? ' The two wave models disagree for this time.' : ''}
          </p>
        )}
      </div>

      {b.defaults && (
        <div className="sf-def-box">
          <b>Default settings.</b> This spot uses the same wave model as the main breaks, but with generic
          settings: its break type is a guess, any tide is scored the same, and its swell window
          ({b.swellWindow ? `${swellTxt(b.swellWindow[0])} to ${swellTxt(b.swellWindow[1])}` : 'generic'}) comes from the
          direction the beach faces. Its rating is capped at Fair until the spot is tuned against observations.
        </div>
      )}
      <div className="st-panel">
        <div className="sf-sec-h">Details</div>
        <p className="st-fine">
          Forecast at CDIP MOP point {b.mop} ({b.mopDepthM} m deep), then a breaking model to the beach.
          {ref && ref.kgM ? ` Model breaker-height check: Hb ${ref.hbM.toFixed(1)} m (Komar–Gaughan ${ref.kgM.toFixed(1)} m), an internal step, not the surf height shown.` : ''}
          {buoy ? ` Nearest buoy (CDIP ${buoy.station}) now, wave height offshore (not surf height): ${buoy.hsFt} ft @ ${Math.round(buoy.tpS)} s from ${sfDir(buoy.dpDeg)}, ${sfLocal(buoy.t, { hour: 'numeric', minute: '2-digit' })}.` : ''}
          {' '}Energy is the swell's power at the model point (about 100 kJ is small, 200–1000 kJ punchy).
        </p>
      </div>
      {near.length > 0 && (
        <div className="st-near">
          <span className="sf-sec-h">Nearby</span>
          {near.map(x => <a key={x.id} {...sfLinkProps(navigate, { sub: 'break', spot: x.id })}>{x.name}</a>)}
        </div>
      )}
      <SurfAbout data={data} extra={extra} compact/>
    </div>
  );
}

function SurfAbout({ data, extra, compact }) {
  const v = data.verification || {};
  return (
    <section className="sf-about">
      <h2>How this forecast works</h2>
      {!compact && <p>{data.method}</p>}
      <div className="sf-checked">
        {v.observed && <p><b>Surf height vs observed breaking surf:</b> {v.observed}</p>}
        {window.SurfScorecard && <window.SurfScorecard card={v.scorecard}/>}
        <p>
          <b>Secondary check, swell model:</b> {v.what}. Over {v.testPeriod}, its wave-height error was{' '}
          {v.hsRmseM ? `${(v.hsRmseM.blend * SF_FT).toFixed(1)} ft (RMS)` : '—'}, better than{' '}
          {(v.beats || []).join(' and ')}. This is wave height at the buoys, not surf height. {v.leadNote}
        </p>
        {v.wind && <p><b>Wind:</b> {v.wind}</p>}
        <p><b>Not yet checked:</b> {v.notVerified} {v.scale} Ratings top out at Fair–Good: a model alone can't call a day Good or Epic.</p>
      </div>
      <p className="sf-muted">Surf height is the breaking face height at the beach; occasional sets run larger. Swell and buoy figures are wave heights offshore, shown for context. Best window is the highest-rated daylight 3-hour model step. Sun times are for La Jolla; water temperature is the latest CDIP buoy reading.{extra ? ' Spots marked "default settings" use the same model with generic break settings that are not yet tuned for that spot, and they update about twice a day.' : ''} Always check the NWS rip current risk and conditions on the beach.</p>
      <p className="sf-credits">{(data.credits || []).concat(data.waterTemp ? [`Water temperature: CDIP buoy ${data.waterTemp.station}`] : [], ['Map tiles: Esri, © OpenStreetMap contributors'], extra && extra.sources ? [extra.sources] : []).join(' · ')}</p>
    </section>
  );
}

// ── Live cams (/sd/surf/cams) ─────────────────────────────────────────────
// Cam list: api/v1/surf_cams.json (hand-edited). Daily status from
// src/surf/cams.py: api/v1/surf_cams_status.json (optional). Only YouTube
// streams whose operators allow embedding. Nothing loads from YouTube except a
// still picture until someone taps a cam; then one youtube-nocookie player.
function useSurfCams() {
  const [st, setSt] = useSfState({ cams: null, status: null, error: false });
  useSfEffect(() => {
    let alive = true;
    const day = new Date().toISOString().slice(0, 13);
    Promise.all([
      fetch('/api/v1/surf_cams.json?h=' + day).then(r => (r.ok ? r.json() : Promise.reject(r.status))),
      fetch('/api/v1/surf_cams_status.json?h=' + day).then(r => (r.ok ? r.json() : null)).catch(() => null),
    ]).then(([list, status]) => {
      if (!alive) return;
      // a status file older than its staleAfterHours says nothing: show the cams
      const fresh = status && status.generatedAt && (Date.now() - Date.parse(status.generatedAt)) / 36e5 < (status.staleAfterHours || 72);
      setSt({ cams: (list && list.cams) || [], status: fresh ? status.cams || {} : {}, error: false });
    }).catch(() => { if (alive) setSt({ cams: [], status: {}, error: true }); });
    return () => { alive = false; };
  }, []);
  return st;
}

function sfCamOffline(status, id) {
  const s = status && status[id];
  return s && s.status === 'offline' ? s : null;
}

function SurfCamCard({ cam, status, playing, onPlay, focus, names, navigate }) {
  const off = sfCamOffline(status, cam.id);
  const ref = useSfRef(null);
  useSfEffect(() => { if (focus && ref.current) ref.current.scrollIntoView({ block: 'center' }); }, [focus]);
  const yt = encodeURIComponent(cam.youtube);
  const watch = `https://www.youtube.com/watch?v=${yt}`;
  const spotLinks = ids => ids.filter(id => names[id]).map((id, i) => (
    <React.Fragment key={id}>{i ? ', ' : ''}<a {...sfLinkProps(navigate, { sub: 'break', spot: id })}>{names[id]}</a></React.Fragment>
  ));
  return (
    <li ref={ref} id={'cam-' + cam.id} className={`st-cam${off ? ' off' : ''}${focus ? ' focus' : ''}`}>
      <div className="st-cam-frame">
        {off ? (
          <div className="st-cam-off" role="status">
            <b>Cam offline</b>
            <span>{off.reason}</span>
            {off.lastSeen && <span>Last seen live {sfLocal(off.lastSeen, { month: 'short', day: 'numeric' })}.</span>}
            <a href={cam.operator.url} target="_blank" rel="noopener noreferrer">Check {cam.operator.name.replace(/ \(.*\)$/, '')} on YouTube ↗</a>
          </div>
        ) : playing ? (
          <iframe src={`https://www.youtube-nocookie.com/embed/${yt}?autoplay=1&mute=1&playsinline=1&rel=0`}
                  title={`${cam.name} live cam`} loading="lazy" referrerPolicy="strict-origin-when-cross-origin"
                  allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowFullScreen/>
        ) : (
          <button type="button" className="st-cam-play" onClick={onPlay} aria-label={`Play ${cam.name} live cam`}>
            <img src={`https://i.ytimg.com/vi/${yt}/hqdefault_live.jpg`} alt="" loading="lazy" decoding="async"
                 onError={e => { if (!/hqdefault\.jpg$/.test(e.currentTarget.src)) e.currentTarget.src = `https://i.ytimg.com/vi/${yt}/hqdefault.jpg`; }}/>
            <span className="st-cam-live">Live</span>
            <span className="st-cam-btn" aria-hidden="true"/>
          </button>
        )}
      </div>
      <div className="st-cam-body">
        <div className="st-cam-name">{cam.name}</div>
        <div className="st-cam-by">
          Cam by <a href={cam.operator.url} target="_blank" rel="noopener noreferrer">{cam.operator.name}</a>
          {!off && <> · <a href={watch} target="_blank" rel="noopener noreferrer">YouTube ↗</a></>}
        </div>
        {cam.covers.length > 0 && <div className="st-cam-spots"><span>In view:</span> {spotLinks(cam.covers)}</div>}
        {cam.near.length > 0 && <div className="st-cam-spots"><span>{cam.kind === 'harbour' ? 'Nearest breaks (not in view):' : 'Nearby:'}</span> {spotLinks(cam.near)}</div>}
        {cam.note && <p className="st-cam-note">{cam.note}</p>}
      </div>
    </li>
  );
}

function SurfCamsPage({ ctx, navigate, camId }) {
  const { cams, status, error } = useSurfCams();
  const [playing, setPlaying] = useSfState(null);
  useSfEffect(() => { if (!camId) window.scrollTo(0, 0); }, []);
  const names = {};
  (ctx.all || []).forEach(b => { names[b.id] = b.name; });
  if (!cams) return <div className="sf-wrap"><h1 className="sf-title">Live cams</h1><p className="sf-muted">Loading cams…</p></div>;
  if (error || !cams.length) return <div className="sf-wrap"><h1 className="sf-title">Live cams</h1><p className="sf-muted">The cam list is unavailable right now.</p></div>;
  const surf = cams.filter(c => c.kind === 'surf');
  const harbour = cams.filter(c => c.kind !== 'surf');
  const areas = SF_AREAS.map(a => a[1]).filter(a => surf.some(c => c.area === a));
  surf.forEach(c => { if (areas.indexOf(c.area) < 0) areas.push(c.area); });
  const card = c => (
    <SurfCamCard key={c.id} cam={c} status={status} names={names} navigate={navigate} focus={camId === c.id}
                 playing={playing === c.id} onPlay={() => setPlaying(c.id)}/>
  );
  const nOff = cams.filter(c => sfCamOffline(status, c.id)).length;
  return (
    <div className="sf-wrap st-cams">
      <div className="sf-top">
        <h1 className="sf-title">Live cams</h1>
        <span className="sf-chip">{cams.length - nOff} of {cams.length} online</span>
      </div>
      <p className="sf-muted st-sub">Live streams run by local businesses and clubs, shown through YouTube's own player. Tap a picture to play; only one plays at a time.</p>

      <section className="st-sec" aria-labelledby="st-cams-surf">
        <h2 className="st-h2" id="st-cams-surf">Surf cams</h2>
        {areas.map(a => (
          <div key={a} className="st-cam-area">
            <h3 className="st-h3">{a}</h3>
            <ul className="st-cam-grid">{surf.filter(c => c.area === a).map(card)}</ul>
          </div>
        ))}
      </section>

      {harbour.length > 0 && (
        <section className="st-sec" aria-labelledby="st-cams-bay">
          <div className="st-sec-head">
            <h2 className="st-h2" id="st-cams-bay">Harbour and bay cams</h2>
            <span className="sf-chip">No surf in view</span>
          </div>
          <ul className="st-cam-grid">{harbour.map(card)}</ul>
        </section>
      )}

      <p className="st-fine">
        Each cam belongs to its operator; follow the links to support them. We check every cam once a day and mark it
        offline if its video has been removed or no longer allows embedding. If a stream has just ended, the player may
        show a recording until the operator restarts it. No Surftracker coverage yet for
        Imperial Beach, Coronado, Sunset Cliffs, Blacks, Torrey Pines or Del Mar.
      </p>
    </div>
  );
}

// Break page: "Live cam" links for any cam whose view covers this break.
function SurfBreakCams({ spot, navigate }) {
  const { cams, status } = useSurfCams();
  const mine = (cams || []).filter(c => c.covers.indexOf(spot) >= 0);
  if (!mine.length) return null;
  return (
    <div className="st-break-cams">
      {mine.map(c => {
        const off = sfCamOffline(status, c.id);
        return (
          <a key={c.id} className={`st-cam-link${off ? ' off' : ''}`} {...sfLinkProps(navigate, { sub: 'cams', spot: c.id })}>
            <span className="st-cam-dot" aria-hidden="true"/>{off ? 'Cam offline' : 'Live cam'}: {c.name} →
          </a>
        );
      })}
    </div>
  );
}

function SurfView({ navigate, sub, spot }) {
  const ctx = useSurfAll();
  const [favs, toggleFav] = useSurfFavs();
  const [spotsTried, setSpotsTried] = useSfState(false);
  useSfEffect(() => { const t = setTimeout(() => setSpotsTried(true), 4000); return () => clearTimeout(t); }, []);
  const { data, error } = ctx;
  if (error) return <div className="sf-wrap"><h1 className="sf-title">Surftracker</h1><p className="sf-muted">The surf forecast is unavailable right now.</p></div>;
  if (!data) return <div className="sf-wrap"><h1 className="sf-title">Surftracker</h1><p className="sf-muted">Loading surf forecast…</p></div>;
  const props = { ctx: Object.assign({}, ctx, { spotsTried }), navigate, favs, toggleFav };
  const page = sub === 'forecast' ? <SurfForecastPage {...props}/>
    : sub === 'map' ? <SurfMapPage {...props}/>
    : sub === 'cams' ? <SurfCamsPage {...props} camId={spot}/>
    : sub === 'break' && spot ? <SurfBreakPage {...props} spot={spot}/>
    : <SurfReport {...props}/>;
  // NWS surf alerts banner (surf-nws.jsx) above every Surftracker tab.
  return <>{window.SurfNwsAlerts && <window.SurfNwsAlerts alerts={data.nwsAlerts}/>}{page}</>;
}

window.SurfView = SurfView;
