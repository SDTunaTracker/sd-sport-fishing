// "Bait at the barge" from the Everingham Bros. Bait Co. Bait Report.
//
// Data path: Everingham's published Google Sheet -> src/bait.py (hourly, only
// when the repo variable BAIT_REPORT_ENABLED is 'true') -> api/v1/bait_now.json.
//
// Display rules:
//   * always credit Everingham with a link to baitbarge.com
//   * show their "As of" time and their note that bait changes during the day
//   * hide the line once the barge's report is older than staleAfterHours
//   * it says what the barge is serving, not what a given boat loaded
//
// Gated by window.FEATURES.SHOW_BAIT_NOW (preview: ?preview_bait=true).

const { useState: _bnUseState, useEffect: _bnUseEffect } = React;

const BN_URL = 'api/v1/bait_now.json';

let _bnPromise = null;
function loadBaitNow() {
  if (!_bnPromise) {
    _bnPromise = fetch(BN_URL, { cache: 'no-cache' })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _bnPromise;
}

function bnBargeFor(data, landing) {
  if (!data || !Array.isArray(data.barges) || !landing) return null;
  const b = data.barges.find(x => Array.isArray(x.landings) && x.landings.includes(landing));
  if (!b || !b.bait) return null;
  // Re-check age in the browser: the JSON can sit unchanged for days if the job stops.
  const ref = Date.parse(b.asOf || b.checkedAt || '');
  const maxH = data.staleAfterHours || 24;
  if (b.stale || !isFinite(ref) || (Date.now() - ref) / 36e5 > maxH) return null;
  return b;
}

function useBaitNow() {
  const on = !!window.FEATURES?.SHOW_BAIT_NOW;
  const [data, setData] = _bnUseState(null);
  _bnUseEffect(() => {
    if (!on) return;
    let live = true;
    loadBaitNow().then(d => { if (live) setData(d); });
    return () => { live = false; };
  }, [on]);
  return on ? data : null;
}

function bnAsOf(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const opts = { timeZone: 'America/Los_Angeles' };
  const day = d.toLocaleDateString('en-US', { ...opts, weekday: 'short' });
  const time = d.toLocaleTimeString('en-US', { ...opts, hour: 'numeric', minute: '2-digit' });
  const today = new Date().toLocaleDateString('en-US', { ...opts, weekday: 'short' });
  return day === today ? time : `${day} ${time}`;
}

// One line for trip cards. Renders nothing when off, missing or stale.
function BaitNowLine({ landing }) {
  const data = useBaitNow();
  const b = bnBargeFor(data, landing);
  if (!b) return null;
  const src = data.source || {};
  return (
    <div className="bn-line" title={data.note || ''}>
      <span className="bn-ico" aria-hidden="true">🐟</span>
      <span>Barge bait: <b>{b.bait}</b></span>
      {b.asOf && <span className="bn-asof"> · as of {bnAsOf(b.asOf)}</span>}
      <a className="bn-credit" href={src.url || 'https://baitbarge.com/'} target="_blank" rel="noopener"
         onClick={e => e.stopPropagation()}>Everingham</a>
    </div>
  );
}

// Panel for landing pages.
function BaitNowPanel({ landing }) {
  const data = useBaitNow();
  const b = bnBargeFor(data, landing);
  if (!b) return null;
  const src = data.source || {};
  return (
    <section className="bn-panel">
      <div className="bn-head">
        <h3>Live bait at the {b.name} barge</h3>
        {b.asOf && <span className="bn-asof">As of {bnAsOf(b.asOf)}</span>}
      </div>
      <div className="bn-bait">{b.bait}</div>
      <p className="bn-note">
        {data.note || 'Bait can change during the day.'} This is what the barge is serving, not what each boat loaded.
        Ask the deckhand what's working.
      </p>
      <div className="bn-src">
        Source: <a href={src.url || 'https://baitbarge.com/'} target="_blank" rel="noopener">{src.name || 'Everingham Bros. Bait Co.'}</a>
        {src.phone && <span> · {src.phone}</span>}
      </div>
    </section>
  );
}

Object.assign(window, { BaitNowLine, BaitNowPanel, loadBaitNow, bnBargeFor });
