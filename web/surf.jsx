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
          <i>{wt ? `buoy ${wt.station}` : nwsWater ? 'NWS' : ''}</i>
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
      layer.current = L.layerGroup().addTo(m);
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
        html: `<span class="sf-pin sf-pin-${key}${open === b.id ? ' on' : ''}"></span>`,
        iconSize: [16, 16], iconAnchor: [8, 8],
      });
      L.marker([b.lat, b.lon], { icon, title: b.name, keyboard: true, zIndexOffset: open === b.id ? 1000 : 0 })
        .bindTooltip(`<b>${b.name}</b> ${txt} ft${bw ? ' · ' + sfTitle(bw.h.label) : ''}`,
                     { direction: 'left', offset: [-8, 0], className: 'sf-tip' })
        .on('click', () => onPick(b.id))
        .addTo(layer.current);
    });
  }
  useSfEffect(() => { draw(); }, [best, open]);
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
                  aria-label={`${d.label}: up to ${Math.max(0, ...steps.map(h => h.faceFt[1]))} ft`}>
            <span className="sf-sday-lbl">{d.wd}<span className="sf-sday-n"> {d.dn}</span></span>
            <span className="sf-bars">
              {steps.map(h => {
                const night = !sfIsDay(h.t, sun);
                const mid = (h.faceFt[0] + h.faceFt[1]) / 2;
                const pMid = Math.min(100, mid / scaleFt * 100);
                const pHi = Math.min(100, h.faceFt[1] / scaleFt * 100);
                const key = sfRateKey(h.label);
                return (
                  <span key={h.t} className={`sf-bar${night ? ' night' : ''}`}
                        title={`${sfLocal(h.t, { weekday: 'short', hour: 'numeric' })} · ${h.faceFt[0]}–${h.faceFt[1]} ft · ${sfTitle(h.label)}${h.windKt != null ? ` · wind ${h.windKt} kt ${h.windType}` : ''}`}>
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

function SurfSlot({ h, label }) {
  if (!h) return <div className="sf-slot sf-slot-empty"><span className="sf-slot-lbl">{label}</span>—</div>;
  const [lo, hi] = h.faceFt;
  return (
    <div className="sf-slot">
      <span className="sf-slot-lbl">{label}</span>
      <span className="sf-face">{lo === hi ? lo : `${lo}–${hi}`}<small> ft</small>
        {h.energyKj != null && <em className="sf-kj" title="Wave energy at the model point, kJ (Surf-forecast.com scale: about 100 small, 200–1000 punchy)">{h.energyKj} kJ</em>}
      </span>
      <span className="sf-band">{sfBand(lo, hi)}</span>
      <span className={sfRatingClass(h.label)}>{sfTitle(h.label)}{h.faded ? ' · wind' : ''}</span>
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
        {h.faceFt[0]}–{h.faceFt[1]} ft · <b>{sfTitle(h.label)}</b>
        {h.windKt != null ? ` · ${h.windKt} kt ${h.windType}` : ''}
        {h.tideFt != null ? ` · tide ${h.tideFt} ft` : ''}
      </span>
    </div>
  );
}

function SurfBreakRow({ b, days, dayKey, dayLabel, sun, tides, buoy, bw, open, onToggle, onDay }) {
  const am = sfPick(b.hours, dayKey, 7);
  const pm = sfPick(b.hours, dayKey, 13);
  const ref = am || pm;
  const steps = b.hours.filter(h => sfDayKey(h.t) === dayKey);
  const isToday = days[0] && days[0].key === dayKey;
  return (
    <li className={`sf-break${open ? ' open' : ''}`} id={`sf-${b.id}`}>
      <button className="sf-break-head" onClick={onToggle} aria-expanded={open}>
        <span className="sf-break-name">{b.name}<i>{b.type === 'reef' ? 'reef' : 'beach'} · faces {sfDir(b.shoreNormal)}</i></span>
        <SurfSlot h={am} label="Morning"/>
        <SurfSlot h={pm} label="Afternoon"/>
        <span className="sf-chev" aria-hidden="true">{open ? '–' : '+'}</span>
      </button>
      <div className="sf-break-glance">
        <SurfBest bw={bw} isToday={isToday} dayLabel={dayLabel}/>
        <SurfStrip b={b} days={days} dayKey={dayKey} sun={sun} onDay={onDay}/>
      </div>
      {ref && (
        <div className="sf-break-sub">
          Swell {(ref.hsM * SF_FT).toFixed(1)} ft @ {Math.round(ref.tpS)} s {sfDir(ref.dpDeg)} ({ref.dpDeg}°)
          {am && am.windKt != null ? ` · AM wind ${am.windKt} kt ${am.windType}` : ''}
          {pm && pm.windKt != null ? ` · PM ${pm.windKt} kt ${pm.windType}` : ''}
          {ref.conf !== 'high' ? ` · ${ref.conf} confidence` : ''}
          {ref.modelsDisagree ? ' · models disagree' : ''}
        </div>
      )}
      {open && (
        <div className="sf-detail">
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
                <span>{h.faceFt[0]}–{h.faceFt[1]} ft</span>
                <span>{h.energyKj != null ? h.energyKj : '—'}</span>
                <span>{h.windKt == null ? '—' : `${h.windKt} kt ${sfDir(h.windFrom)}`}</span>
                <span>{h.tideFt == null ? '—' : h.tideFt}</span>
                <span className={sfRatingClass(h.label)}>{h.score.toFixed(1)}</span>
              </div>
            ))}
          </div>
          <div className="sf-detail-notes">
            MOP point {b.mop} at {b.mopDepthM} m, beach faces {Math.round(b.shoreNormal)}°.
            {b.swellWindow ? ` Works best on swell from ${b.swellWindow[0]}° to ${b.swellWindow[1]}°.` : ''}
            {ref && ref.kgM ? ` Breaking height ${ref.hbM.toFixed(1)} m (Komar–Gaughan check ${ref.kgM.toFixed(1)} m).` : ''}
            {buoy ? ` Nearest buoy (CDIP ${buoy.station}) now: ${buoy.hsFt} ft @ ${Math.round(buoy.tpS)} s from ${sfDir(buoy.dpDeg)}, ${sfLocal(buoy.t, { hour: 'numeric', minute: '2-digit' })}.` : ''}
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
      <span className="sf-legend-note">Bars: face height per 3 h · faded = dark</span>
    </div>
  );
}

function SurfView({ navigate }) {
  const { data, error } = useSurfData();
  const [day, setDay] = useSfState(null);
  const [open, setOpen] = useSfState(null);

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
      return {
        key: k,
        label: sfLocal(h.t, { weekday: 'short', month: 'short', day: 'numeric' }),
        dn: sfLocal(h.t, { day: 'numeric' }),
        wd: sfLocal(h.t, { weekday: 'short' }),
      };
    });
  }, [data]);

  useSfEffect(() => { if (!day && days.length) setDay(days[0].key); }, [days]);

  const best = useSfMemo(() => {
    const out = {};
    if (data && day) data.breaks.forEach(b => { out[b.id] = sfBestWindow(b.hours, day, data.sun); });
    return out;
  }, [data, day]);

  if (error) return <div className="sf-wrap"><h1 className="sf-title">San Diego surf</h1><p className="sf-muted">The surf forecast is unavailable right now.</p></div>;
  if (!data) return <div className="sf-wrap"><h1 className="sf-title">San Diego surf</h1><p className="sf-muted">Loading surf forecast…</p></div>;

  const ageH = (Date.now() - Date.parse(data.generatedAt)) / 3600000;
  const stale = ageH > (data.staleAfterHours || SF_STALE_H);
  const v = data.verification || {};
  const dayObj = days.find(d => d.key === day);
  const pick = id => {
    setOpen(id);
    setTimeout(() => {
      const el = document.getElementById('sf-' + id);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 30);
  };

  return (
    <div className="sf-wrap">
      <div className="sf-top">
        <h1 className="sf-title">San Diego surf</h1>
        <span className="sf-chip">Model forecast</span>
        <span className="sf-muted">Updated {sfLocal(data.generatedAt, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</span>
      </div>
      {stale && <p className="sf-stale">This forecast is {Math.round(ageH)} hours old. It may be out of date.</p>}

      <SurfNws nws={data.nws}/>

      <div className="sf-days" role="tablist" aria-label="Day">
        {days.map(d => (
          <button key={d.key} role="tab" aria-selected={day === d.key}
                  className={`sf-day${day === d.key ? ' on' : ''}`} onClick={() => setDay(d.key)}>{d.label}</button>
        ))}
      </div>

      {day && (
        <div className="sf-overview">
          <SurfConditions data={data} dayKey={day}/>
          <SurfMap breaks={data.breaks} best={best} open={open} onPick={pick}/>
        </div>
      )}

      <SurfLegend/>
      <ul className="sf-list">
        {data.breaks.map(b => (
          <SurfBreakRow key={b.id} b={b} days={days} dayKey={day} dayLabel={dayObj ? dayObj.wd : ''}
                        sun={data.sun} tides={data.tides} buoy={data.buoys && data.buoys[b.buoy]}
                        bw={best[b.id]} open={open === b.id}
                        onToggle={() => setOpen(open === b.id ? null : b.id)} onDay={setDay}/>
        ))}
      </ul>

      <section className="sf-about">
        <h2>How this forecast works</h2>
        <p>{data.method}</p>
        <div className="sf-checked">
          <p>
            <b>What we've checked:</b> {v.what}. Over {v.testPeriod}, the blended model's error was{' '}
            {v.hsRmseM ? `${(v.hsRmseM.blend * SF_FT).toFixed(1)} ft (RMS)` : '—'}, better than{' '}
            {(v.beats || []).join(' and ')}. {v.leadNote}
          </p>
          {v.observed && <p><b>Against observed surf:</b> {v.observed}</p>}
          {v.wind && <p><b>Wind:</b> {v.wind}</p>}
          <p><b>Not yet checked:</b> {v.notVerified} {v.scale} Ratings top out at Fair–Good: a model alone can't call a day Good or Epic.</p>
        </div>
        <p className="sf-muted">Surf height is the face height of the bigger waves; occasional sets run larger. Best window is the highest-rated daylight 3-hour model step. Sun times are for La Jolla; water temperature is the latest CDIP buoy reading. Always check the NWS rip current risk and conditions on the beach.</p>
        <p className="sf-credits">{(data.credits || []).concat(data.waterTemp ? [`Water temperature: CDIP buoy ${data.waterTemp.station}`] : [], ['Map tiles: Esri, © OpenStreetMap contributors']).join(' · ')}</p>
      </section>
    </div>
  );
}

window.SurfView = SurfView;
