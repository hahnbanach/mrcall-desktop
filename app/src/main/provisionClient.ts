/**
 * HTTPS client for the vendor-side `provisiond` service
 * (`engine/zylch/provisiond/`, reverse-proxied by Caddy at
 * `/api/provision*` on the vendor host — see
 * `engine/scripts/server/README-provisiond.md`).
 *
 * Two routes:
 *   - `POST /api/provision` — send this profile's Settings key/values;
 *     the service derives the target profile from the `sub` (uid) claim
 *     INSIDE the bearer token, never from the body. Starts a vendor-hosted
 *     `zylch-server@<uid>` daemon once B3's reconciler discovers the
 *     freshly-written profile dir.
 *   - `GET /api/provision/status` — same auth; returns where that
 *     provisioning attempt currently stands.
 *
 * Both functions take the Firebase ID token the caller already holds
 * (main's `windowTokens` cache, the same token the WS transport and
 * `backend:testConnection` use) — this module never mints or refreshes a
 * token itself.
 *
 * Errors never leak a raw HTTP status or stack trace to the renderer:
 * every failure resolves to `{ ok: false, code, message }` with an
 * ACTIONABLE message, never a thrown exception.
 */
import { readBackendConfig } from './backendConfig'
import { VENDOR_WS_BASE } from './csDescriptor'

export type ProvisionState = 'active' | 'preparing' | 'problem' | 'not_provisioned'

export type ProvisionResult =
  | { ok: true; uid: string; state: 'preparing' }
  | { ok: false; code: string; message: string }

export type ProvisionStatusResult =
  | { ok: true; state: ProvisionState }
  | { ok: false; code: string; message: string }

/**
 * Resolve the HTTPS origin `provisiond` is reachable at. Mirrors
 * `csDescriptor.ts::engineWsUrlFor`'s normalization byte-for-byte (remote
 * mode reads `~/.zylch/backend-config.json`, otherwise falls back to the
 * same `VENDOR_WS_BASE` constant the WS descriptor uses — no second
 * vendor-host literal), then converts the WS scheme to the matching HTTP
 * scheme: `provisiond` is a plain HTTPS service on the same host the WS
 * URL points at, not a WebSocket endpoint itself.
 */
function provisionOriginFor(): string {
  const cfg = readBackendConfig()
  const wsBase =
    cfg.location === 'remote' && cfg.url
      ? cfg.url
          .replace(/^http:\/\//i, 'ws://')
          .replace(/^https:\/\//i, 'wss://')
          .replace(/\/+$/, '')
      : VENDOR_WS_BASE
  return wsBase.replace(/^ws:\/\//i, 'http://').replace(/^wss:\/\//i, 'https://')
}

function provisionUrl(path: string): string {
  return `${provisionOriginFor()}${path}`
}

/**
 * Parse a provisiond JSON error body (`{"error": "..."}`), falling back
 * to a generic label when the body isn't JSON or doesn't carry that
 * shape (e.g. an intermediary — Caddy, a proxy — returned its own error
 * page).
 */
async function readErrorMessage(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { error?: string }
    if (typeof data.error === 'string' && data.error) return data.error
  } catch {
    // Not JSON — fall through to the generic label below.
  }
  return `HTTP ${res.status}`
}

/**
 * Translate a provisiond HTTP response into an actionable, renderer-safe
 * result. Never surfaces a raw status code or the underlying network
 * exception's stack — only the fixed `code` + a plain-English `message`.
 */
async function classifyErrorResponse(
  res: Response
): Promise<{ ok: false; code: string; message: string }> {
  const detail = await readErrorMessage(res)
  switch (res.status) {
    case 401:
      return {
        ok: false,
        code: 'session_expired',
        message: 'Your session has expired — please sign in again.'
      }
    case 409:
      return {
        ok: false,
        code: 'already_provisioned',
        message: 'This account is already provisioned and running.'
      }
    case 400:
      return {
        ok: false,
        code: 'bad_request',
        message: `The provisioning service rejected the request: ${detail}`
      }
    default:
      return {
        ok: false,
        code: 'server_error',
        message: `The provisioning service returned an unexpected error (HTTP ${res.status}).`
      }
  }
}

// A host that accepts the connection and then says nothing would otherwise
// hang forever: `fetch()` has no default timeout. The status route is polled
// from the renderer, so a silent host would pile up pending requests behind
// a spinner that never resolves. Provisioning writes a couple of small files
// server-side, so neither route has any business taking this long.
const REQUEST_TIMEOUT_MS = 20_000

/**
 * Wrap a `fetch()` call so any network-level failure (DNS, connection
 * refused, TLS, or a silent host hitting REQUEST_TIMEOUT_MS) collapses to
 * one actionable result instead of a thrown exception the caller would have
 * to catch.
 */
async function safeFetch(
  url: string,
  init: RequestInit
): Promise<{ ok: true; res: Response } | { ok: false; code: string; message: string }> {
  try {
    const res = await fetch(url, {
      ...init,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    })
    return { ok: true, res }
  } catch (e) {
    const timedOut = e instanceof Error && e.name === 'TimeoutError'
    console.error(`[provisionClient] request to ${url} failed`, e)
    return {
      ok: false,
      code: 'network_error',
      message: timedOut
        ? 'The MrCall provisioning service did not respond in time. Please try again.'
        : 'Could not reach the MrCall provisioning service. Check your internet connection and try again.'
    }
  }
}

/**
 * `POST /api/provision` — provision (or re-provision, if the profile is
 * not currently active) the caller's vendor-hosted profile with `values`.
 *
 * `values` should be the profile's Settings key/values, already filtered
 * to keys the service accepts (see `profileFS.ts::KNOWN_KEYS`) — this
 * function additionally strips `OWNER_ID` defensively before sending: the
 * service derives the owning uid from the token's `sub` claim and rejects
 * any `OWNER_ID` in the body as an unknown key (see `handler.py`'s
 * `KNOWN_KEYS` validation — `OWNER_ID` is injected server-side OUTSIDE
 * that check, deliberately not a client-editable field), so sending it
 * here would only turn a valid request into a 400.
 */
export async function provisionProfile(
  idToken: string,
  values: Record<string, string>
): Promise<ProvisionResult> {
  const { OWNER_ID: _ownerId, ...body } = values

  const attempt = await safeFetch(provisionUrl('/api/provision'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${idToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  })
  if (!attempt.ok) return attempt

  const { res } = attempt
  if (!res.ok) return classifyErrorResponse(res)

  const data = (await res.json()) as { uid?: string; state?: string }
  if (typeof data.uid !== 'string' || data.state !== 'preparing') {
    console.error('[provisionClient] unexpected 200 payload from POST /api/provision', data)
    return {
      ok: false,
      code: 'server_error',
      message: 'The provisioning service returned an unexpected response.'
    }
  }
  return { ok: true, uid: data.uid, state: 'preparing' }
}

/**
 * `GET /api/provision/status` — where the caller's vendor-hosted profile
 * currently stands: `active` (daemon running), `preparing` (provisioned,
 * daemon not up yet), `problem` (the daemon unit failed), or
 * `not_provisioned` (nothing on file for this uid).
 */
export async function getProvisionStatus(idToken: string): Promise<ProvisionStatusResult> {
  const attempt = await safeFetch(provisionUrl('/api/provision/status'), {
    method: 'GET',
    headers: { Authorization: `Bearer ${idToken}` }
  })
  if (!attempt.ok) return attempt

  const { res } = attempt
  if (!res.ok) return classifyErrorResponse(res)

  const data = (await res.json()) as { state?: string }
  const validStates: ProvisionState[] = ['active', 'preparing', 'problem', 'not_provisioned']
  if (typeof data.state !== 'string' || !validStates.includes(data.state as ProvisionState)) {
    console.error('[provisionClient] unexpected 200 payload from GET /api/provision/status', data)
    return {
      ok: false,
      code: 'server_error',
      message: 'The provisioning service returned an unexpected response.'
    }
  }
  return { ok: true, state: data.state as ProvisionState }
}
