function ChartsView() {
  const mapRef = React.useRef(null);
  const mapInstance = React.useRef(null);

  React.useEffect(() => {
    if (!mapRef.current || mapInstance.current) return;

    mapInstance.current = L.map(mapRef.current, {
      center: [32.5, -118.0],
      zoom: 7,
      minZoom: 6,
      maxZoom: 10,
    });

    // Base map
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap',
      opacity: 0.9,
    }).addTo(mapInstance.current);

    // SST overlay from NASA GIBS — use 2 days ago for reliable data availability
    const date = new Date();
    date.setDate(date.getDate() - 2);
    const dateStr = date.toISOString().slice(0, 10);

    L.tileLayer(
      'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Aqua_L3_SST_MidIR_4km_Day_Daily/default/' + dateStr + '/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png',
      {
        opacity: 0.7,
        attribution: 'NASA GIBS',
        maxNativeZoom: 7,
      }
    ).addTo(mapInstance.current);

    // Landing markers — LANDINGS_META is an array of {name, lat, lng, region}
    const landings = (window.SD && window.SD.LANDINGS_META) || [];
    landings.forEach(function(landing) {
      if (!landing || !landing.lat || !landing.lng) return;
      const isSD = (landing.region === 'san_diego' || !landing.region);
      if (isSD) {
        L.marker([landing.lat, landing.lng])
          .addTo(mapInstance.current)
          .bindPopup('<b>' + landing.name + '</b>');
      }
    });

    // Key SoCal fishing banks
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
        radius: 5,
        color: '#fff',
        weight: 2,
        fillColor: '#0F2A4A',
        fillOpacity: 0.9,
      })
        .addTo(mapInstance.current)
        .bindTooltip(b.name, { permanent: false, direction: 'top' });
    });

    return function() {
      if (mapInstance.current) {
        mapInstance.current.remove();
        mapInstance.current = null;
      }
    };
  }, []);

  return (
    <div className="charts-view">
      <div className="charts-header">
        <h1>Ocean Charts</h1>
        <p>Southern California fishing grounds — Sea Surface Temperature</p>
      </div>

      <div ref={mapRef} className="chart-map" />

      <div className="chart-footer">
        <div className="chart-attribution">
          Data: NASA GIBS · OpenStreetMap
        </div>
        <div className="chart-legend">
          <span>Cool</span>
          <div className="legend-gradient sst" />
          <span>Warm</span>
        </div>
      </div>
    </div>
  );
}

window.ChartsView = ChartsView;
