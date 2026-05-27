// Region configuration — San Diego is live; OC/LA is coming soon.
// All SoCal will combine both when OC/LA data is available.
(function () {
  var SD_LANDINGS = [
    "H&M Landing",
    "Fisherman's Landing",
    "Seaforth Sportfishing",
    "Point Loma Sportfishing",
    "Oceanside Sea Center"
  ];

  window.REGIONS = [
    { id: 'san_diego', label: 'San Diego',  short: 'SD',        landings: SD_LANDINGS, comingSoon: false },
    { id: 'oc_la',     label: 'OC / LA',    short: 'OC / LA',   landings: [],          comingSoon: true  },
    { id: 'all_socal', label: 'All SoCal',  short: 'All SoCal', landings: null,        comingSoon: false },
  ];

  // Returns array of landing names to filter to, or null for no landing filter.
  // Returns [] for OC/LA (no data yet — callers should show coming-soon UI).
  window.getLandingsForRegion = function (regionId) {
    var r = (window.REGIONS || []).find(function (r) { return r.id === regionId; });
    if (!r) return null;
    return r.landings;
  };
})();
