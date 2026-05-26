// Boat review system — modal, display, summary
// To enable review submission, set your Formspree endpoint below.
// 1. Go to formspree.io and create a free account
// 2. Create a new form (use your email as the destination)
// 3. Copy the endpoint URL (e.g. https://formspree.io/f/YOUR_FORM_ID)
// 4. Paste it here:
const FORMSPREE_ENDPOINT = 'https://formspree.io/f/mkoepqrz';

const { useState, useMemo, useCallback } = React;

const OVERNIGHT_LENGTHS = new Set([
  'Overnight','1.5 Day','2 Day','2.5 Day','3 Day',
  '4 Day','5 Day','6 Day','7 Day','Long Range',
]);

const TRIP_LENGTH_OPTIONS = [
  'Full Day','3/4 Day','Overnight','1.5 Day','2 Day','2.5 Day',
  '3 Day','4 Day','5 Day','6 Day','7 Day','Long Range',
];

const SPECIES_OPTIONS = [
  'Bluefin','Yellowfin','Yellowtail','Dorado',
  'Albacore','Mixed','Other',
];

// ── Star components ───────────────────────────────────────────────────────────

function StarRating({ value, onChange, size = 20 }) {
  const [hover, setHover] = useState(0);
  return (
    <div className="rv-stars-input" onMouseLeave={() => setHover(0)}>
      {[1,2,3,4,5].map(n => (
        <button key={n}
          type="button"
          className={`rv-star-btn${(hover || value) >= n ? ' filled' : ''}`}
          style={{fontSize: size}}
          onMouseEnter={() => setHover(n)}
          onClick={() => onChange(n)}
          aria-label={`${n} star${n > 1 ? 's' : ''}`}
        >★</button>
      ))}
    </div>
  );
}

function StarDisplay({ value, size = 14, showEmpty = true }) {
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

// ── Review modal ──────────────────────────────────────────────────────────────

const BLANK_FORM = {
  reviewer_name: '', trip_date: '', trip_length: '',
  overall_rating: 0, captain_rating: 0, crew_rating: 0,
  fish_finding_rating: 0, galley_rating: 0, bunks_rating: 0,
  title: '', body: '', species_caught: '', tuna_count: '',
  would_rebook: null,
};

function ReviewModal({ boat, landing, onClose }) {
  const [form, setForm] = useState(BLANK_FORM);
  const [status, setStatus] = useState('idle'); // idle | submitting | success | error
  const isOvernight = OVERNIGHT_LENGTHS.has(form.trip_length);

  const set = (field, val) => setForm(f => ({ ...f, [field]: val }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.overall_rating) return alert('Please add an overall rating.');
    if (!form.body.trim()) return alert('Please write a review.');

    setStatus('submitting');

    const payload = {
      boat, landing,
      ...form,
      tuna_count: form.tuna_count ? parseInt(form.tuna_count) : null,
      would_rebook: form.would_rebook,
      bunks_rating: isOvernight ? form.bunks_rating || null : null,
    };

    if (!FORMSPREE_ENDPOINT) {
      // No endpoint set — show instructions
      console.log('Review payload (Formspree endpoint not configured):', payload);
      setStatus('success');
      return;
    }

    try {
      const resp = await fetch(FORMSPREE_ENDPOINT, {
        method: 'POST',
        headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setStatus(resp.ok ? 'success' : 'error');
    } catch {
      setStatus('error');
    }
  };

  const RatingRow = ({ label, field, note }) => (
    <div className="rv-modal-rating-row">
      <span className="rv-modal-rating-label">
        {label}
        {note && <span className="rv-modal-rating-note"> {note}</span>}
      </span>
      <StarRating value={form[field]} onChange={v => set(field, v)}/>
    </div>
  );

  if (status === 'success') {
    return (
      <div className="rv-modal-backdrop" onClick={onClose}>
        <div className="rv-modal" onClick={e => e.stopPropagation()}>
          <div className="rv-modal-success">
            <div className="rv-success-icon">✓</div>
            <div className="rv-success-title">Thanks for your review!</div>
            <div className="rv-success-body">
              It will appear on the site after a quick moderation check.
            </div>
            <button className="rv-modal-close-btn" onClick={onClose}>Close</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rv-modal-backdrop" onClick={onClose}>
      <div className="rv-modal" onClick={e => e.stopPropagation()}>
        <div className="rv-modal-header">
          <span className="rv-modal-title">Review {boat}</span>
          <button className="rv-modal-x" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <form className="rv-modal-body" onSubmit={handleSubmit}>
          <div className="rv-modal-field">
            <label className="rv-modal-label">Your name <span className="rv-optional">(optional)</span></label>
            <input className="rv-modal-input" type="text" placeholder="e.g. SoCal_Angler"
                   value={form.reviewer_name} onChange={e => set('reviewer_name', e.target.value)}/>
          </div>

          <div className="rv-modal-row2">
            <div className="rv-modal-field">
              <label className="rv-modal-label">Trip date</label>
              <input className="rv-modal-input" type="date"
                     value={form.trip_date} onChange={e => set('trip_date', e.target.value)}/>
            </div>
            <div className="rv-modal-field">
              <label className="rv-modal-label">Trip length</label>
              <select className="rv-modal-select"
                      value={form.trip_length} onChange={e => set('trip_length', e.target.value)}>
                <option value="">Select…</option>
                {TRIP_LENGTH_OPTIONS.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
          </div>

          <div className="rv-modal-field">
            <label className="rv-modal-label">Overall rating <span className="rv-required">*</span></label>
            <StarRating value={form.overall_rating} onChange={v => set('overall_rating', v)} size={24}/>
          </div>

          <div className="rv-modal-section-label">Rate the experience</div>
          <div className="rv-modal-ratings">
            <RatingRow label="Captain"      field="captain_rating"/>
            <RatingRow label="Crew"         field="crew_rating"/>
            <RatingRow label="Fish finding" field="fish_finding_rating"/>
            <RatingRow label="Galley"       field="galley_rating"/>
            {isOvernight && (
              <RatingRow label="Bunks / Staterooms" field="bunks_rating"
                         note="overnight trips"/>
            )}
          </div>

          <div className="rv-modal-row2">
            <div className="rv-modal-field">
              <label className="rv-modal-label">Species caught</label>
              <select className="rv-modal-select"
                      value={form.species_caught} onChange={e => set('species_caught', e.target.value)}>
                <option value="">Select…</option>
                {SPECIES_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="rv-modal-field">
              <label className="rv-modal-label">Tuna count</label>
              <input className="rv-modal-input" type="number" min="0" placeholder="e.g. 8"
                     value={form.tuna_count} onChange={e => set('tuna_count', e.target.value)}/>
            </div>
          </div>

          <div className="rv-modal-field">
            <label className="rv-modal-label">Review title</label>
            <input className="rv-modal-input" type="text" placeholder="e.g. Best bluefin trip of my life!"
                   value={form.title} onChange={e => set('title', e.target.value)}/>
          </div>

          <div className="rv-modal-field">
            <label className="rv-modal-label">Your experience <span className="rv-required">*</span></label>
            <textarea className="rv-modal-textarea" rows={4}
                      placeholder="Tell us about the trip — crew, conditions, catch…"
                      value={form.body} onChange={e => set('body', e.target.value)}/>
          </div>

          <div className="rv-modal-field">
            <label className="rv-modal-label">Would you rebook this boat?</label>
            <div className="rv-modal-rebook">
              {[['yes', true, 'Yes'], ['no', false, 'No']].map(([id, val, lbl]) => (
                <label key={id} className="rv-modal-radio">
                  <input type="radio" name="would_rebook"
                         checked={form.would_rebook === val}
                         onChange={() => set('would_rebook', val)}/>
                  {lbl}
                </label>
              ))}
            </div>
          </div>

          <div className="rv-modal-actions">
            <button type="button" className="rv-cancel-btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="rv-submit-btn" disabled={status === 'submitting'}>
              {status === 'submitting' ? 'Submitting…' : 'Submit Review'}
            </button>
          </div>
          {status === 'error' && (
            <div className="rv-error">Submission failed — please try again.</div>
          )}
          {!FORMSPREE_ENDPOINT && (
            <div className="rv-endpoint-warn">
              ⚠ Review submission endpoint not configured. See <code>boat-reviews.jsx</code> to set up Formspree.
            </div>
          )}
        </form>
      </div>
    </div>
  );
}

// ── Review display ────────────────────────────────────────────────────────────

function ReviewSummary({ summary }) {
  if (!summary || !summary.total_reviews) return null;
  const s = summary;
  const RatingLine = ({ label, value }) => {
    if (value == null) return null;
    return (
      <div className="rv-summary-line">
        <span className="rv-summary-cat">{label}</span>
        <StarDisplay value={value} size={12}/>
        <span className="rv-summary-val">{value.toFixed(1)}</span>
      </div>
    );
  };
  return (
    <div className="rv-summary">
      <div className="rv-summary-top">
        <span className="rv-summary-score">{(s.avg_overall || 0).toFixed(1)}</span>
        <div className="rv-summary-right">
          <StarDisplay value={s.avg_overall} size={18}/>
          <div className="rv-summary-count">{s.total_reviews} review{s.total_reviews !== 1 ? 's' : ''}</div>
        </div>
      </div>
      <div className="rv-summary-cats">
        <RatingLine label="Captain"           value={s.avg_captain}/>
        <RatingLine label="Crew"              value={s.avg_crew}/>
        <RatingLine label="Fish finding"      value={s.avg_fish_finding}/>
        <RatingLine label="Galley"            value={s.avg_galley}/>
        {s.avg_bunks != null && <RatingLine label="Bunks / Staterooms" value={s.avg_bunks}/>}
      </div>
      <div className="rv-summary-footer">
        {s.would_rebook_pct != null && (
          <span className="rv-rebook-pct">
            <span className="rv-rebook-check">✓</span>
            {s.would_rebook_pct}% would rebook
          </span>
        )}
        {s.recent_catch_avg != null && (
          <span className="rv-catch-avg">
            Avg catch: {s.recent_catch_avg} tuna/trip
          </span>
        )}
      </div>
    </div>
  );
}

function ReviewCard({ review }) {
  const isOvernight = OVERNIGHT_LENGTHS.has(review.trip_length || '');
  return (
    <div className="rv-card">
      <div className="rv-card-head">
        <div>
          <StarDisplay value={review.overall_rating} size={16}/>
          {review.title && <div className="rv-card-title">{review.title}</div>}
        </div>
        <div className="rv-card-meta">
          <span className="rv-card-name">{review.reviewer_name}</span>
          {review.submitted_at && <span className="rv-card-date">{review.submitted_at}</span>}
        </div>
      </div>
      <div className="rv-card-trip">
        {review.trip_length && <span className="rv-card-tag">{review.trip_length}</span>}
        {review.trip_date && <span className="rv-card-tag">{review.trip_date}</span>}
        {review.species_caught && review.tuna_count != null && (
          <span className="rv-card-tag rv-card-catch">
            {review.tuna_count} {review.species_caught}
          </span>
        )}
      </div>
      {review.body && <div className="rv-card-body">{review.body}</div>}
      <div className="rv-card-sub-ratings">
        {[
          ['Captain', review.captain_rating],
          ['Crew', review.crew_rating],
          ['Fish finding', review.fish_finding_rating],
          ['Galley', review.galley_rating],
          ...(isOvernight && review.bunks_rating != null ? [['Bunks', review.bunks_rating]] : []),
        ].filter(([, v]) => v != null).map(([lbl, val]) => (
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
  ['catches', 'Most Fish Caught'],
];

function ReviewsSection({ boat, landing }) {
  const [showModal, setShowModal] = useState(false);
  const [sort, setSort] = useState('recent');
  const [page, setPage] = useState(0);
  const PER_PAGE = 5;

  const reviews = useMemo(() => {
    const all = window.SD.REVIEWS?.byBoat?.[boat] || [];
    const copy = [...all];
    if (sort === 'highest') copy.sort((a, b) => (b.overall_rating || 0) - (a.overall_rating || 0));
    else if (sort === 'catches') copy.sort((a, b) => (b.tuna_count || 0) - (a.tuna_count || 0));
    else copy.sort((a, b) => (b.submitted_at || '').localeCompare(a.submitted_at || ''));
    return copy;
  }, [boat, sort]);

  const summary = window.SD.REVIEWS?.summary?.[boat];
  const totalPages = Math.ceil(reviews.length / PER_PAGE);
  const pageReviews = reviews.slice(page * PER_PAGE, (page + 1) * PER_PAGE);

  return (
    <div className="rv-section">
      <div className="rv-section-head">
        <div>
          <div className="rv-section-title">Angler Reviews</div>
          {reviews.length === 0 && (
            <div className="rv-section-sub">Be the first to review {boat}</div>
          )}
        </div>
        <button className="rv-write-btn" onClick={() => setShowModal(true)}>
          ✍ Write a Review
        </button>
      </div>

      {summary && <ReviewSummary summary={summary}/>}

      {reviews.length > 0 && (
        <>
          <div className="rv-sort-row">
            <label className="rv-sort-label">Sort:</label>
            <select className="rv-sort-select" value={sort} onChange={e => { setSort(e.target.value); setPage(0); }}>
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
      )}

      {showModal && (
        <ReviewModal boat={boat} landing={landing} onClose={() => setShowModal(false)}/>
      )}
    </div>
  );
}

// Compact star badge for trip planner cards and boat lists
function ReviewBadge({ boat }) {
  const summary = window.SD.REVIEWS?.summary?.[boat];
  if (!summary || !summary.total_reviews || !summary.avg_overall) return null;
  return (
    <span className="rv-badge" title={`${summary.total_reviews} review${summary.total_reviews !== 1 ? 's' : ''}`}>
      ★ {summary.avg_overall.toFixed(1)}
      <span className="rv-badge-count">({summary.total_reviews})</span>
    </span>
  );
}

Object.assign(window, { ReviewsSection, ReviewBadge });
