// The Tuna Tracker — app-shell service worker
var CACHE = 'tt-shell-v2';

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
        keys.filter(function(k) { return k !== CACHE; }).map(function(k) { return caches.delete(k); })
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
