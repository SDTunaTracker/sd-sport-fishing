// account.jsx — My Account page with Clerk auth integration.
// Signed-out: shows sign-in CTAs + guest preferences.
// Signed-in: shows Clerk UserProfile + cloud-synced preferences.

function MyAccountView({ settings, onSettingsChange, regions, onRegionsDirect }) {
  const { useEffect, useState } = React;
  const { user, loaded, signIn, signUp, signOut, isSignedIn } = useAuth();


  // ── Region helpers ──────────────────────────────────────────────
  // Derive the three-way selection from the regions array.
  const regionChoice =
    regions.length >= 2               ? 'all_socal'  :
    regions[0] === 'oc_la'            ? 'oc_la'      :
                                        'san_diego';

  const REGION_OPTIONS = [
    { id: 'san_diego',  label: 'San Diego',             regions: ['san_diego'] },
    { id: 'oc_la',      label: 'OC / LA',               regions: ['oc_la'] },
    { id: 'all_socal',  label: 'All SoCal (both)',       regions: ['san_diego', 'oc_la'] },
  ];

  function setRegionChoice(optionId) {
    const opt = REGION_OPTIONS.find(o => o.id === optionId);
    if (!opt) return;
    onRegionsDirect(opt.regions);
    window.setUserPref('region_choice', optionId);
  }

  // ── Species helpers ─────────────────────────────────────────────
  function handleSettingsChange(next) {
    onSettingsChange(next);
    if (isSignedIn) {
      window.setUserPref('trophySpecies', next.trophySpecies);
      window.setUserPref('tripLengthMethod', next.tripLengthMethod);
    }
  }

  function toggleSpecies(sp) {
    const next = settings.trophySpecies.includes(sp)
      ? settings.trophySpecies.filter(s => s !== sp)
      : [...settings.trophySpecies, sp];
    if (next.length === 0) return;
    handleSettingsChange({ ...settings, trophySpecies: next });
  }

  function applyPreset(preset) {
    handleSettingsChange({ ...settings, trophySpecies: [...preset.species] });
  }

  function setMethod(m) {
    handleSettingsChange({ ...settings, tripLengthMethod: m });
  }

  function resetAll() {
    handleSettingsChange(defaultSettings());
    onRegionsDirect(['san_diego']);
    window.setUserPref('region_choice', 'san_diego');
  }

  // ── Shared styles ───────────────────────────────────────────────
  const card = {
    background: 'var(--ss-surface)', border: '1px solid var(--ss-border)',
    borderRadius: 10, padding: '20px 24px', marginBottom: 16,
  };
  const sectionTitle = { font: '600 14px/20px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 4 };
  const sectionDesc  = { font: '400 12px/18px var(--ss-font-sans)', color: 'var(--ss-slate)', marginBottom: 16 };
  const fieldLabel   = {
    font: '600 11px/14px var(--ss-font-sans)', color: 'var(--ss-gray-3)',
    textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10, display: 'block',
  };
  const radioRow = {
    display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0',
    cursor: 'pointer', font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-ink)',
  };
  const chipBase = {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '5px 12px', borderRadius: 20, cursor: 'pointer',
    font: '500 12px/16px var(--ss-font-sans)', border: '1px solid var(--ss-border)',
    userSelect: 'none', transition: 'background 0.15s, border-color 0.15s',
  };
  const { trophySpecies, tripLengthMethod } = settings;
  const isDefault = isDefaultSpecies(trophySpecies);

  // ── Region section ──────────────────────────────────────────────
  const showOcla = window.FEATURES && window.FEATURES.SHOW_OCLA;

  function RegionSection() {
    return (
      <div style={card}>
        <div style={sectionTitle}>Default Region</div>
        <p style={sectionDesc}>Choose which region's data loads when you visit the site.</p>

        <label style={{ ...radioRow, cursor: 'pointer' }}>
          <input type="radio" name="regionChoice" value="san_diego"
                 checked={regionChoice === 'san_diego'}
                 onChange={() => setRegionChoice('san_diego')}
                 style={{ accentColor: 'var(--ss-darkseagreen-500)', width: 15, height: 15, cursor: 'pointer', flexShrink: 0 }}/>
          <span>San Diego</span>
          <span style={{ font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-gray-3)' }}>(default)</span>
        </label>

        {showOcla ? (
          <React.Fragment>
            <label style={{ ...radioRow, cursor: 'pointer' }}>
              <input type="radio" name="regionChoice" value="oc_la"
                     checked={regionChoice === 'oc_la'}
                     onChange={() => setRegionChoice('oc_la')}
                     style={{ accentColor: 'var(--ss-darkseagreen-500)', width: 15, height: 15, cursor: 'pointer', flexShrink: 0 }}/>
              <span>OC / LA</span>
            </label>
            <label style={{ ...radioRow, cursor: 'pointer' }}>
              <input type="radio" name="regionChoice" value="all_socal"
                     checked={regionChoice === 'all_socal'}
                     onChange={() => setRegionChoice('all_socal')}
                     style={{ accentColor: 'var(--ss-darkseagreen-500)', width: 15, height: 15, cursor: 'pointer', flexShrink: 0 }}/>
              <span>All SoCal (both)</span>
            </label>
          </React.Fragment>
        ) : (
          <div style={{ ...radioRow, cursor: 'default', opacity: 0.55 }}>
            <i className="fa-solid fa-lock" style={{ fontSize: 11, color: 'var(--ss-gray-3)', flexShrink: 0 }}/>
            <span style={{ color: 'var(--ss-gray-3)' }}>OC / LA</span>
            <span style={{ font: '400 10px/14px var(--ss-font-sans)', color: 'var(--ss-gray-3)', background: 'var(--ss-foam)', padding: '2px 8px', borderRadius: 10 }}>Coming Soon</span>
          </div>
        )}
      </div>
    );
  }

  // ── Species section (shared) ────────────────────────────────────
  function SpeciesSection() {
    const methods = [
      { id: 'rounded', label: 'Rounded (recommended)', sub: 'Full Day, Overnight, and 1.5-day trips all count as 1 day. 2.5-day counts as 2, etc.' },
      { id: 'actual',  label: 'Actual trip length',    sub: 'Full Day = 0.75, Overnight = 1.0, 1.5-day = 1.5, 2.5-day = 2.5, etc.' },
    ];
    return (
      <React.Fragment>
        <div style={card}>
          <div style={sectionTitle}>Trophy Species</div>
          <p style={sectionDesc}>Choose which species count toward the "per angler per day" metric.</p>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: 16 }}>
            {PRESETS.map(p => {
              const active = p.species.length === trophySpecies.length &&
                p.species.every(sp => trophySpecies.includes(sp));
              return (
                <button key={p.label} onClick={() => applyPreset(p)} style={{
                  padding: '4px 12px', borderRadius: 20, cursor: 'pointer',
                  font: '500 11px/16px var(--ss-font-sans)',
                  border: `1px solid ${active ? 'var(--ss-darkseagreen-500)' : 'var(--ss-border)'}`,
                  background: active ? 'var(--ss-darkseagreen-500)' : 'var(--ss-bg)',
                  color: active ? '#fff' : 'var(--ss-slate)',
                }}>{p.label}</button>
              );
            })}
          </div>

          {SPECIES_GROUPS.map(group => (
            <div key={group.label}>
              <div style={{ font: '500 11px/16px var(--ss-font-sans)', color: 'var(--ss-gray-3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8, marginTop: 14 }}>
                {group.label}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 10px', marginBottom: 4 }}>
                {group.species.map(sp => {
                  const on = trophySpecies.includes(sp);
                  return (
                    <div key={sp} onClick={() => toggleSpecies(sp)} style={{
                      ...chipBase,
                      background: on ? 'var(--ss-darkseagreen-500)' : 'var(--ss-bg)',
                      borderColor: on ? 'var(--ss-darkseagreen-500)' : 'var(--ss-border)',
                      color: on ? '#fff' : 'var(--ss-ink)',
                    }}>
                      {on && <i className="fa-solid fa-check" style={{ fontSize: 10 }}/>}
                      {sp}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}

          {!isDefault && (
            <div style={{
              marginTop: 16, padding: '10px 14px', borderRadius: 8,
              background: 'var(--ss-orange-50, #fff7ed)', border: '1px solid var(--ss-orange-200, #fed7aa)',
              font: '400 12px/18px var(--ss-font-sans)', color: 'var(--ss-orange-700, #c2410c)',
              display: 'flex', alignItems: 'flex-start', gap: 8,
            }}>
              <i className="fa-solid fa-triangle-exclamation" style={{ marginTop: 2, flexShrink: 0 }}/>
              <span>Custom species active — metrics show <b>{trophySpecies.join(', ')}</b>. Default: Bluefin, Yellowfin, Yellowtail, Dorado.</span>
            </div>
          )}
        </div>

        <div style={card}>
          <div style={sectionTitle}>Per-Day Metric Calculation</div>
          <p style={sectionDesc}>Controls the denominator used when calculating fish per angler per day.</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {methods.map(m => (
              <label key={m.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
                <input type="radio" name="tripLengthMethod" value={m.id}
                       checked={tripLengthMethod === m.id} onChange={() => setMethod(m.id)}
                       style={{ marginTop: 3, accentColor: 'var(--ss-darkseagreen-500)', cursor: 'pointer' }}/>
                <div>
                  <div style={{ font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-ink)' }}>{m.label}</div>
                  <div style={{ font: '400 12px/16px var(--ss-font-sans)', color: 'var(--ss-slate)', marginTop: 2 }}>{m.sub}</div>
                </div>
              </label>
            ))}
          </div>
        </div>
      </React.Fragment>
    );
  }

  // ── Loading state ───────────────────────────────────────────────
  if (!loaded) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <i className="fa-solid fa-spinner fa-spin" style={{ fontSize: 24, color: 'var(--tb-lime)' }}/>
      </div>
    );
  }

  // ── Signed-out state ────────────────────────────────────────────
  if (!isSignedIn) {
    return (
      <div style={{ maxWidth: 640, margin: '0 auto', padding: '24px 16px' }}>
        <h2 style={{ font: '700 20px/28px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 24 }}>My Account</h2>

        <div style={{ ...card, textAlign: 'center', padding: '40px 32px' }}>
          <i className="fa-solid fa-circle-user" style={{ fontSize: 48, color: 'var(--tb-lime)', marginBottom: 16, display: 'block' }}/>
          <div style={{ font: '700 18px/26px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 8 }}>
            Sign in to access your settings
          </div>
          <p style={{ font: '400 13px/20px var(--ss-font-sans)', color: 'var(--ss-slate)', marginBottom: 24, maxWidth: 380, margin: '0 auto 24px' }}>
            Region preferences, trophy species, and display settings are saved to your account
            and sync across all your devices.
          </p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
            <button className="btn-acct-primary" onClick={signUp}>Create Free Account</button>
            <button className="btn-acct-secondary" onClick={signIn}>Sign In</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Signed-in state ─────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '24px 16px' }}>
      <h2 style={{ font: '700 20px/28px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 24 }}>Preferences</h2>

      <RegionSection/>
      <SpeciesSection/>

      {/* Favorite Boats — placeholder */}
      <div style={{ ...card, opacity: 0.6 }}>
        <div style={sectionTitle}>Favorite Boats</div>
        <p style={{ ...sectionDesc, marginBottom: 0 }}>
          Save boats to your favorites for quick access — coming soon.
        </p>
      </div>

      {/* Sign out */}
      <div style={{ marginTop: 24, display: 'flex', gap: 10 }}>
        <button onClick={resetAll} style={{
          background: 'none', border: '1px solid var(--ss-border)', borderRadius: 6,
          padding: '7px 16px', cursor: 'pointer',
          font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-slate)',
        }}>
          Reset to defaults
        </button>
        <button onClick={signOut} style={{
          background: 'none', border: '1px solid var(--ss-border)', borderRadius: 6,
          padding: '7px 16px', cursor: 'pointer',
          font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-slate)',
        }}>
          <i className="fa-solid fa-right-from-bracket" style={{ marginRight: 6, fontSize: 12 }}/>
          Sign Out
        </button>
      </div>
    </div>
  );
}
