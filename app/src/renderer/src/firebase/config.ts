import { initializeApp } from 'firebase/app'
import { inMemoryPersistence, initializeAuth } from 'firebase/auth'

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

// In-memory persistence: every window signs in independently and every
// app launch shows SignIn. IndexedDB is shared across all BrowserWindows
// of an Electron app, so a restored Firebase session would leak between
// concurrent windows (Window A sees Window B's identity). UID-keyed
// profile binding plus per-window in-memory auth give us the invariant
// "one window = one signin = one profile" with no shared state to drift.
const auth = initializeAuth(app, { persistence: inMemoryPersistence })
auth.useDeviceLanguage()

export { app, auth }
