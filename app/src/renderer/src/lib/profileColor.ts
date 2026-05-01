// Per-profile accent color derived deterministically from the profile email.
//
// Use case: a user opens N desktop windows, one per profile. Each window
// paints a unique accent so it's instantly distinguishable from the others.
//
// Hash: FNV-1a (32-bit). Tiny, deterministic, no deps. The hash isn't
// cryptographic — we just need a stable email -> integer fingerprint.

export interface ProfileColor {
  h: number // hue 0-359
  s: number // saturation %
  l: number // lightness %
  css: string // 'hsl(h s% l%)' — the vivid accent
  cssBg: string // 'hsl(h s% 95%)' — same hue, very light, good as soft bg
}

const FNV_OFFSET_BASIS = 0x811c9dc5
const FNV_PRIME = 0x01000193

function fnv1a32(input: string): number {
  let hash = FNV_OFFSET_BASIS
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i)
    // 32-bit multiply with FNV prime, kept unsigned via Math.imul + >>> 0
    hash = Math.imul(hash, FNV_PRIME) >>> 0
  }
  return hash >>> 0
}

export function profileColor(email: string): ProfileColor {
  const key = (email || '').trim().toLowerCase()
  const hash = fnv1a32(key)
  const h = hash % 360
  const s = 70
  const l = 50
  return {
    h,
    s,
    l,
    css: `hsl(${h} ${s}% ${l}%)`,
    cssBg: `hsl(${h} ${s}% 95%)`
  }
}

// --- inline sanity asserts (commented; kept for documentation) ---
//
// import { profileColor } from './profileColor'
//
// const a = profileColor('alice@example.com')
// const b = profileColor('alice@example.com')
// console.assert(a.h === b.h, 'deterministic: same email -> same hue')
//
// const samples = [
//   'alice@example.com',
//   'bob@example.com',
//   'foo@example.org',
//   'bar@example.org',
//   'support@acme.io'
// ]
// const hues = new Set(samples.map((e) => profileColor(e).h))
// console.assert(hues.size === samples.length, 'no hue collisions on 5-sample set')
