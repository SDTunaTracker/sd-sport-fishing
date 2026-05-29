function getOverlayLayer(chartType) {
  // Chlorophyll lags ~1 day; SST/satellite use no-date form (GIBS serves latest available)
  var yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var yday = yesterday.toISOString().slice(0, 10);

  switch (chartType) {
    case 'sst':
      // MODIS Aqua thermal SST, max native zoom 6; no-date = GIBS default (latest available)
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Aqua_L3_SST_Thermal_4km_Day_Daily/default/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png',
        { opacity: 0.75, attribution: 'NASA GIBS · MODIS Aqua SST', maxNativeZoom: 6 }
      );
    case 'chlorophyll':
      // VIIRS NOAA-20 chlorophyll, Level7; data available with ~1-day lag
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
      // MODIS Terra true-color, Level9; no-date = today's pass
      return L.tileLayer(
        'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg',
        { opacity: 1.0, attribution: 'NASA GIBS · MODIS Terra', maxNativeZoom: 9 }
      );
    default:
      return null;
  }
}

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
    var isSD = (landing.region === 'san_diego' || !landing.region);
    if (isSD) {
      L.marker([landing.lat, landing.lng], { icon: icon })
        .addTo(map)
        .bindPopup('<b>' + landing.name + '</b>');
    }
  });
}

function addBankMarkers(map) {
  var banks = [
    { name: '9-Mile Bank',  lat: 32.7,  lng: -117.4 },
    { name: '43 Fathom',    lat: 32.8,  lng: -117.6 },
    { name: '60-Mile Bank', lat: 32.4,  lng: -117.7 },
    { name: '182 Spot',     lat: 32.6,  lng: -118.0 },
    { name: '209 Spot',     lat: 32.3,  lng: -117.9 },
    { name: 'Tanner Bank',  lat: 32.7,  lng: -119.1 },
    { name: 'Cortes Bank',  lat: 32.4,  lng: -119.1 },
    { name: '302 Spot',     lat: 32.0,  lng: -117.7 },
  ];
  banks.forEach(function(b) {
    L.circleMarker([b.lat, b.lng], {
      radius: 5, color: '#fff', weight: 2,
      fillColor: '#1E293B', fillOpacity: 0.95,
    }).addTo(map).bindTooltip(b.name, {
      permanent: true, direction: 'top',
      offset: [0, -6], className: 'bank-label',
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
    filename = 'tuna-tracker-waypoints.gpx';
    mime = 'application/gpx+xml';
  } else if (format === 'kml') {
    content = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n' +
      waypoints.map(function(wp) {
        return '  <Placemark>\n    <name>' + escXml(wp.name) + '</name>\n' +
               '    <description>' + escXml(wp.notes) + '</description>\n' +
               '    <Point><coordinates>' + wp.lng.toFixed(6) + ',' + wp.lat.toFixed(6) + ',0</coordinates></Point>\n  </Placemark>';
      }).join('\n') + '\n</Document>\n</kml>';
    filename = 'tuna-tracker-waypoints.kml';
    mime = 'application/vnd.google-earth.kml+xml';
  } else {
    content = 'Name,Latitude,Longitude,Notes,Created\n' +
      waypoints.map(function(wp) {
        return '"' + wp.name.replace(/"/g,'""') + '",' +
               wp.lat.toFixed(6) + ',' + wp.lng.toFixed(6) + ',' +
               '"' + (wp.notes||'').replace(/"/g,'""') + '",' +
               '"' + (wp.created_at||'') + '"';
      }).join('\n');
    filename = 'tuna-tracker-waypoints.csv';
    mime = 'text/csv';
  }
  var blob = new Blob([content], { type: mime });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// ── WaypointModal ─────────────────────────────────────────────────────────────

function WaypointModal({ latlng, onSave, onClose }) {
  const [name, setName]   = React.useState('');
  const [notes, setNotes] = React.useState('');

  function handleSave(e) {
    e.preventDefault();
    if (!name.trim()) return;
    onSave({
      id: 'wp_' + Date.now(),
      name: name.trim(),
      notes: notes.trim(),
      lat: latlng.lat,
      lng: latlng.lng,
      created_at: new Date().toISOString(),
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
            <input
              value={name}
              onChange={function(e) { setName(e.target.value); }}
              placeholder="e.g. 9 Mile Honey Hole"
              autoFocus
            />
          </div>
          <div className="wp-field">
            <label>Notes</label>
            <textarea
              value={notes}
              onChange={function(e) { setNotes(e.target.value); }}
              placeholder="e.g. Hit 30lb BFT here last summer"
              rows={3}
            />
          </div>
          <div className="wp-coords-display">
            📍 {latlng.lat.toFixed(4)}°N, {Math.abs(latlng.lng).toFixed(4)}°W
          </div>
          <div className="wp-modal-footer">
            <button type="button" className="wp-btn-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="wp-btn-save" disabled={!name.trim()}>
              Save Waypoint
            </button>
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
              <button className="wp-export-btn" onClick={function() { setExportOpen(!exportOpen); }}>
                Export ▾
              </button>
              {exportOpen && (
                <div className="wp-export-dropdown">
                  {[['gpx','GPX (Garmin)'],['kml','KML (Google Earth)'],['csv','CSV']].map(function(pair) {
                    return (
                      <button key={pair[0]} onClick={function() { setExportOpen(false); onExport(pair[0]); }}>
                        {pair[1]}
                      </button>
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
                    <button
                      className="wp-item-delete"
                      onClick={function(e) { e.stopPropagation(); onDelete(wp.id); }}
                    >×</button>
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
  ];
  return (
    <div className="chart-type-tabs">
      {tabs.map(function(tab) {
        return (
          <button
            key={tab.id}
            className={'chart-tab' + (active === tab.id ? ' active' : '')}
            onClick={function() { onChange(tab.id); }}
          >
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
    sst:         { title: 'Sea Surface Temperature',   desc: 'Bait concentrates at temperature breaks — look for 1–2°F transitions in the 64–72°F range.' },
    chlorophyll: { title: 'Chlorophyll Concentration', desc: 'Phytoplankton density indicates feeding zones — bait fish gather at the edges of green plumes.' },
    bathymetry:  { title: 'Bathymetry (Ocean Depth)',  desc: 'Underwater structure — banks, ledges, and drop-offs hold fish year-round.' },
    satellite:   { title: 'Satellite Imagery',         desc: 'True-color MODIS Terra pass. Cloud cover and water clarity visible at a glance.' },
  };
  var current = titles[chartType] || titles.sst;
  return (
    <div className="charts-header">
      <h1>Ocean Charts</h1>
      <p className="chart-subtitle">Southern California fishing grounds</p>
      <div className="chart-context">
        <span className="chart-name">{current.title}</span>
        <span className="chart-desc">{current.desc}</span>
      </div>
    </div>
  );
}

// ── ChartLegend ───────────────────────────────────────────────────────────────

function ChartLegend({ type }) {
  var legends = {
    sst: {
      gradient: 'linear-gradient(to right, #0033CC, #0099FF, #66CCFF, #99FF66, #FFCC00, #FF6600, #CC0000)',
      low: 'Cool (55°F)', high: 'Warm (75°F)',
    },
    chlorophyll: {
      gradient: 'linear-gradient(to right, #2C3E80, #3DA2FF, #6BD5C5, #B8E060, #FFD500, #FF7300, #C72200)',
      low: 'Clear water', high: 'Rich bait zone',
    },
    bathymetry: {
      gradient: 'linear-gradient(to right, #003366, #0066CC, #66CCFF, #CCEEFF, #e8f4f8)',
      low: 'Deep (6000 ft)', high: 'Shallow (0 ft)',
    },
    satellite: null,
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
  const [chartType, setChartType]       = React.useState('sst');
  const [waypoints, setWaypoints]       = React.useState(loadWaypoints);
  const [showModal, setShowModal]       = React.useState(false);
  const [pendingLatLng, setPending]     = React.useState(null);
  const [sidebarOpen, setSidebarOpen]   = React.useState(true);
  const mapRef          = React.useRef(null);
  const mapInstance     = React.useRef(null);
  const basemapLayer    = React.useRef(null);
  const overlayLayer    = React.useRef(null);
  const chartTypeRef    = React.useRef(chartType);
  const waypointMarkers = React.useRef({});

  React.useEffect(function() { chartTypeRef.current = chartType; }, [chartType]);

  // Initialize map once
  React.useEffect(function() {
    if (!mapRef.current || mapInstance.current) return;

    mapInstance.current = L.map(mapRef.current, {
      center: [32.5, -118.5], zoom: 7, minZoom: 6, maxZoom: 10,
      maxBounds: [[31, -121], [35, -116]],
      maxBoundsViscosity: 0.8,
    });

    addLandingPins(mapInstance.current);
    addBankMarkers(mapInstance.current);

    // Expose modal opener to Leaflet popup HTML buttons
    window.ttOpenWaypointModal = function(lat, lng) {
      mapInstance.current.closePopup();
      setPending({ lat: lat, lng: lng });
      setShowModal(true);
    };

    mapInstance.current.on('click', function(e) {
      var lat = e.latlng.lat;
      var lng = e.latlng.lng;
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

  // Swap basemap + overlay whenever chartType changes
  React.useEffect(function() {
    if (!mapInstance.current) return;

    if (basemapLayer.current) { mapInstance.current.removeLayer(basemapLayer.current); }
    var cartoUrl = (chartType === 'satellite')
      ? 'https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png'
      : 'https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png';
    basemapLayer.current = L.tileLayer(cartoUrl, {
      attribution: '© CARTO © OpenStreetMap', subdomains: 'abcd', maxZoom: 19,
    }).addTo(mapInstance.current);

    if (overlayLayer.current) { mapInstance.current.removeLayer(overlayLayer.current); overlayLayer.current = null; }
    var overlay = getOverlayLayer(chartType);
    if (overlay) { overlay.addTo(mapInstance.current); overlayLayer.current = overlay; }
  }, [chartType]);

  // Sync waypoint markers to React state
  React.useEffect(function() {
    if (!mapInstance.current) return;
    var markers = waypointMarkers.current;
    var ids = new Set(waypoints.map(function(wp) { return wp.id; }));

    Object.keys(markers).forEach(function(id) {
      if (!ids.has(id)) { mapInstance.current.removeLayer(markers[id]); delete markers[id]; }
    });

    waypoints.forEach(function(wp) {
      if (markers[wp.id]) return;
      var icon = L.divIcon({
        className: 'waypoint-marker-icon',
        html: '<div class="waypoint-pin"></div>',
        iconSize: [22, 22],
        iconAnchor: [11, 22],
      });
      markers[wp.id] = L.marker([wp.lat, wp.lng], { icon: icon })
        .addTo(mapInstance.current)
        .bindPopup(
          '<div class="wp-popup-content"><b>' + wp.name + '</b>' +
          (wp.notes ? '<p class="wp-popup-notes">' + wp.notes + '</p>' : '') +
          '<small>' + wp.lat.toFixed(4) + '°N, ' + Math.abs(wp.lng).toFixed(4) + '°W</small></div>'
        );
    });
  }, [waypoints]);

  function handleSave(wp) {
    var next = [wp].concat(waypoints);
    setWaypoints(next);
    persistWaypoints(next);
  }

  function handleDelete(id) {
    var next = waypoints.filter(function(wp) { return wp.id !== id; });
    setWaypoints(next);
    persistWaypoints(next);
  }

  function handleSelect(wp) {
    if (mapInstance.current) mapInstance.current.setView([wp.lat, wp.lng], 9, { animate: true });
  }

  return (
    <div className="charts-view">
      <ChartsHeader chartType={chartType} />
      <ChartTypeTabs active={chartType} onChange={setChartType} />
      <div className="chart-map-container">
        <div ref={mapRef} className="chart-map" />
        <WaypointsSidebar
          waypoints={waypoints}
          onSelect={handleSelect}
          onDelete={handleDelete}
          onExport={function(fmt) { exportWaypoints(waypoints, fmt); }}
          isOpen={sidebarOpen}
          onToggle={function() { setSidebarOpen(!sidebarOpen); }}
        />
      </div>
      <ChartLegend type={chartType} />
      <div className="chart-attribution">Data: NASA GIBS · GEBCO · CARTO · OpenStreetMap</div>
      {showModal && pendingLatLng && (
        <WaypointModal
          latlng={pendingLatLng}
          onSave={handleSave}
          onClose={function() { setShowModal(false); setPending(null); }}
        />
      )}
    </div>
  );
}

window.ChartsView = ChartsView;
