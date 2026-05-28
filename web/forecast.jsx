// TODO: PRO FEATURE — lock for free users later (7-day strip, historical match)
const { useMemo, useState: useS, useEffect: useE } = React;

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
    { key: 'bluefin_score',    name: 'Bluefin',    color: SPECIES_COLORS.Bluefin    },
    { key: 'yellowfin_score',  name: 'Yellowfin',  color: SPECIES_COLORS.Yellowfin  },
    { key: 'yellowtail_score', name: 'Yellowtail', color: SPECIES_COLORS.Yellowtail },
    { key: 'dorado_score',     name: 'Dorado',     color: SPECIES_COLORS.Dorado     },
  ];
  return (
    <Panel title="Species Forecast">
      <div className="fc-species-grid">
        {species.map(({ key, name, color }) => {
          const s = day[key];
          const pct = s != null ? Math.round(((s - 1) / 9) * 100) : 0;
          return (
            <div key={key} className="fc-species-card">
              <div className="fc-species-head">
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

// ─── Consensus components ─────────────────────────────────────────────────────

const CONSENSUS_DOTS_MAP = { Strong: 5, Moderate: 4, Mixed: 3, Conflicted: 2 };

const FACTOR_DISPLAY = {
  sst:          { label: 'SST',            icon: '🌡️' },
  wind_dir:     { label: 'Wind direction', icon: '🧭' },
  sst_gradient: { label: 'Temp break',     icon: '📈' },
  chlorophyll:  { label: 'Chlorophyll',    icon: '🌿' },
  wind_speed:   { label: 'Wind speed',     icon: '💨' },
  swell:        { label: 'Swell',          icon: '🌊' },
  moon:         { label: 'Moon',           icon: '🌙' },
  upwelling:    { label: 'Upwelling',      icon: '🌀' },
};

// ─── Upwelling indicator ──────────────────────────────────────────────────────
function UpwellingWidget({ upwelling }) {
  if (!upwelling || upwelling.index == null) return null;
  const ix    = upwelling.index;
  const label = upwelling.label || '—';
  const fav   = upwelling.is_favorable;
  const color = fav ? '#10B981' : ix >= 150 ? '#EF4444' : '#F97316';
  const bg    = color + '15';
  const note  = fav
    ? 'Weak/downwelling conditions retain warm water — favorable for offshore tuna.'
    : ix >= 150
      ? 'Strong upwelling is pushing cold water inshore — expect fish to hold deeper or farther out.'
      : 'Moderate upwelling is active — nearshore conditions may be cooler than usual.';
  return (
    <Panel>
      <div style={{display:'flex', alignItems:'center', gap:12, flexWrap:'wrap'}}>
        <div style={{
          display:'flex', alignItems:'center', gap:8,
          background: bg, borderRadius:8, padding:'8px 14px', flexShrink:0,
        }}>
          <span style={{fontSize:20}}>🌀</span>
          <div>
            <div style={{fontWeight:700, fontSize:13, color}}>{label}</div>
            <div style={{fontSize:11, color:'var(--tb-slate)'}}>
              Index: {ix > 0 ? '+' : ''}{Math.round(ix)} · {upwelling.date || ''}
            </div>
          </div>
        </div>
        <div style={{fontSize:12, color:'var(--tb-slate)', lineHeight:1.6, flex:1, minWidth:180}}>
          {note}
        </div>
      </div>
    </Panel>
  );
}

function factorNote(score) {
  if (score >= 8.5) return 'strongly favorable';
  if (score >= 7.0) return 'favorable';
  if (score >= 5.5) return 'neutral';
  if (score >= 4.0) return 'unfavorable';
  return 'strongly unfavorable';
}

function ConsensusDots({ label, color, size = 8 }) {
  const filled = CONSENSUS_DOTS_MAP[label] ?? 3;
  return (
    <span className="fc-consensus-dots">
      {[0,1,2,3,4].map(i => (
        <span key={i} className="fc-consensus-dot" style={{
          width: size, height: size,
          background: i < filled ? color : 'var(--tb-border)',
        }}/>
      ))}
    </span>
  );
}

function ConsensusBreakdown({ today, segment }) {
  if (!today?.consensus) return null;
  const c  = today.consensus;
  const fs = today.factor_scores || {};

  // Determine which factors are in scope for this segment's consensus
  const consensusKeys = segment === 'offshore'
    ? ['sst', 'wind_dir', 'sst_gradient', 'chlorophyll']
    : ['sst', 'wind_dir', 'chlorophyll'];
  const secondaryKeys = Object.keys(fs).filter(k => !consensusKeys.includes(k));

  const agreeSet    = new Set((c.factors_agreeing    || []).map(f => f.key));
  const conflictSet = new Set((c.factors_conflicting || []).map(f => f.key));

  // Summary sentence
  const n     = c.factors_agreeing?.length ?? 0;
  const total = n + (c.factors_conflicting?.length ?? 0);
  let summary;
  if (c.consensus_label === 'Strong') {
    summary = `All ${total} key factors agree — high forecast confidence.`;
  } else if (c.consensus_label === 'Moderate') {
    summary = `${n} of ${total} key factors agree — moderate forecast confidence.`;
  } else if (c.consensus_label === 'Mixed') {
    const bad = (c.factors_conflicting || []).map(f => FACTOR_DISPLAY[f.key]?.label || f.key).join(', ');
    summary = `Factors are mixed${bad ? ` — ${bad} is diverging` : ''} — treat this forecast with some caution.`;
  } else {
    const bad = (c.factors_conflicting || []).map(f => FACTOR_DISPLAY[f.key]?.label || f.key).join(', ');
    summary = `Factors are conflicted${bad ? ` — ${bad} pulling against the tide` : ''} — forecast uncertainty is higher than usual.`;
  }

  return (
    <div className="fc-consensus-breakdown">
      <div className="fc-consensus-bd-title">Why we're {c.consensus_label === 'Strong' || c.consensus_label === 'Moderate' ? 'confident' : 'uncertain'}</div>
      {consensusKeys.filter(k => fs[k] != null).map(k => {
        const agrees   = agreeSet.has(k);
        const conflicts = conflictSet.has(k);
        const icon = agrees ? '✓' : conflicts ? '✗' : '?';
        const iconColor = agrees ? '#10B981' : conflicts ? '#EF4444' : '#94A3B8';
        const fd = FACTOR_DISPLAY[k] || { label: k, icon: '' };
        return (
          <div key={k} className="fc-consensus-bd-factor">
            <span className="fc-consensus-bd-icon" style={{color: iconColor}}>{icon}</span>
            <span className="fc-consensus-bd-name">{fd.icon} {fd.label}</span>
            <span className="fc-consensus-bd-score" style={{color: scoreColor(fs[k])}}>{fs[k].toFixed(1)}</span>
            <span className="fc-consensus-bd-note">— {factorNote(fs[k])}</span>
          </div>
        );
      })}
      {secondaryKeys.filter(k => fs[k] != null && fs[k] !== 5.0).map(k => {
        const fd = FACTOR_DISPLAY[k] || { label: k, icon: '' };
        return (
          <div key={k} className="fc-consensus-bd-factor" style={{opacity: 0.65}}>
            <span className="fc-consensus-bd-icon" style={{color: '#94A3B8'}}>·</span>
            <span className="fc-consensus-bd-name">{fd.icon} {fd.label}</span>
            <span className="fc-consensus-bd-score" style={{color: scoreColor(fs[k])}}>{fs[k].toFixed(1)}</span>
            <span className="fc-consensus-bd-note">— {factorNote(fs[k])}</span>
          </div>
        );
      })}
      <div className="fc-consensus-summary">{summary}</div>
    </div>
  );
}

// ─── Dual segment components ──────────────────────────────────────────────────

function ConfidencePill({ label }) {
  const colors = { High: '#22c55e', Medium: '#f59e0b', Low: '#f97316', Outlook: '#94a3b8' };
  const c = colors[label] || '#94a3b8';
  return (
    <span style={{
      display: 'inline-block', fontSize: 10, fontWeight: 700,
      padding: '1px 7px', borderRadius: 99,
      background: c + '22', color: c, letterSpacing: '0.03em',
    }}>{label}</span>
  );
}

function ScoreRange({ low, score, high }) {
  if (low == null || high == null) return null;
  const pctLow  = ((low   - 1) / 9) * 100;
  const pctHigh = ((high  - 1) / 9) * 100;
  const pctMid  = ((score - 1) / 9) * 100;
  const rangeW  = pctHigh - pctLow;
  return (
    <div style={{margin: '6px 0'}}>
      <div style={{height: 8, background: 'var(--tb-border)', borderRadius: 4, position: 'relative', overflow: 'hidden'}}>
        <div style={{
          position: 'absolute', left: `${pctLow}%`, width: `${rangeW}%`,
          top: 0, bottom: 0, background: scoreColor(score) + '44', borderRadius: 4,
        }}/>
        <div style={{
          position: 'absolute', left: `${pctMid}%`, width: 3,
          top: 0, bottom: 0, background: scoreColor(score), borderRadius: 2,
          transform: 'translateX(-1px)',
        }}/>
      </div>
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        fontSize: 10, color: 'var(--tb-slate)', marginTop: 2,
      }}>
        <span>{low.toFixed(1)}</span>
        <span style={{fontWeight: 600, color: scoreColor(score)}}>{score.toFixed(1)}</span>
        <span>{high.toFixed(1)}</span>
      </div>
    </div>
  );
}

function SegmentCard({ title, today }) {
  if (!today || today.overall_score == null) {
    return (
      <div className="fc-segment-card">
        <div className="fc-seg-head">
          <span className="fc-seg-title">{title}</span>
        </div>
        <div style={{color: 'var(--tb-slate)', fontSize: 13, padding: '12px 0'}}>No data</div>
      </div>
    );
  }
  const fs = today.factor_scores || {};
  const topFactors = Object.entries(fs)
    .filter(([, v]) => v != null)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3);
  return (
    <div className="fc-segment-card">
      <div className="fc-seg-head">
        <span className="fc-seg-title">{title}</span>
        {today.confidence && <ConfidencePill label={today.confidence}/>}
      </div>
      <div className="fc-seg-score" style={{color: scoreColor(today.overall_score)}}>
        {today.overall_score.toFixed(1)}
        <span className="fc-seg-denom">/10</span>
      </div>
      <div className="fc-seg-label">{today.conditions_label}</div>
      <ScoreRange low={today.score_low} score={today.overall_score} high={today.score_high}/>
      {today.consensus && (
        <div className="fc-consensus-row">
          <ConsensusDots label={today.consensus.consensus_label} color={today.consensus.consensus_color}/>
          <span style={{color: today.consensus.consensus_color, fontWeight: 700, fontSize: 11}}>
            {today.consensus.consensus_label}
          </span>
          <span style={{color: 'var(--tb-slate)', fontSize: 11}}>
            {today.consensus.consensus_pct}% consensus
          </span>
        </div>
      )}
      {topFactors.length > 0 && (
        <div className="fc-seg-factors">
          {topFactors.map(([k, v]) => (
            <div key={k} className="fc-seg-factor-row">
              <span className="fc-seg-fk">{k.replace('_', ' ')}</span>
              <div className="fc-seg-fbar">
                <div style={{
                  height: '100%', width: `${((v - 1) / 9) * 100}%`,
                  background: scoreColor(v), borderRadius: 2,
                }}/>
              </div>
              <span className="fc-seg-fv" style={{color: scoreColor(v)}}>{v.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DualSegmentWidget({ fc }) {
  const inshore  = fc?.inshore?.today;
  const offshore = fc?.offshore?.today;
  if (!inshore && !offshore) return null;
  // Show breakdown for whichever segment has higher confidence need (lower consensus)
  const [activeBreakdown, setActiveBreakdown] = useS(null);
  const toggleBreakdown = seg => setActiveBreakdown(prev => prev === seg ? null : seg);
  const segForBreakdown = activeBreakdown === 'inshore' ? inshore : offshore;
  return (
    <Panel title="Inshore vs Offshore">
      <div className="fc-dual-grid">
        <div>
          <SegmentCard title="Inshore"  today={inshore}/>
          {inshore?.consensus && (
            <button className="fc-consensus-toggle" onClick={() => toggleBreakdown('inshore')}>
              {activeBreakdown === 'inshore' ? 'Hide breakdown ↑' : 'Why? Factor breakdown ↓'}
            </button>
          )}
        </div>
        <div>
          <SegmentCard title="Offshore" today={offshore}/>
          {offshore?.consensus && (
            <button className="fc-consensus-toggle" onClick={() => toggleBreakdown('offshore')}>
              {activeBreakdown === 'offshore' ? 'Hide breakdown ↑' : 'Why? Factor breakdown ↓'}
            </button>
          )}
        </div>
      </div>
      {activeBreakdown && segForBreakdown && (
        <ConsensusBreakdown today={segForBreakdown} segment={activeBreakdown}/>
      )}
    </Panel>
  );
}

function DualSevenDayStrip({ fc }) {
  const [tab, setTab] = useS('offshore');
  const inDays  = fc?.inshore?.sevenDay  || [];
  const offDays = fc?.offshore?.sevenDay || [];
  if (!inDays.length && !offDays.length) return null;
  const days = tab === 'inshore' ? inDays : offDays;
  const [selectedIdx, setSelectedIdx] = useS(0);
  const selDay = days[selectedIdx];

  return (
    <div>
      <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:8, marginTop:16}}>
        <div className="panel-title-inline" style={{marginBottom:0}}>
          7-Day Segment Forecast
        </div>
        <div className="fc-seg-tabs">
          {['offshore','inshore'].map(t => (
            <button
              key={t}
              className={`fc-seg-tab${tab === t ? ' active' : ''}`}
              onClick={() => { setTab(t); setSelectedIdx(0); }}
            >
              {t === 'offshore' ? 'Offshore' : 'Inshore'}
            </button>
          ))}
        </div>
      </div>
      <div className="fc-strip-wrap">
        <div className="fc-strip">
          {days.map((d, i) => {
            const cn = d.consensus;
            const tooltipText = cn
              ? `${cn.consensus_label} consensus (${cn.consensus_pct}%) — ${
                  cn.factors_agreeing?.length ?? 0} of ${
                  (cn.factors_agreeing?.length ?? 0) + (cn.factors_conflicting?.length ?? 0)} factors agree`
              : '';
            return (
              <button
                key={d.date}
                className={`fc-day-card${i === selectedIdx ? ' active' : ''}`}
                onClick={() => setSelectedIdx(i)}
              >
                <div className="fc-day-name">{d.dayName || '—'}</div>
                {d.confidence && <ConfidencePill label={d.confidence}/>}
                <div className="fc-day-score" style={{color: scoreColor(d.overall_score)}}>
                  {d.overall_score != null ? d.overall_score.toFixed(1) : '—'}
                </div>
                {d.score_low != null && d.score_high != null && (
                  <div style={{fontSize: 10, color: 'var(--tb-slate)', marginTop: 2}}>
                    {d.score_low.toFixed(1)}–{d.score_high.toFixed(1)}
                  </div>
                )}
                <div className="fc-day-label">
                  {d.conditions_label?.split(' ').slice(0, 2).join(' ')}
                </div>
                {cn && (
                  <div className="fc-day-consensus" title={tooltipText}>
                    <span className="fc-day-consensus-dot" style={{background: cn.consensus_color}}/>
                    <span style={{color: cn.consensus_color, fontSize: 9, fontWeight: 700}}>
                      {cn.consensus_label}
                    </span>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>
      {selDay && (
        <Panel title={`${selDay.dayName || selDay.date} — ${tab.charAt(0).toUpperCase() + tab.slice(1)} Detail`}>
          <div className="fc-detail-grid">
            <div className="fc-detail-left">
              <div className="fc-big-score">
                <div className="fc-score-num" style={{color: scoreColor(selDay.overall_score)}}>
                  {selDay.overall_score != null ? selDay.overall_score.toFixed(1) : '—'}
                </div>
                <div className="fc-score-denom">/10</div>
                <div className="fc-score-label">{selDay.conditions_label}</div>
              </div>
              {selDay.confidence && <div style={{marginTop: 6}}><ConfidencePill label={selDay.confidence}/></div>}
              <ScoreRange low={selDay.score_low} score={selDay.overall_score} high={selDay.score_high}/>
              {selDay.consensus && (
                <div className="fc-consensus-row" style={{marginTop: 10}}>
                  <ConsensusDots label={selDay.consensus.consensus_label} color={selDay.consensus.consensus_color}/>
                  <span style={{color: selDay.consensus.consensus_color, fontWeight: 700, fontSize: 11}}>
                    {selDay.consensus.consensus_label}
                  </span>
                  <span style={{color: 'var(--tb-slate)', fontSize: 11}}>
                    {selDay.consensus.consensus_pct}%
                  </span>
                </div>
              )}
            </div>
            {selDay.factor_scores && (
              <div className="fc-detail-right">
                {Object.entries(selDay.factor_scores).map(([k, v]) => v != null && (
                  <ScoreBar key={k} score={v}
                    label={k.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}/>
                ))}
              </div>
            )}
          </div>
          <ConsensusBreakdown today={selDay} segment={tab}/>
        </Panel>
      )}
    </div>
  );
}


// ─── Ensemble model widget ────────────────────────────────────────────────────
const MODEL_WEIGHTS = { A: 40, B: 35, C: 25 };

function EnsembleWidget({ ensemble }) {
  if (!ensemble || (!ensemble.inshore && !ensemble.offshore)) return null;
  const [seg, setSeg] = useS('offshore');
  const data = ensemble[seg];
  if (!data || data.ensemble_score == null) return null;

  const { models, ensemble_score, confidence, confidence_color, note, std_dev, all_agree, direction } = data;
  const modelList = ['A', 'B', 'C'].map(k => ({ key: k, ...(models?.[k] || {}) })).filter(m => m.score != null);

  const directionNote = all_agree
    ? (direction === 'good'
        ? <span style={{color:'#10B981', fontWeight:600}}> All models agree: favorable conditions.</span>
        : <span style={{color:'#EF4444', fontWeight:600}}> All models agree: slow day expected.</span>)
    : null;

  return (
    <Panel title="Model Ensemble">
      {/* Segment tabs */}
      <div className="fc-seg-tabs" style={{marginBottom:14}}>
        {['offshore','inshore'].map(t => (
          <button key={t} className={`fc-seg-tab${seg===t?' active':''}`} onClick={() => setSeg(t)}>
            {t.charAt(0).toUpperCase()+t.slice(1)}
          </button>
        ))}
      </div>

      {/* Headline row */}
      <div style={{display:'flex', alignItems:'center', gap:16, marginBottom:16, flexWrap:'wrap'}}>
        <div>
          <div style={{fontSize:11, color:'var(--tb-slate)', marginBottom:2, textTransform:'uppercase', letterSpacing:'0.05em'}}>Ensemble</div>
          <div style={{fontSize:30, fontWeight:800, color:scoreColor(ensemble_score), lineHeight:1}}>
            {ensemble_score.toFixed(1)}
            <span style={{fontSize:14, fontWeight:400, color:'var(--tb-slate)'}}>/10</span>
          </div>
        </div>
        <div style={{
          display:'flex', alignItems:'center', gap:8,
          background: confidence_color+'18', borderRadius:8, padding:'7px 13px',
        }}>
          <span style={{
            width:9, height:9, borderRadius:'50%',
            background:confidence_color, display:'inline-block', flexShrink:0,
          }}/>
          <div>
            <div style={{fontWeight:700, fontSize:12, color:confidence_color}}>{confidence} Confidence</div>
            <div style={{fontSize:10, color:'var(--tb-slate)'}}>
              Std dev: {std_dev != null ? std_dev.toFixed(2) : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* 3 model score bars with weights */}
      <div style={{display:'flex', flexDirection:'column', gap:10, marginBottom:14}}>
        {modelList.map(m => {
          const pct = ((m.score - 1) / 9) * 100;
          const wt  = MODEL_WEIGHTS[m.key] || m.weight * 100;
          return (
            <div key={m.key} style={{display:'grid', gridTemplateColumns:'108px 1fr 36px', gap:10, alignItems:'center'}}>
              <div>
                <div style={{display:'flex', alignItems:'baseline', gap:5}}>
                  <span style={{fontSize:12, fontWeight:700, color:'var(--tb-ink)'}}>{m.label}</span>
                  <span style={{fontSize:10, color:'var(--tb-slate)'}}>{wt}%</span>
                </div>
                <div style={{fontSize:10, color:'var(--tb-slate)', lineHeight:1.3, marginTop:1}}>{m.description}</div>
              </div>
              <div>
                <div style={{height:8, background:'var(--tb-border)', borderRadius:4, overflow:'hidden'}}>
                  <div style={{width:`${pct}%`, height:'100%', background:scoreColor(m.score), borderRadius:4}}/>
                </div>
              </div>
              <div style={{fontSize:14, fontWeight:700, color:scoreColor(m.score), textAlign:'right'}}>
                {m.score.toFixed(1)}
              </div>
            </div>
          );
        })}
      </div>

      {/* Confidence note */}
      <div style={{fontSize:12, color:'var(--tb-slate)', lineHeight:1.6, borderTop:'1px solid var(--tb-border)', paddingTop:10}}>
        {note}{directionNote}
      </div>
    </Panel>
  );
}

// ─── Fleet departures ─────────────────────────────────────────────────────────

function getFleetAvailability(trip) {
  const status = (trip.tripStatus || '').toLowerCase();
  const raw    = (trip.tripTypeRaw || '').toLowerCase();
  const note   = (trip.note || '').toLowerCase();
  if (status === 'cancelled') return { label: 'CXL',   type: 'cancelled' };
  if (raw.includes('private') || note.includes('private charter'))
                               return { label: 'PRIV',  type: 'private'   };
  if (!trip.openSpots)         return { label: 'FULL',  type: 'full'      };
  const cap = trip.capacity;
  return { label: cap ? `${trip.openSpots}/${cap}` : `${trip.openSpots} open`, type: 'open' };
}

function FleetDepartures({ date, navigate }) {
  const [showAll, setShowAll] = useS(false);

  const schedule = window.SD?.SCHEDULE || [];
  const dayTrips = schedule.filter(t => (t.departureAt || '').slice(0, 10) === date);
  if (!dayTrips.length) return null;

  const [winRateMap] = useS(() => {
    try { return SDA.boatWinRates() || {}; } catch(e) { return {}; }
  });

  const sorted = [...dayTrips].sort((a, b) => {
    const avA = getFleetAvailability(a);
    const avB = getFleetAvailability(b);
    if (avA.type === 'cancelled' && avB.type !== 'cancelled') return  1;
    if (avB.type === 'cancelled' && avA.type !== 'cancelled') return -1;
    const wA = winRateMap[`${a.boat}|${a.tripLength}`]?.winRate ?? -1;
    const wB = winRateMap[`${b.boat}|${b.tripLength}`]?.winRate ?? -1;
    return wB - wA;
  });

  const todayStr  = new Date().toISOString().slice(0, 10);
  const isToday   = date === todayStr;
  const displayed = showAll ? sorted : sorted.slice(0, 8);

  return (
    <Panel title={isToday ? "Today's Departing Fleet" : `Fleet Departures`}>
      <div className="fc-fleet-note">
        Showing all boats heading out {isToday ? 'today' : 'this day'} — including sold-out and private charters — ranked by historical win rate. Tracking every departure lets us validate predictions against the full fleet.
      </div>
      <div className="fc-fleet-list">
        {displayed.map((trip, i) => {
          const av          = getFleetAvailability(trip);
          const wr          = winRateMap[`${trip.boat}|${trip.tripLength}`];
          const winRatePct  = wr ? Math.round(wr.winRate * 100) : null;
          const timeStr     = (trip.departureAt || '').slice(11, 16);
          const landingShort = (trip.landing || '').replace(' Sportfishing','').replace(' Landing','');
          const isCancelled  = av.type === 'cancelled';
          const isOpen       = av.type === 'open';

          return (
            <div
              key={`${trip.boat}|${trip.departureAt}`}
              className={`fc-fleet-row fc-fleet-${av.type}`}
              onClick={isOpen && navigate ? () => navigate('boat', { boat: trip.boat }) : undefined}
            >
              <div className="fc-fleet-rank">{i + 1}</div>
              <div className="fc-fleet-main">
                <div className={`fc-fleet-boat${isCancelled ? ' fc-fleet-boat-cancelled' : ''}`}>
                  {trip.boat}
                </div>
                <div className="fc-fleet-meta">
                  {landingShort}{trip.tripLength ? ` · ${trip.tripLength}` : ''}{timeStr ? ` · ${timeStr}` : ''}
                </div>
              </div>
              <div className="fc-fleet-win">
                {winRatePct != null
                  ? <Fragment>
                      <span className="fc-fleet-win-pct" style={{ color: scoreColor(winRatePct / 10) }}>
                        {winRatePct}%
                      </span>
                      <span className="fc-fleet-win-label">win</span>
                    </Fragment>
                  : <span className="fc-fleet-win-pct" style={{ color: 'var(--tb-gray-3)' }}>—</span>
                }
              </div>
              <div className="fc-fleet-avail">
                <span className={`fc-fleet-badge fc-fleet-badge-${av.type}`}>{av.label}</span>
                {isOpen && <span className="fc-fleet-arrow">→</span>}
              </div>
            </div>
          );
        })}
      </div>
      {sorted.length > 8 && (
        <button className="fc-fleet-show-more" onClick={() => setShowAll(s => !s)}>
          {showAll ? 'Show fewer ↑' : `+ ${sorted.length - 8} more boats →`}
        </button>
      )}
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

  useE(() => {
    if (!window.TTTrack || !fc?.today) return;
    const s = fc.today.overall_score;
    if (s != null) TTTrack.forecastView('overall', s);
  }, []);

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

      {/* Dual inshore / offshore scores */}
      <DualSegmentWidget fc={fc}/>

      {/* Today's full fleet — all departures regardless of availability */}
      <FleetDepartures date={today.date} navigate={navigate}/>

      {/* Ensemble model comparison */}
      <EnsembleWidget ensemble={fc.ensemble}/>

      {/* Upwelling indicator */}
      <UpwellingWidget upwelling={fc.upwelling}/>

      {/* 7-day strip + selected day detail */}
      {/* TODO: PRO FEATURE — lock for free users later */}
      {days.length > 0 && (
        <Fragment>
          <div style={{marginTop: 16}}>
            <div className="panel-title-inline">7-Day Forecast (Overall)</div>
          </div>
          <SevenDayStrip days={days} selectedIdx={selectedDay} onSelect={setSelectedDay}/>
          <DayDetail day={selDay}/>
          {selDay && selDay.date !== today.date && (
            <FleetDepartures date={selDay.date} navigate={navigate}/>
          )}
        </Fragment>
      )}

      {/* Dual segment 7-day strips */}
      <DualSevenDayStrip fc={fc}/>

      {/* Species cards */}
      <SpeciesGrid day={selDay}/>

      {/* Conditions Like These */}
      {/* TODO: PRO FEATURE — lock for free users later */}
      <HistoricalMatch match={fc.historicalMatch}/>

      {/* SST trend chart */}
      <SSTChart/>

      {/* Accuracy */}
      <AccuracyWidget accuracy={fc.accuracy}/>

      {/* Community signal */}
      {(() => {
        const species = window.SD?.COMMUNITY?.biteReport?.species || [];
        const hot = species.filter(s => s.status === 'hot' || s.status === 'active');
        if (!hot.length) return null;
        return (
          <div className="cm-widget" style={{marginTop:16}}>
            <div className="cm-widget-head">
              <span className="cm-widget-title">Community Signal</span>
              <span className="cm-widget-sub">Reddit fishing reports · last 7 days</span>
            </div>
            <div style={{display:'flex', flexWrap:'wrap', gap:8, paddingTop:8}}>
              {hot.map(s => (
                <div key={s.name} style={{display:'flex', alignItems:'center', gap:6, background:'var(--ss-clay)', borderRadius:6, padding:'5px 10px'}}>
                  <span style={{width:8, height:8, borderRadius:'50%', background: s.status === 'hot' ? '#10B981' : '#FBBF24', display:'inline-block'}}/>
                  <span style={{fontSize:13, fontWeight:600, color:'var(--tb-ink)'}}>{s.name}</span>
                  <span style={{fontSize:11, color:'var(--ss-slate)'}}>{s.status}</span>
                  {s.where && <span style={{fontSize:11, color:'var(--ss-slate)'}}>· {s.where}</span>}
                </div>
              ))}
            </div>
          </div>
        );
      })()}
    </Fragment>
  );
}

Object.assign(window, { ForecastView });
