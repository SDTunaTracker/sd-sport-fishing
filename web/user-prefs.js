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
