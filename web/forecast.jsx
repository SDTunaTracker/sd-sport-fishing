// TODO: PRO FEATURE — lock for free users later (7-day strip, historical match)
const { useMemo, useState: useS } = React;

const FC = window.SD?.FORECAST || null;

function scoreColor(s) {
  if (s == null) return 'var(--tb-gray-3)';
  if (s >= 8)   return 'var(--tb-lime)';
  if (s >= 6)   return 'var(--tb-accent)';
  if (s >= 4)   return 'var(--tb-gold)';
  return 'var(--tb-coral)';
}

function moonEmoji(illum) {
  if (illum == null) return '🌑';
  if (illum <= 10) return '🌑';
  if (illum <= 35) return '🌒';
  if (illum <= 55) return '🌓';
  if (illum <= 75) return '🌔';
  if (illum <= 90) return '🌕';
  if (illum <= 97) return '🌖';
  return '🌕';
}

function windLabel(kn) {
  if (kn == null) return '—';
  return `${Math.round(kn)}kn`;
}

function swellLabel(ft) {
  if (ft == null) return '—';
  return `${ft.toFixed(1)}ft`;
}

function sstLabel(f) {
  if (f == null) return '—';
  return `${Math.round(f)}°F`;
}

function ScoreDot({ score, size = 10 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size,
      borderRadius: '50%', background: scoreColor(score),
      flexShrink: 0,
    }}/>
  );
}

function ScoreBar({ score, label }) {
  const pct = score != null ? ((score - 1) / 9) * 100 : 0;
  return (
    <div className="fc-factor-row">
      <span className="fc-factor-label">{label}</span>
      <div className="fc-factor-track">
        <div className="fc-factor-fill" style={{width: `${pct}%`, background: scoreColor(score)}}/>
      </div>
      <span className="fc-factor-val" style={{color: scoreColor(score)}}>
        {score != null ? score.toFixed(1) : '—'}
      </span>
    </div>
  );
}

// ─── Today summary bar ────────────────────────────────────────────────────────
function TodayConditionsBar({ today }) {
  if (!today) return null;
  const items = [
    { icon: '🌡️', val: sstLabel(today.sst_offshore || today.sst_nearshore), label: 'SST' },
    { icon: moonEmoji(today.moon_phase), val: today.moon_phase_name || '—', label: 'Moon' },
    { icon: '💨', val: windLabel(today.wind_speed), label: 'Wind' },
    { icon: '🌊', val: swellLabel(today.swell_height), label: 'Swell' },
  ];
  return (
    <div className="fc-conditions-bar">
      {items.map(({ icon, val, label }) => (
        <div key={label} className="fc-cond-item">
          <span className="fc-cond-icon">{icon}</span>
          <span className="fc-cond-val">{val}</span>
          <span className="fc-cond-lbl">{label}</span>
        </div>
      ))}
    </div>
  );
}

// ─── 7-day strip ─────────────────────────────────────────────────────────────
// TODO: PRO FEATURE — lock for free users later
function SevenDayStrip({ days, selectedIdx, onSelect }) {
  if (!days || days.length === 0) return null;
  return (
    <div className="fc-strip-wrap">
      <div className="fc-strip">
        {days.map((d, i) => (
          <button
            key={d.date}
            className={`fc-day-card${i === selectedIdx ? ' active' : ''}`}
            onClick={() => onSelect(i)}
          >
            <div className="fc-day-name">{d.dayName || '—'}</div>
            <div className="fc-day-label">{d.conditions_label?.split(' ').slice(0, 2).join(' ')}</div>
            <div className="fc-day-score" style={{color: scoreColor(d.overall_score)}}>
              {d.overall_score != null ? d.overall_score.toFixed(1) : '—'}
            </div>
            <div className="fc-day-meta">
              <span>{sstLabel(d.sst)}</span>
            </div>
            <div className="fc-day-meta">
              <span>🌊{swellLabel(d.swell_height)}</span>
              <span>💨{windLabel(d.wind_speed)}</span>
            </div>
            <div className="fc-day-meta">{moonEmoji(d.moon_phase)}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Selected day detail ──────────────────────────────────────────────────────
function forecastStatement(day) {
  if (day.summary) return day.summary;
  const s = day.overall_score;
  const ranked = [
    { name: 'Bluefin',    score: day.bluefin_score },
    { name: 'Yellowfin',  score: day.yellowfin_score },
    { name: 'Yellowtail', score: day.yellowtail_score },
    { name: 'Dorado',     score: day.dorado_score },
  ].filter(x => x.score != null).sort((a, b) => b.score - a.score);

  const opener = s >= 8 ? 'Excellent day on the water'
    : s >= 6 ? 'Good conditions expected'
    : s >= 4 ? 'Fair conditions'
    : 'Slow day expected';

  const hot = ranked.filter(x => x.score >= 7);
  if (hot.length) {
    const names = hot.slice(0, 2).map(x => x.name).join(' and ');
    return `${opener} — ${names} ${hot.length === 1 ? 'looks' : 'look'} like the best bet.`;
  }
  const top = ranked[0];
  if (top && top.score >= 5) return `${opener} — ${top.name} showing the strongest outlook.`;
  return `${opener} — tough bite across all species.`;
}

function DayDetail({ day }) {
  if (!day) return null;
  const stmt = forecastStatement(day);
  return (
    <Panel title={`${day.dayName || day.date} — Conditions`}>
      <div className="fc-detail-grid">
        <div className="fc-detail-left">
          <div className="fc-big-score">
            <div className="fc-score-num" style={{color: scoreColor(day.overall_score)}}>
              {day.overall_score != null ? day.overall_score.toFixed(1) : '—'}
            </div>
            <div className="fc-score-denom">/10</div>
            <div className="fc-score-label">{day.conditions_label}</div>
          </div>
          <div style={{marginTop: 12, fontSize: 12, color: 'var(--tb-slate)', lineHeight: 1.6}}>
            {day.date && `📅 ${new Date(day.date + 'T00:00:00').toLocaleDateString('en-US', {weekday:'long', month:'short', day:'numeric'})}`}
          </div>
        </div>
        {stmt && (
          <div className="fc-detail-right">
            <p style={{margin: 0, fontSize: 14, lineHeight: 1.7, color: 'var(--tb-ink)'}}>{stmt}</p>
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── Species grid ─────────────────────────────────────────────────────────────
function SpeciesGrid({ day }) {
  if (!day) return null;
  const species = [
    { key: 'bluefin_score',    name: 'Bluefin',    emoji: '🐟', color: SPECIES_COLORS.Bluefin    },
    { key: 'yellowfin_score',  name: 'Yellowfin',  emoji: '🐠', color: SPECIES_COLORS.Yellowfin  },
    { key: 'yellowtail_score', name: 'Yellowtail', emoji: '🐡', color: SPECIES_COLORS.Yellowtail },
    { key: 'dorado_score',     name: 'Dorado',     emoji: '🐬', color: SPECIES_COLORS.Dorado     },
  ];
  return (
    <Panel title="Species Forecast">
      <div className="fc-species-grid">
        {species.map(({ key, name, emoji, color }) => {
          const s = day[key];
          const pct = s != null ? Math.round(((s - 1) / 9) * 100) : 0;
          return (
            <div key={key} className="fc-species-card">
              <div className="fc-species-head">
                <span className="fc-species-emoji">{emoji}</span>
                <span className="fc-species-name" style={{color}}>{name}</span>
                <span className="fc-species-score" style={{color: scoreColor(s)}}>
                  {s != null ? s.toFixed(1) : '—'}/10
                </span>
              </div>
              <div className="fc-species-bar-wrap">
                <div className="fc-species-bar-fill" style={{width: `${pct}%`, background: color}}/>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ─── Conditions Like These widget ─────────────────────────────────────────────
// TODO: PRO FEATURE — lock for free users later
function HistoricalMatch({ match }) {
  if (!match || !match.matching_days) return null;
  return (
    <Panel title="Conditions Like These">
      <div className="fc-hist-intro">{match.description}</div>
      <div className="fc-hist-kpis">
        <div className="fc-hist-kpi">
          <div className="fc-hist-v">{match.avg_tpa != null ? match.avg_tpa.toFixed(1) : '—'}</div>
          <div className="fc-hist-k">Avg TPA</div>
        </div>
        <div className="fc-hist-kpi">
          <div className="fc-hist-v">{match.best_boat_avg != null ? match.best_boat_avg.toFixed(1) : '—'}</div>
          <div className="fc-hist-k">Best Boat Avg</div>
        </div>
        <div className="fc-hist-kpi">
          <div className="fc-hist-v">{match.pct_above_2tpa != null ? `${Math.round(match.pct_above_2tpa * 100)}%` : '—'}</div>
          <div className="fc-hist-k">Trips ≥2 TPA</div>
        </div>
        {match.best_species && (
          <div className="fc-hist-kpi">
            <div className="fc-hist-v">{match.best_species} 🔥</div>
            <div className="fc-hist-k">Top Species</div>
          </div>
        )}
      </div>
      {match.top_boats && match.top_boats.length > 0 && (
        <div style={{marginTop: 12}}>
          <div style={{fontSize: 11, fontWeight: 600, color: 'var(--tb-slate)', marginBottom: 6}}>
            Top Boats in These Conditions
          </div>
          <div className="fc-hist-boats">
            {match.top_boats.map((b, i) => (
              <div key={i} className="fc-hist-boat-row">
                <span className="fc-hist-rank">{i + 1}</span>
                <span className="fc-hist-bname">{b.boat}</span>
                <span className="fc-hist-landing">{b.landing?.replace(' Sportfishing','').replace(' Landing','')}</span>
                <span className="fc-hist-tpa">{b.avg_tpa?.toFixed(2)} TPA</span>
                <span className="fc-hist-trips">{b.trips} trips</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

// ─── SST trend chart ──────────────────────────────────────────────────────────
function SSTChart() {
  const sstData = window.SD?.SST?.history || [];
  if (!sstData.length) return null;

  const locations = ['60-Mile Bank', 'Nearshore'];
  const colors = { 'Nearshore': '#3B82F6', '60-Mile Bank': '#F97316' };
  const labels = { 'Nearshore': 'Nearshore', '60-Mile Bank': '60-Mile Bank' };

  // Build per-location series, last 30 days
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 30);
  const cutoffStr = cutoff.toISOString().slice(0, 10);

  const byLoc = {};
  for (const r of sstData) {
    if (r.date < cutoffStr) continue;
    if (!locations.includes(r.location)) continue;
    if (!byLoc[r.location]) byLoc[r.location] = [];
    byLoc[r.location].push({ date: r.date, sst: r.sst });
  }

  const allDates = [...new Set(sstData.filter(r => r.date >= cutoffStr).map(r => r.date))].sort();
  if (allDates.length < 3) return null;

  const allSsts = Object.values(byLoc).flat().map(r => r.sst).filter(Boolean);
  const minS = Math.min(...allSsts) - 1;
  const maxS = Math.max(...allSsts) + 1;
  const W = 600, H = 180, PL = 40, PR = 12, PT = 12, PB = 28;
  const iW = W - PL - PR, iH = H - PT - PB;

  const x = (i) => PL + (i / (allDates.length - 1)) * iW;
  const y = (v) => PT + iH - ((v - minS) / (maxS - minS)) * iH;

  const speciesBands = [
    { lo: 62, hi: 68, color: '#1F4E8F22', label: 'Bluefin zone' },
    { lo: 68, hi: 75, color: '#FFBA3022', label: 'Yellowfin zone' },
  ];

  return (
    <Panel title="30-Day SST Trend">
      <div style={{overflowX: 'auto'}}>
        <svg width={W} height={H} style={{display: 'block', minWidth: W}}>
          {/* Species temp bands */}
          {speciesBands.map(({ lo, hi, color, label }) => {
            const y1 = y(hi), y2 = y(lo);
            if (y1 > H || y2 < 0) return null;
            return (
              <g key={label}>
                <rect x={PL} y={y1} width={iW} height={y2 - y1} fill={color}/>
                <text x={PL + 4} y={y1 + 10} fontSize={9} fill="#888">{label}</text>
              </g>
            );
          })}
          {/* Gridlines */}
          {[minS, (minS + maxS) / 2, maxS].map(v => (
            <g key={v}>
              <line x1={PL} y1={y(v)} x2={W - PR} y2={y(v)} stroke="#e2e8f0" strokeWidth={1}/>
              <text x={PL - 4} y={y(v) + 4} textAnchor="end" fontSize={9} fill="#94a3b8">{v.toFixed(0)}°</text>
            </g>
          ))}
          {/* Lines per location */}
          {locations.map(loc => {
            const series = byLoc[loc] || [];
            if (series.length < 2) return null;
            const pts = series.map(r => {
              const di = allDates.indexOf(r.date);
              return di >= 0 ? [x(di), y(r.sst)] : null;
            }).filter(Boolean);
            const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ');
            return (
              <g key={loc}>
                <path d={d} fill="none" stroke={colors[loc]} strokeWidth={2} strokeLinejoin="round"/>
                <text x={pts[pts.length - 1][0] + 4} y={pts[pts.length - 1][1] + 4}
                      fontSize={9} fill={colors[loc]}>{labels[loc]}</text>
              </g>
            );
          })}
          {/* X-axis: date labels every 7 days */}
          {allDates.filter((_, i) => i % 7 === 0).map(d => {
            const di = allDates.indexOf(d);
            const mm = d.slice(5, 7), dd = d.slice(8);
            return (
              <text key={d} x={x(di)} y={H - 4} textAnchor="middle" fontSize={9} fill="#94a3b8">
                {`${+mm}/${+dd}`}
              </text>
            );
          })}
        </svg>
      </div>
      <div className="fc-sst-legend">
        {locations.map(loc => (
          <span key={loc} style={{display:'flex', alignItems:'center', gap:4, fontSize:11}}>
            <span style={{width:18, height:3, background: colors[loc], borderRadius:2, display:'inline-block'}}/>
            {labels[loc]}
          </span>
        ))}
      </div>
    </Panel>
  );
}

// ─── Accuracy widget ──────────────────────────────────────────────────────────
function AccuracyWidget({ accuracy }) {
  if (!accuracy || !accuracy.total_days_tested) return null;
  const dacc = accuracy.direction_accuracy;
  const trend = accuracy.last_30_days_accuracy;
  const trendTxt = trend != null
    ? (trend > dacc ? ` ⬆️ Last 30d: ${trend}%` : trend < dacc ? ` ⬇️ Last 30d: ${trend}%` : '')
    : '';
  return (
    <Panel title="Forecast Accuracy">
      <div className="fc-accuracy-grid">
        <div className="fc-acc-kpi">
          <div className="fc-acc-v">{dacc != null ? `${dacc}%` : '—'}</div>
          <div className="fc-acc-k">Direction Accuracy</div>
        </div>
        <div className="fc-acc-kpi">
          <div className="fc-acc-v">{accuracy.mae != null ? accuracy.mae.toFixed(1) : '—'}</div>
          <div className="fc-acc-k">MAE (avg error)</div>
        </div>
        <div className="fc-acc-kpi">
          <div className="fc-acc-v">{accuracy.total_days_tested?.toLocaleString()}</div>
          <div className="fc-acc-k">Days Analyzed</div>
        </div>
      </div>
      <div style={{fontSize: 12, color: 'var(--tb-slate)', marginTop: 8, lineHeight: 1.6}}>
        Based on {accuracy.total_days_tested?.toLocaleString()} days of historical data.
        {trendTxt && <span style={{color: trend > dacc ? 'var(--tb-lime)' : 'var(--tb-coral)'}}>{trendTxt}</span>}
        {' '}Improving continuously as more trip data is collected.
      </div>
    </Panel>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────
function NoForecastData() {
  return (
    <div style={{padding: '48px 24px', textAlign: 'center', color: 'var(--tb-slate)'}}>
      <div style={{fontSize: 32, marginBottom: 12}}>🌊</div>
      <div style={{fontWeight: 600, marginBottom: 8}}>Forecast data not yet generated</div>
      <div style={{fontSize: 13, lineHeight: 1.6, maxWidth: 420, margin: '0 auto'}}>
        Run the daily pipeline to generate forecast data:
      </div>
      <pre style={{display: 'inline-block', marginTop: 12, padding: '8px 16px',
                   background: '#f1f5f9', borderRadius: 6, fontSize: 12,
                   color: 'var(--tb-ink)', textAlign: 'left'}}>
        python -m src.main --export-only
      </pre>
    </div>
  );
}

// ─── Main view ────────────────────────────────────────────────────────────────
function ForecastView({ navigate }) {
  const fc = window.SD?.FORECAST;
  const [selectedDay, setSelectedDay] = useS(0);

  if (!fc || !fc.today) {
    return (
      <Fragment>
        <div className="pagehead">
          <h1>Fishing Forecast</h1>
          <p style={{fontSize:14, color:'var(--tb-gray-3)', maxWidth:560, marginBottom:16, lineHeight:1.6}}>
            Daily fishing conditions score (1–10) based on proprietary multi-factor analysis.
          </p>
        </div>
        <NoForecastData/>
      </Fragment>
    );
  }

  const today = fc.today;
  const days  = fc.sevenDay || [];
  const selDay = days[selectedDay] || today;

  return (
    <Fragment>
      <div className="pagehead">
        <div>
          <h1>Fishing Forecast</h1>
          <p style={{fontSize:14, color:'var(--tb-gray-3)', maxWidth:560, marginBottom:16, lineHeight:1.6}}>
            Daily fishing conditions score (1–10) based on proprietary multi-factor analysis.
          </p>
        </div>
      </div>

      {/* Today's headline score */}
      <Panel>
        <div className="fc-today-hero">
          <div className="fc-hero-left">
            <div className="fc-hero-label">{today.conditions_label}</div>
            <div className="fc-hero-score" style={{color: scoreColor(today.overall_score)}}>
              {today.overall_score != null ? today.overall_score.toFixed(1) : '—'}
              <span className="fc-hero-denom">/10</span>
            </div>
            <div className="fc-hero-date">
              {today.dataDate && today.dataDate !== today.date
                ? `Based on ${today.dataDate} SST data`
                : `Today · ${today.date}`}
            </div>
          </div>
          <div className="fc-hero-right">
            {today.summary && (
              <div className="fc-hero-summary">{today.summary}</div>
            )}
            <TodayConditionsBar today={today}/>
          </div>
        </div>
      </Panel>

      {/* 7-day strip + selected day detail */}
      {/* TODO: PRO FEATURE — lock for free users later */}
      {days.length > 0 && (
        <Fragment>
          <div style={{marginTop: 16}}>
            <div className="panel-title-inline">7-Day Forecast</div>
          </div>
          <SevenDayStrip days={days} selectedIdx={selectedDay} onSelect={setSelectedDay}/>
          <DayDetail day={selDay}/>
        </Fragment>
      )}

      {/* Species cards */}
      <SpeciesGrid day={selDay}/>

      {/* Conditions Like These */}
      {/* TODO: PRO FEATURE — lock for free users later */}
      <HistoricalMatch match={fc.historicalMatch}/>

      {/* SST trend chart */}
      <SSTChart/>

      {/* Accuracy */}
      <AccuracyWidget accuracy={fc.accuracy}/>
    </Fragment>
  );
}

Object.assign(window, { ForecastView });
