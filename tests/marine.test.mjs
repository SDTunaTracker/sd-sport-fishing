// Unit tests for web/marine.js (NWS sea-conditions forecast per trip).
// Run: node --test tests/marine.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const M = require('../web/marine.js');
const P = require('../web/trip-picker.js');

const NOW = Date.parse('2026-11-26T22:00:00Z');          // Thu 2 PM Pacific
const UPDATED = '2026-11-26T12:04:00-08:00';

function period(name, start, end, wind, seas) {
  return { name, start, end, windKt: wind, seasFt: seas, text: '' };
}
// Inner zone calm; outer zone rougher Friday night, 8-10 ft Saturday.
const MARINE = {
  zones: {
    PZZ740: { updated: UPDATED, periods: [
      period('Tonight', '2026-11-26T18:00:00-08:00', '2026-11-27T06:00:00-08:00', [0, 10], [3, 5]),
      period('Fri', '2026-11-27T06:00:00-08:00', '2026-11-27T18:00:00-08:00', [0, 10], [3, 4]),
      period('Fri Night', '2026-11-27T18:00:00-08:00', '2026-11-28T06:00:00-08:00', [0, 10], [3, 4]),
      period('Sat', '2026-11-28T06:00:00-08:00', '2026-11-28T18:00:00-08:00', [10, 15], [4, 6]),
    ] },
    PZZ745: { updated: UPDATED, periods: [
      period('Tonight', '2026-11-26T18:00:00-08:00', '2026-11-27T06:00:00-08:00', [0, 10], [5, 7]),
      period('Fri', '2026-11-27T06:00:00-08:00', '2026-11-27T18:00:00-08:00', [0, 10], [3, 5]),
      period('Fri Night', '2026-11-27T18:00:00-08:00', '2026-11-28T06:00:00-08:00', [10, 20], [5, 7]),
      period('Sat', '2026-11-28T06:00:00-08:00', '2026-11-28T18:00:00-08:00', [20, 25], [8, 10]),
    ] },
  },
  alerts: [],
  smallCraftAdvisory: false,
};

test('zone choice by trip length', () => {
  assert.deepEqual(M.zonesFor('1/2 Day AM', 0.5), ['PZZ740']);
  assert.deepEqual(M.zonesFor('3/4 Day', 0.75), ['PZZ740']);
  assert.deepEqual(M.zonesFor('Full Day', 0.75), ['PZZ740', 'PZZ745']);
  assert.deepEqual(M.zonesFor('Overnight', 1), ['PZZ745']);
  assert.deepEqual(M.zonesFor('1.5 Day', 1.5), ['PZZ745']);
});

test('half day uses the inner zone; line reads like the brief', () => {
  const c = M.forTrip(MARINE, { departureAt: '2026-11-27T06:00:00-08:00', tripLength: '1/2 Day AM', tripLengthDays: 0.5 }, NOW);
  assert.deepEqual(c.seasFt, { min: 3, max: 4 });
  assert.equal(M.line(c), 'Seas 3–4 ft · wind <10 kt');
  assert.equal(c.rough, false);
});

test('overnight uses the outer zone across the whole trip; 8 ft+ is rough', () => {
  const c = M.forTrip(MARINE, { departureAt: '2026-11-27T22:00:00-08:00', returnAt: '2026-11-28T17:00:00-08:00',
                               tripLength: 'Overnight', tripLengthDays: 1 }, NOW);
  assert.deepEqual(c.zones, ['PZZ745']);
  assert.deepEqual(c.seasFt, { min: 5, max: 10 });
  assert.equal(M.line(c), 'Seas 5–10 ft · wind 10–25 kt');
  assert.equal(c.rough, true);
});

test('advisory in the trip zone flags the trip; one in another zone does not', () => {
  const adv = { ...MARINE, alerts: [{ event: 'Small Craft Advisory', headline: 'SCA until Sat 3 PM',
    zones: ['PZZ745'], onset: '2026-11-27T03:00:00-08:00', ends: '2026-11-28T15:00:00-08:00' }] };
  const off = M.forTrip(adv, { departureAt: '2026-11-27T05:00:00-08:00', tripLength: 'Full Day', tripLengthDays: 0.75 }, NOW);
  assert.equal(off.advisory.event, 'Small Craft Advisory');
  assert.equal(off.rough, true);
  const half = M.forTrip(adv, { departureAt: '2026-11-27T06:00:00-08:00', tripLength: '1/2 Day AM', tripLengthDays: 0.5 }, NOW);
  assert.equal(half.advisory, null);
});

test('stale forecast, past trip, beyond the forecast: null', () => {
  const trip = { departureAt: '2026-11-27T06:00:00-08:00', tripLength: '1/2 Day AM', tripLengthDays: 0.5 };
  assert.equal(M.forTrip(MARINE, trip, Date.parse('2026-11-28T08:00:00-08:00')), null);   // updated > 24 h ago
  assert.equal(M.forTrip(MARINE, { ...trip, departureAt: '2026-11-25T06:00:00-08:00' }, NOW), null);
  assert.equal(M.forTrip(MARINE, { ...trip, departureAt: '2026-12-04T06:00:00-08:00' }, NOW), null);
  assert.equal(M.forTrip(null, trip, NOW), null);
});

test('3+ day trips show the departure-day forecast', () => {
  const c = M.forTrip(MARINE, { departureAt: '2026-11-27T10:00:00-08:00', tripLength: '3 Day', tripLengthDays: 3 }, NOW);
  assert.equal(c.atDeparture, true);
  assert.deepEqual(c.seasFt, { min: 3, max: 7 });          // Fri + Fri Night only, not Sat
});

test('zone outlook for the boat page skips past periods', () => {
  const o = M.zoneOutlook(MARINE, 'PZZ745', Date.parse('2026-11-27T08:00:00-08:00'), 2);
  assert.deepEqual(o.map(x => x.name), ['Fri', 'Fri Night']);
  assert.equal(o[0].line, 'Seas 3–5 ft · wind <10 kt');
});

test('Pick my trip answers carry the NWS forecast and a rough flag, not a score change', () => {
  const trips = [];
  for (const [b, f] of [['Calm', 30], ['Rough', 40]]) {
    for (const d of [2, 4, 6]) trips.push({ boat: b, landing: 'H&M Landing', date: new Date(NOW - d * 864e5).toISOString().slice(0, 10),
      tripLength: 'Overnight', tripLengthDays: 1, anglers: 20, Yellowfin: f, region: 'san_diego' });
  }
  const sched = (boat, dep) => ({ boat, landing: 'H&M Landing', tripLength: 'Overnight', tripLengthDays: 1,
    departureAt: dep, openSpots: 10, price: 300, sourceId: boat });
  const r = P.pickTrips({ type: 'overnight', now: NOW, from: '2026-11-26', to: '2026-11-30' }, {
    schedule: [sched('Calm', '2026-11-26T22:00:00-08:00'), sched('Rough', '2026-11-27T22:00:00-08:00')],
    trips, marine: MARINE, landingsFor: () => ['H&M Landing'],
  });
  assert.equal(r.best.boat, 'Rough');                         // still ranked on catch
  assert.equal(r.best.sea.rough, true);
  assert.match(r.best.sea.line, /^Seas 5–10 ft/);
  assert.equal(r.alternates[0].sea.rough, false);
});

test('a trip that runs past the last forecast period is labelled at departure', () => {
  const c = M.forTrip(MARINE, { departureAt: '2026-11-28T17:00:00-08:00', returnAt: '2026-11-29T18:00:00-08:00',
                               tripLength: '1.5 Day', tripLengthDays: 1.5 }, NOW);
  assert.equal(c.atDeparture, true);
  assert.deepEqual(c.seasFt, { min: 8, max: 10 });
});
