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
