const { useState: useSfState, useEffect: useSfEffect, useMemo: useSfMemo, useRef: useSfRef } = React;
const SF_TZ = "America/Los_Angeles";
const SF_STALE_H = 12;
const SF_FT = 3.281;
function sfLocal(iso, opts) {
  return new Date(iso).toLocaleString("en-US", Object.assign({ timeZone: SF_TZ }, opts));
}
function sfDayKey(iso) {
  return sfLocal(iso, { year: "numeric", month: "2-digit", day: "2-digit" });
}
function sfHour(iso) {
  return Number(sfLocal(iso, { hour: "numeric", hour12: false })) % 24;
}
function sfFrac(iso) {
  return sfHour(iso) + Number(sfLocal(iso, { minute: "numeric" })) / 60;
}
function sfClock(iso) {
  return sfLocal(iso, { hour: "numeric", minute: "2-digit" }).replace(":00", "").replace(" AM", "a").replace(" PM", "p");
}
function sfFracClock(f) {
  const h = Math.floor(f), m = Math.round((f - h) * 60);
  const hh = (h + 11) % 12 + 1;
  return hh + (m ? ":" + String(m).padStart(2, "0") : "") + (h < 12 ? " AM" : " PM");
}
const SF_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
function sfDir(d) {
  return d == null ? "" : SF_COMPASS[Math.round((d % 360 + 360) % 360 / 22.5) % 16];
}
function sfSets(h) {
  return h && h.setsFt != null && h.faceFt && h.setsFt > h.faceFt[1] ? h.setsFt : null;
}
function sfSetsTxt(h, unit) {
  const x = sfSets(h);
  return x == null ? "" : ` \xB7 sets to ${x}${unit === false ? "" : " ft"}`;
}
function sfBand(lo, hi) {
  const m = (lo + hi) / 2;
  if (m < 1) return "flat";
  if (m < 2) return "ankle\u2013knee";
  if (m < 3) return "knee\u2013waist";
  if (m < 4) return "waist\u2013chest";
  if (m < 5) return "chest\u2013shoulder";
  if (m < 6) return "head high";
  if (m < 8) return "overhead";
  return "well overhead";
}
function sfRateKey(label) {
  return String(label || "flat").toLowerCase().replace(/[^a-z]+/g, "-");
}
function sfRatingClass(label) {
  return "sf-rate sf-rate-" + sfRateKey(label);
}
function sfTitle(label) {
  return String(label || "").toLowerCase().replace(/(^|[–-])([a-z])/g, (m, a, b) => a + b.toUpperCase());
}
function sfPick(hours, dayKey, localHour) {
  let best = null, bestD = 99;
  hours.forEach((h) => {
    if (sfDayKey(h.t) !== dayKey) return;
    const d = Math.abs(sfHour(h.t) - localHour);
    if (d < bestD) {
      best = h;
      bestD = d;
    }
  });
  return bestD <= 2 ? best : null;
}
function sfSunFor(sun, dayKey) {
  return (sun || []).find((s) => s.sunrise && sfDayKey(s.sunrise) === dayKey) || null;
}
function sfIsDay(iso, sun) {
  const s = sfSunFor(sun, sfDayKey(iso));
  const t = Date.parse(iso);
  if (!s || !s.firstLight || !s.lastLight) {
    const h = sfHour(iso);
    return h >= 6 && h <= 18;
  }
  return t >= Date.parse(s.firstLight) && t <= Date.parse(s.lastLight);
}
function sfBestWindow(hours, dayKey, sun) {
  const nowMs = Date.now() - 90 * 6e4;
  const s = sfSunFor(sun, dayKey);
  const steps = hours.filter((h) => sfDayKey(h.t) === dayKey && Date.parse(h.t) >= nowMs && sfIsDay(h.t, sun));
  if (!steps.length) return null;
  let best = steps[0];
  steps.forEach((h) => {
    if (h.score > best.score + 0.05) best = h;
  });
  let a = sfFrac(best.t) - 1.5, b = sfFrac(best.t) + 1.5;
  if (s && s.firstLight) a = Math.max(a, sfFrac(s.firstLight));
  if (s && s.sunset) b = Math.min(b, sfFrac(s.sunset));
  a = Math.ceil(a * 2) / 2;
  b = Math.floor(b * 2) / 2;
  return { h: best, from: a, to: Math.max(b, a + 0.5) };
}
function useSurfSpots() {
  const [spots, setSpots] = useSfState(null);
  useSfEffect(() => {
    let alive = true;
    const hour = Math.floor(Date.now() / 36e5);
    fetch("/api/v1/surf_spots.json?h=" + hour).then((r) => r.ok ? r.json() : null).then((d) => {
      if (!alive || !d || !Array.isArray(d.spots)) return;
      const ageH = (Date.now() - Date.parse(d.generatedAt)) / 36e5;
      if (ageH <= (d.staleAfterHours || 30)) setSpots(d);
    }).catch(() => {
    });
    return () => {
      alive = false;
    };
  }, []);
  return spots;
}
const SF_AREAS = [[32.975, "North County"], [32.81, "Del Mar\u2013La Jolla"], [32.7, "PB\u2013Point Loma"], [-90, "Coronado\u2013Imperial Beach"]];
function sfArea(lat) {
  return SF_AREAS.find((a) => lat > a[0])[1];
}
function useSurfData() {
  const [state, setState] = useSfState({ data: null, error: false });
  useSfEffect(() => {
    let alive = true;
    const hour = Math.floor(Date.now() / 36e5);
    fetch("/api/v1/surf.json?h=" + hour).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then((d) => {
      if (alive) setState({ data: d, error: false });
    }).catch(() => {
      if (alive) setState({ data: null, error: true });
    });
    return () => {
      alive = false;
    };
  }, []);
  return state;
}
function useSfWidth(fallback) {
  const ref = useSfRef(null);
  const [w, setW] = useSfState(fallback);
  useSfEffect(() => {
    const el = ref.current;
    if (!el) return void 0;
    const set = () => {
      const v = Math.round(el.getBoundingClientRect().width);
      if (v > 0) setW(v);
    };
    set();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", set);
      return () => window.removeEventListener("resize", set);
    }
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}
function SurfTide({ tides, dayKey, sun, win, marks, compact }) {
  const [ref, W] = useSfWidth(600);
  const H = compact ? 118 : 132;
  const pad = { l: 30, r: 8, t: 16, b: 20 };
  const hourly = tides && tides.hourly || [];
  const pts = [];
  let last = -1;
  hourly.forEach(([t, ft], i) => {
    if (sfDayKey(t) === dayKey) {
      pts.push([sfFrac(t), ft]);
      last = i;
    }
  });
  if (last >= 0 && hourly[last + 1]) pts.push([24, hourly[last + 1][1]]);
  if (pts.length < 6) return null;
  pts.sort((a, b) => a[0] - b[0]);
  const hilo = (tides && tides.hilo || []).filter((x2) => sfDayKey(x2.t) === dayKey);
  const vals = pts.map((p) => p[1]).concat(win ? win : []);
  const lo = Math.floor(Math.min(-1, ...vals) - 0.8), hi = Math.ceil(Math.max(6, ...vals) + 0.6);
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const x = (f) => pad.l + f / 24 * iw;
  const y = (ft) => pad.t + (hi - ft) / (hi - lo) * ih;
  const line = pts.map((p, i) => (i ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1)).join(" ");
  const area = line + ` L${x(pts[pts.length - 1][0]).toFixed(1)} ${y(lo)} L${x(pts[0][0]).toFixed(1)} ${y(lo)} Z`;
  const s = sfSunFor(sun, dayKey);
  const dawn = s && s.firstLight ? sfFrac(s.firstLight) : null;
  const dusk = s && s.lastLight ? sfFrac(s.lastLight) : null;
  const isToday = dayKey === sfDayKey((/* @__PURE__ */ new Date()).toISOString());
  const nowF = isToday ? sfFrac((/* @__PURE__ */ new Date()).toISOString()) : null;
  const clipId = "sfclip-" + Math.random().toString(36).slice(2, 8);
  const gridFt = [];
  for (let v = Math.ceil(lo / 2) * 2; v <= hi; v += 2) gridFt.push(v);
  const label = win ? `Tide at La Jolla on this day, with this break's best tide (${win[0]} to ${win[1]} ft) shaded` : "Tide at La Jolla on this day";
  return /* @__PURE__ */ React.createElement("div", { className: "sf-tide", ref }, /* @__PURE__ */ React.createElement("svg", { width: W, height: H, role: "img", "aria-label": label }, dawn != null && /* @__PURE__ */ React.createElement("rect", { className: "sf-tide-night", x: pad.l, y: pad.t, width: Math.max(0, x(dawn) - pad.l), height: ih }), dusk != null && /* @__PURE__ */ React.createElement("rect", { className: "sf-tide-night", x: x(dusk), y: pad.t, width: Math.max(0, x(24) - x(dusk)), height: ih }), gridFt.map((v) => /* @__PURE__ */ React.createElement("g", { key: v }, /* @__PURE__ */ React.createElement("line", { className: "sf-tide-grid", x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v) }), /* @__PURE__ */ React.createElement("text", { className: "sf-tide-ax", x: pad.l - 5, y: y(v) + 3.5, textAnchor: "end" }, v))), win && /* @__PURE__ */ React.createElement("rect", { className: "sf-tide-win", x: pad.l, width: iw, y: y(win[1]), height: Math.max(1, y(win[0]) - y(win[1])) }), /* @__PURE__ */ React.createElement("path", { className: "sf-tide-area", d: area }), /* @__PURE__ */ React.createElement("path", { className: "sf-tide-line", d: line }), win && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("clipPath", { id: clipId }, /* @__PURE__ */ React.createElement("rect", { x: pad.l, width: iw, y: y(win[1]), height: Math.max(1, y(win[0]) - y(win[1])) })), /* @__PURE__ */ React.createElement("path", { className: "sf-tide-line-in", d: line, clipPath: `url(#${clipId})` })), (marks || []).map((f) => /* @__PURE__ */ React.createElement("line", { key: f, className: "sf-tide-mark", x1: x(f), x2: x(f), y1: y(lo), y2: y(lo) - 4 })), nowF != null && /* @__PURE__ */ React.createElement("line", { className: "sf-tide-now", x1: x(nowF), x2: x(nowF), y1: pad.t, y2: y(lo) }), hilo.map((p) => {
    const f = sfFrac(p.t), px = x(f), py = y(p.ft);
    const up = p.type === "H";
    const anchor = px < pad.l + 26 ? "start" : px > W - pad.r - 26 ? "end" : "middle";
    return /* @__PURE__ */ React.createElement("g", { key: p.t }, /* @__PURE__ */ React.createElement("circle", { className: "sf-tide-dot", cx: px, cy: py, r: "3" }), /* @__PURE__ */ React.createElement("text", { className: "sf-tide-lbl", x: px, y: up ? py - 6 : py + 13, textAnchor: anchor }, p.ft, " ft ", sfClock(p.t)));
  }), [0, 6, 12, 18].map((f) => /* @__PURE__ */ React.createElement("text", { key: f, className: "sf-tide-ax", x: x(f) + (f === 0 ? 0 : 0), y: H - 5, textAnchor: f === 0 ? "start" : "middle" }, f === 0 ? "12a" : f === 12 ? "12p" : f < 12 ? f + "a" : f - 12 + "p")), /* @__PURE__ */ React.createElement("text", { className: "sf-tide-ax", x: W - pad.r, y: H - 5, textAnchor: "end" }, "ft MLLW")));
}
function SurfConditions({ data, dayKey }) {
  const s = sfSunFor(data.sun, dayKey);
  const wt = data.waterTemp;
  const nwsWater = data.nws && data.nws.periods && data.nws.periods[0] && data.nws.periods[0].water;
  return /* @__PURE__ */ React.createElement("section", { className: "sf-cond", "aria-label": "Conditions" }, /* @__PURE__ */ React.createElement("div", { className: "sf-cond-tiles" }, /* @__PURE__ */ React.createElement("div", { className: "sf-tile" }, /* @__PURE__ */ React.createElement("span", null, "First light"), /* @__PURE__ */ React.createElement("b", null, s && s.firstLight ? sfLocal(s.firstLight, { hour: "numeric", minute: "2-digit" }) : "\u2014")), /* @__PURE__ */ React.createElement("div", { className: "sf-tile" }, /* @__PURE__ */ React.createElement("span", null, "Sunrise"), /* @__PURE__ */ React.createElement("b", null, s && s.sunrise ? sfLocal(s.sunrise, { hour: "numeric", minute: "2-digit" }) : "\u2014")), /* @__PURE__ */ React.createElement("div", { className: "sf-tile" }, /* @__PURE__ */ React.createElement("span", null, "Sunset"), /* @__PURE__ */ React.createElement("b", null, s && s.sunset ? sfLocal(s.sunset, { hour: "numeric", minute: "2-digit" }) : "\u2014")), /* @__PURE__ */ React.createElement("div", { className: "sf-tile", title: wt ? `CDIP buoy ${wt.station}, ${sfLocal(wt.t, { weekday: "short", hour: "numeric", minute: "2-digit" })}` : "" }, /* @__PURE__ */ React.createElement("span", null, "Water"), /* @__PURE__ */ React.createElement("b", null, wt ? `${wt.f}\xB0F` : nwsWater ? nwsWater.replace(" degrees", "\xB0F") : "\u2014"), /* @__PURE__ */ React.createElement("i", null, wt ? `${sfWetsuit(wt.f)} \xB7 buoy ${wt.station}` : nwsWater ? "NWS" : ""))), /* @__PURE__ */ React.createElement("div", { className: "sf-cond-tide" }, /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, "Tide \xB7 La Jolla"), /* @__PURE__ */ React.createElement(SurfTide, { tides: data.tides, dayKey, sun: data.sun, compact: true })));
}
let _sfLeaflet = null;
function sfEnsureLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (_sfLeaflet) return _sfLeaflet;
  _sfLeaflet = new Promise((resolve, reject) => {
    const el = document.getElementById("tt-leaflet-js");
    const src = el && el.getAttribute("src") || "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js";
    const s = document.createElement("script");
    s.src = src;
    s.crossOrigin = "anonymous";
    s.onload = () => resolve(window.L);
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return _sfLeaflet;
}
function SurfMap({ breaks, best, open, onPick, cap }) {
  const box = useSfRef(null);
  const map = useSfRef(null);
  const layer = useSfRef(null);
  const labels = useSfRef(null);
  const placeRef = useSfRef(null);
  const [failed, setFailed] = useSfState(false);
  useSfEffect(() => {
    let alive = true;
    sfEnsureLeaflet().then((L) => {
      if (!alive || !box.current || map.current) return;
      const m = L.map(box.current, { scrollWheelZoom: false, zoomControl: true, attributionControl: true });
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
        maxZoom: 16,
        attribution: "Tiles \xA9 Esri \u2014 Esri, HERE, Garmin, \xA9 OpenStreetMap contributors"
      }).addTo(m);
      const fit = () => {
        m.invalidateSize();
        m.fitBounds(breaks.map((b) => [b.lat, b.lon]), { padding: [18, 18] });
      };
      fit();
      setTimeout(fit, 250);
      map.current = m;
      m.createPane("sfLabels").style.zIndex = 590;
      layer.current = L.layerGroup().addTo(m);
      labels.current = L.layerGroup().addTo(m);
      m.on("zoomend moveend resize", () => placeRef.current && placeRef.current());
      draw();
    }).catch(() => {
      if (alive) setFailed(true);
    });
    return () => {
      alive = false;
      if (map.current) {
        map.current.remove();
        map.current = null;
      }
    };
  }, []);
  function draw() {
    const L = window.L;
    if (!L || !layer.current) return;
    layer.current.clearLayers();
    breaks.forEach((b) => {
      const bw = best[b.id];
      const key = bw ? sfRateKey(bw.h.label) : "none";
      const txt = bw ? bw.h.faceFt[0] === bw.h.faceFt[1] ? bw.h.faceFt[0] : bw.h.faceFt[0] + "\u2013" + bw.h.faceFt[1] : "\xB7";
      const icon = L.divIcon({
        className: "sf-pin-wrap",
        html: `<span class="sf-pin sf-pin-${key}${b.defaults ? " def" : ""}${open === b.id ? " on" : ""}"></span>`,
        iconSize: b.defaults ? [11, 11] : [16, 16],
        iconAnchor: b.defaults ? [5.5, 5.5] : [8, 8]
      });
      L.marker([b.lat, b.lon], { icon, title: b.name, keyboard: true, zIndexOffset: open === b.id ? 1e3 : 0 }).bindTooltip(
        `<b>${b.name}</b> surf ${txt} ft${bw ? sfSetsTxt(bw.h, false) : ""}${bw ? " \xB7 " + sfTitle(bw.h.label) : ""}${b.defaults ? " \xB7 default settings" : ""}`,
        { direction: "left", offset: [-8, 0], className: "sf-tip" }
      ).on("click", () => onPick(b.id)).addTo(layer.current);
    });
    placeLabels();
  }
  function placeLabels() {
    const L = window.L, m = map.current;
    if (!L || !m || !labels.current) return;
    labels.current.clearLayers();
    const z = m.getZoom();
    if (z < 11) return;
    const size = m.getSize();
    const font = "600 12px " + getComputedStyle(box.current).fontFamily;
    const ctx = (placeLabels.cv || (placeLabels.cv = document.createElement("canvas"))).getContext("2d");
    ctx.font = font;
    const pts = breaks.map((b) => ({ b, p: m.latLngToContainerPoint([b.lat, b.lon]), r: b.defaults ? 6.5 : 9 })).filter((o) => o.p.x > -60 && o.p.y > -30 && o.p.x < size.x + 60 && o.p.y < size.y + 30);
    const boxes = pts.map((o) => ({ x0: o.p.x - o.r, y0: o.p.y - o.r, x1: o.p.x + o.r, y1: o.p.y + o.r }));
    const mr = box.current.getBoundingClientRect();
    box.current.querySelectorAll(".leaflet-control").forEach((c) => {
      const r = c.getBoundingClientRect();
      if (r.width) boxes.push({ x0: r.left - mr.left - 3, y0: r.top - mr.top - 3, x1: r.right - mr.left + 3, y1: r.bottom - mr.top + 3 });
    });
    const hit = (r, list) => list.some((q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0);
    const rank = (o) => (o.b.id === open ? 0 : 10) + (o.b.defaults ? 5 : 0) - ["flat", "poor", "poor-fair", "fair", "fair-good", "good"].indexOf(best[o.b.id] ? sfRateKey(best[o.b.id].h.label) : "flat") / 10;
    const placed = [];
    pts.filter((o) => z >= 12 || !o.b.defaults).sort((a, c) => rank(a) - rank(c)).forEach((o) => {
      const w = Math.ceil(ctx.measureText(o.b.name).width) + 10, h = 18, { x, y } = o.p, g = o.r + 3;
      const spots = [[x + g, y - h / 2], [x - g - w, y - h / 2], [x - w / 2, y - g - h], [x - w / 2, y + g]];
      for (const [x0, y0] of spots) {
        const r = { x0, y0, x1: x0 + w, y1: y0 + h };
        if (r.x0 < 2 || r.y0 < 2 || r.x1 > size.x - 2 || r.y1 > size.y - 2) continue;
        if (hit(r, boxes) || hit(r, placed)) continue;
        placed.push({ x0: x0 - 2, y0: y0 - 2, x1: r.x1 + 2, y1: r.y1 + 2 });
        L.marker([o.b.lat, o.b.lon], {
          pane: "sfLabels",
          keyboard: false,
          interactive: true,
          icon: L.divIcon({
            className: "sf-lbl-wrap",
            iconSize: [w, h],
            iconAnchor: [x - x0, y - y0],
            html: `<span class="sf-lbl${o.b.defaults ? " def" : ""}">${o.b.name.replace(/[&<>"]/g, (c) => "&#" + c.charCodeAt(0) + ";")}</span>`
          })
        }).on("click", () => onPick(o.b.id)).addTo(labels.current);
        break;
      }
    });
  }
  placeRef.current = placeLabels;
  useSfEffect(() => {
    draw();
  }, [breaks, best, open]);
  if (failed) return null;
  return /* @__PURE__ */ React.createElement("section", { className: "sf-map-wrap", "aria-label": "Map of surf breaks" }, /* @__PURE__ */ React.createElement("div", { className: "sf-map", ref: box }), /* @__PURE__ */ React.createElement("div", { className: "sf-map-cap" }, cap || "Coloured by each break's best model rating for the day. Tap a dot to open the break."));
}
function SurfStrip({ b, days, dayKey, sun, onDay }) {
  const keys = days.map((d) => d.key);
  let top = 0;
  b.hours.forEach((h) => {
    if (keys.indexOf(sfDayKey(h.t)) >= 0 && h.faceFt[1] > top) top = h.faceFt[1];
  });
  const scaleFt = Math.max(6, Math.ceil(top / 2) * 2);
  return /* @__PURE__ */ React.createElement("div", { className: "sf-strip", role: "group", "aria-label": `${b.name}, 7-day outlook` }, days.map((d) => {
    const steps = b.hours.filter((h) => sfDayKey(h.t) === d.key);
    return /* @__PURE__ */ React.createElement(
      "button",
      {
        key: d.key,
        type: "button",
        className: `sf-sday${d.key === dayKey ? " on" : ""}`,
        onClick: (e) => {
          e.stopPropagation();
          onDay(d.key);
        },
        "aria-label": `${d.label}: surf up to ${Math.max(0, ...steps.map((h) => h.faceFt[1]))} ft`
      },
      /* @__PURE__ */ React.createElement("span", { className: "sf-sday-lbl" }, d.wd, /* @__PURE__ */ React.createElement("span", { className: "sf-sday-n" }, " ", d.dn)),
      /* @__PURE__ */ React.createElement("span", { className: "sf-bars" }, steps.map((h) => {
        const night = !sfIsDay(h.t, sun);
        const mid = h.faceMidFt != null ? h.faceMidFt : (h.faceFt[0] + h.faceFt[1]) / 2;
        const pMid = Math.min(100, mid / scaleFt * 100);
        const pHi = Math.min(100, h.faceFt[1] / scaleFt * 100);
        const key = sfRateKey(h.label);
        return /* @__PURE__ */ React.createElement(
          "span",
          {
            key: h.t,
            className: `sf-bar${night ? " night" : ""}`,
            title: `${sfLocal(h.t, { weekday: "short", hour: "numeric" })} \xB7 ${h.faceFt[0]}\u2013${h.faceFt[1]} ft${sfSetsTxt(h, false)} \xB7 ${sfTitle(h.label)}${h.windKt != null ? ` \xB7 wind ${h.windKt} kt ${h.windType}` : ""}`
          },
          /* @__PURE__ */ React.createElement("span", { className: `sf-bar-hi sf-c-${key}`, style: { height: pHi + "%" } }),
          /* @__PURE__ */ React.createElement("span", { className: `sf-bar-mid sf-c-${key}`, style: { height: Math.max(pMid, mid > 0 ? 3 : 0) + "%" } })
        );
      })),
      /* @__PURE__ */ React.createElement("span", { className: "sf-rbar" }, steps.map((h) => /* @__PURE__ */ React.createElement("span", { key: h.t, className: `sf-c-${sfRateKey(h.label)}${sfIsDay(h.t, sun) ? "" : " night"}` })))
    );
  }), /* @__PURE__ */ React.createElement("span", { className: "sf-strip-scale", "aria-hidden": "true" }, "bars to ", scaleFt, " ft"));
}
function SurfSlot({ h, label, def }) {
  if (!h) return /* @__PURE__ */ React.createElement("div", { className: "sf-slot sf-slot-empty" }, /* @__PURE__ */ React.createElement("span", { className: "sf-slot-lbl" }, label), "\u2014");
  const [lo, hi] = h.faceFt;
  return /* @__PURE__ */ React.createElement("div", { className: "sf-slot" }, /* @__PURE__ */ React.createElement("span", { className: "sf-slot-lbl" }, label), /* @__PURE__ */ React.createElement("span", { className: "sf-face", title: "Surf height: breaking wave face at the beach" }, lo === hi ? lo : `${lo}\u2013${hi}`, /* @__PURE__ */ React.createElement("small", null, " ft"), h.energyKj != null && /* @__PURE__ */ React.createElement("em", { className: "sf-kj", title: "Wave energy at the model point, kJ (Surf-forecast.com scale: about 100 small, 200\u20131000 punchy)" }, h.energyKj, " kJ")), /* @__PURE__ */ React.createElement("span", { className: "sf-band" }, sfBand(lo, hi), sfSets(h) != null && /* @__PURE__ */ React.createElement("span", { className: "sf-sets" }, " \xB7 sets to ", sfSets(h), " ft")), /* @__PURE__ */ React.createElement("span", { className: sfRatingClass(h.label) }, sfTitle(h.label), h.faded ? " \xB7 wind" : ""), def && /* @__PURE__ */ React.createElement("span", { className: "sf-def-tag", title: "Generic break settings, not tuned for this spot; rating capped at Fair" }, "default settings"));
}
function SurfBest({ bw, isToday, dayLabel }) {
  if (!bw) return null;
  const h = bw.h;
  const when = `${sfFracClock(bw.from)}\u2013${sfFracClock(bw.to)}`.replace(/ AM–(\d[\d:]*) AM/, "\u2013$1 AM").replace(/ PM–(\d[\d:]*) PM/, "\u2013$1 PM");
  if (h.score < 0.5) {
    return /* @__PURE__ */ React.createElement("div", { className: "sf-best sf-best-none" }, /* @__PURE__ */ React.createElement("b", null, isToday ? "Best window today" : `Best window ${dayLabel}`, ":"), " none. Flat or near flat all day.");
  }
  return /* @__PURE__ */ React.createElement("div", { className: `sf-best sf-best-${sfRateKey(h.label)}` }, /* @__PURE__ */ React.createElement("span", { className: "sf-best-k" }, isToday ? "Best window today" : `Best window ${dayLabel}`), /* @__PURE__ */ React.createElement("span", { className: "sf-best-t" }, when), /* @__PURE__ */ React.createElement("span", { className: "sf-best-d" }, h.faceFt[0], "\u2013", h.faceFt[1], " ft", sfSetsTxt(h, false), " \xB7 ", /* @__PURE__ */ React.createElement("b", null, sfTitle(h.label)), h.windKt != null ? ` \xB7 ${h.windKt} kt ${h.windType}` : "", h.tideFt != null ? ` \xB7 tide ${h.tideFt} ft` : ""));
}
function SurfBreakRow({ b, days, dayKey, dayLabel, sun, tides, buoy, bw, open, onToggle, onDay, fav, onFav, navigate }) {
  const am = sfPick(b.hours, dayKey, 7);
  const pm = sfPick(b.hours, dayKey, 13);
  const ref = am || pm;
  const steps = b.hours.filter((h) => sfDayKey(h.t) === dayKey);
  const isToday = days[0] && days[0].key === dayKey;
  return /* @__PURE__ */ React.createElement("li", { className: `sf-break${open ? " open" : ""}`, id: `sf-${b.id}` }, /* @__PURE__ */ React.createElement("button", { className: "sf-break-head", onClick: onToggle, "aria-expanded": open }, /* @__PURE__ */ React.createElement("span", { className: "sf-break-name" }, b.name, /* @__PURE__ */ React.createElement("i", null, b.type === "reef" ? "reef" : "beach", " \xB7 faces ", sfDir(b.shoreNormal))), /* @__PURE__ */ React.createElement(SurfSlot, { h: am, label: "Morning", def: b.defaults }), /* @__PURE__ */ React.createElement(SurfSlot, { h: pm, label: "Afternoon", def: b.defaults }), /* @__PURE__ */ React.createElement("span", { className: "sf-chev", "aria-hidden": "true" }, open ? "\u2013" : "+")), b.note && /* @__PURE__ */ React.createElement("div", { className: "sf-note", role: "note" }, b.note), /* @__PURE__ */ React.createElement("div", { className: "sf-break-glance" }, /* @__PURE__ */ React.createElement(SurfBest, { bw, isToday, dayLabel }), /* @__PURE__ */ React.createElement(SurfStrip, { b, days, dayKey, sun, onDay })), ref && /* @__PURE__ */ React.createElement("div", { className: "sf-break-sub" }, "Swell (offshore, not surf height) ", (ref.hsM * SF_FT).toFixed(1), " ft @ ", Math.round(ref.tpS), " s ", sfDir(ref.dpDeg), " (", ref.dpDeg, "\xB0)", am && am.windKt != null ? ` \xB7 AM wind ${am.windKt} kt ${am.windType}` : "", pm && pm.windKt != null ? ` \xB7 PM ${pm.windKt} kt ${pm.windType}` : "", ref.conf !== "high" ? ` \xB7 ${ref.conf} confidence` : "", ref.modelsDisagree ? " \xB7 models disagree" : ""), open && /* @__PURE__ */ React.createElement("div", { className: "sf-detail" }, /* @__PURE__ */ React.createElement("div", { className: "sf-actions" }, onFav && /* @__PURE__ */ React.createElement(SurfStar, { on: fav, onClick: () => onFav(b.id), name: b.name }), navigate && /* @__PURE__ */ React.createElement("a", { className: "sf-go", ...sfLinkProps(navigate, { sub: "break", spot: b.id }) }, "Open ", b.name, " \u2192")), /* @__PURE__ */ React.createElement("div", { className: "sf-detail-tide" }, /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, "Tide \xB7 best for this break ", b.tideWindow ? `${b.tideWindow[0]} to ${b.tideWindow[1]} ft` : ""), /* @__PURE__ */ React.createElement(SurfTide, { tides, dayKey, sun, win: b.tideWindow, marks: steps.map((h) => sfFrac(h.t)) })), /* @__PURE__ */ React.createElement("div", { className: "sf-steps", role: "table", "aria-label": `${b.name} by time of day` }, /* @__PURE__ */ React.createElement("div", { className: "sf-step sf-step-h", role: "row" }, /* @__PURE__ */ React.createElement("span", null, "Time"), /* @__PURE__ */ React.createElement("span", null, "Surf"), /* @__PURE__ */ React.createElement("span", { className: "sf-nocase" }, "kJ"), /* @__PURE__ */ React.createElement("span", null, "Wind"), /* @__PURE__ */ React.createElement("span", null, "Tide"), /* @__PURE__ */ React.createElement("span", null, "Rating")), steps.map((h) => /* @__PURE__ */ React.createElement("div", { key: h.t, className: `sf-step${sfIsDay(h.t, sun) ? "" : " night"}`, role: "row" }, /* @__PURE__ */ React.createElement("span", null, sfClock(h.t)), /* @__PURE__ */ React.createElement("span", null, h.faceFt[0], "\u2013", h.faceFt[1], " ft", sfSets(h) != null && /* @__PURE__ */ React.createElement("small", { className: "sf-sets" }, " \xB7 sets ", sfSets(h))), /* @__PURE__ */ React.createElement("span", null, h.energyKj != null ? h.energyKj : "\u2014"), /* @__PURE__ */ React.createElement("span", null, h.windKt == null ? "\u2014" : `${h.windKt} kt ${sfDir(h.windFrom)}`), /* @__PURE__ */ React.createElement("span", null, h.tideFt == null ? "\u2014" : h.tideFt), /* @__PURE__ */ React.createElement("span", { className: sfRatingClass(h.label) }, h.score.toFixed(1))))), b.defaults && /* @__PURE__ */ React.createElement("div", { className: "sf-def-box" }, /* @__PURE__ */ React.createElement("b", null, "Default settings."), " This spot uses the same wave model as the main breaks, but with generic settings: its break type is a guess, any tide is scored the same, and its swell window (", b.swellWindow ? `${Math.round((b.swellWindow[0] % 360 + 360) % 360)}\xB0 to ${Math.round((b.swellWindow[1] % 360 + 360) % 360)}\xB0` : "generic", ") comes from the direction the beach faces. Its rating is capped at Fair until the spot is tuned against observations."), /* @__PURE__ */ React.createElement("div", { className: "sf-detail-notes" }, "MOP point ", b.mop, " at ", b.mopDepthM, " m, beach faces ", Math.round(b.shoreNormal), "\xB0.", b.swellWindow ? ` Works best on swell from ${b.swellWindow[0]}\xB0 to ${b.swellWindow[1]}\xB0.` : "", ref && ref.kgM ? ` Model breaker-height check: Hb ${ref.hbM.toFixed(1)} m (Komar\u2013Gaughan ${ref.kgM.toFixed(1)} m), an internal step, not the surf height shown.` : "", buoy ? ` Nearest buoy (CDIP ${buoy.station}) now, wave height offshore (not surf height): ${buoy.hsFt} ft @ ${Math.round(buoy.tpS)} s from ${sfDir(buoy.dpDeg)}, ${sfLocal(buoy.t, { hour: "numeric", minute: "2-digit" })}.` : "", " ", "Energy is the swell's power at the model point (Surf-forecast.com scale: about 100 kJ is small, 200\u20131000 kJ punchy).")));
}
function SurfNws({ nws }) {
  if (!nws || !nws.periods || !nws.periods.length) return null;
  const p = nws.periods[0];
  return /* @__PURE__ */ React.createElement("section", { className: "sf-nws", "aria-label": "National Weather Service surf zone forecast" }, /* @__PURE__ */ React.createElement("div", { className: "sf-nws-h" }, "NWS Surf Zone Forecast \xB7 San Diego County"), nws.headlines && nws.headlines.length > 0 && /* @__PURE__ */ React.createElement("ul", { className: "sf-nws-heads" }, nws.headlines.map((h) => /* @__PURE__ */ React.createElement("li", { key: h }, h))), /* @__PURE__ */ React.createElement("div", { className: "sf-nws-row" }, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("b", null, p.name)), p.ripRisk && /* @__PURE__ */ React.createElement("span", null, "Rip current risk: ", /* @__PURE__ */ React.createElement("b", { className: /high/i.test(p.ripRisk) ? "sf-hi" : "" }, p.ripRisk)), p.surf && /* @__PURE__ */ React.createElement("span", null, "Surf: ", p.surf), p.water && /* @__PURE__ */ React.createElement("span", null, "Water ", p.water)), /* @__PURE__ */ React.createElement("div", { className: "sf-nws-src" }, "Issued ", nws.issued ? sfLocal(nws.issued, { weekday: "short", hour: "numeric", minute: "2-digit" }) : "", " by the National Weather Service. Shown as issued."));
}
function SurfLegend() {
  return /* @__PURE__ */ React.createElement("div", { className: "sf-legend", "aria-label": "Rating colours" }, ["FLAT", "POOR", "POOR\u2013FAIR", "FAIR", "FAIR\u2013GOOD"].map((l) => /* @__PURE__ */ React.createElement("span", { key: l }, /* @__PURE__ */ React.createElement("i", { className: `sf-c-${sfRateKey(l)}` }), sfTitle(l))), /* @__PURE__ */ React.createElement("span", { className: "sf-legend-note" }, "Bars: surf (face) height per 3 h \xB7 faded = dark"));
}
function sfPath(params) {
  const fn = window.ttPathFromRoute;
  return fn ? fn("surf", params || {}) : "/sd/surf";
}
function sfLinkProps(navigate, params) {
  return {
    href: sfPath(params),
    onClick: (e) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
      e.preventDefault();
      navigate("surf", params);
    }
  };
}
function SurfWave({ size }) {
  const z = size || 22;
  return /* @__PURE__ */ React.createElement("svg", { width: z, height: z, viewBox: "0 0 24 24", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement(
    "path",
    {
      d: "M2 15c2.2 0 3.3-1.6 4.5-3.4C8 9.3 9.6 6.5 13.4 6.5c3.1 0 5 2 5 4.3 0 1.8-1.3 3-2.9 3-1.2 0-2.1-.8-2.1-1.9",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round"
    }
  ), /* @__PURE__ */ React.createElement(
    "path",
    {
      d: "M2 19.5c1.7 0 2.6-.9 3.8-.9s2.1.9 3.8.9 2.6-.9 3.8-.9 2.1.9 3.8.9 2.6-.9 3.8-.9",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round"
    }
  ));
}
function SurftrackerHeader({ sub, navigate }) {
  const paddle = sub === "paddle" || sub === "races";
  const tabs = paddle ? [["paddle", "Paddle report"]].concat(window.PaddleRaces ? [["races", "Races"]] : []) : [["report", "Report"], ["forecast", "Forecast"], ["map", "Map"], ["cams", "Cams"]];
  const active = sub === "break" ? "forecast" : sub;
  return /* @__PURE__ */ React.createElement("header", { className: "st-header" }, /* @__PURE__ */ React.createElement("div", { className: "st-head-inner" }, /* @__PURE__ */ React.createElement("a", { className: "st-brand", ...sfLinkProps(navigate, { sub: "report" }), "aria-label": "Surftracker home" }, /* @__PURE__ */ React.createElement("span", { className: "st-brand-mark" }, /* @__PURE__ */ React.createElement(SurfWave, { size: 22 })), /* @__PURE__ */ React.createElement("span", { className: "st-brand-text" }, "Surftracker", /* @__PURE__ */ React.createElement("small", null, "San Diego"))), /* @__PURE__ */ React.createElement("div", { className: "st-mode", role: "group", "aria-label": "Surf or paddle" }, /* @__PURE__ */ React.createElement("a", { className: `st-mode-b${paddle ? "" : " on"}`, "aria-current": paddle ? void 0 : "true", ...sfLinkProps(navigate, { sub: "report" }) }, "Surf"), /* @__PURE__ */ React.createElement("a", { className: `st-mode-b${paddle ? " on" : ""}`, "aria-current": paddle ? "true" : void 0, ...sfLinkProps(navigate, { sub: "paddle" }) }, "Paddle")), /* @__PURE__ */ React.createElement("nav", { className: "st-nav", "aria-label": "Surftracker" }, tabs.map(([id, label]) => /* @__PURE__ */ React.createElement(
    "a",
    {
      key: id,
      className: `st-tab${active === id ? " on" : ""}`,
      "aria-current": active === id ? "page" : void 0,
      ...sfLinkProps(navigate, { sub: id })
    },
    label
  ))), /* @__PURE__ */ React.createElement(
    "a",
    {
      className: "st-back",
      href: "/sd/today",
      "aria-label": "Back to Tunatracker",
      onClick: (e) => {
        if (e.metaKey || e.ctrlKey) return;
        e.preventDefault();
        navigate("today");
      }
    },
    /* @__PURE__ */ React.createElement("span", { "aria-hidden": "true" }, "\u2190"),
    /* @__PURE__ */ React.createElement("span", { className: "st-back-l" }, " Tunatracker")
  )));
}
function SurftrackerFooter({ navigate }) {
  return /* @__PURE__ */ React.createElement("footer", { className: "st-footer" }, /* @__PURE__ */ React.createElement("div", { className: "st-foot-inner" }, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("b", null, "Surftracker"), " is the surf side of Tunatracker: free, no ads, and it shows how accurate it is."), /* @__PURE__ */ React.createElement("span", { className: "st-foot-links" }, /* @__PURE__ */ React.createElement("a", { href: "/sd/today", onClick: (e) => {
    e.preventDefault();
    navigate("today");
  } }, "\u2190 Back to Tunatracker"), /* @__PURE__ */ React.createElement("span", { "aria-hidden": "true" }, "\xB7"), /* @__PURE__ */ React.createElement("a", { href: "/privacy/" }, "Privacy"))));
}
window.SurftrackerHeader = SurftrackerHeader;
window.SurftrackerFooter = SurftrackerFooter;
const SF_FAV_KEY = "tt_surf_favs";
function useSurfFavs() {
  const [favs, setFavs] = useSfState(() => {
    try {
      const v = JSON.parse(localStorage.getItem(SF_FAV_KEY) || "[]");
      return Array.isArray(v) ? v : [];
    } catch (e) {
      return [];
    }
  });
  const toggle = (id) => setFavs((f) => {
    const next = f.indexOf(id) >= 0 ? f.filter((x) => x !== id) : f.concat([id]);
    try {
      localStorage.setItem(SF_FAV_KEY, JSON.stringify(next));
    } catch (e) {
    }
    return next;
  });
  return [favs, toggle];
}
function SurfStar({ on, onClick, name, compact }) {
  return /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: `sf-star${on ? " on" : ""}${compact ? " compact" : ""}`,
      "aria-pressed": !!on,
      "aria-label": on ? `Remove ${name} from my spots` : `Add ${name} to my spots`,
      onClick: (e) => {
        e.stopPropagation();
        e.preventDefault();
        onClick();
      }
    },
    /* @__PURE__ */ React.createElement("span", { "aria-hidden": "true" }, on ? "\u2605" : "\u2606"),
    compact ? null : on ? " My spot" : " Add to my spots"
  );
}
function useSurfAll() {
  const { data, error } = useSurfData();
  const extra = useSurfSpots();
  const all = useSfMemo(() => {
    if (!data) return [];
    const have = {};
    const list = data.breaks.map((b) => {
      have[b.id] = 1;
      return Object.assign({}, b, { area: sfArea(b.lat), key: true });
    });
    (extra && extra.spots || []).forEach((b) => {
      if (!have[b.id]) list.push(Object.assign({}, b, { area: b.area || sfArea(b.lat) }));
    });
    return list.sort((a, b) => b.lat - a.lat);
  }, [data, extra]);
  const days = useSfMemo(() => {
    if (!data || !data.breaks[0]) return [];
    const now = Date.now() - 3 * 36e5;
    const keys = [];
    data.breaks[0].hours.forEach((h) => {
      if (Date.parse(h.t) < now) return;
      const k = sfDayKey(h.t);
      if (keys.indexOf(k) < 0) keys.push(k);
    });
    return keys.map((k) => {
      const h = data.breaks[0].hours.find((x) => sfDayKey(x.t) === k);
      return {
        key: k,
        label: sfLocal(h.t, { weekday: "short", month: "short", day: "numeric" }),
        dn: sfLocal(h.t, { day: "numeric" }),
        wd: sfLocal(h.t, { weekday: "short" })
      };
    });
  }, [data]);
  return { data, error, extra, all, days };
}
function sfWetsuit(f) {
  if (f == null) return null;
  if (f >= 72) return "Boardshorts or a spring suit";
  if (f >= 66) return "Spring suit or 2 mm";
  if (f >= 61) return "3/2 full suit";
  if (f >= 56) return "4/3 full suit";
  return "5/4 with booties";
}
function sfNowNext(hours) {
  const t = Date.now();
  let i = -1, best = 1e15;
  hours.forEach((h, k) => {
    const d = Math.abs(Date.parse(h.t) - t);
    if (d < best) {
      best = d;
      i = k;
    }
  });
  if (i < 0 || best > 1.6 * 36e5) return [null, null];
  return [hours[i], hours[i + 1] || null];
}
function sfIsDarkNow(sun) {
  return !sfIsDay((/* @__PURE__ */ new Date()).toISOString(), sun);
}
function SurfAreaChips({ value, onChange, counts, withKey, total }) {
  const opts = (withKey ? [["key", "Main breaks"]] : []).concat(SF_AREAS.map((a) => [a[1], a[1]]), [["all", "All"]]);
  return /* @__PURE__ */ React.createElement("div", { className: "sf-areas", role: "tablist", "aria-label": "Area" }, opts.map(([id, lbl]) => /* @__PURE__ */ React.createElement(
    "button",
    {
      key: id,
      type: "button",
      role: "tab",
      "aria-selected": value === id,
      className: `sf-area${value === id ? " on" : ""}`,
      onClick: () => onChange(id)
    },
    lbl,
    counts ? /* @__PURE__ */ React.createElement("span", { className: "sf-area-n" }, " ", id === "all" ? total : id === "key" ? counts.key : counts[id] || 0) : null
  )));
}
function sfInArea(b, area) {
  return area === "all" || (area === "key" ? b.key : b.area === area);
}
function sfCounts(all) {
  const c = { key: 0 };
  all.forEach((b) => {
    c[b.area] = (c[b.area] || 0) + 1;
    if (b.key) c.key += 1;
  });
  return c;
}
function SurfTopBar({ title, data, children }) {
  const ageH = (Date.now() - Date.parse(data.generatedAt)) / 36e5;
  const stale = ageH > (data.staleAfterHours || SF_STALE_H);
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sf-top" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, title), /* @__PURE__ */ React.createElement("span", { className: "sf-chip" }, "Model forecast"), /* @__PURE__ */ React.createElement("span", { className: "sf-muted" }, "Updated ", sfLocal(data.generatedAt, { weekday: "short", hour: "numeric", minute: "2-digit" })), children), stale && /* @__PURE__ */ React.createElement("p", { className: "sf-stale" }, "This forecast is ", Math.round(ageH), " hours old. It may be out of date."), sfWindNote(data) && /* @__PURE__ */ React.createElement("p", { className: "sf-stale sf-windnote" }, sfWindNote(data)));
}
function SurfDays({ days, day, setDay }) {
  return /* @__PURE__ */ React.createElement("div", { className: "sf-days", role: "tablist", "aria-label": "Day" }, days.map((d) => /* @__PURE__ */ React.createElement(
    "button",
    {
      key: d.key,
      role: "tab",
      "aria-selected": day === d.key,
      className: `sf-day${day === d.key ? " on" : ""}`,
      onClick: () => setDay(d.key)
    },
    d.label
  )));
}
function SurfReport({ ctx, navigate, favs, toggleFav }) {
  const { data, all, days, extra } = ctx;
  const [area, setArea] = useSfState("all");
  const [more, setMore] = useSfState(false);
  const today = days[0] ? days[0].key : null;
  const dark = sfIsDarkNow(data.sun);
  const tomorrow = days[1] ? days[1].key : null;
  const rows = all.filter((b) => sfInArea(b, area)).map((b) => {
    const [now, next] = sfNowNext(b.hours);
    const bwToday = today ? sfBestWindow(b.hours, today, data.sun) : null;
    const bwTom = tomorrow ? sfBestWindow(b.hours, tomorrow, data.sun) : null;
    const rankBy = dark ? bwTom ? bwTom.h.score : -1 : Math.max(now ? now.score : -1, next ? next.score - 0.05 : -1);
    return { b, now, next, bw: dark ? bwTom : bwToday, rankBy };
  }).sort((x, y) => y.rankBy - x.rankBy || y.b.lat - x.b.lat);
  const shown = more ? rows : rows.slice(0, 12);
  const mine = favs.map((id) => all.find((b) => b.id === id)).filter(Boolean);
  const counts = sfCounts(all);
  return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement(SurfTopBar, { title: "Surf report", data }), /* @__PURE__ */ React.createElement(SurfEssentials, { data, region: true, nowLabel: "now" }), /* @__PURE__ */ React.createElement(SurfNws, { nws: data.nws }), window.SurfNwsNotes && /* @__PURE__ */ React.createElement(window.SurfNwsNotes, { notes: data.nwsNotes }), mine.length > 0 && /* @__PURE__ */ React.createElement("section", { className: "st-sec", "aria-label": "My spots" }, /* @__PURE__ */ React.createElement("h2", { className: "st-h2" }, "My spots"), /* @__PURE__ */ React.createElement("div", { className: "st-cards" }, mine.map((b) => {
    const [now] = sfNowNext(b.hours);
    const bw = today ? sfBestWindow(b.hours, today, data.sun) : null;
    const h = now || bw && bw.h;
    return /* @__PURE__ */ React.createElement("a", { key: b.id, className: `st-card st-card-${h ? sfRateKey(h.label) : "none"}`, ...sfLinkProps(navigate, { sub: "break", spot: b.id }) }, /* @__PURE__ */ React.createElement("span", { className: "st-card-name" }, b.name), /* @__PURE__ */ React.createElement("span", { className: "st-card-h", title: "Surf height: breaking wave face at the beach" }, h ? `${h.faceFt[0]}\u2013${h.faceFt[1]}` : "\u2014", /* @__PURE__ */ React.createElement("small", null, " ft"), sfSets(h) != null && /* @__PURE__ */ React.createElement("small", { className: "st-sets" }, "sets to ", sfSets(h), " ft")), /* @__PURE__ */ React.createElement("span", { className: h ? sfRatingClass(h.label) : "sf-rate" }, h ? sfTitle(h.label) : "\u2014"), h && /* @__PURE__ */ React.createElement(SurfEssentials, { data, h, compact: true }), bw && bw.h.score >= 0.5 && /* @__PURE__ */ React.createElement("span", { className: "st-card-bw" }, "Best ", sfFracClock(bw.from), "\u2013", sfFracClock(bw.to)));
  }))), /* @__PURE__ */ React.createElement("section", { className: "st-sec", "aria-labelledby": "st-now-h" }, /* @__PURE__ */ React.createElement("div", { className: "st-sec-head" }, /* @__PURE__ */ React.createElement("h2", { className: "st-h2", id: "st-now-h" }, dark ? "Best bets for tomorrow" : "Where to surf now"), /* @__PURE__ */ React.createElement("span", { className: "sf-muted" }, dark ? `Ranked by each spot's best daylight window ${days[1] ? days[1].wd : "tomorrow"}.` : "Ranked by the model rating now and over the next 3 hours.")), extra && /* @__PURE__ */ React.createElement(SurfAreaChips, { value: area, onChange: (id) => {
    setArea(id);
    setMore(false);
  }, counts, total: all.length }), /* @__PURE__ */ React.createElement("ol", { className: "st-rank" }, shown.map(({ b, now, next, bw }, i) => {
    const h = dark ? bw && bw.h : now;
    return /* @__PURE__ */ React.createElement("li", { key: b.id, className: "st-rank-row" }, /* @__PURE__ */ React.createElement("a", { className: "st-rank-link", ...sfLinkProps(navigate, { sub: "break", spot: b.id }) }, /* @__PURE__ */ React.createElement("span", { className: "st-rank-n" }, i + 1), /* @__PURE__ */ React.createElement("span", { className: "st-rank-name" }, b.name, /* @__PURE__ */ React.createElement("i", null, b.area, b.defaults ? /* @__PURE__ */ React.createElement("em", { className: "sf-def" }, " \xB7 default settings") : null)), /* @__PURE__ */ React.createElement("span", { className: "st-rank-h", title: "Surf height: breaking wave face at the beach" }, h ? `${h.faceFt[0]}\u2013${h.faceFt[1]}` : "\u2014", /* @__PURE__ */ React.createElement("small", null, " ft"), sfSets(h) != null && /* @__PURE__ */ React.createElement("small", { className: "st-sets" }, "sets to ", sfSets(h), " ft")), /* @__PURE__ */ React.createElement("span", { className: "st-rank-r" }, h ? /* @__PURE__ */ React.createElement("span", { className: sfRatingClass(h.label) }, sfTitle(h.label)) : "\u2014", !dark && next && h && sfRateKey(next.label) !== sfRateKey(h.label) ? /* @__PURE__ */ React.createElement("small", { className: "st-rank-next" }, "\u2192 ", sfTitle(next.label)) : null), /* @__PURE__ */ React.createElement("span", { className: "st-rank-w" }, h ? /* @__PURE__ */ React.createElement(SurfEssentials, { data, h, compact: "ws" }) : "", !dark && bw && bw.h.score >= 0.5 ? /* @__PURE__ */ React.createElement("small", null, "Best ", sfFracClock(bw.from), "\u2013", sfFracClock(bw.to)) : null, dark && bw ? /* @__PURE__ */ React.createElement("small", null, sfFracClock(bw.from), "\u2013", sfFracClock(bw.to)) : null)), /* @__PURE__ */ React.createElement(SurfStar, { on: favs.indexOf(b.id) >= 0, onClick: () => toggleFav(b.id), name: b.name, compact: true }));
  })), rows.length > 12 && /* @__PURE__ */ React.createElement("button", { type: "button", className: "st-more", onClick: () => setMore(!more) }, more ? "Show top 12" : `Show all ${rows.length} spots`)), today && /* @__PURE__ */ React.createElement("section", { className: "st-sec", "aria-label": "Today's conditions" }, /* @__PURE__ */ React.createElement("h2", { className: "st-h2" }, "Today"), /* @__PURE__ */ React.createElement(SurfConditions, { data, dayKey: today })), /* @__PURE__ */ React.createElement(SurfAbout, { data, extra }));
}
function SurfForecastPage({ ctx, navigate, favs, toggleFav }) {
  const { data, all, days, extra } = ctx;
  const [day, setDay] = useSfState(null);
  const [open, setOpen] = useSfState(null);
  const [area, setArea] = useSfState("key");
  useSfEffect(() => {
    if (!day && days.length) setDay(days[0].key);
  }, [days]);
  const best = useSfMemo(() => {
    const out = {};
    if (day) all.forEach((b) => {
      out[b.id] = sfBestWindow(b.hours, day, data.sun);
    });
    return out;
  }, [all, day]);
  const dayObj = days.find((d) => d.key === day);
  const shown = all.filter((b) => sfInArea(b, area));
  const pick = (id) => {
    const b = all.find((x) => x.id === id);
    if (b && !sfInArea(b, area)) setArea(b.area);
    setOpen(id);
    setTimeout(() => {
      const el = document.getElementById("sf-" + id);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 30);
  };
  return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement(SurfTopBar, { title: "Surf forecast", data }), /* @__PURE__ */ React.createElement(SurfDays, { days, day, setDay }), day && /* @__PURE__ */ React.createElement("div", { className: "sf-overview" }, /* @__PURE__ */ React.createElement(SurfConditions, { data, dayKey: day }), /* @__PURE__ */ React.createElement(SurfMap, { breaks: all, best, open, onPick: pick })), extra && /* @__PURE__ */ React.createElement(SurfAreaChips, { value: area, onChange: (id) => {
    setArea(id);
    setOpen(null);
  }, counts: sfCounts(all), withKey: true, total: all.length }), /* @__PURE__ */ React.createElement(SurfLegend, null), /* @__PURE__ */ React.createElement("ul", { className: "sf-list" }, shown.map((b) => /* @__PURE__ */ React.createElement(
    SurfBreakRow,
    {
      key: b.id,
      b,
      days,
      dayKey: day,
      dayLabel: dayObj ? dayObj.wd : "",
      sun: data.sun,
      tides: data.tides,
      buoy: data.buoys && data.buoys[b.buoy],
      bw: best[b.id],
      open: open === b.id,
      onToggle: () => setOpen(open === b.id ? null : b.id),
      onDay: setDay,
      fav: favs.indexOf(b.id) >= 0,
      onFav: toggleFav,
      navigate
    }
  ))), /* @__PURE__ */ React.createElement(SurfAbout, { data, extra }));
}
function SurfMapPage({ ctx, navigate }) {
  const { data, all, days } = ctx;
  const [day, setDay] = useSfState(null);
  const [sel, setSel] = useSfState(null);
  const selRef = useSfRef(null);
  const selB = sel && all.find((b) => b.id === sel);
  useSfEffect(() => {
    if (sel && selRef.current) selRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [sel]);
  useSfEffect(() => {
    if (!day && days.length) setDay(days[0].key);
  }, [days]);
  const best = useSfMemo(() => {
    const out = {};
    if (day) all.forEach((b) => {
      out[b.id] = sfBestWindow(b.hours, day, data.sun);
    });
    return out;
  }, [all, day]);
  return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement(SurfTopBar, { title: "Surf map", data }), /* @__PURE__ */ React.createElement(SurfDays, { days, day, setDay }), /* @__PURE__ */ React.createElement("div", { className: "st-bigmap" }, /* @__PURE__ */ React.createElement(
    SurfMap,
    {
      breaks: all,
      best,
      open: sel,
      onPick: (id) => setSel(id),
      cap: "Coloured by each break's best model rating for the day. Tap a dot or name for its spot compass."
    }
  )), /* @__PURE__ */ React.createElement(SurfLegend, null), selB && /* @__PURE__ */ React.createElement("div", { className: "st-panel st-map-compass", ref: selRef }, /* @__PURE__ */ React.createElement("div", { className: "st-map-compass-h" }, /* @__PURE__ */ React.createElement("h2", { className: "st-h2" }, selB.name), /* @__PURE__ */ React.createElement("a", { className: "sf-go", ...sfLinkProps(navigate, { sub: "break", spot: selB.id }) }, "Full forecast \u2192"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "st-more", onClick: () => setSel(null), "aria-label": "Close spot compass" }, "Close")), /* @__PURE__ */ React.createElement(SurfCompass, { b: selB, sun: data.sun, data, title: "Spot compass \xB7 swell and wind at this beach" })), /* @__PURE__ */ React.createElement("div", { className: "st-maplist" }, SF_AREAS.map(([, a]) => {
    const list = all.filter((b) => b.area === a);
    if (!list.length) return null;
    return /* @__PURE__ */ React.createElement("section", { key: a, className: "st-maplist-area" }, /* @__PURE__ */ React.createElement("h2", { className: "st-h3" }, a), /* @__PURE__ */ React.createElement("ul", null, list.map((b) => {
      const bw = best[b.id];
      return /* @__PURE__ */ React.createElement("li", { key: b.id }, /* @__PURE__ */ React.createElement("a", { ...sfLinkProps(navigate, { sub: "break", spot: b.id }) }, /* @__PURE__ */ React.createElement("i", { className: `st-dot sf-c-${bw ? sfRateKey(bw.h.label) : "flat"}` }), /* @__PURE__ */ React.createElement("span", null, b.name, b.defaults ? /* @__PURE__ */ React.createElement("em", { className: "sf-def" }, " *") : null), /* @__PURE__ */ React.createElement("b", null, bw ? `${bw.h.faceFt[0]}\u2013${bw.h.faceFt[1]} ft` : "\u2014")));
    })));
  })), /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "* Default settings: generic break settings, rating capped at Fair until the spot is tuned."));
}
function sfTideAt(tides, ms) {
  const pts = tides && tides.hourly;
  if (!pts || pts.length < 2) return null;
  for (let k = 1; k < pts.length; k++) {
    const t1 = Date.parse(pts[k][0]);
    if (t1 >= ms) {
      const t0 = Date.parse(pts[k - 1][0]);
      if (t0 > ms) return null;
      const f = (ms - t0) / Math.max(1, t1 - t0);
      return pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * f;
    }
  }
  return null;
}
function sfTideNext(tides, ms) {
  return (tides && tides.hilo || []).find((x) => Date.parse(x.t) > ms) || null;
}
function sfWindNote(data) {
  return data && data.windNote ? "Wind from the last update; live wind unavailable." : null;
}
function SurfTideSpark({ tides, ms }) {
  const pts = tides && tides.hourly || [];
  const t0 = ms - 6 * 36e5, t1 = ms + 18 * 36e5;
  const seg = pts.filter((p) => {
    const t = Date.parse(p[0]);
    return t >= t0 && t <= t1;
  });
  if (seg.length < 3) return null;
  const vs = seg.map((p) => p[1]), lo = Math.min(...vs), hi = Math.max(...vs);
  const W = 92, H = 26, x = (t) => (t - t0) / (t1 - t0) * W, y = (v) => H - 3 - (v - lo) / Math.max(0.1, hi - lo) * (H - 6);
  const d = seg.map((p, k) => `${k ? "L" : "M"}${x(Date.parse(p[0])).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
  const now = sfTideAt(tides, ms);
  return /* @__PURE__ */ React.createElement("svg", { className: "sf-es-spark", width: W, height: H, viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d }), now != null && /* @__PURE__ */ React.createElement("circle", { cx: x(ms), cy: y(now), r: "3" }));
}
function SurfEssentials({ data, b, h, ms, compact, nowLabel, region }) {
  const at = ms || Date.now();
  const tide = sfTideAt(data.tides, at);
  const rising = tide != null && sfTideAt(data.tides, at + 30 * 6e4) > tide;
  const next = sfTideNext(data.tides, at);
  const wt = data.waterTemp;
  const nwsWater = data.nws && data.nws.periods && data.nws.periods[0] && data.nws.periods[0].water;
  const wNote = sfWindNote(data);
  const hasWind = h && h.windKt != null && h.windFrom != null;
  const wcls = hasWind ? "sf-es-w-" + sfWindClass(h.windType) : "";
  const arr = (deg) => /* @__PURE__ */ React.createElement("i", { className: "sf-es-arr", style: { transform: `rotate(${(deg + 180) % 360}deg)` }, "aria-hidden": "true" }, "\u2191");
  const swellFt = h && h.hsM != null ? (h.hsM * SF_FT).toFixed(1) : null;
  const nextTxt = next ? `${next.type === "H" ? "High" : "Low"} ${next.ft} ft ${sfLocal(next.t, { hour: "numeric", minute: "2-digit" })}` : "";
  if (compact) {
    return /* @__PURE__ */ React.createElement("span", { className: "sf-es-mini" }, compact !== "ws" && tide != null && /* @__PURE__ */ React.createElement("span", { title: `Tide at La Jolla${nextTxt ? "; next " + nextTxt : ""}` }, "Tide ", tide.toFixed(1), rising ? "\u2191" : "\u2193"), /* @__PURE__ */ React.createElement("span", { className: wcls, title: wNote || "" }, hasWind ? /* @__PURE__ */ React.createElement(React.Fragment, null, arr(h.windFrom), h.windKt, " kt", h.windGustKt ? ` g${h.windGustKt}` : "", " ", h.windType) : "Wind \u2014"), compact !== "ws" && wt && /* @__PURE__ */ React.createElement("span", { title: `CDIP buoy ${wt.station}` }, wt.f, "\xB0F"), swellFt && /* @__PURE__ */ React.createElement("span", { title: "Swell just offshore (not surf height)" }, "Swell ", swellFt, " ft ", Math.round(h.tpS), " s"));
  }
  return /* @__PURE__ */ React.createElement("div", { className: region ? "sf-es sf-es-region" : "sf-es", role: "group", "aria-label": "Tide, wind, water temperature and swell" }, /* @__PURE__ */ React.createElement("div", { className: "sf-es-tile" }, /* @__PURE__ */ React.createElement("span", { className: "sf-es-k" }, "Tide", nowLabel ? ` \xB7 ${nowLabel}` : ""), /* @__PURE__ */ React.createElement("b", null, tide != null ? `${tide.toFixed(1)} ft` : "\u2014", " ", tide != null && /* @__PURE__ */ React.createElement("small", null, rising ? "\u2191 rising" : "\u2193 falling")), /* @__PURE__ */ React.createElement(SurfTideSpark, { tides: data.tides, ms: at }), /* @__PURE__ */ React.createElement("span", { className: "sf-es-s" }, nextTxt ? `Next: ${nextTxt}` : ""), /* @__PURE__ */ React.createElement("span", { className: "sf-es-src" }, "NOAA La Jolla")), !region && /* @__PURE__ */ React.createElement("div", { className: `sf-es-tile ${wcls}` }, /* @__PURE__ */ React.createElement("span", { className: "sf-es-k" }, "Wind"), /* @__PURE__ */ React.createElement("b", null, hasWind ? /* @__PURE__ */ React.createElement(React.Fragment, null, arr(h.windFrom), h.windKt, " kt") : "\u2014", " ", hasWind && h.windGustKt != null && /* @__PURE__ */ React.createElement("small", null, "gusts ", h.windGustKt)), /* @__PURE__ */ React.createElement("span", { className: "sf-es-s" }, hasWind ? `from ${sfDir(h.windFrom)} \xB7 ${h.windType}${b ? " here" : ""}` : "No wind forecast"), /* @__PURE__ */ React.createElement("span", { className: "sf-es-src" }, wNote || "ECMWF model")), /* @__PURE__ */ React.createElement("div", { className: "sf-es-tile" }, /* @__PURE__ */ React.createElement("span", { className: "sf-es-k" }, "Water"), /* @__PURE__ */ React.createElement("b", null, wt ? `${wt.f}\xB0F` : nwsWater ? nwsWater.replace(" degrees", "\xB0F") : "\u2014"), /* @__PURE__ */ React.createElement("span", { className: "sf-es-s" }, wt ? sfWetsuit(wt.f) : ""), /* @__PURE__ */ React.createElement("span", { className: "sf-es-src" }, wt ? `CDIP buoy ${wt.station}, ${sfLocal(wt.t, { weekday: "short", hour: "numeric", minute: "2-digit" })}` : nwsWater ? "NWS surf zone forecast" : "")), !region && /* @__PURE__ */ React.createElement("div", { className: "sf-es-tile sf-es-swell" }, /* @__PURE__ */ React.createElement("span", { className: "sf-es-k" }, "Swell"), /* @__PURE__ */ React.createElement("b", null, swellFt ? /* @__PURE__ */ React.createElement(React.Fragment, null, arr(h.dpDeg), swellFt, " ft") : "\u2014", " ", swellFt && /* @__PURE__ */ React.createElement("small", null, Math.round(h.tpS), " s")), /* @__PURE__ */ React.createElement("span", { className: "sf-es-s" }, swellFt ? `from ${sfDir(h.dpDeg)} ${Math.round(h.dpDeg)}\xB0` : ""), /* @__PURE__ */ React.createElement("span", { className: "sf-es-src" }, h ? `Surf ${h.faceFt[0]}\u2013${h.faceFt[1]} ft (face)` : "")));
}
const SF_WIND_TXT = {
  glassy: "light, close to glassy",
  offshore: "offshore",
  cross: "cross-shore",
  "light onshore": "light onshore",
  bumpy: "onshore, bumpy",
  onshore: "onshore",
  "blown out": "strong onshore, blown out"
};
function sfAngDiff(a, b) {
  return (a - b + 540) % 360 - 180;
}
function sfSwellTxt(dp, normal) {
  const d = Math.abs(sfAngDiff(dp, normal));
  if (d <= 25) return "straight in";
  if (d <= 50) return "angled in";
  if (d <= 75) return "wrapping in, partly shadowed";
  return "mostly blocked";
}
function sfCompassLine(h, b) {
  const parts = [];
  if (h.windKt == null || h.windFrom == null) parts.push("No wind forecast for this hour");
  else parts.push(`Wind ${sfDir(h.windFrom)} ${h.windKt} kt${h.windGustKt ? ` (gusts ${h.windGustKt})` : ""} \u2192 ${SF_WIND_TXT[h.windType] || h.windType} here`);
  if (h.dpDeg != null && h.tpS != null)
    parts.push(`swell ${sfDir(h.dpDeg)} ${Math.round(h.tpS)} s \u2192 ${sfSwellTxt(h.dpDeg, b.shoreNormal)} for this ${sfDir(b.shoreNormal)}-facing beach`);
  return parts.join("; ") + ".";
}
function sfNearestStep(hours) {
  const now = Date.now();
  let best = 0, bd = Infinity;
  hours.forEach((h, i) => {
    const d = Math.abs(Date.parse(h.t) - now);
    if (d < bd) {
      bd = d;
      best = i;
    }
  });
  return best;
}
function useSfBox(ref) {
  const [sz, setSz] = useSfState({ w: 0, h: 0 });
  useSfEffect(() => {
    if (!ref.current) return;
    const upd = () => {
      const r = ref.current.getBoundingClientRect();
      setSz({ w: Math.round(r.width), h: Math.round(r.height) });
    };
    upd();
    const ro = window.ResizeObserver ? new ResizeObserver(upd) : null;
    if (ro) ro.observe(ref.current);
    else window.addEventListener("resize", upd);
    return () => {
      if (ro) ro.disconnect();
      else window.removeEventListener("resize", upd);
    };
  }, []);
  return sz;
}
function SurfCompassDial({ b, h, w, hgt }) {
  const R = Math.max(40, Math.min(w, hgt - 52) / 2 - 10);
  const pt = (deg, r) => [Math.sin(deg * Math.PI / 180) * r, -Math.cos(deg * Math.PI / 180) * r];
  const n = b.shoreNormal;
  const win = b.swellWindow || [n - 60, n + 60];
  const [a0, a1] = [win[0], win[0] + ((win[1] - win[0] + 360) % 360 || 360)];
  const [fx0, fy0] = pt(a0, R * 0.96), [fx1, fy1] = pt(a1, R * 0.96);
  const fan = `M0 0 L${fx0} ${fy0} A${R * 0.96} ${R * 0.96} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${fx1} ${fy1} Z`;
  const arrow = (from, r1, r0, cls) => {
    const [x1, y1] = pt(from, r1), [x0, y0] = pt(from, r0);
    const ang = Math.atan2(y0 - y1, x0 - x1);
    const hx = (sz, t) => `${x0 - Math.cos(ang) * sz + Math.cos(ang + Math.PI / 2) * t},${y0 - Math.sin(ang) * sz + Math.sin(ang + Math.PI / 2) * t}`;
    return /* @__PURE__ */ React.createElement("g", { className: cls }, /* @__PURE__ */ React.createElement("line", { x1, y1, x2: x0 - Math.cos(ang) * 10, y2: y0 - Math.sin(ang) * 10 }), /* @__PURE__ */ React.createElement("polygon", { points: `${x0},${y0} ${hx(14, 7)} ${hx(14, -7)}` }));
  };
  const wcls = h && h.windKt != null ? "sf-cp-wind sf-cp-w-" + sfWindClass(h.windType) : "";
  return /* @__PURE__ */ React.createElement("svg", { className: "sf-cp-svg", width: w, height: hgt, viewBox: `${-w / 2} ${-hgt / 2} ${w} ${hgt}`, "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("circle", { className: "sf-cp-ring", r: R }), Array.from({ length: 36 }, (_, i) => {
    const [x1, y1] = pt(i * 10, R), [x0, y0] = pt(i * 10, R - (i % 9 === 0 ? 9 : 4));
    return /* @__PURE__ */ React.createElement("line", { key: i, className: "sf-cp-tick", x1, y1, x2: x0, y2: y0 });
  }), ["N", "E", "S", "W"].map((c, i) => {
    const [x, y] = pt(i * 90, R - 18);
    return /* @__PURE__ */ React.createElement("text", { key: c, className: "sf-cp-card", x, y: y + 4, textAnchor: "middle" }, c);
  }), /* @__PURE__ */ React.createElement("path", { className: "sf-cp-fan", d: fan }), /* @__PURE__ */ React.createElement("line", { className: "sf-cp-normal", x1: "0", y1: "0", x2: pt(n, R * 0.96)[0], y2: pt(n, R * 0.96)[1] }), h && h.dpDeg != null && arrow(h.dpDeg, R * 0.9, R * 0.12, "sf-cp-swell"), h && h.windKt != null && h.windFrom != null && arrow(h.windFrom, R * 0.66, R * 0.1, wcls), /* @__PURE__ */ React.createElement("circle", { className: "sf-cp-spot", r: "6" }));
}
function SurfCompass({ b, sun, title, data }) {
  const box = useSfRef(null);
  const mapEl = useSfRef(null);
  const map = useSfRef(null);
  const [failed, setFailed] = useSfState(false);
  const hours = b.hours || [];
  const [i, setI] = useSfState(() => sfNearestStep(hours));
  useSfEffect(() => {
    setI(sfNearestStep(hours));
  }, [b.id]);
  const { w, h: hgt } = useSfBox(box);
  useSfEffect(() => {
    let alive = true;
    sfEnsureLeaflet().then((L) => {
      if (!alive || !mapEl.current) return;
      if (!map.current) {
        const m = L.map(mapEl.current, {
          zoomControl: false,
          attributionControl: true,
          dragging: false,
          scrollWheelZoom: false,
          doubleClickZoom: false,
          touchZoom: false,
          boxZoom: false,
          keyboard: false
        });
        L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
          maxZoom: 16,
          attribution: "Tiles \xA9 Esri \u2014 Esri, HERE, Garmin, \xA9 OpenStreetMap contributors"
        }).addTo(m);
        map.current = m;
      }
      map.current.invalidateSize();
      map.current.setView([b.lat, b.lon], 14, { animate: false });
    }).catch(() => {
      if (alive) setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, [b.id, w, hgt]);
  useSfEffect(() => () => {
    if (map.current) {
      map.current.remove();
      map.current = null;
    }
  }, []);
  const cur = hours[Math.min(i, hours.length - 1)];
  if (!cur) return null;
  const dk = sfDayKey(cur.t);
  const steps = hours.map((x, k) => ({ x, k })).filter((o) => sfDayKey(o.x.t) === dk);
  const hasGust = hours.some((x) => x.windGustKt != null);
  const when = sfLocal(cur.t, { weekday: "short", hour: "numeric" });
  const arrowStyle = (deg) => ({ transform: `rotate(${(deg + 180) % 360}deg)` });
  return /* @__PURE__ */ React.createElement("section", { className: "sf-cp", "aria-label": `${b.name} spot compass` }, title && /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, title), data && /* @__PURE__ */ React.createElement(SurfEssentials, { data, b, h: cur, ms: Date.parse(cur.t), nowLabel: when }), /* @__PURE__ */ React.createElement("div", { className: "sf-cp-stage", ref: box }, !failed && /* @__PURE__ */ React.createElement("div", { className: "sf-cp-map", ref: mapEl }), w > 0 && /* @__PURE__ */ React.createElement(SurfCompassDial, { b, h: cur, w, hgt })), /* @__PURE__ */ React.createElement("div", { className: "sf-cp-legend", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("span", { className: "sf-cp-chip sf-cp-swell" }, /* @__PURE__ */ React.createElement("i", null), "Swell"), /* @__PURE__ */ React.createElement("span", { className: `sf-cp-chip sf-cp-wind sf-cp-w-${cur.windKt != null ? sfWindClass(cur.windType) : "none"}` }, /* @__PURE__ */ React.createElement("i", null), "Wind"), /* @__PURE__ */ React.createElement("span", { className: "sf-cp-chip sf-cp-face" }, /* @__PURE__ */ React.createElement("i", null), "Beach faces ", sfDir(b.shoreNormal), " ", Math.round(b.shoreNormal), "\xB0")), /* @__PURE__ */ React.createElement("p", { className: "sf-cp-line" }, /* @__PURE__ */ React.createElement("b", null, when, ":"), " ", sfCompassLine(cur, b), " ", /* @__PURE__ */ React.createElement("span", { className: "sf-cp-surf" }, "Surf ", cur.faceFt[0], "\u2013", cur.faceFt[1], " ft (face)", sfSetsTxt(cur), "."), data && sfWindNote(data) && /* @__PURE__ */ React.createElement("span", { className: "sf-cp-note" }, " ", sfWindNote(data))), /* @__PURE__ */ React.createElement("div", { className: "sf-cp-scrub" }, /* @__PURE__ */ React.createElement("button", { type: "button", onClick: () => setI(Math.max(0, i - 1)), disabled: i <= 0, "aria-label": "Earlier" }, "\u2039"), /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "range",
      min: "0",
      max: hours.length - 1,
      value: i,
      onChange: (e) => setI(Number(e.target.value)),
      "aria-label": "Forecast time",
      "aria-valuetext": when
    }
  ), /* @__PURE__ */ React.createElement("button", { type: "button", onClick: () => setI(Math.min(hours.length - 1, i + 1)), disabled: i >= hours.length - 1, "aria-label": "Later" }, "\u203A"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "sf-cp-now", onClick: () => setI(sfNearestStep(hours)) }, "Now")), /* @__PURE__ */ React.createElement("div", { className: "sf-cp-strip", role: "table", "aria-label": `${b.name}, ${sfLocal(cur.t, { weekday: "long" })}, wind and swell by time` }, /* @__PURE__ */ React.createElement("div", { className: "sf-cp-col sf-cp-head", role: "row" }, /* @__PURE__ */ React.createElement("span", { role: "rowheader" }, sfLocal(cur.t, { weekday: "short" })), /* @__PURE__ */ React.createElement("span", { role: "rowheader" }, "Wind kt"), hasGust && /* @__PURE__ */ React.createElement("span", { role: "rowheader" }, "Gusts"), /* @__PURE__ */ React.createElement("span", { role: "rowheader" }, "Swell ft"), /* @__PURE__ */ React.createElement("span", { role: "rowheader" }, "Period"), /* @__PURE__ */ React.createElement("span", { role: "rowheader" }, "Surf")), steps.map(({ x, k }) => /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      key: x.t,
      role: "row",
      onClick: () => setI(k),
      className: `sf-cp-col${k === i ? " on" : ""}${sfIsDay(x.t, sun) ? "" : " night"}`
    },
    /* @__PURE__ */ React.createElement("span", null, sfClock(x.t)),
    /* @__PURE__ */ React.createElement("span", { className: x.windKt != null ? "sf-cp-w-" + sfWindClass(x.windType) : "" }, x.windFrom != null && /* @__PURE__ */ React.createElement("i", { className: "sf-cp-arr", style: arrowStyle(x.windFrom) }, "\u2191"), x.windKt != null ? x.windKt : "\u2014"),
    hasGust && /* @__PURE__ */ React.createElement("span", null, x.windGustKt != null ? x.windGustKt : "\u2014"),
    /* @__PURE__ */ React.createElement("span", null, x.dpDeg != null && /* @__PURE__ */ React.createElement("i", { className: "sf-cp-arr", style: arrowStyle(x.dpDeg) }, "\u2191"), x.hsM != null ? (x.hsM * SF_FT).toFixed(1) : "\u2014"),
    /* @__PURE__ */ React.createElement("span", null, x.tpS != null ? Math.round(x.tpS) + " s" : "\u2014"),
    /* @__PURE__ */ React.createElement("span", null, x.faceFt[0], "\u2013", x.faceFt[1])
  ))));
}
function sfWindClass(t) {
  if (t === "glassy" || t === "offshore") return "good";
  if (t === "light onshore" || t === "cross") return "ok";
  if (!t || t === "unknown") return "none";
  return "bad";
}
function SurfWind({ steps, sun }) {
  if (!steps.length) return null;
  return /* @__PURE__ */ React.createElement("div", { className: "st-wind", role: "table", "aria-label": "Wind by time of day" }, steps.map((h) => /* @__PURE__ */ React.createElement("div", { key: h.t, role: "row", className: `st-wind-c st-w-${sfWindClass(h.windType)}${sfIsDay(h.t, sun) ? "" : " night"}` }, /* @__PURE__ */ React.createElement("span", { className: "st-wind-t" }, sfClock(h.t)), h.windFrom != null ? /* @__PURE__ */ React.createElement(
    "span",
    {
      className: "st-wind-a",
      style: { transform: `rotate(${(h.windFrom + 180) % 360}deg)` },
      title: `From ${sfDir(h.windFrom)}`,
      "aria-label": `from ${sfDir(h.windFrom)}`
    },
    "\u2191"
  ) : /* @__PURE__ */ React.createElement("span", { className: "st-wind-a", "aria-hidden": "true" }, "\xB7"), /* @__PURE__ */ React.createElement("span", { className: "st-wind-s" }, h.windKt == null ? "\u2014" : h.windKt, /* @__PURE__ */ React.createElement("small", null, " kt")), /* @__PURE__ */ React.createElement("span", { className: "st-wind-k" }, h.windType === "unknown" ? "" : h.windType))));
}
function SurfBreakPage({ ctx, navigate, spot, favs, toggleFav }) {
  const { data, all, days, extra } = ctx;
  const [day, setDay] = useSfState(null);
  useSfEffect(() => {
    if (!day && days.length) setDay(days[0].key);
  }, [days]);
  useSfEffect(() => {
    window.scrollTo(0, 0);
  }, [spot]);
  const b = all.find((x) => x.id === spot);
  if (!b) {
    if (!extra && !ctx.spotsTried) return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "Loading\u2026"));
    return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, "Spot not found"), /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "We don't have a forecast for \u201C", spot, "\u201D. ", /* @__PURE__ */ React.createElement("a", { ...sfLinkProps(navigate, { sub: "forecast" }) }, "See all breaks \u2192")));
  }
  const dk = day || days[0] && days[0].key;
  const dayObj = days.find((d) => d.key === dk);
  const am = sfPick(b.hours, dk, 7), pm = sfPick(b.hours, dk, 13);
  const ref = am || pm;
  const steps = b.hours.filter((h) => sfDayKey(h.t) === dk);
  const bw = dk ? sfBestWindow(b.hours, dk, data.sun) : null;
  const buoy = data.buoys && data.buoys[b.buoy];
  const near = all.filter((x) => x.id !== b.id).map((x) => ({ x, d: Math.abs(x.lat - b.lat) + Math.abs(x.lon - b.lon) })).sort((p, q) => p.d - q.d).slice(0, 4).map((p) => p.x);
  const swellTxt = (w) => `${Math.round((w % 360 + 360) % 360)}\xB0`;
  return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap st-break" }, /* @__PURE__ */ React.createElement("a", { className: "st-crumb", ...sfLinkProps(navigate, { sub: "forecast" }) }, "\u2190 All breaks"), /* @__PURE__ */ React.createElement("div", { className: "sf-top" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, b.name), /* @__PURE__ */ React.createElement("span", { className: "sf-chip" }, "Model forecast"), b.defaults && /* @__PURE__ */ React.createElement("span", { className: "sf-chip sf-chip-warn" }, "Default settings"), /* @__PURE__ */ React.createElement(SurfStar, { on: favs.indexOf(b.id) >= 0, onClick: () => toggleFav(b.id), name: b.name })), /* @__PURE__ */ React.createElement("p", { className: "sf-muted st-sub" }, b.area, " \xB7 ", b.type === "reef" ? "reef" : "beach", " \xB7 faces ", sfDir(b.shoreNormal), " (", Math.round(b.shoreNormal), "\xB0) \xB7 updated ", sfLocal(data.generatedAt, { weekday: "short", hour: "numeric", minute: "2-digit" })), /* @__PURE__ */ React.createElement(SurfEssentials, { data, b, h: b.hours[sfNearestStep(b.hours)], nowLabel: "now" }), b.note && /* @__PURE__ */ React.createElement("div", { className: "sf-note st-note", role: "note" }, b.note), /* @__PURE__ */ React.createElement(SurfBreakCams, { spot: b.id, navigate }), /* @__PURE__ */ React.createElement(SurfDays, { days, day: dk, setDay }), /* @__PURE__ */ React.createElement("div", { className: "st-break-top" }, /* @__PURE__ */ React.createElement("div", { className: "st-slots" }, /* @__PURE__ */ React.createElement(SurfSlot, { h: am, label: "Morning", def: b.defaults }), /* @__PURE__ */ React.createElement(SurfSlot, { h: pm, label: "Afternoon", def: b.defaults })), /* @__PURE__ */ React.createElement(SurfBest, { bw, isToday: days[0] && days[0].key === dk, dayLabel: dayObj ? dayObj.wd : "" })), /* @__PURE__ */ React.createElement("div", { className: "st-panel" }, /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, "7-day outlook"), /* @__PURE__ */ React.createElement(SurfStrip, { b, days, dayKey: dk, sun: data.sun, onDay: setDay }), /* @__PURE__ */ React.createElement(SurfLegend, null)), /* @__PURE__ */ React.createElement("div", { className: "st-panel", id: "compass" }, /* @__PURE__ */ React.createElement(SurfCompass, { b, sun: data.sun, data, title: "Spot compass \xB7 swell and wind at this beach" })), /* @__PURE__ */ React.createElement("div", { className: "st-two" }, /* @__PURE__ */ React.createElement("div", { className: "st-panel" }, /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, "Wind \xB7 ", dayObj ? dayObj.label : ""), /* @__PURE__ */ React.createElement(SurfWind, { steps, sun: data.sun })), /* @__PURE__ */ React.createElement("div", { className: "st-panel" }, /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, "Tide \xB7 La Jolla", !b.defaults && b.tideWindow ? ` \xB7 best ${b.tideWindow[0]} to ${b.tideWindow[1]} ft` : ""), /* @__PURE__ */ React.createElement(SurfTide, { tides: data.tides, dayKey: dk, sun: data.sun, win: b.defaults ? null : b.tideWindow, marks: steps.map((h) => sfFrac(h.t)) }))), /* @__PURE__ */ React.createElement("div", { className: "st-panel" }, /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, "By time of day"), /* @__PURE__ */ React.createElement("div", { className: "sf-steps", role: "table", "aria-label": `${b.name} by time of day` }, /* @__PURE__ */ React.createElement("div", { className: "sf-step sf-step-h", role: "row" }, /* @__PURE__ */ React.createElement("span", null, "Time"), /* @__PURE__ */ React.createElement("span", null, "Surf"), /* @__PURE__ */ React.createElement("span", { className: "sf-nocase" }, "kJ"), /* @__PURE__ */ React.createElement("span", null, "Wind"), /* @__PURE__ */ React.createElement("span", null, "Tide"), /* @__PURE__ */ React.createElement("span", null, "Rating")), steps.map((h) => /* @__PURE__ */ React.createElement("div", { key: h.t, className: `sf-step${sfIsDay(h.t, data.sun) ? "" : " night"}`, role: "row" }, /* @__PURE__ */ React.createElement("span", null, sfClock(h.t)), /* @__PURE__ */ React.createElement("span", null, h.faceFt[0], "\u2013", h.faceFt[1], " ft", sfSets(h) != null && /* @__PURE__ */ React.createElement("small", { className: "sf-sets" }, " \xB7 sets ", sfSets(h))), /* @__PURE__ */ React.createElement("span", null, h.energyKj != null ? h.energyKj : "\u2014"), /* @__PURE__ */ React.createElement("span", null, h.windKt == null ? "\u2014" : `${h.windKt} kt ${sfDir(h.windFrom)}`), /* @__PURE__ */ React.createElement("span", null, h.tideFt == null ? "\u2014" : h.tideFt), /* @__PURE__ */ React.createElement("span", { className: sfRatingClass(h.label) }, h.score.toFixed(1))))), ref && /* @__PURE__ */ React.createElement("p", { className: "st-fine" }, "Swell at the model point (not surf height): ", (ref.hsM * SF_FT).toFixed(1), " ft @ ", Math.round(ref.tpS), " s from ", sfDir(ref.dpDeg), " (", ref.dpDeg, "\xB0)", ref.energyKj != null ? `, ${ref.energyKj} kJ` : "", ".", ref.conf !== "high" ? ` ${ref.conf[0].toUpperCase() + ref.conf.slice(1)} confidence this far out.` : "", ref.modelsDisagree ? " The two wave models disagree for this time." : "")), b.defaults && /* @__PURE__ */ React.createElement("div", { className: "sf-def-box" }, /* @__PURE__ */ React.createElement("b", null, "Default settings."), " This spot uses the same wave model as the main breaks, but with generic settings: its break type is a guess, any tide is scored the same, and its swell window (", b.swellWindow ? `${swellTxt(b.swellWindow[0])} to ${swellTxt(b.swellWindow[1])}` : "generic", ") comes from the direction the beach faces. Its rating is capped at Fair until the spot is tuned against observations."), /* @__PURE__ */ React.createElement("div", { className: "st-panel" }, /* @__PURE__ */ React.createElement("div", { className: "sf-sec-h" }, "Details"), /* @__PURE__ */ React.createElement("p", { className: "st-fine" }, "Model point ", b.mop, " (", b.mopDepthM, " m)", buoy ? ` \xB7 Buoy ${buoy.station}: swell ${buoy.hsFt} ft \xB7 ${Math.round(buoy.tpS)} s ${sfDir(buoy.dpDeg)}, ${sfLocal(buoy.t, { hour: "numeric", minute: "2-digit" })}` : "")), near.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "st-near" }, /* @__PURE__ */ React.createElement("span", { className: "sf-sec-h" }, "Nearby"), near.map((x) => /* @__PURE__ */ React.createElement("a", { key: x.id, ...sfLinkProps(navigate, { sub: "break", spot: x.id }) }, x.name))), /* @__PURE__ */ React.createElement(SurfAbout, { data, extra, compact: true }));
}
function SurfAbout({ data, extra, compact }) {
  const v = data.verification || {};
  return /* @__PURE__ */ React.createElement("section", { className: "sf-about" }, /* @__PURE__ */ React.createElement("h2", null, "How this forecast works"), !compact && /* @__PURE__ */ React.createElement("p", null, data.method), /* @__PURE__ */ React.createElement("div", { className: "sf-checked" }, v.observed && /* @__PURE__ */ React.createElement("p", null, /* @__PURE__ */ React.createElement("b", null, "Surf height vs observed breaking surf:"), " ", v.observed), window.SurfScorecard && /* @__PURE__ */ React.createElement(window.SurfScorecard, { card: v.scorecard }), /* @__PURE__ */ React.createElement("p", null, /* @__PURE__ */ React.createElement("b", null, "Secondary check, swell model:"), " ", v.what, ". Over ", v.testPeriod, ", its wave-height error was", " ", v.hsRmseM ? `${(v.hsRmseM.blend * SF_FT).toFixed(1)} ft (RMS)` : "\u2014", ", better than", " ", (v.beats || []).join(" and "), ". This is wave height at the buoys, not surf height. ", v.leadNote), v.wind && /* @__PURE__ */ React.createElement("p", null, /* @__PURE__ */ React.createElement("b", null, "Wind:"), " ", v.wind), /* @__PURE__ */ React.createElement("p", null, /* @__PURE__ */ React.createElement("b", null, "Not yet checked:"), " ", v.notVerified, " ", v.scale, " Ratings top out at Fair\u2013Good: a model alone can't call a day Good or Epic.")), /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "Surf height is the breaking face height at the beach; occasional sets run larger. Swell and buoy figures are wave heights offshore, shown for context. Best window is the highest-rated daylight 3-hour model step. Sun times are for La Jolla; water temperature is the latest CDIP buoy reading.", extra ? ' Spots marked "default settings" use the same model with generic break settings that are not yet tuned for that spot, and they update about twice a day.' : "", " Always check the NWS rip current risk and conditions on the beach."), /* @__PURE__ */ React.createElement("p", { className: "sf-credits" }, (data.credits || []).concat(data.waterTemp ? [`Water temperature: CDIP buoy ${data.waterTemp.station}`] : [], ["Map tiles: Esri, \xA9 OpenStreetMap contributors"], extra && extra.sources ? [extra.sources] : []).join(" \xB7 ")));
}
function useSurfCams() {
  const [st, setSt] = useSfState({ cams: null, status: null, error: false });
  useSfEffect(() => {
    let alive = true;
    const day = (/* @__PURE__ */ new Date()).toISOString().slice(0, 13);
    Promise.all([
      fetch("/api/v1/surf_cams.json?h=" + day).then((r) => r.ok ? r.json() : Promise.reject(r.status)),
      fetch("/api/v1/surf_cams_status.json?h=" + day).then((r) => r.ok ? r.json() : null).catch(() => null)
    ]).then(([list, status]) => {
      if (!alive) return;
      const fresh = status && status.generatedAt && (Date.now() - Date.parse(status.generatedAt)) / 36e5 < (status.staleAfterHours || 72);
      setSt({ cams: list && list.cams || [], status: fresh ? status.cams || {} : {}, error: false });
    }).catch(() => {
      if (alive) setSt({ cams: [], status: {}, error: true });
    });
    return () => {
      alive = false;
    };
  }, []);
  return st;
}
function sfCamOffline(status, id) {
  const s = status && status[id];
  return s && s.status === "offline" ? s : null;
}
function SurfCamCard({ cam, status, playing, onPlay, focus, names, navigate }) {
  const off = sfCamOffline(status, cam.id);
  const ref = useSfRef(null);
  useSfEffect(() => {
    if (focus && ref.current) ref.current.scrollIntoView({ block: "center" });
  }, [focus]);
  const sky = cam.source === "skyline" && cam.skyline;
  const yt = encodeURIComponent(cam.youtube || "");
  const watch = sky ? sky.page : `https://www.youtube.com/watch?v=${yt}`;
  const spotLinks = (ids) => ids.filter((id) => names[id]).map((id, i) => /* @__PURE__ */ React.createElement(React.Fragment, { key: id }, i ? ", " : "", /* @__PURE__ */ React.createElement("a", { ...sfLinkProps(navigate, { sub: "break", spot: id }) }, names[id])));
  return /* @__PURE__ */ React.createElement("li", { ref, id: "cam-" + cam.id, className: `st-cam${off ? " off" : ""}${focus ? " focus" : ""}` }, /* @__PURE__ */ React.createElement("div", { className: "st-cam-frame" }, off ? /* @__PURE__ */ React.createElement("div", { className: "st-cam-off", role: "status" }, /* @__PURE__ */ React.createElement("b", null, "Cam offline"), /* @__PURE__ */ React.createElement("span", null, off.reason), off.lastSeen && /* @__PURE__ */ React.createElement("span", null, "Last seen live ", sfLocal(off.lastSeen, { month: "short", day: "numeric" }), "."), /* @__PURE__ */ React.createElement("a", { href: cam.operator.url, target: "_blank", rel: "noopener noreferrer" }, "Check ", cam.operator.name.replace(/ \(.*\)$/, ""), sky ? "" : " on YouTube", " \u2197")) : sky ? (
    // SkylineWebcams' own Embed code, unmodified (their terms): a live still that links to their player.
    /* @__PURE__ */ React.createElement("div", { className: "st-cam-sky" }, /* @__PURE__ */ React.createElement("div", { className: "st-cam-sky-embed", dangerouslySetInnerHTML: { __html: sky.embedHtml } }), /* @__PURE__ */ React.createElement("span", { className: "st-cam-live" }, "Live"), /* @__PURE__ */ React.createElement("span", { className: "st-cam-sky-go", "aria-hidden": "true" }, "Watch on SkylineWebcams \u2197"))
  ) : playing ? /* @__PURE__ */ React.createElement(
    "iframe",
    {
      src: `https://www.youtube-nocookie.com/embed/${yt}?autoplay=1&mute=1&playsinline=1&rel=0`,
      title: `${cam.name} live cam`,
      loading: "lazy",
      referrerPolicy: "strict-origin-when-cross-origin",
      allow: "autoplay; encrypted-media; picture-in-picture; fullscreen",
      allowFullScreen: true
    }
  ) : /* @__PURE__ */ React.createElement("button", { type: "button", className: "st-cam-play", onClick: onPlay, "aria-label": `Play ${cam.name} live cam` }, /* @__PURE__ */ React.createElement(
    "img",
    {
      src: `https://i.ytimg.com/vi/${yt}/hqdefault_live.jpg`,
      alt: "",
      loading: "lazy",
      decoding: "async",
      onError: (e) => {
        if (!/hqdefault\.jpg$/.test(e.currentTarget.src)) e.currentTarget.src = `https://i.ytimg.com/vi/${yt}/hqdefault.jpg`;
      }
    }
  ), /* @__PURE__ */ React.createElement("span", { className: "st-cam-live" }, "Live"), /* @__PURE__ */ React.createElement("span", { className: "st-cam-btn", "aria-hidden": "true" }))), /* @__PURE__ */ React.createElement("div", { className: "st-cam-body" }, /* @__PURE__ */ React.createElement("div", { className: "st-cam-name" }, cam.name), /* @__PURE__ */ React.createElement("div", { className: "st-cam-by" }, "Cam by ", /* @__PURE__ */ React.createElement("a", { href: cam.operator.url, target: "_blank", rel: "noopener noreferrer" }, cam.operator.name), !off && !sky && /* @__PURE__ */ React.createElement(React.Fragment, null, " \xB7 ", /* @__PURE__ */ React.createElement("a", { href: watch, target: "_blank", rel: "noopener noreferrer" }, "YouTube \u2197"))), cam.covers.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "st-cam-spots" }, /* @__PURE__ */ React.createElement("span", null, "In view:"), " ", spotLinks(cam.covers)), cam.near.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "st-cam-spots" }, /* @__PURE__ */ React.createElement("span", null, "Nearby:"), " ", spotLinks(cam.near)), cam.note && /* @__PURE__ */ React.createElement("p", { className: "st-cam-note" }, cam.note)));
}
function SurfCamsPage({ ctx, navigate, camId }) {
  const { cams, status, error } = useSurfCams();
  const [playing, setPlaying] = useSfState(null);
  useSfEffect(() => {
    if (!camId) window.scrollTo(0, 0);
  }, []);
  const names = {};
  (ctx.all || []).forEach((b) => {
    names[b.id] = b.name;
  });
  if (!cams) return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, "Live cams"), /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "Loading cams\u2026"));
  if (error || !cams.length) return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, "Live cams"), /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "The cam list is unavailable right now."));
  const surf = cams.filter((c) => c.kind === "surf");
  const areas = SF_AREAS.map((a) => a[1]).filter((a) => surf.some((c) => c.area === a));
  surf.forEach((c) => {
    if (areas.indexOf(c.area) < 0) areas.push(c.area);
  });
  const card = (c) => /* @__PURE__ */ React.createElement(
    SurfCamCard,
    {
      key: c.id,
      cam: c,
      status,
      names,
      navigate,
      focus: camId === c.id,
      playing: playing === c.id,
      onPlay: () => setPlaying(c.id)
    }
  );
  const nOff = surf.filter((c) => sfCamOffline(status, c.id)).length;
  return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap st-cams" }, /* @__PURE__ */ React.createElement("div", { className: "sf-top" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, "Live cams"), /* @__PURE__ */ React.createElement("span", { className: "sf-chip" }, surf.length - nOff, " of ", surf.length, " online")), /* @__PURE__ */ React.createElement("p", { className: "sf-muted st-sub" }, "Live surf cams run by local businesses and people, shown through their own players. Tap a picture to play; only one plays at a time."), /* @__PURE__ */ React.createElement("section", { className: "st-sec", "aria-labelledby": "st-cams-surf" }, /* @__PURE__ */ React.createElement("h2", { className: "st-h2", id: "st-cams-surf" }, "Surf cams"), areas.map((a) => /* @__PURE__ */ React.createElement("div", { key: a, className: "st-cam-area" }, /* @__PURE__ */ React.createElement("h3", { className: "st-h3" }, a), /* @__PURE__ */ React.createElement("ul", { className: "st-cam-grid" }, surf.filter((c) => c.area === a).map(card))))), /* @__PURE__ */ React.createElement("p", { className: "st-fine" }, "Each cam belongs to its operator; follow the links to support them. We check every cam once a day and mark it offline if its video has been removed or no longer allows embedding. If a stream has just ended, the player may show a recording until the operator restarts it. More surf cams coming; none yet for Imperial Beach, Coronado, Ocean Beach, Pacific Beach, Sunset Cliffs, Blacks, Torrey Pines, Del Mar or Cardiff."));
}
function SurfBreakCams({ spot, navigate }) {
  const { cams, status } = useSurfCams();
  const mine = (cams || []).filter((c) => c.covers.indexOf(spot) >= 0);
  if (!mine.length) return null;
  return /* @__PURE__ */ React.createElement("div", { className: "st-break-cams" }, mine.map((c) => {
    const off = sfCamOffline(status, c.id);
    return /* @__PURE__ */ React.createElement("a", { key: c.id, className: `st-cam-link${off ? " off" : ""}`, ...sfLinkProps(navigate, { sub: "cams", spot: c.id }) }, /* @__PURE__ */ React.createElement("span", { className: "st-cam-dot", "aria-hidden": "true" }), off ? "Cam offline" : "Live cam", ": ", c.name, " \u2192");
  }));
}
function SurfView({ navigate, sub, spot }) {
  const ctx = useSurfAll();
  const [favs, toggleFav] = useSurfFavs();
  const [spotsTried, setSpotsTried] = useSfState(false);
  useSfEffect(() => {
    const t = setTimeout(() => setSpotsTried(true), 4e3);
    return () => clearTimeout(t);
  }, []);
  const { data, error } = ctx;
  if (sub === "paddle" && window.PaddleView) {
    return /* @__PURE__ */ React.createElement(
      window.PaddleView,
      {
        spot,
        link: (id) => sfLinkProps(navigate, id ? { sub: "paddle", spot: id } : { sub: "paddle" }),
        surfLink: (id) => sfLinkProps(navigate, { sub: "break", spot: id })
      }
    );
  }
  if (error) return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, "Surftracker"), /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "The surf forecast is unavailable right now."));
  if (!data) return /* @__PURE__ */ React.createElement("div", { className: "sf-wrap" }, /* @__PURE__ */ React.createElement("h1", { className: "sf-title" }, "Surftracker"), /* @__PURE__ */ React.createElement("p", { className: "sf-muted" }, "Loading surf forecast\u2026"));
  const props = { ctx: Object.assign({}, ctx, { spotsTried }), navigate, favs, toggleFav };
  const page = sub === "forecast" ? /* @__PURE__ */ React.createElement(SurfForecastPage, { ...props }) : sub === "map" ? /* @__PURE__ */ React.createElement(SurfMapPage, { ...props }) : sub === "cams" ? /* @__PURE__ */ React.createElement(SurfCamsPage, { ...props, camId: spot }) : sub === "break" && spot ? /* @__PURE__ */ React.createElement(SurfBreakPage, { ...props, spot }) : /* @__PURE__ */ React.createElement(SurfReport, { ...props });
  return /* @__PURE__ */ React.createElement(React.Fragment, null, window.SurfNwsAlerts && /* @__PURE__ */ React.createElement(window.SurfNwsAlerts, { alerts: data.nwsAlerts }), page);
}
window.SurfView = SurfView;
