// TT_REGS — hand-curated fishing regulations for the regs card and Co-Captain.
//
// HOW TO UPDATE
//   1. Re-read each `sources` page below. Rules change a few times a year
//      (groundfish seasons, CDFW summaries, federal bluefin rules).
//   2. Edit the numbers or text here only. The card and Co-Captain read
//      this file, and nothing else hardcodes a limit.
//   3. Set `lastChecked` to the date you re-read the pages, then bump the
//      ?v= of regulations.js in index.html.
// Never add a limit you have not seen on an official page. If something is
// unclear, leave it out and point to the source instead.
window.TT_REGS = {
  lastChecked: '2026-11-25',
  disclaimer: 'Summary only. Rules change, so check the official page before you go.',

  sources: {
    cdfw_fish_table: { short: 'CDFW limits', name: 'CDFW: bag & size limits by species', url: 'https://wildlife.ca.gov/Regions/Marine/FAQ/general-commercial-and-recreational-recreational-what-are-the-sport-regulations-for-the-fish-species-i-am-taking' },
    cdfw_southern:   { name: 'CDFW: Southern Region regulations', url: 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Southern' },
    cdfw_sf:         { name: 'CDFW: San Francisco Region regulations', url: 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/San-Francisco' },
    cdfw_groundfish: { name: 'CDFW: groundfish (rockfish, lingcod) summary', url: 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary' },
    cdfw_license:    { name: 'CDFW: sport fishing licenses', url: 'https://wildlife.ca.gov/Licensing/Fishing' },
    ccr_27_15:      { name: '14 CCR §27.15: multi-day fishing trips', url: 'https://www.law.cornell.edu/regulations/california/14-CCR-27.15' },
    noaa_660_721:    { short: 'NOAA bluefin', name: 'NOAA / 50 CFR §660.721: federal tuna bag limits', url: 'https://www.ecfr.gov/current/title-50/chapter-VI/part-660/subpart-K/section-660.721' },
    conapesca:       { short: 'CONAPESCA permit', name: 'CONAPESCA: Mexican sport-fishing permit', url: 'https://www.gob.mx/conapesca/documentos/conapesca-01-016-pesca-deportivo-recreativa' },
    inm:             { short: 'FMM (INM)', name: 'INM: entering Mexican waters by boat (FMM)', url: 'https://www.gob.mx/inm/acciones-y-programas/sport-fishing-and-nautical-tourism' },
  },

  // California (state waters + federal EEZ off CA). Per angler, per day.
  // `inGeneral20`: counts toward the 20-finfish general daily bag (§27.60(a)).
  california: {
    generalBag: 'General limit: 20 finfish per angler per day in combination. The bluefin and albacore limits below are in addition to it.',
    species: [
      { key: 'Bluefin',   name: 'Bluefin tuna',   limit: '2 per day', card: 'On top of the 20-fish total.', note: 'In addition to the 20-fish general limit. Federal rule (50 CFR §660.721) is also 2.', sources: ['cdfw_fish_table', 'noaa_660_721'] },
      { key: 'Yellowfin', name: 'Yellowfin tuna', limit: '10 per day', card: '', note: 'CDFW lists it as "Tuna, Other (including Bigeye and Yellowfin): 10 fish" (§28.38(d)).', sources: ['cdfw_fish_table'] },
      { key: 'Bigeye',    name: 'Bigeye tuna',    limit: '10 per day', card: '', note: 'CDFW lists it as "Tuna, Other (including Bigeye and Yellowfin): 10 fish" (§28.38(d)).', sources: ['cdfw_fish_table'] },
      { key: 'Yellowtail',name: 'Yellowtail',     limit: '10 per day', card: '24 in. minimum, but up to 5 may be smaller.', note: '24" fork length minimum, except up to 5 may be under 24" (§28.37).', sources: ['cdfw_fish_table', 'cdfw_southern'] },
      { key: 'Dorado',    name: 'Dorado (dolphinfish)', limit: '10 per day', card: 'Counts toward the 20-fish total.', note: 'Within the 20-fish general limit (§27.60(a)).', inGeneral20: true, sources: ['cdfw_fish_table'] },
      { key: 'Albacore',  name: 'Albacore',       limit: '10 per day south of Pt. Conception', card: '25 north of Pt. Conception. On top of the 20-fish total.', note: '25 north of Pt. Conception. In addition to the 20-fish general limit (§28.38(a)).', sources: ['cdfw_fish_table', 'noaa_660_721'] },
      { key: 'Skipjack',  name: 'Skipjack tuna',  limit: 'No limit', card: '', note: '§28.38(c).', sources: ['cdfw_fish_table'] },
    ],
    multiDay: 'Multi-day trips: up to 3 daily limits per angler, but only if the boat filed a CDFW Multi-Day Fishing Trip declaration. Still only one daily limit may be taken per calendar day (§27.15).',
    multiDaySources: ['ccr_27_15'],
    license: 'California sport fishing license: anglers 16 and older. South of Pt. Arguello you also need an Ocean Enhancement Validation, except on a one- or two-day license.',
    licenseSources: ['cdfw_license'],
  },

  // Seasons / closures by CDFW region. Southern = Pt. Conception to Mexico
  // (covers San Diego and OC/LA). Keep to what the region page says.
  regions: {
    southern: {
      name: 'Southern California (Pt. Conception to the Mexico border)',
      appliesTo: ['san_diego', 'oc_la'],
      sources: ['cdfw_southern', 'cdfw_groundfish'],
      closures: [
        'Rockfish, cabezon, greenlings & lingcod: closed Jan 1 – Mar 31. Open all depths Apr 1 – Jun 30. Inside 50 fathoms only Jul 1 – Sep 30. From Oct 1 – Dec 31, nearshore rockfish closed and shelf/slope rockfish & lingcod open outside 50 fathoms only.',
        'White seabass: 3 per day, but only 1 south of Pt. Conception from Mar 15 – Jun 15. Minimum 28".',
        'California sheephead: open to boat anglers Mar 1 – Dec 31, 2026 (2 per day).',
        'Giant (black) sea bass: closed year-round, no take.',
        'Ocean salmon: closed for the rest of 2026.',
        'Spiny lobster: open 6 pm Oct 2, 2026 – Mar 17, 2027 (7 per day, report card required).',
      ],
      otherLimits: [
        'Calico/sand bass: 5 per day combined (max 4 barred sand bass), 14" minimum.',
        'California halibut: 5 per day south of Pt. Sur, 22" minimum.',
        'Lingcod: 2 per day, 22" minimum. Rockfish/cabezon/greenlings: 10 combined.',
      ],
    },
    san_francisco: {
      name: 'San Francisco region (Pt. Arena to Pigeon Point)',
      appliesTo: ['sf_bay'],
      sources: ['cdfw_sf', 'cdfw_groundfish'],
      closures: [
        'Rockfish, cabezon, greenlings & lingcod: closed Jan 1 – Mar 31, open all depths Apr 1 – Dec 31.',
        'Ocean salmon: closed for the rest of 2026.',
        'White sturgeon: catch-and-release only (0 per day), open in ocean waters Oct 1, 2026 – Jun 30, 2027, with the Jan 1 – Mar 15 area closure. Green sturgeon may never be taken.',
        'Pacific halibut: open Apr 1 – Dec 31, 2026 or until the quota is met (1 per day).',
      ],
      otherLimits: [
        'California halibut: 2 per day north of Pt. Sur, 22" minimum.',
        'Albacore: 25 per day north of Pt. Conception.',
      ],
    },
  },

  // Mexican waters (many San Diego overnight and multi-day trips fish there).
  mexico: {
    permit: 'Fishing from a boat in Mexican waters requires an individual Mexican sport-fishing permit (CONAPESCA), bought online by the day, week, month, year or "excursion".',
    permitSources: ['conapesca'],
    fmm: 'Foreigners entering Mexican waters by boat must be on the boat\'s INM passenger list with the immigration fee paid. This visitor permit is the FMM. Carry your passport.',
    fmmSources: ['inm'],
    limits: 'Mexico daily limit: 10 fish per angler, no more than 5 of one species. Dorado (and roosterfish and some others): 2 per day, each counting as 5 fish. Billfish and sharks: 1 per day. On trips longer than 3 days, the most you can keep is 3 days\' worth.',
    limitsSources: ['conapesca'],
    askLanding: 'Ask your landing which permits the trip needs. Many trip listings say "Mexican permit additional" or "Passport required."',
    // Short version for the trip card (the full lines above go to Co-Captain).
    card: [
      'You need a Mexican sport-fishing permit (CONAPESCA) to fish from a boat in Mexican waters. It can be bought online.',
      'Bring your passport. The boat sends its passenger list to INM for the FMM entry permit, and there is a fee per foreign passenger.',
      'Mexican limits: 10 fish per angler, max 5 of one species; dorado 2.',
    ],
  },
};

// Pick what to show for one scheduled trip. Shared by the trip card and
// Co-Captain so both say the same thing.
//   species: CA limits for the trip's target species (trophy four if none named)
//   region:  the CDFW region entry for the trip
//   listing: the trip's own words about passports / permits, quoted verbatim
window.ttRegsForTrip = function (trip) {
  var R = window.TT_REGS;
  if (!R || !trip) return null;
  var targets = String(trip.targetSpecies || '') + ' ' + String(trip.note || '');
  // A bare "tuna" (e.g. "Targeting Tuna, Yellowtail") means the common tunas.
  var genericTuna = /\btunas?\b/i.test(targets.replace(/(bluefin|yellowfin|bigeye|skipjack|albacore)\s+tunas?/ig, ''));
  var species = R.california.species.filter(function (s) {
    return new RegExp('\\b' + s.key, 'i').test(targets) ||
      (s.key === 'Dorado' && /dolphin|mahi/i.test(targets)) ||
      (genericTuna && (s.key === 'Bluefin' || s.key === 'Yellowfin'));
  });
  if (!species.length) {
    species = R.california.species.filter(function (s) {
      return ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'].indexOf(s.key) >= 0;
    });
  }
  var regionId = trip.region === 'sf_bay' ? 'san_francisco' : 'southern';
  var text = [trip.note, trip.whatsIncluded].filter(Boolean).join(' ');
  // Split into sentences without lookbehind (older iOS Safari can't parse it).
  var bits = (text.match(/[^.!]+[.!]*/g) || []).map(function (x) { return x.trim(); }).filter(function (x) {
    return /passport|mexic|fmm|permit|licen[cs]e/i.test(x);
  });
  var days = Number(trip.tripLengthDays) || 0;
  return {
    species: species,
    regionId: regionId,
    region: R.regions[regionId],
    listing: bits.length ? bits.join(' ').trim() : null,
    multiDay: days > 1,
  };
};

// What a trip's own listing says about paperwork. Only reads the listing text;
// it never assumes a trip enters Mexican waters.
//   passport: 'req' | 'not' | null
//   mxPermit: 'incl' | 'extra' | null   (only when the listing says "Mexican")
//   permitsExtra: true when it just says "Permits additional" (no country named)
window.ttTripDocs = function (trip) {
  var txt = [trip && trip.note, trip && trip.whatsIncluded].filter(Boolean).join(' ');
  var out = { passport: null, mxPermit: null, permitsExtra: false, fmm: false };
  if (!txt) return out;
  if (/passport\s+(is\s+)?not\s+req/i.test(txt)) out.passport = 'not';
  else if (/passports?\s+(are\s+|is\s+)?req|valid passport/i.test(txt)) out.passport = 'req';
  if (/includes?[^.]*mexican (fishing )?(permit|licen[cs]e)|mexican (fishing )?(permit|licen[cs]e)s?[^.]*includ/i.test(txt)) out.mxPermit = 'incl';
  else if (/mexican[^.]*(permit|licen[cs]e)s?[^.]*(additional|extra)/i.test(txt)) out.mxPermit = 'extra';
  else if (/permits?\s+(are\s+|will be\s+)?(additional|extra)/i.test(txt)) out.permitsExtra = true;
  out.fmm = /fmm/i.test(txt);
  out.ifNeeded = /if (required|needed)/i.test(txt);
  return out;
};

// Short card-face tag from the listing, or null. Says only what the listing says.
window.ttTripDocsTag = function (trip) {
  var d = window.ttTripDocs(trip);
  var passport = d.passport === 'req';
  if (d.mxPermit && passport) return 'Mexican waters · permit + passport';
  if (d.mxPermit === 'incl') return 'Mexican permit included';
  if (d.mxPermit) return 'Mexican permit extra' + (d.ifNeeded ? ' if needed' : '');
  if (d.permitsExtra && passport) return 'Passport + permits extra';
  if (passport) return 'Passport required';
  if (d.permitsExtra) return 'Permits extra';
  return null;
};
