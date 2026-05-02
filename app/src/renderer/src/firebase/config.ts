import { initializeApp } from 'firebase/app'
import {
  browserLocalPersistence,
  indexedDBLocalPersistence,
  initializeAuth
} from 'firebase/auth'

// Same Firebase project as mrcall-dashboard. The API key + project ID are
// public-by-design (Firebase JS SDK config) — they identify the project,
// not the bearer; security rules and the Firebase Admin SDK key (held
// server-side only) are what gate access.
//
// Mirror of mrcall-dashboard/.env.development "Firebase Configuration
// (Production)" block — kept hard-coded here because:
//   - Electron renderers don't have process.env at runtime in packaged
//     builds (it's stripped by Vite); reading from a .env that ships with
//     the app would just be indirection without security benefit.
//   - The desktop app is MIT/public; embedding the public Firebase config
//     is consistent with how every Firebase web client ships its config.
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

// IndexedDB first (preferred — survives app restarts cleanly in Electron's
// chromium renderer), localStorage as fallback. Same combination the
// dashboard uses; Firebase Auth picks the first that's available at
// runtime.
const auth = initializeAuth(app, {
  persistence: [indexedDBLocalPersistence, browserLocalPersistence]
})
auth.useDeviceLanguage()

export { app, auth }
