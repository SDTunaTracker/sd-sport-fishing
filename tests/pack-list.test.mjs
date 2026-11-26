// Unit tests for web/pack-list.js. Run: node --test tests/pack-list.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../web/pack-list.js');

const names = (pl) => pl.rigs.map(r => r.name);

test('full day: flyline + sinker rig + optional iron, no heavy jig', () => {
  const pl = P.buildPackList({ tripLength: 'Full Day', tripLengthDays: 0.75 });
  assert.deepEqual(names(pl), ['Rig 1: flyline', 'Rig 2: sinker rig', 'Optional: iron']);
  assert.equal(pl.bait, null);
});

test('1.5 and 2 day add the heavy jig rig, not the long-range list', () => {
  for (const d of [1.5, 2, 2.5]) {
    const n = names(P.buildPackList({ tripLength: `${d} Day`, tripLengthDays: d }));
    assert.ok(n.includes('Rig 3: heavy jig'));
    assert.ok(!n.includes('Long-range gear list'));
  }
});

test('long range picks the matching Point Loma list', () => {
  const src = (d) => Object.keys(P.buildPackList({ tripLengthDays: d }).rigs.at(-1).src.reduce((o, s) => (o[s] = 1, o), {}))[0];
  assert.equal(src(3), 'T2a');
  assert.equal(src(5), 'T2a');
  assert.equal(src(8), 'T2b');
  assert.equal(src(12), 'T2c');
});

test('trip length parsed from text when days missing; unknown -> null', () => {
  assert.equal(P._days({ tripLength: 'Overnight' }), 1);
  assert.equal(P._days({ tripLength: '1/2 Day AM' }), 0.5);
  assert.equal(P.buildPackList({ tripLength: 'Special' }), null);
});

test('bait at the barge maps to the cited hook rule', () => {
  assert.equal(P.baitRule({ species: 'sardine', minIn: 5, maxIn: 7 }).id, 'sardine_lg');
  assert.equal(P.baitRule({ species: 'sardine', minIn: 4, maxIn: 6 }).id, 'sardine_sm');
  assert.equal(P.baitRule({ species: 'anchovy', minIn: 2, maxIn: 3 }).id, 'pinhead');
  assert.equal(P.baitRule({ species: 'anchovy', minIn: 3, maxIn: 5 }).id, 'anchovy');
  assert.equal(P.baitRule({ species: 'mackerel' }).id, 'mackerel');
  assert.equal(P.baitRule({ species: 'squid' }), null);
  assert.equal(P.baitRule(null), null);
  const pl = P.buildPackList({ tripLengthDays: 1 }, { species: 'sardine', minIn: 5, maxIn: 7, bait: '5-7 inch Sardine' });
  assert.equal(pl.bait.barge, '5-7 inch Sardine');
  assert.equal(pl.bait.hook, '1/0–2/0');
});

test('every line cites a known source, and the list ends with ask the deckhand', () => {
  for (const d of [0.5, 0.75, 1, 1.5, 3, 8, 12]) {
    const pl = P.buildPackList({ tripLengthDays: d }, { species: 'sardine', maxIn: 6 });
    for (const x of [...pl.rigs, pl.bait, ...pl.extras.slice(0, -1)]) {
      assert.ok(x.src.length > 0, `uncited line at ${d} days`);
      for (const s of x.src) assert.ok(P.SOURCES[s]?.url?.startsWith('https://'), s);
    }
    assert.match(pl.extras.at(-1).text, /deckhand/);
    assert.deepEqual(Object.keys(pl.sources).sort(), [...new Set([...pl.rigs, pl.bait, ...pl.extras].flatMap(x => x.src))].sort());
  }
});
