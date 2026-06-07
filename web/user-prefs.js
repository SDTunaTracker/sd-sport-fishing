// user-prefs.js — Thin preference layer: Clerk unsafeMetadata when signed in,
// localStorage as guest fallback. Always writes to localStorage as backup.
//
// NOTE: uses unsafeMetadata (client-writable). publicMetadata is server-only.

function getUserPref(key, defaultValue) {
  if (window.Clerk && window.Clerk.user) {
    var meta = window.Clerk.user.unsafeMetadata || {};
    var val  = meta[key];
    return (val !== undefined && val !== null) ? val : defaultValue;
  }
  // Guest path — localStorage
  try {
    var raw = localStorage.getItem('tt_pref_' + key);
    return raw !== null ? JSON.parse(raw) : defaultValue;
  } catch (e) {
    return defaultValue;
  }
}

async function setUserPref(key, value) {
  // Always save locally as backup / guest fallback
  try {
    localStorage.setItem('tt_pref_' + key, JSON.stringify(value));
  } catch (e) { /* ignore */ }

  // Save to Clerk if signed in
  if (window.Clerk && window.Clerk.user) {
    try {
      var currentMeta = window.Clerk.user.unsafeMetadata || {};
      await window.Clerk.user.update({
        unsafeMetadata: Object.assign({}, currentMeta, { [key]: value })
      });
    } catch (e) {
      console.error('setUserPref Clerk update failed:', e);
    }
  }
}

window.getUserPref = getUserPref;
window.setUserPref = setUserPref;

// ── Saved boats (local-only watchlist) ───────────────────────────────────────

function getSavedBoats() {
  try { return new Set(JSON.parse(localStorage.getItem('tt_saved_boats') || '[]')); }
  catch(e) { return new Set(); }
}

function toggleSavedBoat(name) {
  var s = getSavedBoats();
  if (s.has(name)) s.delete(name); else s.add(name);
  localStorage.setItem('tt_saved_boats', JSON.stringify([...s]));
  window.dispatchEvent(new Event('tt-saved-boats-changed'));
}

window.getSavedBoats  = getSavedBoats;
window.toggleSavedBoat = toggleSavedBoat;

// ── Followed boats (account-level follow, synced to Clerk) ───────────────────
// Shares the same localStorage key as getSavedBoats so existing watchlist data
// is preserved. The difference is setFollowedBoats also syncs to Clerk.

function getFollowedBoats() {
  if (window.Clerk && window.Clerk.user) {
    var meta = window.Clerk.user.unsafeMetadata || {};
    if (Array.isArray(meta.followed_boats)) return meta.followed_boats;
  }
  return getSavedBoats ? [...getSavedBoats()] : [];
}

async function setFollowedBoats(names) {
  try { localStorage.setItem('tt_saved_boats', JSON.stringify(names)); } catch(e) {}
  window.dispatchEvent(new Event('tt-saved-boats-changed'));
  if (window.Clerk && window.Clerk.user) {
    try {
      var meta = window.Clerk.user.unsafeMetadata || {};
      await window.Clerk.user.update({
        unsafeMetadata: Object.assign({}, meta, { followed_boats: names })
      });
    } catch(e) { console.error('setFollowedBoats Clerk update failed:', e); }
  }
}

window.getFollowedBoats = getFollowedBoats;
window.setFollowedBoats = setFollowedBoats;

// ── Followed landings ─────────────────────────────────────────────────────────

function getFollowedLandings() {
  return getUserPref('followed_landings', ['Seaforth', "Fisherman's"]);
}

async function setFollowedLandings(names) {
  await setUserPref('followed_landings', names);
  window.dispatchEvent(new Event('tt-followed-landings-changed'));
}

window.getFollowedLandings = getFollowedLandings;
window.setFollowedLandings = setFollowedLandings;

// ── Alerts prefs ──────────────────────────────────────────────────────────────

var _DEFAULT_ALERTS = {
  boatFinished: true, boatNewTrip: true, topTripSpots: true,
  weeklyReport: false, deliveryMethod: 'email',
};

function getAlerts() {
  return Object.assign({}, _DEFAULT_ALERTS, getUserPref('alerts', {}));
}

async function setAlerts(alerts) {
  await setUserPref('alerts', alerts);
}

window.getAlerts = getAlerts;
window.setAlerts = setAlerts;

// ── Plan / entitlements ───────────────────────────────────────────────────────
// 'anonymous' = not signed in. 'free' = signed-in free account.
// Reserved: 'pro' for a future paid tier — add gating checks against this value.

function getPlan() {
  if (window.Clerk && window.Clerk.user) return 'free';
  return 'anonymous';
}

window.getPlan = getPlan;
