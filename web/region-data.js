// Per-region data loader. data.js carries the base region (San Diego) only;
// every other region's rows live in data-region-<id>.js (written by
// src/export.py, listed in SD.META.REGION_FILES with a content hash).
// The first time a visitor selects a region, ensure() loads its file and
// merges TRIPS / HALF_DAY_TRIPS / BOATS / SCHEDULE into window.SD, so every
// page keeps reading window.SD exactly as before. New regions (e.g. SF Bay)
// need no change here — only a REGION_FILES entry from the export.
//
// API: window.ttRegionData.isLoaded(regionIds) -> bool
//      window.ttRegionData.ensure(regionIds)   -> Promise (rejects on load error)
// Fires a window 'tt-region-data' event ({detail: {region}}) after each merge.
(function () {
  var loaded = {};
  var pending = {};

  function meta() { return (window.SD && window.SD.META) || {}; }
  function base() { return meta().BASE_REGION || 'san_diego'; }
  function files() { return meta().REGION_FILES || {}; }

  // A region needs loading only when the export listed a file for it. Old
  // data.js files (everything inline, no REGION_FILES) need nothing.
  function needsLoad(id) { return id !== base() && !!files()[id] && !loaded[id]; }

  function byDateThenId(a, b) {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    return (a.id || 0) - (b.id || 0);
  }

  function merge(id) {
    var r = window.SD_REGIONS && window.SD_REGIONS[id];
    if (!r) throw new Error('region file for ' + id + ' did not define its data');
    var SD = window.SD;
    ['TRIPS', 'HALF_DAY_TRIPS', 'BOATS', 'SCHEDULE'].forEach(function (k) {
      if (r[k] && r[k].length) SD[k] = (SD[k] || []).concat(r[k]);
    });
    if (r.TRIPS && r.TRIPS.length) SD.TRIPS.sort(byDateThenId);
    if (r.HALF_DAY_TRIPS && r.HALF_DAY_TRIPS.length) SD.HALF_DAY_TRIPS.sort(byDateThenId);
    // TODAY stays the base region's summary; each region's summary is kept in
    // TODAY_BY_REGION and its still-fishing boats are appended so region-
    // filtered "Still fishing" cards see them.
    SD.TODAY_BY_REGION = SD.TODAY_BY_REGION || {};
    if (!(base() in SD.TODAY_BY_REGION)) SD.TODAY_BY_REGION[base()] = SD.TODAY;
    SD.TODAY_BY_REGION[id] = r.TODAY || null;
    if (r.TODAY && r.TODAY.stillFishing && r.TODAY.stillFishing.length && SD.TODAY) {
      SD.TODAY = Object.assign({}, SD.TODAY, {
        stillFishing: (SD.TODAY.stillFishing || []).concat(r.TODAY.stillFishing),
      });
    }
    // Region-only payloads: CONDITIONS (OC/LA SST + wind points) and MARINE
    // (NWS zones, alerts, smallCraftAdvisory, tides, buoys). The base region's
    // marine data is SD.MARINE in data.js.
    if (r.CONDITIONS) {
      SD.CONDITIONS_BY_REGION = SD.CONDITIONS_BY_REGION || {};
      SD.CONDITIONS_BY_REGION[id] = r.CONDITIONS;
    }
    if (r.MARINE) {
      SD.MARINE_BY_REGION = SD.MARINE_BY_REGION || {};
      if (SD.MARINE && !(base() in SD.MARINE_BY_REGION)) SD.MARINE_BY_REGION[base()] = SD.MARINE;
      SD.MARINE_BY_REGION[id] = r.MARINE;
    }
    SD.META.regionTripCounts = SD.META.regionTripCounts || {};
    SD.META.regionTripCounts[id] = (r.META && r.META.tripCount) || 0;
    delete window.SD_REGIONS[id];
    loaded[id] = true;
    try { window.dispatchEvent(new CustomEvent('tt-region-data', { detail: { region: id } })); } catch (e) {}
  }

  function load(id) {
    if (pending[id]) return pending[id];
    var f = files()[id];
    pending[id] = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = f.file + '?v=' + encodeURIComponent(f.v || '');
      s.async = true;
      s.onload = function () {
        try { merge(id); resolve(); } catch (e) { reject(e); }
      };
      s.onerror = function () { reject(new Error('could not load ' + f.file)); };
      document.head.appendChild(s);
    }).catch(function (e) {
      delete pending[id];   // allow a retry
      throw e;
    });
    return pending[id];
  }

  // Region ids as the app stores them; 'all_socal' style ids are not used here.
  function ids(regionIds) { return (regionIds || []).filter(needsLoad); }

  window.ttRegionData = {
    isLoaded: function (regionIds) { return ids(regionIds).length === 0; },
    ensure: function (regionIds) { return Promise.all(ids(regionIds).map(load)); },
    // Merge a region file that was evaluated some other way (no <script> tag),
    // e.g. the Co-Captain eval harness running files in a Node VM.
    adopt: function (id) { if (!loaded[id]) merge(id); },
    // Trips across every region (data.js + all region files), loaded or not.
    totalTripCount: function () {
      var n = meta().tripCount || 0, f = files();
      Object.keys(f).forEach(function (k) { n += f[k].tripCount || 0; });
      return n;
    },
  };
})();
