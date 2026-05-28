// clerk-init.js — Bootstraps Clerk JS after the async browser script loads.
// Dispatches 'clerk-ready' and 'clerk-auth-change' custom events so React
// components can react without polling.

window.__clerkReady = false;

(function initClerk() {
  if (!window.Clerk) {
    setTimeout(initClerk, 100);
    return;
  }

  window.Clerk.load().then(function () {
    window.__clerkReady = true;
    window.CLERK_USER = window.Clerk.user;

    window.dispatchEvent(new CustomEvent('clerk-ready', {
      detail: { user: window.Clerk.user }
    }));

    window.Clerk.addListener(function (payload) {
      window.CLERK_USER = payload.user;
      window.dispatchEvent(new CustomEvent('clerk-auth-change', {
        detail: { user: payload.user }
      }));
    });
  }).catch(function (e) {
    console.error('Clerk init failed:', e);
  });
})();
