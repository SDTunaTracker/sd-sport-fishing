(function () {
  // Brand + domain live here only (mirrored in src/generate_pages.py and the
  // static head of web/index.html). See docs/seo/DOMAIN_MIGRATION.md.
  var BASE = 'https://thetunatracker.com';
  var SITE_NAME = 'Tunatracker';
  var OLD_NAMES = ['Tuna Tracker', 'The Tuna Tracker'];
  var OG_IMAGE = BASE + '/og-image.png';
  var SFX = ' | ' + SITE_NAME;

  var CONFIG = {
    home: {
      title: SITE_NAME + ' — San Diego Fish Counts & Sportfishing Boat Leaderboards',
      desc:  'Compare daily fish counts from every San Diego sportfishing boat. See who\'s catching tuna, yellowtail, and dorado — and book your next trip in one place.'
    },
    today: {
      title: 'Today\'s San Diego Fish Counts — Live Sportfishing Report' + SFX,
      desc:  'Today\'s fish counts from H&M, Fisherman\'s, Seaforth, Point Loma, and Oceanside landings, checked hourly: bluefin, yellowfin, yellowtail and dorado by boat.'
    },
    forecast: {
      title: 'San Diego Ocean Conditions' + SFX,
      desc:  'San Diego sportfishing ocean conditions: sea surface temperature, wind and swell.'
    },
    boats: {
      title: 'San Diego Sportfishing Boats Directory' + SFX,
      desc:  'Browse every San Diego sportfishing boat with photos, reviews, win rates, and catch records across H&M, Fisherman\'s, Seaforth, Point Loma, and Oceanside.'
    },
    analytics: {
      title: 'San Diego Sportfishing Boat Analytics & Performance' + SFX,
      desc:  'Analytics on 100+ San Diego sportfishing boats: win rates, fish per angler, seasonality, and head-to-head comparisons from catch data back to 2015.'
    },
    'analytics-finder': {
      title: 'Find the Best San Diego Sportfishing Boat for Your Trip' + SFX,
      desc:  'Pick your target species, trip length, and month — see which San Diego boats historically catch the most fish for those exact parameters.',
    },
    tripplanner: {
      title: 'Find the Best San Diego Sportfishing Trip — Trip Planner' + SFX,
      desc:  'Compare upcoming San Diego sportfishing trips by boat, price, trip length, and moon phase. Find the best value trip with the highest historical win rate.'
    },
    account: {
      title: 'My Account' + SFX,
      desc:  'Manage your ' + SITE_NAME + ' preferences, region, and trophy species settings.'
    },
    charts: {
      title: 'Ocean Conditions Map — SST & Chlorophyll' + SFX,
      desc:  'Interactive ocean condition maps for Southern California fishing grounds: sea surface temperature, chlorophyll, and satellite imagery.',
    },
  };

  // OC/LA region (/ocla/...) overrides. Keys missing here fall back to CONFIG.
  var OCLA_CONFIG = {
    home: {
      title: SITE_NAME + ' — Orange County, LA & Ventura Fish Counts & Boat Leaderboards',
      desc:  'Daily fish counts from Newport, Davey\'s Locker, Dana Wharf, 22nd Street, Long Beach, Redondo, Marina Del Rey, Pierpoint, Channel Islands and Ventura sportfishing boats, ranked fairly.'
    },
    today: {
      title: 'Today\'s Orange County, LA & Ventura Fish Counts — Sportfishing Report' + SFX,
      desc:  'Today\'s fish counts from Orange County, Los Angeles and Ventura County landings, by boat: yellowtail, tuna, calico bass, rockfish and more.'
    },
    boats: {
      title: 'Orange County, LA & Ventura Sportfishing Boats' + SFX,
      desc:  'Every Orange County, Los Angeles and Ventura County sportfishing boat with catch records, win rates and recent trips.'
    },
    analytics: {
      title: 'Orange County, LA & Ventura Sportfishing Analytics' + SFX,
      desc:  'Win rates, fish per angler, seasonality and head-to-head comparisons for Orange County, LA and Ventura County sportfishing boats.'
    },
    'analytics-finder': {
      title: 'Find the Best Orange County, LA & Ventura Sportfishing Boat' + SFX,
      desc:  'Pick your target species, trip length and month — see which Orange County and LA boats historically catch the most fish for those trips.'
    },
    tripplanner: {
      title: 'Orange County, LA & Ventura Sportfishing Trips' + SFX,
      desc:  'Find Orange County, LA and Ventura County sportfishing landings and book directly with them.'
    },
  };

  // City for a landing (boat/landing JSON-LD). Default San Diego.
  var LANDING_CITY = {
    'Oceanside Sea Center': 'Oceanside',
    '22nd Street Landing': 'San Pedro', 'LA Waterfront Sportfishing': 'San Pedro',
    'Long Beach Sportfishing': 'Long Beach', 'Marina Del Rey Sportfishing': 'Marina del Rey',
    'Redondo Beach Sportfishing': 'Redondo Beach', 'Pierpoint Landing': 'Long Beach',
    'Channel Islands Sportfishing': 'Oxnard', 'Ventura Harbor Sportfishing': 'Ventura',
    'Newport Landing': 'Newport Beach', "Davey's Locker": 'Newport Beach',
    'Dana Wharf Sportfishing': 'Dana Point',
  };

  // Same objects are baked into web/index.html (ids jld-org / jld-site).
  var ORG_LD = {
    '@context': 'https://schema.org', '@type': 'Organization',
    name: SITE_NAME, alternateName: OLD_NAMES, url: BASE,
    logo: BASE + '/logo.png',
    description: 'San Diego sportfishing analytics platform',
    areaServed: 'San Diego, California',
  };
  var SITE_LD = {
    '@context': 'https://schema.org', '@type': 'WebSite',
    name: SITE_NAME, alternateName: OLD_NAMES, url: BASE + '/',
  };

  // ── helpers ──────────────────────────────────────────────────────────────

  function setMeta(key, val, attr) {
    attr = attr || 'name';
    var el = document.querySelector('meta[' + attr + '="' + key + '"]');
    if (!el) { el = document.createElement('meta'); el.setAttribute(attr, key); document.head.appendChild(el); }
    el.setAttribute('content', val);
  }

  function setJsonLd(id, data) {
    var el = document.getElementById(id);
    if (!el) { el = document.createElement('script'); el.type = 'application/ld+json'; el.id = id; document.head.appendChild(el); }
    el.textContent = JSON.stringify(data);
  }

  function setCanonical(url) {
    var el = document.querySelector('link[rel="canonical"]');
    if (!el) { el = document.createElement('link'); el.setAttribute('rel', 'canonical'); document.head.appendChild(el); }
    el.setAttribute('href', url);
  }

  function clearJsonLd(id) { var el = document.getElementById(id); if (el) el.remove(); }

  // ── main update ──────────────────────────────────────────────────────────

  // Pages generated by src/generate_pages.py (<html data-prerendered>) ship a
  // better head (specific title/description, trailing-slash canonical, JSON-LD)
  // than this file can build. Leave it alone until the user navigates away.
  function normPath(p) {
    try { p = decodeURIComponent(p); } catch (e) {}
    return p.replace(/\/+$/, '') || '/';
  }
  var prerenderedPath = document.documentElement.hasAttribute('data-prerendered')
    ? normPath(window.location.pathname) : null;

  function update(view, params) {
    if (prerenderedPath !== null) {
      if (normPath(window.location.pathname) === prerenderedPath) return;
      prerenderedPath = null;
      document.documentElement.removeAttribute('data-prerendered');
      var robots = document.querySelector('meta[name="robots"]');
      if (robots) robots.remove();
      // Drop the page-specific JSON-LD (seo.js's own blocks carry ids).
      document.querySelectorAll('script[type="application/ld+json"]:not([id])')
        .forEach(function (el) { el.remove(); });
    }
    params = params || {};
    // Path-based canonical URL (e.g. https://thetunatracker.com/sd/today).
    var path = window.location.pathname.replace(/\/+$/, '');
    if (!path) path = '/';
    var cfg, pageUrl = BASE + path;

    if (view === 'boat' && params.boat) {
      var boatMeta = (window.SD && window.SD.BOATS && window.SD.BOATS.find(function(b) { return b.name === params.boat; })) || null;
      var landingName = (boatMeta && boatMeta.landing) || params.landing || 'San Diego Sportfishing';
      var city = LANDING_CITY[landingName] || 'San Diego';
      cfg = {
        title: params.boat + ' Fish Report & Counts — ' + landingName + SFX,
        desc:  'View ' + params.boat + '\'s recent fish counts, win rate, and upcoming trip schedule at ' + landingName + '.',
      };
      var jldBoat = {
        '@context': 'https://schema.org', '@type': 'LocalBusiness',
        name: params.boat,
        description: 'Sportfishing charter boat operating out of ' + landingName + ', ' + city + '.',
        url: pageUrl,
        address: {
          '@type': 'PostalAddress',
          addressLocality: city, addressRegion: 'CA', addressCountry: 'US',
        },
        parentOrganization: { '@type': 'Organization', name: landingName },
      };
      var rv = window.SD && window.SD.REVIEWS && window.SD.REVIEWS.summary && window.SD.REVIEWS.summary[params.boat];
      if (rv && rv.total_reviews >= 3 && rv.avg_overall) {
        jldBoat.aggregateRating = {
          '@type': 'AggregateRating',
          ratingValue: rv.avg_overall.toFixed(1),
          reviewCount: rv.total_reviews,
          bestRating: '5', worstRating: '1',
        };
      }
      setJsonLd('jld-entity', jldBoat);
    } else if (view === 'landing' && params.landing) {
      var lcity = LANDING_CITY[params.landing] || 'San Diego';
      cfg = {
        title: params.landing + ' Fish Counts — Fleet & Boat Stats' + SFX,  // matches src/generate_pages.py
        desc:  'Daily fish counts, boat rankings and catch history for every boat at ' + params.landing + ' in ' + lcity + ', CA.',
      };
      clearJsonLd('jld-entity');
    } else {
      var cfgKey = (view === 'analytics' && params.subtab) ? 'analytics-' + params.subtab : view;
      var isOcla = /^\/ocla(\/|$)/.test(path);
      cfg = (isOcla && (OCLA_CONFIG[cfgKey] || OCLA_CONFIG[view]))
        || CONFIG[cfgKey] || CONFIG[view] || CONFIG.today;
      clearJsonLd('jld-entity');
    }

    document.title = cfg.title;
    setMeta('description', cfg.desc);
    setCanonical(pageUrl);

    setMeta('og:title',       cfg.title,    'property');
    setMeta('og:description', cfg.desc,     'property');
    setMeta('og:url',         pageUrl,      'property');
    setMeta('og:image',       OG_IMAGE,     'property');
    setMeta('og:site_name',   SITE_NAME,    'property');
    setMeta('twitter:title',       cfg.title);
    setMeta('twitter:description', cfg.desc);

    if (view === 'home') {
      setJsonLd('jld-org',  ORG_LD);
      setJsonLd('jld-site', SITE_LD);
    } else {
      clearJsonLd('jld-org');
      clearJsonLd('jld-site');
    }
  }

  // ── route parsing (mirrors app.jsx logic) ────────────────────────────────

  var PREFIXES = { sd: 1, ocla: 1, 'sd+ocla': 1 };
  var VIEW_MAP = {
    home: 'home', today: 'today', forecast: 'forecast', boats: 'boats',
    analytics: 'analytics', tripplanner: 'tripplanner', charts: 'charts',
    account: 'account', settings: 'account', boat: 'boat', landing: 'landing',
  };

  function updateFromLocation() {
    // Prefer the pathname; fall back to a legacy #hash for old URLs.
    var raw = window.location.pathname.replace(/^\/+/, '').replace(/\/+$/, '');
    if (!raw) raw = window.location.hash.replace(/^#/, '');
    var slash = raw.indexOf('/');
    var first = slash === -1 ? raw : raw.slice(0, slash);
    var rest  = PREFIXES[first] && slash !== -1 ? raw.slice(slash + 1) : raw;
    var parts = rest.split('/');
    var seg   = parts[0] || 'home';
    var view  = VIEW_MAP[seg] || 'today';
    var params = {};
    if (seg === 'boat'      && parts[1]) params.boat    = decodeURIComponent(parts[1]);
    if (seg === 'landing'   && parts[1]) params.landing = decodeURIComponent(parts[1]);
    if (seg === 'analytics' && parts[1]) params.subtab  = parts[1];
    update(view, params);
  }

  // Browser navigation (back/forward) + legacy hash changes.
  window.addEventListener('popstate', updateFromLocation);
  window.addEventListener('hashchange', updateFromLocation);

  // Primary update: fire from React's route-change useEffect via __updateMetaTags.
  // Fallback: run on DOMContentLoaded (after React's initial mount + any replaceState
  // calls that don't fire events) and immediately on script load for crawlers.
  updateFromLocation();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updateFromLocation);
  }

  window.__updateMetaTags = update;
})();
