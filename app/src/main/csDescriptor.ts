/**
 * Machine-readable profile descriptor for the separate `cs` CLI
 * (`cs login`). Written to `<profilesDir>/<uid>/cs-descriptor.json` — the
 * same profiles tree `profileFS.ts` manages (`~/.zylch/profiles/<uid>/`)
 * — right after a successful Firebase sign-in, so a headless `cs` process
 * can mint its own session without ever going through the renderer.
 *
 * Contract (frozen, Phase B work item B2):
 *   {
 *     version: 1,
 *     email: "<mailbox>",
 *     uid: "<firebase uid>",
 *     engine_ws_url: "wss://desktop.mrcall.ai/ws/<uid>",
 *     firebase_web_api_key: "<see SERVER_API_KEY>",
 *     refresh_token: "<firebase refresh token>",
 *     written_at: "<iso8601>"
 *   }
 *
 * Mode 0600, atomic write (tmp + rename) — mirrors `lastProfile.ts`'s
 * pattern. The profile directory is assumed to already exist: `profileFS`
 * creates it at bind time, strictly before any token can be pushed for
 * that uid.
 */
import {
  existsSync,
  openSync,
  closeSync,
  fsyncSync,
  fchmodSync,
  writeFileSync,
  renameSync,
  unlinkSync
} from 'fs'
import { join } from 'path'
import { profileDir } from './profileFS'
import { readBackendConfig } from './backendConfig'

// Server-side web API key of the engine's Firebase project, restricted to
// Identity Toolkit + Token Service; public by design (a key alone mints
// nothing — exchanges require a valid refresh token); used by the `cs`
// CLI for headless token refresh; the browser key in
// `renderer/src/firebase/config.ts` stays separate and referrer-restricted.
export const SERVER_API_KEY = 'AIzaSyA_LnUBg1dfafu9RMMRNvAm4_ZTfjoHEEI'

// The engine runs vendor-side for now (decision 2): the per-uid path is
// `/ws/<uid>`, routed statically by Caddy.
export const VENDOR_WS_BASE = 'wss://desktop.mrcall.ai'

function csDescriptorPath(uid: string): string {
  return join(profileDir(uid), 'cs-descriptor.json')
}

/**
 * Resolve the WS URL the `cs` CLI should dial for `uid`.
 *
 * Remote mode (`backend-config.json` has `location: 'remote'` and a
 * `url`): derive from that URL's origin — normalize http(s) → ws(s)
 * defensively (the stored URL is already validated to be `ws://`/`wss://`
 * at write time by `settings:setBackendLocation`, but a hand-edited config
 * file could still carry an http(s) scheme), strip any trailing slash, and
 * append `/ws/<uid>`. This mirrors `WebSocketRpcClient.connectUrl()` byte
 * for byte — the same base-URL-plus-`/ws/<profile>` shape the app's own
 * transport uses to reach this exact engine — so the descriptor always
 * points at the same socket the app itself would connect to.
 *
 * Local mode: in local-app mode there is no locally listening WS endpoint
 * (stdio only), so the descriptor points at the vendor-hosted daemon.
 * Until that profile is provisioned vendor-side, `cs login`'s proof call
 * fails with a handled message — truthful and expected (plan §B4 owns
 * making it true).
 */
export function engineWsUrlFor(uid: string): string {
  const cfg = readBackendConfig()
  if (cfg.location === 'remote' && cfg.url) {
    const normalized = cfg.url
      .replace(/^http:\/\//i, 'ws://')
      .replace(/^https:\/\//i, 'wss://')
      .replace(/\/+$/, '')
    return `${normalized}/ws/${encodeURIComponent(uid)}`
  }
  return `${VENDOR_WS_BASE}/ws/${uid}`
}

export interface CsDescriptor {
  version: 1
  email: string
  uid: string
  engine_ws_url: string
  firebase_web_api_key: string
  refresh_token: string
  written_at: string
}

export interface WriteCsDescriptorArgs {
  uid: string
  email: string
  refreshToken: string
}

/**
 * Write (or refresh) the descriptor for `uid`, atomically (tmp + rename)
 * and mode 0600. The freshest refresh token always wins — this is a
 * cheap, idempotent overwrite meant to be called on every token push that
 * carries one, so no debounce.
 *
 * Never throws into the caller: any failure is logged (module convention:
 * `[csDescriptor]`-prefixed, same bracket-tag style as the rest of
 * `main/`) and swallowed.
 */
export function writeCsDescriptor({ uid, email, refreshToken }: WriteCsDescriptorArgs): void {
  const trimmedUid = (uid || '').trim()
  const trimmedEmail = (email || '').trim()
  if (!trimmedUid || !refreshToken || !trimmedEmail) {
    console.error(
      `[csDescriptor] writeCsDescriptor called with missing uid/refreshToken/email (uid=${trimmedUid ? 'set' : 'empty'}, refreshToken=${refreshToken ? 'set' : 'empty'}, email=${trimmedEmail ? 'set' : 'empty'}) — skipping`
    )
    return
  }
  try {
    const dir = profileDir(trimmedUid)
    if (!existsSync(dir)) {
      // Should not happen — profileFS creates the dir at bind time,
      // strictly before any token can be pushed for this uid. Defensive
      // only.
      console.error(`[csDescriptor] profile dir missing for uid=${trimmedUid} — skipping`)
      return
    }
    const descriptor: CsDescriptor = {
      version: 1,
      email: trimmedEmail,
      uid: trimmedUid,
      engine_ws_url: engineWsUrlFor(trimmedUid),
      firebase_web_api_key: SERVER_API_KEY,
      refresh_token: refreshToken,
      written_at: new Date().toISOString()
    }
    const finalPath = csDescriptorPath(trimmedUid)
    const tmpPath = finalPath + '.tmp'
    const fd = openSync(tmpPath, 'w', 0o600)
    try {
      // `openSync`'s mode argument only takes effect when the file is
      // freshly created; if a previous crashed write left a `.tmp` file
      // behind with different permissions, `'w'` (O_TRUNC) reuses that
      // inode as-is, so re-assert 0600 explicitly rather than inherit
      // stale permissions.
      fchmodSync(fd, 0o600)
      writeFileSync(fd, JSON.stringify(descriptor, null, 2) + '\n', 'utf8')
      fsyncSync(fd)
    } finally {
      closeSync(fd)
    }
    // Atomic replace via rename — same discipline as `writeLastProfile`
    // and `writeProfileEnvValue`.
    renameSync(tmpPath, finalPath)
    console.log(`[csDescriptor] wrote descriptor uid=${trimmedUid}`)
  } catch (e) {
    console.error(`[csDescriptor] writeCsDescriptor failed for uid=${trimmedUid}`, e)
  }
}

/**
 * Best-effort delete of `uid`'s descriptor.
 *
 * Exported for future sign-out wiring but DELIBERATELY NOT CALLED
 * anywhere yet — a signed-out profile should stop offering headless `cs`
 * access, but deciding where in the sign-out path that belongs (and
 * whether sign-out should also revoke the refresh token server-side) is
 * outside this task's scope.
 */
export function deleteCsDescriptor(uid: string): void {
  const trimmedUid = (uid || '').trim()
  if (!trimmedUid) return
  try {
    const p = csDescriptorPath(trimmedUid)
    if (existsSync(p)) {
      unlinkSync(p)
      console.log(`[csDescriptor] deleted descriptor uid=${trimmedUid}`)
    }
  } catch (e) {
    console.error(`[csDescriptor] deleteCsDescriptor failed for uid=${trimmedUid}`, e)
  }
}
