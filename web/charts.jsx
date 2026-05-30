// ── Overlay layers (synchronous tile/WMS layers) ──────────────────────────────

function getOverlayLayer(chartType) {
  var yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var yday = yesterday.toISOString().slice(0, 10);

  switch (chartType) {
    case 'sst':
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Aqua_L3_SST_Thermal_4km_Day_Daily/default/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png',
        { opacity: 0.75, attribution: 'NASA GIBS · MODIS Aqua SST', maxNativeZoom: 6 }
      );
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
    return <div className="tides-panel"><div className="tides-loading">Fetching tide data from NOAA...</div></div>;
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

function ChartsHeader({ chartType }) {
  var titles = {
    sst:         { title: 'Sea Surface Temperature',    desc: 'Bait concentrates at temperature breaks — look for 1–2°F transitions in the 64–72°F range.' },
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

function ChartLegend({ type }) {
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

function ChartsView() {
  const [chartType, setChartType]     = React.useState('sst');
  const [waypoints, setWaypoints]     = React.useState(loadWaypoints);
  const [showModal, setShowModal]     = React.useState(false);
  const [pendingLatLng, setPending]   = React.useState(null);
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const [tidesData, setTidesData]     = React.useState(null);
  const [condLoading, setCondLoading] = React.useState(false);
  const [boatPositions, setBoats]     = React.useState([]);
  const [boatsError, setBoatsError]   = React.useState(false);

  const mapRef          = React.useRef(null);
  const mapInstance     = React.useRef(null);
  const basemapLayer    = React.useRef(null);
  const overlayLayer    = React.useRef(null);
  const condGroupRef    = React.useRef(null);
  const boatLayerRef    = React.useRef(null);
  const boatsPollRef    = React.useRef(null);
  const velocityLayerRef = React.useRef(null);
  const chartTypeRef    = React.useRef(chartType);
  const waypointMarkers = React.useRef({});

  React.useEffect(function() { chartTypeRef.current = chartType; }, [chartType]);

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

    // Tile overlay (SST / chloro / bathymetry / satellite)
    if (overlayLayer.current) { mapInstance.current.removeLayer(overlayLayer.current); overlayLayer.current = null; }
    var overlay = getOverlayLayer(chartType);
    if (overlay) { overlay.addTo(mapInstance.current); overlayLayer.current = overlay; }

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

  function handleSave(wp) { var n = [wp].concat(waypoints); setWaypoints(n); persistWaypoints(n); }
  function handleDelete(id) { var n = waypoints.filter(function(wp) { return wp.id !== id; }); setWaypoints(n); persistWaypoints(n); }
  function handleSelect(wp) { if (mapInstance.current) mapInstance.current.setView([wp.lat, wp.lng], 9, { animate: true }); }

  var showMap       = chartType !== 'tides';
  var workerReady   = !!(window.VESSEL_WORKER_URL || '').trim();
  var showBoatSetup = chartType === 'boats' && !workerReady && boatsError;

  return (
    <div className="charts-view">
      <ChartsHeader chartType={chartType} />
      <ChartTypeTabs active={chartType} onChange={setChartType} />

      {showMap && (
        <div className="chart-map-container">
          <div ref={mapRef} className="chart-map" />
          {condLoading && (
            <div className="cond-loading-overlay">
              <div className="cond-loading-pill">Loading conditions…</div>
            </div>
          )}
          {chartType === 'boats' && !boatsError && boatPositions.length > 0 && (
            <div className="boats-count-pill">
              🚢 {boatPositions.length} boat{boatPositions.length !== 1 ? 's' : ''} tracked
            </div>
          )}
          {showBoatSetup && <BoatsSetupOverlay />}
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

      <ChartLegend type={chartType} />
      <div className="chart-attribution">Data: NASA GIBS · GEBCO · CARTO · Open-Meteo · NOAA · AIS: AISStream.io</div>

      {showModal && pendingLatLng && (
        <WaypointModal latlng={pendingLatLng} onSave={handleSave}
          onClose={function() { setShowModal(false); setPending(null); }} />
      )}
    </div>
  );
}

window.ChartsView = ChartsView;
