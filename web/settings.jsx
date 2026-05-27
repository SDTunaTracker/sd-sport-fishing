// Settings view — trophy species + trip length methodology
const DEFAULT_TROPHY_SPECIES = ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado'];

const SPECIES_GROUPS = [
  {
    label: 'Offshore / Pelagic',
    species: ['Bluefin', 'Yellowfin', 'Yellowtail', 'Dorado', 'Skipjack', 'Bigeye', 'Albacore', 'Bonito', 'Barracuda'],
  },
  {
    label: 'Inshore / Bottom',
    species: ['White Sea Bass', 'Halibut', 'Calico Bass', 'Sand Bass', 'Rockfish', 'Lingcod', 'Sheephead', 'Whitefish'],
  },
];

const ALL_SPECIES = SPECIES_GROUPS.flatMap(g => g.species);

const PRESETS = [
  { label: 'Tuna Only',   species: ['Bluefin', 'Yellowfin', 'Skipjack', 'Bigeye', 'Albacore'] },
  { label: 'All Pelagic', species: SPECIES_GROUPS[0].species },
  { label: 'Inshore Mix', species: ['White Sea Bass', 'Halibut', 'Calico Bass', 'Yellowtail'] },
  { label: 'All Species', species: ALL_SPECIES },
];

const SETTINGS_KEY = 'sd_user_settings';

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...defaultSettings(), ...JSON.parse(raw) };
  } catch(e) {}
  return defaultSettings();
}

function defaultSettings() {
  return {
    trophySpecies: [...DEFAULT_TROPHY_SPECIES],
    tripLengthMethod: 'rounded',
  };
}

function saveSettings(s) {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); } catch(e) {}
}

function isDefaultSpecies(selected) {
  if (selected.length !== DEFAULT_TROPHY_SPECIES.length) return false;
  return DEFAULT_TROPHY_SPECIES.every(sp => selected.includes(sp));
}

function SettingsView({ settings, onSettingsChange }) {
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

  function resetDefaults() {
    onSettingsChange(defaultSettings());
  }

  const isDefault = isDefaultSpecies(trophySpecies);

  const sectionStyle = {
    background: 'var(--ss-surface)',
    border: '1px solid var(--ss-border)',
    borderRadius: 10,
    padding: '20px 24px',
    marginBottom: 16,
  };
  const labelStyle = {
    font: '600 13px/20px var(--ss-font-sans)',
    color: 'var(--ss-ink)',
    marginBottom: 8,
    display: 'block',
  };
  const groupLabelStyle = {
    font: '500 11px/16px var(--ss-font-sans)',
    color: 'var(--ss-gray-3)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginBottom: 8,
    marginTop: 16,
    display: 'block',
  };
  const descStyle = {
    font: '400 12px/18px var(--ss-font-sans)',
    color: 'var(--ss-slate)',
    marginBottom: 12,
  };
  const chipBase = {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '5px 12px', borderRadius: 20, cursor: 'pointer',
    font: '500 12px/16px var(--ss-font-sans)',
    border: '1px solid var(--ss-border)',
    userSelect: 'none',
    transition: 'background 0.15s, border-color 0.15s',
  };
  const radioRowStyle = { display: 'flex', flexDirection: 'column', gap: 10 };
  const radioItemStyle = {
    display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer',
  };
  const radioLabelStyle = { font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-ink)' };
  const radioSubStyle = { font: '400 12px/16px var(--ss-font-sans)', color: 'var(--ss-slate)', marginTop: 2 };

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
    <div style={{ maxWidth: 620, margin: '0 auto', padding: '24px 16px' }}>
      <h2 style={{ font: '700 20px/28px var(--ss-font-sans)', color: 'var(--ss-ink)', marginBottom: 24 }}>
        Settings
      </h2>

      {/* Trophy Species */}
      <div style={sectionStyle}>
        <span style={labelStyle}>Trophy Species</span>
        <p style={descStyle}>
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
            <span style={groupLabelStyle}>{group.label}</span>
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

        {/* Non-default warning banner */}
        {!isDefault && (
          <div style={{
            marginTop: 16,
            padding: '10px 14px',
            borderRadius: 8,
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

      {/* Trip Length Methodology */}
      <div style={sectionStyle}>
        <span style={labelStyle}>Per-Day Metric Calculation</span>
        <p style={descStyle}>
          Controls the denominator used when calculating fish per angler per day.
        </p>
        <div style={radioRowStyle}>
          {methods.map(m => (
            <label key={m.id} style={radioItemStyle}>
              <input type="radio" name="tripLengthMethod" value={m.id}
                     checked={tripLengthMethod === m.id}
                     onChange={() => setMethod(m.id)}
                     style={{ marginTop: 3, accentColor: 'var(--ss-darkseagreen-500)' }}/>
              <div>
                <div style={radioLabelStyle}>{m.label}</div>
                <div style={radioSubStyle}>{m.sub}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Reset */}
      <button onClick={resetDefaults}
              style={{
                background: 'none', border: '1px solid var(--ss-border)',
                borderRadius: 6, padding: '7px 16px', cursor: 'pointer',
                font: '500 13px/20px var(--ss-font-sans)', color: 'var(--ss-slate)',
              }}>
        Reset to defaults
      </button>
    </div>
  );
}
