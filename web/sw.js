// Tunatracker — app-shell service worker
// Bumping CACHE forces old service workers to be replaced on next visit
// (the activate handler purges every key that isn't the current CACHE).
var CACHE = 'tt-shell-v5';

// Map tiles live in their own cache so a shell bump doesn't throw them away.
// NASA GIBS sends even dated tiles with no-store, so without this every visit
// re-downloads the same SST/chlorophyll tiles. A tile whose URL carries a date
// (YYYY-MM-DD) never changes; Stadia basemap tiles are good for days. Capped
// at TILE_MAX entries, oldest first out.
var TILE_CACHE = 'tt-tiles-v1';
var TILE_MAX = 800;
var _DATED_GIBS = /gibs\.earthdata\.nasa\.gov\/.*\/\d{4}-\d{2}-\d{2}\//;
var _STADIA_TILE = /tiles\.stadiamaps\.com\/tiles\//;
var _tilePuts = 0;
function _trimTiles() {
  return caches.open(TILE_CACHE).then(function(c) {
    return c.keys().then(function(keys) {
      var extra = keys.length - TILE_MAX;
      return extra > 0 ? Promise.all(keys.slice(0, extra).map(function(k) { return c.delete(k); })) : null;
    });
  });
}
function _tileCacheFirst(req) {
  return caches.open(TILE_CACHE).then(function(c) {
    return c.match(req).then(function(hit) {
      if (hit) return hit;
      return fetch(req).then(function(res) {
        // Only real (CORS) 200s: an opaque copy costs ~7 MB of quota in Chrome.
        if (res && res.status === 200 && res.type === 'cors') {
          c.put(req, res.clone());
          if (++_tilePuts % 50 === 0) _trimTiles();
        }
        return res;
      });
    });
  });
}

// Regex for files that CHANGE without their URL changing. The daily scrape
// commits a fresh data.js roughly every hour but does NOT re-stamp the
// ?v= query in index.html (only full deploys via build-prod.py do that),
// so cache-first-by-URL leaves mobile users looking at hours-old counts.
// These files must be network-first with cache as an offline fallback.
var _MUTABLE_DATA = /\/(data\.js|data-region-[a-z0-9_]+\.js|ais_positions\.json|sst_grid\.json)(\?|$)/;

// Resources to pre-cache on install (app shell)
var SHELL = [
  '/',
  '/styles.css',
  '/logo.png',
  '/favicon.ico',
];

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(c) {
      return c.addAll(SHELL);
    }).catch(function() {}) // don't block install if any resource 404s
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE && k !== TILE_CACHE; }).map(function(k) { return caches.delete(k); })
      );
    })
  );
  self.clients.claim();
});

// respondWith MUST always receive a real Response — undefined causes
// "Failed to convert value to 'Response'" and breaks navigation.
function _cacheOrError(req) {
  return caches.match(req).then(function(r) { return r || Response.error(); });
}
function _cacheRootOrError() {
  return caches.match('/').then(function(r) { return r || Response.error(); });
}

self.addEventListener('fetch', function(e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = req.url;

  // Owner pages (behind Cloudflare Access) and the analytics collector: never cache.
  var swPath = new URL(url).pathname;
  if (swPath.indexOf('/owner/') === 0 || swPath.indexOf('/a/') === 0) return;

  // Immutable, version-pinned CDN libraries (Leaflet, React): cache-first.
  if (
    url.indexOf('/leaflet/1.9.4/') !== -1 ||
    url.indexOf('react@18.3.1') !== -1 ||
    url.indexOf('react-dom@18.3.1') !== -1
  ) {
    e.respondWith(
      caches.match(req).then(function(cached) {
        if (cached) return cached;
        return fetch(req).then(function(res) {
          if (res && (res.status === 200 || res.type === 'opaque')) {
            var clone = res.clone();
            caches.open(CACHE).then(function(c) { c.put(req, clone); });
          }
          return res;
        }).catch(function() { return _cacheOrError(req); });
      })
    );
    return;
  }

  // Map tiles: cache-first in the tile cache (see TILE_CACHE above).
  if (_DATED_GIBS.test(url) || _STADIA_TILE.test(url)) {
    e.respondWith(_tileCacheFirst(req).catch(function() { return fetch(req); }));
    return;
  }

  // Skip external API calls — always network
  if (
    url.includes('open-meteo.com') ||
    url.includes('erddap') ||
    url.includes('tidesandcurrents.noaa.gov') ||
    url.includes('aisstream.io') ||
    url.includes('clerk.accounts') ||
    url.includes('googletagmanager') ||
    url.includes('gibs.earthdata') ||
    url.includes('gebco.net') ||
    url.includes('cdnjs.cloudflare') ||
    url.includes('unpkg.com')
  ) return;

  // Mutable data files (rewritten by the hourly scrape) — network-first with
  // cache fallback. Must be checked BEFORE the ?v= cache-first branch below,
  // because data.js is loaded as `data.js?v=<hash>` and the hash only updates
  // on full deploys, not on hourly scrape commits.
  if (_MUTABLE_DATA.test(url)) {
    e.respondWith(
      fetch(req).then(function(res) {
        if (res && res.status === 200) {
          var clone = res.clone();
          caches.open(CACHE).then(function(c) { c.put(req, clone); });
        }
        return res;
      }).catch(function() { return _cacheOrError(req); })
    );
    return;
  }

  // HTML navigation: network-first, fall back to cached root
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req).catch(_cacheRootOrError)
    );
    return;
  }

  // Versioned assets (?v=...) and dist/ bundles: cache-first
  if (url.includes('?v=') || url.includes('/dist/') || url.includes('/lib/')) {
    e.respondWith(
      caches.match(req).then(function(cached) {
        if (cached) return cached;
        return fetch(req).then(function(res) {
          if (res && res.status === 200) {
            var clone = res.clone();
            caches.open(CACHE).then(function(c) { c.put(req, clone); });
          }
          return res;
        }).catch(function() { return _cacheOrError(req); });
      })
    );
    return;
  }

  // Static assets (logo, favicon, css): cache-first
  if (url.endsWith('.png') || url.endsWith('.ico') || url.endsWith('.css') || url.endsWith('.webmanifest')) {
    e.respondWith(
      caches.match(req).then(function(cached) {
        if (cached) return cached;
        return fetch(req).then(function(res) {
          if (res && res.status === 200) {
            var clone = res.clone();
            caches.open(CACHE).then(function(c) { c.put(req, clone); });
          }
          return res;
        }).catch(function() { return Response.error(); });
      })
    );
    return;
  }

  // Everything else: network-first, fall back to cache, never undefined
  e.respondWith(
    fetch(req).catch(function() { return _cacheOrError(req); })
  );
});
