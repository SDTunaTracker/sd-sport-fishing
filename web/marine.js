// NWS sea-conditions forecast for a trip, from window.SD.MARINE
// (src/marine.py region_payload: NWS coastal waters zones PZZ740 / PZZ745,
// alerts, tides, buoys). Pure functions, no DOM.
//
// Zone choice (owner + app-dev plan): half and 3/4 day use the inner zone
// PZZ740 (0–10 nm); full day takes the worse of both; overnight and longer use
// the outer zone PZZ745 (10–60 nm, incl. San Clemente Island). NWS periods
// only reach ~3–5 days out and long range leaves NWS waters, so trips of
// 3+ days show the departure-day forecast, flagged atDeparture.
//
// Staleness: a zone forecast whose `updated` is older than 24 h is ignored,
// so a stale forecast never shows. Always label it "NWS forecast".
//
// API (window.TTMarine; module.exports in Node):
//   forTrip(marine, trip, now?) -> { zones, windKt:{min,max}|null, seasFt:{min,max}|null,
//       advisory:{event,headline,ends}|null, rough, atDeparture, updated } | null
//   line(cond) -> "Seas 3–4 ft · wind <10 kt"
//   zoneOutlook(marine, zone, now?, n?) -> [{ name, line, rough }]
//   zonesFor(tripLength, tripLengthDays), ROUGH_SEAS_FT, ZONES
// Unit tests: node --test tests/marine.test.mjs
(function (root) {
  'use strict';

  var HOUR = 3600000, DAY = 24 * HOUR;
  var INNER = 'PZZ740', OUTER = 'PZZ745';
  var ZONES = {
    PZZ740: { label: 'Inshore', range: '0–10 nm' },
    PZZ745: { label: 'Offshore', range: '10–60 nm' },
  };
  var STALE_H = 24;
  var ROUGH_SEAS_FT = 8;
  var ROUGH_RE = /small craft|gale|storm|hazardous seas/i;

  function tripDays(tripLength, days) {
    var d = Number(days);
    if (isFinite(d) && d > 0) return d;
    var t = String(tripLength || '');
    if (/half|1\/2|twilight/i.test(t)) return 0.5;
    if (/3\/4/.test(t)) return 0.6;
    if (/overnight/i.test(t)) return 1;
    if (/full/i.test(t)) return 0.75;
    var m = /(\d+(?:\.\d+)?)\s*day/i.exec(t);
    return m ? parseFloat(m[1]) : 1;
  }

  function zonesFor(tripLength, days) {
    var t = String(tripLength || '');
    if (/half|1\/2|3\/4|twilight/i.test(t)) return [INNER];
    var d = tripDays(tripLength, days);
    if (/overnight/i.test(t) || d >= 1) return [OUTER];
    if (d >= 0.75) return [INNER, OUTER];
    return [INNER];
  }

  function fresh(zone, now) {
    if (!zone || !zone.updated) return false;
    var u = Date.parse(zone.updated);
    return isFinite(u) && now - u <= STALE_H * HOUR;
  }

  function range(list) {
    var lo = null, hi = null;
    list.forEach(function (r) {
      if (!r || r[1] == null) return;
      var a = r[0] == null ? r[1] : r[0];
      lo = lo == null ? a : Math.min(lo, a);
      hi = hi == null ? r[1] : Math.max(hi, r[1]);
    });
    return hi == null ? null : { min: lo, max: hi };
  }

  function overlaps(s, e, a, b) { return s < b && e > a; }

  function forTrip(marine, trip, now) {
    if (!marine || !marine.zones || !trip) return null;
    now = now != null ? now : Date.now();
    var dep = Date.parse(trip.departureAt);
    if (!isFinite(dep)) return null;
    var d = tripDays(trip.tripLength, trip.tripLengthDays);
    var ret = trip.returnAt ? Date.parse(trip.returnAt) : NaN;
    if (!isFinite(ret) || ret <= dep) ret = dep + Math.max(d * DAY, 5 * HOUR);
    var atDeparture = d >= 3;
    var end = atDeparture ? dep + 18 * HOUR : ret;
    if (end < now) return null;
    var zones = zonesFor(trip.tripLength, trip.tripLengthDays);
    var periods = [], updated = null, lastEnd = -Infinity;
    zones.forEach(function (z) {
      var zone = marine.zones[z];
      if (!fresh(zone, now)) return;
      updated = updated && updated > zone.updated ? updated : zone.updated;
      (zone.periods || []).forEach(function (p) {
        var s = Date.parse(p.start), e = Date.parse(p.end);
        if (isFinite(e)) lastEnd = Math.max(lastEnd, e);
        if (isFinite(s) && isFinite(e) && overlaps(s, e, dep, end)) periods.push(p);
      });
    });
    if (!periods.length) return null;
    // The forecast stops before the trip ends: say it is the departure forecast.
    if (end > lastEnd) atDeparture = true;
    var advisory = null;
    (marine.alerts || []).some(function (a) {
      if (!a || !ROUGH_RE.test(a.event || a.headline || '')) return false;
      if (a.zones && a.zones.length && !a.zones.some(function (z) { return zones.indexOf(z) >= 0; })) return false;
      var s = a.onset ? Date.parse(a.onset) : -Infinity, e = a.ends ? Date.parse(a.ends) : Infinity;
      if (!overlaps(s, e, dep, end) || e < now) return false;
      advisory = { event: a.event || 'Small Craft Advisory', headline: a.headline || null, ends: a.ends || null };
      return true;
    });
    var seas = range(periods.map(function (p) { return p.seasFt; }));
    var wind = range(periods.map(function (p) { return p.windKt; }));
    return {
      zones: zones, windKt: wind, seasFt: seas, advisory: advisory,
      rough: !!advisory || !!(seas && seas.max >= ROUGH_SEAS_FT),
      atDeparture: atDeparture, updated: updated,
    };
  }

  function span(r, unit) {
    if (!r) return null;
    return r.min === r.max ? r.max + ' ' + unit : r.min + '–' + r.max + ' ' + unit;
  }

  function line(c) {
    if (!c) return '';
    var parts = [];
    if (c.seasFt) parts.push('Seas ' + span(c.seasFt, 'ft'));
    if (c.windKt) parts.push(c.windKt.min === 0 ? 'wind <' + c.windKt.max + ' kt' : 'wind ' + span(c.windKt, 'kt'));
    return parts.join(' · ');
  }

  function zoneOutlook(marine, zone, now, n) {
    now = now != null ? now : Date.now();
    var z = marine && marine.zones && marine.zones[zone];
    if (!fresh(z, now)) return [];
    return (z.periods || []).filter(function (p) {
      var e = Date.parse(p.end);
      return !isFinite(e) || e > now;
    }).slice(0, n || 4).map(function (p) {
      var c = { seasFt: range([p.seasFt]), windKt: range([p.windKt]) };
      return { name: p.name, line: line(c), rough: !!(c.seasFt && c.seasFt.max >= ROUGH_SEAS_FT), text: p.text };
    });
  }

  var api = { forTrip: forTrip, line: line, zoneOutlook: zoneOutlook, zonesFor: zonesFor,
              ROUGH_SEAS_FT: ROUGH_SEAS_FT, ZONES: ZONES, INNER: INNER, OUTER: OUTER };
  if (root) root.TTMarine = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : null);
