window.METRIC_DEFINITIONS = {
  winRate: {
    name: 'Win Rate',
    tooltip: '% of head-to-head matchups won. A matchup is when 2+ boats run the same trip length on the same day — the boat with the highest catch-per-angler wins. Requires 10+ matchups.',
  },
  tpaDay: {
    name: 'TPA/Day',
    tooltip: 'Trophy fish Per Angler per Day. Total trophy-class fish caught divided by anglers, normalized to a per-day basis. Lets you compare boats across different trip lengths.',
  },
  rating: {
    name: 'Rating',
    tooltip: 'How this trip compares to the average TPA/Day for similar trips (same trip length) over the past 30 days. Above Avg = better than the recent norm.',
  },
  forecastScore: {
    name: 'Forecast Score',
    tooltip: 'Predicted fishing quality 1–10, based on water temperature, wind, swell height, moon phase, and years of historical catch data.',
  },
};
