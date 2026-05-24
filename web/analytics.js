// Analytics aggregations over SD.TRIPS
(function () {
  // Called from app.jsx whenever settings change. Adds `totalTuna` (from
  // user-selected trophy species) and `calcDays` (rounded or actual) to every
  // trip so all downstream analytics respect user preferences without any
  // further changes.
  function preprocessTrips(settings) {
    const trophySp = (settings && settings.trophySpecies) || ['Bluefin','Yellowfin','Yellowtail','Dorado'];
    const method   = (settings && settings.tripLengthMethod) || 'rounded';
    window.SD_PROC_TRIPS = window.SD.TRIPS.map(function(t) {
      var totalTuna = trophySp.reduce(function(s, sp) { return s + (t[sp] || 0); }, 0);
      var rawDays   = t.tripLengthDays > 0 ? t.tripLengthDays : 1;
      var calcDays  = method === 'rounded' ? Math.max(1, Math.floor(rawDays)) : rawDays;
      return Object.assign({}, t, { totalTuna: totalTuna, calcDays: calcDays });
    });
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

  const _SEASONS = {
    spring: [3,4,5], summer: [6,7,8], fall: [9,10,11], winter: [12,1,2],
  };

  function filterTrips(filters) {
    const t = window.SD_PROC_TRIPS || window.SD.TRIPS;
    return t.filter((r) => {
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
      // Season: trip's month must fall inside ANY selected season's months.
      if (filters.season && filters.season !== 'all') {
        const sel = Array.isArray(filters.season) ? filters.season : [filters.season];
        if (sel.length > 0) {
          const months = sel.flatMap(s => _SEASONS[s] || []);
          if (months.length > 0 && !months.includes(r.month)) return false;
        }
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

  // For each trip on selectedDate, look back 30 days of same-trip-length history
  // and compute a percentile rating. Returns rated boat rows + angler-weighted
  // fleet rating key.
  function fishingRating(selectedDate) {
    const allTrips = window.SD_PROC_TRIPS || window.SD.TRIPS;
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
    median, mean, stddev, speciesField,
  };
})();
