window.METRIC_DEFINITIONS = {
  winRate: {
    name: 'Win Rate',
    tooltip: '% of head-to-head matchups won. A matchup is when 2+ boats run the same trip length on the same day — the boat with the most tuna per angler wins. Days when no boat caught tuna don't count as a win. Requires 10+ matchups.',
  },
  tpaDay: {
    name: 'TPA/Day',
    tooltip: 'Tuna Per Angler per Day. Bluefin, yellowfin, bigeye and albacore caught, divided by anglers and trip days. Boats are ranked on it, so a full day and a 3-day trip compare fairly.',
  },
  rating: {
    name: 'Rating',
    tooltip: 'How this trip compares to the average TPA/Day (tuna) for similar trips (same trip length) over the past 30 days. Above Avg = better than the recent norm.',
  },
  forecastScore: {
    name: 'Forecast Score',
    tooltip: 'Predicted fishing quality 1–10, based on water temperature, wind, swell height, moon phase, and years of historical catch data.',
  },
  topPerformerRate: {
    name: 'Top Performer Rate',
    tooltip: '% of trips where this boat landed in the top 25% of comparable trips on tuna per angler per day — same trip length, within ±3 days, vs. boats from all four landings. A more inclusive ranking than Win Rate: any trip with 3+ comparable boats qualifies.',
  },
};
