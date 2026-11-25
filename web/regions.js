// Region configuration — San Diego and OC/LA both live.
(function () {
  var SD_LANDINGS = [
    "H&M Landing",
    "Fisherman's Landing",
    "Seaforth Sportfishing",
    "Point Loma Sportfishing",
    "Oceanside Sea Center",
  ];
  var OCLA_LANDINGS = [
    "22nd Street Landing",
    "Long Beach Sportfishing",
    "LA Waterfront Sportfishing",
    "Marina Del Rey Sportfishing",
    "Redondo Beach Sportfishing",
    "Pierpoint Landing",
    "Channel Islands Sportfishing",
    "Ventura Harbor Sportfishing",
    "Newport Landing",
    "Davey's Locker",
    "Dana Wharf Sportfishing",
  ];

  // OC/LA landings' own booking pages (verified 2026-11-25). We have no
  // schedule feed for these landings yet, so Trip Planner links out instead.
  // LA Waterfront is omitted: its site could not be confirmed.
  window.OCLA_LANDING_SITES = {
    "22nd Street Landing":          "https://22ndstreet.fishingreservations.net/sales/",
    "Long Beach Sportfishing":      "https://longbeach.fishingreservations.net/sales/",
    "Marina Del Rey Sportfishing":  "https://mdrsf.com/",
    "Redondo Beach Sportfishing":   "https://redondo.fishingreservations.com/sales/",
    "Pierpoint Landing":            "https://pierpoint.fishingreservations.com/sales/",
    "Channel Islands Sportfishing": "https://ciscos.fishingreservations.net/sales/",
    "Ventura Harbor Sportfishing":  "https://ventura.fishingreservations.com/sales/",
    "Newport Landing":              "https://newportlanding.com/reserve-your-trip.html",
    "Davey's Locker":               "https://daveyslocker.com/deep-sea-fishing-trip-tickets/",
    "Dana Wharf Sportfishing":      "https://danawharf.com/fishing-trips/",
  };

  window.REGIONS = [
    { id: 'san_diego', label: 'San Diego', short: 'San Diego', landings: SD_LANDINGS,   comingSoon: false },
    { id: 'oc_la',     label: 'OC / LA',   short: 'OC / LA',   landings: OCLA_LANDINGS, comingSoon: false },
  ];

  // URL hash prefix ↔ regions array mapping
  window.REGION_HASH_TO_IDS = {
    'sd':      ['san_diego'],
    'ocla':    ['oc_la'],
    'sd+ocla': ['san_diego', 'oc_la'],
  };

  window.regionsToHashPrefix = function (regionIds) {
    var hasSd   = regionIds.indexOf('san_diego') !== -1;
    var hasOcla = regionIds.indexOf('oc_la')     !== -1;
    if (hasSd && hasOcla) return 'sd+ocla';
    if (hasOcla)          return 'ocla';
    return 'sd';
  };

  // Effective single-region string for analytics.js filterTrips
  window.getEffectiveRegion = function (regionIds) {
    var hasSd   = regionIds.indexOf('san_diego') !== -1;
    var hasOcla = regionIds.indexOf('oc_la')     !== -1;
    if (hasSd && hasOcla) return 'all_socal';
    if (hasOcla)          return 'oc_la';
    return 'san_diego';
  };

  // Landing array for filterTrips — null means "no filter, show all"
  window.getLandingsForRegion = function (regionId) {
    if (regionId === 'all_socal') return null;
    var r = (window.REGIONS || []).find(function (r) { return r.id === regionId; });
    return r ? r.landings : null;
  };

  // Header subtitle text
  window.getRegionSubtitle = function (regionIds) {
    var eff = window.getEffectiveRegion(regionIds);
    if (eff === 'all_socal') return 'All SoCal';
    if (eff === 'oc_la')     return 'OC / LA';
    return 'San Diego';
  };
})();
