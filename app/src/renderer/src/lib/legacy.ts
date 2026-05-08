// `?legacy=1` is set by main when a window is opened via the
// "+ New Window for Profile" picker (or via the ZYLCH_PROFILE dev
// escape hatch). Such windows are bound to a profile dir directly
// and pre-date the Firebase-as-identity model, so the renderer
// skips FirebaseAuthGate entirely and never pushes a Firebase token
// to the sidecar.
//
// Important: with `indexedDBLocalPersistence` (firebase/config.ts),
// `auth.currentUser` may still be populated in a legacy window from
// a Firebase session signed in on a different window of the same
// app. UI surfaces that read `auth.currentUser` (IdentityBanner,
// Settings → AccountCard, LLMProviderCard's `signedIn` flag) MUST
// gate on `isLegacyWindow()` first — otherwise they show the wrong
// identity, and a Sign out from a legacy window would clear the
// Firebase session globally and kick the proper-Firebase window
// back to SignIn.
export function isLegacyWindow(): boolean {
  try {
    const qs = new URLSearchParams(window.location.search)
    return qs.get('legacy') === '1'
  } catch {
    return false
  }
}
