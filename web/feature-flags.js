(function () {
  var params = new URLSearchParams(window.location.search);
  window.FEATURES = {
    OCLA_PUBLIC:  false,   // flip to true when OC/LA is ready to launch
    _previewOcla: params.get('preview_ocla') === 'true',

    // Google reviews panel on boat and landing pages (web/google-reviews.jsx).
    // Needs the places-proxy Worker deployed with GOOGLE_PLACES_API_KEY, and
    // place_ids in api/v1/google_places.json. Preview: ?preview_google=true
    GOOGLE_REVIEWS: false,
    // YouTube trip videos on boat pages (web/boat-videos.jsx), read from
    // api/v1/boat_videos.json (written by src/youtube.py). Preview: ?preview_videos=true
    YOUTUBE_VIDEOS: false,
  };
  // SHOW_OCLA is the single gate checked by all UI code
  window.FEATURES.SHOW_OCLA = window.FEATURES.OCLA_PUBLIC || window.FEATURES._previewOcla;
  window.FEATURES.SHOW_GOOGLE_REVIEWS = window.FEATURES.GOOGLE_REVIEWS || params.get('preview_google') === 'true';
  window.FEATURES.SHOW_YOUTUBE_VIDEOS = window.FEATURES.YOUTUBE_VIDEOS || params.get('preview_videos') === 'true';

  // Deployed places-proxy Worker URL, no trailing slash. Empty = panel stays hidden.
  window.PLACES_WORKER_URL = '';
})();
