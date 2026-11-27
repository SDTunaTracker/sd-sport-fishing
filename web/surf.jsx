// San Diego surf forecast page (/sd/surf). Reads api/v1/surf.json, written by
// src/surf/forecast.py: CDIP MOP per break, our breaking step, Open-Meteo
// wind, NOAA tides, a 0–5 rating, and the NWS Surf Zone Forecast verbatim.
//
// Labelled "Model forecast" everywhere. Face heights and ratings are model
// estimates (no surf observations yet); the only accuracy numbers shown are
// the held-out buoy scores in surf.json's `verification` block.
const { useState: useSfState, useEffect: useSfEffect, useMemo: useSfMemo } = React;

const SF_TZ = 'America/Los_Angeles';
const SF_STALE_H = 12;

function sfLocal(iso, opts) {
  return new Date(iso).toLocaleString('en-US', Object.assign({ timeZone: SF_TZ }, opts));
}
function sfDayKey(iso) { return sfLocal(iso, { year: 'numeric', month: '2-digit', day: '2-digit' }); }
function sfHour(iso) { return Number(sfLocal(iso, { hour: 'numeric', hour12: false })) % 24; }

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

function sfRatingClass(label) {
  return 'sf-rate sf-rate-' + String(label || 'flat').toLowerCase().replace(/[^a-z]+/g, '-');
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

function SurfSlot({ h, label }) {
  if (!h) return <div className="sf-slot sf-slot-empty"><span className="sf-slot-lbl">{label}</span>—</div>;
  const [lo, hi] = h.faceFt;
  return (
    <div className="sf-slot">
      <span className="sf-slot-lbl">{label}</span>
      <span className="sf-face">{lo === hi ? lo : `${lo}–${hi}`}<small> ft</small></span>
      <span className="sf-band">{sfBand(lo, hi)}</span>
      <span className={sfRatingClass(h.label)}>{h.label}{h.faded ? ' · wind' : ''}</span>
    </div>
  );
}

function SurfBreakRow({ b, dayKey, buoy, open, onToggle }) {
  const am = sfPick(b.hours, dayKey, 7);
  const pm = sfPick(b.hours, dayKey, 13);
  const ref = am || pm;
  const steps = b.hours.filter(h => sfDayKey(h.t) === dayKey);
  return (
    <li className={`sf-break${open ? ' open' : ''}`}>
      <button className="sf-break-head" onClick={onToggle} aria-expanded={open}>
        <span className="sf-break-name">{b.name}<i>{b.type === 'reef' ? 'reef' : 'beach'} · faces {sfDir(b.shoreNormal)}</i></span>
        <SurfSlot h={am} label="Morning"/>
        <SurfSlot h={pm} label="Afternoon"/>
      </button>
      {ref && (
        <div className="sf-break-sub">
          Swell {(ref.hsM * 3.281).toFixed(1)} ft @ {Math.round(ref.tpS)} s {sfDir(ref.dpDeg)} ({ref.dpDeg}°)
          {am && am.windKt != null ? ` · AM wind ${am.windKt} kt ${am.windType}` : ''}
          {pm && pm.windKt != null ? ` · PM ${pm.windKt} kt ${pm.windType}` : ''}
          {ref.conf !== 'high' ? ` · ${ref.conf} confidence` : ''}
          {ref.modelsDisagree ? ' · models disagree' : ''}
        </div>
      )}
      {open && (
        <div className="sf-detail">
          <div className="sf-steps" role="table" aria-label={`${b.name} by time of day`}>
            <div className="sf-step sf-step-h" role="row">
              <span>Time</span><span>Surf</span><span>Wind</span><span>Tide</span><span>Rating</span>
            </div>
            {steps.map(h => (
              <div key={h.t} className="sf-step" role="row">
                <span>{sfLocal(h.t, { hour: 'numeric' })}</span>
                <span>{h.faceFt[0]}–{h.faceFt[1]} ft</span>
                <span>{h.windKt == null ? '—' : `${h.windKt} kt ${sfDir(h.windFrom)}`}</span>
                <span>{h.tideFt == null ? '—' : `${h.tideFt} ft`}</span>
                <span className={sfRatingClass(h.label)}>{h.score.toFixed(1)}</span>
              </div>
            ))}
          </div>
          <div className="sf-detail-notes">
            MOP point {b.mop} at {b.mopDepthM} m, beach faces {Math.round(b.shoreNormal)}°.
            {ref && ref.kgM ? ` Breaking height ${ref.hbM.toFixed(1)} m (Komar–Gaughan check ${ref.kgM.toFixed(1)} m).` : ''}
            {buoy ? ` Nearest buoy (CDIP ${buoy.station}) now: ${buoy.hsFt} ft @ ${Math.round(buoy.tpS)} s from ${sfDir(buoy.dpDeg)}, ${sfLocal(buoy.t, { hour: 'numeric', minute: '2-digit' })}.` : ''}
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

function SurfView({ navigate }) {
  const { data, error } = useSurfData();
  const [day, setDay] = useSfState(null);
  const [open, setOpen] = useSfState(null);

  const days = useSfMemo(() => {
    if (!data) return [];
    const now = Date.now() - 3 * 3600000;
    const keys = [];
    (data.breaks[0] ? data.breaks[0].hours : []).forEach(h => {
      if (Date.parse(h.t) < now) return;
      const k = sfDayKey(h.t);
      if (keys.indexOf(k) < 0) keys.push(k);
    });
    return keys.map(k => {
      const h = data.breaks[0].hours.find(x => sfDayKey(x.t) === k);
      return { key: k, label: sfLocal(h.t, { weekday: 'short', month: 'short', day: 'numeric' }) };
    });
  }, [data]);

  useSfEffect(() => { if (!day && days.length) setDay(days[0].key); }, [days]);

  if (error) return <div className="sf-wrap"><h1 className="sf-title">San Diego surf</h1><p className="sf-muted">The surf forecast is unavailable right now.</p></div>;
  if (!data) return <div className="sf-wrap"><h1 className="sf-title">San Diego surf</h1><p className="sf-muted">Loading surf forecast…</p></div>;

  const ageH = (Date.now() - Date.parse(data.generatedAt)) / 3600000;
  const stale = ageH > (data.staleAfterHours || SF_STALE_H);
  const tidesToday = (data.tides && data.tides.hilo || []).filter(t => sfDayKey(t.t) === day);
  const v = data.verification || {};

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

      {tidesToday.length > 0 && (
        <div className="sf-tides">Tides, La Jolla: {tidesToday.map(t =>
          `${t.type === 'H' ? 'High' : 'Low'} ${t.ft} ft ${sfLocal(t.t, { hour: 'numeric', minute: '2-digit' })}`).join(' · ')}</div>
      )}

      <ul className="sf-list">
        {data.breaks.map(b => (
          <SurfBreakRow key={b.id} b={b} dayKey={day} buoy={data.buoys && data.buoys[b.buoy]}
                        open={open === b.id} onToggle={() => setOpen(open === b.id ? null : b.id)}/>
        ))}
      </ul>

      <section className="sf-about">
        <h2>How this forecast works</h2>
        <p>{data.method}</p>
        <p>
          <b>What we've checked:</b> {v.what}. Over {v.testPeriod}, the blended model's error was{' '}
          {v.hsRmseM ? `${(v.hsRmseM.blend * 3.281).toFixed(1)} ft (RMS)` : '—'}, better than{' '}
          {(v.beats || []).join(' and ')}. {v.leadNote}
        </p>
        {v.observed && <p><b>Against observed surf:</b> {v.observed}</p>}
        <p><b>Not yet checked:</b> {v.notVerified} {v.scale} Ratings top out at Fair–Good: a model alone can't call a day Good or Epic.</p>
        <p className="sf-muted">Surf height is the face height of the bigger waves; occasional sets run larger. Always check the NWS rip current risk and conditions on the beach.</p>
        <p className="sf-credits">{(data.credits || []).join(' · ')}</p>
      </section>
    </div>
  );
}

window.SurfView = SurfView;
