(function () {
  var BASE = 'https://thetunatracker.com';
  var OG_IMAGE = BASE + '/logo.png';

  var CONFIG = {
    home: {
      title: 'The Tuna Tracker — San Diego Sportfishing Fish Counts & Boat Leaderboards',
      desc:  'Compare daily fish counts from every San Diego sportfishing boat. See who\'s catching tuna, yellowtail, and dorado — and book your next trip in one place.'
    },
    today: {
      title: 'Today\'s San Diego Fish Counts — Live Sportfishing Report | Tuna Tracker',
      desc:  'Live daily fish counts from H&M, Fisherman\'s, Seaforth, Point Loma, and Oceanside landings. Updated hourly with bluefin, yellowfin, and yellowtail counts.'
    },
    forecast: {
      title: 'San Diego Fishing Forecast — 7-Day Conditions | Tuna Tracker',
      desc:  'San Diego sportfishing forecast based on SST, wind, swell, and 11 years of catch history. Inshore and offshore predictions.'
    },
    boats: {
      title: 'San Diego Sportfishing Boats Directory | Tuna Tracker',
      desc:  'Browse every San Diego sportfishing boat with photos, reviews, win rates, and catch records across H&M, Fisherman\'s, Seaforth, Point Loma, and Oceanside.'
    },
    analytics: {
      title: 'San Diego Sportfishing Boat Analytics & Performance | Tuna Tracker',
      desc:  'Detailed analytics on 34+ San Diego sportfishing boats: win rates, average tuna per angler, seasonality, and head-to-head comparisons across 11 years of data.'
    },
    tripplanner: {
      title: 'Find the Best San Diego Sportfishing Trip — Trip Planner | Tuna Tracker',
      desc:  'Compare upcoming San Diego sportfishing trips by boat, price, trip length, and moon phase. Find the best value trip with the highest historical win rate.'
    },
    account: {
      title: 'My Account | Tuna Tracker',
      desc:  'Manage your Tuna Tracker preferences, region, and trophy species settings.'
    },
    charts: {
      title: 'Ocean Conditions Map — SST, Chlorophyll & Currents | Tuna Tracker',
      desc:  'Interactive ocean condition maps for Southern California fishing grounds. Sea surface temperature, chlorophyll, satellite imagery, and live current forecasts.',
    },
  };

  var ORG_LD = {
    '@context': 'https://schema.org', '@type': 'Organization',
    name: 'The Tuna Tracker', url: BASE,
    description: 'San Diego sportfishing analytics platform',
    areaServed: 'San Diego, California',
  };
  var SITE_LD = {
    '@context': 'https://schema.org', '@type': 'WebSite',
    name: 'The Tuna Tracker', url: BASE,
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

  function clearJsonLd(id) { var el = document.getElementById(id); if (el) el.remove(); }

  // ── main update ──────────────────────────────────────────────────────────

  function update(view, params) {
    params = params || {};
    var cfg, pageUrl = BASE + '/' + window.location.hash;

    if (view === 'boat' && params.boat) {
      cfg = {
        title: params.boat + ' — Fish Counts, Reviews & Schedule | Tuna Tracker',
        desc:  'View ' + params.boat + '\'s recent fish counts, win rate, and upcoming trip schedule' +
               (params.landing ? ' at ' + params.landing : '') + '.',
      };
      setJsonLd('jld-entity', {
        '@context': 'https://schema.org', '@type': 'Service',
        name: params.boat,
        provider: { '@type': 'Organization', name: params.landing || 'San Diego Sportfishing' },
        areaServed: 'San Diego, California',
        url: pageUrl,
      });
    } else {
      cfg = CONFIG[view] || CONFIG.today;
      clearJsonLd('jld-entity');
    }

    document.title = cfg.title;
    setMeta('description', cfg.desc);

    setMeta('og:title',       cfg.title,    'property');
    setMeta('og:description', cfg.desc,     'property');
    setMeta('og:url',         pageUrl,      'property');
    setMeta('og:image',       OG_IMAGE,     'property');
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

  function updateFromHash() {
    var raw  = window.location.hash.replace(/^#/, '');
    var slash = raw.indexOf('/');
    var first = slash === -1 ? raw : raw.slice(0, slash);
    var rest  = PREFIXES[first] && slash !== -1 ? raw.slice(slash + 1) : raw;
    var parts = rest.split('/');
    var seg   = parts[0] || 'home';
    var view  = VIEW_MAP[seg] || 'today';
    var params = {};
    if (seg === 'boat'    && parts[1]) params.boat    = decodeURIComponent(parts[1]);
    if (seg === 'landing' && parts[1]) params.landing = decodeURIComponent(parts[1]);
    update(view, params);
  }

  window.addEventListener('hashchange', updateFromHash);

  // Primary update: fire from React's route-change useEffect via __updateMetaTags.
  // Fallback: run on DOMContentLoaded (after React's initial mount + any replaceState
  // calls that don't fire hashchange) and immediately on script load for crawlers.
  updateFromHash();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updateFromHash);
  }

  window.__updateMetaTags = update;
})();
