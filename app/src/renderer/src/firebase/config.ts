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

// In-memory persistence only. Earlier versions of this file used
// indexedDB + localStorage so the user stayed signed in across app
// restarts. That created a serious failure mode: a stale session for a
// previous user (or test account) was silently restored on startup, the
// SignIn screen never showed, and the renderer ended up bound to a
// Firebase identity the current operator did not just authenticate as.
// On-disk profile selection is keyed by Firebase UID (see main/index.ts
// auth:bindProfile), so a wrong identity = wrong profile = wrong data.
//
// Trade-off: the user must sign in on every app launch. For a desktop
// app where StarChat needs a live JWT anyway, that is a fair price for
// removing the silent-restore trap.
const auth = initializeAuth(app, { persistence: inMemoryPersistence })
auth.useDeviceLanguage()

export { app, auth }
