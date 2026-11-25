// "Google reviews" panel on boat and landing pages.
//
// Data path: api/v1/google_places.json (hand-checked place_id per boat or landing,
// the only Google field we are allowed to store) -> places-proxy Worker ->
// Google Places API (New), fetched live each time the Reviews tab opens.
// Nothing from Google is cached in the browser beyond this page view.
//
// Google display rules followed here:
//   * at most 5 reviews, in Google's order ("most relevant"), and we say so
//   * each review shows its author's name, linked to their Google profile,
//     and their photo
//   * "Google Maps" source attribution plus a link to the listing
//   * kept apart from Tunatracker's own angler-review average
//
// Gated by window.FEATURES.SHOW_GOOGLE_REVIEWS and window.PLACES_WORKER_URL.

const { useState: _grUseState, useEffect: _grUseEffect } = React;

const GR_MAP_URL = 'api/v1/google_places.json';
const GR_CLAMP = 280;

let _grMapPromise = null;
function loadGooglePlaceMap() {
  if (!_grMapPromise) {
    _grMapPromise = fetch(GR_MAP_URL, { cache: 'no-cache' })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _grMapPromise;
}

// Pick the boat's own listing; fall back to its landing's listing, clearly labelled.
function grResolvePlace(map, boat, landing) {
  if (!map) return null;
  if (boat && map.boats && map.boats[boat] && map.boats[boat].place_id) {
    return { placeId: map.boats[boat].place_id, scope: 'boat', label: boat };
  }
  if (landing && map.landings && map.landings[landing] && map.landings[landing].place_id) {
    return { placeId: map.landings[landing].place_id, scope: 'landing', label: landing };
  }
  return null;
}

function useGooglePlace(boat, landing) {
  const [state, setState] = _grUseState({ status: 'idle', place: null, data: null });
  _grUseEffect(() => {
    const base = window.PLACES_WORKER_URL;
    if (!window.FEATURES?.SHOW_GOOGLE_REVIEWS || !base) { setState({ status: 'off' }); return; }
    let live = true;
    setState({ status: 'loading' });
    loadGooglePlaceMap().then(map => {
      const place = grResolvePlace(map, boat, landing);
      if (!place) { if (live) setState({ status: 'none' }); return; }
      return fetch(`${base}/v1/place/${encodeURIComponent(place.placeId)}`, { cache: 'no-store' })
        .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
        .then(data => { if (live) setState({ status: 'ok', place, data }); })
        .catch(() => { if (live) setState({ status: 'error', place }); });
    });
    return () => { live = false; };
  }, [boat, landing]);
  return state;
}

function GrStars({ value, size = 14 }) {
  const v = Math.max(0, Math.min(5, Number(value) || 0));
  return (
    <span className="gr-stars" role="img" aria-label={`${v.toFixed(1)} out of 5 stars`}
          style={{ '--gr-pct': `${(v / 5) * 100}%`, fontSize: size }}>
      <span aria-hidden="true">★★★★★</span>
    </span>
  );
}

function GrReview({ r }) {
  const [open, setOpen] = _grUseState(false);
  const long = (r.text || '').length > GR_CLAMP;
  const text = !long || open ? r.text : r.text.slice(0, GR_CLAMP).replace(/\s+\S*$/, '') + '…';
  const name = r.author?.name || 'Google user';
  return (
    <li className="fr-card gr-card">
      <div className="gr-author">
        {r.author?.photo
          ? <img className="gr-avatar" src={r.author.photo} alt="" width="32" height="32"
                 loading="lazy" referrerPolicy="no-referrer"/>
          : <span className="gr-avatar gr-avatar-blank" aria-hidden="true">{name.slice(0, 1)}</span>}
        <div className="gr-author-text">
          {r.author?.uri
            ? <a className="gr-author-name" href={r.author.uri} target="_blank" rel="noopener noreferrer">{name}</a>
            : <span className="gr-author-name">{name}</span>}
          <span className="fr-card-meta">{r.when}</span>
        </div>
        {r.rating != null && <GrStars value={r.rating}/>}
      </div>
      {text && <p className="fr-card-catch gr-text">{text}</p>}
      {long && (
        <button type="button" className="gr-toggle" onClick={() => setOpen(o => !o)} aria-expanded={open}>
          {open ? 'Show less' : 'Read more'}
        </button>
      )}
    </li>
  );
}

function GoogleReviewsSection({ boat, landing }) {
  const st = useGooglePlace(boat, landing);
  if (st.status === 'off' || st.status === 'none' || st.status === 'idle') return null;
  const scopeNote = st.place?.scope === 'landing'
    ? `${boat ? `${boat} has no Google listing of its own, so these` : 'These'} are reviews of ${st.place.label}, the landing.`
    : null;

  return (
    <section className="fr-section gr-section" aria-labelledby="gr-title">
      <div className="fr-eyebrow">From Google Maps</div>
      <h2 className="fr-title" id="gr-title">Google reviews</h2>
      {scopeNote && <p className="fr-sub">{scopeNote}</p>}

      {st.status === 'loading' && <p className="fr-sub" aria-live="polite">Loading Google reviews…</p>}
      {st.status === 'error' && <p className="fr-sub">Google reviews aren't available right now.</p>}

      {st.status === 'ok' && (() => {
        const d = st.data;
        return (
          <>
            <div className="fr-summary gr-summary">
              <div className="fr-rebook">
                <b>{d.rating != null ? d.rating.toFixed(1) : '–'}<small> / 5</small></b>
                <span>{d.rating != null && <GrStars value={d.rating} size={13}/>} {Number(d.count || 0).toLocaleString()} Google ratings</span>
              </div>
            </div>
            {d.reviews?.length > 0 && (
              <ul className="fr-list">{d.reviews.map((r, i) => <GrReview key={i} r={r}/>)}</ul>
            )}
            <p className="fr-attrib">
              Up to 5 reviews, sorted by Google's "most relevant" order. Source: <span className="gr-gmaps">Google Maps</span>.
              {d.mapsUri && <> <a href={d.mapsUri} target="_blank" rel="noopener noreferrer">Read all reviews on Google Maps<span aria-hidden="true"> ↗</span></a></>}
              {' '}Google ratings are separate from Tunatracker angler reviews.
            </p>
          </>
        );
      })()}
    </section>
  );
}

Object.assign(window, { GoogleReviewsSection, loadGooglePlaceMap, grResolvePlace });
