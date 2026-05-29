// Reusable metric label with hover/tap ⓘ tooltip.
// Usage: <MetricLabel {...METRIC_DEFINITIONS.winRate} />
//        <MetricLabel name="Win Rate" tooltip="..." />
function MetricLabel({ name, tooltip, learnMoreLink }) {
  const [show, setShow] = React.useState(false);
  const ref = React.useRef(null);

  React.useEffect(() => {
    if (!show) return;
    function onTap(e) {
      if (!ref.current?.contains(e.target)) setShow(false);
    }
    document.addEventListener('mousedown', onTap);
    return () => document.removeEventListener('mousedown', onTap);
  }, [show]);

  return (
    <span
      ref={ref}
      className="metric-label"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {name}
      <button
        className="metric-info-icon"
        onClick={e => { e.stopPropagation(); setShow(s => !s); }}
        aria-label={`What is ${name}?`}
      >ⓘ</button>
      {show && (
        <div className="metric-tooltip">
          <div className="metric-tooltip-title">{name}</div>
          <div className="metric-tooltip-body">{tooltip}</div>
          {learnMoreLink && (
            <a href={learnMoreLink} className="metric-tooltip-link" onClick={e => e.stopPropagation()}>
              Learn more →
            </a>
          )}
        </div>
      )}
    </span>
  );
}
window.MetricLabel = MetricLabel;

// Compact tier badge for top-performer rate.
// tier: 'top' | 'strong' | 'solid' | 'developing'
// pct: optional numeric 0–1 to show alongside icon
function TopPerformerBadge({ tier, pct, style }) {
  if (!tier) return null;
  const cfg = {
    top:        { icon: '⭐', label: 'Top Performer',  cls: 'tp-tier-top' },
    strong:     { icon: '🔥', label: 'Strong',          cls: 'tp-tier-strong' },
    solid:      { icon: '✓',  label: 'Solid',           cls: 'tp-tier-solid' },
    developing: { icon: '○',  label: 'Developing',      cls: 'tp-tier-developing' },
  }[tier] || { icon: '—', label: tier, cls: '' };
  return (
    <span className={`tp-tier-badge ${cfg.cls}`} title={cfg.label} style={style}>
      <span className="tp-tier-icon">{cfg.icon}</span>
      {pct != null && <span className="tp-tier-pct">{Math.round(pct * 100)}%</span>}
    </span>
  );
}
window.TopPerformerBadge = TopPerformerBadge;
