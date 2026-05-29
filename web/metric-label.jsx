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
