// Paddle mode (stand-up paddling). Self-contained so it can move to its own
// site: own data (api/v1/paddle_spots.json, src/surf/paddle.py), own helpers,
// own CSS (pd-). The host passes navigation in as props:
//   <PaddleView spot={id|''} link={id => anchorProps} surfLink={surfId => anchorProps|null}/>
const { useState: usePdState, useEffect: usePdEffect } = React;

const PD_TZ = 'America/Los_Angeles';
const PD_DIRS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const PD_KIND = { bay: 'Bay', harbour: 'Harbour', lagoon: 'Lagoon', coast: 'Beach' };
function pdTime(iso, opts) { return new Date(iso).toLocaleString('en-US', Object.assign({ timeZone: PD_TZ }, opts)); }
function pdDir(d) { return d == null ? '' : PD_DIRS[Math.round(((d % 360) + 360) % 360 / 22.5) % 16]; }
function pdKey(label) { return label ? label.toLowerCase() : 'none'; }
function pdNow(hours) { const n = Date.now(); return hours.find(h => Date.parse(h.t) + 3600e3 > n) || hours[hours.length - 1]; }
function pdClock(iso) { return pdTime(iso, { hour: 'numeric', minute: '2-digit' }).replace(':00', ''); }
function pdWin(w) { return w ? `${pdClock(w.from)}–${pdClock(w.to)}` : ''; }
function pdWetsuit(f) {
  if (f == null) return '';
  if (f >= 70) return 'Boardshorts or spring suit';
  if (f >= 64) return 'Spring suit or 2 mm';
  if (f >= 58) return '3/2 wetsuit';
  return 'Full wetsuit, cold water';
}
function pdTideAt(t, ms) {
  const p = (t && t.hourly) || [];
  for (let k = 1; k < p.length; k++) {
    const t1 = Date.parse(p[k][0]);
    if (t1 >= ms) {
      const t0 = Date.parse(p[k - 1][0]);
      if (t0 > ms) return null;
      return p[k - 1][1] + (p[k][1] - p[k - 1][1]) * (ms - t0) / Math.max(1, t1 - t0);
    }
  }
  return null;
}
function pdArrow(toward) {
  return <i className="pd-arr" style={{ transform: `rotate(${toward}deg)` }} aria-hidden="true">↑</i>;
}

function usePaddleData() {
  const [st, setSt] = usePdState({ data: null, error: false });
  usePdEffect(() => {
    let alive = true;
    fetch('/api/v1/paddle_spots.json?h=' + new Date().toISOString().slice(0, 13))
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(d => { if (alive) setSt({ data: d, error: false }); })
      .catch(() => { if (alive) setSt({ data: null, error: true }); });
    return () => { alive = false; };
  }, []);
  return st;
}

function PaddlePill({ label }) { return <span className={`pd-pill pd-${pdKey(label)}`}>{label || '—'}</span>; }

// Tide, wind, water, waves and (where NOAA predicts it) current, for one hour.
function PaddleTiles({ pd, s, h }) {
  const ms = h ? Date.parse(h.t) : Date.now();
  const tides = (pd.tides || {})[s.tideStation];
  const tide = pdTideAt(tides, ms);
  const rising = tide != null && pdTideAt(tides, ms + 30 * 60e3) > tide;
  const next = ((tides && tides.hilo) || []).find(x => Date.parse(x.t) > ms);
  const wt = pd.waterTemp;
  const wind = h && h.windKt != null;
  const cur = h && h.current;
  return (
    <div className="pd-tiles">
      <div className="pd-tile">
        <span className="pd-k">Tide</span>
        <b>{tide != null ? `${tide.toFixed(1)} ft ${rising ? '↑' : '↓'}` : '—'}</b>
        <span className="pd-s">{next ? `${next.type === 'H' ? 'High' : 'Low'} ${next.ft} ft ${pdTime(next.t, { hour: 'numeric', minute: '2-digit' })}` : ''}</span>
        <span className="pd-src">{tides ? tides.name : ''}</span>
      </div>
      <div className="pd-tile">
        <span className="pd-k">Wind</span>
        <b>{wind ? <>{h.windFrom != null && pdArrow((h.windFrom + 180) % 360)}{h.windKt} kt</> : '—'}{wind && h.windGustKt != null && <small> g{h.windGustKt}</small>}</b>
        <span className="pd-s">{wind ? pdDir(h.windFrom) : ''}</span>
        {pd.windNote && <span className="pd-src">From last update</span>}
      </div>
      <div className="pd-tile">
        <span className="pd-k">Water</span>
        <b>{wt ? `${wt.f}°F` : '—'}</b>
        <span className="pd-s">{wt ? pdWetsuit(wt.f) : ''}</span>
        <span className="pd-src">{wt ? `Buoy ${wt.station}` : ''}</span>
      </div>
      <div className="pd-tile">
        <span className="pd-k">{s.kind === 'coast' ? 'Surf' : 'Waves'}</span>
        <b>{h && h.faceFt ? `${h.faceFt[0]}–${h.faceFt[1]} ft` : s.kind === 'coast' ? '—' : 'Flat'}</b>
        <span className="pd-s">{h && h.hsM != null ? `Swell ${(h.hsM * 3.281).toFixed(1)} ft · ${Math.round(h.tpS)} s ${pdDir(h.dpDeg)}` : s.kind === 'coast' ? '' : 'Sheltered'}</span>
      </div>
      {s.currentStation && (
        <div className="pd-tile">
          <span className="pd-k">Current</span>
          <b>{cur ? (cur.type === 'slack' ? 'Slack' : <>{cur.towardDeg != null && pdArrow(cur.towardDeg)}{cur.kt} kt</>) : '—'}</b>
          <span className="pd-s">{cur && cur.type !== 'slack' ? (cur.type === 'ebb' ? 'Ebb, outgoing' : 'Flood, incoming') : ''}</span>
          <span className="pd-src">{pd.currentStationName}{s.currentScored ? '' : ' (indicative)'}</span>
        </div>
      )}
    </div>
  );
}

function PaddleList({ pd, link }) {
  const rows = pd.spots.map(s => {
    const h = pdNow(s.hours);
    const best = (s.best || []).find(w => Date.parse(w.to) > Date.now());
    return { s, h, best, rank: h && h.level != null ? h.level : -1 };
  }).sort((a, b) => b.rank - a.rank || (b.best ? b.best.level : -1) - (a.best ? a.best.level : -1));
  return (
    <ol className="pd-list">
      {rows.map(({ s, h, best }) => (
        <li key={s.id}>
          <a className="pd-row" {...link(s.id)}>
            <span className="pd-name">{s.name}<i>{PD_KIND[s.kind]}</i></span>
            <PaddlePill label={h && h.label}/>
            <span className="pd-why">{h ? h.reason : ''}</span>
            <span className="pd-meta">
              {h && h.windKt != null && <span>{h.windFrom != null && pdArrow((h.windFrom + 180) % 360)}{h.windKt} kt{h.windGustKt != null ? ` g${h.windGustKt}` : ''}</span>}
              {h && h.tideFt != null && <span>Tide {h.tideFt.toFixed(1)}</span>}
              {h && h.faceFt && <span>Surf {h.faceFt[0]}–{h.faceFt[1]}</span>}
              {s.currentScored && h && h.current && h.current.type !== 'slack' && <span>{h.current.type === 'ebb' ? 'Ebb' : 'Flood'} {h.current.kt} kt</span>}
              {best && <small>Best {pdTime(best.from, { weekday: 'short' })} {pdWin(best)} · {best.label}</small>}
            </span>
          </a>
        </li>
      ))}
    </ol>
  );
}

function PaddleSpot({ pd, s, link, surfLink }) {
  const [day, setDay] = usePdState(null);
  usePdEffect(() => { window.scrollTo(0, 0); }, [s.id]);
  const h = pdNow(s.hours);
  const days = (s.best || []).filter(w => Date.parse(w.to) > Date.now() - 12 * 3600e3);
  const dk = day || (days[0] && days[0].date);
  const sun = (pd.sun || []).find(x => x.date === dk);
  const steps = sun ? s.hours.filter(x => Date.parse(x.t) >= Date.parse(sun.sunrise) - 3600e3 && Date.parse(x.t) <= Date.parse(sun.sunset)) : [];
  const surf = s.surfRef && surfLink ? surfLink(s.surfRef) : null;
  return (
    <div className="pd-wrap">
      <a className="pd-crumb" {...link('')}>← All paddle spots</a>
      <div className="pd-top">
        <h1 className="pd-title">{s.name}</h1>
        <span className="pd-chip">Rule of thumb</span>
      </div>
      <p className="pd-sub">{PD_KIND[s.kind]}{s.shoreNormal != null ? ` · faces ${pdDir(s.shoreNormal)}` : ''} · updated {pdTime(pd.generatedAt, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</p>
      <div className={`pd-now pd-now-${pdKey(h && h.label)}`}>
        <PaddlePill label={h && h.label}/> <b>{h ? h.reason : ''}</b>
      </div>
      <PaddleTiles pd={pd} s={s} h={h}/>
      {s.note && <p className="pd-note">{s.note}</p>}
      {surf && <p className="pd-sub"><a {...surf}>Surf forecast here →</a></p>}
      <section className="pd-panel">
        <h2 className="pd-h">Best window</h2>
        <ul className="pd-days">
          {days.map(w => (
            <li key={w.date}>
              <button type="button" className={`pd-day${w.date === dk ? ' on' : ''}`} onClick={() => setDay(w.date)}>
                <span className="pd-d">{pdTime(w.from, { weekday: 'short', month: 'short', day: 'numeric' })}</span>
                <PaddlePill label={w.label}/>
                <span className="pd-t">{pdWin(w)}</span>
                <span className="pd-r">{w.reason}{w.worseAfter ? ` Worse after ${pdTime(w.to, { hour: 'numeric' })}.` : ''}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="pd-panel">
        <h2 className="pd-h">{sun ? pdTime(sun.sunrise, { weekday: 'long' }) : ''} by hour</h2>
        <div className="pd-hours" role="table" aria-label={`${s.name} by hour`}>
          {steps.map(x => (
            <div key={x.t} role="row" className="pd-hr">
              <span className="pd-hr-t">{pdTime(x.t, { hour: 'numeric' })}</span>
              <PaddlePill label={x.label}/>
              <span className="pd-hr-w">{x.windKt != null ? <>{x.windFrom != null && pdArrow((x.windFrom + 180) % 360)}{x.windKt} kt{x.windGustKt != null ? ` g${x.windGustKt}` : ''}</> : '—'}</span>
              <span className="pd-hr-x">{x.tideFt != null ? `Tide ${x.tideFt.toFixed(1)}` : ''}{x.faceFt ? ` · Surf ${x.faceFt[0]}–${x.faceFt[1]}` : ''}{x.current && x.current.type !== 'slack' ? ` · ${x.current.type === 'ebb' ? 'Ebb' : 'Flood'} ${x.current.kt} kt` : ''}</span>
              <span className="pd-hr-r">{x.reason}</span>
            </div>
          ))}
        </div>
      </section>
      <p className="pd-src pd-credit">{pd.sources}</p>
    </div>
  );
}

function PaddleView({ spot, link, surfLink }) {
  const { data: pd, error } = usePaddleData();
  if (error) return <div className="pd-wrap"><h1 className="pd-title">Paddle</h1><p className="pd-sub">Paddle forecast unavailable right now.</p></div>;
  if (!pd) return <div className="pd-wrap"><h1 className="pd-title">Paddle</h1><p className="pd-sub">Loading…</p></div>;
  const s = spot && pd.spots.find(x => x.id === spot);
  if (spot && !s) return <div className="pd-wrap"><h1 className="pd-title">Spot not found</h1><p className="pd-sub"><a {...link('')}>All paddle spots →</a></p></div>;
  if (s) return <PaddleSpot pd={pd} s={s} link={link} surfLink={surfLink}/>;
  const wt = pd.waterTemp;
  return (
    <div className="pd-wrap">
      <div className="pd-top">
        <h1 className="pd-title">Paddle report</h1>
        <span className="pd-chip">Rule of thumb</span>
      </div>
      <p className="pd-sub">Updated {pdTime(pd.generatedAt, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}
        {wt ? ` · Water ${wt.f}°F, ${pdWetsuit(wt.f).toLowerCase()}` : ''}{pd.windNote ? ' · Wind from last update' : ''}</p>
      <PaddleList pd={pd} link={link}/>
      <p className="pd-src pd-credit">{pd.sources}</p>
    </div>
  );
}

window.PaddleView = PaddleView;
