// surf-report.jsx: Surftracker's written surf and paddle report (auto-generated).
// - SurfAutoReport  (Report tab): today's report, one line per region, paddle note
// - SurfAutoOutlook (Forecast tab): the 3–5 day outlook
// Data: /api/v1/surf_report.json (src/surf/report.py). Written automatically from
// Surftracker's own forecast and NWS data; every number is fact-checked against
// the forecast before it is published. Heights are breaking face height.

const { useState: useSrState, useEffect: useSrEffect } = React;

let srCache = null;
let srPending = null;
function useSurfAutoReport() {
  const [rep, setRep] = useSrState(srCache);
  useSrEffect(() => {
    if (srCache) return;
    const hour = new Date().toISOString().slice(0, 13);
    srPending = srPending || fetch('/api/v1/surf_report.json?h=' + hour)
      .then(r => (r.ok ? r.json() : null)).catch(() => null);
    let live = true;
    srPending.then(j => { srCache = j; if (live) setRep(j); });
    return () => { live = false; };
  }, []);
  if (!rep || !rep.today || !rep.generatedAt) return null;
  const ageH = (Date.now() - Date.parse(rep.generatedAt)) / 3600000;
  return ageH > (rep.staleAfterHours || 8) ? null : rep;
}

// "6:05 AM" today, "Fri 6:05 AM" otherwise (Pacific time).
function srWhen(iso) {
  try {
    const tz = { timeZone: 'America/Los_Angeles' };
    const d = new Date(iso);
    const day = x => x.toLocaleDateString('en-US', tz);
    const opts = Object.assign({ hour: 'numeric', minute: '2-digit' }, tz,
      day(d) === day(new Date()) ? {} : { weekday: 'short' });
    return d.toLocaleString('en-US', opts);
  } catch (e) { return ''; }
}

// Sentences: split after ". " followed by a capital (keeps "7.3 ft" whole).
function srSentences(text) {
  const out = [];
  let cur = '';
  const s = String(text || '');
  for (let i = 0; i < s.length; i++) {
    cur += s[i];
    if (s[i] === '.' && s[i + 1] === ' ' && /[A-Z]/.test(s[i + 2] || '')) { out.push(cur.trim()); cur = ''; }
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

function SurfAutoSrc({ rep }) {
  return (
    <div className="sfr-src">Auto-written from Surftracker's forecast and NWS data · {srWhen(rep.generatedAt)}</div>
  );
}

function SurfAutoReport() {
  const rep = useSurfAutoReport();
  const [open, setOpen] = useSrState(false);
  if (!rep) return null;
  const label = rep.covers === 'tomorrow' ? `Surf report · ${rep.reportDay}` : 'Surf report · Today';
  // Collapsed (default): headline + the first two sentences. Expanded: all of it.
  const sents = srSentences(rep.today);
  const short = sents.slice(0, 2).join(' ');
  const more = sents.length > 2 || rep.paddle || (rep.regions && rep.regions.length);
  return (
    <section className="sfr" aria-label="Surf report">
      <div className="sfr-h">{label}</div>
      {rep.headline && <p className="sfr-head">{rep.headline}</p>}
      <p className="sfr-p">{open ? rep.today : short}</p>
      {open && rep.paddle && <p className="sfr-p sfr-paddle"><b>Paddle:</b> {rep.paddle}</p>}
      {open && rep.regions && rep.regions.length > 0 && (
        <ul className="sfr-regions" aria-label="By region">
          {rep.regions.map(r => <li key={r.region}><b>{r.region}</b> {r.line}</li>)}
        </ul>
      )}
      {more && (
        <button type="button" className="sfr-more" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Less' : 'More'}
        </button>
      )}
      <SurfAutoSrc rep={rep}/>
    </section>
  );
}

function SurfAutoOutlook() {
  const rep = useSurfAutoReport();
  const [open, setOpen] = useSrState(false);
  if (!rep || !rep.outlook) return null;
  const sents = srSentences(rep.outlook);
  return (
    <section className="sfr" aria-label="Surf outlook">
      <div className="sfr-h">Outlook · next 5 days</div>
      <p className="sfr-p">{open ? rep.outlook : sents.slice(0, 2).join(' ')}</p>
      {sents.length > 2 && (
        <button type="button" className="sfr-more" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Less' : 'More'}
        </button>
      )}
      <SurfAutoSrc rep={rep}/>
    </section>
  );
}

window.SurfAutoReport = SurfAutoReport;
window.SurfAutoOutlook = SurfAutoOutlook;
