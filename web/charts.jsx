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
  ];
  return (
    <div className="chart-type-tabs">
      {tabs.map(function(tab) {
        return (
          <button key={tab.id}
            className={'chart-tab' + (active === tab.id ? ' active' : '')}
            onClick={function() { onChange(tab.id); }}>
            <span className="tab-icon">{tab.icon}</span>
            {tab.label}
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
    wind:        { title: 'Wind Conditions',            desc: 'Current wind speed and direction. Green = calm (<8 kt). Yellow = moderate. Red = rough (>28 kt). Data: Open-Meteo.' },
    waves:       { title: 'Wave Height & Direction',    desc: 'Significant wave height in feet — the main factor for trip comfort. Blue = calm (<2 ft). Data: Open-Meteo Marine.' },
    tides:       { title: 'San Diego Tide Schedule',    desc: 'High and low tides for today from NOAA Station 9410230. Fish most actively bite on moving tides.' },
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
    wind:        { gradient: 'linear-gradient(to right, #22c55e, #84cc16, #eab308, #f97316, #ef4444)', low: 'Calm (0 kt)', high: 'Rough (30+ kt)' },
    waves:       { gradient: 'linear-gradient(to right, #3b82f6, #22c55e, #eab308, #f97316, #ef4444)', low: 'Calm (0–2 ft)', high: 'Rough (8+ ft)' },
    satellite:   null,
    tides:       null,
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

  const mapRef          = React.useRef(null);
  const mapInstance     = React.useRef(null);
  const basemapLayer    = React.useRef(null);
  const overlayLayer    = React.useRef(null);
  const condGroupRef    = React.useRef(null);
  const chartTypeRef    = React.useRef(chartType);
  const waypointMarkers = React.useRef({});

  React.useEffect(function() { chartTypeRef.current = chartType; }, [chartType]);

  // Initialize map once
  React.useEffect(function() {
    if (!mapRef.current || mapInstance.current) return;

    mapInstance.current = L.map(mapRef.current, {
      center: [32.5, -118.5], zoom: 7, minZoom: 6, maxZoom: 10,
      maxBounds: [[28, -123], [36, -117.5]],
      maxBoundsViscosity: 1.0,
    });

    addLandingPins(mapInstance.current);
    addBankMarkers(mapInstance.current);

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

    // Clear conditions (wind/wave arrows)
    if (condGroupRef.current) { mapInstance.current.removeLayer(condGroupRef.current); condGroupRef.current = null; }
    setTidesData(null);

    // Async conditions
    if (chartType === 'wind' || chartType === 'waves') {
      setCondLoading(true);
      fetchConditionsData(chartType).then(function(data) {
        setCondLoading(false);
        if (!mapInstance.current) return;
        var layer = buildConditionsLayer(chartType, data);
        layer.addTo(mapInstance.current);
        condGroupRef.current = layer;
      }).catch(function() { setCondLoading(false); });
    } else if (chartType === 'tides') {
      setCondLoading(true);
      fetchTidesData().then(function(data) {
        setCondLoading(false);
        setTidesData(data);
      }).catch(function() { setCondLoading(false); });
    } else {
      setCondLoading(false);
    }
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

  var showMap = chartType !== 'tides';

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
      <div className="chart-attribution">Data: NASA GIBS · GEBCO · CARTO · Open-Meteo · NOAA</div>

      {showModal && pendingLatLng && (
        <WaypointModal latlng={pendingLatLng} onSave={handleSave}
          onClose={function() { setShowModal(false); setPending(null); }} />
      )}
    </div>
  );
}

window.ChartsView = ChartsView;
