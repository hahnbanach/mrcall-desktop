import { initializeApp } from 'firebase/app'
import { indexedDBLocalPersistence, initializeAuth } from 'firebase/auth'

// Same Firebase project as mrcall-dashboard. The API key + project ID are
// public-by-design (Firebase JS SDK config) — they identify the project,
// not the bearer; security rules and the Firebase Admin SDK key (held
// server-side only) are what gate access.
const firebaseConfig = {
  // Restricted by API (Identity Toolkit + Token Service), NOT by HTTP
  // referrer. That distinction is the whole point: Electron sends no
  // Referer header, so a referrer-restricted key rejects every sign-in
  // with `auth/requests-from-referer-<empty>-are-blocked`. The previous
  // key (AIzaSyDTaGA…Xn8g) acquired exactly that restriction and broke
  // sign-in on 2026-08-18 — the second time this project has been bitten
  // by it: the same thing hit the cs clones on 2026-08-09, which is why
  // this server-side key was minted in the first place. Verified by
  // probing both keys against accounts:signInWithPassword — the old one
  // returns the referer error, this one reaches credential validation.
  // If you ever swap this, check the restriction TYPE, not just that a
  // key exists.
  apiKey: 'AIzaSyA_LnUBg1dfafu9RMMRNvAm4_ZTfjoHEEI',
  authDomain: 'talkmeapp-e696c.firebaseapp.com',
  projectId: 'talkmeapp-e696c',
  storageBucket: 'talkmeapp-e696c.appspot.com',
  messagingSenderId: '375340415237',
  appId: '1:375340415237:web:d0551e6e27d341eb7f9f6c',
  measurementId: 'G-Q5HNTEV6DH'
}

const app = initializeApp(firebaseConfig)

// IndexedDB-backed persistence so a signed-in user survives across app
// launches. The historic cross-window bleed (one BrowserWindow inheriting
// another window's `auth.currentUser`) is structurally prevented by the
// main process: every BrowserWindow is created with its own
// `webPreferences.partition` (`persist:firebase-<uid>` for bound profiles
// or `persist:firebase-pending-<uuid>` for fresh signin). Chromium scopes
// IndexedDB per partition, so each window's Firebase session is isolated
// even though they share the same renderer code. See `main/index.ts`
// (`createAuthPendingWindow` + `auth:bindProfile`) and
// `main/profileFS.ts` (`FIREBASE_PARTITION` in profile `.env`).
const auth = initializeAuth(app, { persistence: indexedDBLocalPersistence })
auth.useDeviceLanguage()

export { app, auth }
