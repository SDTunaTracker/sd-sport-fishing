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
const FR_TONE_WORD = { pos: 'Mostly positive', mixed: 'Mixed', neg: 'Mostly negative' };

function ForumAspectRow({ aspects }) {
  const items = FR_ASPECTS
    .map(([k, label]) => ({ k, label, c: aspects[k] }))
    .filter(x => x.c && (x.c.pos + x.c.mixed + x.c.neg) > 0);
  if (!items.length) return null;
  return (
    <ul className="fr-aspects" aria-label="What reports said, by topic">
      {items.map(({ k, label, c }) => {
        const tone = _frTone(c);
        const n = c.pos + c.mixed + c.neg;
        const title = `${c.pos} positive, ${c.mixed} mixed, ${c.neg} negative mention${n === 1 ? '' : 's'}`;
        return (
          <li key={k} className="fr-aspect" title={title}>
            <span className="fr-aspect-label">{label}</span>
            <span className={`fr-aspect-tone fr-${tone}`}>
              <i className="fr-dot" aria-hidden="true"/>{FR_TONE_WORD[tone]}
              <span className="fr-aspect-n"> · {n}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// BloodyDecks photos are full-size originals with no public thumbnail, so
// we link to the post rather than embedding them.
function FrPhotoLink({ n, url, short }) {
  if (!n || !url) return null;
  const label = `${n} photo${n === 1 ? '' : 's'}`;
  return (
    <a className="fr-photos-link" href={url} target="_blank" rel="noopener noreferrer">
      <span aria-hidden="true">📷 </span>{short ? label : `${label} on BloodyDecks`}<span aria-hidden="true"> ↗</span>
      <span className="sr-only">{short ? ' on BloodyDecks (new tab)' : ' (new tab)'}</span>
    </a>
  );
}

function ForumReportCard({ r }) {
  const quotes = Object.entries(r.quotes || {})
    .filter(([k]) => k !== 'fish_finding')
    .slice(0, 2);
  const lc = r.landing_count;
  const lcText = lc && lc.catch
    ? Object.entries(lc.catch).filter(([, v]) => v > 0).map(([s, v]) => `${v} ${s.toLowerCase()}`).join(', ')
    : null;
  // RSS dates are the thread's last activity, so prefer the trip date
  const when = r.trip_date ? `Departed ${_frDate(r.trip_date)}` : `Posted ${_frDate(r.published_at)}`;
  return (
    <li className="fr-card">
      <div className="fr-card-meta">
        {[r.trip_length, when].filter(Boolean).join(' · ')}
        {r.would_rebook === true && <span className="fr-rb fr-rb-yes"> · Would rebook</span>}
        {r.would_rebook === false && <span className="fr-rb fr-rb-no"> · Wouldn't rebook</span>}
      </div>
      <a className="fr-card-title" href={r.url} target="_blank" rel="noopener noreferrer">
        {r.title}<span className="fr-ext" aria-hidden="true"> ↗</span>
        <span className="sr-only"> (opens BloodyDecks in a new tab)</span>
      </a>
      {r.catch_summary && <p className="fr-card-catch">{r.catch_summary}</p>}
      {lc && (
        <div className="fr-card-confirm" title="Matched to the landing's published fish count">
          <span aria-hidden="true">✓</span> Matches the landing count for {_frDate(lc.date)}: {lc.anglers} anglers{lcText ? `, ${lcText}` : ''}
        </div>
      )}
      {quotes.length > 0 && (
        <div className="fr-quotes">
          {quotes.map(([k, q]) => <blockquote key={k}>“{q}”</blockquote>)}
        </div>
      )}
      {r.tackle?.length > 0 && (
        <div className="fr-card-tackle">
          <span className="fr-k">What worked</span>
          {r.tackle.slice(0, 3).map((t, i) => <span key={i} className="fr-chip">{t}</span>)}
        </div>
      )}
      <FrPhotoLink n={r.photos} url={r.url}/>
    </li>
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
    <section className="fr-section" aria-labelledby="fr-title">
      <div className="fr-eyebrow">From the forums</div>
      <h2 className="fr-title" id="fr-title">BloodyDecks trip reports</h2>
      <p className="fr-sub">
        {data.report_count} report{data.report_count === 1 ? '' : 's'} about {boat} in the last year, summarized automatically.
        These aren't verified reviews and don't count toward the rating. Each one links to the original thread.
      </p>

      <div className="fr-summary">
        {rbN > 0 && (
          <div className="fr-rebook">
            <b>{rb.yes}<small> of {rbN}</small></b>
            <span>would fish {boat} again</span>
          </div>
        )}
        <ForumAspectRow aspects={data.aspects}/>
      </div>

      <ul className="fr-list">
        {reports.map(r => <ForumReportCard key={r.url} r={r}/>)}
      </ul>
      {data.reports.length > FR_SHOW && (
        <button className="fr-more" onClick={() => setShowAll(s => !s)} aria-expanded={showAll}>
          {showAll ? 'Show fewer reports' : `Show all ${data.reports.length} reports`}
        </button>
      )}
      <p className="fr-attrib">
        Source: public posts on <a href="https://www.bdoutdoors.com/forums/" target="_blank" rel="noopener noreferrer">BloodyDecks</a>.
        Quotes are short excerpts.
      </p>
    </section>
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

// The site's selected region -> which block of whats_working.json to show.
// One region selected: that region's reports (incl. ones tagged "both"), and
// nothing at all if the file has no block for it (older cached JSON) - never
// another region's tips. SD + OC/LA together (or no region info): every report.
function _wwClassesFor(data, regions) {
  const eff = (regions && window.getEffectiveRegion) ? window.getEffectiveRegion(regions) : 'all_socal';
  if (eff === 'all_socal') return data.classes;
  return (data.by_region && data.by_region[eff]) || {};
}

function WhatsWorkingCard({ lengths, regions }) {
  const [data, setData] = _frUseState(null);
  const [pick, setPick] = _frUseState(null);
  _frUseEffect(() => { let live = true; loadWhatsWorking().then(d => live && setData(d)); return () => { live = false; }; }, []);
  if (!data?.classes) return null;
  const classes = _wwClassesFor(data, regions);

  const withItems = Object.keys(classes).filter(k => classes[k].items?.length);
  if (!withItems.length) return null;
  const preferred = _wwClassFor(lengths);
  const key = (pick && withItems.includes(pick)) ? pick
    : (preferred && withItems.includes(preferred)) ? preferred
    : withItems.reduce((a, b) => (classes[b].report_count > classes[a].report_count ? b : a));
  const c = classes[key];
  const shown = c.items.slice(0, WW_SHOW);
  const hasLanding = shown.some(it => it.source === 'landing');
  const hasForum = shown.some(it => it.source !== 'landing');

  return (
    <section className="ww-card" aria-labelledby="ww-title">
      <div className="ww-top">
        <div>
          <div className="fr-eyebrow">
            {hasLanding && hasForum ? 'From landing reports and BloodyDecks'
              : hasLanding ? "From the landings' reports" : 'From BloodyDecks trip reports'}
          </div>
          <h3 className="ww-title" id="ww-title">What's working</h3>
          <p className="ww-sub">
            {c.report_count} report{c.report_count === 1 ? '' : 's'} · last {c.window_days} days
            {c.top_spots?.length > 0 && <> · Where: <span className="ww-spots">{c.top_spots.join(', ')}</span></>}
          </p>
        </div>
        <div className="ww-tabs" role="tablist" aria-label="Trip type">
          {withItems.map(k => (
            <button key={k} role="tab" aria-selected={k === key}
              className={`ww-tab${k === key ? ' on' : ''}`} onClick={() => setPick(k)}>
              {classes[k].label}
            </button>
          ))}
        </div>
      </div>
      <ul className="ww-list" role="tabpanel">
        {shown.map(it => (
          <li key={it.url + (it.boat || '')} className="ww-item">
            <div className="ww-item-meta">
              {[it.trip_length, it.trip_date && _frDate(it.trip_date).replace(/, \d{4}$/, '')].filter(Boolean).join(' · ')}
            </div>
            <div className="ww-item-boat">{it.boat || 'Party boat'}</div>
            {it.tackle?.length > 0 && (
              <div className="ww-chips">{it.tackle.map((t, i) => <span key={i} className="fr-chip">{t}</span>)}</div>
            )}
            {(it.bait || it.conditions) && (
              <dl className="ww-facts">
                {it.bait && <><dt>Bait</dt><dd>{it.bait}</dd></>}
                {it.conditions && <><dt>Conditions</dt><dd>{it.conditions}</dd></>}
              </dl>
            )}
            <a className="ww-link" href={it.url} target="_blank" rel="noopener noreferrer">
              {it.source === 'landing' ? 'Landing report' : 'Read the report'}<span aria-hidden="true"> ↗</span>
              <span className="sr-only">{it.source === 'landing' ? " on the landing's site (new tab)" : ' on BloodyDecks (new tab)'}</span>
            </a>
            {it.source !== 'landing' && <FrPhotoLink n={it.photos} url={it.url} short/>}
          </li>
        ))}
      </ul>
      <p className="fr-attrib">
        Automatic summaries of {hasForum && <>public posts on <a href="https://www.bdoutdoors.com/forums/" target="_blank" rel="noopener noreferrer">BloodyDecks</a></>}
        {hasForum && hasLanding && ' and '}{hasLanding && "the landings' own reports"}.
      </p>
    </section>
  );
}

// ── "From the landing" section (boat page) ───────────────────────────────────
// Data: api/v1/landing_notes.json, written by scraper/paddies/landing_reports.py
// from the landing's and skipper's own posts. Our one-line summary, sizes,
// bait, tackle, one short quote, and the report's photos hot-linked from the
// landing's photo host (never re-hosted); every note links to its report.

const LN_URL = 'api/v1/landing_notes.json';
const LN_SHOW = 3;
let _lnPromise = null;
function loadLandingNotes() {
  if (!_lnPromise) {
    _lnPromise = fetch(LN_URL, { cache: 'no-cache' }).then(r => (r.ok ? r.json() : null)).catch(() => null);
  }
  return _lnPromise;
}

function _lnSize(size) {
  return (size || []).map(s => {
    const lb = s.min_lb && s.max_lb ? `${s.min_lb}–${s.max_lb} lb` : s.max_lb ? `to ${s.max_lb} lb` : `${s.min_lb}+ lb`;
    return `${s.name} ${lb}`;
  }).join(' · ');
}

function LandingNotesSection({ boat }) {
  const [notes, setNotes] = _frUseState(null);
  _frUseEffect(() => {
    let live = true;
    loadLandingNotes().then(d => { if (live) setNotes(d?.boats?.[boat]?.notes || []); });
    return () => { live = false; };
  }, [boat]);
  if (!notes || !notes.length) return null;
  return (
    <section className="fr-section ln-section" aria-labelledby="ln-title">
      <div className="fr-eyebrow">From the landing</div>
      <h2 className="fr-title" id="ln-title">Skipper and landing reports</h2>
      <p className="fr-sub">Summaries of {boat}'s recent posts on the landing's report page. Photos and full reports are on the landing's site.</p>
      <ul className="fr-list">
        {notes.slice(0, LN_SHOW).map(n => (
          <li key={n.url} className="fr-card">
            <div className="fr-card-meta">{[n.trip_length, n.date && _frDate(n.date), n.by && `by ${n.by}`].filter(Boolean).join(' · ')}</div>
            <a className="fr-card-title" href={n.url} target="_blank" rel="noopener noreferrer">
              {n.title}<span className="fr-ext" aria-hidden="true"> ↗</span>
              <span className="sr-only"> (opens the landing's report in a new tab)</span>
            </a>
            {n.skipper_note && <p className="fr-card-catch">{n.skipper_note}</p>}
            {n.size?.length > 0 && <div className="fr-card-confirm"><span aria-hidden="true">⚖</span> {_lnSize(n.size)}</div>}
            {n.quote && <div className="fr-quotes"><blockquote>“{n.quote}”</blockquote></div>}
            {(n.tackle?.length > 0 || n.bait) && (
              <div className="fr-card-tackle">
                <span className="fr-k">{n.tackle?.length ? 'Tackle' : 'Bait'}</span>
                {n.bait && <span className="fr-chip">{n.bait}{n.bait_on_board ? ' on board' : ''}</span>}
                {(n.tackle || []).slice(0, 3).map((t, i) => <span key={i} className="fr-chip">{t}</span>)}
              </div>
            )}
            {n.photos?.length > 0 && (
              <div className="ln-photos">
                {n.photos.slice(0, 4).map(src => (
                  <a key={src} href={n.url} target="_blank" rel="noopener noreferrer" className="ln-photo">
                    <img src={src} alt={`Photo from ${boat}'s report`} loading="lazy" referrerPolicy="no-referrer"/>
                  </a>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="fr-attrib">Source: the landing's own reports (SanDiegoFishReports.com / SoCalFishReports.com).</p>
    </section>
  );
}

Object.assign(window, { ForumReportsSection, loadForumReports, WhatsWorkingCard, loadWhatsWorking,
                        LandingNotesSection, loadLandingNotes });
