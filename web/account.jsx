// account.jsx — My Account page
// Region preferences, trophy species, display settings.
// Auth (Clerk) integration slots in here once keys are configured.

function MyAccountView({ settings, onSettingsChange, regions, onRegionsDirect }) {
  const { useState: useS } = React;

  const REGIONS_DEF = window.REGIONS || [
    { id: 'san_diego', label: 'San Diego',                    short: 'SD'    },
    { id: 'oc_la',     label: 'Orange County / Los Angeles',  short: 'OC/LA' },
  ];

  const primary   = regions[0] || 'san_diego';
  const secondary = REGIONS_DEF.find(r => r.id !== primary);
  const hasSecondary = !!(secondary && regions.includes(secondary.id));

  function setPrimary(id) {
    if (hasSecondary) {
      const sec = regions.find(r => r !== id);
      onRegionsDirect([id, sec]);
    } else {
      onRegionsDirect([id]);
    }
  }

  function toggleSecondary() {
    if (!secondary) return;
    if (hasSecondary) {
      onRegionsDirect([primary]);
    } else {
      onRegionsDirect([primary, secondary.id]);
    }
  }

  const { trophySpecies, tripLengthMethod } = settings;

  function toggleSpecies(sp) {
    const next = trophySpecies.includes(sp)
      ? trophySpecies.filter(s => s !== sp)
      : [...trophySpecies, sp];
    if (next.length === 0) return;
    onSettingsChange({ ...settings, trophySpecies: next });
  }

  function applyPreset(preset) {
    onSettingsChange({ ...settings, trophySpecies: [...preset.species] });
  }

  function setMethod(m) {
    onSettingsChange({ ...settings, tripLengthMethod: m });
  }

  const isDefault = isDefaultSpecies(trophySpecies);

  const card = {
    background: 'var(--ss-surface)',
    border: '1px solid var(--ss-border)',
    borderRadius: 10,
    padding: '20px 24px',
    marginBottom: 16,
  };

  const sectionTitle = {
    font: '600 14px/20px var(--ss-font-sans)',
    color: 'var(--ss-ink)',
    marginBottom: 4,
  };

  const sectionDesc = {
    font: '400 12px/18px var(--ss-font-sans)',
    color: 'var(--ss-slate)',
    marginBottom: 16,
  };

  const fieldLabel = {
    font: '600 11px/14px var(--ss-font-sans)',
    color: 'var(--ss-gray-3)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginBottom: 10,
    display: 'block',
  };

  const radioRow = {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '7px 0', cursor: 'pointer',
    font: '500 13px/20px var(--ss-font-sans)',
    color: 'var(--ss-ink)',
  };

  const chipBase = {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '5px 12px', borderRadius: 20, cursor: 'pointer',
    font: '500 12px/16px var(--ss-font-sans)',
    border: '1px solid var(--ss-border)',
    userSelect: 'none',
    transition: 'background 0.15s, border-color 0.15s',
  };

  const methods = [
    {
      id: 'rounded',
      label: 'Rounded (recommended)',
      sub: 'Full Day, Overnight, and 1.5-day trips all count as 1 day. 2.5-day counts as 2, etc.',
    },
    {
      id: 'actual',
      label: 'Actual trip length',
      sub: 'Full Day = 0.75, Overnight = 1.0, 1.5-day = 1.5, 2.5-day = 2.5, etc.',
    },
  ];

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '24px 16px' }}>
      <h2 style={{ font: '700 20px/28px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 24 }}>
        My Account
      </h2>

      {/* ── Section 1: Profile / Auth placeholder ── */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <i className="fa-solid fa-circle-user" style={{ fontSize: 44, color: 'var(--tb-lime)', flexShrink: 0, marginTop: 2 }}></i>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ font: '600 15px/22px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 4 }}>
              Continuing as guest
            </div>
            <div style={{ font: '400 12px/18px var(--ss-font-sans)', color: 'var(--ss-slate)', marginBottom: 14 }}>
              Your preferences are saved in this browser. Sign in to sync across devices and unlock future Pro features.
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button disabled style={{
                padding: '8px 18px', borderRadius: 6,
                background: 'var(--tb-deep)', color: '#fff',
                border: 'none', font: '600 13px/16px var(--ss-font-sans)',
                cursor: 'not-allowed', opacity: 0.45,
              }}>
                Sign In
              </button>
              <button disabled style={{
                padding: '8px 18px', borderRadius: 6,
                background: 'none', color: 'var(--tb-deep)',
                border: '1px solid var(--tb-deep)',
                font: '600 13px/16px var(--ss-font-sans)',
                cursor: 'not-allowed', opacity: 0.45,
              }}>
                Create Account
              </button>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 10px',
                background: 'var(--ss-bg-muted)', borderRadius: 20,
                font: '500 11px/14px var(--ss-font-sans)', color: 'var(--ss-gray-3)',
              }}>
                <i className="fa-solid fa-clock" style={{ fontSize: 9 }}></i>
                Coming soon
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Section 2: Region Preferences ── */}
      <div style={card}>
        <div style={sectionTitle}>Region Preferences</div>
        <p style={sectionDesc}>
          Choose which sportfishing region's data to display across all views.
        </p>

        <span style={fieldLabel}>Primary Region</span>
        {REGIONS_DEF.map(reg => (
          <label key={reg.id} style={{ ...radioRow, cursor: 'pointer' }}>
            <input
              type="radio"
              name="primaryRegion"
              value={reg.id}
              checked={primary === reg.id}
              onChange={() => setPrimary(reg.id)}
              style={{ accentColor: 'var(--ss-darkseagreen-500)', width: 15, height: 15, cursor: 'pointer', flexShrink: 0 }}
            />
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
              <input
                type="checkbox"
                checked={hasSecondary}
                onChange={toggleSecondary}
                style={{
                  accentColor: 'var(--ss-darkseagreen-500)',
                  width: 15, height: 15, marginTop: 3,
                  cursor: 'pointer', flexShrink: 0,
                }}
              />
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

      {/* ── Section 3: Trophy Species ── */}
      <div style={card}>
        <div style={sectionTitle}>Trophy Species</div>
        <p style={sectionDesc}>
          Choose which species count toward the "per angler per day" metric.
          All charts and leaderboards update instantly.
        </p>

        {/* Quick-select presets */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: 16 }}>
          {PRESETS.map(p => {
            const active = p.species.length === trophySpecies.length &&
              p.species.every(sp => trophySpecies.includes(sp));
            return (
              <button key={p.label} onClick={() => applyPreset(p)}
                      style={{
                        padding: '4px 12px', borderRadius: 20, cursor: 'pointer',
                        font: '500 11px/16px var(--ss-font-sans)',
                        border: `1px solid ${active ? 'var(--ss-darkseagreen-500)' : 'var(--ss-border)'}`,
                        background: active ? 'var(--ss-darkseagreen-500)' : 'var(--ss-bg)',
                        color: active ? '#fff' : 'var(--ss-slate)',
                      }}>
                {p.label}
              </button>
            );
          })}
        </div>

        {/* Species chips by group */}
        {SPECIES_GROUPS.map(group => (
          <div key={group.label}>
            <div style={{
              font: '500 11px/16px var(--ss-font-sans)', color: 'var(--ss-gray-3)',
              textTransform: 'uppercase', letterSpacing: '0.05em',
              marginBottom: 8, marginTop: 14,
            }}>
              {group.label}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 10px', marginBottom: 4 }}>
              {group.species.map(sp => {
                const on = trophySpecies.includes(sp);
                return (
                  <div key={sp}
                       onClick={() => toggleSpecies(sp)}
                       style={{
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

        {/* Non-default warning */}
        {!isDefault && (
          <div style={{
            marginTop: 16, padding: '10px 14px', borderRadius: 8,
            background: 'var(--ss-orange-50, #fff7ed)',
            border: '1px solid var(--ss-orange-200, #fed7aa)',
            font: '400 12px/18px var(--ss-font-sans)',
            color: 'var(--ss-orange-700, #c2410c)',
            display: 'flex', alignItems: 'flex-start', gap: 8,
          }}>
            <i className="fa-solid fa-triangle-exclamation" style={{ marginTop: 2, flexShrink: 0 }}/>
            <span>
              Custom species active — metrics show <b>{trophySpecies.join(', ')}</b>.
              Default is Bluefin, Yellowfin, Yellowtail, Dorado.
            </span>
          </div>
        )}
      </div>

      {/* ── Section 4: Per-Day Metric Calculation ── */}
      <div style={card}>
        <div style={sectionTitle}>Per-Day Metric Calculation</div>
        <p style={sectionDesc}>
          Controls the denominator used when calculating fish per angler per day.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {methods.map(m => (
            <label key={m.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
              <input type="radio" name="tripLengthMethod" value={m.id}
                     checked={tripLengthMethod === m.id}
                     onChange={() => setMethod(m.id)}
                     style={{ marginTop: 3, accentColor: 'var(--ss-darkseagreen-500)', cursor: 'pointer' }}/>
              <div>
                <div style={{ font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-ink)' }}>{m.label}</div>
                <div style={{ font: '400 12px/16px var(--ss-font-sans)', color: 'var(--ss-slate)', marginTop: 2 }}>{m.sub}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* ── Section 5: Display Preferences (future) ── */}
      <div style={{ ...card, opacity: 0.55 }}>
        <div style={sectionTitle}>Display Preferences</div>
        <p style={{ ...sectionDesc, marginBottom: 0 }}>
          Dark mode, email notifications, and privacy settings — available with account sign-in.
        </p>
      </div>

      {/* Reset all */}
      <button onClick={() => onSettingsChange(defaultSettings())}
              style={{
                background: 'none', border: '1px solid var(--ss-border)',
                borderRadius: 6, padding: '7px 16px', cursor: 'pointer',
                font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-slate)',
                marginTop: 4,
              }}>
        Reset to defaults
      </button>
    </div>
  );
}
