// Paddle Tracker: paddler index and profiles (/sd/surf/races/paddlers, /sd/surf/races/paddler-<id>).
//
// Data: /api/v1/paddle_people.json, built by `python -m src.paddle.results build` from
// hand-entered files (PaddleGuru forbids scraping). Only paddlers the owner listed;
// hidden paddlers are removed before the file is written. Pages are noindex.
// Uses helpers from paddle-races.jsx (window.PaddleRacesKit). CSS prefix pr-.
const { useState: usePpState, useEffect: usePpEffect, useMemo: usePpMemo } = React;

function ppNoindex() {
  usePpEffect(() => {
    const m = document.createElement('meta');
    m.name = 'robots'; m.content = 'noindex, nofollow'; m.setAttribute('data-pp', '1');
    document.head.appendChild(m);
    return () => m.remove();
  }, []);
}

function ppSecs(t) {
  if (!t) return null;
  const p = t.split(':').map(Number);
  return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
}
function ppFmt(s, signed) {
  if (s == null) return '';
  const neg = s < 0; s = Math.round(Math.abs(s));
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  const body = (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(x).padStart(2, '0');
  return (signed ? (neg ? '−' : '+') : '') + body;
}
function ppPct(r) {
  if (!r.place || !r.field) return null;
  return r.field === 1 ? 100 : Math.round(100 * (r.field - r.place) / (r.field - 1));
}

// One row per result with race, distance, seconds, percentile, pace and conditions joined in.
function ppRows(people, races, cond) {
  const byRace = {};
  (races.races || []).forEach(r => { byRace[r.id] = r; });
  return (people.results || []).map(r => {
    const race = byRace[r.race] || { name: r.race, distances: [] };
    const dist = (race.distances || []).find(d => d.id === r.distance) || null;
    const secs = ppSecs(r.time);
    const c = cond && cond.races && cond.races[r.race] && cond.races[r.race][r.distance];
    return Object.assign({}, r, {
      raceObj: race, dist, secs, pct: ppPct(r),
      pace: secs && dist && dist.miles ? secs / dist.miles : null,
      cond: c || null, key: race.series + '|' + (r.distance || ''), date: race.date || String(race.year || ''),
    });
  }).sort((a, b) => (b.date || '').localeCompare(a.date || ''));
}

function PpIndex({ people, races, cond, hrefFor, go }) {
  const K = window.PaddleRacesKit;
  ppNoindex();
  const [q, setQ] = usePpState('');
  const [craft, setCraft] = usePpState('');
  const [series, setSeries] = usePpState('');
  const rows = usePpMemo(() => ppRows(people, races, cond), [people, races, cond]);
  const seriesOpts = usePpMemo(() => {
    const m = {};
    rows.forEach(r => { m[r.raceObj.series] = r.raceObj.name; });
    return Object.entries(m).sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);
  const list = (people.paddlers || []).map(p => {
    const mine = rows.filter(r => r.paddler === p.id);
    return { p, mine, crafts: [...new Set(mine.map(r => r.craft))] };
  }).filter(x => (!q || x.p.name.toLowerCase().includes(q.toLowerCase()))
    && (!craft || x.crafts.includes(craft))
    && (!series || x.mine.some(r => r.raceObj.series === series)))
    .sort((a, b) => a.p.name.localeCompare(b.p.name));
  return (
    <div className="pr-wrap">
      <K.PrLink className="pr-crumb" hrefFor={hrefFor} go={go} id="">← Races</K.PrLink>
      <h1 className="pr-title">Paddlers</h1>
      <div className="pr-filters">
        <input className="pr-input" type="search" placeholder="Search name" value={q} onChange={e => setQ(e.target.value)} aria-label="Search paddlers"/>
        <select className="pr-input" value={craft} onChange={e => setCraft(e.target.value)} aria-label="Division">
          <option value="">All divisions</option>
          {(people.crafts || []).map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="pr-input" value={series} onChange={e => setSeries(e.target.value)} aria-label="Race">
          <option value="">All races</option>
          {seriesOpts.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </div>
      <ul className="pr-list">
        {list.map(({ p, mine, crafts }) => (
          <li key={p.id}>
            <K.PrLink className="pr-row pr-row-pp" hrefFor={hrefFor} go={go} id={'paddler-' + p.id}>
              <span className="pr-row-main">
                <span className="pr-row-name">{p.name}{p.crew && <em className="pr-crew">crew</em>}</span>
                <span className="pr-row-sub">{mine.length} result{mine.length === 1 ? '' : 's'}{mine[0] ? ' · last: ' + mine[0].raceObj.name + ' ' + (mine[0].raceObj.year || '') : ''}</span>
                <span className="pr-chips">{crafts.map(c => <span key={c} className="pr-chip">{c}</span>)}</span>
              </span>
            </K.PrLink>
          </li>
        ))}
      </ul>
      {!list.length && <p className="pr-muted">{(people.paddlers || []).length ? 'No paddlers match.' : 'No paddlers listed yet.'}</p>}
      <p className="pr-foot">Paddlers listed by the site owner. Results typed in from public race results. <a href={people.remove}>Remove my profile</a></p>
    </div>
  );
}

// Simple SVG: percentile by race date (0–100, higher is better).
function PpPctChart({ rows }) {
  const pts = rows.filter(r => r.pct != null && r.raceObj.date).slice().reverse();
  if (pts.length < 2) return null;
  const W = 600, H = 150, L = 34, R = 10, T = 10, B = 24;
  const t0 = Date.parse(pts[0].raceObj.date), t1 = Date.parse(pts[pts.length - 1].raceObj.date) || t0 + 1;
  const x = d => L + (W - L - R) * (t1 === t0 ? 0.5 : (Date.parse(d) - t0) / (t1 - t0));
  const y = p => T + (H - T - B) * (1 - p / 100);
  return (
    <svg className="pr-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Placing percentile by race">
      {[0, 50, 100].map(v => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="pr-grid"/><text x={L - 6} y={y(v) + 4} className="pr-ax" textAnchor="end">{v}%</text></g>)}
      <polyline className="pr-line" points={pts.map(r => x(r.raceObj.date) + ',' + y(r.pct)).join(' ')}/>
      {pts.map((r, i) => <circle key={i} className="pr-pt" cx={x(r.raceObj.date)} cy={y(r.pct)} r="4"><title>{r.raceObj.name} {r.raceObj.year}: {r.pct}%</title></circle>)}
      <text x={L} y={H - 6} className="pr-ax">{pts[0].raceObj.year}</text>
      <text x={W - R} y={H - 6} className="pr-ax" textAnchor="end">{pts[pts.length - 1].raceObj.year}</text>
    </svg>
  );
}

function PpYoY({ rows, hrefFor, go }) {
  const K = window.PaddleRacesKit;
  const groups = {};
  rows.filter(r => r.secs).forEach(r => { (groups[r.key] = groups[r.key] || []).push(r); });
  const multi = Object.values(groups).filter(g => g.length > 1);
  if (!multi.length) return <p className="pr-muted pr-small">Shows once the same race has times from two or more years.</p>;
  return multi.map(g => {
    const yrs = g.slice().sort((a, b) => (a.raceObj.year || 0) - (b.raceObj.year || 0));
    const max = Math.max(...yrs.map(r => r.secs));
    return (
      <div key={yrs[0].key} className="pr-yoy">
        <div className="pr-yoy-h">{yrs[0].raceObj.name}{yrs[0].dist && yrs[0].dist.label !== yrs[0].raceObj.name ? ' · ' + yrs[0].dist.label : ''}</div>
        {yrs.map((r, i) => {
          const prev = yrs[i - 1];
          const d = prev ? r.secs - prev.secs : null;
          return (
            <div key={r.race} className="pr-yoy-row">
              <K.PrLink className="pr-yoy-yr" hrefFor={hrefFor} go={go} id={r.race}>{r.raceObj.year}</K.PrLink>
              <span className="pr-yoy-bar"><i style={{ width: (100 * r.secs / max) + '%' }}/></span>
              <span className="pr-yoy-t">{ppFmt(r.secs)}{d != null && <small className={d < 0 ? 'pr-faster' : 'pr-slower'}> {ppFmt(d, true)}</small>}</span>
              <span className="pr-yoy-c">{r.cond ? r.cond.reason.split(';')[0] : ''}</span>
            </div>
          );
        })}
      </div>
    );
  });
}

function PpH2H({ me, rows, people, hrefFor, go }) {
  const K = window.PaddleRacesKit;
  const mine = rows.filter(r => r.paddler === me.id && (r.secs || r.place));
  const out = (people.paddlers || []).filter(p => p.id !== me.id && (me.crew ? p.crew : true)).map(p => {
    let w = 0, l = 0;
    const gaps = [];
    mine.forEach(a => {
      // same race and distance; faster time wins (places only count within one division)
      const b = rows.find(r => r.paddler === p.id && r.key === a.key && r.race === a.race);
      if (!b) return;
      if (a.secs && b.secs) {
        if (a.secs < b.secs) w++; else if (a.secs > b.secs) l++;
        gaps.push(a.secs - b.secs);
      } else if (a.place && b.place && a.division && a.division === b.division) {
        if (a.place < b.place) w++; else if (a.place > b.place) l++;
      }
    });
    gaps.sort((x, y) => x - y);
    const med = gaps.length ? gaps[Math.floor(gaps.length / 2)] : null;
    return { p, w, l, med, n: w + l };
  }).filter(x => x.n > 0).sort((a, b) => b.n - a.n);
  if (!out.length) return <p className="pr-muted pr-small">No shared races with other listed paddlers yet.</p>;
  return (
    <ul className="pr-h2h">
      {out.map(x => (
        <li key={x.p.id}>
          <K.PrLink hrefFor={hrefFor} go={go} id={'paddler-' + x.p.id}>{x.p.name}</K.PrLink>
          <b>{x.w}–{x.l}</b>
          {x.med != null && <span className="pr-muted">median {x.med <= 0 ? ppFmt(-x.med) + ' ahead' : ppFmt(x.med) + ' behind'}</span>}
        </li>
      ))}
    </ul>
  );
}

function PpProfile({ id, people, races, cond, hrefFor, go }) {
  const K = window.PaddleRacesKit;
  ppNoindex();
  usePpEffect(() => { window.scrollTo(0, 0); }, [id]);
  const rows = usePpMemo(() => ppRows(people, races, cond), [people, races, cond]);
  const me = (people.paddlers || []).find(p => p.id === id);
  if (!me) {
    return <div className="pr-wrap"><h1 className="pr-title">Paddler not found</h1><K.PrLink className="pr-crumb" hrefFor={hrefFor} go={go} id="paddlers">← Paddlers</K.PrLink></div>;
  }
  const mine = rows.filter(r => r.paddler === me.id);
  const crafts = [...new Set(mine.map(r => r.craft))];
  const years = [...new Set(mine.map(r => r.raceObj.year).filter(Boolean))].sort();
  return (
    <div className="pr-wrap">
      <K.PrLink className="pr-crumb" hrefFor={hrefFor} go={go} id="paddlers">← Paddlers</K.PrLink>
      <h1 className="pr-title">{me.name}</h1>
      <p className="pr-meta">{crafts.join(', ') || 'No results yet'}{mine.length ? ` · ${mine.length} race${mine.length === 1 ? '' : 's'}` : ''}{years.length ? ' · ' + years[0] + (years.length > 1 ? '–' + years[years.length - 1] : '') : ''}</p>

      {mine.length > 0 && (
        <section className="pr-group">
          <h2 className="pr-h2">Results</h2>
          <div className="pr-res" role="table" aria-label="Race results">
            <div className="pr-res-row pr-leg-head" role="row">
              <span role="columnheader">Race</span><span role="columnheader">Time</span><span role="columnheader">Place</span>
              <span role="columnheader">Pace</span><span role="columnheader">Conditions</span>
            </div>
            {mine.map(r => (
              <div key={r.race + r.distance} className="pr-res-row" role="row">
                <span role="cell" className="pr-res-race">
                  <K.PrLink hrefFor={hrefFor} go={go} id={r.race}>{r.raceObj.name} {r.raceObj.year}</K.PrLink>
                  <small>{[r.dist && r.dist.label, r.division || r.craft].filter(Boolean).join(' · ')}</small>
                </span>
                <span role="cell">{r.time || '—'}</span>
                <span role="cell">{r.place ? r.place + (r.field ? '/' + r.field : '') : '—'}{r.pct != null && <small>{r.pct}%</small>}</span>
                <span role="cell">{r.pace ? ppFmt(r.pace) + '/mi' : '—'}</span>
                <span role="cell">{r.cond ? <><K.PrPill label={r.cond.label}/><small>{r.cond.reason.split(';')[0]}</small></> : '—'}
                  {r.source && <a className="pr-src-link" href={r.source} target="_blank" rel="noopener nofollow">results ↗</a>}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="pr-group"><h2 className="pr-h2">Year over year</h2><PpYoY rows={mine} hrefFor={hrefFor} go={go}/></section>
      {mine.some(r => r.pct != null) && <section className="pr-group"><h2 className="pr-h2">Placing</h2><PpPctChart rows={mine}/><p className="pr-muted pr-small">100% = won the division.</p></section>}
      <section className="pr-group"><h2 className="pr-h2">Head to head</h2><PpH2H me={me} rows={rows} people={people} hrefFor={hrefFor} go={go}/></section>
      <p className="pr-foot">Results typed in from public race results; each links to its source. <a href={people.remove}>Remove my profile</a></p>
    </div>
  );
}

// Crew results on a race page (used by paddle-races.jsx).
function PpRaceResults({ race, people, hrefFor, go }) {
  const K = window.PaddleRacesKit;
  if (!people) return null;
  const names = {};
  (people.paddlers || []).forEach(p => { names[p.id] = p.name; });
  const rows = (people.results || []).filter(r => r.race === race.id && names[r.paddler])
    .sort((a, b) => (a.distance || '').localeCompare(b.distance || '') || (a.craft || '').localeCompare(b.craft || '') || (a.place || 99) - (b.place || 99));
  if (!rows.length) return null;
  return (
    <section className="pr-group" aria-labelledby="pr-rr-h">
      <h2 className="pr-h2" id="pr-rr-h">Listed paddlers</h2>
      <ul className="pr-list">
        {rows.map(r => (
          <li key={r.paddler + r.distance} className="pr-rr">
            <K.PrLink hrefFor={hrefFor} go={go} id={'paddler-' + r.paddler}>{names[r.paddler]}</K.PrLink>
            <span className="pr-muted">{r.division || r.craft}</span>
            <b>{r.time || '—'}</b>
            <span>{r.place ? r.place + (r.field ? '/' + r.field : '') : ''}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

window.PaddlePaddlers = { PpIndex, PpProfile, PpRaceResults };
