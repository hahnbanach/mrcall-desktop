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
