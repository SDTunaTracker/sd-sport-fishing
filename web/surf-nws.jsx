// surf-nws.jsx: NWS San Diego surf commentary for Surftracker, shown verbatim.
// - SurfNwsAlerts: banner for active surf and coastal alerts (top of every tab)
// - SurfNwsNotes:  the forecaster's .BEACHES notes from the Area Forecast Discussion
// Data: surf.json nwsAlerts / nwsNotes (src/surf/nws.py). NWS text is public
// domain; we quote it as issued and credit the National Weather Service San Diego.
// NWS surf heights are breaking surf, the same measure as ours.

const { useState: useNwsState } = React;

function nwsWhen(iso, opts) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('en-US', Object.assign({ timeZone: 'America/Los_Angeles' }, opts));
  } catch (e) { return ''; }
}

const NWS_LEVEL_LABEL = { warning: 'Warning', advisory: 'Advisory', watch: 'Watch', statement: 'Statement' };

function SurfNwsAlert({ a }) {
  const [open, setOpen] = useNwsState(false);
  const until = nwsWhen(a.until, { weekday: 'short', hour: 'numeric', minute: '2-digit' });
  return (
    <div className={`sfa sfa-${a.level}`} role="region" aria-label={`NWS ${a.event}`}>
      <div className="sfa-top">
        <span className="sfa-badge">{NWS_LEVEL_LABEL[a.level] || 'Alert'}</span>
        <b className="sfa-event">{a.event}</b>
        {until && <span className="sfa-until">until {until}</span>}
        <button type="button" className="sfa-more" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Hide details' : 'Details'}
        </button>
      </div>
      {a.headline && <div className="sfa-head">{a.headline}</div>}
      {open && (
        <div className="sfa-body">
          {a.description && <p className="sfa-text">{a.description}</p>}
          {a.instruction && <p className="sfa-text">{a.instruction}</p>}
          <p className="sfa-src">Source: National Weather Service San Diego. Shown as issued.</p>
        </div>
      )}
    </div>
  );
}

function SurfNwsAlerts({ alerts }) {
  const now = Date.now();
  const live = (alerts || []).filter(a => !a.until || Date.parse(a.until) > now);
  if (!live.length) return null;
  return (
    <div className="sf-wrap sfa-wrap" aria-label="National Weather Service surf alerts">
      {live.map(a => <SurfNwsAlert key={a.event + (a.until || '')} a={a}/>)}
    </div>
  );
}

function SurfNwsNotes({ notes }) {
  if (!notes || !notes.paragraphs || !notes.paragraphs.length) return null;
  const issued = nwsWhen(notes.issued, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  return (
    <section className="sfn" aria-label="NWS forecaster notes">
      <div className="sfn-h">NWS forecaster notes · Beaches</div>
      {notes.paragraphs.map((p, i) => <p key={i} className="sfn-p">{p}</p>)}
      <div className="sfn-src">
        {issued ? `Issued ${issued}. ` : ''}Source: National Weather Service San Diego, Area Forecast Discussion, shown as issued.
        {' '}Heights are breaking surf.{' '}
        {notes.url && <a href={notes.url} target="_blank" rel="noopener">Full discussion ↗</a>}
      </div>
    </section>
  );
}

window.SurfNwsAlerts = SurfNwsAlerts;
window.SurfNwsNotes = SurfNwsNotes;
