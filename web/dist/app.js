const { useState: useS, useEffect: useE } = React;
var _chartsLoadPromise = null;
function _ensureChartsLoaded() {
  if (_chartsLoadPromise) return _chartsLoadPromise;
  if (window.L && window.L.velocityLayer) {
    _chartsLoadPromise = Promise.resolve();
    return _chartsLoadPromise;
  }
  function loadScript(id) {
    return new Promise(function(resolve, reject) {
      var el = document.getElementById(id);
      if (!el) {
        resolve();
        return;
      }
      var src = el.getAttribute("src");
      if (!src) {
        resolve();
        return;
      }
      if (document.querySelector('script[src="' + src + '"]:not([type])')) {
        resolve();
        return;
      }
      var s = document.createElement("script");
      s.src = src;
      var co = el.getAttribute("crossorigin");
      if (co) s.crossOrigin = co;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  _chartsLoadPromise = loadScript("tt-leaflet-js").then(function() {
    return loadScript("tt-leaflet-vel-js");
  }).catch(function() {
  });
  return _chartsLoadPromise;
}
const TWEAK_DEFAULTS = (
  /*EDITMODE-BEGIN*/
  {
    "density": "comfortable",
    "monthlyView": "tpa",
    "showSpike": true,
    "includeZero": true
  }
);
const HASH_VIEWS = {
  home: "home",
  today: "today",
  tripplanner: "tripplanner",
  pick: "pick",
  settings: "account",
  admin: "admin",
  forecast: "forecast",
  account: "account",
  boats: "boats",
  charts: "charts",
  surf: "surf"
};
const ANALYTICS_SUBTABS = ["overview", "finder", "headtohead", "seasonality", "moon", "halfday"];
function extractRegionFromHash(raw) {
  if (!raw) return { regionIds: null, rest: "" };
  var slash = raw.indexOf("/");
  var first = slash === -1 ? raw : raw.slice(0, slash);
  var ids = window.REGION_HASH_TO_IDS && window.REGION_HASH_TO_IDS[first];
  if (ids) return { regionIds: ids, rest: slash === -1 ? "" : raw.slice(slash + 1) };
  return { regionIds: null, rest: raw };
}
function parseRoute(raw) {
  if (!raw) return { view: "home", params: {}, hashRegions: null };
  const qIdx = raw.indexOf("?");
  const query = qIdx === -1 ? "" : raw.slice(qIdx + 1);
  if (qIdx !== -1) raw = raw.slice(0, qIdx);
  const { regionIds, rest } = extractRegionFromHash(raw);
  if (!rest || rest === "home") return { view: "home", params: query ? { query } : {}, hashRegions: regionIds };
  const [seg, ...parts] = rest.split("/");
  const detail = parts.length ? decodeURIComponent(parts.join("/")) : "";
  if (seg === "boat" && detail) return { view: "boat", params: { boat: detail }, hashRegions: regionIds };
  if (seg === "surf") {
    const sub = ["forecast", "map", "break", "cams", "paddle"].includes(parts[0]) ? parts[0] : "report";
    const spot = (sub === "break" || sub === "cams" || sub === "paddle") && parts[1] ? decodeURIComponent(parts[1]) : "";
    return { view: "surf", params: spot ? { sub, spot } : { sub }, hashRegions: regionIds };
  }
  if (seg === "landing" && detail) return { view: "landing", params: { landing: detail }, hashRegions: regionIds };
  if (seg === "analytics") {
    if (detail === "boats") return { view: "boats", params: {}, hashRegions: regionIds };
    const subtab = ANALYTICS_SUBTABS.includes(detail) ? detail : "overview";
    return { view: "analytics", params: { subtab }, hashRegions: regionIds };
  }
  if (seg === "seasonality") {
    const sub = detail === "moon" ? "moon" : "seasonality";
    return { view: "analytics", params: { subtab: sub }, hashRegions: regionIds };
  }
  if (seg === "boats") return { view: "boats", params: {}, hashRegions: regionIds };
  if (seg === "landings" && regionIds && regionIds[0] === "sf_bay") return { view: "landings", params: {}, hashRegions: regionIds };
  if (seg === "landings") return { view: "analytics", params: { subtab: "overview" }, hashRegions: regionIds };
  if (seg === "headtohead") return { view: "analytics", params: { subtab: "headtohead" }, hashRegions: regionIds };
  if (seg === "moon") return { view: "analytics", params: { subtab: "moon" }, hashRegions: regionIds };
  if (HASH_VIEWS[seg]) return { view: HASH_VIEWS[seg], params: query ? { query } : {}, hashRegions: regionIds };
  return { view: "today", params: {}, hashRegions: regionIds };
}
function rawFromLocation() {
  const path = window.location.pathname.replace(/^\/+/, "").replace(/\/+$/, "");
  if (path) return path + (window.location.search || "");
  return window.location.hash.replace(/^#/, "");
}
function routeFromLocation() {
  return parseRoute(rawFromLocation());
}
function pathFromRoute(view, params = {}, regions = ["san_diego"]) {
  const prefix = window.regionsToHashPrefix ? window.regionsToHashPrefix(regions) : "sd";
  let route;
  if (view === "home") route = "home";
  else if (view === "boat" && params.boat) route = "boat/" + encodeURIComponent(params.boat);
  else if (view === "landing" && params.landing) route = "landing/" + encodeURIComponent(params.landing);
  else if (view === "analytics") route = "analytics/" + (params.subtab || "overview");
  else if (view === "boats") route = "boats";
  else if (view === "surf") route = "surf" + (params.sub && params.sub !== "report" ? "/" + params.sub : "") + ((params.sub === "break" || params.sub === "cams" || params.sub === "paddle") && params.spot ? "/" + encodeURIComponent(params.spot) : "");
  else route = view;
  return "/" + prefix + "/" + route;
}
window.ttPathFromRoute = pathFromRoute;
function RegionLoading({ regions, error, onRetry }) {
  const label = window.getRegionSubtitle ? window.getRegionSubtitle(regions) : "this region";
  if (error) {
    return /* @__PURE__ */ React.createElement("div", { className: "region-loading", role: "alert" }, /* @__PURE__ */ React.createElement("div", { className: "region-loading-title" }, "Couldn't load ", label, " fish counts."), /* @__PURE__ */ React.createElement("div", { className: "region-loading-sub" }, "Check your connection and try again."), /* @__PURE__ */ React.createElement("button", { className: "btn primary", onClick: onRetry }, "Try again"));
  }
  return /* @__PURE__ */ React.createElement("div", { className: "region-loading", role: "status", "aria-live": "polite", "aria-busy": "true" }, /* @__PURE__ */ React.createElement("div", { className: "region-loading-title" }, /* @__PURE__ */ React.createElement("span", { className: "region-loading-spinner", "aria-hidden": "true" }), "Loading ", label, " fish counts\u2026"), /* @__PURE__ */ React.createElement("div", { className: "region-loading-sub" }, "One-time download for this region."), window.SkeletonRows && /* @__PURE__ */ React.createElement(SkeletonRows, { count: 6 }));
}
function App() {
  const [route, setRoute] = useS(() => routeFromLocation());
  const [navBusy, setNavBusy] = useS(false);
  const [filters, setFilters] = useS({ ...DEFAULT_FILTERS });
  const [tweaks, setTweaksState] = useTweaks(TWEAK_DEFAULTS);
  const [chartsReady, setChartsReady] = useS(function() {
    return !!(window.L && window.L.velocityLayer);
  });
  const [pageContext, setPageContext] = useS({ page: "today", boat: null, date: null });
  const { user, isSignedIn } = useAuth();
  const _norm = (ids) => window.normalizeRegions ? window.normalizeRegions(ids) : ids;
  const [regions, setRegions] = useS(() => _norm((() => {
    if (window.FEATURES && window.FEATURES.SHOW_SFBAY) {
      const r0 = routeFromLocation();
      if (r0.hashRegions && r0.hashRegions[0] === "sf_bay") return ["sf_bay"];
      if (!r0.hashRegions) {
        try {
          const saved = JSON.parse(localStorage.getItem("tt_regions"));
          if (Array.isArray(saved) && saved[0] === "sf_bay") return ["sf_bay"];
        } catch (e) {
        }
      }
    }
    if (!window.FEATURES || !window.FEATURES.SHOW_OCLA) return ["san_diego"];
    const initial = routeFromLocation();
    if (initial.hashRegions) return initial.hashRegions;
    try {
      const saved = JSON.parse(localStorage.getItem("tt_regions"));
      if (Array.isArray(saved) && saved.length > 0) return saved;
    } catch (e) {
    }
    const old = localStorage.getItem("tt_region");
    if (old === "oc_la") return ["oc_la"];
    return ["san_diego"];
  })()));
  useE(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("tt_regions"));
      if (Array.isArray(saved) && saved.length > 1) localStorage.setItem("tt_regions", JSON.stringify(regions));
    } catch (e) {
    }
  }, []);
  useE(() => {
    if (regions.includes("sf_bay") && !(window.FEATURES && window.FEATURES.SHOW_SFBAY)) {
      const next = ["san_diego"];
      setRegions(next);
      try {
        localStorage.setItem("tt_regions", JSON.stringify(next));
      } catch (e) {
      }
      return;
    }
    if (regions.includes("sf_bay")) return;
    if (!window.FEATURES || !window.FEATURES.SHOW_OCLA) {
      if (regions.includes("oc_la")) {
        const next = ["san_diego"];
        setRegions(next);
        try {
          localStorage.setItem("tt_regions", JSON.stringify(next));
        } catch (e) {
        }
      }
    }
  }, [regions]);
  const [settings, setSettingsState] = useS(() => {
    const s = loadSettings();
    SDA.preprocessTrips(s);
    SDA.preprocessHalfDayTrips(s);
    return s;
  });
  const [regionDataTick, setRegionDataTick] = useS(0);
  const [regionLoadError, setRegionLoadError] = useS(null);
  const regionDataReady = !window.ttRegionData || window.ttRegionData.isLoaded(regions);
  const metricRegion = window.getEffectiveRegion ? window.getEffectiveRegion(regions) : "san_diego";
  if (window.SD_METRIC_REGION !== metricRegion) {
    SDA.preprocessTrips(settings, metricRegion);
    SDA.preprocessHalfDayTrips(settings, metricRegion);
  }
  useE(() => {
    if (regionDataReady) return;
    setRegionLoadError(null);
    window.ttRegionData.ensure(regions).then(() => {
      const s = loadSettings();
      SDA.preprocessTrips(s);
      SDA.preprocessHalfDayTrips(s);
      setRegionDataTick((t) => t + 1);
    }).catch((e) => setRegionLoadError(e && e.message || String(e)));
  }, [regions, regionDataReady, regionDataTick]);
  function onSettingsChange(next) {
    saveSettings(next);
    SDA.preprocessTrips(next);
    SDA.preprocessHalfDayTrips(next);
    setSettingsState(next);
  }
  useE(() => {
    if (!isSignedIn || !window.getUserPref) return;
    const CHOICE_MAP = { san_diego: ["san_diego"], oc_la: ["oc_la"], all_socal: ["san_diego"] };
    if (window.FEATURES && window.FEATURES.SHOW_SFBAY) CHOICE_MAP.sf_bay = ["sf_bay"];
    const savedChoice = window.getUserPref("region_choice", null);
    if (savedChoice && CHOICE_MAP[savedChoice]) {
      setRegionsDirect(CHOICE_MAP[savedChoice]);
    }
    const savedSpecies = window.getUserPref("trophySpecies", null);
    if (savedSpecies && Array.isArray(savedSpecies)) {
      const next = { ...settings, trophySpecies: savedSpecies };
      saveSettings(next);
      SDA.preprocessTrips(next);
      SDA.preprocessHalfDayTrips(next);
      setSettingsState(next);
    }
    const savedMethod = window.getUserPref("tripLengthMethod", null);
    if (savedMethod) {
      const next = { ...settings, tripLengthMethod: savedMethod };
      saveSettings(next);
      setSettingsState(next);
    }
    const savedUnits = window.getUserPref("unitSystem", null);
    if (savedUnits) {
      const next = { ...settings, unitSystem: savedUnits };
      saveSettings(next);
      setSettingsState(next);
    }
    const savedSixpack = window.getUserPref("includeSixPackCharters", null);
    if (savedSixpack !== null) {
      const next = { ...settings, includeSixPackCharters: !!savedSixpack };
      saveSettings(next);
      SDA.preprocessTrips(next);
      SDA.preprocessHalfDayTrips(next);
      setSettingsState(next);
    }
  }, [isSignedIn, user && user.id]);
  useE(() => {
    window.CURRENT_REGION = window.getEffectiveRegion ? window.getEffectiveRegion(regions) : regions[0];
  }, [regions]);
  useE(() => {
    const newPath = pathFromRoute(route.view, route.params || {}, regions);
    if (window.location.pathname !== newPath) {
      history.replaceState(null, "", newPath);
    }
  }, [regions, route]);
  function setRegionsDirect(newRegions) {
    const cleaned = _norm(Array.isArray(newRegions) && newRegions.length > 0 ? newRegions : ["san_diego"]);
    setRegions(cleaned);
    try {
      localStorage.setItem("tt_regions", JSON.stringify(cleaned));
    } catch (e) {
    }
    setFilters((f) => ({ ...f, landing: "all", boat: "all" }));
  }
  function toggleRegion(regionId) {
    setRegionsDirect([regionId]);
  }
  window.__setTweak = (patch) => setTweaksState(patch);
  useE(() => {
    if (filters.includeZero !== tweaks.includeZero) {
      setFilters((f) => ({ ...f, includeZero: tweaks.includeZero }));
    }
  }, [tweaks.includeZero]);
  useE(() => {
    document.body.classList.toggle("compact", tweaks.density === "compact");
  }, [tweaks.density]);
  useE(() => {
    const applyParsed = (parsed) => {
      setRoute((prev) => prev && prev.view === parsed.view && JSON.stringify(prev.params || {}) === JSON.stringify(parsed.params || {}) ? prev : { view: parsed.view, params: parsed.params });
      if (parsed.hashRegions) {
        setRegions((prev) => {
          const same = parsed.hashRegions.length === prev.length && parsed.hashRegions.every((x) => prev.includes(x));
          if (same) return prev;
          localStorage.setItem("tt_regions", JSON.stringify(parsed.hashRegions));
          return parsed.hashRegions;
        });
      }
    };
    if (window.location.hash) {
      const h = window.location.hash.replace(/^#/, "");
      if (h) {
        const p = parseRoute(h);
        history.replaceState(null, "", pathFromRoute(p.view, p.params, p.hashRegions || regions));
      }
    }
    const onPop = () => applyParsed(routeFromLocation());
    const onHash = () => {
      const h = window.location.hash.replace(/^#/, "");
      if (!h) return;
      const parsed = parseRoute(h);
      history.replaceState(null, "", pathFromRoute(parsed.view, parsed.params, parsed.hashRegions || regions));
      applyParsed(parsed);
      window.scrollTo({ top: 0, behavior: "instant" });
    };
    window.addEventListener("popstate", onPop);
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);
  useE(function() {
    if (route.view !== "charts" || chartsReady) return;
    _ensureChartsLoaded().then(function() {
      setChartsReady(true);
    });
  }, [route.view, chartsReady]);
  useE(function() {
    var warmData = function() {
      if (window.__ttPrewarmCharts) window.__ttPrewarmCharts();
    };
    if (window.L && window.L.velocityLayer) {
      warmData();
      return;
    }
    var ric = window.requestIdleCallback || function(fn) {
      return setTimeout(fn, 1500);
    };
    var cancel = window.cancelIdleCallback || clearTimeout;
    var id = ric(function() {
      _ensureChartsLoaded();
      warmData();
    }, { timeout: 4e3 });
    return function() {
      try {
        cancel(id);
      } catch (e) {
      }
    };
  }, []);
  useE(() => {
    if (window.TTTrack) TTTrack.pageView(route.view);
  }, [route.view]);
  useE(() => {
    if (window.__updateMetaTags) window.__updateMetaTags(route.view, route.params || {});
  }, [route.view, route.params?.boat, route.params?.subtab, regionDataTick, regions.join(",")]);
  useE(() => {
    const root = document.documentElement;
    if (route.view === "charts") {
      root.classList.add("charts-open");
    } else {
      root.classList.remove("charts-open");
    }
    return () => root.classList.remove("charts-open");
  }, [route.view]);
  useE(() => {
    setPageContext({
      page: route.view,
      boat: route.params?.boat || null,
      date: null,
      region: window.getEffectiveRegion ? window.getEffectiveRegion(regions) : regions[0],
      regions
    });
  }, [route, regions]);
  if (route.view === "admin") {
    window.location.replace("/owner/admin/");
    return null;
  }
  const navigate = (view, params = {}) => {
    const nextPath = pathFromRoute(view, params, regions);
    const changing = nextPath !== window.location.pathname || view !== route.view;
    if (changing) {
      setNavBusy(true);
      window.clearTimeout(window.__ttNavBusyTimer);
      window.__ttNavBusyTimer = window.setTimeout(() => setNavBusy(false), 500);
    }
    if (window.location.pathname !== nextPath) {
      history.pushState(null, "", nextPath);
      window.__ttInAppNavs = (window.__ttInAppNavs || 0) + 1;
      try {
        window.dispatchEvent(new PopStateEvent("popstate"));
      } catch (e) {
      }
    }
    setRoute({ view, params });
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  const navMap = {
    home: "home",
    today: "today",
    forecast: "forecast",
    analytics: "analytics",
    tripplanner: "tripplanner",
    account: "account",
    boats: "boats",
    charts: "charts",
    landings: "landings",
    pick: "pick",
    surf: "surf"
  };
  const isSfbay = regions[0] === "sf_bay";
  const isSurf = route.view === "surf" && !isSfbay;
  let content;
  if (isSfbay && route.view !== "account") {
    content = /* @__PURE__ */ React.createElement(SFBayView, { view: route.view, params: route.params || {}, navigate });
  } else if (route.view === "home") {
    content = /* @__PURE__ */ React.createElement(HomeView, { navigate, settings, regions });
  } else if (route.view === "today") {
    content = /* @__PURE__ */ React.createElement(TodayView, { navigate, settings, regions });
  } else if (route.view === "surf" && window.SurfView) {
    content = /* @__PURE__ */ React.createElement(SurfView, { navigate, sub: route.params.sub || "report", spot: route.params.spot || "" });
  } else if (route.view === "pick" && window.PickTripView) {
    content = /* @__PURE__ */ React.createElement(PickTripView, { navigate, regions });
  } else if (route.view === "analytics") {
    content = /* @__PURE__ */ React.createElement(AnalyticsView, { filters, setFilters, navigate, tweaks, settings, regions, subtab: route.params.subtab || "overview" });
  } else if (route.view === "boats") {
    content = /* @__PURE__ */ React.createElement(BoatsView, { filters, setFilters, navigate, tweaks, settings, regions });
  } else if (route.view === "boat") {
    content = /* @__PURE__ */ React.createElement(BoatDetail, { filters, setFilters, navigate, boat: route.params.boat, regions });
  } else if (route.view === "landing") {
    content = /* @__PURE__ */ React.createElement(LandingDetail, { filters, setFilters, navigate, landing: route.params.landing, regions });
  } else if (route.view === "tripplanner") {
    content = /* @__PURE__ */ React.createElement(TripPlanner, { filters, setFilters, navigate, tweaks, regions });
  } else if (route.view === "forecast") {
    if (typeof window !== "undefined" && window.history && window.history.replaceState) {
      try {
        window.history.replaceState(null, "", "#charts");
      } catch (e) {
      }
    }
    content = chartsReady ? /* @__PURE__ */ React.createElement(ChartsView, { navigate, settings, regions }) : /* @__PURE__ */ React.createElement("div", { className: "charts-map-loading" }, /* @__PURE__ */ React.createElement("div", { className: "charts-map-loading-text" }, "Loading map\u2026"));
  } else if (route.view === "charts") {
    content = chartsReady ? /* @__PURE__ */ React.createElement(ChartsView, { navigate, settings, regions }) : /* @__PURE__ */ React.createElement("div", { className: "charts-map-loading" }, /* @__PURE__ */ React.createElement("div", { className: "charts-map-loading-text" }, "Loading map\u2026"));
  } else if (route.view === "account") {
    content = /* @__PURE__ */ React.createElement(
      MyAccountView,
      {
        settings,
        onSettingsChange,
        regions,
        onRegionsDirect: setRegionsDirect,
        navigate
      }
    );
  }
  if (!regionDataReady && route.view !== "account" && route.view !== "surf") {
    content = /* @__PURE__ */ React.createElement(
      RegionLoading,
      {
        regions,
        error: regionLoadError,
        onRetry: () => setRegionDataTick((t) => t + 1)
      }
    );
  }
  const headerActive = route.view === "boat" ? "boats" : route.view === "pick" ? "today" : isSfbay && route.view === "home" ? "today" : route.view === "landing" ? isSfbay ? "landings" : "analytics" : route.view;
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: `tt-nav-progress${navBusy ? " on" : ""}`, "aria-hidden": "true" }), isSurf && window.SurftrackerHeader ? /* @__PURE__ */ React.createElement(SurftrackerHeader, { sub: route.params.sub || "report", navigate }) : /* @__PURE__ */ React.createElement(
    AppHeader,
    {
      active: headerActive,
      onNavigate: (id) => navigate(navMap[id] || "today"),
      hrefFor: (id) => pathFromRoute(navMap[id] || "today", {}, regions),
      regions,
      onRegionToggle: toggleRegion,
      onRegionsDirect: setRegionsDirect
    }
  ), /* @__PURE__ */ React.createElement("main", { className: `main-content${isSurf ? " st-main" : ""}`, "data-screen-label": route.view }, content), isSurf && window.SurftrackerFooter ? /* @__PURE__ */ React.createElement(SurftrackerFooter, { navigate }) : isSfbay ? /* @__PURE__ */ React.createElement(SFBayFooter, null) : /* @__PURE__ */ React.createElement(AppFooter, { regions }), route.view === "tripplanner" && !isSfbay && regionDataReady && /* @__PURE__ */ React.createElement(ChatBot, { pageContext }), route.view === "tripplanner" && window.PickFab && !isSfbay && regionDataReady && /* @__PURE__ */ React.createElement(PickFab, { navigate, regions }), /* @__PURE__ */ React.createElement(TweaksPanel, { title: "Tweaks" }, /* @__PURE__ */ React.createElement(TweakSection, { title: "Display" }, /* @__PURE__ */ React.createElement(TweakRadio, { label: "Density", value: tweaks.density, options: [
    { value: "comfortable", label: "Comfortable" },
    { value: "compact", label: "Compact" }
  ], onChange: (v) => setTweaksState({ density: v }) })), /* @__PURE__ */ React.createElement(TweakSection, { title: "Charts" }, /* @__PURE__ */ React.createElement(TweakRadio, { label: "Monthly chart shows", value: tweaks.monthlyView, options: [
    { value: "tpa", label: "Per Angler" },
    { value: "total", label: "Total Catch" }
  ], onChange: (v) => setTweaksState({ monthlyView: v }) }), /* @__PURE__ */ React.createElement(
    TweakToggle,
    {
      label: "Show spike-trip warnings",
      value: tweaks.showSpike,
      onChange: (v) => setTweaksState({ showSpike: v })
    }
  )), /* @__PURE__ */ React.createElement(TweakSection, { title: "Data" }, /* @__PURE__ */ React.createElement(
    TweakToggle,
    {
      label: "Include zero-tuna trips",
      value: tweaks.includeZero,
      onChange: (v) => setTweaksState({ includeZero: v })
    }
  )), /* @__PURE__ */ React.createElement(TweakSection, { title: "Quick Filters" }, /* @__PURE__ */ React.createElement(
    TweakSelect,
    {
      label: "Year",
      value: filters.year,
      options: [{ value: "all", label: "All" }, ...[...new Set(window.SD.TRIPS.map((t) => t.year))].sort((a, b) => b - a).map((y) => ({ value: String(y), label: String(y) }))],
      onChange: (v) => setFilters({ ...filters, year: v })
    }
  ), /* @__PURE__ */ React.createElement(
    TweakSelect,
    {
      label: "Species focus",
      value: filters.species,
      options: [{ value: "all", label: SDA.headlineIsAllSpecies() ? "All species" : "All Tuna" }, { value: "Bluefin", label: "Bluefin" }, { value: "Yellowfin", label: "Yellowfin" }, { value: "Yellowtail", label: "Yellowtail" }, { value: "Dorado", label: "Dorado" }, { value: "Skipjack", label: "Skipjack" }, { value: "Bigeye", label: "Bigeye" }, { value: "Albacore", label: "Albacore" }],
      onChange: (v) => setFilters({ ...filters, species: v })
    }
  ))));
}
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(err) {
    return { error: err };
  }
  componentDidCatch(err, info) {
    if (window.gtag) gtag("event", "js_error_boundary", { description: String(err), fatal: false });
  }
  render() {
    if (this.state.error) {
      return /* @__PURE__ */ React.createElement("div", { style: { padding: "32px 24px", maxWidth: 480, margin: "60px auto", fontFamily: "system-ui,sans-serif" } }, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 18, fontWeight: 700, color: "#0F2A4A", marginBottom: 8 } }, "Something went wrong"), /* @__PURE__ */ React.createElement("div", { style: { fontSize: 14, color: "#64748B", marginBottom: 20, lineHeight: 1.5 } }, String(this.state.error.message || this.state.error)), /* @__PURE__ */ React.createElement(
        "button",
        {
          onClick: () => window.location.reload(),
          style: { background: "#38BDF8", color: "white", border: "none", borderRadius: 8, padding: "10px 20px", fontSize: 14, cursor: "pointer" }
        },
        "Reload page"
      ));
    }
    return this.props.children;
  }
}
ReactDOM.createRoot(document.getElementById("root")).render(
  /* @__PURE__ */ React.createElement(ErrorBoundary, null, /* @__PURE__ */ React.createElement(App, null))
);
