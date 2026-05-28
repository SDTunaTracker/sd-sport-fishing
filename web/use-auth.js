// use-auth.js — React hook that wraps Clerk auth state.
// Listens to clerk-ready / clerk-auth-change events and exposes a stable
// {user, loaded, isSignedIn, signIn, signUp, signOut} object.

function useAuth() {
  var useState  = React.useState;
  var useEffect = React.useEffect;

  var _s = useState(window.CLERK_USER || null);
  var user    = _s[0];
  var setUser = _s[1];

  var _l = useState(window.__clerkReady || false);
  var loaded    = _l[0];
  var setLoaded = _l[1];

  useEffect(function () {
    function handleReady(e) {
      setUser(e.detail.user);
      setLoaded(true);
    }
    function handleChange(e) {
      setUser(e.detail.user);
    }

    window.addEventListener('clerk-ready',       handleReady);
    window.addEventListener('clerk-auth-change', handleChange);

    // Catch the case where Clerk finished before this component mounted.
    if (window.__clerkReady) {
      setUser(window.CLERK_USER || null);
      setLoaded(true);
    }

    return function () {
      window.removeEventListener('clerk-ready',       handleReady);
      window.removeEventListener('clerk-auth-change', handleChange);
    };
  }, []);

  function signIn()  { window.Clerk && window.Clerk.openSignIn(); }
  function signUp()  { window.Clerk && window.Clerk.openSignUp(); }
  function signOut() { window.Clerk && window.Clerk.signOut(); }

  return {
    user:       user,
    loaded:     loaded,
    isSignedIn: !!user,
    signIn:     signIn,
    signUp:     signUp,
    signOut:    signOut,
  };
}

window.useAuth = useAuth;
