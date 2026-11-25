// "From BloodyDecks trip reports" panel on the boat page, and the
// "What's working" card on the trip planner.
//
// Data: api/v1/boat_forum_reports.json, written by scraper/paddies/boat_reports.py
// from public BloodyDecks (bdoutdoors.com) trip reports. These are automatic
// summaries of forum posts, NOT verified reviews: we show our one-line
// summary, short quotes and a link to each thread, never the post itself or
// the author's name, and keep them apart from the angler review average.

const { useState: _frUseState, useEffect: _frUseEffect } = React;

const FR_URL = 'api/v1/boat_forum_reports.json';
const FR_MIN_REPORTS = 2;          // one angry (or glowing) post is not a picture of a boat
const FR_SHOW = 4;
const FR_ASPECTS = [
  ['captain', 'Captain'], ['crew', 'Crew'], ['galley', 'Galley'],
  ['bunks', 'Bunks'], ['fish_finding', 'Fish-finding'],
];

let _frPromise = null;
function loadForumReports() {
  if (!_frPromise) {
    _frPromise = fetch(FR_URL, { cache: 'no-cache' })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _frPromise;
}

function useForumReports(boat) {
  const [state, setState] = _frUseState({ loading: true, data: null });
  _frUseEffect(() => {
    let live = true;
    loadForumReports().then(d => { if (live) setState({ loading: false, data: d?.boats?.[boat] || null }); });
    return () => { live = false; };
  }, [boat]);
  return state;
}

function _frDate(iso) {
  if (!iso) return '';
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso);
  return isNaN(d) ? '' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function _frTone(c) {
  // c = {pos, mixed, neg}
  const n = c.pos + c.mixed + c.neg;
  if (!n) return null;
  if (c.pos / n >= 0.7) return 'pos';
  if (c.neg / n >= 0.5) return 'neg';
  return 'mixed';
}

function ForumAspectRow({ aspects }) {
  const items = FR_ASPECTS
    .map(([k, label]) => ({ k, label, c: aspects[k] }))
    .filter(x => x.c && (x.c.pos + x.c.mixed + x.c.neg) > 0);
  if (!items.length) return null;
  return (
    <div className="fr-aspects">
      {items.map(({ k, label, c }) => {
        const tone = _frTone(c);
        const n = c.pos + c.mixed + c.neg;
        const title = `${c.pos} positive, ${c.mixed} mixed, ${c.neg} negative mention${n === 1 ? '' : 's'}`;
        return (
          <span key={k} className={`fr-aspect fr-${tone}`} title={title}>
            {label}
            <span className="fr-aspect-n">
              {tone === 'pos' ? '👍' : tone === 'neg' ? '👎' : '±'} {n}
            </span>
          </span>
        );
      })}
    </div>
  );
}

function ForumReportCard({ r }) {
  const quotes = Object.entries(r.quotes || {})
    .filter(([k]) => k !== 'fish_finding')
    .slice(0, 2);
  const lc = r.landing_count;
  const lcText = lc && lc.catch
    ? Object.entries(lc.catch).filter(([, v]) => v > 0).map(([s, v]) => `${v} ${s}`).join(', ')
    : null;
  return (
    <div className="fr-card">
      <div className="fr-card-head">
        <a className="fr-card-title" href={r.url} target="_blank" rel="noopener noreferrer">{r.title}</a>
        {/* RSS dates are the thread's last activity, so prefer the trip date */}
        {!r.trip_date && <span className="fr-card-date">{_frDate(r.published_at)}</span>}
      </div>
      <div className="fr-card-tags">
        {r.trip_length && <span className="rv-card-tag">{r.trip_length}</span>}
        {r.trip_date && <span className="rv-card-tag">Departed {_frDate(r.trip_date)}</span>}
        {r.would_rebook === true && <span className="rv-card-rebook yes">Would rebook</span>}
        {r.would_rebook === false && <span className="rv-card-rebook no">Wouldn't rebook</span>}
      </div>
      {r.catch_summary && <div className="fr-card-catch">{r.catch_summary}</div>}
      {lc && (
        <div className="fr-card-confirm" title="Matched to the landing's published fish count">
          ✓ Landing count {_frDate(lc.date)}: {lc.anglers} anglers{lcText ? ` · ${lcText}` : ''}
        </div>
      )}
      {quotes.length > 0 && (
        <ul className="fr-quotes">
          {quotes.map(([k, q]) => <li key={k}>“{q}”</li>)}
        </ul>
      )}
      {r.tackle?.length > 0 && (
        <div className="fr-card-tackle"><b>What worked:</b> {r.tackle.slice(0, 3).join(' · ')}</div>
      )}
    </div>
  );
}

function ForumReportsSection({ boat }) {
  const { loading, data } = useForumReports(boat);
  const [showAll, setShowAll] = _frUseState(false);
  if (loading || !data || data.report_count < FR_MIN_REPORTS) return null;

  const reports = showAll ? data.reports : data.reports.slice(0, FR_SHOW);
  const rb = data.rebook || { yes: 0, no: 0 };
  const rbN = rb.yes + rb.no;

  return (
    <div className="fr-section">
      <div className="rv-section-head">
        <div>
          <h2 className="rv-section-title">From BloodyDecks trip reports</h2>
          <div className="rv-section-sub">
            {data.report_count} report{data.report_count === 1 ? '' : 's'} on BloodyDecks in the last year,
            summarised automatically. Not verified reviews: read the originals.
          </div>
        </div>
      </div>

      <div className="fr-summary">
        <ForumAspectRow aspects={data.aspects}/>
        {rbN > 0 && (
          <div className="fr-rebook">{rb.yes} of {rbN} who said so would fish {boat} again</div>
        )}
      </div>

      <div className="fr-list">
        {reports.map(r => <ForumReportCard key={r.url} r={r}/>)}
      </div>
      {data.reports.length > FR_SHOW && (
        <button className="rv-page-btn fr-more" onClick={() => setShowAll(s => !s)}>
          {showAll ? 'Show fewer' : `Show all ${data.reports.length}`}
        </button>
      )}
      <div className="fr-attrib">
        Source: public posts on <a href="https://www.bdoutdoors.com/forums/" target="_blank" rel="noopener noreferrer">BloodyDecks</a>.
        Quotes are excerpts; each card links to the full thread.
      </div>
    </div>
  );
}

// ── "What's working" card (trip planner) ─────────────────────────────────────
// Data: api/v1/whats_working.json — recent tackle / bait / conditions notes per
// trip type, each linked to its BloodyDecks thread.

const WW_URL = 'api/v1/whats_working.json';
const WW_CLASS_LENGTHS = {
  short: ['1/2 Day', '3/4 Day'],
  full: ['Full Day', 'Overnight'],
  multi: ['1.5 Day', '2 Day', '2.5 Day', '3 Day', '3.5 Day'],
  extended: ['4 Day', '5 Day', '6 Day', '7 Day'],
  long_range: ['8 Day', '9 Day', '10 Day', '11 Day', '12 Day', '13 Day', '14 Day', '15 Day', '16 Day'],
};
const WW_SHOW = 3;

let _wwPromise = null;
function loadWhatsWorking() {
  if (!_wwPromise) {
    _wwPromise = fetch(WW_URL, { cache: 'no-cache' })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _wwPromise;
}

function _wwClassFor(lengths) {
  // lengths: 'all' or an array of trip-length labels from the planner filter
  if (!Array.isArray(lengths) || !lengths.length) return null;
  const hits = Object.keys(WW_CLASS_LENGTHS)
    .filter(k => WW_CLASS_LENGTHS[k].some(l => lengths.includes(l)));
  return hits.length === 1 ? hits[0] : null;
}

function WhatsWorkingCard({ lengths }) {
  const [data, setData] = _frUseState(null);
  const [pick, setPick] = _frUseState(null);
  _frUseEffect(() => { let live = true; loadWhatsWorking().then(d => live && setData(d)); return () => { live = false; }; }, []);
  if (!data?.classes) return null;

  const withItems = Object.keys(data.classes).filter(k => data.classes[k].items?.length);
  if (!withItems.length) return null;
  const preferred = _wwClassFor(lengths);
  const key = (pick && withItems.includes(pick)) ? pick
    : (preferred && withItems.includes(preferred)) ? preferred
    : withItems.reduce((a, b) => (data.classes[b].report_count > data.classes[a].report_count ? b : a));
  const c = data.classes[key];

  return (
    <section className="ww-card" aria-label="What's working, from BloodyDecks trip reports">
      <div className="ww-head">
        <div>
          <h3 className="ww-title">What's working</h3>
          <div className="ww-sub">
            From {c.report_count} BloodyDecks trip report{c.report_count === 1 ? '' : 's'} · last {c.window_days} days
          </div>
        </div>
        <div className="ww-tabs" role="tablist">
          {withItems.map(k => (
            <button key={k} role="tab" aria-selected={k === key}
              className={`ww-tab${k === key ? ' active' : ''}`} onClick={() => setPick(k)}>
              {data.classes[k].label}
            </button>
          ))}
        </div>
      </div>
      {c.top_spots?.length > 0 && (
        <div className="ww-spots"><b>Where:</b> {c.top_spots.join(' · ')}</div>
      )}
      <ul className="ww-list">
        {c.items.slice(0, WW_SHOW).map(it => (
          <li key={it.url + (it.boat || '')} className="ww-item">
            <div className="ww-item-head">
              <span className="ww-item-boat">{it.boat || 'Party boat'}</span>
              <span className="ww-item-meta">
                {[it.trip_length, it.trip_date && _frDate(it.trip_date)].filter(Boolean).join(' · ')}
              </span>
            </div>
            {it.tackle?.length > 0 && (
              <div className="ww-chips">{it.tackle.map((t, i) => <span key={i} className="ww-chip">{t}</span>)}</div>
            )}
            {it.bait && <div className="ww-line"><b>Bait:</b> {it.bait}</div>}
            {it.conditions && <div className="ww-line"><b>Conditions:</b> {it.conditions}</div>}
            <a className="ww-link" href={it.url} target="_blank" rel="noopener noreferrer">Read the report →</a>
          </li>
        ))}
      </ul>
      <div className="fr-attrib">
        Automatic summaries of public posts on <a href="https://www.bdoutdoors.com/forums/" target="_blank" rel="noopener noreferrer">BloodyDecks</a>.
      </div>
    </section>
  );
}

Object.assign(window, { ForumReportsSection, loadForumReports, WhatsWorkingCard, loadWhatsWorking });
