import { initializeApp } from 'firebase/app'
import { indexedDBLocalPersistence, initializeAuth } from 'firebase/auth'

// Same Firebase project as mrcall-dashboard. The API key + project ID are
// public-by-design (Firebase JS SDK config) — they identify the project,
// not the bearer; security rules and the Firebase Admin SDK key (held
// server-side only) are what gate access.
const firebaseConfig = {
  apiKey: 'AIzaSyDTaGASuYL5ZEW5YUaJvOa3DN-7LSaXn8g',
  authDomain: 'talkmeapp-e696c.firebaseapp.com',
  projectId: 'talkmeapp-e696c',
  storageBucket: 'talkmeapp-e696c.appspot.com',
  messagingSenderId: '375340415237',
  appId: '1:375340415237:web:d0551e6e27d341eb7f9f6c',
  measurementId: 'G-Q5HNTEV6DH'
}

const app = initializeApp(firebaseConfig)

// IndexedDB-backed persistence so a signed-in user survives across app
// launches. Profiles are UID-keyed (`auth:bindProfile(uid)` attaches
// `~/.zylch/profiles/<firebase_uid>/`), so a restored Firebase session
// can only ever bind to the matching profile — the "wrong account on
// the wrong profile" drift the previous in-memory-only setup guarded
// against is structurally prevented now. The IdentityBanner at the
// top of every signed-in window keeps the active identity visible in
// case a restored session catches the user by surprise.
//
// One consequence of IndexedDB persistence: `auth.currentUser` is
// shared across all BrowserWindows of this Electron app. Legacy
// windows ("+ New Window for Profile", `?legacy=1`) are bound to a
// profile dir directly and skip the Firebase gate — they MUST also
// suppress any UI that reads `auth.currentUser` (IdentityBanner,
// AccountCard, "Sign out"), or they will advertise the identity of
// a different window and let a Sign out from here clear the session
// globally. See `lib/legacy.ts` for the gate helper.
//
// To force a re-signin (debug, or to sanity-check the gate), the user
// uses the explicit "Sign out" button on the IdentityBanner.
const auth = initializeAuth(app, { persistence: indexedDBLocalPersistence })
auth.useDeviceLanguage()

export { app, auth }
