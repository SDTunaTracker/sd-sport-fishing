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

// ── ChartTypeTabs ─────────────────────────────────────────────────────────────

function ChartTypeTabs({ active, onChange }) {
  var tabs = [
    { id: 'sst',         label: 'Sea Surface Temp', icon: '🌡️' },
    { id: 'chlorophyll', label: 'Chlorophyll',      icon: '🌿' },
    { id: 'bathymetry',  label: 'Depth',            icon: '⛰️' },
    { id: 'satellite',   label: 'Satellite',        icon: '🛰️' },
    { id: 'wind',        label: 'Wind',             icon: '💨' },
    { id: 'waves',       label: 'Waves',            icon: '🌊' },
    { id: 'tides',       label: 'Tides',            icon: '🌙' },
    { id: 'currents',    label: 'Currents',         icon: '🌀' },
    { id: 'boats',       label: 'Boats Live',       icon: '🚢', badge: 'LIVE' },
  ];
  return (
    <div className="chart-type-tabs">
      {tabs.map(function(tab) {
        return (
          <button key={tab.id}
            className={'chart-tab' + (active === tab.id ? ' active' : '') + (tab.badge ? ' chart-tab-live' : '')}
            onClick={function() { onChange(tab.id); }}>
            <span className="tab-icon">{tab.icon}</span>
            {tab.label}
            {tab.badge && <span className="tab-live-badge">{tab.badge}</span>}
          </button>
        );
      })}
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

function ChartsHeader({ chartType, sstMode, sstReadout }) {
  var sstSrc = SST_SOURCES[sstMode] || SST_SOURCES.mur;
  var titles = {
    sst:         { title: 'Sea Surface Temperature',    desc: sstSrc.desc + ' Bait concentrates at 1–2°F transitions in the 64–72°F range.' },
    chlorophyll: { title: 'Chlorophyll Concentration',  desc: 'Phytoplankton density indicates feeding zones — bait fish gather at the edges of green plumes.' },
    bathymetry:  { title: 'Bathymetry (Ocean Depth)',   desc: 'Underwater structure — banks, ledges, and drop-offs hold fish year-round.' },
    satellite:   { title: 'Satellite Imagery',          desc: 'True-color MODIS Terra pass. Cloud cover and water clarity visible at a glance.' },
    wind:        { title: 'Wind Conditions',            desc: 'Animated wind particle flow — Windy-style. Green = calm (<8 kt), yellow = moderate, red = rough (>28 kt). Data: Open-Meteo.' },
    waves:       { title: 'Wave Height & Direction',    desc: 'Significant wave height in feet — the main factor for trip comfort. Blue = calm (<2 ft). Data: Open-Meteo Marine.' },
    tides:       { title: 'San Diego Tide Schedule',    desc: 'High and low tides for today from NOAA Station 9410230. Fish most actively bite on moving tides.' },
    currents:    { title: 'Ocean Surface Currents',     desc: 'Animated surface current flow. Particles show direction and speed. Slack (blue) → Strong (red, 2+ kt). Currents determine where bait concentrates.' },
    boats:       { title: 'Boats Live — Real-Time Positions', desc: 'Live AIS vessel positions for tracked SD sportfishing boats. Green = fishing slow. Blue = transit speed. Trail = last 60 min.' },
  };
  var c = titles[chartType] || titles.sst;
  return (
    <div className="charts-header">
      <h1>Ocean Charts</h1>
      <p className="chart-subtitle">Southern California fishing grounds</p>
      <div className="chart-context">
        <span className="chart-name">{c.title}</span>
        <span className="chart-desc">{c.desc}</span>
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
    waves:       { gradient: 'linear-gradient(to right, #3b82f6, #22c55e, #eab308, #f97316, #ef4444)', low: 'Calm (0–2 ft)', high: 'Rough (8+ ft)' },
    currents:    { gradient: 'linear-gradient(to right, rgb(20,60,140), rgb(100,160,220), rgb(180,230,220), rgb(250,230,150), rgb(255,150,70), rgb(220,40,40))', low: 'Slack (0 kt)', high: 'Strong (2+ kt)' },
    satellite:   null,
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

function ChartsView({ navigate }) {
  const [chartType, setChartType]     = React.useState('sst');
  const [sstMode, setSstMode]         = React.useState(function() {
    return localStorage.getItem('tt_sst_mode') || 'mur';
  });
  const [waypoints, setWaypoints]     = React.useState(loadWaypoints);
  const [showModal, setShowModal]     = React.useState(false);
  const [pendingLatLng, setPending]   = React.useState(null);
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const [tidesData, setTidesData]     = React.useState(null);
  const [condLoading, setCondLoading] = React.useState(false);
  const [boatPositions, setBoats]     = React.useState([]);
  const [boatsError, setBoatsError]   = React.useState(false);
  const [showCatches, setShowCatches] = React.useState(false);

  const mapRef          = React.useRef(null);
  const mapInstance     = React.useRef(null);
  const basemapLayer    = React.useRef(null);
  const overlayLayer    = React.useRef(null);
  const condGroupRef    = React.useRef(null);
  const boatLayerRef    = React.useRef(null);
  const boatsPollRef    = React.useRef(null);
  const velocityLayerRef = React.useRef(null);
  const chartTypeRef    = React.useRef(chartType);
  const sstModeRef      = React.useRef(sstMode);
  const waypointMarkers = React.useRef({});
  // MUR raster refs — canvas-based SST + thermal-front overlays
  const murGridRef       = React.useRef(null);
  const murSSTLayerRef   = React.useRef(null);
  const murFrontLayerRef = React.useRef(null);
  const catchLayerRef    = React.useRef(null);
  const [sstReadout, setSstReadout] = React.useState(null); // {sst,grad}|null

  React.useEffect(function() { chartTypeRef.current = chartType; }, [chartType]);
  React.useEffect(function() { sstModeRef.current = sstMode; }, [sstMode]);

  // Initialize map once
  React.useEffect(function() {
    if (!mapRef.current || mapInstance.current) return;

    mapInstance.current = L.map(mapRef.current, {
      center: [32.5, -118.5], zoom: 7, minZoom: 4, maxZoom: 12,
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

    window.ttOpenWaypointModal = function(lat, lng) {
      mapInstance.current.closePopup();
      setPending({ lat: lat, lng: lng });
      setShowModal(true);
    };

    window._ttCatchNav = function(boat) { if (navigate) navigate('boat', { boat: boat }); };

    mapInstance.current.on('click', function(e) {
      var lat = e.latlng.lat, lng = e.latlng.lng;
      L.popup({ className: 'tt-popup' })
        .setLatLng(e.latlng)
        .setContent(
          '<div class="map-popup">' +
            '<div class="popup-coords">' + lat.toFixed(4) + '°N,&nbsp;' + Math.abs(lng).toFixed(4) + '°W</div>' +
            '<button class="popup-save-waypoint" onclick="window.ttOpenWaypointModal(' + lat + ',' + lng + ')">+ Save as waypoint</button>' +
          '</div>'
        )
        .openOn(mapInstance.current);
    });

    return function() {
      delete window.ttOpenWaypointModal;
      delete window._ttCatchNav;
      if (mapInstance.current) { mapInstance.current.remove(); mapInstance.current = null; }
    };
  }, []);

  // Swap layers whenever chartType changes
  React.useEffect(function() {
    if (!mapInstance.current) return;

    // Basemap
    if (basemapLayer.current) { mapInstance.current.removeLayer(basemapLayer.current); }
    var cartoUrl = (chartType === 'satellite')
      ? 'https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png'
      : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png';
    basemapLayer.current = L.tileLayer(cartoUrl, {
      attribution: '© CARTO © OpenStreetMap', subdomains: 'abcd', maxZoom: 19,
    }).addTo(mapInstance.current);

    // Clear MUR canvas layers whenever tab switches
    [murSSTLayerRef, murFrontLayerRef].forEach(function(ref) {
      if (ref.current) { mapInstance.current.removeLayer(ref.current); ref.current = null; }
    });
    murGridRef.current = null;
    setSstReadout(null);

    // Tile overlay (SST / chloro / bathymetry / satellite)
    if (overlayLayer.current) { mapInstance.current.removeLayer(overlayLayer.current); overlayLayer.current = null; }
    if (chartType === 'sst' && sstModeRef.current === 'raster') {
      // canvas raster — handled below (same logic as sstMode effect)
      setCondLoading(true);
      _getCachedMURRasterGrid().then(function(grid) {
        setCondLoading(false);
        if (!mapInstance.current || chartTypeRef.current !== 'sst' || sstModeRef.current !== 'raster') return;
        murGridRef.current = grid;
        var ovs = _buildMUROverlays(grid);
        ovs.sst.addTo(mapInstance.current); murSSTLayerRef.current = ovs.sst;
        ovs.front.addTo(mapInstance.current); murFrontLayerRef.current = ovs.front;
      }).catch(function() { setCondLoading(false); });
    } else {
      var overlay = getOverlayLayer(chartType, sstModeRef.current);
      if (overlay) { overlay.addTo(mapInstance.current); overlayLayer.current = overlay; }
    }

    // Clear conditions (wind/wave arrows + velocity particles)
    if (condGroupRef.current) { mapInstance.current.removeLayer(condGroupRef.current); condGroupRef.current = null; }
    if (velocityLayerRef.current) { mapInstance.current.removeLayer(velocityLayerRef.current); velocityLayerRef.current = null; }
    setTidesData(null);

    // Async conditions
    if (chartType === 'wind') {
      setCondLoading(true);
      if (typeof L.velocityLayer === 'function') {
        getCachedWindGrid().then(function(data) {
          setCondLoading(false);
          if (!mapInstance.current || chartTypeRef.current !== 'wind') return;
          var vl = L.velocityLayer({
            displayValues: true,
            displayOptions: {
              velocityType: 'Wind',
              position: 'bottomleft',
              emptyString: 'No wind data',
              angleConvention: 'bearingCW',
              speedUnit: 'kt',
            },
            data: data,
            maxVelocity: 35,
            velocityScale: 0.008,
            particleAge: 60,
            lineWidth: 1.8,
            particleMultiplier: 0.008,
            frameRate: 30,
            colorScale: WIND_PARTICLE_COLORS,
            opacity: 0.95,
          });
          vl.addTo(mapInstance.current);
          velocityLayerRef.current = vl;
        }).catch(function() { setCondLoading(false); });
      } else {
        fetchConditionsData('wind').then(function(data) {
          setCondLoading(false);
          if (!mapInstance.current) return;
          var layer = buildConditionsLayer('wind', data);
          layer.addTo(mapInstance.current);
          condGroupRef.current = layer;
        }).catch(function() { setCondLoading(false); });
      }
    } else if (chartType === 'waves') {
      setCondLoading(true);
      fetchConditionsData('waves').then(function(data) {
        setCondLoading(false);
        if (!mapInstance.current) return;
        var layer = buildConditionsLayer('waves', data);
        layer.addTo(mapInstance.current);
        condGroupRef.current = layer;
      }).catch(function() { setCondLoading(false); });
    } else if (chartType === 'currents') {
      setCondLoading(true);
      if (typeof L.velocityLayer === 'function') {
        getCachedCurrentGrid().then(function(data) {
          setCondLoading(false);
          if (!mapInstance.current || chartTypeRef.current !== 'currents') return;
          var vl = L.velocityLayer({
            displayValues: true,
            displayOptions: {
              velocityType: 'Ocean Current',
              position: 'bottomleft',
              emptyString: 'No current data',
              angleConvention: 'bearingCW',
              speedUnit: 'kt',
            },
            data: data,
            maxVelocity: 1.0,
            velocityScale: 0.02,
            particleAge: 120,
            lineWidth: 1.5,
            particleMultiplier: 0.003,
            colorScale: CURRENT_PARTICLE_COLORS,
            opacity: 0.92,
          });
          vl.addTo(mapInstance.current);
          velocityLayerRef.current = vl;
        }).catch(function() { setCondLoading(false); });
      } else {
        setCondLoading(false);
      }
    } else if (chartType === 'tides') {
      setCondLoading(true);
      fetchTidesData().then(function(data) {
        setCondLoading(false);
        setTidesData(data);
      }).catch(function() { setCondLoading(false); });
    } else {
      setCondLoading(false);
    }

    // Clear boat layer + poll when leaving boats tab
    if (chartType !== 'boats') {
      clearInterval(boatsPollRef.current);
      boatsPollRef.current = null;
      if (boatLayerRef.current) {
        mapInstance.current.removeLayer(boatLayerRef.current);
        boatLayerRef.current = null;
      }
      setBoats([]);
      setBoatsError(false);
    }
  }, [chartType]);

  // Swap SST layer when user changes source (tile ↔ canvas raster)
  React.useEffect(function() {
    if (chartTypeRef.current !== 'sst' || !mapInstance.current) return;
    localStorage.setItem('tt_sst_mode', sstMode);
    // Clear both tile overlay and MUR canvas layers
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
        if (!mapInstance.current || chartTypeRef.current !== 'sst' || sstModeRef.current !== 'raster') return;
        murGridRef.current = grid;
        var ovs = _buildMUROverlays(grid);
        ovs.sst.addTo(mapInstance.current); murSSTLayerRef.current = ovs.sst;
        ovs.front.addTo(mapInstance.current); murFrontLayerRef.current = ovs.front;
      }).catch(function() { setCondLoading(false); });
    } else {
      var overlay = getOverlayLayer('sst', sstMode);
      if (overlay) { overlay.addTo(mapInstance.current); overlayLayer.current = overlay; }
    }
  }, [sstMode]);

  // SST readout: update on hover when canvas raster is active
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var throttle = 0;
    function onMove(e) {
      var now = Date.now();
      if (now - throttle < 33) return; // ~30 fps
      throttle = now;
      if (chartTypeRef.current !== 'sst' || sstModeRef.current !== 'raster' || !murGridRef.current) return;
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

  // Boat polling effect
  React.useEffect(function() {
    if (chartType !== 'boats' || !mapInstance.current) return;

    function refreshBoats() {
      fetchBoatPositions()
        .then(function(data) {
          setBoats(data);
          setBoatsError(false);
          if (!mapInstance.current) return;
          if (boatLayerRef.current) mapInstance.current.removeLayer(boatLayerRef.current);
          if (data.length > 0) {
            boatLayerRef.current = buildBoatsLayer(data);
            boatLayerRef.current.addTo(mapInstance.current);
          } else {
            boatLayerRef.current = null;
          }
        })
        .catch(function() {
          setBoatsError(true);
        });
    }

    refreshBoats();
    boatsPollRef.current = setInterval(refreshBoats, BOAT_POLL_MS);
    return function() { clearInterval(boatsPollRef.current); };
  }, [chartType]);

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

  // Catch overlay: add/remove when toggled; persists across tab changes
  React.useEffect(function() {
    if (!mapInstance.current) return;
    if (catchLayerRef.current) { mapInstance.current.removeLayer(catchLayerRef.current); catchLayerRef.current = null; }
    if (showCatches) {
      var trips = (window.SD && window.SD.TRIPS) || [];
      catchLayerRef.current = buildCatchLayer(trips);
      catchLayerRef.current.addTo(mapInstance.current);
    }
  }, [showCatches]);

  function handleSave(wp) { var n = [wp].concat(waypoints); setWaypoints(n); persistWaypoints(n); }
  function handleDelete(id) { var n = waypoints.filter(function(wp) { return wp.id !== id; }); setWaypoints(n); persistWaypoints(n); }
  function handleSelect(wp) { if (mapInstance.current) mapInstance.current.setView([wp.lat, wp.lng], 9, { animate: true }); }

  var showMap       = chartType !== 'tides';
  var workerReady   = !!(window.VESSEL_WORKER_URL || '').trim();
  var showBoatSetup = chartType === 'boats' && !workerReady && boatsError;

  return (
    <div className="charts-view">
      <ChartsHeader chartType={chartType} sstMode={sstMode} sstReadout={sstReadout} />
      <ChartTypeTabs active={chartType} onChange={setChartType} />
      {chartType === 'sst' && (
        <SstSourcePicker mode={sstMode} onChange={setSstMode} />
      )}

      {showMap && (
        <div className="chart-map-container">
          <div ref={mapRef} className="chart-map" />
          {condLoading && (
            <div className="cond-loading-overlay">
              <div className="cond-loading-pill">
                {chartType === 'sst' && sstMode === 'raster' ? 'Loading SST grid…' : 'Loading conditions…'}
              </div>
            </div>
          )}
          <button
            className={'catch-toggle-pill' + (showCatches ? ' active' : '')}
            onClick={function() { setShowCatches(!showCatches); }}
          >
            🎣 {showCatches ? 'Catches on' : 'Catches'}
          </button>
          {chartType === 'boats' && !boatsError && boatPositions.length > 0 && (
            <div className="boats-count-pill">
              🚢 {boatPositions.length} boat{boatPositions.length !== 1 ? 's' : ''} tracked
            </div>
          )}
          {showBoatSetup && <BoatsSetupOverlay />}
          {sstReadout && chartType === 'sst' && sstMode === 'raster' && (
            <div className="sst-readout">
              {sstReadout.sst !== null ? (
                <React.Fragment>
                  <span className="sst-readout-temp">{sstReadout.sst.toFixed(1)}°F</span>
                  {sstReadout.grad !== null && (
                    <span className="sst-readout-grad">∇{sstReadout.grad.toFixed(2)} °C/km</span>
                  )}
                </React.Fragment>
              ) : (
                <span className="sst-readout-na">No SST (land/cloud)</span>
              )}
            </div>
          )}
          <WaypointsSidebar
            waypoints={waypoints} onSelect={handleSelect}
            onDelete={handleDelete} onExport={function(fmt) { exportWaypoints(waypoints, fmt); }}
            isOpen={sidebarOpen} onToggle={function() { setSidebarOpen(!sidebarOpen); }}
          />
        </div>
      )}

      {chartType === 'tides' && (
        <TidesPanel data={tidesData} loading={condLoading} />
      )}

      <ChartLegend type={chartType} sstMode={sstMode} />
      <div className="chart-attribution">Data: NASA GIBS · GEBCO · CARTO · Open-Meteo · NOAA · AIS: AISStream.io</div>

      {showModal && pendingLatLng && (
        <WaypointModal latlng={pendingLatLng} onSave={handleSave}
          onClose={function() { setShowModal(false); setPending(null); }} />
      )}
    </div>
  );
}

window.ChartsView = ChartsView;
