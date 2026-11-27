const { useState: usePdState, useEffect: usePdEffect } = React;
const PD_TZ = "America/Los_Angeles";
const PD_DIRS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const PD_KIND = { bay: "Bay", harbour: "Harbour", lagoon: "Lagoon", coast: "Beach" };
function pdTime(iso, opts) {
  return new Date(iso).toLocaleString("en-US", Object.assign({ timeZone: PD_TZ }, opts));
}
function pdDir(d) {
  return d == null ? "" : PD_DIRS[Math.round((d % 360 + 360) % 360 / 22.5) % 16];
}
function pdKey(label) {
  return label ? label.toLowerCase() : "none";
}
function pdNow(hours) {
  const n = Date.now();
  return hours.find((h) => Date.parse(h.t) + 36e5 > n) || hours[hours.length - 1];
}
function pdClock(iso) {
  return pdTime(iso, { hour: "numeric", minute: "2-digit" }).replace(":00", "");
}
function pdWin(w) {
  return w ? `${pdClock(w.from)}\u2013${pdClock(w.to)}` : "";
}
function pdWetsuit(f) {
  if (f == null) return "";
  if (f >= 70) return "Boardshorts or spring suit";
  if (f >= 64) return "Spring suit or 2 mm";
  if (f >= 58) return "3/2 wetsuit";
  return "Full wetsuit, cold water";
}
function pdTideAt(t, ms) {
  const p = t && t.hourly || [];
  for (let k = 1; k < p.length; k++) {
    const t1 = Date.parse(p[k][0]);
    if (t1 >= ms) {
      const t0 = Date.parse(p[k - 1][0]);
      if (t0 > ms) return null;
      return p[k - 1][1] + (p[k][1] - p[k - 1][1]) * (ms - t0) / Math.max(1, t1 - t0);
    }
  }
  return null;
}
function pdArrow(toward) {
  return /* @__PURE__ */ React.createElement("i", { className: "pd-arr", style: { transform: `rotate(${toward}deg)` }, "aria-hidden": "true" }, "\u2191");
}
function usePaddleData() {
  const [st, setSt] = usePdState({ data: null, error: false });
  usePdEffect(() => {
    let alive = true;
    fetch("/api/v1/paddle_spots.json?h=" + (/* @__PURE__ */ new Date()).toISOString().slice(0, 13)).then((r) => r.ok ? r.json() : Promise.reject(r.status)).then((d) => {
      if (alive) setSt({ data: d, error: false });
    }).catch(() => {
      if (alive) setSt({ data: null, error: true });
    });
    return () => {
      alive = false;
    };
  }, []);
  return st;
}
function PaddlePill({ label }) {
  return /* @__PURE__ */ React.createElement("span", { className: `pd-pill pd-${pdKey(label)}` }, label || "\u2014");
}
function PaddleTiles({ pd, s, h }) {
  const ms = h ? Date.parse(h.t) : Date.now();
  const tides = (pd.tides || {})[s.tideStation];
  const tide = pdTideAt(tides, ms);
  const rising = tide != null && pdTideAt(tides, ms + 30 * 6e4) > tide;
  const next = (tides && tides.hilo || []).find((x) => Date.parse(x.t) > ms);
  const wt = pd.waterTemp;
  const wind = h && h.windKt != null;
  const cur = h && h.current;
  return /* @__PURE__ */ React.createElement("div", { className: "pd-tiles" }, /* @__PURE__ */ React.createElement("div", { className: "pd-tile" }, /* @__PURE__ */ React.createElement("span", { className: "pd-k" }, "Tide"), /* @__PURE__ */ React.createElement("b", null, tide != null ? `${tide.toFixed(1)} ft ${rising ? "\u2191" : "\u2193"}` : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "pd-s" }, next ? `${next.type === "H" ? "High" : "Low"} ${next.ft} ft ${pdTime(next.t, { hour: "numeric", minute: "2-digit" })}` : ""), /* @__PURE__ */ React.createElement("span", { className: "pd-src" }, tides ? tides.name : "")), /* @__PURE__ */ React.createElement("div", { className: "pd-tile" }, /* @__PURE__ */ React.createElement("span", { className: "pd-k" }, "Wind"), /* @__PURE__ */ React.createElement("b", null, wind ? /* @__PURE__ */ React.createElement(React.Fragment, null, h.windFrom != null && pdArrow((h.windFrom + 180) % 360), h.windKt, " kt") : "\u2014", wind && h.windGustKt != null && /* @__PURE__ */ React.createElement("small", null, " g", h.windGustKt)), /* @__PURE__ */ React.createElement("span", { className: "pd-s" }, wind ? pdDir(h.windFrom) : ""), pd.windNote && /* @__PURE__ */ React.createElement("span", { className: "pd-src" }, "From last update")), /* @__PURE__ */ React.createElement("div", { className: "pd-tile" }, /* @__PURE__ */ React.createElement("span", { className: "pd-k" }, "Water"), /* @__PURE__ */ React.createElement("b", null, wt ? `${wt.f}\xB0F` : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "pd-s" }, wt ? pdWetsuit(wt.f) : ""), /* @__PURE__ */ React.createElement("span", { className: "pd-src" }, wt ? `Buoy ${wt.station}` : "")), /* @__PURE__ */ React.createElement("div", { className: "pd-tile" }, /* @__PURE__ */ React.createElement("span", { className: "pd-k" }, s.kind === "coast" ? "Surf" : "Waves"), /* @__PURE__ */ React.createElement("b", null, h && h.faceFt ? `${h.faceFt[0]}\u2013${h.faceFt[1]} ft` : s.kind === "coast" ? "\u2014" : "Flat"), /* @__PURE__ */ React.createElement("span", { className: "pd-s" }, h && h.hsM != null ? `Swell ${(h.hsM * 3.281).toFixed(1)} ft \xB7 ${Math.round(h.tpS)} s ${pdDir(h.dpDeg)}` : s.kind === "coast" ? "" : "Sheltered")), s.currentStation && /* @__PURE__ */ React.createElement("div", { className: "pd-tile" }, /* @__PURE__ */ React.createElement("span", { className: "pd-k" }, "Current"), /* @__PURE__ */ React.createElement("b", null, cur ? cur.type === "slack" ? "Slack" : /* @__PURE__ */ React.createElement(React.Fragment, null, cur.towardDeg != null && pdArrow(cur.towardDeg), cur.kt, " kt") : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "pd-s" }, cur && cur.type !== "slack" ? cur.type === "ebb" ? "Ebb, outgoing" : "Flood, incoming" : ""), /* @__PURE__ */ React.createElement("span", { className: "pd-src" }, pd.currentStationName, s.currentScored ? "" : " (indicative)")));
}
function PaddleList({ pd, link }) {
  const rows = pd.spots.map((s) => {
    const h = pdNow(s.hours);
    const best = (s.best || []).find((w) => Date.parse(w.to) > Date.now());
    return { s, h, best, rank: h && h.level != null ? h.level : -1 };
  }).sort((a, b) => b.rank - a.rank || (b.best ? b.best.level : -1) - (a.best ? a.best.level : -1));
  return /* @__PURE__ */ React.createElement("ol", { className: "pd-list" }, rows.map(({ s, h, best }) => /* @__PURE__ */ React.createElement("li", { key: s.id }, /* @__PURE__ */ React.createElement("a", { className: "pd-row", ...link(s.id) }, /* @__PURE__ */ React.createElement("span", { className: "pd-name" }, s.name, /* @__PURE__ */ React.createElement("i", null, PD_KIND[s.kind])), /* @__PURE__ */ React.createElement(PaddlePill, { label: h && h.label }), /* @__PURE__ */ React.createElement("span", { className: "pd-why" }, h ? h.reason : ""), /* @__PURE__ */ React.createElement("span", { className: "pd-meta" }, h && h.windKt != null && /* @__PURE__ */ React.createElement("span", null, h.windFrom != null && pdArrow((h.windFrom + 180) % 360), h.windKt, " kt", h.windGustKt != null ? ` g${h.windGustKt}` : ""), h && h.tideFt != null && /* @__PURE__ */ React.createElement("span", null, "Tide ", h.tideFt.toFixed(1)), h && h.faceFt && /* @__PURE__ */ React.createElement("span", null, "Surf ", h.faceFt[0], "\u2013", h.faceFt[1]), s.currentScored && h && h.current && h.current.type !== "slack" && /* @__PURE__ */ React.createElement("span", null, h.current.type === "ebb" ? "Ebb" : "Flood", " ", h.current.kt, " kt"), best && /* @__PURE__ */ React.createElement("small", null, "Best ", pdTime(best.from, { weekday: "short" }), " ", pdWin(best), " \xB7 ", best.label))))));
}
function PaddleSpot({ pd, s, link, surfLink }) {
  const [day, setDay] = usePdState(null);
  usePdEffect(() => {
    window.scrollTo(0, 0);
  }, [s.id]);
  const h = pdNow(s.hours);
  const days = (s.best || []).filter((w) => Date.parse(w.to) > Date.now() - 12 * 36e5);
  const dk = day || days[0] && days[0].date;
  const sun = (pd.sun || []).find((x) => x.date === dk);
  const steps = sun ? s.hours.filter((x) => Date.parse(x.t) >= Date.parse(sun.sunrise) - 36e5 && Date.parse(x.t) <= Date.parse(sun.sunset)) : [];
  const surf = s.surfRef && surfLink ? surfLink(s.surfRef) : null;
  return /* @__PURE__ */ React.createElement("div", { className: "pd-wrap" }, /* @__PURE__ */ React.createElement("a", { className: "pd-crumb", ...link("") }, "\u2190 All paddle spots"), /* @__PURE__ */ React.createElement("div", { className: "pd-top" }, /* @__PURE__ */ React.createElement("h1", { className: "pd-title" }, s.name), /* @__PURE__ */ React.createElement("span", { className: "pd-chip" }, "Rule of thumb")), /* @__PURE__ */ React.createElement("p", { className: "pd-sub" }, PD_KIND[s.kind], s.shoreNormal != null ? ` \xB7 faces ${pdDir(s.shoreNormal)}` : "", " \xB7 updated ", pdTime(pd.generatedAt, { weekday: "short", hour: "numeric", minute: "2-digit" })), /* @__PURE__ */ React.createElement("div", { className: `pd-now pd-now-${pdKey(h && h.label)}` }, /* @__PURE__ */ React.createElement(PaddlePill, { label: h && h.label }), " ", /* @__PURE__ */ React.createElement("b", null, h ? h.reason : "")), /* @__PURE__ */ React.createElement(PaddleTiles, { pd, s, h }), s.note && /* @__PURE__ */ React.createElement("p", { className: "pd-note" }, s.note), surf && /* @__PURE__ */ React.createElement("p", { className: "pd-sub" }, /* @__PURE__ */ React.createElement("a", { ...surf }, "Surf forecast here \u2192")), /* @__PURE__ */ React.createElement("section", { className: "pd-panel" }, /* @__PURE__ */ React.createElement("h2", { className: "pd-h" }, "Best window"), /* @__PURE__ */ React.createElement("ul", { className: "pd-days" }, days.map((w) => /* @__PURE__ */ React.createElement("li", { key: w.date }, /* @__PURE__ */ React.createElement("button", { type: "button", className: `pd-day${w.date === dk ? " on" : ""}`, onClick: () => setDay(w.date) }, /* @__PURE__ */ React.createElement("span", { className: "pd-d" }, pdTime(w.from, { weekday: "short", month: "short", day: "numeric" })), /* @__PURE__ */ React.createElement(PaddlePill, { label: w.label }), /* @__PURE__ */ React.createElement("span", { className: "pd-t" }, pdWin(w)), /* @__PURE__ */ React.createElement("span", { className: "pd-r" }, w.reason, w.worseAfter ? ` Worse after ${pdTime(w.to, { hour: "numeric" })}.` : "")))))), /* @__PURE__ */ React.createElement("section", { className: "pd-panel" }, /* @__PURE__ */ React.createElement("h2", { className: "pd-h" }, sun ? pdTime(sun.sunrise, { weekday: "long" }) : "", " by hour"), /* @__PURE__ */ React.createElement("div", { className: "pd-hours", role: "table", "aria-label": `${s.name} by hour` }, steps.map((x) => /* @__PURE__ */ React.createElement("div", { key: x.t, role: "row", className: "pd-hr" }, /* @__PURE__ */ React.createElement("span", { className: "pd-hr-t" }, pdTime(x.t, { hour: "numeric" })), /* @__PURE__ */ React.createElement(PaddlePill, { label: x.label }), /* @__PURE__ */ React.createElement("span", { className: "pd-hr-w" }, x.windKt != null ? /* @__PURE__ */ React.createElement(React.Fragment, null, x.windFrom != null && pdArrow((x.windFrom + 180) % 360), x.windKt, " kt", x.windGustKt != null ? ` g${x.windGustKt}` : "") : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "pd-hr-x" }, x.tideFt != null ? `Tide ${x.tideFt.toFixed(1)}` : "", x.faceFt ? ` \xB7 Surf ${x.faceFt[0]}\u2013${x.faceFt[1]}` : "", x.current && x.current.type !== "slack" ? ` \xB7 ${x.current.type === "ebb" ? "Ebb" : "Flood"} ${x.current.kt} kt` : ""), /* @__PURE__ */ React.createElement("span", { className: "pd-hr-r" }, x.reason))))), /* @__PURE__ */ React.createElement("p", { className: "pd-src pd-credit" }, pd.sources));
}
function PaddleView({ spot, link, surfLink }) {
  const { data: pd, error } = usePaddleData();
  if (error) return /* @__PURE__ */ React.createElement("div", { className: "pd-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "pd-title" }, "Paddle"), /* @__PURE__ */ React.createElement("p", { className: "pd-sub" }, "Paddle forecast unavailable right now."));
  if (!pd) return /* @__PURE__ */ React.createElement("div", { className: "pd-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "pd-title" }, "Paddle"), /* @__PURE__ */ React.createElement("p", { className: "pd-sub" }, "Loading\u2026"));
  const s = spot && pd.spots.find((x) => x.id === spot);
  if (spot && !s) return /* @__PURE__ */ React.createElement("div", { className: "pd-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "pd-title" }, "Spot not found"), /* @__PURE__ */ React.createElement("p", { className: "pd-sub" }, /* @__PURE__ */ React.createElement("a", { ...link("") }, "All paddle spots \u2192")));
  if (s) return /* @__PURE__ */ React.createElement(PaddleSpot, { pd, s, link, surfLink });
  const wt = pd.waterTemp;
  return /* @__PURE__ */ React.createElement("div", { className: "pd-wrap" }, /* @__PURE__ */ React.createElement("div", { className: "pd-top" }, /* @__PURE__ */ React.createElement("h1", { className: "pd-title" }, "Paddle report"), /* @__PURE__ */ React.createElement("span", { className: "pd-chip" }, "Rule of thumb")), /* @__PURE__ */ React.createElement("p", { className: "pd-sub" }, "Updated ", pdTime(pd.generatedAt, { weekday: "short", hour: "numeric", minute: "2-digit" }), wt ? ` \xB7 Water ${wt.f}\xB0F, ${pdWetsuit(wt.f).toLowerCase()}` : "", pd.windNote ? " \xB7 Wind from last update" : ""), /* @__PURE__ */ React.createElement(PaddleList, { pd, link }), /* @__PURE__ */ React.createElement("p", { className: "pd-src pd-credit" }, pd.sources));
}
window.PaddleView = PaddleView;
