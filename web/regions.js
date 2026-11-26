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

  // Approximate harbor positions for the Charts map (LANDINGS_META in data.js
  // only carries the San Diego landings). Within ~1 km; shown as "approx".
  window.OCLA_LANDING_COORDS = {
    "22nd Street Landing":          { lat: 33.7225, lng: -118.2803 },
    "LA Waterfront Sportfishing":   { lat: 33.7385, lng: -118.2785 },
    "Long Beach Sportfishing":      { lat: 33.7686, lng: -118.2140 },
    "Pierpoint Landing":            { lat: 33.7620, lng: -118.1950 },
    "Marina Del Rey Sportfishing":  { lat: 33.9770, lng: -118.4490 },
    "Redondo Beach Sportfishing":   { lat: 33.8430, lng: -118.3950 },
    "Channel Islands Sportfishing": { lat: 34.1620, lng: -119.2240 },
    "Ventura Harbor Sportfishing":  { lat: 34.2460, lng: -119.2640 },
    "Newport Landing":              { lat: 33.6020, lng: -117.8880 },
    "Davey's Locker":               { lat: 33.6040, lng: -117.8920 },
    "Dana Wharf Sportfishing":      { lat: 33.4610, lng: -117.6990 },
  };

  window.REGIONS = [
    { id: 'san_diego', label: 'San Diego', short: 'San Diego', landings: SD_LANDINGS,   comingSoon: false },
    { id: 'oc_la',     label: 'OC / LA',   short: 'OC / LA',   landings: OCLA_LANDINGS, comingSoon: false },
  ];

  // SF Bay Area (NorCal): its own data file (data-region-sfbay.js) and pages
  // (sfbay.jsx). Never combined with the SoCal regions. Landings are filled in
  // from the data file when it loads. Only registered behind SHOW_SFBAY.
  var SHOW_SFBAY = !!(window.FEATURES && window.FEATURES.SHOW_SFBAY);
  if (SHOW_SFBAY) {
    window.REGIONS.push({ id: 'sf_bay', label: 'SF Bay Area', short: 'SF Bay', landings: [], comingSoon: false, group: 'norcal' });
  }

  // URL hash prefix ↔ regions array mapping
  window.REGION_HASH_TO_IDS = {
    'sd':      ['san_diego'],
    'ocla':    ['oc_la'],
    'sd+ocla': ['san_diego', 'oc_la'],
  };
  if (SHOW_SFBAY) window.REGION_HASH_TO_IDS['sfbay'] = ['sf_bay'];

  window.regionsToHashPrefix = function (regionIds) {
    if (regionIds.indexOf('sf_bay') !== -1) return 'sfbay';
    var hasSd   = regionIds.indexOf('san_diego') !== -1;
    var hasOcla = regionIds.indexOf('oc_la')     !== -1;
    if (hasSd && hasOcla) return 'sd+ocla';
    if (hasOcla)          return 'ocla';
    return 'sd';
  };

  // Effective single-region string for analytics.js filterTrips
  window.getEffectiveRegion = function (regionIds) {
    if (regionIds.indexOf('sf_bay') !== -1) return 'sf_bay';
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
    if (eff === 'sf_bay')    return 'SF Bay Area';
    if (eff === 'oc_la')     return 'OC / LA';
    return 'San Diego';
  };
})();
