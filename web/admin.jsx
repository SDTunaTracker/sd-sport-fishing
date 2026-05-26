// Admin Dashboard — internal only. Access via #admin (not linked in nav).
// Password protected via sessionStorage; change ADMIN_PASSWORD before deploy.
// Wrapped in an IIFE so none of its helpers (fmtN, hoursAgo, etc.) leak to
// the shared global scope and shadow names exported by ui.jsx.
(function () {
const ADMIN_PASSWORD = "StepStone1";

const { useState: useS, useEffect: useE, useCallback: useCB, Fragment } = React;
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

// ─── Helpers ─────────────────────────────────────────────────────────────────

// Reference point: when was data.js built? Fall back to Date.now() if missing.
const DATA_BUILD_TIME = (() => {
  try { return new Date(window.SD.META.lastScrape).getTime(); } catch { return Date.now(); }
})();

// Hours between isoStr and data.js build time (not browser clock).
// This prevents scrapers from appearing stale just because the page was
// loaded hours after data.js was generated.
function hoursAgo(isoStr) {
  if (!isoStr) return Infinity;
  return (DATA_BUILD_TIME - new Date(isoStr).getTime()) / 3_600_000;
}

function healthColor(isoStr, hasError) {
  if (hasError) return "red";
  const h = hoursAgo(isoStr);
  if (h < 2) return "green";
  if (h < 6) return "yellow";
  return "red";
}

function fmtN(n, dec = 0) {
  if (n == null) return "—";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: dec });
}

function fmtAgo(isoStr) {
  if (!isoStr) return "never";
  const h = hoursAgo(isoStr);
  if (h < 1) return `${Math.round(h * 60)}m ago`;
  if (h < 24) return `${h.toFixed(1)}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

function CopyBtn({ text }) {
  const [copied, setCopied] = useS(false);
  return (
    <button
      className={`adm-copy-btn${copied ? " copied" : ""}`}
      onClick={() => {
        navigator.clipboard.writeText(text).catch(() => {});
        setCopied(true);
        setTimeout(() => setCopied(false), 1800);
      }}
    >
      {copied ? "Copied!" : "Copy command"}
    </button>
  );
}

// ─── Password gate ────────────────────────────────────────────────────────────

function AdminLogin({ onAuth }) {
  const [pw, setPw] = useS("");
  const [err, setErr] = useS(false);
  const submit = () => {
    if (pw === ADMIN_PASSWORD) { onAuth(); }
    else { setErr(true); setPw(""); }
  };
  return (
    <div className="adm-login">
      <div className="adm-login-box">
        <h2>Admin Dashboard</h2>
        <p>Internal use only — direct URL access</p>
        <input
          type="password"
          placeholder="Password"
          className={err ? "err" : ""}
          value={pw}
          autoFocus
          onChange={e => { setPw(e.target.value); setErr(false); }}
          onKeyDown={e => e.key === "Enter" && submit()}
        />
        {err && <div className="adm-login-error">Incorrect password</div>}
        <button className="adm-login-btn" onClick={submit}>Sign in</button>
      </div>
    </div>
  );
}

// ─── Section 1 — Scraper Health ───────────────────────────────────────────────

function ScraperCard({ name, runs }) {
  const last = runs?.[0];
  const lastAt = last?.at;
  const lastErr = last?.status === "error" ? last.error : null;
  const color = healthColor(lastAt, !!lastErr);
  const tripsToday = (runs || []).filter(r => r.at?.startsWith(new Date().toISOString().slice(0, 10)))
    .reduce((s, r) => s + (r.kept || 0), 0);
  const tripsWeek = (runs || []).reduce((s, r) => s + (r.kept || 0), 0);

  return (
    <div className="adm-card">
      <div className="adm-card-title">
        <span className={`adm-dot ${color}`}/>
        {name}
        <span style={{ marginLeft: "auto" }}>
          <span className={`adm-status-chip ${color}`}>
            {color === "green" ? "Healthy" : color === "yellow" ? "Stale" : "Issue"}
          </span>
        </span>
      </div>
      <div className="adm-card-sub">{lastAt ? fmtAgo(lastAt) : "No runs recorded"}</div>
      <div className="adm-stat-row"><span className="lbl">Last run</span><span className="vl">{lastAt ? lastAt.slice(0, 16).replace("T", " ") : "—"}</span></div>
      <div className="adm-stat-row"><span className="lbl">Trips added today</span><span className="vl">{tripsToday}</span></div>
      <div className="adm-stat-row"><span className="lbl">Trips (last 10 runs)</span><span className="vl">{tripsWeek}</span></div>
      <div className="adm-stat-row"><span className="lbl">Last seen</span><span className="vl">{last ? `${last.seen} parsed` : "—"}</span></div>
      {lastErr && (
        <div style={{ marginTop: 8, padding: "6px 8px", background: "rgba(239,68,68,0.1)", borderRadius: 6, color: "#F87171", fontSize: 11 }}>
          {lastErr}
        </div>
      )}
    </div>
  );
}

function SSTCard({ sstLog }) {
  const lastDate = sstLog?.length ? sstLog.reduce((a, b) => a.date > b.date ? a : b).date : null;
  const color = lastDate ? healthColor(lastDate + "T12:00:00Z", false) : "red";
  return (
    <div className="adm-card">
      <div className="adm-card-title">
        <span className={`adm-dot ${color}`}/>
        SST Fetcher (NOAA ERDDAP)
        <span style={{ marginLeft: "auto" }}>
          <span className={`adm-status-chip ${color}`}>
            {color === "green" ? "Current" : color === "yellow" ? "Stale" : sstLog?.length ? "Lagged" : "No data"}
          </span>
        </span>
      </div>
      <div className="adm-card-sub">MUR SST jplMURSST41 — 3–6 day data lag expected</div>
      {(sstLog || []).map(s => (
        <div key={s.location} className="adm-stat-row">
          <span className="lbl">{s.location}</span>
          <span className="vl">{s.sstF != null ? `${s.sstF.toFixed(1)}°F` : "—"} <span style={{ color: "#64748B", fontWeight: 400 }}>({s.date})</span></span>
        </div>
      ))}
    </div>
  );
}

function Section1({ scrapeLog, sstLog }) {
  const sources = ["H&M Landing", "Fisherman's Landing", "Seaforth Sportfishing", "Point Loma Sportfishing"];
  return (
    <div className="adm-section">
      <div className="adm-section-title">Scraper Health</div>
      <div className="adm-cards">
        {sources.map(s => <ScraperCard key={s} name={s} runs={scrapeLog[s]} />)}
        <SSTCard sstLog={sstLog} />
      </div>
    </div>
  );
}

// ─── Section 2 — Database Stats ───────────────────────────────────────────────

function BarChart({ data, labelKey, valueKey, color = "var(--tb-accent)" }) {
  const max = Math.max(...data.map(d => d[valueKey]), 1);
  return (
    <div className="adm-bars">
      {data.map(d => (
        <div key={d[labelKey]} className="adm-bar-row">
          <div className="adm-bar-label" title={d[labelKey]}>{d[labelKey]}</div>
          <div className="adm-bar-track">
            <div className="adm-bar-fill" style={{ width: `${(d[valueKey] / max * 100).toFixed(1)}%`, background: color }} />
          </div>
          <div className="adm-bar-val">{fmtN(d[valueKey])}</div>
        </div>
      ))}
    </div>
  );
}

function Section2({ dbStats }) {
  const s = dbStats || {};
  const unknowns = s.unknownSpecies || [];
  return (
    <div className="adm-section">
      <div className="adm-section-title">Database Stats</div>
      <div className="adm-kpis">
        <div className="adm-kpi"><div className="k">Full-Day Trips</div><div className="v">{fmtN(s.totalTrips)}</div></div>
        <div className="adm-kpi"><div className="k">Half-Day Trips</div><div className="v">{fmtN(s.halfDayTrips)}</div></div>
        <div className="adm-kpi"><div className="k">Total Anglers</div><div className="v">{fmtN(s.totalAnglers)}</div></div>
        <div className="adm-kpi"><div className="k">Total Trophy Fish</div><div className="v">{fmtN(s.totalTuna)}</div></div>
        <div className="adm-kpi"><div className="k">Earliest Record</div><div className="v" style={{ fontSize: 16 }}>{s.earliestDate || "—"}</div></div>
        <div className="adm-kpi"><div className="k">Latest Record</div><div className="v" style={{ fontSize: 16 }}>{s.latestDate || "—"}</div></div>
        <div className="adm-kpi"><div className="k">Unknown Species</div><div className="v">{fmtN(unknowns.length)}<span className="u"> types</span></div></div>
        <div className="adm-kpi"><div className="k">New This Week</div><div className="v" style={{ color: s.newSpeciesThisWeek ? "#FBBF24" : "#34D399" }}>{fmtN(s.newSpeciesThisWeek)}</div></div>
      </div>

      <div className="adm-two-col" style={{ gap: 16 }}>
        <div className="adm-card">
          <div className="adm-card-title" style={{ marginBottom: 12 }}>Trips by Landing</div>
          <BarChart data={s.byLanding || []} labelKey="landing" valueKey="count" />
        </div>
        <div className="adm-card">
          <div className="adm-card-title" style={{ marginBottom: 12 }}>Trips by Year</div>
          <BarChart data={s.byYear || []} labelKey="year" valueKey="count" color="#34D399" />
        </div>
      </div>

      {unknowns.length > 0 && (
        <div className="adm-card" style={{ marginTop: 16 }}>
          <div className="adm-card-title" style={{ marginBottom: 12 }}>Unknown Species Log <span style={{ fontWeight: 400, color: "#64748B", fontSize: 11 }}>— not mapped to any DB column</span></div>
          <div style={{ maxHeight: 260, overflowY: "auto" }}>
            <table className="adm-species-table">
              <thead><tr><th>Species Name</th><th>Total Count</th><th>Last Seen</th></tr></thead>
              <tbody>
                {unknowns.slice(0, 30).map(u => (
                  <tr key={u.species}>
                    <td>{u.species}</td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>{fmtN(u.total)}</td>
                    <td style={{ color: "#64748B" }}>{u.lastSeen}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Section 3 — Forecast Model Performance ───────────────────────────────────

function MonthlyHeatmap({ byMonth }) {
  if (!byMonth) return <div style={{ color: "#64748B", fontSize: 12 }}>No monthly data — run backtest first.</div>;
  return (
    <div className="adm-month-grid">
      {MONTHS.map((mn, i) => {
        const mae = byMonth[String(i + 1)];
        const cls = mae == null ? "" : mae < 1.5 ? "good" : mae < 2.5 ? "ok" : "bad";
        return (
          <div key={mn} className={`adm-month-cell ${cls}`}>
            <div className="mn">{mn}</div>
            <div className="mv">{mae != null ? mae.toFixed(2) : "—"}</div>
          </div>
        );
      })}
    </div>
  );
}

function WeightsDisplay({ weights }) {
  const entries = [
    { key: "sst_weight", label: "SST Weight", max: 2.0 },
    { key: "anomaly_weight", label: "Anomaly Weight", max: 2.0 },
    { key: "moon_weight", label: "Moon Weight", max: 1.0 },
    { key: "wind_weight", label: "Wind Weight", max: 1.0 },
  ];
  return (
    <div className="adm-weights">
      {entries.map(({ key, label, max }) => {
        const val = weights?.[key];
        const pct = val != null ? Math.min((val / max) * 100, 100) : 0;
        return (
          <div key={key} className="adm-weight-row">
            <div className="adm-weight-label">{label}</div>
            <div className="adm-weight-bar-track">
              <div className="adm-weight-bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <div className="adm-weight-val">{val != null ? val.toFixed(3) : "—"}</div>
          </div>
        );
      })}
    </div>
  );
}

const WEIGHT_KEYS = [
  { key: "sst_weight",    label: "SST" },
  { key: "anomaly_weight",label: "Anomaly" },
  { key: "wind_weight",   label: "Wind" },
  { key: "moon_weight",   label: "Moon" },
];

function WeightHistory({ history }) {
  if (!history || history.length === 0) return null;
  // history is newest-first; compute deltas vs the next-older row
  return (
    <div className="adm-card" style={{ marginTop: 16 }}>
      <div className="adm-card-title" style={{ marginBottom: 12 }}>
        Weight History
        <span style={{ fontWeight: 400, color: "#64748B", fontSize: 11, marginLeft: 8 }}>
          — Δ vs previous run · last {history.length} recalibrations
        </span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="adm-pred-table">
          <thead>
            <tr>
              <th>Run Date</th>
              <th>Window</th>
              <th style={{ textAlign: "right" }}>MAE</th>
              <th style={{ textAlign: "right" }}>Dir%</th>
              {WEIGHT_KEYS.map(w => (
                <th key={w.key} style={{ textAlign: "right" }}>{w.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {history.map((row, i) => {
              const prev = history[i + 1];
              const w     = row.weights  || {};
              const prevW = prev?.weights || {};
              function delta(cur, old) {
                if (cur == null || old == null) return null;
                return cur - old;
              }
              function fmtDelta(d) {
                if (d == null) return null;
                const color = Math.abs(d) < 0.005 ? "#64748B"
                            : d > 0 ? "#34D399" : "#F87171";
                return <span style={{ color, fontSize: 10, marginLeft: 3 }}>
                  {d > 0 ? "+" : ""}{d.toFixed(3)}
                </span>;
              }
              const dMae = delta(row.mae, prev?.mae);
              const dDir = delta(row.direction_accuracy, prev?.direction_accuracy);
              return (
                <tr key={row.run_date} style={{ opacity: i === 0 ? 1 : 0.8 }}>
                  <td style={{ fontWeight: i === 0 ? 600 : 400 }}>
                    {row.run_date}
                    {i === 0 && <span style={{ marginLeft: 6, fontSize: 10, color: "#38BDF8" }}>current</span>}
                  </td>
                  <td style={{ color: "#64748B", fontSize: 11 }}>
                    {row.date_range_start?.slice(0, 7)} → {row.date_range_end?.slice(0, 7)}
                  </td>
                  <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {row.mae?.toFixed(3)}
                    {fmtDelta(dMae != null ? -dMae : null) /* lower MAE = better → invert color */}
                  </td>
                  <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {row.direction_accuracy?.toFixed(1)}%
                    {fmtDelta(dDir)}
                  </td>
                  {WEIGHT_KEYS.map(wk => {
                    const val  = w[wk.key];
                    const d    = delta(val, prevW[wk.key]);
                    return (
                      <td key={wk.key} style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                        {val?.toFixed(3) ?? "—"}
                        {fmtDelta(d)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Section3({ backtest, weights, history }) {
  const bt = backtest || {};
  const lastRunDate = bt.run_date;
  const daysAgo = lastRunDate
    ? Math.round((Date.now() - new Date(lastRunDate).getTime()) / 86_400_000)
    : null;
  const nextOpt = daysAgo != null ? Math.max(0, 30 - daysAgo) : null;

  return (
    <div className="adm-section">
      <div className="adm-section-title">Forecast Model Performance</div>
      <div className="adm-kpis">
        <div className="adm-kpi">
          <div className="k">Direction Accuracy</div>
          <div className="v" style={{ color: bt.direction_accuracy >= 65 ? "#34D399" : bt.direction_accuracy >= 50 ? "#FBBF24" : "#F87171" }}>
            {bt.direction_accuracy != null ? `${bt.direction_accuracy.toFixed(1)}%` : "—"}
          </div>
          <div className="u">target: &gt;65%</div>
        </div>
        <div className="adm-kpi">
          <div className="k">Mean Abs. Error</div>
          <div className="v" style={{ color: bt.mae < 1.5 ? "#34D399" : bt.mae < 2.5 ? "#FBBF24" : "#F87171" }}>
            {bt.mae != null ? bt.mae.toFixed(3) : "—"}
          </div>
          <div className="u">target: &lt;1.5</div>
        </div>
        <div className="adm-kpi">
          <div className="k">RMSE</div>
          <div className="v">{bt.rmse != null ? bt.rmse.toFixed(3) : "—"}</div>
        </div>
        <div className="adm-kpi">
          <div className="k">Backtest Days</div>
          <div className="v">{fmtN(bt.total_days)}</div>
          <div className="u">{bt.date_range_start} → {bt.date_range_end?.slice(2)}</div>
        </div>
        <div className="adm-kpi">
          <div className="k">Last Optimized</div>
          <div className="v" style={{ fontSize: 16 }}>{lastRunDate || "—"}</div>
          <div className="u">{daysAgo != null ? `${daysAgo}d ago` : ""}</div>
        </div>
        <div className="adm-kpi">
          <div className="k">Next Recalibration</div>
          <div className="v" style={{ fontSize: 20, color: nextOpt === 0 ? "#F87171" : "#CBD5E1" }}>
            {nextOpt != null ? (nextOpt === 0 ? "Overdue" : `${nextOpt}d`) : "—"}
          </div>
          <div className="u">30-day cycle</div>
        </div>
      </div>

      <div className="adm-two-col" style={{ gap: 16 }}>
        <div className="adm-card">
          <div className="adm-card-title" style={{ marginBottom: 12 }}>MAE by Month <span style={{ fontWeight: 400, color: "#64748B", fontSize: 11 }}>(green &lt;1.5 · yellow &lt;2.5 · red ≥2.5)</span></div>
          <MonthlyHeatmap byMonth={bt.by_month} />
        </div>
        <div className="adm-card">
          <div className="adm-card-title" style={{ marginBottom: 14 }}>Factor Weights (current)</div>
          <WeightsDisplay weights={weights} />
        </div>
      </div>

      <WeightHistory history={history} />
    </div>
  );
}

// ─── Section 4 — Recent Predictions vs Actuals ───────────────────────────────

function PredRow({ p }) {
  const cls = p.error <= 1.5 ? "good" : p.error <= 2.5 ? "ok" : "bad";
  const errColor = cls === "good" ? "#34D399" : cls === "ok" ? "#FBBF24" : "#F87171";
  const icon = cls === "good" ? "✅" : cls === "ok" ? "⚠️" : "❌";
  return (
    <tr className={cls}>
      <td className="date-col">{p.date}</td>
      <td className="num">{p.predicted?.toFixed(1)}</td>
      <td className="num">{p.actualTpa?.toFixed(3)}</td>
      <td className="num">{p.actualRating?.toFixed(1)}</td>
      <td>
        <span className="err-chip" style={{ background: `${errColor}18`, color: errColor }}>
          {icon} {p.error?.toFixed(2)}
        </span>
      </td>
      <td style={{ color: "#64748B" }}>{p.nBoats} boats</td>
    </tr>
  );
}

function Section4({ preds }) {
  const sorted = [...(preds || [])].sort((a, b) => b.date.localeCompare(a.date));
  const good = sorted.filter(p => p.error <= 1.5).length;
  const pctGood = sorted.length ? Math.round(good / sorted.length * 100) : 0;

  return (
    <div className="adm-section">
      <div className="adm-section-title">
        Recent Predictions vs Actuals — last {sorted.length} days with sufficient data
        {sorted.length > 0 && (
          <span style={{ marginLeft: 12, fontWeight: 400, textTransform: "none", letterSpacing: 0, color: pctGood >= 50 ? "#34D399" : "#FBBF24" }}>
            {pctGood}% within 1.5 pts
          </span>
        )}
      </div>
      {sorted.length === 0 ? (
        <div className="adm-placeholder">No overlapping SST + trip data in the last 14 days.<br/>Run backtest to populate historical_conditions.</div>
      ) : (
        <div className="adm-card" style={{ padding: 0 }}>
          <div style={{ overflowX: "auto" }}>
            <table className="adm-pred-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Predicted</th>
                  <th>Actual TPA</th>
                  <th>Actual Rating</th>
                  <th>Error</th>
                  <th>N</th>
                </tr>
              </thead>
              <tbody>{sorted.map(p => <PredRow key={p.date} p={p} />)}</tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Section 5 — User Stats placeholder ──────────────────────────────────────

function Section5() {
  return (
    <div className="adm-section">
      <div className="adm-section-title">User Stats</div>
      <div className="adm-card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24 }}>
        <div>
          <div className="adm-card-title" style={{ marginBottom: 6 }}>Google Analytics — G-6QDTY73V37</div>
          <div style={{ font: "400 12px/18px var(--ss-font-sans)", color: "#64748B", maxWidth: 480 }}>
            Sessions, page views, user counts, countries, devices, and real-time visitors are all available in the GA4 dashboard.
          </div>
        </div>
        <a
          href="https://analytics.google.com/"
          target="_blank"
          rel="noopener noreferrer"
          style={{ flexShrink: 0, padding: "9px 20px", background: "rgba(56,189,248,0.12)", color: "var(--tb-accent)", border: "1px solid rgba(56,189,248,0.2)", borderRadius: 7, font: "600 13px/18px var(--ss-font-sans)", textDecoration: "none", whiteSpace: "nowrap" }}
        >
          Open GA4 Dashboard ↗
        </a>
      </div>
    </div>
  );
}

// ─── Section 6 — Quick Actions ────────────────────────────────────────────────

const ACTIONS = [
  {
    title: "Run Scraper Now",
    desc: "Scrapes all 4 landings, updates schedules, fetches SST, and regenerates data.js.",
    cmd: ".venv\\Scripts\\python.exe -m src.main",
  },
  {
    title: "Fetch SST Only",
    desc: "Runs the export pipeline without scraping trip data. Useful to refresh data.js.",
    cmd: ".venv\\Scripts\\python.exe -m src.main --export-only",
  },
  {
    title: "Backfill SST (90 days)",
    desc: "Fetches 90 days of SST history from NOAA ERDDAP for all 4 locations.",
    cmd: ".venv\\Scripts\\python.exe -m src.main --backfill-sst",
  },
  {
    title: "Run Backtest",
    desc: "Full 2-year backtest: extends SST, fetches wind/swell, computes model accuracy.",
    cmd: ".venv\\Scripts\\python.exe -m src.backtest --start 2024-01-01 --end 2026-05-24 --optimize --output backtest_report.json",
  },
  {
    title: "Re-optimize Weights",
    desc: "Runs the backtest with --optimize to recalibrate score breaks and factor weights.",
    cmd: ".venv\\Scripts\\python.exe -m src.backtest --no-extend-sst --optimize --output backtest_report.json",
  },
  {
    title: "Export Database Backup",
    desc: "Creates a timestamped copy of the SQLite database file.",
    cmd: "copy tracker.db tracker_backup_%date:~-4,4%%date:~-10,2%%date:~-7,2%.db",
  },
];

function ActionCard({ action }) {
  return (
    <div className="adm-action-card">
      <h4>{action.title}</h4>
      <p>{action.desc}</p>
      <div className="adm-action-cmd">{action.cmd}</div>
      <CopyBtn text={action.cmd} />
    </div>
  );
}

function Section6() {
  return (
    <div className="adm-section">
      <div className="adm-section-title">
        Quick Actions <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0, color: "#475569" }}>— copy command and run on the server</span>
      </div>
      <div className="adm-actions-grid">
        {ACTIONS.map(a => <ActionCard key={a.title} action={a} />)}
      </div>
    </div>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────

function AdminView() {
  const [authed, setAuthed] = useS(
    () => sessionStorage.getItem("admin_auth") === "1"
  );

  if (!authed) {
    return <AdminLogin onAuth={() => { sessionStorage.setItem("admin_auth", "1"); setAuthed(true); }} />;
  }

  const admin = window.SD?.ADMIN || {};
  const meta  = window.SD?.META  || {};

  return (
    <div className="adm-root">
      <header className="adm-header">
        <div className="adm-header-inner">
          <div>
            <span className="adm-title">The Tuna Tracker</span>
            <span className="adm-badge">Admin</span>
          </div>
          <div className="adm-header-meta">
            data.js built: {meta.lastScrape ? meta.lastScrape.slice(0, 16).replace("T", " ") + " UTC" : "unknown"}
            <button
              className="adm-btn-ghost"
              onClick={() => { sessionStorage.removeItem("admin_auth"); setAuthed(false); }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="adm-body">
        <Section1 scrapeLog={admin.scrapeLog || {}} sstLog={admin.sstLog || []} />
        <Section2 dbStats={admin.dbStats} />
        <Section3 backtest={admin.backtestResults} weights={admin.weights} history={admin.backtestHistory} />
        <Section4 preds={admin.recentPredictions} />
        <Section5 />
        <Section6 />
      </div>
    </div>
  );
}

Object.assign(window, { AdminView });
})(); // end IIFE
