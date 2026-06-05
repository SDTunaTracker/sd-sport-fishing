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

self.addEventListener('fetch', function(e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = req.url;

  // Immutable, version-pinned CDN libraries (Leaflet, React): cache-first.
  // These URLs never change for a given version, so a cached copy is always
  // valid — this makes the map appear instantly on repeat visits and offline.
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
        }).catch(function() { return caches.match(req); });
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
      fetch(req).catch(function() {
        return caches.match('/');
      })
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
        }).catch(function() { return caches.match(req); });
      })
    );
    return;
  }

  // Static assets (logo, favicon, css): cache-first
  if (url.endsWith('.png') || url.endsWith('.ico') || url.endsWith('.css') || url.endsWith('.webmanifest')) {
    e.respondWith(
      caches.match(req).then(function(cached) {
        return cached || fetch(req).then(function(res) {
          if (res && res.status === 200) {
            var clone = res.clone();
            caches.open(CACHE).then(function(c) { c.put(req, clone); });
          }
          return res;
        });
      })
    );
    return;
  }

  // Everything else: network-first
  e.respondWith(
    fetch(req).catch(function() { return caches.match(req); })
  );
});
