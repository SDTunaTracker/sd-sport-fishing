// Shared component library — all compose from A.1 design tokens (--tb-* CSS vars).
// IIFE rule: everything used cross-file must be window-exported at the bottom.

// ── Button ───────────────────────────────────────────────────────────────────
// Wraps the existing .btn CSS system.
// variant: 'primary' | 'secondary' | 'ghost' (default)
// size:    'sm' | 'icon' (default: normal)
function Button({ variant = 'ghost', size, onClick, children, className = '', disabled, style, type = 'button' }) {
  const cls = ['btn', variant, size === 'sm' ? 'sm' : size === 'icon' ? 'icon' : '', className]
    .filter(Boolean).join(' ');
  return (
    <button type={type} className={cls} onClick={onClick} disabled={disabled} style={style}>
      {children}
    </button>
  );
}

// ── Card ─────────────────────────────────────────────────────────────────────
// Settings/account-style section container.
function Card({ title, description, children, style, className = '' }) {
  return (
    <div className={`card-section${className ? ' ' + className : ''}`} style={style}>
      {title && <div className="card-section-title">{title}</div>}
      {description && <p className="card-section-desc">{description}</p>}
      {children}
    </div>
  );
}

// ── Chip ─────────────────────────────────────────────────────────────────────
// Toggle pill for species, filter, and preset selections.
function Chip({ active, onClick, children, style }) {
  return (
    <div className={`chip${active ? ' active' : ''}`} onClick={onClick} style={style}>
      {active && <i className="fa-solid fa-check" style={{ fontSize: 10 }} />}
      {children}
    </div>
  );
}

// ── FieldLabel ────────────────────────────────────────────────────────────────
function FieldLabel({ children, style }) {
  return <span className="field-label" style={style}>{children}</span>;
}

// ── SectionTitle / SectionDesc ────────────────────────────────────────────────
function SectionTitle({ children, style }) {
  return <div className="section-title" style={style}>{children}</div>;
}
function SectionDesc({ children, style }) {
  return <p className="section-desc" style={style}>{children}</p>;
}

// ── Badge ─────────────────────────────────────────────────────────────────────
// Non-interactive status/info pill.
function Badge({ children, style, className = '' }) {
  return (
    <span className={`badge${className ? ' ' + className : ''}`} style={style}>
      {children}
    </span>
  );
}

// ── StatTile ──────────────────────────────────────────────────────────────────
// Homepage stat bar tile — number + label.
function StatTile({ num, label, numColor, children }) {
  return (
    <div className="home-stat">
      <span className="home-stat-num" style={numColor ? { color: numColor } : undefined}>
        {num != null ? num : children}
      </span>
      <span className="home-stat-lbl">{label}</span>
    </div>
  );
}

// ── EmptyState ────────────────────────────────────────────────────────────────
function EmptyState({ children, className = '', style }) {
  return (
    <div className={`empty-state${className ? ' ' + className : ''}`} style={style}>
      {children || 'No data available'}
    </div>
  );
}

// ── Modal ─────────────────────────────────────────────────────────────────────
// Wraps existing .modal / .modal-backdrop CSS.
function Modal({ open, onClose, title, children, maxWidth = 1100 }) {
  if (!open) return null;
  function handleBackdrop(e) { if (e.target === e.currentTarget) onClose(); }
  return (
    <div className="modal-backdrop" onClick={handleBackdrop}>
      <div className="modal" style={{ maxWidth }}>
        <div className="modal-head">
          <span style={{ font: '600 16px/24px var(--tb-font-body)', color: 'var(--tb-ink)' }}>{title}</span>
          <button className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

// ── Toast ─────────────────────────────────────────────────────────────────────
// Notification strip anchored at page bottom. Wraps .rv-toast CSS.
function Toast({ visible, onDismiss, children }) {
  if (!visible) return null;
  return (
    <div className="rv-toast">
      <span className="rv-toast-text">{children}</span>
      <button className="rv-toast-close" onClick={onDismiss} aria-label="Dismiss">✕</button>
    </div>
  );
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
// CSS-only tooltip — no portal, no JS positioning.
// placement: 'top' (default) | 'bottom'
function Tooltip({ tip, children, placement = 'top' }) {
  return (
    <span className={`tooltip-wrap tooltip-${placement}`} data-tip={tip}>
      {children}
    </span>
  );
}

Object.assign(window, {
  Button, Card, Chip, FieldLabel, SectionTitle, SectionDesc,
  Badge, StatTile, EmptyState, Modal, Toast, Tooltip,
});
