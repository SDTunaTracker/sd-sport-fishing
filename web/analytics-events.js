// TTTrack — central event tracking helper + localStorage click log.
// Loaded before all JSX so every component can call TTTrack.*
// All gtag calls are guarded so the page degrades gracefully if GA fails.
window.TTTrack = {

  // ── GA events ─────────────────────────────────────────────────────────────

  tripClick: function(trip, context) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'trip_click', {
        boat_name:      trip.boat,
        landing:        trip.landing,
        trip_length:    trip.tripLength,
        departure_date: trip.departureAt ? trip.departureAt.slice(0, 10) : null,
        return_date:    trip.returnAt    ? trip.returnAt.slice(0, 10)    : null,
        price:          trip.price,
        open_spots:     trip.openSpots,
        max_load:       trip.capacity,
        moon_phase:     trip.moonPhase  || null,
        win_rate:       trip._winRate   != null ? Math.round(trip._winRate * 100) : null,
        tab_active:     context.tab     || null,
        list_position:  context.position || null,
        filters_active: context.filters  || 0,
        month_selected: context.month    || null,
      });
    }
    TTTrack._logClick(trip, context);
  },

  filterApplied: function(filterType, value) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'filter_applied', {
        filter_type:  filterType,
        filter_value: Array.isArray(value) ? value.join(',') : String(value),
      });
    }
  },

  tabSwitch: function(tab) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'tab_switch', { tab_name: tab });
    }
  },

  forecastView: function(segment, score) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'forecast_view', {
        segment:    segment,
        score:      score,
        conditions: score >= 7 ? 'good' : score >= 5 ? 'average' : 'poor',
      });
    }
  },

  boatView: function(boatName, landing) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'boat_view', { boat_name: boatName, landing: landing });
    }
  },

  pageView: function(page) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'page_view', { page_name: page });
    }
  },

  // ── UTM builder ────────────────────────────────────────────────────────────
  // Appends utm_* params to any outbound URL. Handles existing ? and # fragments.
  buildUrl: function(baseUrl, boat, landing, tripDate) {
    if (!baseUrl) return baseUrl;
    var params = new URLSearchParams({
      utm_source:   'thetunatracker',
      utm_medium:   'trip_planner',
      utm_campaign: (landing || '').toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, ''),
      utm_content:  (boat    || '').toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, ''),
      utm_term:     tripDate || '',
    });
    // Insert before any # fragment so UTM lands in the query string, not the hash.
    var hashIdx = baseUrl.indexOf('#');
    var base    = hashIdx >= 0 ? baseUrl.slice(0, hashIdx) : baseUrl;
    var frag    = hashIdx >= 0 ? baseUrl.slice(hashIdx)    : '';
    var sep     = base.includes('?') ? '&' : '?';
    return base + sep + params.toString() + frag;
  },

  // ── localStorage click log (admin dashboard source of truth) ──────────────

  _logClick: function(trip, context) {
    try {
      var clicks = JSON.parse(localStorage.getItem('tt_clicks') || '[]');
      clicks.push({
        ts:            new Date().toISOString(),
        boat:          trip.boat,
        landing:       trip.landing,
        tripLength:    trip.tripLength,
        price:         trip.price,
        tab:           context.tab      || null,
        position:      context.position || null,
        forecastScore: trip.forecastScore || null,
      });
      if (clicks.length > 500) clicks.shift();
      localStorage.setItem('tt_clicks', JSON.stringify(clicks));
    } catch(e) {}
  },

  chatOpen: function() {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'chat_open');
    }
  },

  chatMessage: function(question, pageContext) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'chat_message', {
        page:             pageContext?.page || 'unknown',
        has_boat_context: !!pageContext?.boat,
        question_length:  question.length,
      });
    }
  },

  chatLimitHit: function() {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'chat_limit_hit');
    }
  },

  chatLinkClick: function(linkText, url, isExternal) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'chat_link_click', {
        link_text: linkText,
        link_type: isExternal ? 'external_booking' : 'internal_page',
        destination: url,
      });
    }
  },

  chatAction: function(actionType, data) {
    if (typeof gtag !== 'undefined') {
      gtag('event', 'chat_action', {
        action_type: actionType,
        action_data: typeof data === 'string' ? data : JSON.stringify(data),
      });
    }
  },

  getClickStats: function() {
    try {
      var clicks = JSON.parse(localStorage.getItem('tt_clicks') || '[]');
      var byLanding = {}, byBoat = {}, byTab = { best: 0, cheapest: 0 }, byDay = {};
      clicks.forEach(function(c) {
        if (c.landing) byLanding[c.landing] = (byLanding[c.landing] || 0) + 1;
        if (c.boat)    byBoat[c.boat]       = (byBoat[c.boat]       || 0) + 1;
        if (c.tab)     byTab[c.tab]         = (byTab[c.tab]         || 0) + 1;
        var day = (c.ts || '').slice(0, 10);
        if (day) byDay[day] = (byDay[day] || 0) + 1;
      });
      return {
        total:     clicks.length,
        byLanding: byLanding,
        byBoat:    byBoat,
        byTab:     byTab,
        byDay:     byDay,
        recent:    clicks.slice(-20).reverse(),
        raw:       clicks,
      };
    } catch(e) { return null; }
  },
};

// Memory pressure monitor — logs to GA when JS heap exceeds 200 MB.
// Helps identify devices hitting memory limits before they get a blank page.
(function () {
  if (!window.performance || !performance.memory) return;
  var warned = false;
  setInterval(function () {
    var mb = performance.memory.usedJSHeapSize / 1048576;
    if (mb > 200 && !warned) {
      warned = true;
      if (typeof gtag !== 'undefined') {
        gtag('event', 'high_memory_warning', { memory_mb: Math.round(mb) });
      }
    }
  }, 30000);
})();

// ─── First-party visit statistics (Tunatracker's own, no cookies) ───────────
// Sends small batched beacons to /a/e (cloudflare-worker/analytics.js), which
// feeds the owner dashboard at /owner/. Runs alongside GA4 during the overlap.
//   - Nothing is sent when Global Privacy Control or Do Not Track is on.
//   - No cookies and no ids. One date is stored (localStorage "tt_seen") so a
//     returning visitor isn't counted as new; we send only "days since your last
//     visit" on the first page of each day.
//   - Paths drop query strings, and referrers are reduced to the site name.
//   - Only sends on thetunatracker.com (not localhost or previews), unless
//     window.TT_ANALYTICS_ENDPOINT is set for local testing.
// It wraps existing TTTrack helpers, so call sites don't change, and helpers
// added later in this file (e.g. Co-Captain's chatBookClick) are picked up too.
(function () {
  var TT = window.TTTrack;
  if (!TT) return;
  var host = location.hostname;
  var endpoint = window.TT_ANALYTICS_ENDPOINT ||
    ((host === 'thetunatracker.com' || host === 'www.thetunatracker.com') ? '/a/e' : null);
  function optedOut() {
    try {
      // The owner's own browsers (marked when they open /owner/) aren't counted.
      if (localStorage.getItem('tt_owner') === '1') return true;
    } catch (e) {}
    try {
      return navigator.globalPrivacyControl === true ||
        navigator.doNotTrack === '1' || window.doNotTrack === '1' || navigator.msDoNotTrack === '1';
    } catch (e) { return false; }
  }
  var enabled = !!endpoint && !optedOut();
  TT.firstParty = { enabled: enabled };
  TT._send = function () {};
  if (!enabled) return;

  var src = 'web';
  try {
    if ((window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone) src = 'pwa';
  } catch (e) {}
  var queue = [], timer = null, entrySent = false, gapFallbackSent = false, lastPath = null;

  function localDay(d) {
    d = d || new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  // Days since this browser's previous visit, on the first pageview of a day; otherwise null.
  function visitGap() {
    try {
      var today = localDay(), last = localStorage.getItem('tt_seen');
      if (last === today) return null;
      localStorage.setItem('tt_seen', today);
      if (!last) return 400;
      var g = Math.round((Date.parse(today) - Date.parse(last)) / 864e5);
      return g >= 1 && g <= 400 ? g : 400;
    } catch (e) {
      // Storage blocked: count once per page load (the dashboard notes this overcounts).
      if (gapFallbackSent) return null;
      gapFallbackSent = true;
      return 400;
    }
  }
  function referrer() {
    var utm = null;
    try { utm = new URLSearchParams(location.search).get('utm_source'); } catch (e) {}
    if (utm) return 'utm:' + utm.slice(0, 40);
    try {
      if (!document.referrer) return '';
      var h = new URL(document.referrer).hostname;
      return h === host ? '' : h;
    } catch (e) { return ''; }
  }
  function flush() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!queue.length) return;
    var body = JSON.stringify({ src: src, w: (window.screen && screen.width) || window.innerWidth || 0, ev: queue.splice(0, 25) });
    try {
      var sent = navigator.sendBeacon && navigator.sendBeacon(endpoint, new Blob([body], { type: 'application/json' }));
      if (!sent && window.fetch) {
        fetch(endpoint, { method: 'POST', body: body, keepalive: true, headers: { 'Content-Type': 'application/json' } })
          .catch(function () {});
      }
    } catch (e) {}
    if (queue.length) flush();
  }
  function send(t, props) {
    var e = { t: t, p: location.pathname };
    if (props) for (var k in props) if (props[k] != null && props[k] !== '') e[k] = props[k];
    // One booking hand-off can fire two helpers (chatBookClick + chatLinkClick 'Book'); merge them.
    var prev = queue[queue.length - 1];
    if (prev && prev.t === t && t === 'chat_book_click' && Date.now() - prev._at < 1500) {
      for (var j in e) if (prev[j] == null) prev[j] = e[j];
      return;
    }
    Object.defineProperty(e, '_at', { value: Date.now(), enumerable: false });
    queue.push(e);
    if (queue.length >= 20) flush();
    else if (!timer) timer = setTimeout(flush, t === 'pageview' ? 3000 : 1500);
  }
  TT._send = send;

  function pageview() {
    var p = location.pathname;
    if (p === lastPath) return;
    lastPath = p;
    var props = { g: visitGap() };
    if (!entrySent) { entrySent = true; props.e = 1; props.r = referrer(); }
    send('pageview', props);
  }

  // SPA navigation: app.jsx uses history.pushState + popstate. replaceState is
  // used for the region prefix and hash upgrades, so it isn't a new pageview.
  var push = history.pushState;
  history.pushState = function () {
    var r = push.apply(this, arguments);
    setTimeout(pageview, 0);
    return r;
  };
  window.addEventListener('popstate', function () { setTimeout(pageview, 0); });
  // First pageview after the app has routed (it may rewrite #hash URLs to paths).
  if (document.readyState === 'complete') setTimeout(pageview, 0);
  else window.addEventListener('load', function () { setTimeout(pageview, 0); });

  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') flush(); });
  window.addEventListener('pagehide', flush);

  // Helper → first-party event. Only public catalog data (boat, landing, trip id).
  var lastBoat = { name: null, at: 0 };
  var MAP = {
    boatView: function (boat, landing) {
      // Boat cards fire this on click and the boat page fires it again on mount.
      if (boat === lastBoat.name && Date.now() - lastBoat.at < 5000) return null;
      lastBoat = { name: boat, at: Date.now() };
      return ['boat_view', { boat: boat, landing: landing }];
    },
    tripClick: function (trip) {
      trip = trip || {};
      return ['book_click', { boat: trip.boat, landing: trip.landing, trip: trip.sourceId || trip.tripId || null, k: 'planner' }];
    },
    chatOpen: function () { return ['chat_open']; },
    chatMessage: function () { return ['chat_message']; },
    chatLinkClick: function (text, url, isExternal) {
      return isExternal ? ['chat_book_click', { k: 'chat_link' }] : null;
    },
    chatRecommend: function () { return ['chat_recommend']; },
    chatBookIntent: function (p) { p = p || {}; return ['chat_book_intent', { boat: p.boat, landing: p.landing, trip: p.tripId }]; },
    chatBookClick: function (p) { p = p || {}; return ['chat_book_click', { boat: p.boat, landing: p.landing, trip: p.tripId, k: 'chat_card' }]; },
  };
  Object.keys(MAP).forEach(function (name) {
    var orig = TT[name];
    if (typeof orig !== 'function') return;
    TT[name] = function () {
      try { var ev = MAP[name].apply(null, arguments); if (ev) send(ev[0], ev[1]); } catch (e) {}
      return orig.apply(this, arguments);
    };
  });

  // Sign-ups: Clerk reports the new user; we send only that a sign-up happened.
  window.addEventListener('clerk-auth-change', function (e) {
    try {
      var u = e.detail && e.detail.user;
      var created = u && u.createdAt ? new Date(u.createdAt).getTime() : 0;
      if (!created || Date.now() - created > 10 * 60e3) return;
      if (sessionStorage.getItem('tt_signup_sent')) return;
      sessionStorage.setItem('tt_signup_sent', '1');
      send('signup');
    } catch (err) {}
  });
})();
