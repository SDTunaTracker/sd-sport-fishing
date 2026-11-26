// "Pack for this trip": a tackle checklist from published SoCal sportboat
// guidance. Pure rules, no model. Every line cites its source (T-ids below,
// from docs/research/BAIT_SOURCES.md §5), and the list always ends with
// "ask the deckhand".
//
// Inputs: the scheduled trip (tripLength, tripLengthDays) and, optionally,
// the bait the barge is serving now ({ species, minIn, maxIn, bait } from
// api/v1/bait_now.json via web/bait-now.jsx).
//
// Gated in the UI by window.FEATURES.SHOW_PACK_LIST (preview ?preview_pack=true).
// Unit tests: node --test tests/pack-list.test.mjs
(function (root) {
  'use strict';

  var SOURCES = {
    T1: { name: 'H&M Landing: What to Bring & Tackle Suggestions', url: 'https://www.hmlanding.com/tackle-suggestions' },
    T2a: { name: 'Point Loma Sportfishing: 3–6 day gear list', url: 'https://www.pointlomasportfishing.com/gear1.php' },
    T2b: { name: 'Point Loma Sportfishing: 7–10 day gear list', url: 'https://www.pointlomasportfishing.com/gear2.php' },
    T2c: { name: 'Point Loma Sportfishing: 11–23 day gear list', url: 'https://www.pointlomasportfishing.com/gear3.php' },
    T3: { name: "Fisherman's Landing fish count update (Nov 25, 2026)", url: 'https://www.fishermanslanding.com/fishcounts.php' },
    T4: { name: 'The Log: "Medium but Mighty" (Jul 2025)', url: 'https://thelog.com/medium-but-mighty-how-to-hook-socals-favorite-1-to-10-pound-fish/' },
    T5: { name: 'San Diego Reader fish report (Aug 2025)', url: 'https://www.sandiegoreader.com/news/2025/aug/11/fish-report-light-line-fishing-smaller-bluefin/' },
    T6: { name: 'Sport Fishing: "Hook Choice"', url: 'https://www.sportfishingmag.com/?p=45809' },
    T7: { name: 'The Log: "When the Bait Is Too Big" (Jun 2026)', url: 'https://thelog.com/when-the-bait-is-too-big/' },
    T9: { name: 'Sport Fishing: live-bait hook sizing', url: 'https://www.sportfishingmag.com/how-to-catch-more-fish-with-live-bait/' },
  };

  // Bait at the barge -> flyline hook and line (BAIT_SOURCES.md draft rule table).
  var BAIT_RULES = [
    { id: 'pinhead', label: 'Small anchovy (3" or less)', hook: '#4 live-bait hook', line: '15–20 lb', note: 'Light-wire hooks.', src: ['T5'] },
    { id: 'anchovy', label: 'Anchovy', hook: '#4–#2', line: '20–25 lb', note: 'Light wire for yellowfin.', src: ['T4', 'T6'] },
    { id: 'sardine_sm', label: 'Sardine up to 6"', hook: '#2–1/0 (or 1/0–2/0 circle)', line: '20–30 lb', note: null, src: ['T1', 'T3', 'T4'] },
    { id: 'sardine_lg', label: 'Sardine over 6"', hook: '1/0–2/0', line: '25–40 lb', note: '40 lb fluorocarbon leader for yellowtail or bigger tuna.', src: ['T1', 'T3', 'T4', 'T6'] },
    { id: 'mackerel', label: 'Mackerel or very large sardine', hook: '2/0–4/0', line: '40 lb and up', note: 'Or switch to jigs when the bait is too big to cast.', src: ['T4', 'T6', 'T7'] },
  ];

  function baitRule(bait) {
    if (!bait || !bait.species) return null;
    var sp = String(bait.species).toLowerCase();
    var max = typeof bait.maxIn === 'number' ? bait.maxIn : null;
    if (sp === 'anchovy') return BAIT_RULES[max != null && max <= 3 ? 0 : 1];
    if (sp === 'sardine') {
      if (max != null && max > 8) return BAIT_RULES[4];
      return BAIT_RULES[max != null && max <= 6 ? 2 : 3];
    }
    if (sp === 'mackerel') return BAIT_RULES[4];
    return null; // squid etc.: no published rule we can cite
  }

  function days(trip) {
    var d = Number(trip && trip.tripLengthDays);
    if (isFinite(d) && d > 0) return d;
    var t = (trip && trip.tripLength) || '';
    if (/half|1\/2|3\/4|twilight/i.test(t)) return 0.5;
    if (/overnight/i.test(t)) return 1;
    if (/full/i.test(t)) return 0.75;
    var m = /(\d+(?:\.\d+)?)\s*day/i.exec(t);
    if (m) return parseFloat(m[1]);
    return null;
  }

  function longRangeSource(d) {
    if (d >= 11) return 'T2c';
    if (d >= 7) return 'T2b';
    return 'T2a';
  }

  // Returns { rigs, bait, extras, sources } or null when the trip length is unknown.
  function buildPackList(trip, bait) {
    var d = days(trip);
    if (d == null) return null;
    var rigs = [];
    if (d < 0.75) {
      rigs.push({ name: 'Half-day rig', detail: '#2–2/0 J-hooks, 4–6 oz torpedo sinkers, ¼–¾ oz egg sinkers', src: ['T1'] });
    } else {
      rigs.push({ name: 'Rig 1: flyline', detail: '20–40 lb line; #2–2/0 J-hooks and 1/0–2/0 circle hooks; fluorocarbon leader', src: ['T1'] });
      rigs.push({ name: 'Rig 2: sinker rig', detail: '50–80 lb line; 6–12 oz torpedo sinkers; rubber bands', src: ['T1'] });
      if (d < 1.5) {
        rigs.push({ name: 'Optional: iron', detail: '40 lb jig outfit', src: ['T1'] });
      } else {
        rigs.push({ name: 'Rig 3: heavy jig', detail: '80–130 lb line; 300–500 g flat-fall or knife jigs', src: ['T1'] });
      }
    }
    var lr = null;
    if (d >= 3) {
      var id = longRangeSource(d);
      lr = { name: 'Long-range gear list', detail: 'Multi-day trips need more rigs (25 lb up to 100 lb) and spare hooks, leader and wire. Use the landing\'s full list and check it with the boat: these pages are older.', src: [id] };
      rigs.push(lr);
    }
    var rule = baitRule(bait);
    var baitLine = rule ? {
      barge: bait.bait || rule.label, rule: rule.label, hook: rule.hook, line: rule.line, note: rule.note, src: rule.src,
    } : null;
    var extras = [
      { text: 'Rental rods are available at the landing.', src: ['T1'] },
      { text: 'Hook sizes differ between brands: if unsure, go slightly smaller, not larger.', src: ['T9'] },
      { text: "Ask the deckhand: they'll tell you what's working today.", src: [] },
    ];
    var used = {};
    rigs.concat(baitLine ? [baitLine] : [], extras).forEach(function (x) { x.src.forEach(function (s) { used[s] = SOURCES[s]; }); });
    return { days: d, rigs: rigs, bait: baitLine, extras: extras, sources: used };
  }

  var api = { buildPackList: buildPackList, baitRule: baitRule, SOURCES: SOURCES, BAIT_RULES: BAIT_RULES, _days: days };
  if (root) root.TTPack = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : null);
