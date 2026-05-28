// Boats — visual directory and discovery experience
const _STATIC_LANDINGS_META = [
  { name: "H&M Landing",            lat: 32.7235, lng: -117.2276, googleRating: 4.3, googleCount: 850,  region: "san_diego" },
  { name: "Fisherman's Landing",     lat: 32.7250, lng: -117.2265, googleRating: 4.5, googleCount: 650,  region: "san_diego" },
  { name: "Point Loma Sportfishing", lat: 32.7241, lng: -117.2273, googleRating: 4.4, googleCount: 420,  region: "san_diego" },
  { name: "Seaforth Sportfishing",   lat: 32.7631, lng: -117.2355, googleRating: 4.7, googleCount: 310,  region: "san_diego" },
  { name: "Oceanside Sea Center",    lat: 33.2052, lng: -117.3891, googleRating: 4.6, googleCount: 180,  region: "san_diego" },
];

function StarRow({ rating, count, size }) {
  if (rating == null) return React.createElement('span', { style: { color: 'var(--tb-gray-3)', fontSize: 11 } }, 'No reviews');
  const stars = [];
  for (let i = 1; i <= 5; i++) {
    if (rating >= i) stars.push('full');
    else if (rating >= i - 0.75) stars.push('half');
    else stars.push('empty');
  }
  return (
    <span className={`star-row${size === 'xs' ? ' star-row-xs' : ''}`}>
      {stars.map((t, i) => (
        <i key={i} className={
          t === 'full'  ? 'fa-solid fa-star' :
          t === 'half'  ? 'fa-solid fa-star-half-stroke' :
                          'fa-regular fa-star'
        } />
      ))}
      <span className="star-row-score">{Number(rating).toFixed(1)}</span>
      {count != null && <span className="star-row-count">({count})</span>}
    </span>
  );
}

function BoatCard({ boat, landing, profile, reviewData, tpa, winRate, form, lengths, navigate }) {
  const hasPhoto = profile && profile.photoUrl;

  let badge = null;
  if (form >= 7) badge = <span className="boats-form-badge hot">🔥 Hot</span>;
  else if (form != null && form <= 3) badge = <span className="boats-form-badge cold">❄️ Cold</span>;

  return (
    <div className="boat-card" onClick={() => {
      if (window.TTTrack) TTTrack.boatView(boat, landing || '');
      navigate('boat', { boat });
    }}>
      <div className="boat-card-img">
        {hasPhoto
          ? <img src={profile.photoUrl} alt={boat} loading="lazy" />
          : <div className="boat-card-img-placeholder"><i className="fa-solid fa-sailboat" /></div>
        }
        {badge && <div className="boat-card-badge-overlay">{badge}</div>}
      </div>
      <div className="boat-card-body">
        <div className="boat-card-name">{boat}</div>
        {reviewData && reviewData.avgRating != null && (
          <StarRow rating={reviewData.avgRating} count={reviewData.count} />
        )}
        <div className="boat-card-stats">
          {tpa != null && (
            <div className="boat-card-stat">
              <span className="bcs-val">{fmt.tpa(tpa)}</span>
              <span className="bcs-lbl">fish/day</span>
            </div>
          )}
          {winRate != null && (
            <div className="boat-card-stat">
              <span className="bcs-val">{Math.round(winRate * 100)}%</span>
              <span className="bcs-lbl">win rate</span>
            </div>
          )}
        </div>
        {lengths && lengths.length > 0 && (
          <div className="boat-card-lengths">
            {lengths.slice(0, 4).map(l => (
              <span key={l} className="boat-card-len">{l}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LandingMap({ landingsMeta, boatsByLanding }) {
  const mapRef = useRef(null);
  const instanceRef = useRef(null);

  useEffect(() => {
    if (!window.L || !mapRef.current) return;
    if (instanceRef.current) {
      instanceRef.current.remove();
      instanceRef.current = null;
    }

    const visible = landingsMeta.filter(m => m.lat && m.lng);
    if (!visible.length) return;

    const avgLat = visible.reduce((s, m) => s + m.lat, 0) / visible.length;
    const avgLng = visible.reduce((s, m) => s + m.lng, 0) / visible.length;

    const map = window.L.map(mapRef.current, { center: [avgLat, avgLng], zoom: 11 });
    instanceRef.current = map;

    window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);

    visible.forEach(meta => {
      const boats = boatsByLanding[meta.name] || [];
      const shortName = meta.name.split(' ')[0];
      const pin = window.L.divIcon({
        className: '',
        html: `<div class="l-pin"><div class="l-pin-dot"></div><div class="l-pin-label">${shortName}</div></div>`,
        iconSize: [80, 36],
        iconAnchor: [40, 8],
        popupAnchor: [0, -14],
      });
      const popup = `<div class="l-popup">
        <div class="l-popup-name">${meta.name}</div>
        <div class="l-popup-rating">⭐ ${meta.googleRating} · ${meta.googleCount} reviews</div>
        <div class="l-popup-boats">${boats.length} boat${boats.length !== 1 ? 's' : ''}</div>
      </div>`;
      window.L.marker([meta.lat, meta.lng], { icon: pin }).bindPopup(popup).addTo(map);
    });

    return () => {
      if (instanceRef.current) {
        instanceRef.current.remove();
        instanceRef.current = null;
      }
    };
  }, [landingsMeta]);

  if (!window.L) {
    return (
      <div className="landing-map-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--tb-gray-3)', fontSize: 13 }}>
        Map unavailable
      </div>
    );
  }
  return <div ref={mapRef} className="landing-map-container" />;
}

function BoatsView({ filters, setFilters, navigate, tweaks, settings, regions }) {
  const landingsMeta = (window.SD && window.SD.LANDINGS_META) ? window.SD.LANDINGS_META : _STATIC_LANDINGS_META;
  const profiles   = (window.SD && window.SD.BOAT_PROFILES) || {};
  const reviewsMap = (window.SD && window.SD.REVIEWS && window.SD.REVIEWS.byBoat) || {};

  const boatLengths = useMemo(() => {
    const m = {};
    if (window.SD && window.SD.BOATS) {
      for (const b of window.SD.BOATS) m[b.name] = b.lengths;
    }
    return m;
  }, []);

  const trips = useMemo(() => SDA.filterTrips({ ...filters, minTrips: 0 }, regions), [filters, regions]);
  const { rows } = useMemo(() => SDA.boatLeaderboard(trips, filters.species, 0), [trips, filters.species]);

  const boatWinMap = useMemo(() => {
    try {
      const raw = SDA.boatWinRates ? SDA.boatWinRates() : {};
      const acc = {};
      for (const [key, val] of Object.entries(raw)) {
        const boat = key.split('|')[0];
        if (!acc[boat]) acc[boat] = { sum: 0, n: 0 };
        acc[boat].sum += val.winRate;
        acc[boat].n   += 1;
      }
      const out = {};
      for (const [boat, { sum, n }] of Object.entries(acc)) out[boat] = sum / n;
      return out;
    } catch(e) { return {}; }
  }, []);

  const formMap = useMemo(() => {
    try {
      const _ALL = { year:'all', species:'all', landing:'all', month:'all', minTrips:0, includeZero:true, boat:'all' };
      const streaks = SDA.boatStreaks(SDA.filterTrips(_ALL, regions));
      const out = {};
      for (const s of streaks) out[s.boat] = s.goodCount;
      return out;
    } catch(e) { return {}; }
  }, [regions]);

  // View toggle — persisted to localStorage
  const [viewMode, setViewModeRaw] = useState(() => {
    try { return localStorage.getItem('tt_boats_view') || 'grid'; }
    catch(e) { return 'grid'; }
  });
  const setViewMode = (v) => {
    setViewModeRaw(v);
    try { localStorage.setItem('tt_boats_view', v); } catch(e) {}
  };

  const [search, setSearch]       = useState('');
  const [formFilter, setFormFilter] = useState('all');
  const [sortBy, setSortBy]       = useState('avgTPAPerDay');
  const [sortDir, setSortDir]     = useState('desc');

  // Merge all data onto each row
  const boatRows = useMemo(() => rows.map(r => ({
    ...r,
    winRate: boatWinMap[r.boat] ?? null,
    form:    formMap[r.boat]    ?? null,
    lengths: boatLengths[r.boat] || [],
    profile: profiles[r.boat]   || null,
    reviews: reviewsMap[r.boat] || null,
  })), [rows, boatWinMap, formMap, boatLengths, profiles, reviewsMap]);

  const filtered = useMemo(() => {
    let r = [...boatRows];
    if (search) {
      const q = search.toLowerCase();
      r = r.filter(x => x.boat.toLowerCase().includes(q) || (x.landing || '').toLowerCase().includes(q));
    }
    if (formFilter === 'hot')  r = r.filter(x => x.form >= 7);
    if (formFilter === 'cold') r = r.filter(x => x.form != null && x.form <= 3);
    return r;
  }, [boatRows, search, formFilter]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let va, vb;
      if      (sortBy === 'winRate') { va = a.winRate ?? -1; vb = b.winRate ?? -1; }
      else if (sortBy === 'form')    { va = a.form    ?? -1; vb = b.form    ?? -1; }
      else if (sortBy === 'boat' || sortBy === 'landing') { va = a[sortBy] || ''; vb = b[sortBy] || ''; }
      else                           { va = a[sortBy] ?? -1; vb = b[sortBy] ?? -1; }
      if (typeof va === 'string') return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      return sortDir === 'asc' ? va - vb : vb - va;
    });
  }, [filtered, sortBy, sortDir]);

  // Group by landing
  const byLanding = useMemo(() => {
    const m = {};
    for (const b of sorted) {
      if (!m[b.landing]) m[b.landing] = [];
      m[b.landing].push(b);
    }
    return m;
  }, [sorted]);

  // All boats by landing (for map popup counts, unfiltered)
  const allByLanding = useMemo(() => {
    const m = {};
    for (const b of boatRows) {
      if (!m[b.landing]) m[b.landing] = [];
      m[b.landing].push(b);
    }
    return m;
  }, [boatRows]);

  // Landing order: follow LANDINGS_META order, then any unknowns
  const landingOrder = useMemo(() => {
    const metaNames = landingsMeta.map(m => m.name);
    const seen = new Set(metaNames);
    const extra = Object.keys(byLanding).filter(l => !seen.has(l));
    return [...metaNames.filter(l => byLanding[l]), ...extra.filter(l => byLanding[l])];
  }, [landingsMeta, byLanding]);

  const toggleSort = (k) => {
    if (sortBy === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortBy(k); setSortDir('desc'); }
  };
  const sortArrow = (k) => sortBy === k ? (sortDir === 'asc' ? '▲' : '▼') : '⇅';

  const regionLabel  = (regions && window.getRegionSubtitle) ? window.getRegionSubtitle(regions) : 'San Diego';
  const speciesLabel = (filters.species && filters.species !== 'all') ? filters.species : 'Tuna';

  // Which landings have map coords and have boats in filtered set
  const mapLandings = landingsMeta.filter(m => m.lat && m.lng && allByLanding[m.name]);

  return (
    <Fragment>
      <div className="pagehead">
        <div>
          <h1>Boats <span className="region-subtitle-badge">{regionLabel}</span></h1>
          <div className="sub">Browse and discover every boat — {filtered.length} boats · click any card for the full profile</div>
        </div>
      </div>

      {/* Controls bar */}
      <div className="boats-controls">
        <div className="boats-search-input-wrap">
          <i className="fa-solid fa-magnifying-glass boats-search-icon" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search boats or landings…"
            className="boats-search-input"
          />
          {search && <button onClick={() => setSearch('')} className="boats-search-clear">×</button>}
        </div>
        <div className="row" style={{ gap: 4 }}>
          {[['all','All'],['hot','🔥 Hot'],['cold','❄️ Cold']].map(([val, lbl]) => (
            <span key={val} className={`filter-pill ${formFilter === val ? 'on' : ''}`}
                  onClick={() => setFormFilter(val)}>{lbl}</span>
          ))}
        </div>
        <div className="boats-view-toggle">
          <button className={viewMode === 'grid' ? 'active' : ''} onClick={() => setViewMode('grid')} title="Grid view">
            <i className="fa-solid fa-grip" />
          </button>
          <button className={viewMode === 'map' ? 'active' : ''} onClick={() => setViewMode('map')} title="Map view">
            <i className="fa-solid fa-map-location-dot" />
          </button>
          <button className={viewMode === 'list' ? 'active' : ''} onClick={() => setViewMode('list')} title="List view">
            <i className="fa-solid fa-list" />
          </button>
        </div>
      </div>

      <FilterBar filters={filters} setFilters={setFilters} regions={regions} />

      {/* ── MAP VIEW ─────────────────────────────────────────────────── */}
      {viewMode === 'map' && (
        <div className="boats-map-wrap">
          <LandingMap landingsMeta={mapLandings} boatsByLanding={allByLanding} />
          <div className="boats-landing-chips">
            {mapLandings.map(meta => {
              const cnt = (byLanding[meta.name] || []).length;
              return (
                <div key={meta.name} className="blanding-chip">
                  <span className="blc-name">{meta.name}</span>
                  {meta.googleRating && <span className="blc-rating">⭐ {meta.googleRating}</span>}
                  <span className="blc-count">{cnt} boat{cnt !== 1 ? 's' : ''}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── GRID VIEW ────────────────────────────────────────────────── */}
      {viewMode === 'grid' && (
        <div className="boats-grid-wrap">
          {landingOrder.length === 0 && (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--tb-gray-3)' }}>No boats match your search.</div>
          )}
          {landingOrder.map(lname => {
            const meta  = landingsMeta.find(m => m.name === lname);
            const boats = byLanding[lname] || [];
            if (!boats.length) return null;
            return (
              <div key={lname} className="boats-landing-section">
                <div className="boats-landing-header">
                  <div className="blh-left">
                    <span className="blh-name">{lname}</span>
                    <span className="blh-count">{boats.length} boat{boats.length !== 1 ? 's' : ''}</span>
                  </div>
                  {meta && meta.googleRating && (
                    <div className="blh-rating">
                      <StarRow rating={meta.googleRating} count={meta.googleCount} size="xs" />
                      <span className="blh-google">Google</span>
                    </div>
                  )}
                </div>
                <div className="boats-card-grid">
                  {boats.map(b => (
                    <BoatCard
                      key={b.boat}
                      boat={b.boat}
                      landing={b.landing}
                      profile={b.profile}
                      reviewData={b.reviews}
                      tpa={b.avgTPAPerDay}
                      winRate={b.winRate}
                      form={b.form}
                      lengths={b.lengths}
                      navigate={navigate}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── LIST VIEW ────────────────────────────────────────────────── */}
      {viewMode === 'list' && (
        <Panel title="All Boats" meta={`${sorted.length} boats · sorted by ${sortBy === 'avgTPAPerDay' ? speciesLabel + '/day' : sortBy}`} padding={false}>
          <div style={{ overflowX: 'auto' }}>
            <table className="dt">
              <thead>
                <tr>
                  <th style={{ width: 36 }}>#</th>
                  <th className={sortBy === 'boat' ? 'active' : ''} onClick={() => toggleSort('boat')} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                    Boat <span className="sortarrow">{sortArrow('boat')}</span>
                  </th>
                  <th className={sortBy === 'landing' ? 'active' : ''} onClick={() => toggleSort('landing')} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                    Landing <span className="sortarrow">{sortArrow('landing')}</span>
                  </th>
                  <th className={`num ${sortBy === 'tripCount' ? 'active' : ''}`} onClick={() => toggleSort('tripCount')} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                    Trips <span className="sortarrow">{sortArrow('tripCount')}</span>
                  </th>
                  <th className={`num ${sortBy === 'avgTPAPerDay' ? 'active' : ''}`} onClick={() => toggleSort('avgTPAPerDay')} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                    {speciesLabel}/Day <span className="sortarrow">{sortArrow('avgTPAPerDay')}</span>
                  </th>
                  <th className={`num ${sortBy === 'winRate' ? 'active' : ''}`} onClick={() => toggleSort('winRate')} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                    Win Rate <span className="sortarrow">{sortArrow('winRate')}</span>
                  </th>
                  <th className={sortBy === 'form' ? 'active' : ''} onClick={() => toggleSort('form')} style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                    Form <span className="sortarrow">{sortArrow('form')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((b, i) => (
                  <tr key={b.boat} className="clickable" onClick={() => {
                    if (window.TTTrack) TTTrack.boatView(b.boat, b.landing || '');
                    navigate('boat', { boat: b.boat });
                  }}>
                    <td>
                      <span className="rank" style={{
                        color: i < 3 ? 'var(--ss-orange-500)' : undefined,
                        fontWeight: i < 3 ? 700 : 500,
                      }}>{i + 1}</span>
                    </td>
                    <td><b>{b.boat}</b></td>
                    <td>{b.landing}</td>
                    <td className="num">{fmt.n(b.tripCount)}</td>
                    <td className="num">{fmt.tpa(b.avgTPAPerDay)}</td>
                    <td className="num">{b.winRate != null ? `${Math.round(b.winRate * 100)}%` : '—'}</td>
                    <td>
                      {b.form >= 7
                        ? <span className="boats-form-badge hot">🔥 Hot</span>
                        : b.form != null && b.form <= 3
                          ? <span className="boats-form-badge cold">❄️ Cold</span>
                          : b.form != null
                            ? <span style={{ color: 'var(--tb-slate)', fontSize: 11 }}>{b.form}/10</span>
                            : <span style={{ color: 'var(--ss-gray-2)' }}>—</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </Fragment>
  );
}

Object.assign(window, { BoatsView });
