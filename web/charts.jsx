function getOverlayLayer(chartType) {
  // Chlorophyll data lags ~1 day; SST/satellite use no-date form (GIBS serves latest available)
  var yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var yday = yesterday.toISOString().slice(0, 10);

  switch (chartType) {
    case 'sst':
      // MODIS Aqua thermal SST, max native zoom 6; no-date URL = GIBS default (latest available)
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
        layers: 'GEBCO_LATEST',
        format: 'image/png',
        transparent: true,
        opacity: 0.65,
        attribution: '© GEBCO 2024',
      });
    case 'satellite':
      // MODIS Terra true-color, Level9; no-date URL = today's pass
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
  landings.forEach(function(landing) {
    if (!landing || !landing.lat || !landing.lng) return;
    var isSD = (landing.region === 'san_diego' || !landing.region);
    if (isSD) {
      L.marker([landing.lat, landing.lng])
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
      fillColor: '#0F2A4A', fillOpacity: 0.9,
    }).addTo(map).bindTooltip(b.name, { permanent: false, direction: 'top' });
  });
}

function ChartTypeTabs({ active, onChange }) {
  var tabs = [
    { id: 'sst',          label: 'Sea Surface Temp', icon: '🌡️' },
    { id: 'chlorophyll',  label: 'Chlorophyll',      icon: '🌿' },
    { id: 'bathymetry',   label: 'Depth',            icon: '⛰️' },
    { id: 'satellite',    label: 'Satellite',         icon: '🛰️' },
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

function ChartsHeader({ chartType }) {
  var titles = {
    sst:          { title: 'Sea Surface Temperature',    desc: 'Bait concentrates at temperature breaks — look for 1–2°F transitions in the 64–72°F range.' },
    chlorophyll:  { title: 'Chlorophyll Concentration',  desc: 'Phytoplankton density indicates feeding zones — bait fish gather at the edges of green plumes.' },
    bathymetry:   { title: 'Bathymetry (Ocean Depth)',   desc: 'Underwater structure — banks, ledges, and drop-offs hold fish year-round.' },
    satellite:    { title: 'Satellite Imagery',           desc: 'True-color MODIS Terra pass. Cloud cover and water clarity visible at a glance.' },
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

function ChartsView() {
  const [chartType, setChartType] = React.useState('sst');
  const mapRef      = React.useRef(null);
  const mapInstance = React.useRef(null);
  const overlayLayer = React.useRef(null);

  // Initialize map once
  React.useEffect(function() {
    if (!mapRef.current || mapInstance.current) return;

    mapInstance.current = L.map(mapRef.current, {
      center: [32.5, -118.5], zoom: 7, minZoom: 6, maxZoom: 10,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap', opacity: 0.9,
    }).addTo(mapInstance.current);

    addLandingPins(mapInstance.current);
    addBankMarkers(mapInstance.current);

    return function() {
      if (mapInstance.current) {
        mapInstance.current.remove();
        mapInstance.current = null;
      }
    };
  }, []);

  // Swap overlay whenever chartType changes
  React.useEffect(function() {
    if (!mapInstance.current) return;
    if (overlayLayer.current) {
      mapInstance.current.removeLayer(overlayLayer.current);
      overlayLayer.current = null;
    }
    var layer = getOverlayLayer(chartType);
    if (layer) {
      layer.addTo(mapInstance.current);
      overlayLayer.current = layer;
    }
  }, [chartType]);

  return (
    <div className="charts-view">
      <ChartsHeader chartType={chartType} />
      <ChartTypeTabs active={chartType} onChange={setChartType} />
      <div ref={mapRef} className="chart-map" />
      <ChartLegend type={chartType} />
      <div className="chart-attribution">Data: NASA GIBS · GEBCO · OpenStreetMap</div>
    </div>
  );
}

window.ChartsView = ChartsView;
