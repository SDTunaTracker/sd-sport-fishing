// Unit tests for web/trip-picker.js. Run: node --test tests/trip-picker.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../web/trip-picker.js');

// Wed Nov 25 2026, 10:00 Pacific
const NOW = Date.parse('2026-11-25T18:00:00Z');
const day = (n) => P.addDays('2026-11-25', n);
const dep = (n, hh = '20:00') => `${day(n)}T${hh}:00-08:00`;

let id = 0;
function trip(boat, daysAgo, fish, anglers = 20, extra = {}) {
  return { id: ++id, date: day(-daysAgo), boat, landing: extra.landing || 'H&M Landing', tripLength: extra.tripLength || 'Overnight',
           tripLengthDays: extra.tripLengthDays || 1, anglers, trophyCount: fish, Yellowfin: extra.Yellowfin ?? fish,
           Bluefin: extra.Bluefin ?? 0, Yellowtail: 0, Dorado: 0, region: extra.region || 'san_diego', fullCatch: extra.fullCatch, rate: extra.rate };
}
function sched(boat, inDays, extra = {}) {
  return { boat, landing: extra.landing || 'H&M Landing', tripLength: extra.tripLength || 'Overnight', tripLengthDays: extra.tripLengthDays || 1,
           departureAt: dep(inDays), returnAt: dep(inDays + 1, '18:00'), price: extra.price ?? 360, capacity: 30,
           openSpots: extra.openSpots ?? 10, tripStatus: extra.tripStatus ?? null, sourceId: `${boat}-${inDays}`,
           ...(extra.region ? { region: extra.region } : {}) };
}
const data = (schedule, trips, more = {}) => ({ schedule, trips, landingsFor: () => null, bookingUrl: (t) => `https://book/${t.sourceId}`, ...more });

test('consistent boat beats a one-trip wonder', () => {
  const trips = [
    trip('Steady', 2, 60), trip('Steady', 5, 56), trip('Steady', 8, 64), trip('Steady', 11, 58),
    trip('Lucky', 3, 140),
    trip('Meh', 2, 20), trip('Meh', 6, 24), trip('Meh', 9, 22),
  ];
  const r = P.pickTrips({ type: 'overnight', now: NOW }, data([sched('Steady', 3), sched('Lucky', 3), sched('Meh', 2)], trips));
  assert.equal(r.best.boat, 'Steady');
  assert.equal(r.alternates.length, 2);
  assert.ok(r.alternates.some((a) => a.boat === 'Lucky'));
  assert.equal(r.best.bookingUrl, 'https://book/Steady-3');
  assert.match(r.best.reason, /Steady averaged 3\.0 tuna per angler on 4 overnights in the last 14 days \(fleet: 2\.8\)/);
  assert.match(r.alternates.find((a) => a.boat === 'Lucky').reason, /treat it as a lean/);
});

test('filters: sold out, full status, out of range, over budget, wrong type', () => {
  const trips = ['A', 'B', 'C', 'D', 'E', 'F'].flatMap((b) => [trip(b, 2, 40), trip(b, 4, 40), trip(b, 6, 40)]);
  const s = [
    sched('A', 2, { openSpots: 0 }),
    sched('B', 2, { tripStatus: 'Full' }),
    sched('C', 20),
    sched('D', 2, { price: 900 }),
    sched('E', 2, { tripLength: 'Full Day', tripLengthDays: 0.75 }),
    sched('F', 2),
  ];
  const r = P.pickTrips({ type: 'overnight', maxPrice: 500, now: NOW }, data(s, trips));
  assert.equal(r.considered, 1);
  assert.equal(r.best.boat, 'F');
  assert.equal(r.alternates.length, 0);
});

test('no candidates returns best null', () => {
  const r = P.pickTrips({ type: 'long', now: NOW }, data([sched('A', 2)], []));
  assert.equal(r.best, null);
  assert.equal(r.considered, 0);
});

test('widens the window when recent samples are thin', () => {
  const trips = [trip('Old', 20, 40), trip('Old', 25, 44), trip('Old', 28, 42), trip('Other', 3, 30)];
  const r = P.pickTrips({ type: 'overnight', now: NOW }, data([sched('Old', 2)], trips));
  assert.equal(r.best.boat, 'Old');
  assert.equal(r.best.samples, 3);
  assert.equal(r.best.windowDays, 30);
});

test('species query ranks by that species', () => {
  const trips = [
    trip('Tuna', 2, 40, 20, { Bluefin: 30, Yellowfin: 10 }), trip('Tuna', 4, 40, 20, { Bluefin: 30, Yellowfin: 10 }), trip('Tuna', 6, 40, 20, { Bluefin: 30, Yellowfin: 10 }),
    trip('Yft', 2, 50, 20, { Bluefin: 0, Yellowfin: 50 }), trip('Yft', 4, 50, 20, { Bluefin: 0, Yellowfin: 50 }), trip('Yft', 6, 50, 20, { Bluefin: 0, Yellowfin: 50 }),
  ];
  const s = [sched('Tuna', 2), sched('Yft', 2)];
  assert.equal(P.pickTrips({ type: 'overnight', now: NOW }, data(s, trips)).best.boat, 'Yft');
  const blue = P.pickTrips({ type: 'overnight', species: 'Bluefin', now: NOW }, data(s, trips));
  assert.equal(blue.best.boat, 'Tuna');
  assert.equal(blue.best.noun, 'bluefin');
});

test('one row per boat: its best departure, earliest on a tie', () => {
  const trips = [trip('A', 2, 40), trip('A', 4, 40), trip('A', 6, 40)];
  const r = P.pickTrips({ type: 'overnight', now: NOW }, data([sched('A', 5), sched('A', 2)], trips));
  assert.equal(r.alternates.length, 0);
  assert.equal(r.best.departureAt, dep(2));
});

test('advisory is a warning only, never a score change', () => {
  const trips = [trip('A', 2, 60), trip('A', 4, 60), trip('A', 6, 60), trip('B', 2, 30), trip('B', 4, 30), trip('B', 6, 30)];
  const marine = { alerts: [{ event: 'Small Craft Advisory', smallCraftAdvisory: true, onset: `${day(1)}T00:00:00-08:00`, ends: `${day(4)}T00:00:00-08:00` }] };
  const r = P.pickTrips({ type: 'overnight', now: NOW }, data([sched('A', 2), sched('B', 2)], trips, { marine }));
  assert.equal(r.best.boat, 'A');
  assert.equal(r.best.advisory.event, 'Small Craft Advisory');
  const later = P.pickTrips({ type: 'overnight', now: NOW }, data([sched('A', 6)], trips, { marine }));
  assert.equal(later.best.advisory, null);
});

test('boats with no recent trips rank below boats with data', () => {
  const trips = [trip('Known', 2, 10), trip('Known', 4, 10), trip('Known', 6, 10)];
  const r = P.pickTrips({ type: 'overnight', now: NOW }, data([sched('Unknown', 1), sched('Known', 3)], trips));
  assert.equal(r.best.boat, 'Known');
  assert.equal(r.noData, 1);
  assert.equal(r.alternates.length, 0);
});

test('OC/LA ranks on tuna too, not every landed species', () => {
  const fc = (n) => ({ Yellowtail: 0, Rockfish: n, Whitefish: n });
  const trips = [
    trip('Rock', 2, 0, 20, { region: 'oc_la', tripLength: 'Full Day', tripLengthDays: 0.75, fullCatch: fc(100) }),
    trip('Rock', 4, 0, 20, { region: 'oc_la', tripLength: 'Full Day', tripLengthDays: 0.75, fullCatch: fc(100) }),
    trip('Rock', 6, 0, 20, { region: 'oc_la', tripLength: 'Full Day', tripLengthDays: 0.75, fullCatch: fc(100) }),
    trip('Few', 2, 5, 20, { region: 'oc_la', tripLength: 'Full Day', tripLengthDays: 0.75, fullCatch: fc(2) }),
    trip('Few', 4, 5, 20, { region: 'oc_la', tripLength: 'Full Day', tripLengthDays: 0.75, fullCatch: fc(2) }),
    trip('Few', 6, 5, 20, { region: 'oc_la', tripLength: 'Full Day', tripLengthDays: 0.75, fullCatch: fc(2) }),
  ];
  const oc = { tripLength: 'Full Day', tripLengthDays: 0.75, region: 'oc_la' };
  const s = [sched('Rock', 2, oc), sched('Few', 2, oc)];
  const r = P.pickTrips({ type: 'full', region: 'oc_la', now: NOW }, data(s, trips));
  assert.equal(r.best.boat, 'Few');
  assert.equal(r.best.noun, 'tuna');
});

test('region filter uses landingsFor when available', () => {
  const trips = [trip('SD', 2, 40), trip('SD', 4, 40), trip('SD', 6, 40), trip('LB', 2, 90, 20, { landing: 'Long Beach' }), trip('LB', 4, 90, 20, { landing: 'Long Beach' }), trip('LB', 6, 90, 20, { landing: 'Long Beach' })];
  const s = [sched('SD', 2), sched('LB', 2, { landing: 'Long Beach' })];
  const r = P.pickTrips({ type: 'overnight', region: 'san_diego', now: NOW }, data(s, trips, { landingsFor: () => ['H&M Landing'] }));
  assert.equal(r.best.boat, 'SD');
  assert.equal(r.considered, 1);
});

test('limit-rate metric (SF Bay rows carry .rate)', () => {
  const sf = (rate) => ({ rate, region: 'sf_bay' });
  const trips = [trip('Hi', 2, 0, 20, sf(0.9)), trip('Hi', 4, 0, 20, sf(0.95)), trip('Hi', 6, 0, 20, sf(0.85)),
                 trip('Lo', 2, 0, 20, sf(0.3)), trip('Lo', 4, 0, 20, sf(0.4)), trip('Lo', 6, 0, 20, sf(0.35))];
  const r = P.pickTrips({ type: 'overnight', region: 'sf_bay', now: NOW }, data([sched('Lo', 2, { region: 'sf_bay' }), sched('Hi', 2, { region: 'sf_bay' })], trips, { metric: 'limitRate' }));
  assert.equal(r.best.boat, 'Hi');
  assert.match(r.best.reason, /90% of limits/);
});

test('whatsBiting ranks species and reports change', () => {
  const trips = [
    trip('A', 1, 0, 10, { Yellowfin: 50, Bluefin: 5 }), trip('B', 3, 0, 10, { Yellowfin: 30, Bluefin: 0 }),
    trip('A', 9, 0, 20, { Yellowfin: 20, Bluefin: 10 }),
  ];
  const w = P.whatsBiting({ now: NOW, days: 7 }, data([], trips));
  assert.deepEqual(w.items.map((i) => i.species), ['Yellowfin', 'Bluefin']);
  assert.equal(w.items[0].perAngler, 4);
  assert.equal(w.items[0].change, 3);   // 4.0 vs 1.0 per angler
  assert.equal(w.trips, 2);
});

test('presets: weekend from a Wednesday, and from a Saturday', () => {
  assert.deepEqual(P.presets(NOW).weekend, { from: '2026-11-27', to: '2026-11-29', label: 'This weekend' });
  assert.deepEqual(P.presets(NOW).next7, { from: '2026-11-25', to: '2026-12-01', label: 'Next 7 days' });
  const sat = Date.parse('2026-11-28T18:00:00Z');
  assert.deepEqual(P.presets(sat).weekend, { from: '2026-11-28', to: '2026-11-29', label: 'This weekend' });
});

test('typeOf groups trip lengths', () => {
  assert.equal(P.typeOf('Full Day'), 'full');
  assert.equal(P.typeOf('Overnight'), 'overnight');
  assert.equal(P.typeOf('1.5 Day'), '1.5');
  assert.equal(P.typeOf('2.5 Day'), 'multi');
  assert.equal(P.typeOf('3.5 Day'), 'multi');
  assert.equal(P.typeOf('5 Day'), 'long');
  assert.equal(P.typeOf('Long Range'), 'long');
});

test('scheduled counts future departures so "no schedule" differs from "none match"', () => {
  const r1 = P.pickTrips({ type: 'long', now: NOW }, data([sched('A', 2)], []));
  assert.equal(r1.considered, 0);
  assert.equal(r1.scheduled, 1);
  const r2 = P.pickTrips({ type: 'full', region: 'oc_la', now: NOW }, data([], []));
  assert.equal(r2.scheduled, 0);
});

test('whatsBiting in OC/LA ranks every landed species', () => {
  const trips = [trip('A', 1, 0, 10, { region: 'oc_la', fullCatch: { Rockfish: 40, Yellowtail: 5 }, Yellowfin: 0 })];
  const w = P.whatsBiting({ now: NOW, region: 'oc_la' }, data([], trips));
  assert.equal(w.items[0].species, 'Rockfish');
});

test('quick picks build queries and run', () => {
  assert.deepEqual(P.QUICK_PICKS.map((q) => q.id), ['overnight-week', 'under-300', 'yellowtail', 'fullday-weekend']);
  const q = P.quickQuery('under-300', { now: NOW, region: 'san_diego' });
  assert.deepEqual([q.from, q.to, q.maxPrice], ['2026-11-25', '2026-12-01', 300]);
  assert.equal(P.quickQuery('fullday-weekend', { now: NOW }).from, '2026-11-27');
  assert.equal(P.quickQuery('yellowtail', { now: NOW }).species, 'Yellowtail');
  const trips = [trip('A', 2, 40), trip('A', 4, 40), trip('A', 6, 40)];
  const r = P.pickTrips(P.quickQuery('under-300', { now: NOW }), data([sched('A', 2, { price: 280 }), sched('B', 2, { price: 400 })], trips));
  assert.equal(r.best.boat, 'A');
  assert.equal(r.considered, 1);
  assert.equal(P.quickQuery('nope'), null);
});

test('species query never offers a boat that is not landing that species', () => {
  const yt = (b, d, n) => ({ ...trip(b, d, 10), Yellowtail: n });
  const trips = [yt('YT', 2, 8), yt('YT', 4, 6), yt('YT', 6, 7), yt('None', 2, 0), yt('None', 4, 0), yt('None', 6, 0)];
  const r = P.pickTrips({ type: 'overnight', species: 'Yellowtail', now: NOW }, data([sched('YT', 2), sched('None', 2)], trips));
  assert.equal(r.best.boat, 'YT');
  assert.equal(r.alternates.length, 0);
  const r2 = P.pickTrips({ type: 'overnight', species: 'Yellowtail', now: NOW }, data([sched('None', 2)], trips));
  assert.equal(r2.best, null);
  assert.equal(r2.reason, 'no-species');
});

test('reason uses the trip label for non-standard lengths', () => {
  const tl = { tripLength: '3/4 Day', tripLengthDays: 0.75 };
  const trips = [trip('Q', 2, 20, 20, tl), trip('Q', 4, 20, 20, tl), trip('Q', 6, 20, 20, tl)];
  const r = P.pickTrips({ type: 'full', now: NOW }, data([sched('Q', 2, tl)], trips));
  assert.match(r.best.reason, /on 3 3\/4 day trips/);
});

test('a region with no landing list never borrows San Diego rows', () => {
  const trips = [trip('SD', 2, 40), trip('SD', 4, 40), trip('SD', 6, 40)];
  const sdRow = { ...sched('SD', 2) };
  const r = P.pickTrips({ type: 'overnight', region: 'sf_bay', now: NOW }, data([sdRow], trips));
  assert.equal(r.best, null);
  assert.equal(r.scheduled, 0);
  assert.equal(r.reason, 'no-schedule');
  assert.equal(P.whatsBiting({ region: 'sf_bay', now: NOW }, data([], trips)).trips, 0);
  assert.equal(P.pickTrips({ type: 'overnight', region: 'san_diego', now: NOW }, data([sdRow], trips)).best.boat, 'SD');
});

test('days: only departures on the chosen days count', () => {
  const trips = ['A', 'B', 'C'].flatMap((b, i) => [trip(b, 2, 40 + i * 10), trip(b, 4, 40 + i * 10), trip(b, 6, 40 + i * 10)]);
  const s = [sched('A', 1), sched('B', 3), sched('C', 5)];
  const r = P.pickTrips({ type: 'overnight', days: [day(5), day(1)], now: NOW }, data(s, trips));
  assert.equal(r.considered, 2);
  assert.equal(r.best.boat, 'C');
  assert.deepEqual(r.query.days, [day(1), day(5)]);
  assert.equal(r.query.from, day(1));
  assert.equal(r.query.to, day(5));
  const none = P.pickTrips({ type: 'overnight', days: [day(2)], now: NOW }, data(s, trips));
  assert.equal(none.best, null);
  assert.equal(none.reason, 'no-match');
  const empty = P.pickTrips({ type: 'overnight', days: [], now: NOW }, data(s, trips));
  assert.equal(empty.considered, 3);
});
