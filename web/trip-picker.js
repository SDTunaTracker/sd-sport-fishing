// Trip picker: "what's the best trip to book?" as a plain answer.
//
// One pure ranking used by the "Pick my trip" card, the answers at the top of
// Today, and Co-Captain. It ranks SCHEDULED trips that still have seats, using
// only OBSERVED catch data (no forecast scores: forecasting is R&D only):
//   - the boat's recent catch rate on the same kind of trip over one shared
//     window (last 14 days, widening to 30/60, or 30-120 for long range, until
//     most candidate boats have 3+ trips),
//     shrunk toward the fleet average so one lucky trip can't win;
//   - its consistency: how often it beat the fleet's median on those trips;
//   - boats with fewer than 3 recent trips of the type rank after boats with
//     a full sample (they are a "lean", and the reason says so);
//   - a small nudge for price and for nearly-full boats;
//   - NWS small-craft advisories are returned as a WARNING, never scored.
//
// API (also window.TTPicker):
//   pickTrips(query, data?) -> { best, alternates[], considered, noData, scheduled, reason, query }
//     reason when best is null: 'no-schedule' | 'no-match' | 'no-species'
//     (a species query drops boats under 0.05 of that species per angler)
//     (scheduled = future departures in the region of any type; 0 means the
//      region has no schedule data, which is different from "none match")
//     query: { type, from, to, species?, maxPrice?, region?, now? }
//       type    'full' | 'overnight' | '1.5' | 'multi' | 'long', an exact
//               trip length ('Full Day', '2 Day', ...), or an array of those
//       from/to 'YYYY-MM-DD' (Pacific dates, inclusive; default next 7 days)
//       days: optional ['YYYY-MM-DD', ...] — only departures on these days
//             (multi-select in Pick dates); from/to become its first/last day
//       species 'Bluefin' | 'Yellowfin' | 'Yellowtail' | 'Dorado' | 'Tuna' | ... (optional;
//       'Tuna' = bluefin + yellowfin)
//       maxPrice number, dollars (optional)
//       region  'san_diego' (default) | 'oc_la' | 'all_socal' | 'sf_bay'
//       now     ms timestamp (tests); defaults to Date.now()
//     data (all optional): { schedule, trips, marine, landingsFor(region),
//       bookingUrl(trip), metric } — defaults read window.SD,
//       window.getLandingsForRegion and window.ccBookingInfo. SF Bay rows carry
//       their own limit rate in .rate: pass metric: 'limitRate'.
//     Each answer: { boat, landing, tripLength, departureAt, returnAt, dateLabel,
//       price, openSpots, rate, fleetRate, samples, windowDays, beatFleet, noun,
//       metric, bookingUrl, sourceId, advisory|null, reason }
//   whatsBiting(query, data?) -> { region, days, trips, anglers,
//       items: [{ species, fish, perAngler, tripsWithCatch, change|null }] }
//   presets(now?) -> { weekend: {from,to,label}, next7: {from,to,label} }
//   QUICK_PICKS [{ id, label, type, range, maxPrice?, species? }] and
//   quickQuery(id, { region?, now? }) -> a pickTrips query for that shortcut
//   TRIP_TYPES, typeOf(tripLength, days)
(function (root) {
  'use strict';

  var DAY = 86400000;

  var TRIP_TYPES = [
    { id: 'full',      label: 'Full day',   noun: 'full day',        nounPl: 'full days' },
    { id: 'overnight', label: 'Overnight',  noun: 'overnight',       nounPl: 'overnights' },
    { id: '1.5',       label: '1.5 day',    noun: '1.5-day trip',    nounPl: '1.5-day trips' },
    { id: 'multi',     label: '2–3 day',    noun: '2–3 day trip',    nounPl: '2–3 day trips' },
    { id: 'long',      label: 'Long range', noun: 'long-range trip', nounPl: 'long-range trips' },
  ];
  var TYPE_BY_ID = {};
  TRIP_TYPES.forEach(function (t) { TYPE_BY_ID[t.id] = t; });

  // Sample windows (days back from now) tried in order until a boat has
  // MIN_SAMPLES trips of this type. Long range runs less often.
  var WINDOWS = { def: [14, 30, 60], long: [30, 60, 120] };
  var MIN_SAMPLES = 3;
  var SHRINK_K = 2;          // pseudo-trips of fleet average blended into each boat
  var TROPHY = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];
  var ALL_SPECIES_REGIONS = { oc_la: true };
  var SPECIES_FLOOR = 0.05;  // fish per angler (per day) below which a boat isn't "landing" a species

  function daysOf(len) {
    if (!len) return null;
    if (len === 'Full Day') return 0.75;
    if (len === 'Overnight') return 1;
    if (len === 'Long Range') return 8;
    var m = /^(\d+(?:\.\d+)?)\s*Day/.exec(len);
    return m ? +m[1] : null;
  }

  function typeOf(tripLength, days) {
    var d = days != null ? days : daysOf(tripLength);
    if (tripLength === 'Full Day' || (d != null && d < 1)) return 'full';
    if (tripLength === 'Overnight' || d === 1) return 'overnight';
    if (d === 1.5) return '1.5';
    if (d != null && d >= 2 && d < 4) return 'multi';
    if (d != null && d >= 4) return 'long';
    return null;
  }

  // Does a trip length match the requested type(s)?
  function matcher(type) {
    var list = Array.isArray(type) ? type : [type];
    return function (len, days) {
      for (var i = 0; i < list.length; i++) {
        var q = list[i];
        if (q === len) return true;
        if (TYPE_BY_ID[q] && typeOf(len, days) === q) return true;
      }
      return false;
    };
  }

  // Pacific calendar date of an ISO timestamp ('YYYY-MM-DD').
  var _pacFmt = null;
  function pacificDate(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d)) return null;
    try {
      _pacFmt = _pacFmt || new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit' });
      return _pacFmt.format(d);
    } catch (e) { return String(iso).slice(0, 10); }
  }
  function isoDay(ms) { return pacificDate(new Date(ms).toISOString()); }
  function addDays(ymd, n) {
    var p = ymd.split('-').map(Number);
    return new Date(Date.UTC(p[0], p[1] - 1, p[2] + n, 12)).toISOString().slice(0, 10);
  }

  // Fish counted for a trip under this query.
  // "Tuna" groups the tunas anglers book for (bluefin + yellowfin).
  function fishFn(species, region) {
    if (species === 'Tuna') {
      var one = fishFn('Bluefin', region), two = fishFn('Yellowfin', region);
      return function (t) { return one(t) + two(t); };
    }
    if (species) {
      return function (t) {
        if (t[species] != null) return +t[species] || 0;
        return (t.fullCatch && +t.fullCatch[species]) || 0;
      };
    }
    if (ALL_SPECIES_REGIONS[region]) {
      return function (t) {
        if (t.fullCatch) { var n = 0; for (var k in t.fullCatch) n += +t.fullCatch[k] || 0; return n; }
        return t.trophyCount || 0;
      };
    }
    return function (t) {
      return t.trophyCount != null ? t.trophyCount : TROPHY.reduce(function (s, x) { return s + (t[x] || 0); }, 0);
    };
  }
  function nounFor(species, region, metric) {
    if (metric === 'limitRate') return 'of limits';
    if (species) return species.toLowerCase();
    return 'fish';   // owner wording (#13): "fish", not "trophy fish"
  }

  function defaults(data) {
    var w = root || {};
    var SD = w.SD || {};
    data = data || {};
    return {
      schedule: data.schedule || SD.SCHEDULE || [],
      trips: data.trips || w.SD_PROC_TRIPS || SD.TRIPS || [],
      marine: data.marine !== undefined ? data.marine : null,
      marineFor: data.marineFor || function (region) {
        var by = SD.MARINE_BY_REGION || {};
        return by[region] || (region === 'san_diego' || !region ? SD.MARINE : null) || null;
      },
      landingsFor: data.landingsFor || function (region) {
        if (!region || region === 'all') return null;
        if (typeof w.getLandingsForRegion === 'function') {
          var l = w.getLandingsForRegion(region);
          if (l && l.length) return l;
        }
        return null;
      },
      bookingUrl: data.bookingUrl || function (t) {
        if (typeof w.ccBookingInfo === 'function') { try { return w.ccBookingInfo(t).url || null; } catch (e) {} }
        return null;
      },
      metric: data.metric || null,
    };
  }

  // Row-level region test when no landing list is available. Rows without a
  // region field are base-region (San Diego) rows, never another region's.
  function regionMatch(t, region) {
    if (region === 'all') return true;
    var r = t.region || 'san_diego';
    if (region === 'all_socal') return r !== 'sf_bay';
    return r === region;
  }

  function seatsOf(t) {
    if (t.openSpots != null) return t.openSpots;
    if (t.capacity != null) return t.capacity - (t.reservedSpots || 0);
    return null;
  }

  function median(xs) {
    if (!xs.length) return 0;
    var s = xs.slice().sort(function (a, b) { return a - b; });
    var m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  function round(x, n) { var p = Math.pow(10, n); return Math.round(x * p) / p; }
  function fmtRate(x, metric) {
    if (metric === 'limitRate') return Math.round(x * 100) + '%';
    return x >= 10 ? String(Math.round(x)) : x.toFixed(1);
  }
  function fmtDate(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    try { return d.toLocaleDateString('en-US', { timeZone: 'America/Los_Angeles', weekday: 'short', month: 'short', day: 'numeric' }); }
    catch (e) { return String(iso).slice(0, 10); }
  }

  // Small-craft advisory overlapping the trip, from NWS alerts (warning only).
  function advisoryFor(marine, trip, now) {
    if (!marine) return null;
    var alerts = marine.alerts || [];
    var dep = new Date(trip.departureAt).getTime();
    var ret = trip.returnAt ? new Date(trip.returnAt).getTime() : dep + DAY;
    for (var i = 0; i < alerts.length; i++) {
      var a = alerts[i] || {};
      var sca = a.smallCraftAdvisory || /small craft|gale|storm|hazardous seas/i.test(a.event || a.headline || '');
      if (!sca) continue;
      var on = a.onset || a.effective || a.start, off = a.ends || a.expires || a.end;
      var s = on ? new Date(on).getTime() : -Infinity, e = off ? new Date(off).getTime() : Infinity;
      if (s <= ret && e >= dep) return { event: a.event || 'Small Craft Advisory', ends: off || null, headline: a.headline || null };
    }
    if (!alerts.length && marine.smallCraftAdvisory === true && dep - now < 2 * DAY) {
      return { event: 'Small Craft Advisory', ends: null, headline: null };
    }
    return null;
  }

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : (many || one + 's')); }

  function reasonFor(s, noun, metric, idx) {
    if (!s.hasData) {
      return s.boat + " hasn't reported a trip like this recently, so this is just the next open seat.";
    }
    var std = { 'Full Day': 'full', 'Overnight': 'overnight', '1.5 Day': '1.5' }[s.tripLength];
    var ty = std ? TYPE_BY_ID[std] : null;
    var one = ty ? ty.noun : s.tripLength.toLowerCase() + ' trip', many = ty ? ty.nounPl : one + 's';
    var multiDay = (daysOf(s.tripLength) || 1) > 1;
    var per = metric === 'limitRate' ? '' : ' per angler' + (multiDay ? ' per day' : '');
    var line = s.boat + ' averaged ' + fmtRate(s.rate, metric) + ' ' + noun + per + ' on ' +
      (s.samples === 1 ? '1 ' + one : s.samples + ' ' + many) + ' in the last ' + s.windowDays +
      ' days (fleet: ' + fmtRate(s.fleetRate, metric) + ')';
    if (s.samples >= 2) line += ', beating the fleet median on ' + s.beatFleet + ' of them';
    line += '.';
    if (s.samples < MIN_SAMPLES) line += ' Only ' + plural(s.samples, 'recent trip') + ', so treat it as a lean.';
    else if (idx === 0 && s.rate < s.fleetRate) line += ' The boats catching more have no open seats in these dates.';
    return line;
  }

  function pickTrips(query, data) {
    query = query || {};
    var D = defaults(data);
    var now = query.now != null ? query.now : Date.now();
    var region = query.region || 'san_diego';
    var metric = D.metric;
    var match = matcher(query.type || 'full');
    var nowDay = isoDay(now);
    var days = Array.isArray(query.days) && query.days.length ? query.days.slice().sort() : null;
    var daySet = days ? {} : null;
    if (days) days.forEach(function (d) { daySet[d] = true; });
    var from = days ? days[0] : (query.from || nowDay);
    var to = days ? days[days.length - 1] : (query.to || addDays(from, 6));
    var landings = D.landingsFor(region);
    var inRegion = function (t) {
      if (landings) return landings.indexOf(t.landing) >= 0;
      return regionMatch(t, region);
    };
    var fish = fishFn(query.species, region);
    var rateOf = metric === 'limitRate'
      ? function (t) { return t.rate != null ? +t.rate : null; }
      : function (t) {
          var a = t.anglers > 0 ? t.anglers : 0;
          if (!a) return null;
          var d = t.tripLengthDays > 0 ? t.tripLengthDays : (daysOf(t.tripLength) || 1);
          return fish(t) / a / d;
        };

    // 1) Candidates: scheduled, in range, seats left, within budget.
    var scheduled = 0;
    D.schedule.forEach(function (t) {
      if (t && t.departureAt && inRegion(t) && new Date(t.departureAt).getTime() > now) scheduled++;
    });
    var cands = D.schedule.filter(function (t) {
      if (!t || !t.departureAt || !inRegion(t)) return false;
      if (!match(t.tripLength, t.tripLengthDays)) return false;
      if (!(new Date(t.departureAt).getTime() > now)) return false;
      var day = pacificDate(t.departureAt);
      if (daySet ? !daySet[day] : (day < from || day > to)) return false;
      var seats = seatsOf(t);
      if (seats != null && seats <= 0) return false;
      if (/full|cancel/i.test(String(t.tripStatus || '')) || t.bookable === false) return false;
      if (query.maxPrice != null && t.price != null && t.price > query.maxPrice) return false;
      return true;
    });

    var result = {
      best: null, alternates: [], considered: cands.length, noData: 0, scheduled: scheduled, reason: null,
      query: { type: query.type || 'full', from: from, to: to, days: days, species: query.species || null,
               maxPrice: query.maxPrice != null ? query.maxPrice : null, region: region },
    };
    if (!cands.length) { result.reason = scheduled ? 'no-match' : 'no-schedule'; return result; }

    // 2) Recent observed trips of the same type in this region.
    var types = {};
    cands.forEach(function (t) { types[typeOf(t.tripLength, t.tripLengthDays)] = true; });
    var windows = types.long && Object.keys(types).length === 1 ? WINDOWS.long : WINDOWS.def;
    var maxBack = windows[windows.length - 1];
    var oldest = isoDay(now - maxBack * DAY);
    var recent = [];
    for (var i = 0; i < D.trips.length; i++) {
      var t = D.trips[i];
      if (!t || !t.date || t.date < oldest || t.date > nowDay) continue;
      if (!inRegion(t) || !match(t.tripLength, t.tripLengthDays)) continue;
      var r = rateOf(t);
      if (r == null || !isFinite(r)) continue;
      recent.push({ boat: t.boat, rate: r, ageDays: (now - Date.parse(t.date + 'T20:00:00Z')) / DAY });
    }

    // 3) One sample window for the whole query, so every boat is compared on
    //    the same days against the same fleet: the shortest window in which
    //    most candidate boats (up to 3) have a full sample.
    var byBoat = {};
    recent.forEach(function (x) { (byBoat[x.boat] || (byBoat[x.boat] = [])).push(x); });
    var candBoats = Object.keys(cands.reduce(function (m, t) { m[t.boat] = 1; return m; }, {}));
    var need = Math.min(3, Math.ceil(candBoats.length / 2));
    var winDays = maxBack;
    for (var w = 0; w < windows.length; w++) {
      var ok = candBoats.filter(function (b) {
        return (byBoat[b] || []).filter(function (x) { return x.ageDays <= windows[w]; }).length >= MIN_SAMPLES;
      }).length;
      if (ok >= need) { winDays = windows[w]; break; }
    }
    function boatStats(boat) {
      return { samples: (byBoat[boat] || []).filter(function (x) { return x.ageDays <= winDays; }), windowDays: winDays };
    }
    var fleetCache = {};
    function fleetFor(win) {
      if (fleetCache[win]) return fleetCache[win];
      var xs = recent.filter(function (x) { return x.ageDays <= win; }).map(function (x) { return x.rate; });
      var mean = xs.length ? xs.reduce(function (a, b) { return a + b; }, 0) / xs.length : 0;
      return (fleetCache[win] = { mean: mean, median: median(xs), n: xs.length });
    }

    var prices = cands.map(function (t) { return t.price; }).filter(function (p) { return p != null; });
    var pMin = prices.length ? Math.min.apply(null, prices) : 0;
    var pMax = prices.length ? Math.max.apply(null, prices) : 0;

    var scored = cands.map(function (t) {
      var st = boatStats(t.boat);
      var n = st.samples.length;
      var fleet = fleetFor(st.windowDays);
      var avg = n ? st.samples.reduce(function (a, x) { return a + x.rate; }, 0) / n : 0;
      var hits = st.samples.filter(function (x) { return x.rate > fleet.median; }).length;
      var shrunk = (n * avg + SHRINK_K * fleet.mean) / (n + SHRINK_K);
      var score = n ? shrunk * (0.7 + 0.3 * (hits / n)) : -1;
      var seats = seatsOf(t);
      if (n && t.price != null && pMax > pMin) score *= 1 - 0.1 * (t.price - pMin) / (pMax - pMin);
      if (n && seats != null && seats <= 2) score *= 0.97;
      return {
        trip: t, boat: t.boat, landing: t.landing, tripLength: t.tripLength,
        departureAt: t.departureAt, returnAt: t.returnAt || null,
        price: t.price != null ? t.price : null, openSpots: seats,
        rate: round(avg, 3), samples: n, windowDays: st.windowDays,
        fleetRate: round(fleet.mean, 3), beatFleet: hits, score: score, hasData: n > 0,
      };
    });
    result.noData = scored.filter(function (s) { return !s.hasData; }).length;

    // 4) Best departure per boat, then rank. Boats with a full sample beat
    //    boats with only 1-2 recent trips (a lean), which beat boats with none;
    //    within a tier, higher score wins and an earlier date breaks ties.
    var tier = function (s) { return s.samples >= MIN_SAMPLES ? 2 : s.samples > 0 ? 1 : 0; };
    scored.sort(function (a, b) {
      return (tier(b) - tier(a)) || (b.score - a.score) || (Date.parse(a.departureAt) - Date.parse(b.departureAt));
    });
    var seen = {}, ranked = [];
    scored.forEach(function (s) { if (!seen[s.boat]) { seen[s.boat] = true; ranked.push(s); } });
    var withData = ranked.filter(function (s) { return s.hasData; });
    var pool = withData.length ? withData : ranked;
    if (query.species) {
      // A species question only gets boats that have actually been landing it.
      pool = withData.filter(function (s) { return s.rate >= SPECIES_FLOOR; });
      if (!pool.length) result.reason = 'no-species';
    }

    var marine = D.marine || D.marineFor(region);
    var noun = nounFor(query.species, region, metric);
    var top = pool.slice(0, 3).map(function (s, idx) {
      return {
        boat: s.boat, landing: s.landing, tripLength: s.tripLength,
        departureAt: s.departureAt, returnAt: s.returnAt, dateLabel: fmtDate(s.departureAt),
        price: s.price != null ? Math.round(s.price) : null, openSpots: s.openSpots,
        rate: s.rate, fleetRate: s.fleetRate, samples: s.samples, windowDays: s.windowDays, beatFleet: s.beatFleet,
        noun: noun, metric: metric || 'perAnglerDay',
        bookingUrl: D.bookingUrl(s.trip),
        sourceId: s.trip.sourceId || null,
        advisory: advisoryFor(marine, s.trip, now),
        reason: reasonFor(s, noun, metric, idx),
      };
    });
    result.best = top[0] || null;
    result.alternates = top.slice(1);
    return result;
  }

  // What's biting: species ranked by fish per angler over the last N days,
  // with the change vs the N days before. Observed counts only.
  function whatsBiting(query, data) {
    query = query || {};
    var D = defaults(data);
    var now = query.now != null ? query.now : Date.now();
    var days = query.days || 7;
    var region = query.region || 'san_diego';
    var landings = D.landingsFor(region);
    var species = query.species || null;
    if (!species && ALL_SPECIES_REGIONS[region]) {
      // Every landed species in the window (OC/LA headline counts all fish).
      var seenSp = {};
      for (var j = 0; j < D.trips.length; j++) {
        var tj = D.trips[j];
        if (!tj || !tj.date || tj.date < isoDay(now - (2 * days - 1) * DAY) || tj.date > isoDay(now)) continue;
        if (tj.region && tj.region !== region) continue;
        for (var k in (tj.fullCatch || {})) seenSp[k] = 1;
      }
      species = Object.keys(seenSp);
    }
    species = species && species.length ? species : TROPHY;
    var nowDay = isoDay(now);
    var start = isoDay(now - (days - 1) * DAY), prevStart = isoDay(now - (2 * days - 1) * DAY);
    var cur = { anglers: 0, trips: 0 }, prev = { anglers: 0, trips: 0 };
    var curC = {}, prevC = {}, curTrips = {};
    species.forEach(function (sp) { curC[sp] = 0; prevC[sp] = 0; curTrips[sp] = 0; });
    for (var i = 0; i < D.trips.length; i++) {
      var t = D.trips[i];
      if (!t || !t.date || t.date < prevStart || t.date > nowDay) continue;
      if (landings ? landings.indexOf(t.landing) < 0 : !regionMatch(t, region)) continue;
      if (!(t.anglers > 0)) continue;
      var isCur = t.date >= start;
      var bucket = isCur ? cur : prev, counts = isCur ? curC : prevC;
      bucket.anglers += t.anglers; bucket.trips++;
      species.forEach(function (sp) {
        var n = t[sp] != null ? +t[sp] || 0 : ((t.fullCatch && +t.fullCatch[sp]) || 0);
        counts[sp] += n;
        if (isCur && n > 0) curTrips[sp]++;
      });
    }
    var items = species.map(function (sp) {
      var pa = cur.anglers ? curC[sp] / cur.anglers : 0;
      var pp = prev.anglers ? prevC[sp] / prev.anglers : 0;
      return { species: sp, fish: curC[sp], perAngler: round(pa, 2), tripsWithCatch: curTrips[sp],
               change: pp > 0 ? round((pa - pp) / pp, 2) : null };
    }).filter(function (x) { return x.fish > 0; })
      .sort(function (a, b) { return b.perAngler - a.perAngler; });
    return { region: region, days: days, trips: cur.trips, anglers: cur.anglers, items: items };
  }

  // One-tap quick picks, shared by the Pick my trip card and Co-Captain so
  // mobile visitors (no chat on phones) get the same answers chat users do.
  //   range: 'weekend' | 'next7' | 'next14'
  var ALL_TYPES = ['full', 'overnight', '1.5', 'multi', 'long'];
  // These four match Co-Captain's starter buttons exactly. Tuna replaced
  // "Where are the yellowtail?" (2026-11-26): yellowfin out-land yellowtail
  // ~8:1 in San Diego and owners say tuna is what anglers ask about.
  var QUICK_PICKS = [
    { id: 'overnight-week', label: 'Best overnight this week', type: 'overnight', range: 'next7' },
    { id: 'under-300', label: 'Best trip under $300', type: ['full', 'overnight', '1.5'], range: 'next7', maxPrice: 300 },
    { id: 'tuna-week', label: 'Best boat for tuna this week', type: ['full', 'overnight', '1.5', 'multi'], range: 'next7', species: 'Tuna' },
    { id: 'fullday-weekend', label: 'Best full day this weekend', type: 'full', range: 'weekend' },
  ];
  // Query for a quick pick: quickQuery(id, { region, now }) -> pickTrips query.
  function quickQuery(id, opts) {
    opts = opts || {};
    var q = QUICK_PICKS.filter(function (x) { return x.id === id; })[0];
    if (!q) return null;
    var pr = presets(opts.now);
    var r = q.range === 'weekend' ? pr.weekend
      : { from: pr.next7.from, to: addDays(pr.next7.from, q.range === 'next14' ? 13 : 6) };
    return { type: q.type, from: r.from, to: r.to, maxPrice: q.maxPrice, species: q.species,
             region: opts.region, now: opts.now };
  }

  // Date-range presets in Pacific time. "This weekend" is Fri–Sun; on Sat/Sun
  // it's the rest of this weekend.
  function presets(now) {
    now = now != null ? now : Date.now();
    var today = isoDay(now);
    var p = today.split('-').map(Number);
    var dow = new Date(Date.UTC(p[0], p[1] - 1, p[2], 12)).getUTCDay(); // 0 = Sun
    var fri = dow === 0 ? addDays(today, -2) : dow === 6 ? addDays(today, -1) : addDays(today, 5 - dow);
    return {
      weekend: { from: fri < today ? today : fri, to: addDays(fri, 2), label: 'This weekend' },
      next7: { from: today, to: addDays(today, 6), label: 'Next 7 days' },
    };
  }

  var api = { pickTrips: pickTrips, whatsBiting: whatsBiting, presets: presets,
              QUICK_PICKS: QUICK_PICKS, quickQuery: quickQuery, ALL_TYPES: ALL_TYPES,
              TRIP_TYPES: TRIP_TYPES, typeOf: typeOf, pacificDate: pacificDate, addDays: addDays };
  if (root) root.TTPicker = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : null);
