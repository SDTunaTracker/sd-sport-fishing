// Analytics aggregations over SD.TRIPS
(function () {
  // Called from app.jsx whenever settings change. Adds `totalTuna` (from
  // user-selected trophy species) and `calcDays` (rounded or actual) to every
  // trip so all downstream analytics respect user preferences without any
  // further changes.
  //
  // Also filters six-pack (USCG uninspected passenger vessel) charters out of
  // the Analytics universe when settings.includeSixPackCharters is falsy —
  // this is the SINGLE choke point for six-pack exclusion. Every leaderboard,
  // Win Rate matchup pool, TPA/Day, and head-to-head calc reads from
  // window.SD_PROC_TRIPS, so dropping the trip here removes the boat from
  // every metric at once (no per-metric drift possible). Reports / Today's
  // Report render from window.SD.TODAY and window.SD.TRIPS directly and are
  // deliberately not touched.
  //
  // Match on window.SD.SIXPACK_BOATS (case-insensitive, whitespace-trimmed).
  function _sixpackFilter(settings) {
    if (settings && settings.includeSixPackCharters) return null;  // pass-through
    var list = (window.SD && window.SD.SIXPACK_BOATS) || [];
    if (!list.length) return null;
    var set = new Set();
    for (var i = 0; i < list.length; i++) {
      var n = list[i];
      if (n) set.add(String(n).trim().toLowerCase());
    }
    return set;
  }

  function preprocessTrips(settings) {
    const trophySp = (settings && settings.trophySpecies) || ['Bluefin','Yellowfin','Yellowtail','Dorado'];
    const method   = (settings && settings.tripLengthMethod) || 'rounded';
    const sixpackSet = _sixpackFilter(settings);
    const out = [];
    for (var i = 0; i < window.SD.TRIPS.length; i++) {
      var t = window.SD.TRIPS[i];
      if (sixpackSet) {
        var key = String(t.boat || '').trim().toLowerCase();
        if (sixpackSet.has(key)) continue;
      }
      var totalTuna = trophySp.reduce(function(s, sp) { return s + (t[sp] || 0); }, 0);
      var rawDays   = t.tripLengthDays > 0 ? t.tripLengthDays : 1;
      var calcDays  = method === 'rounded' ? Math.max(1, Math.floor(rawDays)) : rawDays;
      out.push(Object.assign({}, t, { totalTuna: totalTuna, calcDays: calcDays }));
    }
    window.SD_PROC_TRIPS = out;
  }
  // Helper: every filter can be 'all' / null / single value / array. This makes
  // each one behave the same way (multi-select compatible) without changing
  // the call sites.
  function _passes(value, filter, opts) {
    opts = opts || {};
    if (filter == null || filter === 'all' || filter === '') return true;
    const sel = Array.isArray(filter) ? filter : [filter];
    if (sel.length === 0) return true;
    if (opts.toNumber) return sel.map(Number).includes(+value);
    return sel.map(String).includes(String(value));
  }

  function filterTrips(filters, regions) {
    var effectiveRegion = (regions && window.getEffectiveRegion)
      ? window.getEffectiveRegion(regions)
      : window.CURRENT_REGION;
    var regionLandings = (effectiveRegion && window.getLandingsForRegion)
      ? window.getLandingsForRegion(effectiveRegion)
      : null;
    const t = window.SD_PROC_TRIPS || window.SD.TRIPS;
    return t.filter((r) => {
      if (regionLandings && regionLandings.length > 0 && !regionLandings.includes(r.landing)) return false;
      if (!_passes(r.year, filters.year, { toNumber: true })) return false;
      if (!_passes(r.month, filters.month, { toNumber: true })) return false;
      if (!_passes(r.landing, filters.landing)) return false;
      if (!_passes(r.boat, filters.boat)) return false;
      if (!_passes(r.tripLength, filters.tripLength)) return false;
      // Species: keep trip if ANY selected species had a non-zero catch.
      if (filters.species && filters.species !== 'all') {
        const sel = Array.isArray(filters.species) ? filters.species : [filters.species];
        if (sel.length > 0 && !sel.some(sp => (r[sp] || 0) > 0)) return false;
      }
      if (!filters.includeZero && r.totalTuna === 0) return false;
      return true;
    });
  }

  function median(arr) {
    if (!arr.length) return 0;
    const s = [...arr].sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  function mean(arr) {
    if (!arr.length) return 0;
    return arr.reduce((a, b) => a + b, 0) / arr.length;
  }

  function stddev(arr) {
    if (arr.length < 2) return 0;
    const m = mean(arr);
    return Math.sqrt(arr.reduce((s, v) => s + (v - m) ** 2, 0) / (arr.length - 1));
  }

  function speciesField(species) {
    if (!species || species === 'all') return 'totalTuna';
    // Multi-select form: only treat as a single column when exactly one species
    // is selected; otherwise fall back to the all-tuna trophy sum.
    if (Array.isArray(species)) {
      if (species.length === 1) return species[0];
      return 'totalTuna';
    }
    return species;
  }

  function boatLeaderboard(trips, species, minTrips) {
    const byBoat = {};
    const sf = speciesField(species);
    trips.forEach((t) => {
      if (!byBoat[t.boat]) {
        byBoat[t.boat] = {
          boat: t.boat,
          landing: t.landing,
          trips: [],
        };
      }
      byBoat[t.boat].trips.push(t);
    });
    const allTPAs = [];
    const allTPAsPerDay = [];
    Object.values(byBoat).forEach((b) => {
      b.trips.forEach((t) => {
        if (t.anglers > 0) {
          const tpa = (t[sf] || 0) / t.anglers;
          allTPAs.push(tpa);
          const days = t.calcDays || 1;
          allTPAsPerDay.push(tpa / days);
        }
      });
    });
    const fleetMedianTPA = median(allTPAs);
    const fleetMedianTPAPerDay = median(allTPAsPerDay);

    const rows = Object.values(byBoat).map((b) => {
      const tpas = b.trips.map((t) => (t[sf] || 0) / Math.max(1, t.anglers));
      const tpasPerDay = b.trips.map((t) => {
        const days = t.calcDays || 1;
        return ((t[sf] || 0) / Math.max(1, t.anglers)) / days;
      });
      const totalTuna = b.trips.reduce((s, t) => s + (t[sf] || 0), 0);
      const totalAnglers = b.trips.reduce((s, t) => s + t.anglers, 0);
      const totalAnglerDays = b.trips.reduce((s, t) => s + (t.anglers * (t.calcDays || 1)), 0);
      const avgTPA = totalAnglers ? totalTuna / totalAnglers : 0;
      const avgTPAPerDay = totalAnglerDays ? totalTuna / totalAnglerDays : 0;
      const medTPA = median(tpas);
      const medTPAPerDay = median(tpasPerDay);
      const successCount = b.trips.filter((t) => (t[sf] || 0) > 0).length;
      const successRate = b.trips.length ? successCount / b.trips.length : 0;
      const cv = mean(tpas) > 0 ? stddev(tpas) / mean(tpas) : 0;
      const bestTrip = Math.max(0, ...b.trips.map((t) => t[sf] || 0));
      const bestTripPct = totalTuna > 0 ? bestTrip / totalTuna : 0;
      const aboveAvg = tpas.filter((v) => v > fleetMedianTPA).length;
      const aboveAvgPct = b.trips.length ? aboveAvg / b.trips.length : 0;

      let label = null;
      if (b.trips.length >= (minTrips || 10)) {
        if (avgTPAPerDay > fleetMedianTPAPerDay && medTPAPerDay > fleetMedianTPAPerDay && successRate > 0.6) {
          label = 'Consistent';
        } else if (bestTripPct > 0.4 && b.trips.length < 25) {
          label = 'Spike';
        }
      }

      return {
        boat: b.boat,
        landing: b.landing,
        tripCount: b.trips.length,
        totalTuna,
        totalAnglers,
        avgTPA,
        avgTPAPerDay,
        medTPA,
        medTPAPerDay,
        successRate,
        cv,
        bestTrip,
        bestTripPct,
        aboveAvgPct,
        label,
      };
    });
    rows.sort((a, b) => b.avgTPAPerDay - a.avgTPAPerDay);
    return { rows, fleetMedianTPA, fleetMedianTPAPerDay };
  }

  function landingSummary(trips, species) {
    const sf = speciesField(species);
    const by = {};
    trips.forEach((t) => {
      if (!by[t.landing]) by[t.landing] = { landing: t.landing, trips: 0, anglers: 0, tuna: 0, success: 0, boats: new Set(), bySpecies: { Bluefin: 0, Yellowfin: 0, Skipjack: 0, Bigeye: 0, Albacore: 0 } };
      const r = by[t.landing];
      r.trips++;
      r.anglers += t.anglers;
      r.tuna += t[sf] || 0;
      r.boats.add(t.boat);
      if ((t[sf] || 0) > 0) r.success++;
      ['Bluefin','Yellowfin','Skipjack','Bigeye','Albacore'].forEach(sp => r.bySpecies[sp] += t[sp] || 0);
    });
    return Object.values(by).map((r) => ({
      landing: r.landing,
      trips: r.trips,
      anglers: r.anglers,
      tuna: r.tuna,
      tpa: r.anglers ? r.tuna / r.anglers : 0,
      successRate: r.trips ? r.success / r.trips : 0,
      boatCount: r.boats.size,
      bySpecies: r.bySpecies,
    })).sort((a, b) => b.tpa - a.tpa);
  }

  function monthlyTrend(trips, species) {
    const sf = speciesField(species);
    const months = Array.from({ length: 12 }, (_, i) => ({
      month: i + 1, tuna: 0, anglers: 0, trips: 0,
    }));
    trips.forEach((t) => {
      const m = months[t.month - 1];
      m.tuna += t[sf] || 0;
      m.anglers += t.anglers;
      m.trips++;
    });
    months.forEach((m) => m.tpa = m.anglers ? m.tuna / m.anglers : 0);
    return months;
  }

  function speciesMix(trips) {
    const out = { Bluefin: 0, Yellowfin: 0, Skipjack: 0, Bigeye: 0, Albacore: 0 };
    trips.forEach((t) => {
      out.Bluefin += t.Bluefin || 0;
      out.Yellowfin += t.Yellowfin || 0;
      out.Skipjack += t.Skipjack || 0;
      out.Bigeye += t.Bigeye || 0;
      out.Albacore += t.Albacore || 0;
    });
    return out;
  }

  function moonAnalysis(trips, species) {
    const sf = speciesField(species);
    const phases = ['New', 'Waxing Crescent', 'First Quarter', 'Waxing Gibbous', 'Full', 'Waning Gibbous', 'Last Quarter', 'Waning Crescent'];
    return phases.map((p) => {
      const ts = trips.filter((t) => t.moonPhase === p);
      const tpas = ts.map((t) => (t[sf] || 0) / Math.max(1, t.anglers));
      const totalT = ts.reduce((s, t) => s + (t[sf] || 0), 0);
      const totalA = ts.reduce((s, t) => s + t.anglers, 0);
      return {
        phase: p,
        trips: ts.length,
        tpa: totalA ? totalT / totalA : 0,
        medTPA: median(tpas),
        totalTuna: totalT,
      };
    });
  }

  function dayOfYearHeatmap(trips, species) {
    const sf = speciesField(species);
    // Aggregate by month×day, normalize by anglers
    const map = {};
    trips.forEach((t) => {
      const k = `${t.month}-${t.day}`;
      if (!map[k]) map[k] = { tuna: 0, anglers: 0, trips: 0 };
      map[k].tuna += t[sf] || 0;
      map[k].anglers += t.anglers;
      map[k].trips++;
    });
    return map;
  }

  function bestSingleDays(trips, species, n) {
    const sf = speciesField(species);
    const map = {};
    trips.forEach((t) => {
      if (!map[t.date]) map[t.date] = { date: t.date, tuna: 0, anglers: 0, trips: 0 };
      map[t.date].tuna += t[sf] || 0;
      map[t.date].anglers += t.anglers;
      map[t.date].trips++;
    });
    return Object.values(map)
      .map((d) => ({ ...d, tpa: d.anglers ? d.tuna / d.anglers : 0 }))
      .sort((a, b) => b.tpa - a.tpa)
      .slice(0, n || 10);
  }

  function tripLengthBreakdown(trips, species) {
    const sf = speciesField(species);
    const lens = window.SD.TRIP_LENGTHS;
    return lens.map((len) => {
      const ts = trips.filter((t) => t.tripLength === len);
      const totalT = ts.reduce((s, t) => s + (t[sf] || 0), 0);
      const totalA = ts.reduce((s, t) => s + t.anglers, 0);
      return {
        tripLength: len,
        trips: ts.length,
        tpa: totalA ? totalT / totalA : 0,
        totalTuna: totalT,
      };
    }).filter((r) => r.trips > 0);
  }

  // Head-to-head ("peer") comparisons. For each trip we find peers — other
  // trips on the SAME date with the SAME trip length — and compare this trip's
  // trophy/angler/day against the peer-group median. A boat's peer rank tells
  // you whether it's outperforming the other boats that fished the same
  // conditions (same date, same trip duration).
  function _tpaPerDay(t, sf) {
    const days = t.calcDays || 1;
    return ((t[sf] || 0) / Math.max(1, t.anglers)) / days;
  }

  // Group trips by (date, tripLength) and return only groups with ≥ 2 boats.
  // Returns: [{ date, tripLength, trips: [...] }]
  function peerMatchups(trips, species) {
    const sf = speciesField(species);
    const groups = {};
    trips.forEach((t) => {
      const k = `${t.date}|${t.tripLength}`;
      if (!groups[k]) groups[k] = { date: t.date, tripLength: t.tripLength, trips: [] };
      groups[k].trips.push(t);
    });
    return Object.values(groups)
      .filter((g) => {
        // Need 2+ distinct boats fishing the same date+length.
        const boats = new Set(g.trips.map((t) => t.boat));
        return boats.size >= 2;
      })
      .map((g) => {
        const scored = g.trips.map((t) => ({ ...t, _tpapd: _tpaPerDay(t, sf) }))
                              .sort((a, b) => b._tpapd - a._tpapd);
        const med = median(scored.map((t) => t._tpapd));
        return { date: g.date, tripLength: g.tripLength, trips: scored, peerMedianTPAPerDay: med };
      })
      .sort((a, b) => b.date.localeCompare(a.date));
  }

  // For each boat, aggregate its performance across all matchups it participated
  // in. Returns rows sorted by avgDelta desc (boats most consistently above
  // their peer median come first).
  function peerLeaderboard(trips, species) {
    const sf = speciesField(species);
    const matchups = peerMatchups(trips, species);
    const byBoat = {};
    matchups.forEach((m) => {
      const top = m.trips[0]._tpapd;
      // Wins: tie-break — if 2+ boats share top, each gets a "co-win" (we
      // award 1 win to each tied boat since we can't fairly demote).
      m.trips.forEach((t, idx) => {
        const r = byBoat[t.boat] || (byBoat[t.boat] = {
          boat: t.boat, landing: t.landing,
          matchupCount: 0, wins: 0,
          deltas: [], myTPAPerDays: [], peerMedians: [],
        });
        r.matchupCount++;
        if (t._tpapd >= top - 1e-9) r.wins++;
        r.deltas.push(t._tpapd - m.peerMedianTPAPerDay);
        r.myTPAPerDays.push(t._tpapd);
        r.peerMedians.push(m.peerMedianTPAPerDay);
      });
    });
    const rows = Object.values(byBoat).map((r) => ({
      boat: r.boat,
      landing: r.landing,
      matchupCount: r.matchupCount,
      wins: r.wins,
      winRate: r.matchupCount ? r.wins / r.matchupCount : 0,
      avgDelta: mean(r.deltas),
      avgMy: mean(r.myTPAPerDays),
      avgPeerMedian: mean(r.peerMedians),
      bestWin: Math.max(0, ...r.deltas),
      worstLoss: Math.min(0, ...r.deltas),
    }));
    rows.sort((a, b) => b.avgDelta - a.avgDelta);
    return rows;
  }

  function _isoMinus(isoDate, days) {
    const d = new Date(isoDate + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10);
  }

  function _pctToRatingKey(pct) {
    if (pct >= 90) return 'fire';
    if (pct >= 60) return 'above';
    if (pct >= 40) return 'avg';
    if (pct >= 20) return 'below';
    return 'slow';
  }

  // Returns object keyed by "boat|tripLength" → { winRate, wins, matchupCount, avgTPAPerDay, total }.
  // Win rate = H2H: % of matchups won where 2+ boats ran the same trip length on the same date.
  // winRate is null for boat+tripLength combos with <10 matchups (insufficient sample).
  function boatWinRates() {
    const MIN_MATCHUPS = 10;
    const allTrips = window.SD_PROC_TRIPS || window.SD.TRIPS;

    // Group trips by (date, tripLength) to find competitive matchups
    const byDayLen = {};
    allTrips.forEach(t => {
      const k = `${t.date}|${t.tripLength}`;
      (byDayLen[k] || (byDayLen[k] = [])).push(t);
    });

    // Per (boat, tripLength): H2H wins + matchup count
    const mStats = {};
    Object.values(byDayLen).forEach(group => {
      if (group.length < 2) return;
      const top = Math.max(...group.map(t => t.trophyPerAnglerPerDay || 0));
      group.forEach(t => {
        const k = `${t.boat}|${t.tripLength}`;
        const r = mStats[k] || (mStats[k] = { wins: 0, matchupCount: 0 });
        r.matchupCount++;
        if ((t.trophyPerAnglerPerDay || 0) >= top - 1e-9) r.wins++;
      });
    });

    // Per (boat, tripLength): total trip count + TPA sum (includes non-matchup trips)
    const tStats = {};
    allTrips.forEach(t => {
      const k = `${t.boat}|${t.tripLength}`;
      const r = tStats[k] || (tStats[k] = { tpaSum: 0, total: 0 });
      r.tpaSum += t.trophyPerAnglerPerDay || 0;
      r.total++;
    });

    const out = {};
    Object.entries(tStats).forEach(([k, ts]) => {
      const ms = mStats[k] || { wins: 0, matchupCount: 0 };
      out[k] = {
        total:        ts.total,
        avgTPAPerDay: ts.total > 0 ? ts.tpaSum / ts.total : 0,
        wins:         ms.wins,
        matchupCount: ms.matchupCount,
        winRate:      ms.matchupCount >= MIN_MATCHUPS ? ms.wins / ms.matchupCount : null,
      };
    });
    return out;
  }

  function fishingRating(selectedDate, regions) {
    const _eff = (regions && window.getEffectiveRegion)
      ? window.getEffectiveRegion(regions) : window.CURRENT_REGION;
    const _rl = (_eff && window.getLandingsForRegion)
      ? window.getLandingsForRegion(_eff) : null;
    const allTripsRaw = window.SD_PROC_TRIPS || window.SD.TRIPS;
    const allTrips = _rl ? allTripsRaw.filter(t => _rl.includes(t.landing)) : allTripsRaw;
    const cutoff = _isoMinus(selectedDate, 30);

    const histByLength = {};
    allTrips.forEach(t => {
      if (t.date >= cutoff && t.date < selectedDate) {
        const vals = histByLength[t.tripLength] || (histByLength[t.tripLength] = []);
        vals.push(t.trophyPerAnglerPerDay || 0);
      }
    });

    const todayBoats = allTrips
      .filter(t => t.date === selectedDate)
      .map(t => {
        const hist = histByLength[t.tripLength] || [];
        if (hist.length < 3) return Object.assign({}, t, { ratingKey: 'new', ratingPct: null });
        const myVal = t.trophyPerAnglerPerDay || 0;
        const pct = (hist.filter(v => v <= myVal).length / hist.length) * 100;
        return Object.assign({}, t, { ratingKey: _pctToRatingKey(pct), ratingPct: pct });
      })
      .sort((a, b) => (b.trophyPerAnglerPerDay || 0) - (a.trophyPerAnglerPerDay || 0));

    const valid = todayBoats.filter(b => b.ratingPct != null);
    let fleetRatingKey = null;
    if (valid.length > 0) {
      const totalAnglers = valid.reduce((s, b) => s + b.anglers, 0);
      if (totalAnglers > 0) {
        const wPct = valid.reduce((s, b) => s + b.ratingPct * b.anglers, 0) / totalAnglers;
        fleetRatingKey = _pctToRatingKey(wPct);
      }
    }

    return { boats: todayBoats, fleetRatingKey };
  }

  // For each boat, compute "recent form" from its last 10 trips vs fleet median.
  // Uses the full unfiltered trip dataset so "last 10" is always chronological.
  function boatStreaks(allTrips) {
    // Fleet median trophyPerAnglerPerDay per trip length (all-time) — used as a
    // fallback benchmark on days with too few peers to form a same-day median.
    const byLen = {};
    allTrips.forEach(t => {
      (byLen[t.tripLength] || (byLen[t.tripLength] = [])).push(t.trophyPerAnglerPerDay || 0);
    });
    const fleetMed = {};
    Object.entries(byLen).forEach(([len, vals]) => { fleetMed[len] = median(vals); });

    // Same-day fleet median keyed by date|tripLength, so a trip is judged
    // against the boats it actually competed with that day — this controls for
    // bite conditions (a good day lifts everyone). Requires ≥3 peer trips that
    // day/length to be meaningful; otherwise we fall back to the all-time median.
    const byDayLen = {};
    allTrips.forEach(t => {
      const k = t.date + '|' + t.tripLength;
      (byDayLen[k] || (byDayLen[k] = [])).push(t.trophyPerAnglerPerDay || 0);
    });
    const dayLenMed = {};
    Object.entries(byDayLen).forEach(([k, vals]) => { dayLenMed[k] = median(vals); });

    function benchmarkFor(t) {
      const grp = byDayLen[t.date + '|' + t.tripLength];
      if (grp && grp.length >= 3) return dayLenMed[t.date + '|' + t.tripLength];
      return fleetMed[t.tripLength] ?? 0;
    }

    // Group by boat (landing comes from first occurrence)
    const byBoat = {};
    allTrips.forEach(t => {
      if (!byBoat[t.boat]) byBoat[t.boat] = { trips: [], landing: t.landing };
      byBoat[t.boat].trips.push(t);
    });

    const result = [];
    Object.entries(byBoat).forEach(([boat, d]) => {
      if (d.trips.length < 10) return; // minimum 10 historical trips
      const sorted = [...d.trips].sort((a, b) => b.date.localeCompare(a.date));
      const last10 = sorted.slice(0, 10);
      const dots = last10.map(t => ({
        good: (t.trophyPerAnglerPerDay || 0) > benchmarkFor(t),
        date: t.date,
        tpa: t.trophyPerAnglerPerDay || 0,
      }));
      const goodCount = dots.filter(x => x.good).length;

      // Consecutive same-result streak from most recent
      let streakLen = dots.length > 0 ? 1 : 0;
      for (let i = 1; i < dots.length; i++) {
        if (dots[i].good === dots[0].good) streakLen++;
        else break;
      }
      const streakType = dots.length > 0 ? (dots[0].good ? 'hot' : 'cold') : 'mixed';

      result.push({
        boat,
        landing: d.landing,
        last10: dots,
        goodCount,
        hotPct: Math.round((goodCount / dots.length) * 100),
        streakLen,
        streakType,
        totalTrips: d.trips.length,
      });
    });
    result.sort((a, b) => b.hotPct - a.hotPct);
    return result;
  }

  // Returns object keyed by boat → { rate, wins, total, tier }.
  // Rate = % of trips where this boat ranked in the top 25% of comparable trips
  // (same trip length, within ±3 days of that trip's date, ≥3 other boats required).
  // tier: 'top' (≥50%), 'strong' (35-49%), 'solid' (25-34%), 'developing' (<25%).
  // Pass tripsOverride to restrict to a subset (e.g. last 30 days).
  function boatTopPerformerRates(tripsOverride) {
    const MIN_QUALIFYING = 5;
    const MIN_COMPARABLE = 3;
    const THREE_DAYS_MS  = 3 * 86400000;

    const source = (tripsOverride || window.SD_PROC_TRIPS || window.SD.TRIPS)
      .filter(t => t.trophyPerAnglerPerDay != null);

    // Pre-compute date timestamps and group by tripLength
    const withMs = source.map(t => ({ ...t, _ms: new Date(t.date + 'T00:00:00Z').getTime() }));
    const byLen  = {};
    withMs.forEach(t => (byLen[t.tripLength] || (byLen[t.tripLength] = [])).push(t));

    const stats = {};   // boat → { wins, qualifying }

    withMs.forEach(trip => {
      const bucket     = byLen[trip.tripLength] || [];
      const comparable = bucket.filter(t => t.boat !== trip.boat && Math.abs(t._ms - trip._ms) <= THREE_DAYS_MS);
      if (comparable.length < MIN_COMPARABLE) return;

      const r = stats[trip.boat] || (stats[trip.boat] = { wins: 0, qualifying: 0 });
      r.qualifying++;

      // Top-25% threshold across this trip + all comparable trips
      const allTPAs = [trip.trophyPerAnglerPerDay, ...comparable.map(t => t.trophyPerAnglerPerDay)]
        .sort((a, b) => b - a);
      const threshold = allTPAs[Math.floor(allTPAs.length * 0.25)] ?? 0;

      if (trip.trophyPerAnglerPerDay >= threshold) r.wins++;
    });

    const out = {};
    for (const [boat, s] of Object.entries(stats)) {
      if (s.qualifying < MIN_QUALIFYING) continue;
      const rate = s.wins / s.qualifying;
      out[boat] = {
        rate,
        wins:  s.wins,
        total: s.qualifying,
        tier:  rate >= 0.50 ? 'top' : rate >= 0.35 ? 'strong' : rate >= 0.25 ? 'solid' : 'developing',
      };
    }
    return out;
  }

  // Returns the best upcoming trip to book based on current-year boat rankings.
  // Scans window.SD.SCHEDULE for trips departing within 14 days with open spots,
  // scores by season rank percentile, and returns the top pick with display stats.
  function computeTopTripToBook() {
    const schedule = window.SD?.SCHEDULE || [];
    if (!schedule.length) return null;

    const now = Date.now();
    const cutoff = now + 14 * 24 * 60 * 60 * 1000;
    const year = window.TT_DATES.getPacificYear();

    const upcoming = schedule.filter(t => {
      if (!t.departureAt) return false;
      const dep = new Date(t.departureAt).getTime();
      if (dep <= now || dep > cutoff) return false;
      const spots = t.openSpots ?? (t.capacity != null ? t.capacity - (t.reservedSpots || 0) : null);
      if (spots != null && spots <= 0) return false;
      if (t.tripStatus === 'full') return false;
      return true;
    });
    if (!upcoming.length) return null;

    const allTrips = window.SD_PROC_TRIPS || window.SD?.TRIPS;
    if (!allTrips) return null;

    const yearStart = `${year}-01-01`;
    const yearTrips = allTrips.filter(t => t.date >= yearStart);
    const { rows: lb } = boatLeaderboard(yearTrips, 'all', 3);
    if (!lb.length) return null;

    const rankMap = {};
    lb.forEach((b, i) => {
      rankMap[b.boat] = { rank: i + 1, total: lb.length, avgTPAPerDay: b.avgTPAPerDay, tripCount: b.tripCount };
    });

    let best = null, bestScore = -Infinity;
    for (const trip of upcoming) {
      const stat = rankMap[trip.boat];
      if (!stat) continue;
      const pct = 1 - (stat.rank - 1) / stat.total;
      const dep = new Date(trip.departureAt).getTime();
      const daysAway = (dep - now) / 86400000;
      const score = pct - daysAway * 0.005;
      if (score > bestScore) {
        bestScore = score;
        best = { trip, ...stat };
      }
    }
    if (!best) return null;

    const boatTrips = yearTrips
      .filter(t => t.boat === best.trip.boat)
      .sort((a, b) => b.date.localeCompare(a.date))
      .slice(0, 10);
    const recentTpa = boatTrips.length
      ? boatTrips.reduce((s, t) => s + ((t.totalTuna || 0) / Math.max(1, t.anglers) / (t.calcDays || 1)), 0) / boatTrips.length
      : best.avgTPAPerDay;

    const winRates = boatWinRates();
    const wrKey = `${best.trip.boat}|${best.trip.tripLength}`;
    const wr = winRates[wrKey];
    const openSpots = best.trip.openSpots ??
      (best.trip.capacity != null ? best.trip.capacity - (best.trip.reservedSpots || 0) : null);

    return {
      boat:        best.trip.boat,
      landing:     best.trip.landing,
      tripLength:  best.trip.tripLength,
      departureAt: best.trip.departureAt,
      price:       best.trip.price,
      openSpots,
      recentTpa,
      winRate:     wr?.winRate != null ? Math.round(wr.winRate * 100) : null,
      rank:        best.rank,
      total:       best.total,
    };
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // HALF-DAY ANALYTICS
  // ───────────────────────────────────────────────────────────────────────────
  // Half-day trips (is_half_day=1 in the DB) ship in window.SD.HALF_DAY_TRIPS,
  // separate from the trophy-tuna TRIPS array. The functions below mirror the
  // trophy-side aggregators (preprocessTrips/filterTrips/boatLeaderboard/etc)
  // but operate on the half-day set with three differences:
  //  1. The primary metric is TOTAL FISH per angler (all landed species),
  //     because half-day trips catch bass, rockfish, sheephead, etc. — trophy
  //     tuna is nearly zero.
  //  2. Trips carry a `slot` field derived from tripLength: 'AM' / 'PM' /
  //     'Twilight' / 'Full' — since AM vs PM performance is a real half-day
  //     question that trophy analytics never has to ask.
  //  3. Species filter is multi-select and sums across the selection.

  // Every species field currently exported by src/export.py._trip_to_js.
  // Kept in sync with the (key, col) list there.
  var HD_ALL_SPECIES = [
    'Bluefin','Yellowfin','Yellowtail','Dorado',
    'Skipjack','Bigeye','Albacore',
    'Rockfish','Sheephead','Calico Bass','Sand Bass',
    'Halibut','Lingcod','Whitefish','Bonito','Barracuda','White Sea Bass',
  ];
  // "Rare catch" for a half-day trip: trophy-grade fish that turn a routine
  // near-shore trip into a memorable one. Reported as count per 100 anglers.
  var HD_RARE_SPECIES = ['White Sea Bass', 'Halibut', 'Lingcod', 'Yellowtail'];

  function _hdSlot(tripLength) {
    if (tripLength === 'Half Day AM')       return 'AM';
    if (tripLength === 'Half Day PM')       return 'PM';
    if (tripLength === 'Half Day Twilight') return 'Twilight';
    return 'Full';   // 'Half Day' (no AM/PM qualifier)
  }

  function _hdTotalFish(t) {
    var n = 0;
    for (var i = 0; i < HD_ALL_SPECIES.length; i++) n += t[HD_ALL_SPECIES[i]] || 0;
    return n;
  }

  function preprocessHalfDayTrips(settings) {
    var trophySp = (settings && settings.trophySpecies) || ['Bluefin','Yellowfin','Yellowtail','Dorado'];
    var sixpackSet = _sixpackFilter(settings);
    var src = (window.SD && window.SD.HALF_DAY_TRIPS) || [];
    var out = [];
    for (var i = 0; i < src.length; i++) {
      var t = src[i];
      if (sixpackSet) {
        var key = String(t.boat || '').trim().toLowerCase();
        if (sixpackSet.has(key)) continue;
      }
      var totalFish = _hdTotalFish(t);
      var totalTrophy = trophySp.reduce(function(s, sp) { return s + (t[sp] || 0); }, 0);
      out.push(Object.assign({}, t, {
        totalFish: totalFish,
        totalTuna: totalTrophy,   // keep the field name that shared helpers expect
        calcDays: 1,              // half-day trips normalize to 1-day for TPAD
        slot: _hdSlot(t.tripLength),
      }));
    }
    window.SD_HD_TRIPS = out;
  }

  // Half-day filter: same field shape as filterTrips PLUS a `slot` field.
  // species: array (multi-select) or single string; 'all' passes everything.
  function filterHalfDayTrips(filters, regions) {
    var effectiveRegion = (regions && window.getEffectiveRegion)
      ? window.getEffectiveRegion(regions)
      : window.CURRENT_REGION;
    var regionLandings = (effectiveRegion && window.getLandingsForRegion)
      ? window.getLandingsForRegion(effectiveRegion)
      : null;
    var t = window.SD_HD_TRIPS || [];
    return t.filter(function(r) {
      if (regionLandings && regionLandings.length > 0 && !regionLandings.includes(r.landing)) return false;
      if (!_passes(r.year,       filters.year,       { toNumber: true })) return false;
      if (!_passes(r.month,      filters.month,      { toNumber: true })) return false;
      if (!_passes(r.landing,    filters.landing))                        return false;
      if (!_passes(r.boat,       filters.boat))                           return false;
      if (!_passes(r.slot,       filters.slot))                           return false;
      if (!_passes(r.tripLength, filters.tripLength))                     return false;
      if (filters.species && filters.species !== 'all') {
        var sel = Array.isArray(filters.species) ? filters.species : [filters.species];
        if (sel.length > 0 && !sel.some(function(sp) { return (r[sp] || 0) > 0; })) return false;
      }
      return true;
    });
  }

  // Score a single half-day trip under a given metric. Returns fish-count-like
  // number to be divided by anglers by the caller.
  //   'fpa'     — total fish across all species  (default)
  //   'tpad'    — trophy species (settings.trophySpecies) — same formula as tuna analytics
  //   'species' — sum of user-selected species from filters.species (array)
  function _hdSpeciesSum(t, speciesList) {
    if (!speciesList || speciesList === 'all') return t.totalFish || 0;
    var sel = Array.isArray(speciesList) ? speciesList : [speciesList];
    if (sel.length === 0) return t.totalFish || 0;
    var n = 0;
    for (var i = 0; i < sel.length; i++) n += t[sel[i]] || 0;
    return n;
  }

  // Ranked half-day boat leaderboard. `metric` selects the ranking rule; extra
  // columns (fpa, tpad, wsbRate, halibutRate, lingcodRate, ytRate) are always
  // computed so the UI can show them side-by-side regardless of sort key.
  //   metric: 'fpa' | 'tpad' | 'species'   (default 'fpa')
  //   species: array (only used when metric='species' or for the fpa-of-selection view)
  function halfDayLeaderboard(trips, opts) {
    opts = opts || {};
    var metric   = opts.metric   || 'fpa';
    var species  = opts.species  || 'all';
    var minTrips = opts.minTrips || 3;

    var byBoat = {};
    trips.forEach(function(t) {
      if (!byBoat[t.boat]) byBoat[t.boat] = { boat: t.boat, landing: t.landing, trips: [] };
      byBoat[t.boat].trips.push(t);
    });

    var rows = Object.values(byBoat).map(function(b) {
      var trips = b.trips;
      var totalAnglers = 0, totalFish = 0, totalTrophy = 0, totalSpeciesSel = 0;
      var rareCounts = { 'White Sea Bass': 0, Halibut: 0, Lingcod: 0, Yellowtail: 0 };
      var amTrips = 0, amAnglers = 0, amFish = 0;
      var pmTrips = 0, pmAnglers = 0, pmFish = 0;

      trips.forEach(function(t) {
        var ang = t.anglers || 0;
        totalAnglers    += ang;
        totalFish       += t.totalFish  || 0;
        totalTrophy     += t.totalTuna  || 0;
        totalSpeciesSel += _hdSpeciesSum(t, species);
        for (var i = 0; i < HD_RARE_SPECIES.length; i++) {
          rareCounts[HD_RARE_SPECIES[i]] += t[HD_RARE_SPECIES[i]] || 0;
        }
        if (t.slot === 'AM') { amTrips++; amAnglers += ang; amFish += t.totalFish || 0; }
        if (t.slot === 'PM') { pmTrips++; pmAnglers += ang; pmFish += t.totalFish || 0; }
      });

      var fpa      = totalAnglers ? totalFish       / totalAnglers : 0;
      var tpad     = totalAnglers ? totalTrophy     / totalAnglers : 0;  // calcDays=1 for half-day
      var speciesFpa = totalAnglers ? totalSpeciesSel / totalAnglers : 0;
      var amFpa    = amAnglers ? amFish / amAnglers : 0;
      var pmFpa    = pmAnglers ? pmFish / pmAnglers : 0;

      // Rare-catch rate: total rare fish per 100 anglers.
      var rareSum = HD_RARE_SPECIES.reduce(function(s, sp) { return s + rareCounts[sp]; }, 0);
      var rareRate = totalAnglers ? (rareSum / totalAnglers) * 100 : 0;

      var sortValue = metric === 'tpad'    ? tpad :
                      metric === 'species' ? speciesFpa :
                                             fpa;

      return {
        boat: b.boat, landing: b.landing,
        tripCount:  trips.length,
        totalAnglers: totalAnglers, totalFish: totalFish, totalTrophy: totalTrophy,
        avgAnglers: trips.length ? totalAnglers / trips.length : 0,
        fpa: fpa, tpad: tpad, speciesFpa: speciesFpa,
        amTrips: amTrips, pmTrips: pmTrips, amFpa: amFpa, pmFpa: pmFpa,
        rareCounts: rareCounts, rareRate: rareRate,
        sortValue: sortValue,
      };
    });

    var eligible = rows.filter(function(r) { return r.tripCount >= minTrips; });
    eligible.sort(function(a, b) { return b.sortValue - a.sortValue; });
    return { rows: eligible, allRows: rows, metric: metric, minTrips: minTrips };
  }

  // Head-to-head win rate for half-day boats. A "matchup" = same-date, same-slot
  // pool of ≥2 boats. Wins credited per-matchup (each pair compared). Metric
  // choice ('fpa' | 'tpad' | 'species') decides the comparison value.
  // MIN_MATCHUPS deliberately lower than trophy (10 → 5) because the SD half-
  // day fleet is thin and stricter thresholds would suppress the whole list.
  function halfDayWinRates(trips, opts) {
    opts = opts || {};
    var metric   = opts.metric   || 'fpa';
    var species  = opts.species  || 'all';
    var MIN_MATCHUPS = opts.minMatchups || 5;

    function valOf(t) {
      var ang = Math.max(1, t.anglers || 0);
      if (metric === 'tpad')    return (t.totalTuna || 0) / ang;      // calcDays=1
      if (metric === 'species') return _hdSpeciesSum(t, species) / ang;
      return (t.totalFish || 0) / ang;
    }

    // Group by date + slot so AM and PM boats aren't compared against each other.
    var groups = {};
    trips.forEach(function(t) {
      var k = t.date + '|' + t.slot;
      (groups[k] || (groups[k] = [])).push(t);
    });

    var stats = {};   // boat|landing -> { wins, matchups, sumVal, trips }
    var landingMap = {};
    Object.values(groups).forEach(function(pool) {
      if (pool.length < 2) return;
      var scored = pool.map(function(t) { return { t: t, v: valOf(t) }; });
      scored.forEach(function(a, i) {
        var key = a.t.boat + '|' + a.t.landing;
        landingMap[a.t.boat] = a.t.landing;
        var s = stats[key] || (stats[key] = { wins: 0, matchups: 0, sumVal: 0, trips: 0 });
        s.trips++; s.sumVal += a.v;
        scored.forEach(function(b, j) {
          if (i === j) return;
          s.matchups++;
          if (a.v > b.v) s.wins++;
          else if (a.v === b.v) s.wins += 0.5;
        });
      });
    });

    var out = Object.keys(stats).map(function(key) {
      var parts = key.split('|');
      var s = stats[key];
      return {
        boat:      parts[0],
        landing:   parts[1],
        wins:      s.wins,
        matchups:  s.matchups,
        trips:     s.trips,
        avgVal:    s.trips ? s.sumVal / s.trips : 0,
        winRate:   s.matchups >= MIN_MATCHUPS ? s.wins / s.matchups : null,
      };
    });
    out.sort(function(a, b) {
      var aw = a.winRate == null ? -1 : a.winRate;
      var bw = b.winRate == null ? -1 : b.winRate;
      return bw - aw;
    });
    return out;
  }

  // AM vs PM per-boat comparison. Only boats that ran BOTH slots are returned.
  function halfDayAMvsPM(trips, opts) {
    opts = opts || {};
    var minTripsPerSlot = opts.minTripsPerSlot || 3;
    var byBoat = {};
    trips.forEach(function(t) {
      var slot = t.slot;
      if (slot !== 'AM' && slot !== 'PM') return;
      var r = byBoat[t.boat] || (byBoat[t.boat] = {
        boat: t.boat, landing: t.landing,
        AM: { trips: 0, anglers: 0, fish: 0 },
        PM: { trips: 0, anglers: 0, fish: 0 },
      });
      r[slot].trips++;
      r[slot].anglers += t.anglers || 0;
      r[slot].fish    += t.totalFish || 0;
    });
    return Object.values(byBoat)
      .filter(function(r) { return r.AM.trips >= minTripsPerSlot && r.PM.trips >= minTripsPerSlot; })
      .map(function(r) {
        var amFpa = r.AM.anglers ? r.AM.fish / r.AM.anglers : 0;
        var pmFpa = r.PM.anglers ? r.PM.fish / r.PM.anglers : 0;
        return {
          boat: r.boat, landing: r.landing,
          amTrips: r.AM.trips, pmTrips: r.PM.trips,
          amFpa: amFpa, pmFpa: pmFpa,
          delta: amFpa - pmFpa,
          preferredSlot: amFpa > pmFpa ? 'AM' : (pmFpa > amFpa ? 'PM' : 'even'),
        };
      })
      .sort(function(a, b) { return Math.abs(b.delta) - Math.abs(a.delta); });
  }

  // "Recent form" streak tracker for half-day boats — last 10 trips vs the
  // fleet's same-day / same-slot median (falls back to all-time slot median
  // when the day is thin). Mirrors boatStreaks() on the trophy side.
  function halfDayStreaks(allTrips, opts) {
    opts = opts || {};
    var minTrips = opts.minTrips || 5;

    function fpa(t) { return (t.totalFish || 0) / Math.max(1, t.anglers || 0); }

    // All-time median FpA per slot as a fallback benchmark.
    var bySlot = {};
    allTrips.forEach(function(t) {
      (bySlot[t.slot] || (bySlot[t.slot] = [])).push(fpa(t));
    });
    var slotMed = {};
    Object.entries(bySlot).forEach(function(kv) { slotMed[kv[0]] = median(kv[1]); });

    // Same-day / same-slot median for context-adjusted benchmark.
    var byDaySlot = {};
    allTrips.forEach(function(t) {
      var k = t.date + '|' + t.slot;
      (byDaySlot[k] || (byDaySlot[k] = [])).push(fpa(t));
    });
    var daySlotMed = {};
    Object.entries(byDaySlot).forEach(function(kv) { daySlotMed[kv[0]] = median(kv[1]); });

    function benchmarkFor(t) {
      var grp = byDaySlot[t.date + '|' + t.slot];
      if (grp && grp.length >= 3) return daySlotMed[t.date + '|' + t.slot];
      return slotMed[t.slot] || 0;
    }

    var byBoat = {};
    allTrips.forEach(function(t) {
      if (!byBoat[t.boat]) byBoat[t.boat] = { trips: [], landing: t.landing };
      byBoat[t.boat].trips.push(t);
    });

    var result = [];
    Object.entries(byBoat).forEach(function(kv) {
      var boat = kv[0], d = kv[1];
      if (d.trips.length < minTrips) return;
      var sorted = d.trips.slice().sort(function(a, b) { return b.date.localeCompare(a.date); });
      var last10 = sorted.slice(0, 10);
      var dots = last10.map(function(t) {
        return { good: fpa(t) > benchmarkFor(t), date: t.date, fpa: fpa(t), slot: t.slot };
      });
      var goodCount = dots.filter(function(x) { return x.good; }).length;
      result.push({
        boat: boat, landing: d.landing,
        last10: dots, goodCount: goodCount,
        hotPct: Math.round((goodCount / Math.max(1, dots.length)) * 100),
        totalTrips: d.trips.length,
      });
    });
    result.sort(function(a, b) { return b.hotPct - a.hotPct; });
    return result;
  }

  // Rare-catch leaderboard: WSB / halibut / lingcod / yellowtail per 100 anglers.
  // These four are the half-day "trophies" — infrequent hits that stand out on
  // a day of routine rockfish/bass fishing.
  function halfDayRareCatchRate(trips, opts) {
    opts = opts || {};
    var minTrips = opts.minTrips || 5;
    var byBoat = {};
    trips.forEach(function(t) {
      var r = byBoat[t.boat] || (byBoat[t.boat] = {
        boat: t.boat, landing: t.landing, trips: 0, anglers: 0,
        counts: { 'White Sea Bass': 0, Halibut: 0, Lingcod: 0, Yellowtail: 0 },
      });
      r.trips++; r.anglers += t.anglers || 0;
      HD_RARE_SPECIES.forEach(function(sp) { r.counts[sp] += t[sp] || 0; });
    });
    return Object.values(byBoat)
      .filter(function(b) { return b.trips >= minTrips; })
      .map(function(b) {
        var total = HD_RARE_SPECIES.reduce(function(s, sp) { return s + b.counts[sp]; }, 0);
        var rate  = b.anglers ? (total / b.anglers) * 100 : 0;
        return {
          boat: b.boat, landing: b.landing,
          trips: b.trips, anglers: b.anglers,
          counts: b.counts, total: total, ratePer100: rate,
        };
      })
      .sort(function(a, b) { return b.ratePer100 - a.ratePer100; });
  }

  window.SDA = {
    preprocessTrips,
    filterTrips,
    boatLeaderboard,
    landingSummary,
    monthlyTrend,
    speciesMix,
    moonAnalysis,
    dayOfYearHeatmap,
    bestSingleDays,
    tripLengthBreakdown,
    peerMatchups,
    peerLeaderboard,
    fishingRating,
    boatWinRates,
    boatTopPerformerRates,
    boatStreaks,
    computeTopTripToBook,
    // Half-day aggregators (see block above)
    preprocessHalfDayTrips,
    filterHalfDayTrips,
    halfDayLeaderboard,
    halfDayWinRates,
    halfDayAMvsPM,
    halfDayStreaks,
    halfDayRareCatchRate,
    HD_ALL_SPECIES,
    HD_RARE_SPECIES,
    median, mean, stddev, speciesField,
  };
})();
