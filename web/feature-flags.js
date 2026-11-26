(function () {
  var params = new URLSearchParams(window.location.search);
  // SF Bay soft launch: ?preview_sfbay=true sticks for the browser tab
  // (sessionStorage) so deep links and reloads keep working while previewing.
  var previewSfbay = params.get('preview_sfbay') === 'true';
  try {
    if (params.get('preview_sfbay') === 'false') sessionStorage.removeItem('tt_preview_sfbay');
    else if (previewSfbay) sessionStorage.setItem('tt_preview_sfbay', '1');
    else previewSfbay = sessionStorage.getItem('tt_preview_sfbay') === '1';
  } catch (e) {}
  window.FEATURES = {
    OCLA_PUBLIC:  true,    // OC/LA launched 2026-11-25 (owner OK). Rollback: set false.
    _previewOcla: params.get('preview_ocla') === 'true',
    SFBAY_PUBLIC: false,   // flip to true when the owner approves the SF Bay launch
    _previewSfbay: previewSfbay,

    // Google reviews panel on boat and landing pages (web/google-reviews.jsx).
    // Needs the places-proxy Worker deployed with GOOGLE_PLACES_API_KEY, and
    // place_ids in api/v1/google_places.json. Preview: ?preview_google=true
    GOOGLE_REVIEWS: false,
    // YouTube trip videos on boat pages (web/boat-videos.jsx), read from
    // api/v1/boat_videos.json (written by src/youtube.py). Preview: ?preview_videos=true
    YOUTUBE_VIDEOS: false,
    // "Barge bait" line on trip cards and landing pages (web/bait-now.jsx), read
    // from api/v1/bait_now.json (src/bait.py, Everingham Bait Report). Waiting on
    // the owner's email to Everingham. Preview: ?preview_bait=true
    BAIT_NOW: false,
  };
  // SHOW_OCLA is the single gate checked by all UI code
  window.FEATURES.SHOW_OCLA = window.FEATURES.OCLA_PUBLIC || window.FEATURES._previewOcla;
  // SHOW_SFBAY gates the SF Bay region everywhere (regions.js, app.jsx, ui.jsx)
  window.FEATURES.SHOW_SFBAY = window.FEATURES.SFBAY_PUBLIC || window.FEATURES._previewSfbay;
  window.FEATURES.SHOW_GOOGLE_REVIEWS = window.FEATURES.GOOGLE_REVIEWS || params.get('preview_google') === 'true';
  window.FEATURES.SHOW_YOUTUBE_VIDEOS = window.FEATURES.YOUTUBE_VIDEOS || params.get('preview_videos') === 'true';
  window.FEATURES.SHOW_BAIT_NOW = window.FEATURES.BAIT_NOW || params.get('preview_bait') === 'true';

  // Deployed places-proxy Worker URL, no trailing slash. Empty = panel stays hidden.
  window.PLACES_WORKER_URL = '';
})();
