// account.jsx — My Account page with Clerk auth integration.
// Signed-out: shows sign-in CTAs + guest preferences.
// Signed-in: shows Clerk UserProfile + cloud-synced preferences.

function MyAccountView({ settings, onSettingsChange, regions, onRegionsDirect }) {
  const { useEffect, useState } = React;
  const { user, loaded, signIn, signUp, signOut, isSignedIn } = useAuth();

  const REGIONS_DEF = window.REGIONS || [
    { id: 'san_diego', label: 'San Diego',                   short: 'SD'    },
    { id: 'oc_la',     label: 'Orange County / Los Angeles', short: 'OC/LA' },
  ];

  const primary     = regions[0] || 'san_diego';
  const secondary   = REGIONS_DEF.find(r => r.id !== primary);
  const hasSecondary = !!(secondary && regions.includes(secondary.id));

  // Mount Clerk UserProfile widget when signed in (must be outside any conditional).
  useEffect(() => {
    if (!isSignedIn) return;
    const el = document.getElementById('clerk-user-profile');
    if (el && window.Clerk && el.childElementCount === 0) {
      window.Clerk.mountUserProfile(el);
    }
  }, [isSignedIn]);

  // ── Region helpers ──────────────────────────────────────────────
  function setPrimary(id) {
    const newRegions = hasSecondary ? [id, regions.find(r => r !== id)] : [id];
    onRegionsDirect(newRegions);
    window.setUserPref('primary_region', id);
  }

  function toggleSecondary() {
    if (!secondary) return;
    const newRegions = hasSecondary ? [primary] : [primary, secondary.id];
    onRegionsDirect(newRegions);
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
    window.setUserPref('primary_region', 'san_diego');
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

  // ── Region section (shared between signed-in / signed-out) ──────
  function RegionSection() {
    return (
      <div style={card}>
        <div style={sectionTitle}>Region Preferences</div>
        <p style={sectionDesc}>Choose which sportfishing region's data to display across all views.</p>

        <span style={fieldLabel}>Primary Region</span>
        {REGIONS_DEF.map(reg => (
          <label key={reg.id} style={{ ...radioRow, cursor: 'pointer' }}>
            <input type="radio" name="primaryRegion" value={reg.id}
                   checked={primary === reg.id}
                   onChange={() => setPrimary(reg.id)}
                   style={{ accentColor: 'var(--ss-darkseagreen-500)', width: 15, height: 15, cursor: 'pointer', flexShrink: 0 }}/>
            <span>{reg.label}</span>
            {reg.id === 'san_diego' && (
              <span style={{ font: '400 11px/14px var(--ss-font-sans)', color: 'var(--ss-gray-3)' }}>(default)</span>
            )}
          </label>
        ))}

        {secondary && (
          <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--ss-border)' }}>
            <span style={fieldLabel}>Additional Region</span>
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
              <input type="checkbox" checked={hasSecondary} onChange={toggleSecondary}
                     style={{ accentColor: 'var(--ss-darkseagreen-500)', width: 15, height: 15, marginTop: 3, cursor: 'pointer', flexShrink: 0 }}/>
              <div>
                <div style={{ font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-ink)' }}>
                  Include {secondary.label} data
                </div>
                <div style={{ font: '400 12px/16px var(--ss-font-sans)', color: 'var(--ss-slate)', marginTop: 2 }}>
                  Merge {secondary.short} boats and landings into your {primary === 'san_diego' ? 'San Diego' : 'OC/LA'} view
                </div>
              </div>
            </label>
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

        <div style={card}>
          <div style={{ font: '600 15px/22px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 8 }}>
            Sign in to sync your preferences
          </div>
          <p style={{ font: '400 13px/20px var(--ss-font-sans)', color: 'var(--ss-slate)', marginBottom: 16 }}>
            Save your region and trophy species settings to your account and access them on any device.
            Unlock Pro features as they launch.
          </p>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
            <button className="btn-acct-primary" onClick={signUp}>Create Free Account</button>
            <button className="btn-acct-secondary" onClick={signIn}>Sign In</button>
          </div>
          <div style={{ font: '400 12px/16px var(--ss-font-sans)', color: 'var(--ss-gray-3)', fontStyle: 'italic' }}>
            Continuing as guest — your settings save locally on this browser.
          </div>
        </div>

        <RegionSection/>
        <SpeciesSection/>

        <button onClick={resetAll} style={{
          background: 'none', border: '1px solid var(--ss-border)', borderRadius: 6,
          padding: '7px 16px', cursor: 'pointer',
          font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-slate)', marginTop: 4,
        }}>
          Reset to defaults
        </button>
      </div>
    );
  }

  // ── Signed-in state ─────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '24px 16px' }}>
      <h2 style={{ font: '700 20px/28px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 24 }}>My Account</h2>

      {/* Clerk UserProfile — email, password, connected accounts */}
      <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
        <div id="clerk-user-profile"/>
      </div>

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
