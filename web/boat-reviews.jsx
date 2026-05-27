// Boat review system — 3-step modal, Expedia-style display, highlights
// Formspree endpoint: go to formspree.io, create a form, paste the URL below.
const FORMSPREE_ENDPOINT = 'https://formspree.io/f/mkoepqrz';

const { useState, useMemo, useEffect, useRef } = React;

const OVERNIGHT_LENGTHS = new Set([
  'Overnight','1.5 Day','2 Day','2.5 Day','3 Day',
  '4 Day','5 Day','6 Day','7 Day','Long Range',
]);

const TRIP_LENGTH_OPTIONS = [
  'Full Day','3/4 Day','Overnight','1.5 Day','2 Day','2.5 Day',
  '3 Day','4 Day','5 Day','6 Day','7 Day','Long Range',
];

// ── Label thresholds (Expedia-style) ─────────────────────────────────────────
const REVIEW_LABELS = [
  [4.5, 'Exceptional', '#10B981'],
  [4.0, 'Excellent',   '#22C55E'],
  [3.5, 'Very Good',   '#84CC16'],
  [3.0, 'Good',        '#EAB308'],
  [0,   'Mixed',       '#F97316'],
];

function getReviewLabel(score) {
  for (const [threshold, label, color] of REVIEW_LABELS) {
    if (score >= threshold) return { label, color };
  }
  return { label: 'Mixed', color: '#F97316' };
}

// ── Star components ───────────────────────────────────────────────────────────
function StarRating({ value, onChange, size = 28 }) {
  const [hover, setHover] = useState(0);
  return (
    <div className="rv-stars-input" onMouseLeave={() => setHover(0)}>
      {[1,2,3,4,5].map(n => (
        <button key={n}
          type="button"
          className={`rv-star-btn${(hover || value) >= n ? ' filled' : ''}`}
          style={{fontSize: size, minWidth: 44, minHeight: 44}}
          onMouseEnter={() => setHover(n)}
          onClick={() => onChange(n)}
          aria-label={`${n} star${n > 1 ? 's' : ''}`}
        >★</button>
      ))}
    </div>
  );
}

function StarDisplay({ value, size = 14 }) {
  if (value == null) return null;
  const full = Math.round(value);
  return (
    <span className="rv-stars-display" style={{fontSize: size}} aria-label={`${value} out of 5 stars`}>
      {[1,2,3,4,5].map(n => (
        <span key={n} className={n <= full ? 'rv-star-full' : 'rv-star-empty'}>★</span>
      ))}
    </span>
  );
}

// ── Form state ────────────────────────────────────────────────────────────────
const BLANK_FORM = {
  reviewer_name: '', return_date: '', trip_length: '',
  overall_rating: 0, captain_rating: 0, crew_rating: 0,
  fish_finding_rating: 0, galley_rating: 0, bunks_rating: 0,
  title: '', body: '', would_rebook: null,
};

// ── Step sub-components ───────────────────────────────────────────────────────
function StepWhichTrip({ form, set, initBoat }) {
  const boats = (window.SD.BOATS || []).map(b => b.name).sort();
  const today = new Date().toISOString().slice(0,10);
  return (
    <div className="rv-step">
      <div className="rv-step-head">
        <span className="rv-step-num">Step 1 of 3</span>
        <h3 className="rv-step-title">Which trip?</h3>
      </div>

      {!initBoat && (
        <div className="rv-modal-field">
          <label className="rv-modal-label">Boat</label>
          <select className="rv-modal-select" value={form.boat || ''} onChange={e => set('boat', e.target.value)}>
            <option value="">Select boat…</option>
            {boats.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
      )}

      <div className="rv-modal-field">
        <label className="rv-modal-label">
          When did you return?
          <span className="rv-modal-label-sub">The date your trip ended</span>
        </label>
        <input className="rv-modal-input" type="date"
               max={today}
               value={form.return_date}
               onChange={e => set('return_date', e.target.value)}/>
      </div>

      <div className="rv-modal-field">
        <label className="rv-modal-label">Trip length <span className="rv-optional">(optional)</span></label>
        <select className="rv-modal-select" value={form.trip_length} onChange={e => set('trip_length', e.target.value)}>
          <option value="">Select…</option>
          {TRIP_LENGTH_OPTIONS.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
      </div>
    </div>
  );
}

function StepHowWasIt({ form, set }) {
  const isOvernight = OVERNIGHT_LENGTHS.has(form.trip_length);
  const RatingRow = ({ label, field, required }) => (
    <div className="rv-modal-rating-row">
      <span className="rv-modal-rating-label">
        {label}{required && <span className="rv-required"> *</span>}
      </span>
      <StarRating value={form[field]} onChange={v => set(field, v)}/>
    </div>
  );
  return (
    <div className="rv-step">
      <div className="rv-step-head">
        <span className="rv-step-num">Step 2 of 3</span>
        <h3 className="rv-step-title">How was it?</h3>
      </div>
      <p className="rv-step-note">* Overall rating required · everything else optional</p>
      <RatingRow label="Overall"      field="overall_rating" required/>
      <RatingRow label="Captain"      field="captain_rating"/>
      <RatingRow label="Crew"         field="crew_rating"/>
      <RatingRow label="Fish Finding" field="fish_finding_rating"/>
      <RatingRow label="Galley"       field="galley_rating"/>
      {isOvernight && <RatingRow label="Bunks / Staterooms" field="bunks_rating"/>}
      <div className="rv-modal-field" style={{marginTop:14}}>
        <label className="rv-modal-label">Would you rebook? <span className="rv-optional">(optional)</span></label>
        <div className="rv-rebook-btns">
          {[[true,'👍 Yes'],[false,'👎 No']].map(([val, lbl]) => (
            <button key={String(val)} type="button"
                    className={`rv-rebook-btn${form.would_rebook === val ? (val ? ' sel-yes' : ' sel-no') : ''}`}
                    onClick={() => set('would_rebook', form.would_rebook === val ? null : val)}>
              {lbl}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function StepTellUsMore({ form, set }) {
  return (
    <div className="rv-step">
      <div className="rv-step-head">
        <span className="rv-step-num">Step 3 of 3</span>
        <h3 className="rv-step-title">Tell us more <span className="rv-optional-head">(optional)</span></h3>
      </div>
      <div className="rv-modal-field">
        <label className="rv-modal-label">Review title <span className="rv-optional">(optional)</span></label>
        <input className="rv-modal-input" type="text" placeholder="e.g. Best bluefin trip of my life!"
               value={form.title} onChange={e => set('title', e.target.value)}/>
      </div>
      <div className="rv-modal-field">
        <label className="rv-modal-label">Your experience <span className="rv-optional">(optional)</span></label>
        <textarea className="rv-modal-textarea" rows={4}
                  placeholder="Tell us about the trip — crew, conditions, catch…"
                  value={form.body} onChange={e => set('body', e.target.value)}/>
      </div>
      <div className="rv-modal-field">
        <label className="rv-modal-label">Your name <span className="rv-optional">(optional)</span></label>
        <input className="rv-modal-input" type="text" placeholder="e.g. SoCal_Angler"
               value={form.reviewer_name} onChange={e => set('reviewer_name', e.target.value)}/>
      </div>
    </div>
  );
}

function SuccessScreen({ boat, onClose }) {
  const shareText = `Just left a review for ${boat} on The Tuna Tracker! thetunatracker.com`;
  const copyLink = () => {
    navigator.clipboard.writeText('https://thetunatracker.com').catch(() => {});
    alert('Link copied!');
  };
  const shareFB = () => {
    window.open(
      `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent('https://thetunatracker.com')}&quote=${encodeURIComponent(shareText)}`,
      '_blank', 'width=600,height=400'
    );
  };
  return (
    <div className="rv-modal-backdrop" onClick={onClose}>
      <div className="rv-modal" onClick={e => e.stopPropagation()}>
        <div className="rv-modal-success">
          <div className="rv-success-icon">✓</div>
          <div className="rv-success-title">Thanks for your review!</div>
          <div className="rv-success-body">
            It will appear after a quick moderation check.
          </div>
          <div className="rv-success-share">
            <div className="rv-success-share-label">Help other anglers find this —</div>
            <div className="rv-success-share-btns">
              <button className="rv-share-btn rv-share-fb" onClick={shareFB}>
                Share on Facebook
              </button>
              <button className="rv-share-btn rv-share-copy" onClick={copyLink}>
                Copy Link
              </button>
            </div>
          </div>
          <button className="rv-modal-close-btn" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}

// ── 3-step Review Modal ───────────────────────────────────────────────────────
function ReviewModal({ boat: initBoat, landing: initLanding, prefill = {}, onClose }) {
  const [step, setStep] = useState(1);
  const [form, setForm] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return {
      ...BLANK_FORM,
      return_date: params.get('date') || prefill.date || '',
      trip_length: params.get('length') || prefill.length || '',
    };
  });
  const [status, setStatus] = useState('idle');

  const set = (field, val) => setForm(f => ({ ...f, [field]: val }));
  const displayBoat = initBoat || form.boat || '';
  const isOvernight = OVERNIGHT_LENGTHS.has(form.trip_length);

  const handleSubmit = async () => {
    if (!form.overall_rating) {
      alert('Please add an Overall rating on Step 2.');
      setStep(2);
      return;
    }
    setStatus('submitting');
    const payload = {
      boat: displayBoat, landing: initLanding || '',
      reviewer_name: form.reviewer_name,
      trip_date: form.return_date,
      trip_length: form.trip_length,
      overall_rating: form.overall_rating,
      captain_rating: form.captain_rating || null,
      crew_rating: form.crew_rating || null,
      fish_finding_rating: form.fish_finding_rating || null,
      galley_rating: form.galley_rating || null,
      bunks_rating: isOvernight ? (form.bunks_rating || null) : null,
      title: form.title,
      body: form.body,
      would_rebook: form.would_rebook,
    };
    if (!FORMSPREE_ENDPOINT) { setStatus('success'); return; }
    try {
      const resp = await fetch(FORMSPREE_ENDPOINT, {
        method: 'POST',
        headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setStatus(resp.ok ? 'success' : 'error');
    } catch { setStatus('error'); }
  };

  if (status === 'success') return <SuccessScreen boat={displayBoat} onClose={onClose}/>;

  const STEPS = ['Trip info', 'Ratings', 'Details'];

  return (
    <div className="rv-modal-backdrop" onClick={onClose}>
      <div className="rv-modal rv-modal-stepped" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="rv-modal-header">
          <div>
            <span className="rv-modal-title">Review {displayBoat || 'Your Trip'}</span>
          </div>
          <button className="rv-modal-x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Progress */}
        <div className="rv-progress-bar">
          {STEPS.map((lbl, i) => (
            <div key={lbl} className={`rv-progress-step${step === i+1 ? ' active' : step > i+1 ? ' done' : ''}`}
                 onClick={() => i+1 < step && setStep(i+1)}>
              <div className="rv-progress-dot"/>
              <span className="rv-progress-label">{lbl}</span>
            </div>
          ))}
          <div className="rv-progress-track">
            <div className="rv-progress-fill" style={{width: `${((step-1)/2)*100}%`}}/>
          </div>
        </div>

        {/* Body */}
        <div className="rv-modal-body rv-modal-stepped-body">
          {step === 1 && <StepWhichTrip form={form} set={set} initBoat={initBoat}/>}
          {step === 2 && <StepHowWasIt form={form} set={set}/>}
          {step === 3 && <StepTellUsMore form={form} set={set}/>}
        </div>

        {/* Footer nav */}
        <div className="rv-modal-footer">
          {step > 1 && (
            <button className="rv-back-btn" onClick={() => setStep(s => s - 1)}>← Back</button>
          )}
          <div style={{flex:1}}/>
          {step < 3 ? (
            <>
              {step === 2 && (
                <button className="rv-submit-quick" onClick={handleSubmit}
                        disabled={!form.overall_rating || status === 'submitting'}>
                  {status === 'submitting' ? 'Submitting…' : 'Submit ↗'}
                </button>
              )}
              <button className="rv-next-btn" onClick={() => setStep(s => s + 1)}>
                {step === 2 ? 'Add details →' : 'Next →'}
              </button>
            </>
          ) : (
            <button className="rv-submit-btn" onClick={handleSubmit}
                    disabled={!form.overall_rating || status === 'submitting'}>
              {status === 'submitting' ? 'Submitting…' : 'Submit Review →'}
            </button>
          )}
        </div>

        {status === 'error' && (
          <div className="rv-error">Submission failed — please try again.</div>
        )}
      </div>
    </div>
  );
}

// ── Review highlights (keyword frequency) ─────────────────────────────────────
const _POS = [
  { label: 'Great captain',         rx: /great captain|captain.{0,15}(awesome|amazing|great|excellent)/i },
  { label: 'Fish finder on point',  rx: /fish.?finder|on the fish|great fish.?finding|found us fish/i },
  { label: 'Excellent galley',      rx: /galley|food.{0,10}(great|good|excellent|amazing)/i },
  { label: 'Great crew',            rx: /crew.{0,15}(great|awesome|amazing|helpful|professional|friendly)/i },
  { label: 'Would highly recommend',rx: /highly recommend|10\/10|best.*trip|amazing trip|great trip/i },
  { label: 'Great experience',      rx: /great experience|excellent trip|fantastic trip/i },
];
const _NEG = [
  { label: 'Bunks cramped',   rx: /bunk.{0,15}(cramp|small|tight|uncomfortable)/i },
  { label: 'Rough conditions',rx: /rough seas|very choppy|sea.?sick/i },
  { label: 'Slow fishing',    rx: /slow fish|didn.?t catch|nothing biting/i },
];

function ReviewHighlights({ reviews }) {
  if (!reviews || reviews.length < 2) return null;
  const text = reviews.map(r => `${r.title||''} ${r.body||''}`).join(' ');
  const pos = _POS.map(p => ({ ...p, n: (text.match(new RegExp(p.rx.source,'gi'))||[]).length })).filter(p => p.n > 0).slice(0,4);
  const neg = _NEG.map(p => ({ ...p, n: (text.match(new RegExp(p.rx.source,'gi'))||[]).length })).filter(p => p.n > 0).slice(0,2);
  if (!pos.length && !neg.length) return null;
  return (
    <div className="rv-highlights">
      <div className="rv-highlights-title">Highlights from reviews:</div>
      {pos.map(p => (
        <div key={p.label} className="rv-hl-row rv-hl-pos">
          <span className="rv-hl-icon">✓</span>
          <span className="rv-hl-text">{p.label}</span>
          <span className="rv-hl-count">mentioned {p.n}×</span>
        </div>
      ))}
      {neg.map(p => (
        <div key={p.label} className="rv-hl-row rv-hl-neg">
          <span className="rv-hl-icon">⚠</span>
          <span className="rv-hl-text">{p.label}</span>
          <span className="rv-hl-count">mentioned {p.n}×</span>
        </div>
      ))}
    </div>
  );
}

// ── Review summary (Expedia-style) ────────────────────────────────────────────
function ReviewSummary({ summary }) {
  if (!summary || !summary.total_reviews) return null;
  const s = summary;
  const score = s.avg_overall || 0;
  const { label, color } = getReviewLabel(score);
  const BarRow = ({ label: lbl, value }) => {
    if (value == null) return null;
    return (
      <div className="rv-bar-row">
        <span className="rv-bar-label">{lbl}</span>
        <div className="rv-bar-track">
          <div className="rv-bar-fill" style={{width:`${(value/5)*100}%`}}/>
        </div>
        <span className="rv-bar-val">{value.toFixed(1)}</span>
      </div>
    );
  };
  return (
    <div className="rv-summary">
      <div className="rv-summary-top">
        <div className="rv-summary-big-score">{score.toFixed(1)}</div>
        <div className="rv-summary-info">
          <StarDisplay value={score} size={20}/>
          <div className="rv-summary-label" style={{color}}>{label}</div>
          <div className="rv-summary-count">{s.total_reviews} verified review{s.total_reviews !== 1 ? 's' : ''}</div>
        </div>
      </div>
      <div className="rv-bar-rows">
        <BarRow label="Captain"      value={s.avg_captain}/>
        <BarRow label="Fish Finding" value={s.avg_fish_finding}/>
        <BarRow label="Crew"         value={s.avg_crew}/>
        <BarRow label="Galley"       value={s.avg_galley}/>
        {s.avg_bunks != null && <BarRow label="Bunks" value={s.avg_bunks}/>}
      </div>
      {s.would_rebook_pct != null && (
        <div className="rv-summary-rebook">
          <span className="rv-rebook-check">✓</span>
          {s.would_rebook_pct}% would rebook
        </div>
      )}
    </div>
  );
}

// ── Individual review card ────────────────────────────────────────────────────
const BODY_LIMIT = 220;

function ReviewCard({ review }) {
  const [expanded, setExpanded] = useState(false);
  const isOvernight = OVERNIGHT_LENGTHS.has(review.trip_length || '');
  const body = review.body || '';
  const isLong = body.length > BODY_LIMIT;
  return (
    <div className="rv-card">
      <div className="rv-card-head">
        <div>
          <StarDisplay value={review.overall_rating} size={16}/>
          {review.title && <div className="rv-card-title">{review.title}</div>}
        </div>
        <div className="rv-card-meta">
          <span className="rv-card-name">{review.reviewer_name || 'Anonymous'}</span>
          {review.submitted_at && <span className="rv-card-date"> · {review.submitted_at}</span>}
        </div>
      </div>
      <div className="rv-card-trip">
        {review.trip_length && <span className="rv-card-tag">{review.trip_length}</span>}
        {review.trip_date && <span className="rv-card-tag">{review.trip_date}</span>}
      </div>
      {body && (
        <div className="rv-card-body">
          {expanded || !isLong ? body : body.slice(0, BODY_LIMIT) + '…'}
          {isLong && (
            <button className="rv-read-more" onClick={() => setExpanded(e => !e)}>
              {expanded ? ' Show less' : ' Read more'}
            </button>
          )}
        </div>
      )}
      <div className="rv-card-sub-ratings">
        {[
          ['Captain', review.captain_rating],
          ['Crew', review.crew_rating],
          ['Fish finding', review.fish_finding_rating],
          ['Galley', review.galley_rating],
          ...(isOvernight && review.bunks_rating != null ? [['Bunks', review.bunks_rating]] : []),
        ].filter(([, v]) => v != null && v > 0).map(([lbl, val]) => (
          <span key={lbl} className="rv-card-sub">
            <span className="rv-card-sub-lbl">{lbl}</span>
            <StarDisplay value={val} size={11}/>
          </span>
        ))}
      </div>
      {review.would_rebook != null && (
        <div className={`rv-card-rebook${review.would_rebook ? ' yes' : ' no'}`}>
          {review.would_rebook ? '✓ Would rebook' : '✕ Would not rebook'}
        </div>
      )}
    </div>
  );
}

const SORT_OPTIONS = [
  ['recent',  'Most Recent'],
  ['highest', 'Highest Rated'],
];

// ── Reviews section (boat detail tab) ────────────────────────────────────────
function ReviewsSection({ boat, landing }) {
  const [showModal, setShowModal] = useState(false);
  const [sort, setSort] = useState('recent');
  const [page, setPage] = useState(0);
  const PER_PAGE = 5;

  // Auto-open from URL param (e.g. from Today's Report ⭐ click)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('openReview') === '1') {
      setShowModal(true);
      params.delete('openReview');
      const newSearch = params.toString();
      history.replaceState(null, '', newSearch ? `?${newSearch}` : window.location.pathname);
    }
  }, []);

  const reviews = useMemo(() => {
    const all = window.SD.REVIEWS?.byBoat?.[boat] || [];
    const copy = [...all];
    if (sort === 'highest') copy.sort((a, b) => (b.overall_rating||0) - (a.overall_rating||0));
    else copy.sort((a, b) => (b.submitted_at||'').localeCompare(a.submitted_at||''));
    return copy;
  }, [boat, sort]);

  const summary = window.SD.REVIEWS?.summary?.[boat];
  const totalPages = Math.ceil(reviews.length / PER_PAGE);
  const pageReviews = reviews.slice(page * PER_PAGE, (page + 1) * PER_PAGE);

  return (
    <div className="rv-section">
      <div className="rv-section-head">
        <div className="rv-section-title">Angler Reviews</div>
        <button className="rv-write-btn-primary" onClick={() => setShowModal(true)}>
          ⭐ Write a Review
        </button>
      </div>

      {summary && <ReviewSummary summary={summary}/>}
      {reviews.length > 0 && <ReviewHighlights reviews={reviews}/>}

      {reviews.length > 0 ? (
        <>
          <div className="rv-sort-row">
            <label className="rv-sort-label">Sort:</label>
            <select className="rv-sort-select" value={sort}
                    onChange={e => { setSort(e.target.value); setPage(0); }}>
              {SORT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="rv-list">
            {pageReviews.map(r => <ReviewCard key={r.id} review={r}/>)}
          </div>
          {totalPages > 1 && (
            <div className="rv-pagination">
              <button className="rv-page-btn" disabled={page === 0}
                      onClick={() => setPage(p => p - 1)}>← Prev</button>
              <span className="rv-page-info">{page + 1} / {totalPages}</span>
              <button className="rv-page-btn" disabled={page >= totalPages - 1}
                      onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          )}
        </>
      ) : (
        <div className="rv-section-sub">Be the first to review {boat}</div>
      )}

      <div className="rv-section-footer">
        <span>Been on {boat}? Share your experience</span>
        <button className="rv-write-btn-secondary" onClick={() => setShowModal(true)}>
          Write a Review →
        </button>
      </div>

      {showModal && (
        <ReviewModal boat={boat} landing={landing} onClose={() => setShowModal(false)}/>
      )}
    </div>
  );
}

// ── Compact star badge (inline with boat name) ────────────────────────────────
function ReviewBadge({ boat }) {
  const summary = window.SD.REVIEWS?.summary?.[boat];
  if (!summary || summary.total_reviews < 3 || !summary.avg_overall) return null;
  const { label, color } = getReviewLabel(summary.avg_overall);
  return (
    <span className="rv-badge">
      <span className="rv-badge-star">★</span>
      <span className="rv-badge-score">{summary.avg_overall.toFixed(1)}</span>
      <span className="rv-badge-label" style={{color}}>{label}</span>
      <span className="rv-badge-count">· {summary.total_reviews}</span>
    </span>
  );
}

// ── Expedia-style card badge (trip planner) ───────────────────────────────────
function ReviewCardBadge({ boat }) {
  const summary = window.SD.REVIEWS?.summary?.[boat];
  if (!summary || summary.total_reviews < 3 || !summary.avg_overall) return null;
  const { label, color } = getReviewLabel(summary.avg_overall);
  const topReview = window.SD.REVIEWS?.byBoat?.[boat]?.[0];
  return (
    <div className="rv-card-badge">
      <div className="rv-card-badge-top">
        <span className="rv-card-badge-score">{summary.avg_overall.toFixed(1)}</span>
        <span className="rv-card-badge-label" style={{color}}>{label}</span>
        <span className="rv-card-badge-count">· {summary.total_reviews} reviews</span>
      </div>
      {topReview?.title && (
        <div className="rv-card-badge-quote">"{topReview.title}"</div>
      )}
    </div>
  );
}

Object.assign(window, { ReviewsSection, ReviewBadge, ReviewCardBadge, ReviewModal, getReviewLabel });
