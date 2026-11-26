// "Trip videos" panel on the boat page.
//
// Data: api/v1/boat_videos.json, written by src/youtube.py through the YouTube Data
// API (video ids + titles only, re-confirmed every run, dropped after 30 days
// without confirmation). Videos play only in the YouTube player, from
// youtube-nocookie.com, and only after a click, so nothing from YouTube loads
// until the visitor asks for it.
//
// Gated by window.FEATURES.SHOW_YOUTUBE_VIDEOS.

const { useState: _bvUseState, useEffect: _bvUseEffect } = React;

const BV_URL = 'api/v1/boat_videos.json';

let _bvPromise = null;
function loadBoatVideos() {
  if (!_bvPromise) {
    _bvPromise = fetch(BV_URL, { cache: 'no-cache' })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _bvPromise;
}

function _bvDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + 'T12:00:00');
  return isNaN(d) ? '' : d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

function BoatVideo({ v }) {
  const [play, setPlay] = _bvUseState(false);
  const watch = `https://www.youtube.com/watch?v=${encodeURIComponent(v.id)}`;
  return (
    <li className="bv-item">
      <div className="bv-frame">
        {play ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(v.id)}?autoplay=1&rel=0`}
            title={v.title} loading="lazy" referrerPolicy="strict-origin-when-cross-origin"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen/>
        ) : (
          <>
            <img src={`https://i.ytimg.com/vi/${encodeURIComponent(v.id)}/hqdefault.jpg`} alt="" loading="lazy"/>
            <button type="button" className="bv-play" onClick={() => setPlay(true)}
                    aria-label={`Play video: ${v.title}`}/>
          </>
        )}
      </div>
      <a className="bv-title" href={watch} target="_blank" rel="noopener noreferrer">{v.title}</a>
      <span className="bv-meta">{[v.channel, _bvDate(v.published)].filter(Boolean).join(' · ')}</span>
    </li>
  );
}

function BoatVideosSection({ boat }) {
  const [videos, setVideos] = _bvUseState(null);
  _bvUseEffect(() => {
    if (!window.FEATURES?.SHOW_YOUTUBE_VIDEOS) return;
    let live = true;
    loadBoatVideos().then(d => { if (live) setVideos(d?.boats?.[boat] || []); });
    return () => { live = false; };
  }, [boat]);
  if (!window.FEATURES?.SHOW_YOUTUBE_VIDEOS || !videos || !videos.length) return null;
  return (
    <section className="fr-section bv-section" aria-labelledby="bv-title">
      <div className="fr-eyebrow">From YouTube</div>
      <h2 className="fr-title" id="bv-title">Trip videos</h2>
      <p className="fr-sub">Videos that anglers and crews have posted that mention {boat}. Matched automatically by title, so a few may be off.</p>
      <ul className="bv-grid">{videos.map(v => <BoatVideo key={v.id} v={v}/>)}</ul>
      <p className="fr-attrib">Videos play in the YouTube player and are subject to YouTube's terms.</p>
    </section>
  );
}

Object.assign(window, { BoatVideosSection, loadBoatVideos });
