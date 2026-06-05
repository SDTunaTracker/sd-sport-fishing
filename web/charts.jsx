// ── SST source configuration ──────────────────────────────────────────────────

var SST_SOURCES = {
  daily: {
    label: 'Daily (MODIS)',
    badge: null,
    desc: 'Latest single-day MODIS Aqua SST. Marine layer may create cloud gaps — switch to Gap-free for clearer coverage.',
    layer: function() {
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Aqua_L3_SST_Thermal_4km_Day_Daily/default/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png',
        { opacity: 0.75, attribution: 'NASA GIBS · MODIS Aqua', maxNativeZoom: 6 }
      );
    },
  },
  night: {
    label: 'Nightly (MODIS)',
    badge: null,
    desc: 'Nighttime MODIS Aqua SST pass. Different cloud coverage than daytime — may reveal clearer ocean areas.',
    layer: function() {
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Aqua_L3_SST_Thermal_4km_Night_Daily/default/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png',
        { opacity: 0.75, attribution: 'NASA GIBS · MODIS Aqua Night', maxNativeZoom: 6 }
      );
    },
  },
  mur: {
    label: 'Gap-free (MUR)',
    badge: null,
    desc: 'JPL MUR multi-source composite — fuses satellite + in-situ data. No cloud gaps. ~2 day lag. Best for finding temperature breaks.',
    layer: function() {
      var d = new Date();
      d.setDate(d.getDate() - 2);
      var dt = d.toISOString().slice(0, 10);
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/GHRSST_L4_MUR_Sea_Surface_Temperature/default/' + dt + '/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png',
        { opacity: 0.80, attribution: 'NASA GIBS · JPL MUR', maxNativeZoom: 7 }
      );
    },
  },
  raster: {
    label: 'Canvas + Fronts',
    badge: 'New',
    desc: 'Client-rendered 0.04° MUR grid — cloud-free, gap-free. Thermal fronts (orange/red) = SST gradient breaks where bait concentrates. Hover for readout. 3–6 day lag.',
    layer: null, // handled async in ChartsView — not a tile layer
  },
};

// ── Overlay layers (synchronous tile/WMS layers) ──────────────────────────────

function getOverlayLayer(chartType, sstMode) {
  var yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var yday = yesterday.toISOString().slice(0, 10);

  switch (chartType) {
    case 'sst':
      return (SST_SOURCES[sstMode || 'mur'] || SST_SOURCES.mur).layer();
    case 'chlorophyll':
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_NOAA20_Chlorophyll_a/default/' + yday + '/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png',
        { opacity: 0.75, attribution: 'NASA GIBS · VIIRS NOAA-20', maxNativeZoom: 7 }
      );
    case 'bathymetry':
      return L.tileLayer.wms('https://wms.gebco.net/mapserv', {
        layers: 'GEBCO_LATEST', format: 'image/png', transparent: true,
        opacity: 0.65, attribution: '© GEBCO 2024',
      });
    case 'satellite':
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg',
        { opacity: 1.0, attribution: 'NASA GIBS · MODIS Terra', maxNativeZoom: 9 }
      );
    default:
      return null; // wind / waves / tides handled async
  }
}

// ── Conditions grid (Open-Meteo) ──────────────────────────────────────────────

var COND_GRID = [
  { lat: 32.0, lng: -117.7 },  // 302 Spot
  { lat: 32.5, lng: -117.9 },  // Near SD
  { lat: 32.5, lng: -119.1 },  // Cortes Bank
  { lat: 33.0, lng: -117.8 },  // San Clemente area
  { lat: 33.2, lng: -118.5 },  // Catalina area
  { lat: 33.8, lng: -119.5 },  // Santa Cruz Island
];

function fetchConditionsData(type) {
  var hour = new Date().getUTCHours();
  var fetches = COND_GRID.map(function(pt) {
    var url = type === 'wind'
      ? 'https://api.open-meteo.com/v1/forecast?latitude=' + pt.lat + '&longitude=' + pt.lng +
        '&hourly=windspeed_10m,winddirection_10m&forecast_days=1&wind_speed_unit=kn&timezone=UTC'
      : 'https://marine-api.open-meteo.com/v1/marine?latitude=' + pt.lat + '&longitude=' + pt.lng +
        '&hourly=wave_height,wave_direction&forecast_days=1&timezone=UTC';
    return fetch(url)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        var h = d.hourly || {};
        if (type === 'wind') {
          return { lat: pt.lat, lng: pt.lng,
            speed: (h.windspeed_10m || [])[hour],
            dir:   (h.winddirection_10m || [])[hour] };
        }
        var hm = (h.wave_height || [])[hour];
        return { lat: pt.lat, lng: pt.lng,
          height: hm != null ? hm * 3.28084 : null,
          dir:    (h.wave_direction || [])[hour] };
      })
      .catch(function() { return null; });
  });
  return Promise.all(fetches).then(function(r) { return r.filter(Boolean); });
}

function fetchTidesData() {
  var d = new Date();
  var dt = String(d.getFullYear()) +
    String(d.getMonth() + 1).padStart(2, '0') +
    String(d.getDate()).padStart(2, '0');
  return fetch(
    'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?' +
    'station=9410230&product=predictions&datum=MLLW&time_zone=lst_ldt' +
    '&interval=hilo&units=english&application=tunatracker&format=json' +
    '&begin_date=' + dt + '&end_date=' + dt
  ).then(function(r) { return r.json(); });
}

// ── Wind particle grid (leaflet-velocity) ─────────────────────────────────────

var WIND_PARTICLE_COLORS = [
  'rgb(255,255,255)', // 0 m/s  — white (calm)
  'rgb(240,248,255)', // 2      — pale blue
  'rgb(200,220,255)', // 4      — light blue
  'rgb(140,180,255)', // 6      — blue
  'rgb(100,220,180)', // 8      — teal-green
  'rgb(80,220,100)',  // 10     — green
  'rgb(180,220,60)',  // 12     — lime
  'rgb(255,220,50)',  // 14     — yellow
  'rgb(255,180,40)',  // 16     — gold
  'rgb(255,130,30)',  // 18     — orange
  'rgb(255,90,30)',   // 21     — red-orange
  'rgb(240,50,50)',   // 24     — red
  'rgb(200,30,80)',   // 27     — magenta-red
  'rgb(160,30,140)',  // 30     — purple
  'rgb(120,30,180)',  // 33     — deep purple
  'rgb(80,30,180)',   // 35+    — violet (storm)
];
var WAVE_PARTICLE_COLORS = [
  'rgb(59,130,246)',   // calm  — blue
  'rgb(34,197,94)',    // 0.5m  — green
  'rgb(163,230,53)',   // 1.0m  — lime
  'rgb(234,179,8)',    // 1.5m  — yellow
  'rgb(249,115,22)',   // 2.0m  — orange
  'rgb(239,68,68)',    // 2.5m  — red
  'rgb(168,85,247)',   // 3.0m+ — purple
];

var _WIND_NX = 9, _WIND_NY = 9;
var _WIND_LO1 = -121.0, _WIND_LA1 = 35.0, _WIND_DX = 0.5, _WIND_DY = 0.5;
// v2 busts any stale all-zero cache from the previous 81-request implementation
var _WIND_CACHE_KEY = 'tt_wind_grid_v2', _WIND_CACHE_TTL = 3600000;

function _buildWindHeader(extra) {
  return Object.assign({
    parameterCategory: 2,
    lo1: _WIND_LO1, la1: _WIND_LA1,
    lo2: _WIND_LO1 + (_WIND_NX - 1) * _WIND_DX,
    la2: _WIND_LA1 - (_WIND_NY - 1) * _WIND_DY,
    dx: _WIND_DX, dy: _WIND_DY, nx: _WIND_NX, ny: _WIND_NY,
    refTime: new Date().toISOString(),
  }, extra);
}

function _syntheticWindGrid() {
  // Fallback when API fails: ~8kt from SW, with slight variation
  var u = [], v = [];
  for (var i = 0; i < _WIND_NX * _WIND_NY; i++) {
    var spd = 4 + Math.random() * 2; // m/s ≈ 8-12kt
    var dir = 225 + (Math.random() - 0.5) * 30;
    var rad = dir * Math.PI / 180;
    u.push(-(spd * Math.sin(rad)));
    v.push(-(spd * Math.cos(rad)));
  }
  return [
    { header: _buildWindHeader({ parameterNumber: 2 }), data: u },
    { header: _buildWindHeader({ parameterNumber: 3 }), data: v },
  ];
}

function _fetchWindGrid() {
  // Single batch request for all 81 grid points — avoids rate-limiting
  var lats = [], lons = [];
  for (var j = 0; j < _WIND_NY; j++) {
    for (var i = 0; i < _WIND_NX; i++) {
      lats.push((_WIND_LA1 - j * _WIND_DY).toFixed(2));
      lons.push((_WIND_LO1 + i * _WIND_DX).toFixed(2));
    }
  }
  var hour = new Date().getUTCHours();
  var url = 'https://api.open-meteo.com/v1/forecast' +
    '?latitude=' + lats.join(',') +
    '&longitude=' + lons.join(',') +
    '&hourly=windspeed_10m,winddirection_10m' +
    '&forecast_days=1&wind_speed_unit=ms&timezone=UTC';

  return fetch(url)
    .then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function(results) {
      var locs = Array.isArray(results) ? results : [results];
      var u = [], v = [];
      locs.forEach(function(loc) {
        var h = loc.hourly || {};
        var spd = (h.windspeed_10m || [])[hour] || 0;
        var dir = (h.winddirection_10m || [])[hour] || 0;
        var rad = dir * Math.PI / 180;
        u.push(-(spd * Math.sin(rad)));
        v.push(-(spd * Math.cos(rad)));
      });
      return [
        { header: _buildWindHeader({ parameterNumber: 2 }), data: u },
        { header: _buildWindHeader({ parameterNumber: 3 }), data: v },
      ];
    });
}

function getCachedWindGrid() {
  try {
    var c = JSON.parse(localStorage.getItem(_WIND_CACHE_KEY) || 'null');
    if (c && Date.now() - c.ts < _WIND_CACHE_TTL) return Promise.resolve(c.data);
  } catch(e) {}
  return _fetchWindGrid()
    .then(function(data) {
      try { localStorage.setItem(_WIND_CACHE_KEY, JSON.stringify({ ts: Date.now(), data: data })); } catch(e) {}
      return data;
    })
    .catch(function(err) {
      console.warn('Wind grid fetch failed, using synthetic fallback:', err);
      return _syntheticWindGrid();
    });
}

// ── Ocean current particle grid ───────────────────────────────────────────────

var CURRENT_PARTICLE_COLORS = [
  'rgb(20,60,140)', 'rgb(60,110,180)', 'rgb(100,160,220)', 'rgb(140,200,230)',
  'rgb(180,230,220)', 'rgb(220,240,200)', 'rgb(250,230,150)', 'rgb(255,200,100)',
  'rgb(255,150,70)', 'rgb(255,90,50)', 'rgb(220,40,40)',
];
var _CURR_NX = 9, _CURR_NY = 9;
var _CURR_LO1 = -121.0, _CURR_LA1 = 35.0, _CURR_DX = 0.5, _CURR_DY = 0.5;
var _CURR_CACHE_KEY = 'tt_currents_grid_v1', _CURR_CACHE_TTL = 6 * 3600000;

function _buildCurrHeader(extra) {
  return Object.assign({
    parameterCategory: 2,
    lo1: _CURR_LO1, la1: _CURR_LA1,
    lo2: _CURR_LO1 + (_CURR_NX - 1) * _CURR_DX,
    la2: _CURR_LA1 - (_CURR_NY - 1) * _CURR_DY,
    dx: _CURR_DX, dy: _CURR_DY, nx: _CURR_NX, ny: _CURR_NY,
    refTime: new Date().toISOString(),
  }, extra);
}

function _syntheticCurrentGrid() {
  // California Current: generally southward (~185-200°) at 0.1-0.4 m/s (~0.2-0.8 kt)
  var u = [], v = [];
  for (var i = 0; i < _CURR_NX * _CURR_NY; i++) {
    var spd = 0.1 + Math.random() * 0.3;
    var dir = 190 + (Math.random() - 0.5) * 30;
    var rad = dir * Math.PI / 180;
    u.push(-(spd * Math.sin(rad)));
    v.push(-(spd * Math.cos(rad)));
  }
  return [
    { header: _buildCurrHeader({ parameterNumber: 2 }), data: u },
    { header: _buildCurrHeader({ parameterNumber: 3 }), data: v },
  ];
}

function _fetchCurrentGrid() {
  // NOAA ERDDAP: HYCOM regional surface currents (water_u / water_v in m/s)
  var url = 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/HYCOM_GLOBAL_UV_3z.json' +
    '?u[(last)][0][(31.0):(35.0)][(-121.0):(-117.0)]' +
    ',v[(last)][0][(31.0):(35.0)][(-121.0):(-117.0)]';
  return fetch(url)
    .then(function(r) {
      if (!r.ok) throw new Error('ERDDAP HTTP ' + r.status);
      return r.json();
    })
    .then(function(json) {
      // ERDDAP table format: rows = [time, depth, lat, lon, u, v]
      var rows = (json.table && json.table.rows) || [];
      if (rows.length === 0) throw new Error('ERDDAP returned empty table');

      // Build a lat/lon → {u,v} lookup, then sample onto our 9×9 grid
      var lookup = {};
      rows.forEach(function(row) {
        var lat = Math.round(row[2] * 10) / 10;
        var lon = Math.round(row[3] * 10) / 10;
        lookup[lat + ',' + lon] = { u: row[4] || 0, v: row[5] || 0 };
      });

      var uArr = [], vArr = [];
      for (var j = 0; j < _CURR_NY; j++) {
        for (var i = 0; i < _CURR_NX; i++) {
          var lat = Math.round((_CURR_LA1 - j * _CURR_DY) * 10) / 10;
          var lon = Math.round((_CURR_LO1 + i * _CURR_DX) * 10) / 10;
          var pt = lookup[lat + ',' + lon] || { u: 0, v: 0 };
          uArr.push(pt.u);
          vArr.push(pt.v);
        }
      }
      return [
        { header: _buildCurrHeader({ parameterNumber: 2 }), data: uArr },
        { header: _buildCurrHeader({ parameterNumber: 3 }), data: vArr },
      ];
    });
}

function getCachedCurrentGrid() {
  try {
    var c = JSON.parse(localStorage.getItem(_CURR_CACHE_KEY) || 'null');
    if (c && Date.now() - c.ts < _CURR_CACHE_TTL) return Promise.resolve(c.data);
  } catch(e) {}
  return _fetchCurrentGrid()
    .then(function(data) {
      try { localStorage.setItem(_CURR_CACHE_KEY, JSON.stringify({ ts: Date.now(), data: data })); } catch(e) {}
      return data;
    })
    .catch(function(err) {
      console.warn('Current grid fetch failed, using synthetic fallback:', err);
      return _syntheticCurrentGrid();
    });
}

// ── 14-day forecast time series (wind + waves) ───────────────────────────────

var _SERIES_TTL = 3 * 3600000; // 3 h in-memory cache
var _windSeries14d  = null;    // { ts, frames, hours }
var _wavesSeries7d  = null;    // { ts, frames, hours }

function _buildSeriesFrames(locs, getSpd, getDir, headerBuilder, negate) {
  var nHours = ((locs[0].hourly || {}).time || []).length;
  var hours  = (locs[0].hourly || {}).time || [];
  var frames = [];
  for (var t = 0; t < nHours; t++) {
    var u = [], v = [];
    locs.forEach(function(loc) {
      var spd = (getSpd(loc) || [])[t] || 0;
      var dir = (getDir(loc) || [])[t] || 0;
      var rad = dir * Math.PI / 180;
      var sign = negate ? -1 : 1;
      u.push(sign * (spd * Math.sin(rad)));
      v.push(sign * (spd * Math.cos(rad)));
    });
    frames.push([
      { header: headerBuilder({ parameterNumber: 2 }), data: u },
      { header: headerBuilder({ parameterNumber: 3 }), data: v },
    ]);
  }
  return { frames: frames, hours: hours };
}

function _latlonArrays() {
  var lats = [], lons = [];
  for (var j = 0; j < _WIND_NY; j++)
    for (var i = 0; i < _WIND_NX; i++) {
      lats.push((_WIND_LA1 - j * _WIND_DY).toFixed(2));
      lons.push((_WIND_LO1 + i * _WIND_DX).toFixed(2));
    }
  return '?latitude=' + lats.join(',') + '&longitude=' + lons.join(',');
}

function _fetchWindSeries14d() {
  var url = 'https://api.open-meteo.com/v1/forecast' + _latlonArrays() +
    '&hourly=windspeed_10m,winddirection_10m&forecast_days=14&wind_speed_unit=ms&timezone=UTC';
  return fetch(url)
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function(res) {
      var locs = Array.isArray(res) ? res : [res];
      return _buildSeriesFrames(locs,
        function(l) { return (l.hourly || {}).windspeed_10m; },
        function(l) { return (l.hourly || {}).winddirection_10m; },
        _buildWindHeader, true); // wind = "from" → negate
    });
}

function getCachedWindSeries14d() {
  if (_windSeries14d && Date.now() - _windSeries14d.ts < _SERIES_TTL)
    return Promise.resolve(_windSeries14d);
  return _fetchWindSeries14d().then(function(d) {
    _windSeries14d = { ts: Date.now(), frames: d.frames, hours: d.hours };
    return _windSeries14d;
  });
}

function _fetchWavesSeries7d() {
  var url = 'https://marine-api.open-meteo.com/v1/marine' + _latlonArrays() +
    '&hourly=swell_wave_height,swell_wave_direction,swell_wave_period&forecast_days=7&timezone=UTC';
  return fetch(url)
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function(res) {
      var locs = Array.isArray(res) ? res : [res];
      var built = _buildSeriesFrames(locs,
        function(l) { return (l.hourly || {}).swell_wave_height; },
        function(l) { return (l.hourly || {}).swell_wave_direction; },
        _buildWindHeader, true);
      // Average swell period (seconds) per time step across all grid points
      var periods = built.frames.map(function(_, t) {
        var sum = 0, cnt = 0;
        locs.forEach(function(loc) {
          var p = ((loc.hourly || {}).swell_wave_period || [])[t];
          if (p > 0) { sum += p; cnt++; }
        });
        return cnt > 0 ? sum / cnt : 0;
      });
      return { frames: built.frames, hours: built.hours, periods: periods };
    });
}

function getCachedWavesSeries7d() {
  if (_wavesSeries7d && Date.now() - _wavesSeries7d.ts < _SERIES_TTL)
    return Promise.resolve(_wavesSeries7d);
  return _fetchWavesSeries7d().then(function(d) {
    _wavesSeries7d = { ts: Date.now(), frames: d.frames, hours: d.hours, periods: d.periods };
    return _wavesSeries7d;
  });
}

// ── Single-frame swell grid for immediate animated display ───────────────────

var _SWELL_CACHE_KEY = 'tt_swell_grid_v1', _SWELL_CACHE_TTL = 2 * 3600000;

function _fetchSwellGrid() {
  var hour = new Date().getUTCHours();
  var url = 'https://marine-api.open-meteo.com/v1/marine' + _latlonArrays() +
    '&hourly=swell_wave_height,swell_wave_direction,swell_wave_period&forecast_days=1&timezone=UTC';
  return fetch(url)
    .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function(res) {
      var locs = Array.isArray(res) ? res : [res];
      var u = [], v = [], pSum = 0, pCnt = 0;
      locs.forEach(function(loc) {
        var h = loc.hourly || {};
        var spd = (h.swell_wave_height || [])[hour]   || 0;
        var dir = (h.swell_wave_direction || [])[hour] || 0;
        var per = (h.swell_wave_period || [])[hour]   || 0;
        var rad = dir * Math.PI / 180;
        u.push(-(spd * Math.sin(rad)));
        v.push(-(spd * Math.cos(rad)));
        if (per > 0) { pSum += per; pCnt++; }
      });
      return {
        velocityData: [
          { header: _buildWindHeader({ parameterNumber: 2 }), data: u },
          { header: _buildWindHeader({ parameterNumber: 3 }), data: v },
        ],
        avgPeriod: pCnt > 0 ? pSum / pCnt : 0,
      };
    });
}

function getCachedSwellGrid() {
  try {
    var c = JSON.parse(localStorage.getItem(_SWELL_CACHE_KEY) || 'null');
    if (c && Date.now() - c.ts < _SWELL_CACHE_TTL) return Promise.resolve(c.data);
  } catch(e) {}
  return _fetchSwellGrid().then(function(data) {
    try { localStorage.setItem(_SWELL_CACHE_KEY, JSON.stringify({ ts: Date.now(), data: data })); } catch(e) {}
    return data;
  });
}

// ── Pressure isobars ──────────────────────────────────────────────────────────

// Same 9×9 grid extent as wind for easy comparison
var _PRESS_NX = 9, _PRESS_NY = 9;
var _PRESS_LO1 = -121.0, _PRESS_LA1 = 35.0, _PRESS_DX = 0.5, _PRESS_DY = 0.5;
var _PRESS_CACHE_KEY = 'tt_pressure_v1', _PRESS_CACHE_TTL = 2 * 3600000;

var _PRESS_LATS = (function() {
  var a = []; for (var j = 0; j < _PRESS_NY; j++) a.push(_PRESS_LA1 - j * _PRESS_DY); return a;
})();
var _PRESS_LONS = (function() {
  var a = []; for (var i = 0; i < _PRESS_NX; i++) a.push(_PRESS_LO1 + i * _PRESS_DX); return a;
})();

function _fetchPressureGrid() {
  var lats = [], lons = [];
  for (var j = 0; j < _PRESS_NY; j++) {
    for (var i = 0; i < _PRESS_NX; i++) {
      lats.push((_PRESS_LA1 - j * _PRESS_DY).toFixed(2));
      lons.push((_PRESS_LO1 + i * _PRESS_DX).toFixed(2));
    }
  }
  var hour = new Date().getUTCHours();
  return fetch(
    'https://api.open-meteo.com/v1/forecast' +
    '?latitude=' + lats.join(',') + '&longitude=' + lons.join(',') +
    '&hourly=surface_pressure&forecast_days=1&timezone=UTC'
  ).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function(results) {
    var locs = Array.isArray(results) ? results : [results];
    var grid = [];
    for (var j = 0; j < _PRESS_NY; j++) {
      grid[j] = [];
      for (var i = 0; i < _PRESS_NX; i++) {
        var loc = locs[j * _PRESS_NX + i] || {};
        var h = (loc.hourly || {}).surface_pressure || [];
        grid[j][i] = h[hour] || 1013;
      }
    }
    return { grid: grid, lats: _PRESS_LATS, lons: _PRESS_LONS };
  });
}

function getCachedPressureGrid() {
  try {
    var c = JSON.parse(localStorage.getItem(_PRESS_CACHE_KEY) || 'null');
    if (c && Date.now() - c.ts < _PRESS_CACHE_TTL) return Promise.resolve(c.data);
  } catch(e) {}
  return _fetchPressureGrid().then(function(data) {
    try { localStorage.setItem(_PRESS_CACHE_KEY, JSON.stringify({ ts: Date.now(), data: data })); } catch(e) {}
    return data;
  });
}

// Marching squares: returns array of [[lat,lon],[lat,lon]] line segments
function _isobarSegments(grid, lats, lons, level) {
  var segs = [];
  function lerp(a, b, va, vb) {
    return Math.abs(vb - va) < 1e-9 ? a : a + (b - a) * (level - va) / (vb - va);
  }
  for (var r = 0; r < lats.length - 1; r++) {
    for (var c = 0; c < lons.length - 1; c++) {
      var tl = grid[r][c],   tr = grid[r][c+1];
      var bl = grid[r+1][c], br = grid[r+1][c+1];
      var cfg = ((tl >= level) ? 8:0) | ((tr >= level) ? 4:0) |
                ((br >= level) ? 2:0) | ((bl >= level) ? 1:0);
      if (cfg === 0 || cfg === 15) continue;
      var top    = [lats[r],   lerp(lons[c], lons[c+1], tl, tr)];
      var right  = [lerp(lats[r], lats[r+1], tr, br), lons[c+1]];
      var bottom = [lats[r+1], lerp(lons[c], lons[c+1], bl, br)];
      var left   = [lerp(lats[r], lats[r+1], tl, bl), lons[c]];
      var avg = (tl + tr + br + bl) / 4;
      switch (cfg) {
        case 1:  segs.push([left, bottom]); break;
        case 2:  segs.push([bottom, right]); break;
        case 3:  segs.push([left, right]); break;
        case 4:  segs.push([top, right]); break;
        case 5:  if (avg >= level) { segs.push([top, left]); segs.push([right, bottom]); }
                 else              { segs.push([top, right]); segs.push([left, bottom]); } break;
        case 6:  segs.push([top, bottom]); break;
        case 7:  segs.push([top, left]); break;
        case 8:  segs.push([top, left]); break;
        case 9:  segs.push([top, bottom]); break;
        case 10: if (avg >= level) { segs.push([top, right]); segs.push([left, bottom]); }
                 else              { segs.push([top, left]); segs.push([right, bottom]); } break;
        case 11: segs.push([top, right]); break;
        case 12: segs.push([left, right]); break;
        case 13: segs.push([bottom, right]); break;
        case 14: segs.push([left, bottom]); break;
      }
    }
  }
  return segs;
}

function _buildIsobarLayer(grid, lats, lons) {
  var group = L.layerGroup();
  var minP = Infinity, maxP = -Infinity;
  for (var r = 0; r < lats.length; r++) {
    for (var c = 0; c < lons.length; c++) {
      if (grid[r][c] < minP) minP = grid[r][c];
      if (grid[r][c] > maxP) maxP = grid[r][c];
    }
  }
  var firstLevel = Math.ceil(minP / 4) * 4;
  var lastLevel  = Math.floor(maxP / 4) * 4;

  for (var level = firstLevel; level <= lastLevel; level += 4) {
    var segs = _isobarSegments(grid, lats, lons, level);
    if (segs.length === 0) continue;
    var isMajor = (level % 8 === 0);
    var color = level <= 1008 ? '#3b82f6' :   // low — blue
                level >= 1020 ? '#dc2626' :   // high — red
                '#64748b';                    // mid — slate
    var weight = isMajor ? 2.5 : 1.5;
    segs.forEach(function(seg) {
      L.polyline(seg, {
        color: color, weight: weight, opacity: 0.8,
        smoothFactor: 1.5, lineCap: 'round', lineJoin: 'round',
      }).addTo(group);
    });
    if (isMajor && segs.length > 0) {
      var ls = segs[Math.floor(segs.length / 2)];
      L.marker([(ls[0][0] + ls[1][0]) / 2, (ls[0][1] + ls[1][1]) / 2], {
        icon: L.divIcon({
          className: 'isobar-label',
          html: '<span style="color:' + color + '">' + level + '</span>',
          iconSize: [36, 16], iconAnchor: [18, 8],
        }),
        interactive: false,
      }).addTo(group);
    }
  }
  return group;
}

// ── MUR SST canvas raster + thermal-front overlay ────────────────────────────

var _MUR_RASTER_BBOX = { latMin: 30.0, latMax: 34.5, lonMin: -121.5, lonMax: -116.0 };
var _MUR_RASTER_STRIDE = 4;           // every 4th 0.01° native cell → ~0.04° ≈ 4.4 km
var _MUR_RASTER_CACHE_KEY = 'tt_mur_raster_v1';
var _MUR_RASTER_CACHE_TTL = 22 * 3600000; // 22 h — MUR is daily, refresh once per day

// SST color ramp: [°F, r, g, b] breakpoints
var _SST_RAMP = [
  [55,  0,  20, 180],   // deep blue
  [60,  0,  80, 220],   // blue
  [63, 20, 160, 220],   // cyan
  [66, 80, 210, 120],   // green
  [68,160, 230,  60],   // lime
  [70,230, 230,  50],   // yellow
  [72,255, 180,  40],   // orange
  [74,255,  80,  20],   // red-orange
  [76,200,  20,  20],   // red
];

function _sstRgb(f) {
  var r = _SST_RAMP;
  if (f <= r[0][0]) return [r[0][1], r[0][2], r[0][3]];
  for (var i = 1; i < r.length; i++) {
    if (f <= r[i][0]) {
      var t = (f - r[i-1][0]) / (r[i][0] - r[i-1][0]);
      return [
        Math.round(r[i-1][1] + t*(r[i][1]-r[i-1][1])),
        Math.round(r[i-1][2] + t*(r[i][2]-r[i-1][2])),
        Math.round(r[i-1][3] + t*(r[i][3]-r[i-1][3])),
      ];
    }
  }
  var last = r[r.length-1];
  return [last[1], last[2], last[3]];
}

function _fetchMURRasterGrid(dateStr) {
  var t = dateStr + 'T09:00:00Z';
  var b = _MUR_RASTER_BBOX, s = _MUR_RASTER_STRIDE;
  var url = 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.json' +
    '?analysed_sst' +
    '[(' + t + '):1:(' + t + ')]' +
    '[(' + b.latMin + '):' + s + ':(' + b.latMax + ')]' +
    '[(' + b.lonMin + '):' + s + ':(' + b.lonMax + ')]';
  return fetch(url)
    .then(function(r) {
      if (!r.ok) throw new Error('ERDDAP HTTP ' + r.status);
      return r.json();
    })
    .then(function(d) {
      var tbl = d.table || {};
      var cols = tbl.columnNames || [];
      var latI = cols.indexOf('latitude'), lonI = cols.indexOf('longitude'), sstI = cols.indexOf('analysed_sst');
      if (sstI === -1) throw new Error('no analysed_sst column');
      var rows = tbl.rows || [];
      if (rows.length < 20) throw new Error('too few rows: ' + rows.length);

      var latSet = Object.create(null), lonSet = Object.create(null);
      for (var i = 0; i < rows.length; i++) {
        if (rows[i][sstI] !== null) { latSet[rows[i][latI]] = true; lonSet[rows[i][lonI]] = true; }
      }
      var lats = Object.keys(latSet).map(Number).sort(function(a,b){return a-b;});
      var lons = Object.keys(lonSet).map(Number).sort(function(a,b){return a-b;});
      var ny = lats.length, nx = lons.length;
      if (ny < 5 || nx < 5) throw new Error('grid too small: ' + ny + 'x' + nx);

      var dlat = ny > 1 ? lats[1]-lats[0] : 0.04;
      var dlon = nx > 1 ? lons[1]-lons[0] : 0.04;
      var values = new Float32Array(ny * nx);
      values.fill(NaN);
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        if (row[sstI] === null) continue;
        var sst_c = row[sstI];
        if (sst_c > 200) sst_c -= 273.15; // Kelvin guard
        var li  = Math.round((row[latI] - lats[0]) / dlat);
        var loi = Math.round((row[lonI] - lons[0]) / dlon);
        if (li >= 0 && li < ny && loi >= 0 && loi < nx)
          values[li * nx + loi] = sst_c * 9/5 + 32; // → °F
      }
      return { lats: lats, lons: lons, values: values, nx: nx, ny: ny, dlat: dlat, dlon: dlon, date: dateStr };
    });
}

function _getCachedMURRasterGrid() {
  try {
    var c = JSON.parse(localStorage.getItem(_MUR_RASTER_CACHE_KEY) || 'null');
    if (c && c.data && Date.now() - c.ts < _MUR_RASTER_CACHE_TTL) {
      c.data.values = new Float32Array(c.data.values);
      return Promise.resolve(c.data);
    }
  } catch(e) {}
  var today = new Date();
  function attempt(back) {
    if (back > 9) return Promise.reject(new Error('MUR: no data in last 9 days'));
    var d = new Date(today); d.setDate(d.getDate() - back);
    return _fetchMURRasterGrid(d.toISOString().slice(0,10))
      .then(function(data) {
        try {
          localStorage.setItem(_MUR_RASTER_CACHE_KEY, JSON.stringify({
            ts: Date.now(),
            data: { lats: data.lats, lons: data.lons, nx: data.nx, ny: data.ny,
                    dlat: data.dlat, dlon: data.dlon, date: data.date,
                    values: Array.from(data.values) },
          }));
        } catch(e) {}
        return data;
      })
      .catch(function() { return attempt(back + 1); });
  }
  return attempt(3);
}

function _renderSSTCanvas(grid) {
  var nx = grid.nx, ny = grid.ny;
  var canvas = document.createElement('canvas');
  canvas.width = nx; canvas.height = ny;
  var ctx = canvas.getContext('2d');
  var img = ctx.createImageData(nx, ny);
  var px = img.data;
  for (var row = 0; row < ny; row++) {
    var li = ny - 1 - row; // canvas row 0 = top = north = high lat index
    for (var col = 0; col < nx; col++) {
      var v = grid.values[li * nx + col];
      var p = (row * nx + col) * 4;
      if (isNaN(v)) { px[p+3] = 0; continue; }
      var rgb = _sstRgb(v);
      px[p] = rgb[0]; px[p+1] = rgb[1]; px[p+2] = rgb[2]; px[p+3] = 215;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}

function _renderFrontCanvas(grid) {
  // Paint cells where |∇SST| exceeds threshold — the thermal-front layer
  var nx = grid.nx, ny = grid.ny;
  var canvas = document.createElement('canvas');
  canvas.width = nx; canvas.height = ny;
  var ctx = canvas.getContext('2d');
  var img = ctx.createImageData(nx, ny);
  var px = img.data;
  // Thresholds in °F per grid cell (1 cell ≈ 4.4 km)
  var FMIN = 0.8, FMAX = 4.0;
  for (var row = 0; row < ny; row++) {
    var li = ny - 1 - row;
    for (var col = 0; col < nx; col++) {
      var p = (row * nx + col) * 4;
      if (li < 1 || li >= ny-1 || col < 1 || col >= nx-1) { px[p+3] = 0; continue; }
      var here = grid.values[li * nx + col];
      if (isNaN(here)) { px[p+3] = 0; continue; }
      var n = grid.values[(li+1)*nx+col], s = grid.values[(li-1)*nx+col];
      var e = grid.values[li*nx+(col+1)], w = grid.values[li*nx+(col-1)];
      if (isNaN(n)||isNaN(s)||isNaN(e)||isNaN(w)) { px[p+3] = 0; continue; }
      var dLat = (n-s)/2, dLon = (e-w)/2;
      var grad = Math.sqrt(dLat*dLat + dLon*dLon);
      if (grad < FMIN) { px[p+3] = 0; continue; }
      var t = Math.min((grad - FMIN) / (FMAX - FMIN), 1.0);
      // yellow → orange → red
      px[p] = 255; px[p+1] = Math.round(220*(1-t)); px[p+2] = 0;
      px[p+3] = Math.round(80 + t*160);
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}

function _buildMUROverlays(grid) {
  var b = _MUR_RASTER_BBOX;
  var bounds = L.latLngBounds([[b.latMin, b.lonMin], [b.latMax, b.lonMax]]);
  return {
    sst:   L.imageOverlay(_renderSSTCanvas(grid).toDataURL(), bounds, { opacity: 0.85, interactive: false }),
    front: L.imageOverlay(_renderFrontCanvas(grid).toDataURL(), bounds, { opacity: 0.90, interactive: false }),
  };
}

function _murGridReadout(grid, latlng) {
  var lat = latlng.lat, lng = latlng.lng;
  var b = _MUR_RASTER_BBOX;
  if (lat < b.latMin || lat > b.latMax || lng < b.lonMin || lng > b.lonMax) return null;
  var li  = Math.max(0, Math.min(grid.ny-1, Math.round((lat - grid.lats[0]) / grid.dlat)));
  var loi = Math.max(0, Math.min(grid.nx-1, Math.round((lng - grid.lons[0]) / grid.dlon)));
  var sst = grid.values[li * grid.nx + loi];
  if (isNaN(sst)) return { sst: null, grad: null };
  var grad = null;
  if (li > 0 && li < grid.ny-1 && loi > 0 && loi < grid.nx-1) {
    var n = grid.values[(li+1)*grid.nx+loi], s = grid.values[(li-1)*grid.nx+loi];
    var e = grid.values[li*grid.nx+(loi+1)], w = grid.values[li*grid.nx+(loi-1)];
    if (!isNaN(n)&&!isNaN(s)&&!isNaN(e)&&!isNaN(w)) {
      var dLat=(n-s)/2, dLon=(e-w)/2;
      // convert from °F/cell to °C/km (1 cell ≈ 4.4 km, 1°F = 0.556°C)
      grad = Math.sqrt(dLat*dLat+dLon*dLon) * 0.556 / 4.4;
    }
  }
  return { sst: sst, grad: grad };
}

// ── Point readout: sample active layers at a lat/lng for the tap popup ─────────

// Sample a leaflet-velocity u/v grid pair ([{header,data:u},{header,data:v}])
// at a lat/lng. Returns magnitude (m/s for wind/current, m for swell height)
// plus the FROM bearing (wind/swell convention) and TO bearing (current flow).
function _sampleVelGrid(pair, latlng) {
  if (!pair || !pair[0] || !pair[1]) return null;
  var h = pair[0].header, u = pair[0].data, v = pair[1].data;
  var col = Math.round((latlng.lng - h.lo1) / h.dx);
  var row = Math.round((h.la1 - latlng.lat) / h.dy);
  if (col < 0 || col >= h.nx || row < 0 || row >= h.ny) return null;
  var idx = row * h.nx + col;
  var uu = u[idx], vv = v[idx];
  if (uu == null || vv == null) return null;
  var speed = Math.sqrt(uu * uu + vv * vv);
  var toDir = (Math.atan2(uu, vv) * 180 / Math.PI + 360) % 360;
  return { speed: speed, toDir: toDir, fromDir: (toDir + 180) % 360 };
}

// Sample the pressure scalar grid ({ grid:[row][col], lats, lons }).
function _samplePressureGrid(p, latlng) {
  if (!p || !p.grid || !p.lats || !p.lons) return null;
  var dLon = p.lons.length > 1 ? p.lons[1] - p.lons[0] : 0.5;
  var dLat = p.lats.length > 1 ? p.lats[0] - p.lats[1] : 0.5;
  var col = Math.round((latlng.lng - p.lons[0]) / dLon);
  var row = Math.round((p.lats[0] - latlng.lat) / dLat);
  if (row < 0 || row >= p.lats.length || col < 0 || col >= p.lons.length) return null;
  var val = p.grid[row] && p.grid[row][col];
  return (val == null || isNaN(val)) ? null : val;
}

function _compass8(deg) {
  return ['N','NE','E','SE','S','SW','W','NW'][Math.round(deg / 45) % 8];
}

// Unit-aware formatters. Stored units: temp °F, wind/current m/s, swell m, pressure hPa.
function _fmtTemp(f, sys)     { return sys === 'metric' ? ((f - 32) * 5 / 9).toFixed(1) + '°C' : f.toFixed(1) + '°F'; }
function _fmtSpeed(ms, sys)   { return sys === 'metric' ? ms.toFixed(1) + ' m/s' : (ms * 1.94384).toFixed(1) + ' kt'; }
function _fmtSwell(m, sys)    { return sys === 'metric' ? m.toFixed(1) + ' m'   : (m * 3.28084).toFixed(1) + ' ft'; }
function _fmtPressure(h, sys) { return sys === 'metric' ? Math.round(h) + ' hPa' : (h * 0.02953).toFixed(2) + ' inHg'; }

// "Locate me" coverage: SoCal coast + offshore grounds (San Diego through the
// Channel Islands / Ventura). A user whose location falls inside this box gets
// a "you are here" point; outside it, we keep the default San Diego view.
var _GEO_SUPPORTED_BBOX = { latMin: 31.0, latMax: 35.5, lonMin: -122.0, lonMax: -116.3 };

// ── Conditions rendering ──────────────────────────────────────────────────────

function windColor(kts) {
  if (kts == null) return '#94a3b8';
  if (kts < 8)  return '#22c55e';
  if (kts < 15) return '#84cc16';
  if (kts < 21) return '#eab308';
  if (kts < 28) return '#f97316';
  return '#ef4444';
}

function waveColor(ft) {
  if (ft == null) return '#94a3b8';
  if (ft < 2)  return '#3b82f6';
  if (ft < 4)  return '#22c55e';
  if (ft < 6)  return '#eab308';
  if (ft < 8)  return '#f97316';
  return '#ef4444';
}

function condArrowHtml(type, pt) {
  var isWind = type === 'wind';
  var value  = isWind ? pt.speed : pt.height;
  var color  = isWind ? windColor(value) : waveColor(value);
  // dir is meteorological FROM-direction; +180 = direction wind/waves are travelling
  var deg    = ((pt.dir || 0) + 180) % 360;
  var label  = isWind
    ? (value != null ? Math.round(value) + ' kt' : '—')
    : (value != null ? Math.round(value) + ' ft' : '—');

  var svg =
    '<svg width="20" height="20" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">' +
      '<g transform="rotate(' + deg + ',10,10)">' +
        '<polygon points="10,2 14,16 10,13 6,16" fill="' + color + '" stroke="white" stroke-width="0.8"/>' +
      '</g></svg>';

  return '<div class="cond-wrap">' +
    '<div class="cond-bg" style="border-color:' + color + '">' + svg + '</div>' +
    '<div class="cond-lbl" style="color:' + color + '">' + label + '</div>' +
  '</div>';
}

function buildConditionsLayer(type, data) {
  var group = L.layerGroup();
  data.forEach(function(pt) {
    var isWind = type === 'wind';
    var value = isWind ? pt.speed : pt.height;
    var color = isWind ? windColor(value) : waveColor(value);
    var labelTip = isWind
      ? 'Wind: ' + (value != null ? Math.round(value) + ' kt' : '—') + ' from ' + Math.round(pt.dir || 0) + '°'
      : 'Waves: ' + (value != null ? (value).toFixed(1) + ' ft' : '—') + ' from ' + Math.round(pt.dir || 0) + '°';

    L.marker([pt.lat, pt.lng], {
      icon: L.divIcon({
        className: 'cond-icon',
        html: condArrowHtml(type, pt),
        iconSize: [46, 52],
        iconAnchor: [23, 26],
      }),
    }).addTo(group).bindTooltip(labelTip, { direction: 'top' });
  });
  return group;
}

// ── Landing pins + bank markers ───────────────────────────────────────────────

function addLandingPins(map) {
  var landings = (window.SD && window.SD.LANDINGS_META) || [];
  var icon = L.divIcon({
    className: 'landing-marker',
    html: '<div class="landing-pin"></div>',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
  landings.forEach(function(landing) {
    if (!landing || !landing.lat || !landing.lng) return;
    if (landing.region === 'san_diego' || !landing.region) {
      L.marker([landing.lat, landing.lng], { icon: icon })
        .addTo(map)
        .bindPopup('<b>' + landing.name + '</b>');
    }
  });
}

function addBankMarkers(map) {
  var banks = [
    { name: '9-Mile Bank',  lat: 32.7,  lng: -117.4, dir: 'top' },
    { name: '43 Fathom',    lat: 32.8,  lng: -117.6, dir: 'left' },
    { name: '60-Mile Bank', lat: 32.4,  lng: -117.7, dir: 'bottom' },
    { name: '182 Spot',     lat: 32.6,  lng: -118.0, dir: 'top' },
    { name: '209 Spot',     lat: 32.3,  lng: -117.9, dir: 'bottom' },
    { name: 'Tanner Bank',  lat: 32.7,  lng: -119.1, dir: 'top' },
    { name: 'Cortes Bank',  lat: 32.4,  lng: -119.1, dir: 'bottom' },
    { name: '302 Spot',     lat: 32.0,  lng: -117.7, dir: 'right' },
  ];
  banks.forEach(function(b) {
    L.circleMarker([b.lat, b.lng], {
      radius: 5, color: '#fff', weight: 2,
      fillColor: '#1E293B', fillOpacity: 0.95,
    }).addTo(map).bindTooltip(b.name, {
      permanent: false, direction: b.dir,
      offset: [0, b.dir === 'top' ? -6 : b.dir === 'bottom' ? 6 : 0],
      className: 'bank-label',
    });
  });
}

// ── Waypoints helpers ─────────────────────────────────────────────────────────

function loadWaypoints() {
  try { return JSON.parse(localStorage.getItem('tt_waypoints') || '[]'); }
  catch(e) { return []; }
}

function persistWaypoints(wps) {
  localStorage.setItem('tt_waypoints', JSON.stringify(wps));
}

function escXml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function exportWaypoints(waypoints, format) {
  var content, filename, mime;
  if (format === 'gpx') {
    content = '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="The Tuna Tracker">\n' +
      waypoints.map(function(wp) {
        return '  <wpt lat="' + wp.lat.toFixed(6) + '" lon="' + wp.lng.toFixed(6) + '">\n' +
               '    <name>' + escXml(wp.name) + '</name>\n' +
               '    <desc>' + escXml(wp.notes) + '</desc>\n  </wpt>';
      }).join('\n') + '\n</gpx>';
    filename = 'tuna-tracker-waypoints.gpx'; mime = 'application/gpx+xml';
  } else if (format === 'kml') {
    content = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n' +
      waypoints.map(function(wp) {
        return '  <Placemark>\n    <name>' + escXml(wp.name) + '</name>\n' +
               '    <description>' + escXml(wp.notes) + '</description>\n' +
               '    <Point><coordinates>' + wp.lng.toFixed(6) + ',' + wp.lat.toFixed(6) + ',0</coordinates></Point>\n  </Placemark>';
      }).join('\n') + '\n</Document>\n</kml>';
    filename = 'tuna-tracker-waypoints.kml'; mime = 'application/vnd.google-earth.kml+xml';
  } else {
    content = 'Name,Latitude,Longitude,Notes,Created\n' +
      waypoints.map(function(wp) {
        return '"' + wp.name.replace(/"/g,'""') + '",' + wp.lat.toFixed(6) + ',' + wp.lng.toFixed(6) + ',' +
               '"' + (wp.notes||'').replace(/"/g,'""') + '","' + (wp.created_at||'') + '"';
      }).join('\n');
    filename = 'tuna-tracker-waypoints.csv'; mime = 'text/csv';
  }
  var blob = new Blob([content], { type: mime });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// ── TidesPanel ────────────────────────────────────────────────────────────────

function TidesPanel({ data, loading }) {
  if (loading) {
    return <div className="tides-panel"><SkeletonRows count={4} height={28} /></div>;
  }
  if (!data || !data.predictions || data.predictions.length === 0) {
    var err = data && data.error ? data.error.message : 'Unavailable';
    return <div className="tides-panel"><div className="tides-error">Tide data unavailable — {err}</div></div>;
  }

  var now = new Date();
  var preds = data.predictions.map(function(p) {
    return {
      t: p.t, v: parseFloat(p.v), type: p.type,
      date: new Date(p.t.replace(' ', 'T')),
    };
  });

  var past   = preds.filter(function(p) { return p.date <= now; });
  var future = preds.filter(function(p) { return p.date > now; });
  var last   = past[past.length - 1];
  var next   = future[0];

  var phase = last ? (last.type === 'L' ? 'Rising' : 'Falling') : '—';

  function fmtTime(t) {
    var parts = t.split(' ')[1].split(':');
    var h = parseInt(parts[0]), m = parts[1];
    return (h % 12 || 12) + ':' + m + (h >= 12 ? ' PM' : ' AM');
  }

  function fmtHeight(v) { return (v >= 0 ? '+' : '') + v.toFixed(1) + ' ft'; }

  return (
    <div className="tides-panel">
      <div className="tides-station-row">
        <span className="tides-station">San Diego — NOAA Station 9410230</span>
        <span className="tides-date">{now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</span>
      </div>
      <div className="tides-summary">
        <div className="tides-summary-item">
          <span className="tides-sum-label">Tide phase</span>
          <span className="tides-sum-value">{phase}</span>
        </div>
        {next && (
          <div className="tides-summary-item">
            <span className="tides-sum-label">Next {next.type === 'H' ? 'High' : 'Low'}</span>
            <span className="tides-sum-value">{fmtTime(next.t)}</span>
          </div>
        )}
        {next && (
          <div className="tides-summary-item">
            <span className="tides-sum-label">{next.type === 'H' ? 'High' : 'Low'} height</span>
            <span className={'tides-sum-value ' + (next.type === 'H' ? 'tide-high' : 'tide-low')}>{fmtHeight(next.v)}</span>
          </div>
        )}
      </div>
      <div className="tides-schedule">
        <div className="tides-schedule-title">Today's tide schedule</div>
        {preds.map(function(p, i) {
          var isNext = next && p.t === next.t;
          return (
            <div key={i} className={'tide-row' + (isNext ? ' tide-row-next' : '') + (p.date <= now ? ' tide-row-past' : '')}>
              <span className={'tide-type-badge ' + (p.type === 'H' ? 'tide-high-badge' : 'tide-low-badge')}>
                {p.type === 'H' ? '▲ High' : '▼ Low'}
              </span>
              <span className="tide-row-time">{fmtTime(p.t)}</span>
              <span className="tide-row-height">{fmtHeight(p.v)}</span>
              {isNext && <span className="tide-next-pill">Next</span>}
            </div>
          );
        })}
      </div>
      <div className="tides-note">Fish are most active on moving tides — incoming and outgoing.</div>
    </div>
  );
}

// ── WaypointModal ─────────────────────────────────────────────────────────────

function WaypointModal({ latlng, onSave, onClose }) {
  const [name, setName]   = React.useState('');
  const [notes, setNotes] = React.useState('');

  function handleSave(e) {
    e.preventDefault();
    if (!name.trim()) return;
    onSave({
      id: 'wp_' + Date.now(), name: name.trim(), notes: notes.trim(),
      lat: latlng.lat, lng: latlng.lng, created_at: new Date().toISOString(),
    });
    onClose();
  }

  return (
    <div className="wp-modal-overlay" onClick={onClose}>
      <div className="wp-modal" onClick={function(e) { e.stopPropagation(); }}>
        <div className="wp-modal-header">
          <span>Save Waypoint</span>
          <button className="wp-modal-close" onClick={onClose}>×</button>
        </div>
        <form className="wp-modal-body" onSubmit={handleSave}>
          <div className="wp-field">
            <label>Name</label>
            <input value={name} onChange={function(e) { setName(e.target.value); }}
                   placeholder="e.g. 9 Mile Honey Hole" autoFocus />
          </div>
          <div className="wp-field">
            <label>Notes</label>
            <textarea value={notes} onChange={function(e) { setNotes(e.target.value); }}
                      placeholder="e.g. Hit 30lb BFT here last summer" rows={3} />
          </div>
          <div className="wp-coords-display">
            📍 {latlng.lat.toFixed(4)}°N, {Math.abs(latlng.lng).toFixed(4)}°W
          </div>
          <div className="wp-modal-footer">
            <button type="button" className="wp-btn-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="wp-btn-save" disabled={!name.trim()}>Save Waypoint</button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── WaypointsSidebar ──────────────────────────────────────────────────────────

function WaypointsSidebar({ waypoints, onSelect, onDelete, onExport, isOpen, onToggle }) {
  const [exportOpen, setExportOpen] = React.useState(false);
  return (
    <div className={'wp-sidebar' + (isOpen ? ' open' : '')}>
      <div className="wp-sidebar-header" onClick={onToggle}>
        <span className="wp-sidebar-title">
          📍 My Waypoints{waypoints.length > 0 ? ' (' + waypoints.length + ')' : ''}
        </span>
        <div className="wp-sidebar-controls" onClick={function(e) { e.stopPropagation(); }}>
          {waypoints.length > 0 && (
            <div className="wp-export-wrap">
              <button className="wp-export-btn" onClick={function() { setExportOpen(!exportOpen); }}>Export ▾</button>
              {exportOpen && (
                <div className="wp-export-dropdown">
                  {[['gpx','GPX (Garmin)'],['kml','KML (Google Earth)'],['csv','CSV']].map(function(pair) {
                    return (
                      <button key={pair[0]} onClick={function() { setExportOpen(false); onExport(pair[0]); }}>{pair[1]}</button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
          <span className="wp-sidebar-chevron">{isOpen ? '▲' : '▼'}</span>
        </div>
      </div>
      {isOpen && (
        <div className="wp-sidebar-list">
          {waypoints.length === 0 ? (
            <div className="wp-empty">Click anywhere on the map to save a waypoint.</div>
          ) : (
            waypoints.map(function(wp) {
              return (
                <div key={wp.id} className="wp-item" onClick={function() { onSelect(wp); }}>
                  <div className="wp-item-row">
                    <span className="wp-item-name">⭐ {wp.name}</span>
                    <button className="wp-item-delete" onClick={function(e) { e.stopPropagation(); onDelete(wp.id); }}>×</button>
                  </div>
                  <div className="wp-item-coords">{wp.lat.toFixed(3)}°N, {Math.abs(wp.lng).toFixed(3)}°W</div>
                  {wp.notes && <div className="wp-item-notes">{wp.notes}</div>}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

// ── Boats Live: helpers ───────────────────────────────────────────────────────

var BOAT_POLL_MS = 60000; // refresh every 60 s

function fetchBoatPositions() {
  var workerUrl = (window.VESSEL_WORKER_URL || '').trim();
  var url = workerUrl
    ? workerUrl.replace(/\/$/, '') + '/vessels'
    : '/ais_positions.json';
  return fetch(url, { cache: 'no-store' }).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  });
}

function boatSpeedColor(kts) {
  if (kts == null || kts < 0.5) return '#94a3b8'; // gray  – docked/drifting
  if (kts < 3)                   return '#22c55e'; // green – fishing
  if (kts < 8)                   return '#eab308'; // yellow
  if (kts < 14)                  return '#f97316'; // orange
  return '#60a5fa';                                // blue  – transit
}

function boatIconHtml(boat) {
  var age     = Date.now() - new Date(boat.updated_at).getTime();
  var fresh   = age < 10 * 60 * 1000;
  var heading = (boat.heading != null && boat.heading <= 360) ? boat.heading : (boat.cog || 0);
  var color   = boatSpeedColor(boat.sog);
  var label   = boat.name.split(' ').slice(-1)[0];
  return '<div class="boat-wrap' + (fresh ? ' boat-fresh' : '') + '">' +
    '<div class="boat-icon" style="border-color:' + color + '">' +
      '<svg width="18" height="18" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">' +
        '<g transform="rotate(' + heading + ',12,12)">' +
          '<polygon points="12,2 17,20 12,15 7,20" fill="' + color + '" stroke="white" stroke-width="1.2"/>' +
        '</g>' +
      '</svg>' +
    '</div>' +
    '<div class="boat-lbl" style="color:' + color + '">' + label + '</div>' +
  '</div>';
}

function boatPopupHtml(boat) {
  var age    = Math.round((Date.now() - new Date(boat.updated_at).getTime()) / 60000);
  var sog    = boat.sog || 0;
  var status = sog < 0.5 ? '⚓ At dock / drifting'
             : sog < 3   ? '🎣 Fishing'
             : sog < 10  ? '🚢 Underway'
             :              '⚡ Transit speed';
  return '<div class="boat-popup">' +
    '<div class="bp-name">' + boat.name + '</div>' +
    '<div class="bp-status">' + status + '</div>' +
    '<div class="bp-stats">' +
      '<span>' + sog.toFixed(1) + ' kt</span>' +
      '<span>' + Math.round(boat.cog || boat.heading || 0) + '°</span>' +
    '</div>' +
    '<div class="bp-meta">' + (boat.landing || '') + '</div>' +
    '<div class="bp-updated">Updated ' + age + ' min ago</div>' +
  '</div>';
}

function buildBoatsLayer(boats) {
  var group = L.layerGroup();
  boats.forEach(function(boat) {
    if (boat.lat == null || boat.lng == null) return;

    // Trail polyline (drawn first, below marker)
    var trail = boat.trail || [];
    if (trail.length >= 1) {
      var pts = trail.map(function(p) { return [p.lat, p.lng]; });
      pts.push([boat.lat, boat.lng]);
      L.polyline(pts, {
        color: boatSpeedColor(boat.sog), weight: 2, opacity: 0.4, dashArray: '4 6',
      }).addTo(group);
    }

    // Vessel marker
    L.marker([boat.lat, boat.lng], {
      icon: L.divIcon({
        className: 'boat-marker-icon',
        html:      boatIconHtml(boat),
        iconSize:  [46, 52],
        iconAnchor:[23, 26],
      }),
      zIndexOffset: 500,
    }).addTo(group).bindPopup(boatPopupHtml(boat), { className: 'boat-popup-wrap' });
  });
  return group;
}

// ── Boats Live: setup panel ───────────────────────────────────────────────────

function BoatsSetupOverlay() {
  return (
    <div className="boats-setup-overlay">
      <div className="boats-setup-card">
        <div className="boats-setup-icon">🚢</div>
        <h3>Vessel Tracking — Setup Required</h3>
        <p>To show live boat positions, deploy the vessel-tracker Cloudflare Worker and add your AIS API key.</p>
        <ol className="boats-setup-steps">
          <li>Register free at <b>aisstream.io</b> → get API key</li>
          <li>Run: <code>python scripts/discover_mmsi.py</code></li>
          <li>Deploy: <code>cd cloudflare-worker && wrangler deploy vessel-tracker.js</code></li>
          <li>Set <code>window.VESSEL_WORKER_URL</code> in <code>web/index.html</code></li>
        </ol>
      </div>
    </div>
  );
}

// ── Catch overlay ─────────────────────────────────────────────────────────────

var _CATCH_DAYS = 14;

// Named fishing zones → lat/lng; keys are lowercase substrings to match against rawText
var _FISHING_ZONES = [
  { keys: ['coronado island', 'the islands', 'islands area'], lat: 32.42, lng: -117.25 },
  { keys: ['9-mile', '9 mile', 'nine-mile', 'nine mile'],     lat: 32.70, lng: -117.40 },
  { keys: ['43 fathom', '43-fathom'],                         lat: 32.80, lng: -117.60 },
  { keys: ['60-mile', '60 mile', 'sixty mile'],               lat: 32.40, lng: -117.70 },
  { keys: ['302 spot', '302spot'],                            lat: 32.00, lng: -117.70 },
  { keys: ['209 spot', '209spot'],                            lat: 32.30, lng: -117.90 },
  { keys: ['182 spot', '182spot'],                            lat: 32.60, lng: -118.00 },
  { keys: ['tanner bank', 'tanner'],                          lat: 32.70, lng: -119.10 },
  { keys: ['cortes bank', 'cortes'],                          lat: 32.40, lng: -119.10 },
  { keys: ['san clemente island'],                            lat: 32.90, lng: -118.50 },
  { keys: ['catalina island', 'catalina'],                    lat: 33.40, lng: -118.40 },
  { keys: ['hidden bank'],                                    lat: 32.95, lng: -117.50 },
  { keys: ['425 bank', ' 425 '],                              lat: 31.90, lng: -119.50 },
  { keys: ['point loma kelp', 'pt loma kelp', 'loma kelp'],  lat: 32.65, lng: -117.28 },
  { keys: ['ensenada'],                                       lat: 31.87, lng: -116.60 },
  { keys: ['uncle sam bank', 'uncle sam'],                    lat: 32.60, lng: -118.30 },
];

var _CATCH_COLORS = {
  Bluefin:   '#3b82f6',
  Yellowfin: '#f59e0b',
  Yellowtail:'#f97316',
  Dorado:    '#22c55e',
};

function _zoneFromText(text) {
  if (!text) return null;
  var t = text.toLowerCase();
  for (var i = 0; i < _FISHING_ZONES.length; i++) {
    var z = _FISHING_ZONES[i];
    for (var j = 0; j < z.keys.length; j++) {
      if (t.indexOf(z.keys[j]) !== -1) return { lat: z.lat, lng: z.lng };
    }
  }
  return null;
}

function _landingCoords(name) {
  var metas = (window.SD && window.SD.LANDINGS_META) || [];
  for (var i = 0; i < metas.length; i++) {
    if (metas[i].name === name) return { lat: metas[i].lat, lng: metas[i].lng };
  }
  return null;
}

function _dominantSpecies(trip) {
  var best = null, bestN = 0;
  ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'].forEach(function(sp) {
    var n = trip[sp] || 0;
    if (n > bestN) { bestN = n; best = sp; }
  });
  return best;
}

// Deterministic per-trip jitter so toggling doesn't reshuffle markers
function _tripJitter(id, axis) {
  var h = 0, s = id + axis;
  for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffffffff;
  return ((h & 0xffff) / 0xffff - 0.5) * 0.014;
}

function buildCatchLayer(trips) {
  var today  = Date.now();
  var cutoff = new Date(); cutoff.setDate(cutoff.getDate() - _CATCH_DAYS);
  var cutStr = cutoff.toISOString().slice(0, 10);
  var group  = L.layerGroup();

  trips.filter(function(t) {
    return t.date >= cutStr && !t.isPreliminary && (t.region === 'san_diego' || !t.region);
  }).forEach(function(trip) {
    var zoneLoc = _zoneFromText(trip.rawText);
    var isZone  = !!zoneLoc;
    var loc     = zoneLoc || _landingCoords(trip.landing);
    if (!loc) return;

    var tid   = String(trip.id || trip.boat + trip.date);
    var lat   = loc.lat + _tripJitter(tid, 'lat');
    var lng   = loc.lng + _tripJitter(tid, 'lng');
    var ageDays  = (today - new Date(trip.date).getTime()) / 86400000;
    var recency  = Math.max(0.35, 1 - (ageDays / _CATCH_DAYS) * 0.65);
    var tc       = trip.trophyCount || 0;
    var radius   = Math.max(6, Math.min(18, 6 + Math.sqrt(tc) * 2.2));
    var sp       = _dominantSpecies(trip);
    var color    = _CATCH_COLORS[sp] || '#8b5cf6';

    var marker = L.circleMarker([lat, lng], {
      radius:      radius,
      color:       isZone ? color : '#ffffff',
      weight:      2,
      dashArray:   isZone ? null : '4,3',
      fillColor:   color,
      fillOpacity: recency * 0.82,
      opacity:     recency,
    });

    var speciesStr = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'].filter(function(s) {
      return (trip[s] || 0) > 0;
    }).map(function(s) { return trip[s] + ' ' + s; }).join(', ') || 'No trophies';
    var ageStr  = ageDays < 1 ? 'Today' : ageDays < 2 ? 'Yesterday' : Math.floor(ageDays) + ' days ago';
    var locTag  = isZone ? '📍 Zone' : '🚢 Landing (approx)';
    var boatKey = JSON.stringify(trip.boat);

    marker.bindPopup(
      '<div class="catch-popup">' +
        '<div class="catch-popup-boat">' + trip.boat + '</div>' +
        '<div class="catch-popup-meta">' + trip.tripLength + ' &middot; ' + (trip.anglers || '?') + ' anglers</div>' +
        '<div class="catch-popup-species">' + speciesStr + '</div>' +
        '<div class="catch-popup-loc">' + locTag + ' &middot; ' + ageStr + '</div>' +
        '<button class="catch-popup-btn" onclick="window._ttCatchNav(' + boatKey + ')">View boat →</button>' +
      '</div>',
      { className: 'catch-popup-wrap', maxWidth: 240 }
    );

    marker.addTo(group);
  });

  return group;
}

// ── ForecastSlider ────────────────────────────────────────────────────────────

function ForecastSlider({ series, step, onStep, loading }) {
  if (loading && !series) {
    return (
      <div className="forecast-slider-wrap">
        <div className="forecast-slider-loading">⏳ Loading forecast series…</div>
      </div>
    );
  }
  if (!series) return null;

  var maxStep   = series.frames.length - 1;
  var isLowConf = step >= 168;
  var hourStr   = series.hours[step] || '';
  var dt        = new Date(hourStr.length === 13 ? hourStr + ':00:00Z' : hourStr + 'Z');
  var dayLabel  = isNaN(dt) ? '' : dt.toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric', timeZone: 'America/Los_Angeles' });
  var timeLabel = isNaN(dt) ? '' : dt.toLocaleTimeString('en-US', {
    hour: 'numeric', hour12: true, timeZone: 'America/Los_Angeles' });
  var nDays     = Math.ceil((maxStep + 1) / 24);
  var nowStep   = new Date().getUTCHours(); // first 24 steps correspond to today

  return (
    <div className={'forecast-slider-wrap' + (isLowConf ? ' fsl-low-conf' : '')}>
      <div className="forecast-slider-row">
        <span className="fsl-time">
          <span className="fsl-day">{dayLabel}</span>
          <span className="fsl-hr">{timeLabel} PT</span>
        </span>
        {step === nowStep && <span className="fsl-now-badge">Now</span>}
        {isLowConf && <span className="fsl-conf-badge">⚠ Lower confidence</span>}
      </div>
      <input type="range" className="forecast-slider-range" min={0} max={maxStep}
        step={1} value={step} onInput={function(e) { onStep(+e.target.value); }} />
      <div className="fsl-day-ticks">
        {Array.from({ length: nDays }, function(_, i) {
          var d = new Date(); d.setUTCDate(d.getUTCDate() + i); d.setUTCHours(0,0,0,0);
          var label = i === 0 ? 'Today' : d.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', timeZone: 'UTC' });
          return (
            <span key={i} className={'fsl-tick' + (i >= 7 ? ' fsl-tick-dim' : '')}>{label}</span>
          );
        })}
      </div>
    </div>
  );
}

// ── LayerPanel ────────────────────────────────────────────────────────────────
// Grouped toggles: Base (radio, one-at-a-time), Conditions (multi-select), Overlays (multi-select)

function LayerPanel({ baseLayer, condLayers, showTides, showBoats, showCatches, sstMode,
                      onBase, onCond, onTides, onBoats, onCatches, onSstMode }) {
  var bases = [
    { id: 'sst',         icon: '🌡️', label: 'SST' },
    { id: 'chlorophyll', icon: '🌿', label: 'Chlorophyll' },
    { id: 'bathymetry',  icon: '⛰️', label: 'Depth' },
    { id: 'satellite',   icon: '🛰️', label: 'Satellite' },
  ];
  var conds = [
    { id: 'wind',     icon: '💨', label: 'Wind' },
    { id: 'waves',    icon: '🌊', label: 'Swell' },
    { id: 'currents', icon: '🌀', label: 'Currents' },
    { id: 'pressure', icon: '🔵', label: 'Pressure' },
  ];
  return (
    <div className="layer-panel">
      <div className="layer-group">
        <div className="layer-group-label">Base</div>
        <div className="layer-group-row">
          {bases.map(function(b) {
            var isActive = baseLayer === b.id;
            return (
              <button key={b.id} className={'layer-btn' + (isActive ? ' active' : '')}
                onClick={function() { onBase(isActive ? null : b.id); }}>
                <span className="layer-btn-icon">{b.icon}</span>{b.label}
              </button>
            );
          })}
        </div>
        {baseLayer === 'sst' && (
          <div className="layer-sst-subrow">
            {Object.keys(SST_SOURCES).map(function(id) {
              var src = SST_SOURCES[id];
              return (
                <button key={id} className={'layer-sst-btn' + (sstMode === id ? ' active' : '')}
                  onClick={function() { onSstMode(id); }}>
                  {src.label}{src.badge ? <span className="sst-picker-badge">{src.badge}</span> : null}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="layer-group">
        <div className="layer-group-label">Conditions</div>
        <div className="layer-group-row">
          {conds.map(function(c) {
            return (
              <button key={c.id} className={'layer-btn' + (condLayers[c.id] ? ' active' : '')}
                onClick={function() { onCond(c.id, !condLayers[c.id]); }}>
                <span className="layer-btn-icon">{c.icon}</span>{c.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="layer-group">
        <div className="layer-group-label">Overlays</div>
        <div className="layer-group-row">
          <button className={'layer-btn' + (showTides   ? ' active' : '')} onClick={function() { onTides(!showTides); }}>
            <span className="layer-btn-icon">🌙</span>Tides
          </button>
          <button className={'layer-btn' + (showCatches ? ' active' : '')} onClick={function() { onCatches(!showCatches); }}>
            <span className="layer-btn-icon">🎣</span>Catches
          </button>
          <button className={'layer-btn' + (showBoats   ? ' active' : '')} onClick={function() { onBoats(!showBoats); }}>
            <span className="layer-btn-icon">🚢</span>Boats<span className="layer-live-badge">LIVE</span>
          </button>
        </div>
      </div>
    </div>
  );
}

// ── ChartsHeader ──────────────────────────────────────────────────────────────

function SstSourcePicker({ mode, onChange }) {
  return (
    <div className="sst-source-picker">
      <span className="sst-picker-label">SST Source:</span>
      {Object.keys(SST_SOURCES).map(function(id) {
        var src = SST_SOURCES[id];
        return (
          <button key={id}
            className={'sst-picker-btn' + (mode === id ? ' active' : '')}
            onClick={function() { onChange(id); }}>
            {src.label}
            {src.badge && <span className="sst-picker-badge">{src.badge}</span>}
          </button>
        );
      })}
    </div>
  );
}

function ChartsHeader({ baseLayer, condLayers, sstMode }) {
  var sstSrc = SST_SOURCES[sstMode] || SST_SOURCES.mur;
  var descs = {
    sst:         sstSrc.desc + ' Bait concentrates at 1–2°F transitions in the 64–72°F range.',
    chlorophyll: 'Phytoplankton density indicates feeding zones — bait fish gather at the edges of green plumes.',
    bathymetry:  'Underwater structure — banks, ledges, and drop-offs hold fish year-round.',
    satellite:   'True-color MODIS Terra pass. Cloud cover and water clarity visible at a glance.',
    wind:        'Animated wind flow. Green = calm (<8 kt), yellow = moderate, red = rough. Data: Open-Meteo.',
    waves:       'Animated swell field. Particles colored by height (blue=calm, red=rough 3m+). Data: Open-Meteo Marine.',
    currents:    'Animated surface current flow. Particles show direction and speed. Data: HYCOM.',
    pressure:    'Atmospheric pressure isobars (hPa). Tightly-spaced lines = strong winds. Blue = low pressure, red = high pressure. Data: Open-Meteo.',
  };
  var cl = condLayers || {};
  var primary = baseLayer || (cl.wind ? 'wind' : cl.waves ? 'waves' : cl.currents ? 'currents' : cl.pressure ? 'pressure' : null);
  var desc = primary ? (descs[primary] || '') : 'Select a base layer or condition from the panel below.';
  return (
    <div className="charts-header">
      <h1>Ocean Charts</h1>
      <p className="chart-subtitle">Southern California fishing grounds</p>
      <div className="chart-context">
        <span className="chart-name chart-desc">{desc}</span>
      </div>
    </div>
  );
}

// ── ChartLegend ───────────────────────────────────────────────────────────────

function ChartLegend({ type, sstMode }) {
  var legends = {
    sst:         { gradient: 'linear-gradient(to right, #0033CC, #0099FF, #66CCFF, #99FF66, #FFCC00, #FF6600, #CC0000)', low: 'Cool (55°F)', high: 'Warm (75°F)' },
    chlorophyll: { gradient: 'linear-gradient(to right, #2C3E80, #3DA2FF, #6BD5C5, #B8E060, #FFD500, #FF7300, #C72200)', low: 'Clear water', high: 'Rich bait zone' },
    bathymetry:  { gradient: 'linear-gradient(to right, #003366, #0066CC, #66CCFF, #CCEEFF, #e8f4f8)', low: 'Deep (6000 ft)', high: 'Shallow (0 ft)' },
    wind:        { gradient: 'linear-gradient(to right, rgb(255,255,255), rgb(140,180,255), rgb(80,220,100), rgb(255,220,50), rgb(255,130,30), rgb(240,50,50), rgb(160,30,140), rgb(80,30,180))', low: 'Calm (0 kt)', high: 'Storm (60+ kt)' },
    waves:       { gradient: 'linear-gradient(to right, #3b82f6, #22c55e, #a3e635, #eab308, #f97316, #ef4444, #a855f7)', low: 'Calm (0 m)', high: 'Rough (3+ m)' },
    currents:    { gradient: 'linear-gradient(to right, rgb(20,60,140), rgb(100,160,220), rgb(180,230,220), rgb(250,230,150), rgb(255,150,70), rgb(220,40,40))', low: 'Slack (0 kt)', high: 'Strong (2+ kt)' },
    satellite:   null,
    pressure:    { gradient: 'linear-gradient(to right, #3b82f6, #64748b, #dc2626)', low: 'Low pressure', high: 'High pressure' },
    tides:       null,
    boats:       null,
  };
  if (type === 'sst' && sstMode === 'raster') {
    return (
      <div className="chart-legend-bar">
        <span className="legend-label">55°F</span>
        <div className="legend-gradient-bar" style={{ background: 'linear-gradient(to right, #00148b, #0050dc, #14a0dc, #50d278, #a0e63c, #e6e632, #ffb428, #ff5014, #c81414)' }} />
        <span className="legend-label">76°F</span>
        <span className="legend-front-key">
          <span className="legend-front-swatch"></span>Thermal front
        </span>
      </div>
    );
  }
  var config = legends[type];
  if (!config) return null;
  return (
    <div className="chart-legend-bar">
      <span className="legend-label">{config.low}</span>
      <div className="legend-gradient-bar" style={{ background: config.gradient }} />
      <span className="legend-label">{config.high}</span>
    </div>
  );
}

// ── ChartsView ────────────────────────────────────────────────────────────────

function ChartsView({ navigate, settings }) {
  var unitSystem = (settings && settings.unitSystem) || 'imperial';
  const [baseLayer, setBaseLayer]   = React.useState('sst');
  const [condLayers, setCondLayers] = React.useState({ wind: false, waves: false, currents: false, pressure: false });
  const [showTides, setShowTides]   = React.useState(false);
  const [showBoats, setShowBoats]   = React.useState(false);
  const [showCatches, setShowCatches] = React.useState(false);
  const [sheetOpen, setSheetOpen]   = React.useState(false);
  const [sstMode, setSstMode]       = React.useState(function() {
    return localStorage.getItem('tt_sst_mode') || 'raster';
  });
  const [waypoints, setWaypoints]   = React.useState(loadWaypoints);
  const [showModal, setShowModal]   = React.useState(false);
  const [pendingLatLng, setPending] = React.useState(null);
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const [tidesData, setTidesData]   = React.useState(null);
  const [condLoading, setCondLoading] = React.useState(false);
  const [boatPositions, setBoats]   = React.useState([]);
  const [boatsError, setBoatsError] = React.useState(false);
  const [sliderStep, setSliderStep] = React.useState(function() { return new Date().getUTCHours(); });
  const [sliderSeries, setSliderSeries] = React.useState(null);
  const [sliderLoading, setSliderLoading] = React.useState(false);
  const [swellPeriod, setSwellPeriod] = React.useState(null);
  const [sstReadout, setSstReadout] = React.useState(null);
  const [geoNote, setGeoNote]       = React.useState(null);

  const mapRef           = React.useRef(null);
  const mapInstance      = React.useRef(null);
  const basemapLayer     = React.useRef(null);
  const overlayLayer     = React.useRef(null);
  const condGroupRef     = React.useRef(null);
  const boatLayerRef     = React.useRef(null);
  const boatsPollRef     = React.useRef(null);
  const windVelRef       = React.useRef(null);
  const wavesVelRef      = React.useRef(null);
  const currentsVelRef   = React.useRef(null);
  const pressureLayerRef = React.useRef(null);
  const condLayersRef    = React.useRef(condLayers);
  const baseLyrRef       = React.useRef(baseLayer);
  const sstModeRef       = React.useRef(sstMode);
  const waypointMarkers  = React.useRef({});
  const murGridRef       = React.useRef(null);
  const murSSTLayerRef   = React.useRef(null);
  const murFrontLayerRef = React.useRef(null);
  const catchLayerRef    = React.useRef(null);
  const sliderThrottleRef = React.useRef(null);
  // Raw, sampleable grid data for the tap-to-read popup (refs stay current
  // inside the stable map-click closure).
  const windDataRef      = React.useRef(null);
  const wavesDataRef     = React.useRef(null);
  const currentsDataRef  = React.useRef(null);
  const pressureDataRef  = React.useRef(null);
  const swellPeriodRef   = React.useRef(null);
  const unitSystemRef    = React.useRef(unitSystem);
  const userLocMarkerRef = React.useRef(null);

  React.useEffect(function() { condLayersRef.current = condLayers; }, [condLayers]);
  React.useEffect(function() { baseLyrRef.current = baseLayer; }, [baseLayer]);
  React.useEffect(function() { sstModeRef.current = sstMode; }, [sstMode]);
  React.useEffect(function() { unitSystemRef.current = unitSystem; }, [unitSystem]);
  React.useEffect(function() { swellPeriodRef.current = swellPeriod; }, [swellPeriod]);
  React.useEffect(function() {
    if (!geoNote) return;
    var t = setTimeout(function() { setGeoNote(null); }, 4500);
    return function() { clearTimeout(t); };
  }, [geoNote]);

  // Initialize map once
  React.useEffect(function() {
    if (!mapRef.current || mapInstance.current) return;

    mapInstance.current = L.map(mapRef.current, {
      center: [32.5, -119.0], zoom: 7, minZoom: 4, maxZoom: 12,
      maxBounds: [[22.0, -132.0], [42.0, -108.0]],
      maxBoundsViscosity: 0.7,
    });

    addLandingPins(mapInstance.current);
    addBankMarkers(mapInstance.current);

    var recenterControl = L.control({ position: 'topright' });
    recenterControl.onAdd = function() {
      var div = L.DomUtil.create('div', 'leaflet-bar leaflet-control recenter-control');
      div.innerHTML = '<a href="#" title="Recenter on San Diego">📍 Recenter</a>';
      L.DomEvent.on(div, 'click', function(e) {
        L.DomEvent.preventDefault(e);
        mapInstance.current.setView([32.5, -118.5], 7, { animate: true });
      });
      return div;
    };
    recenterControl.addTo(mapInstance.current);

    // Build the tap/location popup HTML: coordinates (or a label) + a readout of
    // every active layer's value at the point + the save-waypoint action.
    function buildPointPopupHtml(lat, lng, label) {
      var latlng = { lat: lat, lng: lng };
      var sys = unitSystemRef.current || 'imperial';
      var rows = '';
      function addRow(icon, lbl, val) {
        if (val == null) return;
        rows += '<div class="popup-metric"><span class="popup-metric-label">' + icon + ' ' + lbl + '</span>'
              + '<span class="popup-metric-val">' + val + '</span></div>';
      }
      if (baseLyrRef.current === 'sst' && sstModeRef.current === 'raster' && murGridRef.current) {
        var sr = _murGridReadout(murGridRef.current, latlng);
        if (sr) addRow('🌡️', 'SST', sr.sst == null ? 'land / cloud' : _fmtTemp(sr.sst, sys));
      }
      var cl = condLayersRef.current || {};
      if (cl.wind && windDataRef.current) {
        var w = _sampleVelGrid(windDataRef.current, latlng);
        if (w) addRow('💨', 'Wind', _fmtSpeed(w.speed, sys) + ' from ' + _compass8(w.fromDir));
      }
      if (cl.waves && wavesDataRef.current) {
        var swv = _sampleVelGrid(wavesDataRef.current, latlng);
        if (swv) addRow('🌊', 'Swell', _fmtSwell(swv.speed, sys) + ' from ' + _compass8(swv.fromDir)
              + (swellPeriodRef.current ? ' · ' + Math.round(swellPeriodRef.current) + 's' : ''));
      }
      if (cl.currents && currentsDataRef.current) {
        var cu = _sampleVelGrid(currentsDataRef.current, latlng);
        if (cu) addRow('🌀', 'Current', _fmtSpeed(cu.speed, sys) + ' → ' + _compass8(cu.toDir));
      }
      if (cl.pressure && pressureDataRef.current) {
        var pv = _samplePressureGrid(pressureDataRef.current, latlng);
        if (pv != null) addRow('🔵', 'Pressure', _fmtPressure(pv, sys));
      }
      var coords = label ? label : (lat.toFixed(4) + '°N,&nbsp;' + Math.abs(lng).toFixed(4) + '°W');
      var metricsHtml = rows ? '<div class="popup-metrics">' + rows + '</div>' : '';
      return '<div class="map-popup">'
        + '<div class="popup-coords">' + coords + '</div>'
        + metricsHtml
        + '<button class="popup-save-waypoint" onclick="window.ttOpenWaypointModal(' + lat + ',' + lng + ')">+ Save as waypoint</button>'
        + '</div>';
    }

    // ── "Locate me" geolocation ───────────────────────────────────────────────
    function placeUserLocation(lat, lng, opts) {
      opts = opts || {};
      var b = _GEO_SUPPORTED_BBOX;
      var inRegion = lat >= b.latMin && lat <= b.latMax && lng >= b.lonMin && lng <= b.lonMax;
      if (!inRegion) { setGeoNote("You're outside the SoCal coverage area"); return; }
      if (userLocMarkerRef.current) {
        userLocMarkerRef.current.setLatLng([lat, lng]);
      } else {
        var icon = L.divIcon({
          className: 'user-loc-marker',
          html: '<div class="user-loc-pulse"></div><div class="user-loc-dot"></div>',
          iconSize: [22, 22], iconAnchor: [11, 11],
        });
        userLocMarkerRef.current = L.marker([lat, lng], { icon: icon, zIndexOffset: 1000, keyboard: false })
          .addTo(mapInstance.current);
        userLocMarkerRef.current.bindPopup(function() {
          var ll = userLocMarkerRef.current.getLatLng();
          return buildPointPopupHtml(ll.lat, ll.lng, '📍 Your location');
        }, { className: 'tt-popup' });
      }
      if (opts.pan && mapInstance.current) {
        mapInstance.current.setView([lat, lng], Math.max(mapInstance.current.getZoom(), 9), { animate: true });
      }
      if (opts.openPopup && userLocMarkerRef.current) userLocMarkerRef.current.openPopup();
    }

    function requestGeolocate(opts) {
      if (!navigator.geolocation) { if (opts && opts.manual) setGeoNote('Location not available on this device'); return; }
      navigator.geolocation.getCurrentPosition(
        function(pos) { placeUserLocation(pos.coords.latitude, pos.coords.longitude, opts); },
        function(err) {
          if (opts && opts.manual) setGeoNote(err && err.code === 1 ? 'Location permission denied' : "Couldn't get your location");
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
      );
    }

    var locateControl = L.control({ position: 'topright' });
    locateControl.onAdd = function() {
      var div = L.DomUtil.create('div', 'leaflet-bar leaflet-control locate-control');
      div.innerHTML = '<a href="#" title="Show my location">🧭 Locate me</a>';
      L.DomEvent.on(div, 'click', function(e) {
        L.DomEvent.preventDefault(e);
        requestGeolocate({ pan: true, openPopup: true, manual: true });
      });
      return div;
    };
    locateControl.addTo(mapInstance.current);

    // Auto-locate on open ONLY if the user already granted permission — no
    // surprise prompt for first-time visitors (they use the button instead).
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: 'geolocation' })
        .then(function(status) { if (status.state === 'granted') requestGeolocate({ pan: true }); })
        .catch(function() {});
    }

    window.ttOpenWaypointModal = function(lat, lng) {
      mapInstance.current.closePopup();
      setPending({ lat: lat, lng: lng });
      setShowModal(true);
    };

    window._ttCatchNav = function(boat) { if (navigate) navigate('boat', { boat: boat }); };

    mapInstance.current.on('click', function(e) {
      L.popup({ className: 'tt-popup' })
        .setLatLng(e.latlng)
        .setContent(buildPointPopupHtml(e.latlng.lat, e.latlng.lng, null))
        .openOn(mapInstance.current);
    });

    return function() {
      delete window.ttOpenWaypointModal;
      delete window._ttCatchNav;
      userLocMarkerRef.current = null;
      if (mapInstance.current) { mapInstance.current.remove(); mapInstance.current = null; }
    };
  }, []);

  // Swap base layer (SST / chlorophyll / bathymetry / satellite)
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var cancelled = false;

    setSliderSeries(null);
    setSliderLoading(false);
    setSliderStep(new Date().getUTCHours());
    setSwellPeriod(null);
    clearTimeout(sliderThrottleRef.current);

    if (basemapLayer.current) { mapInstance.current.removeLayer(basemapLayer.current); }
    basemapLayer.current = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_matter_nolabels/{z}/{x}/{y}{r}.png',
      { attribution: '© CARTO © OpenStreetMap', subdomains: 'abcd', maxZoom: 19 }
    ).addTo(mapInstance.current);

    [murSSTLayerRef, murFrontLayerRef].forEach(function(ref) {
      if (ref.current) { mapInstance.current.removeLayer(ref.current); ref.current = null; }
    });
    murGridRef.current = null;
    setSstReadout(null);

    if (overlayLayer.current) { mapInstance.current.removeLayer(overlayLayer.current); overlayLayer.current = null; }
    if (baseLayer === 'sst' && sstModeRef.current === 'raster') {
      setCondLoading(true);
      _getCachedMURRasterGrid().then(function(grid) {
        setCondLoading(false);
        if (cancelled || !mapInstance.current || baseLyrRef.current !== 'sst' || sstModeRef.current !== 'raster') return;
        murGridRef.current = grid;
        var ovs = _buildMUROverlays(grid);
        ovs.sst.addTo(mapInstance.current); murSSTLayerRef.current = ovs.sst;
        ovs.front.addTo(mapInstance.current); murFrontLayerRef.current = ovs.front;
      }).catch(function() { if (!cancelled) setCondLoading(false); });
    } else if (baseLayer) {
      var overlay = getOverlayLayer(baseLayer, sstModeRef.current);
      if (overlay) { overlay.addTo(mapInstance.current); overlayLayer.current = overlay; }
    }

    return function() { cancelled = true; };
  }, [baseLayer]);

  // Swap SST source (tile ↔ canvas raster) without changing base layer
  React.useEffect(function() {
    if (baseLyrRef.current !== 'sst' || !mapInstance.current) return;
    localStorage.setItem('tt_sst_mode', sstMode);
    var cancelled = false;
    if (overlayLayer.current) { mapInstance.current.removeLayer(overlayLayer.current); overlayLayer.current = null; }
    [murSSTLayerRef, murFrontLayerRef].forEach(function(ref) {
      if (ref.current) { mapInstance.current.removeLayer(ref.current); ref.current = null; }
    });
    murGridRef.current = null;
    setSstReadout(null);
    if (sstMode === 'raster') {
      setCondLoading(true);
      _getCachedMURRasterGrid().then(function(grid) {
        setCondLoading(false);
        if (cancelled || !mapInstance.current || baseLyrRef.current !== 'sst' || sstModeRef.current !== 'raster') return;
        murGridRef.current = grid;
        var ovs = _buildMUROverlays(grid);
        ovs.sst.addTo(mapInstance.current); murSSTLayerRef.current = ovs.sst;
        ovs.front.addTo(mapInstance.current); murFrontLayerRef.current = ovs.front;
      }).catch(function() { if (!cancelled) setCondLoading(false); });
    } else {
      var overlay = getOverlayLayer('sst', sstMode);
      if (overlay) { overlay.addTo(mapInstance.current); overlayLayer.current = overlay; }
    }
    return function() { cancelled = true; };
  }, [sstMode]);

  // SST readout: update on hover when canvas raster is active
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var throttle = 0;
    function onMove(e) {
      var now = Date.now();
      if (now - throttle < 33) return;
      throttle = now;
      if (baseLyrRef.current !== 'sst' || sstModeRef.current !== 'raster' || !murGridRef.current) return;
      setSstReadout(_murGridReadout(murGridRef.current, e.latlng));
    }
    function onLeave() { setSstReadout(null); }
    mapInstance.current.on('mousemove', onMove);
    mapInstance.current.on('mouseout', onLeave);
    return function() {
      if (!mapInstance.current) return;
      mapInstance.current.off('mousemove', onMove);
      mapInstance.current.off('mouseout', onLeave);
    };
  }, []);

  // Wind condition layer
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var cancelled = false;
    if (condLayers.wind) {
      if (typeof L.velocityLayer === 'function') {
        setCondLoading(true);
        getCachedWindGrid().then(function(data) {
          setCondLoading(false);
          if (cancelled || !mapInstance.current || !condLayersRef.current.wind) return;
          var vl = L.velocityLayer({
            displayValues: true,
            displayOptions: { velocityType: 'Wind', position: 'bottomleft', emptyString: 'No wind data', angleConvention: 'bearingCW', speedUnit: 'kt' },
            data: data, maxVelocity: 35, velocityScale: 0.008, particleAge: 60,
            lineWidth: 1.8, particleMultiplier: 0.008, frameRate: 30,
            colorScale: WIND_PARTICLE_COLORS, opacity: 0.95,
          });
          vl.addTo(mapInstance.current);
          windVelRef.current = vl;
          windDataRef.current = data;
          setSliderLoading(true);
          getCachedWindSeries14d().then(function(series) {
            setSliderLoading(false);
            if (cancelled || !mapInstance.current || !condLayersRef.current.wind) return;
            var initStep = new Date().getUTCHours();
            setSliderSeries(Object.assign({ type: 'wind' }, series));
            setSliderStep(initStep);
          }).catch(function() { if (!cancelled) setSliderLoading(false); });
        }).catch(function() { if (!cancelled) setCondLoading(false); });
      }
    } else {
      if (windVelRef.current && mapInstance.current) { mapInstance.current.removeLayer(windVelRef.current); windVelRef.current = null; }
      windDataRef.current = null;
      setSliderSeries(function(prev) { return (prev && prev.type === 'wind') ? null : prev; });
    }
    return function() { cancelled = true; };
  }, [condLayers.wind]);

  // Waves condition layer
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var cancelled = false;
    if (condLayers.waves) {
      if (typeof L.velocityLayer === 'function') {
        setCondLoading(true);
        getCachedSwellGrid().then(function(result) {
          setCondLoading(false);
          if (cancelled || !mapInstance.current || !condLayersRef.current.waves) return;
          var vl = L.velocityLayer({
            displayValues: true,
            displayOptions: { velocityType: 'Swell', position: 'bottomleft', emptyString: 'No swell data', angleConvention: 'bearingCW', speedUnit: 'm' },
            data: result.velocityData, maxVelocity: 3.5, velocityScale: 0.012, particleAge: 90,
            lineWidth: 2.0, particleMultiplier: 0.004, colorScale: WAVE_PARTICLE_COLORS, opacity: 0.92,
          });
          vl.addTo(mapInstance.current);
          wavesVelRef.current = vl;
          wavesDataRef.current = result.velocityData;
          if (result.avgPeriod > 0) setSwellPeriod(result.avgPeriod);
        }).catch(function() { if (!cancelled) setCondLoading(false); });
        setSliderLoading(true);
        getCachedWavesSeries7d().then(function(series) {
          setSliderLoading(false);
          if (cancelled || !mapInstance.current || !condLayersRef.current.waves) return;
          var initStep = new Date().getUTCHours();
          var tagged = Object.assign({ type: 'waves' }, series);
          if (wavesVelRef.current && typeof wavesVelRef.current.setData === 'function') {
            var frame = tagged.frames[initStep] || tagged.frames[0];
            try { wavesVelRef.current.setData(frame); } catch(e) {}
          } else if (typeof L.velocityLayer === 'function') {
            if (condGroupRef.current) { mapInstance.current.removeLayer(condGroupRef.current); condGroupRef.current = null; }
            var frame2 = tagged.frames[initStep] || tagged.frames[0];
            var vl2 = L.velocityLayer({
              displayValues: true,
              displayOptions: { velocityType: 'Swell', position: 'bottomleft', emptyString: 'No swell data', angleConvention: 'bearingCW', speedUnit: 'm' },
              data: frame2, maxVelocity: 3.5, velocityScale: 0.012, particleAge: 90,
              lineWidth: 2.0, particleMultiplier: 0.004, colorScale: WAVE_PARTICLE_COLORS, opacity: 0.92,
            });
            vl2.addTo(mapInstance.current);
            wavesVelRef.current = vl2;
          }
          if (tagged.periods && tagged.periods[initStep] > 0) setSwellPeriod(tagged.periods[initStep]);
          if (!condLayersRef.current.wind) {
            setSliderSeries(tagged);
            setSliderStep(initStep);
          }
        }).catch(function() { if (!cancelled) setSliderLoading(false); });
      } else {
        setCondLoading(true);
        fetchConditionsData('waves').then(function(data) {
          setCondLoading(false);
          if (cancelled || !mapInstance.current) return;
          var layer = buildConditionsLayer('waves', data);
          layer.addTo(mapInstance.current);
          condGroupRef.current = layer;
        }).catch(function() { if (!cancelled) setCondLoading(false); });
      }
    } else {
      if (wavesVelRef.current && mapInstance.current) { mapInstance.current.removeLayer(wavesVelRef.current); wavesVelRef.current = null; }
      if (condGroupRef.current && mapInstance.current) { mapInstance.current.removeLayer(condGroupRef.current); condGroupRef.current = null; }
      wavesDataRef.current = null;
      setSwellPeriod(null);
      setSliderSeries(function(prev) { return (prev && prev.type === 'waves') ? null : prev; });
    }
    return function() { cancelled = true; };
  }, [condLayers.waves]);

  // Currents condition layer
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var cancelled = false;
    if (condLayers.currents) {
      if (typeof L.velocityLayer === 'function') {
        setCondLoading(true);
        getCachedCurrentGrid().then(function(data) {
          setCondLoading(false);
          if (cancelled || !mapInstance.current || !condLayersRef.current.currents) return;
          var vl = L.velocityLayer({
            displayValues: true,
            displayOptions: { velocityType: 'Ocean Current', position: 'bottomleft', emptyString: 'No current data', angleConvention: 'bearingCW', speedUnit: 'kt' },
            data: data, maxVelocity: 1.0, velocityScale: 0.02, particleAge: 120,
            lineWidth: 1.5, particleMultiplier: 0.003, colorScale: CURRENT_PARTICLE_COLORS, opacity: 0.92,
          });
          vl.addTo(mapInstance.current);
          currentsVelRef.current = vl;
          currentsDataRef.current = data;
        }).catch(function() { if (!cancelled) setCondLoading(false); });
      }
    } else {
      if (currentsVelRef.current && mapInstance.current) { mapInstance.current.removeLayer(currentsVelRef.current); currentsVelRef.current = null; }
      currentsDataRef.current = null;
    }
    return function() { cancelled = true; };
  }, [condLayers.currents]);

  // Pressure isobar layer
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var cancelled = false;
    if (condLayers.pressure) {
      setCondLoading(true);
      getCachedPressureGrid().then(function(data) {
        setCondLoading(false);
        if (cancelled || !mapInstance.current || !condLayersRef.current.pressure) return;
        if (pressureLayerRef.current) { mapInstance.current.removeLayer(pressureLayerRef.current); pressureLayerRef.current = null; }
        pressureLayerRef.current = _buildIsobarLayer(data.grid, data.lats, data.lons);
        pressureLayerRef.current.addTo(mapInstance.current);
        pressureDataRef.current = data;
      }).catch(function() { if (!cancelled) setCondLoading(false); });
    } else {
      if (pressureLayerRef.current && mapInstance.current) {
        mapInstance.current.removeLayer(pressureLayerRef.current);
        pressureLayerRef.current = null;
      }
      pressureDataRef.current = null;
    }
    return function() { cancelled = true; };
  }, [condLayers.pressure]);

  // Tides overlay
  React.useEffect(function() {
    if (showTides) {
      setCondLoading(true);
      fetchTidesData().then(function(data) {
        setCondLoading(false);
        setTidesData(data);
      }).catch(function() { setCondLoading(false); });
    } else {
      setTidesData(null);
    }
  }, [showTides]);

  // Boat positions overlay + polling
  React.useEffect(function() {
    if (!mapInstance.current) return;
    if (!showBoats) {
      clearInterval(boatsPollRef.current);
      boatsPollRef.current = null;
      if (boatLayerRef.current) { mapInstance.current.removeLayer(boatLayerRef.current); boatLayerRef.current = null; }
      setBoats([]);
      setBoatsError(false);
      return;
    }
    function refreshBoats() {
      fetchBoatPositions()
        .then(function(data) {
          setBoats(data);
          setBoatsError(false);
          if (!mapInstance.current) return;
          if (boatLayerRef.current) mapInstance.current.removeLayer(boatLayerRef.current);
          boatLayerRef.current = data.length > 0 ? buildBoatsLayer(data) : null;
          if (boatLayerRef.current) boatLayerRef.current.addTo(mapInstance.current);
        })
        .catch(function() { setBoatsError(true); });
    }
    refreshBoats();
    boatsPollRef.current = setInterval(refreshBoats, BOAT_POLL_MS);
    return function() { clearInterval(boatsPollRef.current); };
  }, [showBoats]);

  // Sync waypoint markers to state
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var markers = waypointMarkers.current;
    var ids = new Set(waypoints.map(function(wp) { return wp.id; }));
    Object.keys(markers).forEach(function(id) {
      if (!ids.has(id)) { mapInstance.current.removeLayer(markers[id]); delete markers[id]; }
    });
    waypoints.forEach(function(wp) {
      if (markers[wp.id]) return;
      markers[wp.id] = L.marker([wp.lat, wp.lng], {
        icon: L.divIcon({ className: 'waypoint-marker-icon', html: '<div class="waypoint-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 22] }),
      }).addTo(mapInstance.current)
        .bindPopup('<div class="wp-popup-content"><b>' + wp.name + '</b>' +
          (wp.notes ? '<p class="wp-popup-notes">' + wp.notes + '</p>' : '') +
          '<small>' + wp.lat.toFixed(4) + '°N, ' + Math.abs(wp.lng).toFixed(4) + '°W</small></div>');
    });
  }, [waypoints]);

  // Forecast slider: update velocity layer when step changes
  React.useEffect(function() {
    if (!sliderSeries) return;
    var ref = sliderSeries.type === 'wind' ? windVelRef : wavesVelRef;
    if (!ref.current) return;
    var frame = sliderSeries.frames[sliderStep];
    if (!frame) return;
    try { ref.current.setData(frame); } catch(e) {}
    // Keep the tap-readout data in sync with the forecast hour on display, so
    // dragging the slider also moves the value shown when you tap the map.
    if (sliderSeries.type === 'wind') {
      windDataRef.current = frame;
    } else {
      wavesDataRef.current = frame;
      if (sliderSeries.periods) {
        var p = sliderSeries.periods[sliderStep];
        if (p && p > 0) setSwellPeriod(p);
      }
    }
  }, [sliderStep, sliderSeries]);

  // Catch overlay
  React.useEffect(function() {
    if (!mapInstance.current) return;
    if (catchLayerRef.current) { mapInstance.current.removeLayer(catchLayerRef.current); catchLayerRef.current = null; }
    if (showCatches) {
      var trips = (window.SD && window.SD.TRIPS) || [];
      catchLayerRef.current = buildCatchLayer(trips);
      catchLayerRef.current.addTo(mapInstance.current);
    }
  }, [showCatches]);

  function handleSliderInput(val) {
    setSliderStep(val);
    clearTimeout(sliderThrottleRef.current);
    sliderThrottleRef.current = setTimeout(function() {
      if (!sliderSeries) return;
      var ref = sliderSeries.type === 'wind' ? windVelRef : wavesVelRef;
      if (!ref.current) return;
      var frame = sliderSeries.frames[val];
      if (!frame) return;
      try { ref.current.setData(frame); } catch(e) {}
    }, 80);
  }

  function handleSave(wp) { var n = [wp].concat(waypoints); setWaypoints(n); persistWaypoints(n); }
  function handleDelete(id) { var n = waypoints.filter(function(wp) { return wp.id !== id; }); setWaypoints(n); persistWaypoints(n); }
  function handleSelect(wp) { if (mapInstance.current) mapInstance.current.setView([wp.lat, wp.lng], 9, { animate: true }); }

  function onCond(id, val) {
    setCondLayers(function(prev) { var n = Object.assign({}, prev); n[id] = val; return n; });
  }

  var workerReady   = !!(window.VESSEL_WORKER_URL || '').trim();
  var showBoatSetup = showBoats && !workerReady && boatsError;
  var showSlider    = (condLayers.wind || condLayers.waves) && (sliderSeries || sliderLoading);

  // Summary of active layers, surfaced on the mobile "Map Layers" bar so the
  // current selection is visible without opening the sheet.
  var baseLabels = { sst: 'SST', chlorophyll: 'Chlorophyll', bathymetry: 'Depth', satellite: 'Satellite' };
  var activeLayerLabels = [];
  if (baseLayer) activeLayerLabels.push(baseLabels[baseLayer] || baseLayer);
  if (condLayers.wind)     activeLayerLabels.push('Wind');
  if (condLayers.waves)    activeLayerLabels.push('Swell');
  if (condLayers.currents) activeLayerLabels.push('Currents');
  if (condLayers.pressure) activeLayerLabels.push('Pressure');
  if (showTides)           activeLayerLabels.push('Tides');
  if (showCatches)         activeLayerLabels.push('Catches');
  if (showBoats)           activeLayerLabels.push('Boats');

  return (
    <div className="charts-view">
      <ChartsHeader baseLayer={baseLayer} condLayers={condLayers} sstMode={sstMode} />

      {showSlider && (
        <ForecastSlider series={sliderSeries} step={sliderStep}
          onStep={handleSliderInput} loading={sliderLoading} />
      )}

      <div className="chart-map-container">
        {/* Mobile-only: full-width, always-visible bar above the map that opens
            the layer sheet and shows the current selection. Replaces the
            easy-to-miss corner FAB. */}
        <button className="mobile-layers-bar" aria-label="Open map layers"
          aria-expanded={sheetOpen}
          onClick={function() { setSheetOpen(true); }}>
          <span className="mobile-layers-bar-icon">⊞</span>
          <span className="mobile-layers-bar-text">
            <span className="mobile-layers-bar-title">Map Layers</span>
            <span className="mobile-layers-bar-active">
              {activeLayerLabels.length ? activeLayerLabels.join(' · ') : 'None selected'}
            </span>
          </span>
          <span className="mobile-layers-bar-chevron">›</span>
        </button>

        <div className="chart-map-stage">
          <div ref={mapRef} className="chart-map" />

          <div className="layer-panel-desktop">
            <LayerPanel
              baseLayer={baseLayer} condLayers={condLayers}
              showTides={showTides} showBoats={showBoats} showCatches={showCatches}
              sstMode={sstMode}
              onBase={setBaseLayer}
              onCond={onCond}
              onTides={setShowTides} onBoats={setShowBoats} onCatches={setShowCatches}
              onSstMode={setSstMode}
            />
          </div>

          {condLoading && (
            <div className="cond-loading-overlay">
              <div className="cond-loading-pill">
                {baseLayer === 'sst' && sstMode === 'raster' ? 'Loading SST grid…' : 'Loading conditions…'}
              </div>
            </div>
          )}

          {sstReadout && baseLayer === 'sst' && sstMode === 'raster' && (
            <div className="sst-readout">
              {sstReadout.sst !== null ? (
                <React.Fragment>
                  <span className="sst-readout-temp">{_fmtTemp(sstReadout.sst, unitSystem)}</span>
                  {sstReadout.grad !== null && (
                    <span className="sst-readout-grad">∇{sstReadout.grad.toFixed(2)} °C/km</span>
                  )}
                </React.Fragment>
              ) : (
                <span className="sst-readout-na">No SST (land/cloud)</span>
              )}
            </div>
          )}

          {swellPeriod != null && condLayers.waves && (
            <div className="swell-period-readout">
              ~{Math.round(swellPeriod)}s swell period
            </div>
          )}

          {showBoatSetup && <BoatsSetupOverlay />}
          {showBoats && !boatsError && boatPositions.length > 0 && (
            <div className="boats-count-pill">
              🚢 {boatPositions.length} boat{boatPositions.length !== 1 ? 's' : ''} tracked
            </div>
          )}

          {geoNote && <div className="geo-note-pill">{geoNote}</div>}
        </div>

        <WaypointsSidebar
          waypoints={waypoints} onSelect={handleSelect}
          onDelete={handleDelete} onExport={function(fmt) { exportWaypoints(waypoints, fmt); }}
          isOpen={sidebarOpen} onToggle={function() { setSidebarOpen(!sidebarOpen); }}
        />
      </div>

      {sheetOpen && (
        <div className="layers-sheet-overlay"
          onClick={function(e) { if (e.target === e.currentTarget) setSheetOpen(false); }}>
          <div className="layers-sheet" role="dialog" aria-label="Map layers">
            <div className="layers-sheet-handle" />
            <div className="layers-sheet-title">Map Layers</div>
            <LayerPanel
              baseLayer={baseLayer} condLayers={condLayers}
              showTides={showTides} showBoats={showBoats} showCatches={showCatches}
              sstMode={sstMode}
              onBase={setBaseLayer}
              onCond={onCond}
              onTides={setShowTides} onBoats={setShowBoats} onCatches={setShowCatches}
              onSstMode={setSstMode}
            />
            <button className="layers-sheet-close" onClick={function() { setSheetOpen(false); }}>Done</button>
          </div>
        </div>
      )}

      {showTides && <TidesPanel data={tidesData} loading={condLoading} />}

      {baseLayer && <ChartLegend type={baseLayer} sstMode={sstMode} />}
      {condLayers.wind && <ChartLegend type="wind" />}
      {condLayers.waves && <ChartLegend type="waves" />}
      {condLayers.currents && <ChartLegend type="currents" />}
      {condLayers.pressure && <ChartLegend type="pressure" />}

      <div className="chart-attribution">Data: NASA GIBS · GEBCO · CARTO · Open-Meteo · NOAA · AIS: AISStream.io</div>

      {showModal && pendingLatLng && (
        <WaypointModal latlng={pendingLatLng} onSave={handleSave}
          onClose={function() { setShowModal(false); setPending(null); }} />
      )}
    </div>
  );
}

window.ChartsView = ChartsView;

// ── Idle pre-warm ────────────────────────────────────────────────────────────
// Primes the default Charts data so the first-ever visit paints instantly,
// before the user even taps the Charts tab. Called from app.jsx during idle.
// Safe to run once; fetches are skipped when a fresh cache already exists.
var _chartsPrewarmed = false;

// Prefetch a 3×3 block of map tiles around the default San Diego view
// (center 32.5,-118.5). new Image() warms the browser cache so the tile
// layer reads straight from disk on first map mount.
function _prewarmTiles(z, makeUrl) {
  try {
    var lat = 32.5, lon = -118.5;
    var n = Math.pow(2, z);
    var cx = Math.floor((lon + 180) / 360 * n);
    var latRad = lat * Math.PI / 180;
    var cy = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
    for (var dx = -1; dx <= 1; dx++) {
      for (var dy = -1; dy <= 1; dy++) {
        var x = cx + dx, y = cy + dy;
        if (x < 0 || y < 0 || x >= n || y >= n) continue;
        (new Image()).src = makeUrl(z, x, y);
      }
    }
  } catch (e) {}
}

function _prewarmCharts() {
  if (_chartsPrewarmed) return;
  _chartsPrewarmed = true;

  // 1. CARTO Dark Matter tiles — the actual basemap in use.
  var subs = 'abcd', si = 0;
  _prewarmTiles(7, function(z, x, y) {
    return 'https://' + subs[si++ % subs.length] +
      '.basemaps.cartocdn.com/dark_matter_nolabels/' + z + '/' + x + '/' + y + '.png';
  });

  // 2. SST grid — the default base-layer data (no-op if cache is still fresh).
  try { _getCachedMURRasterGrid().catch(function() {}); } catch (e) {}
}

window.__ttPrewarmCharts = _prewarmCharts;
