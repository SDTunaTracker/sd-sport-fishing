// Shared UI primitives: header, sidenav, charts, formatting helpers
const SPECIES_COLORS = {
  Bluefin:   '#1F4E8F',
  Yellowfin: '#FFBA30',
  Yellowtail: '#1E9B6B',
  Dorado:    '#3DD1A4',
  Skipjack:  '#FF7705',
  Bigeye:    '#5F2E8F',
  Albacore:  '#99D6EF',
};
// The 4 species that count toward "trophy fish" per the project spec.
const TROPHY_SPECIES = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];

const fmt = {
  n: (v, d=0) => (v == null || isNaN(v) ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })),
  pct: (v, d=0) => (v == null || isNaN(v) ? '—' : `${(v * 100).toFixed(d)}%`),
  tpa: (v) => (v == null || isNaN(v) ? '—' : v.toFixed(2)),
  date: (s) => {
    const d = new Date(s + 'T00:00:00');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  },
};

const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function AppHeader({ active, onNavigate }) {
  const [menuState, setMenuState] = React.useState('closed'); // 'closed' | 'open' | 'closing'

  const NAV = [
    { id: 'today',       label: 'Today',              icon: 'fa-chart-column' },
    { id: 'forecast',    label: 'Forecast',           icon: 'fa-cloud-sun-rain' },
    { id: 'analytics',   label: 'Analytics',          icon: 'fa-magnifying-glass-chart' },
    { id: 'tripplanner', label: 'Trip Planner',       icon: 'fa-calendar-check' },
    { id: 'seasonality', label: 'Seasonality & Moon', icon: 'fa-calendar-days' },
  ];

  function openMenu() { setMenuState('open'); }

  function closeMenu() {
    setMenuState('closing');
    window.setTimeout(() => setMenuState(s => s === 'closing' ? 'closed' : s), 220);
  }

  function handleNavItem(id) {
    setMenuState('closed');
    onNavigate && onNavigate(id);
  }

  const menuVisible = menuState !== 'closed';
  const menuClosing = menuState === 'closing';

  return (
    <React.Fragment>
      <div className="app-header">
        <div className="header-top">
          {/* Logo: fish icon + wordmark */}
          <div className="logo" onClick={() => handleNavItem('today')} style={{cursor:'pointer'}}>
            <i className="fa-solid fa-fish-fins logo-fish"></i>
            <span className="logo-wordmark">The Tuna Tracker</span>
          </div>
          {/* Nav tabs — desktop only */}
          <div className="header-nav">
            {NAV.map(t => (
              <div key={t.id}
                   className={`tab${active === t.id ? ' sel' : ''}`}
                   onClick={() => handleNavItem(t.id)}>
                <i className={`fa-solid ${t.icon}`}></i>{t.label}
              </div>
            ))}
          </div>
          {/* Gear icon */}
          <span className="header-gear iconbtn" title="Settings"
                onClick={() => handleNavItem('settings')}
                style={{color: active === 'settings' ? 'var(--tb-ink)' : 'var(--tb-slate)'}}>
            <i className="fa-solid fa-gear"></i>
          </span>
          {/* Hamburger: mobile only */}
          <span className="header-hamburger iconbtn" title="Menu"
                onClick={() => menuState === 'open' ? closeMenu() : openMenu()}>
            <i className={`fa-solid ${menuState === 'open' ? 'fa-xmark' : 'fa-bars'}`}></i>
          </span>
        </div>
      </div>

      {/* Mobile slide-in nav panel */}
      {menuVisible && (
        <div className={`mobile-menu-overlay${menuClosing ? ' closing' : ''}`}
             onClick={closeMenu}>
          <div className="mobile-menu" onClick={e => e.stopPropagation()}>
            <div className="mobile-menu-head">
              <div className="mm-logo">
                <i className="fa-solid fa-fish-fins" style={{color:'var(--tb-lime)'}}></i>
                <span>The Tuna Tracker</span>
              </div>
              <span className="mm-close" onClick={closeMenu}>
                <i className="fa-solid fa-xmark"></i>
              </span>
            </div>
            {NAV.map(t => (
              <div key={t.id}
                   className={`mobile-menu-item${active === t.id ? ' sel' : ''}`}
                   onClick={() => handleNavItem(t.id)}>
                <i className={`fa-solid ${t.icon}`}></i>
                <span>{t.label}</span>
              </div>
            ))}
            <div className="mobile-menu-divider"></div>
            <div className={`mobile-menu-item${active === 'settings' ? ' sel' : ''}`}
                 onClick={() => handleNavItem('settings')}>
              <i className="fa-solid fa-gear"></i>
              <span>Settings</span>
            </div>
          </div>
        </div>
      )}
    </React.Fragment>
  );
}

function SideNav({ active, onNavigate }) {
  const items = [
    { group: 'Analyze' },
    { id: 'today', label: 'Today', icon: 'fa-chart-column' },
    { id: 'analytics', label: 'Analytics', icon: 'fa-magnifying-glass-chart' },
    { id: 'boats', label: 'Boat Leaderboard', icon: 'fa-sailboat' },
    { id: 'landings', label: 'Landings', icon: 'fa-anchor' },
    { id: 'headtohead', label: 'Head-to-Head', icon: 'fa-scale-balanced' },
    { id: 'seasonality', label: 'Seasonality', icon: 'fa-calendar-days' },
    { id: 'moon', label: 'Moon & Tides', icon: 'fa-moon' },
    { group: 'Plan' },
    { id: 'tripplanner', label: 'Trip Planner', icon: 'fa-calendar-check' },
    { group: 'My Stuff' },
    { id: 'watchlist', label: 'Watchlist', icon: 'fa-bookmark' },
    { id: 'recent', label: 'Recent', icon: 'fa-clock-rotate-left' },
    { group: 'Admin' },
    { id: 'settings', label: 'Settings', icon: 'fa-gear' },
  ];
  return (
    <aside className="sidenav">
      {items.map((it, i) => it.group
        ? <div key={i} className="group">{it.group}</div>
        : (
          <div key={it.id}
               className={`sideitem${active === it.id ? ' sel' : ''}`}
               onClick={() => onNavigate && onNavigate(it.id)}>
            <i className={`fa-solid ${it.icon}`}></i>{it.label}
          </div>
        )
      )}
    </aside>
  );
}

function Crumbs({ items, onNav }) {
  return (
    <div className="crumbs">
      {items.map((it, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="sep">›</span>}
          {it.onClick
            ? <span className="lk" onClick={it.onClick}>{it.label}</span>
            : <b>{it.label}</b>}
        </React.Fragment>
      ))}
    </div>
  );
}

function KPI({ label, value, unit, delta, deltaLabel, ctx, accent }) {
  const positive = delta == null ? null : delta >= 0;
  return (
    <div className="kpi">
      <div className="k">{label}</div>
      <div className="v" style={accent ? { color: accent } : null}>
        {value}{unit && <span className="u">{unit}</span>}
        {delta != null && (
          <span className={`d${!positive ? ' neg' : ''}`}>
            <i className={`fa-solid ${positive ? 'fa-arrow-up' : 'fa-arrow-down'}`}></i>
            {Math.abs(delta).toFixed(1)}% {deltaLabel}
          </span>
        )}
      </div>
      {ctx && <div className="ctx">{ctx}</div>}
    </div>
  );
}

function Panel({ title, meta, actions, children, padding = true, className = '' }) {
  return (
    <div className={`panel${className ? ' ' + className : ''}`}>
      <div className="phead">
        <div>
          <h3>{title}</h3>
          {meta && <div className="meta">{meta}</div>}
        </div>
        <div className="actions">
          {meta && !title && <span className="meta">{meta}</span>}
          {actions}
        </div>
      </div>
      <div style={padding ? null : {padding: 0}} className={padding ? 'pbody' : ''}>{children}</div>
    </div>
  );
}

// ─── Tiny SVG charts ────────────────────────────────
function Sparkline({ values, width = 80, height = 24, color = '#008566', fill = true }) {
  if (!values || values.length === 0) return null;
  const max = Math.max(...values, 0.001);
  const min = Math.min(...values, 0);
  const range = (max - min) || 1;
  const dx = width / (values.length - 1 || 1);
  const points = values.map((v, i) => `${i*dx},${height - ((v - min)/range)*height}`).join(' ');
  const area = `0,${height} ${points} ${width},${height}`;
  return (
    <svg className="spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {fill && <polygon points={area} fill={color} fillOpacity="0.12"/>}
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5"/>
    </svg>
  );
}

function VBarChart({ data, width = 720, height = 240, color = '#008566', valueKey = 'value', labelKey = 'label', formatY = (v) => v }) {
  const padL = 40, padR = 12, padT = 12, padB = 28;
  const w = width - padL - padR;
  const h = height - padT - padB;
  const max = Math.max(...data.map(d => d[valueKey]), 0.001);
  const bw = w / data.length;
  const grid = 4;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {[...Array(grid+1)].map((_, i) => {
        const y = padT + (h * i / grid);
        const v = max * (1 - i/grid);
        return (
          <g key={i}>
            <line x1={padL} y1={y} x2={padL + w} y2={y} stroke="#EDEDED" strokeWidth="1"/>
            <text x={padL - 6} y={y + 3} textAnchor="end" fontSize="9" fill="#90979F" fontFamily="var(--ss-font-sans)">
              {formatY(v)}
            </text>
          </g>
        );
      })}
      {data.map((d, i) => {
        const v = d[valueKey];
        const bh = (v / max) * h;
        const x = padL + i * bw + 3;
        const y = padT + h - bh;
        return (
          <g key={i}>
            <rect x={x} y={y} width={bw - 6} height={bh} fill={d.color || color} rx="2"/>
            <text x={x + (bw-6)/2} y={padT + h + 14} textAnchor="middle" fontSize="10" fill="#445460" fontFamily="var(--ss-font-sans)">
              {d[labelKey]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function StackedBarChart({ data, series, width = 720, height = 240, formatY = (v) => v }) {
  const padL = 40, padR = 12, padT = 12, padB = 28;
  const w = width - padL - padR;
  const h = height - padT - padB;
  const max = Math.max(...data.map(d => series.reduce((s, k) => s + (d[k] || 0), 0)), 0.001);
  const bw = w / data.length;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {[0,1,2,3,4].map(i => {
        const y = padT + (h * i / 4);
        const v = max * (1 - i/4);
        return (
          <g key={i}>
            <line x1={padL} y1={y} x2={padL + w} y2={y} stroke="#EDEDED" strokeWidth="1"/>
            <text x={padL - 6} y={y + 3} textAnchor="end" fontSize="9" fill="#90979F">{formatY(v)}</text>
          </g>
        );
      })}
      {data.map((d, i) => {
        const x = padL + i * bw + 3;
        let acc = 0;
        return (
          <g key={i}>
            {series.map((k) => {
              const v = d[k] || 0;
              const bh = (v / max) * h;
              const y = padT + h - acc - bh;
              acc += bh;
              return <rect key={k} x={x} y={y} width={bw - 6} height={bh} fill={SPECIES_COLORS[k] || '#008566'}/>;
            })}
            <text x={x + (bw-6)/2} y={padT + h + 14} textAnchor="middle" fontSize="10" fill="#445460">{d.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

function LineChart({ data, valueKey = 'value', labelKey = 'label', width = 720, height = 240, color = '#008566', formatY = (v) => v }) {
  const padL = 40, padR = 12, padT = 12, padB = 28;
  const w = width - padL - padR;
  const h = height - padT - padB;
  const max = Math.max(...data.map(d => d[valueKey]), 0.001);
  const dx = w / (data.length - 1 || 1);
  const pts = data.map((d, i) => [padL + i * dx, padT + h - (d[valueKey] / max) * h]);
  const ptsStr = pts.map(p => p.join(',')).join(' ');
  const area = `${pts[0][0]},${padT+h} ${ptsStr} ${pts[pts.length-1][0]},${padT+h}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {[0,1,2,3,4].map(i => {
        const y = padT + (h * i / 4);
        const v = max * (1 - i/4);
        return (
          <g key={i}>
            <line x1={padL} y1={y} x2={padL + w} y2={y} stroke="#EDEDED"/>
            <text x={padL - 6} y={y + 3} textAnchor="end" fontSize="9" fill="#90979F">{formatY(v)}</text>
          </g>
        );
      })}
      <polygon points={area} fill={color} fillOpacity="0.10"/>
      <polyline points={ptsStr} stroke={color} strokeWidth="2" fill="none"/>
      {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="2.5" fill="#fff" stroke={color} strokeWidth="1.5"/>)}
      {data.map((d, i) => (
        <text key={i} x={padL + i*dx} y={padT + h + 14} textAnchor="middle" fontSize="10" fill="#445460">{d[labelKey]}</text>
      ))}
    </svg>
  );
}

function Donut({ data, size = 160, thickness = 26 }) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const r = size / 2 - thickness / 2;
  const cx = size / 2, cy = size / 2;
  let acc = 0;
  const arcs = data.map((d, i) => {
    const a0 = (acc / total) * Math.PI * 2 - Math.PI / 2;
    acc += d.value;
    const a1 = (acc / total) * Math.PI * 2 - Math.PI / 2;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    return <path key={i} d={`M${x0},${y0} A${r},${r} 0 ${large} 1 ${x1},${y1}`} stroke={d.color} strokeWidth={thickness} fill="none"/>;
  });
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cy} r={r} stroke="var(--ss-clay)" strokeWidth={thickness} fill="none"/>
      {arcs}
    </svg>
  );
}

// Moon glyph
function MoonGlyph({ phase, size = 36 }) {
  const map = {
    'New': 'shape-new', 'Waxing Crescent': 'shape-waxc', 'First Quarter': 'shape-firstq',
    'Waxing Gibbous': 'shape-waxg', 'Full': 'shape-full', 'Waning Gibbous': 'shape-wang',
    'Last Quarter': 'shape-lastq', 'Waning Crescent': 'shape-wanc',
  };
  return (
    <div className={`glyph ${map[phase]}`} style={{ width: size, height: size }}>
      <div className="lit"></div>
    </div>
  );
}

Object.assign(window, {
  SPECIES_COLORS, fmt, MONTH_NAMES,
  AppHeader, SideNav, Crumbs, KPI, Panel,
  Sparkline, VBarChart, StackedBarChart, LineChart, Donut, MoonGlyph,
});
