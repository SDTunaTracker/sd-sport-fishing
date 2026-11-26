// Best-boat rankings use tuna only (owner decision 2026-11-26).
// Run: node --test tests/tuna-ranking.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SRC = readFileSync(new URL('../web/analytics.js', import.meta.url), 'utf8');

function load(trips) {
  const window = { SD: { TRIPS: trips, SIXPACK_BOATS: [] } };
  vm.runInNewContext(SRC, { window, Set, Math, Object, Date, console });
  return window;
}

let id = 0;
function trip(boat, date, catchBy, extra = {}) {
  return {
    id: ++id, boat, date, landing: extra.landing || 'H&M Landing', year: 2026,
    month: +date.slice(5, 7), day: +date.slice(8, 10),
    tripLength: extra.tripLength || 'Full Day', tripLengthDays: extra.tripLengthDays || 0.75,
    anglers: extra.anglers || 20, Bluefin: 0, Yellowfin: 0, Yellowtail: 0, Dorado: 0,
    ...catchBy,
    region: extra.region || 'san_diego',
  };
}

// "YT King" lands lots of yellowtail (trophy, not tuna); "Tuna Boat" fewer fish but tuna.
function fleet() {
  const out = [];
  for (let d = 1; d <= 12; d++) {
    const date = `2026-08-${String(d).padStart(2, '0')}`;
    out.push(trip('YT King', date, { Yellowtail: 100, Dorado: 20 }));
    out.push(trip('Tuna Boat', date, { Yellowfin: 15, Bigeye: 3, Albacore: 2 }));
    out.push(trip('Skip Boat', date, { Skipjack: 60 }));   // skipjack is not in the tuna set
  }
  return out;
}

test('preprocessTrips adds tuna count and rate; totals keep trophy fish', () => {
  const w = load(fleet());
  w.SDA.preprocessTrips(null, 'san_diego');
  const t = w.SD_PROC_TRIPS.find(x => x.boat === 'Tuna Boat');
  assert.equal(t.tunaCount, 20);
  assert.equal(t.tunaPerAnglerPerDay, 1);            // 20 tuna / 20 anglers / 1 day
  assert.equal(t.rankPerAnglerPerDay, 1);
  assert.equal(t.totalTuna, 15);                     // headline: trophy species
  const yt = w.SD_PROC_TRIPS.find(x => x.boat === 'YT King');
  assert.equal(yt.tunaCount, 0);
  assert.equal(yt.totalTuna, 120);
  assert.deepEqual([...w.SDA.TUNA_SPECIES], ['Bluefin', 'Yellowfin', 'Bigeye', 'Albacore']);
});

test('boat leaderboard ranks on tuna per angler per day', () => {
  const w = load(fleet());
  w.SDA.preprocessTrips(null, 'san_diego');
  const { rows } = w.SDA.boatLeaderboard(w.SD_PROC_TRIPS, 'all', 5);
  assert.equal(rows[0].boat, 'Tuna Boat');           // YT King and Skip Boat: 0 tuna
  assert.equal(rows[0].avgTPAPerDay, 1);
  assert.equal(rows[0].totalTuna, 240);              // ranked count (tuna), consistent with the rate
  assert.equal(rows.find(r => r.boat === 'YT King').totalHeadline, 1440);
  // A species filter still ranks on that species.
  const ytRows = w.SDA.boatLeaderboard(w.SD_PROC_TRIPS, 'Yellowtail', 5).rows;
  assert.equal(ytRows[0].boat, 'YT King');
});

test('win rate and top performer go to the tuna boat; all-zero days have no winner', () => {
  const trips = fleet();
  // Twelve more days where nobody caught tuna.
  for (let d = 13; d <= 24; d++) {
    const date = `2026-08-${String(d).padStart(2, '0')}`;
    trips.push(trip('YT King', date, { Yellowtail: 50 }));
    trips.push(trip('Tuna Boat', date, { Yellowtail: 5 }));
  }
  const w = load(trips);
  w.SDA.preprocessTrips(null, 'san_diego');
  const wr = w.SDA.boatWinRates();
  assert.equal(wr['Tuna Boat|Full Day'].wins, 12);
  assert.equal(wr['YT King|Full Day'].wins, 0);
  assert.equal(wr['YT King|Full Day'].matchupCount, 24);
  const tp = w.SDA.boatTopPerformerRates();
  assert.ok(tp['Tuna Boat'].rate > tp['YT King'].rate);
  assert.equal(tp['YT King'].wins, 0);
});

test('fishing rating and head-to-head order boats by tuna', () => {
  const w = load(fleet());
  w.SDA.preprocessTrips(null, 'san_diego');
  w.getLandingsForRegion = () => null;
  const r = w.SDA.fishingRating('2026-08-12');
  assert.equal(r.boats[0].boat, 'Tuna Boat');
  const peer = w.SDA.peerLeaderboard(w.SD_PROC_TRIPS, 'all');
  assert.equal(peer.find(p => p.boat === 'Tuna Boat').wins, 12);
  assert.equal(peer.find(p => p.boat === 'YT King').wins, 0);
});

test('OC/LA ranks on tuna too; its headline total stays every species', () => {
  const trips = [];
  for (let d = 1; d <= 6; d++) {
    const date = `2026-08-${String(d).padStart(2, '0')}`;
    trips.push(trip('Rock Boat', date, { fullCatch: { Rockfish: 200 } }, { landing: 'Newport Landing', region: 'oc_la' }));
    trips.push(trip('Albie Boat', date, { Albacore: 10, fullCatch: { Albacore: 10 } }, { landing: 'Newport Landing', region: 'oc_la' }));
  }
  const w = load(trips);
  w.SDA.preprocessTrips(null, 'oc_la');
  const rock = w.SD_PROC_TRIPS.find(t => t.boat === 'Rock Boat');
  assert.equal(rock.totalTuna, 200);                 // headline: all landed fish
  assert.equal(rock.rankCount, 0);
  const { rows } = w.SDA.boatLeaderboard(w.SD_PROC_TRIPS, 'all', 3);
  assert.equal(rows[0].boat, 'Albie Boat');
  assert.equal(w.SDA.rankLabel(), 'Tuna');
});

test('custom target species in Settings rank on those species', () => {
  const w = load(fleet());
  w.SDA.preprocessTrips({ trophySpecies: ['Yellowtail'] }, 'san_diego');
  const { rows } = w.SDA.boatLeaderboard(w.SD_PROC_TRIPS, 'all', 5);
  assert.equal(rows[0].boat, 'YT King');
  assert.equal(w.SDA.rankLabel(), 'Target');
});

test('rankRate works on raw SD.TRIPS rows (no preprocessing)', () => {
  const w = load([]);
  const raw = trip('X', '2026-08-01', { Bluefin: 6, Yellowtail: 40 }, { tripLengthDays: 2.5, anglers: 10 });
  assert.equal(w.SDA.rankRate(raw), 0.3);           // 6 tuna / 10 anglers / 2 days
  assert.equal(w.SDA.rankRate({ ...raw, anglers: 0 }), 0);
});
