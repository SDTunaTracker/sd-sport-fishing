// account.jsx — Account & Settings page (Coastal design system)
// Free account unlocks personal/sticky features (follows, alerts, species, data export).
// Anonymous users can still set Preferences (saved to localStorage).

const ALL_LANDINGS = ['Seaforth', "Fisherman's", 'H&M', 'Point Loma'];

const ACCOUNT_SPECIES = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado', 'Bigeye', 'Skipjack', 'Albacore'];

function _getInitials(name) {
  if (!name) return '?';
  var parts = name.trim().split(/\s+/);
  return parts.length >= 2
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : parts[0].slice(0, 2).toUpperCase();
}

function _exportCSV() {
  var trips = window.SD && Array.isArray(window.SD.TRIPS) ? window.SD.TRIPS : [];
  if (!trips.length) { alert('No trip data loaded yet — try again after the page data refreshes.'); return; }
  var cols = ['date', 'boat', 'landing', 'trip_length', 'anglers',
              'bluefin', 'yellowfin', 'yellowtail', 'dorado', 'skipjack', 'bigeye', 'albacore',
              'trophy_count', 'trophy_per_angler', 'trophy_per_angler_per_day'];
  var rows = [cols.join(',')].concat(trips.map(function(t) {
    return cols.map(function(c) {
      var v = t[c];
      if (v == null) return '';
      if (typeof v === 'string' && (v.includes(',') || v.includes('"')))
        return '"' + v.replace(/"/g, '""') + '"';
      return v;
    }).join(',');
  }));
  var blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = 'tuna-tracker-trips.csv'; a.click();
  setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}

function GatePrompt({ title, sub, onSignIn, onSignUp }) {
  return (
    <div className="acct-gate">
      <div className="acct-gate-t">{title}</div>
      {sub && <div className="acct-gate-s">{sub}</div>}
      <div className="acct-gate-btns">
        <button className="acct-btn coral" onClick={onSignUp}>Create free account</button>
        <button className="acct-btn" onClick={onSignIn}>Sign in</button>
      </div>
    </div>
  );
}

function MyAccountView({ settings, onSettingsChange, regions, onRegionsDirect, navigate }) {
  const { useEffect, useState, useRef } = React;
  const { user, loaded, signIn, signUp, signOut, isSignedIn } = useAuth();

  // ── Followed boats ────────────────────────────────────────────
  const [followedBoats, setFollowedBoatsState] = useState(function() {
    return window.getFollowedBoats ? window.getFollowedBoats() : [];
  });
  const [addingBoat, setAddingBoat] = useState(false);
  const [newBoat, setNewBoat] = useState('');
  const addInputRef = useRef(null);

  useEffect(function() {
    function sync() {
      setFollowedBoatsState(window.getFollowedBoats ? window.getFollowedBoats() : []);
    }
    window.addEventListener('tt-saved-boats-changed', sync);
    return function() { window.removeEventListener('tt-saved-boats-changed', sync); };
  }, []);

  useEffect(function() {
    if (addingBoat && addInputRef.current) addInputRef.current.focus();
  }, [addingBoat]);

  function unfollowBoat(name) {
    var next = followedBoats.filter(function(b) { return b !== name; });
    setFollowedBoatsState(next);
    if (window.setFollowedBoats) window.setFollowedBoats(next);
  }

  function commitAddBoat() {
    var name = newBoat.trim();
    if (name && !followedBoats.includes(name)) {
      var next = [...followedBoats, name];
      setFollowedBoatsState(next);
      if (window.setFollowedBoats) window.setFollowedBoats(next);
    }
    setNewBoat(''); setAddingBoat(false);
  }

  // ── Followed landings ─────────────────────────────────────────
  const [followedLandings, setFollowedLandingsState] = useState(function() {
    return window.getFollowedLandings ? window.getFollowedLandings() : ['Seaforth', "Fisherman's"];
  });

  useEffect(function() {
    function sync() {
      setFollowedLandingsState(window.getFollowedLandings ? window.getFollowedLandings() : []);
    }
    window.addEventListener('tt-followed-landings-changed', sync);
    return function() { window.removeEventListener('tt-followed-landings-changed', sync); };
  }, []);

  function toggleLanding(name) {
    var set = new Set(followedLandings);
    if (set.has(name)) set.delete(name); else set.add(name);
    var next = [...set];
    setFollowedLandingsState(next);
    if (window.setFollowedLandings) window.setFollowedLandings(next);
  }

  // ── Alerts ────────────────────────────────────────────────────
  const [alerts, setAlertsState] = useState(function() {
    return window.getAlerts ? window.getAlerts() : { boatFinished: true, boatNewTrip: true, topTripSpots: true, weeklyReport: false, deliveryMethod: 'email' };
  });

  function setAlert(key, val) {
    var next = Object.assign({}, alerts, { [key]: val });
    setAlertsState(next);
    if (window.setAlerts) window.setAlerts(next);
  }

  // ── Settings helpers ──────────────────────────────────────────
  function handleSettingsChange(next) {
    onSettingsChange(next);
    if (isSignedIn) {
      if (window.setUserPref) {
        window.setUserPref('trophySpecies', next.trophySpecies);
        window.setUserPref('tripLengthMethod', next.tripLengthMethod);
        window.setUserPref('unitSystem', next.unitSystem);
        window.setUserPref('tripTypeFilter', next.tripTypeFilter);
        window.setUserPref('windUnit', next.windUnit);
        window.setUserPref('density', next.density);
      }
    } else {
      // Preferences persist for anonymous users too (localStorage via setUserPref)
      if (window.setUserPref) {
        window.setUserPref('tripTypeFilter', next.tripTypeFilter);
        window.setUserPref('density', next.density);
      }
    }
  }

  function setPref(key, val) {
    handleSettingsChange(Object.assign({}, settings, { [key]: val }));
  }

  function toggleSpecies(sp) {
    var next = settings.trophySpecies.includes(sp)
      ? settings.trophySpecies.filter(function(s) { return s !== sp; })
      : [...settings.trophySpecies, sp];
    if (next.length === 0) return;
    handleSettingsChange(Object.assign({}, settings, { trophySpecies: next }));
  }

  // ── Region ────────────────────────────────────────────────────
  var regionChoice =
    regions && regions.length >= 2   ? 'all_socal' :
    regions && regions[0] === 'oc_la' ? 'oc_la'    : 'san_diego';

  function setRegion(val) {
    var map = { san_diego: ['san_diego'], oc_la: ['oc_la'], all_socal: ['san_diego', 'oc_la'] };
    if (onRegionsDirect) onRegionsDirect(map[val] || ['san_diego']);
    if (window.setUserPref) window.setUserPref('region_choice', val);
  }

  // ── Boat name suggestions ─────────────────────────────────────
  var allBoatNames = window.SD && window.SD.BOATS
    ? Object.keys(window.SD.BOATS).sort()
    : [];

  var gateProps = { onSignIn: signIn, onSignUp: signUp };

  // ── Loading ───────────────────────────────────────────────────
  if (!loaded) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <i className="fa-solid fa-spinner fa-spin" style={{ fontSize: 24, color: 'var(--accent)' }}/>
      </div>
    );
  }

  return (
    <div className="acct-wrap">
      <div className="acct-eyebrow">Your account</div>
      <h1 className="acct-h1">Account &amp; settings</h1>

      {/* ── 1. Identity ────────────────────────────────────────── */}
      {isSignedIn ? (
        <div className="acct-card">
          <div className="acct-id">
            <div className="acct-avb" aria-hidden="true">
              {_getInitials(user.fullName || user.firstName || '')}
            </div>
            <div className="acct-id-info">
              <div className="acct-nm">{user.fullName || user.firstName || 'Account'}</div>
              <div className="acct-em">{(user.primaryEmailAddress && user.primaryEmailAddress.emailAddress) || ''}</div>
              <span className="acct-badge">● Free account</span>
            </div>
            <button className="acct-out" onClick={signOut}>Sign out</button>
          </div>
          <div className="acct-freeline">
            Your account saves your <b>followed boats, species, and alerts</b> across all your devices.
          </div>
        </div>
      ) : (
        <div className="acct-card acct-sign-card">
          <div className="acct-sign-title">Follow boats. Get alerts. Save settings.</div>
          <p className="acct-sign-sub">
            A free account keeps your followed boats, target species, and preferences in sync across every device.
          </p>
          <div className="acct-sign-btns">
            <button className="acct-btn coral" onClick={signUp}>Create free account</button>
            <button className="acct-btn" onClick={signIn}>Sign in</button>
          </div>
        </div>
      )}

      {/* ── 2. Following ───────────────────────────────────────── */}
      <div className="acct-card">
        <div className="acct-sec-t">Boats you follow</div>
        <div className="acct-sec-d">Followed boats get highlighted on Today and trigger your alerts.</div>

        {isSignedIn ? (
          <React.Fragment>
            <div className="acct-chips">
              {followedBoats.map(function(name) {
                return (
                  <SettingsChip
                    key={name}
                    selected
                    removable
                    onRemove={function() { unfollowBoat(name); }}
                  >
                    {name}
                  </SettingsChip>
                );
              })}

              {addingBoat ? (
                <div className="acct-add-input-wrap">
                  <input
                    ref={addInputRef}
                    id="acct-add-boat-input"
                    list="acct-boat-list"
                    className="acct-add-input"
                    value={newBoat}
                    onChange={function(e) { setNewBoat(e.target.value); }}
                    onKeyDown={function(e) {
                      if (e.key === 'Enter')  { commitAddBoat(); }
                      if (e.key === 'Escape') { setAddingBoat(false); setNewBoat(''); }
                    }}
                    placeholder="Boat name…"
                    aria-label="Enter boat name to follow"
                  />
                  <datalist id="acct-boat-list">
                    {allBoatNames.map(function(n) { return <option key={n} value={n}/>; })}
                  </datalist>
                  <button className="acct-btn coral" onClick={commitAddBoat}>Add</button>
                  <button className="acct-btn" onClick={function() { setAddingBoat(false); setNewBoat(''); }}>Cancel</button>
                </div>
              ) : (
                <SettingsChip add onClick={function() { setAddingBoat(true); }}>＋ Follow a boat</SettingsChip>
              )}
            </div>

            <div className="acct-sec-t" style={{ marginTop: 20 }}>Your landings</div>
            <div className="acct-sec-d">Focus Today and the leaderboards on the landings you launch from.</div>
            <div className="acct-chips">
              {ALL_LANDINGS.map(function(name) {
                return (
                  <SettingsChip
                    key={name}
                    selected={followedLandings.includes(name)}
                    onClick={function() { toggleLanding(name); }}
                  >
                    {name}
                  </SettingsChip>
                );
              })}
            </div>
          </React.Fragment>
        ) : (
          <GatePrompt
            title="Create a free account to follow boats"
            sub="Takes 10 seconds. Followed boats are highlighted on Today's report."
            {...gateProps}
          />
        )}
      </div>

      {/* ── 3. Target species ──────────────────────────────────── */}
      <div className="acct-card">
        <div className="acct-sec-t">Target species</div>
        <div className="acct-sec-d">Tailors the leaderboards, reports, and your trophy count to what you actually chase.</div>

        {isSignedIn ? (
          <div className="acct-chips">
            {ACCOUNT_SPECIES.map(function(sp) {
              return (
                <SettingsChip
                  key={sp}
                  selected={settings.trophySpecies.includes(sp)}
                  onClick={function() { toggleSpecies(sp); }}
                >
                  {sp}
                </SettingsChip>
              );
            })}
          </div>
        ) : (
          <GatePrompt
            title="Sign in to customize target species"
            sub="Leaderboards and trophy counts follow your species selection."
            {...gateProps}
          />
        )}
      </div>

      {/* ── 4. Alerts ──────────────────────────────────────────── */}
      <div className="acct-card">
        <div className="acct-sec-t">Alerts &amp; notifications</div>
        <div className="acct-sec-d">Tell us what's worth a ping.</div>

        {isSignedIn ? (
          <React.Fragment>
            {[
              { key: 'boatFinished', t: 'A boat you follow finished a trip',
                s: 'Get the fish counts as soon as a followed boat reports in' },
              { key: 'boatNewTrip',  t: 'A boat you follow scheduled a new trip',
                s: 'When a followed boat posts a new trip you can book' },
              { key: 'topTripSpots', t: 'A top trip opens spots',
                s: 'Open spots on a high-performing upcoming trip' },
              { key: 'weeklyReport', t: 'Weekly bite report',
                s: 'A Friday digest of the week on the water' },
            ].map(function(row) {
              return (
                <div key={row.key} className="acct-row" role="group" aria-label={row.t}>
                  <div className="acct-row-l">
                    <div className="acct-row-t">{row.t}</div>
                    <div className="acct-row-s">{row.s}</div>
                  </div>
                  <SettingsToggle
                    on={!!alerts[row.key]}
                    onChange={function(val) { setAlert(row.key, val); }}
                  />
                </div>
              );
            })}

            <div className="acct-field" style={{ borderTop: '1px solid var(--line)', marginTop: 6 }}>
              <label className="acct-field-l" htmlFor="acct-delivery-seg">
                <div className="acct-field-t">Deliver by</div>
              </label>
              <SegmentedControl
                value={alerts.deliveryMethod || 'email'}
                onChange={function(v) { setAlert('deliveryMethod', v); }}
                options={[
                  { value: 'email', label: 'Email' },
                  { value: 'push',  label: 'Push'  },
                ]}
              />
            </div>
          </React.Fragment>
        ) : (
          <GatePrompt
            title="Sign in to set up alerts"
            sub="Get notified when your boats report in or top trips open spots."
            {...gateProps}
          />
        )}
      </div>

      {/* ── 5. Preferences ────────────────────────────────────── */}
      <div className="acct-card">
        <div className="acct-sec-t">Preferences</div>
        <div className="acct-sec-d">Display &amp; defaults — saved for your next visit.</div>

        <div className="acct-field">
          <label className="acct-field-l" htmlFor="acct-region-select">
            <div className="acct-field-t">Region</div>
          </label>
          <select
            id="acct-region-select"
            className="acct-select"
            value={regionChoice}
            onChange={function(e) { setRegion(e.target.value); }}
          >
            <option value="san_diego">San Diego</option>
            <option value="oc_la" disabled={!(window.FEATURES && window.FEATURES.SHOW_OCLA)}>
              OC / LA (soon)
            </option>
          </select>
        </div>

        <div className="acct-field">
          <div className="acct-field-l">
            <div className="acct-field-t">Trip type focus</div>
            <div className="acct-field-s">how leaderboards weight trips</div>
          </div>
          <SegmentedControl
            value={settings.tripTypeFilter || 'all'}
            onChange={function(v) { setPref('tripTypeFilter', v); }}
            options={[
              { value: 'all',      label: 'All'        },
              { value: 'local',    label: 'Local / day' },
              { value: 'multiday', label: 'Multi-day'  },
            ]}
          />
        </div>

        <div className="acct-field">
          <label className="acct-field-l">
            <div className="acct-field-t">Water temp</div>
          </label>
          <SegmentedControl
            value={(settings.unitSystem === 'metric') ? 'c' : 'f'}
            onChange={function(v) { setPref('unitSystem', v === 'c' ? 'metric' : 'imperial'); }}
            options={[{ value: 'f', label: '°F' }, { value: 'c', label: '°C' }]}
          />
        </div>

        <div className="acct-field">
          <label className="acct-field-l">
            <div className="acct-field-t">Wind</div>
          </label>
          <SegmentedControl
            value={settings.windUnit || 'kt'}
            onChange={function(v) { setPref('windUnit', v); }}
            options={[{ value: 'kt', label: 'kt' }, { value: 'mph', label: 'mph' }]}
          />
        </div>

        <div className="acct-field">
          <label className="acct-field-l">
            <div className="acct-field-t">Density</div>
          </label>
          <SegmentedControl
            value={settings.density || 'comfortable'}
            onChange={function(v) { setPref('density', v); }}
            options={[
              { value: 'comfortable', label: 'Comfortable' },
              { value: 'compact',     label: 'Compact'     },
            ]}
          />
        </div>
      </div>

      {/* ── 6. Your data ──────────────────────────────────────── */}
      <div className="acct-card">
        <div className="acct-sec-t">Your data</div>
        <div className="acct-sec-d">Export leaderboards and boat history — free.</div>

        {isSignedIn ? (
          <button className="acct-btn" onClick={_exportCSV}>
            ⬇ Export CSV
          </button>
        ) : (
          <GatePrompt
            title="Sign in to export data"
            sub="Download leaderboards and boat history as a spreadsheet."
            {...gateProps}
          />
        )}
      </div>
    </div>
  );
}

Object.assign(window, { MyAccountView });
