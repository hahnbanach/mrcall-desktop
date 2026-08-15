---
status: active
owner: cross-cutting (engine + app + IPC + release)
created: 2026-05-31
discipline: |
  Mario's standard rules. NEVER claim a feature is "fixed", "done", or
  "verified" until Mario has used it himself end-to-end (Electron client
  on the Mac, backend on the Scaleway VPS) and confirmed it. Unit tests,
  typecheck, RPC probes and log lines do NOT count — the real system is
  "the backend runs 24/7 on the server, Electron attaches over WSS, and
  notifications arrive in real time". One phase at a time. Tell Mario
  exactly what to test. Wait. NEVER commit until he confirms it works.
  Italian register in the chat.
---

# Cross-machine transport (remote backend + thin client)

## Status — 2026-06-02 (in-progress)

- **Phase 1 ✅** (commit `5294587a`) — engine WS (`zylch serve --ws`), Firebase
  JWT handshake gate (`uid == OWNER_ID`), shared `dispatch_raw`, `auth.refresh`,
  4401-on-expiry. Live-validated on Mac.
- **Phase 2 ✅** (commit `5a4f378a`) — Electron thin client: `RpcClient`
  interface, `WebSocketRpcClient`, `Settings → Backend location` (Local/Remote),
  per-window token cache (`account:pushToken`, out-of-band so main can set the
  WS handshake header). Live-validated: identity + Tasks + Emails over WS.
  Fixes that landed here:
  - the WS client **queues early RPCs** and flushes on `open`, mirroring the
    stdio pipe — without it, views that mount before the socket connects fail
    with "not connected" (this was hiding the Email tab);
  - `ws`'s optional natives (`bufferutil`/`utf-8-validate`) must be `external`
    in `electron.vite.config.ts` or `electron-vite dev` won't bundle;
  - a spawn ENOENT now emits a clean `{alive:false}` status instead of crashing.
- **Phase 3a ✅** — engine deployed on the Scaleway VPS (`51.158.109.183`,
  Ubuntu 24.04 aarch64, py3.12) at `~/zylch-engine`, reached from the Mac via an
  **SSH tunnel** (`ssh -L 5174:127.0.0.1:5174 claude`). Proven: `settings.get` +
  `emails.list_inbox` served from the VPS, live.
- **Phase 3c ✅** — systemd **template** `zylch-server@<uid>.service` (artifact:
  `engine/scripts/systemd/zylch-server@.service`) + per-profile
  `/etc/zylch/<uid>.conf` (`ZYLCH_WS_ADDR=127.0.0.1:<port>`). Enabled (boot),
  auto-restart proven (`kill -9` → respawn, `NRestarts=1`).
- **Phase 3b ✅** (2026-06-02) — public TLS endpoint. **Caddy** v2.11 on the VPS,
  `desktop.mrcall.ai` (DNS-only A record → the IP), auto Let's Encrypt cert
  (tls-alpn-01). `reverse_proxy /ws/* 127.0.0.1:5174` → the engine. Engine gained
  `serve --unix <socket>`; the app's `WebSocketRpcClient` appends `/ws/<uid>`
  to a BASE URL (one machine-global config, per-window routing; an unrouted
  direct engine ignores the path → backward-compatible with the tunnel). Live-
  validated end-to-end: <prod-profile> over `wss://desktop.mrcall.ai`, no
  tunnel; auth gate proven (no token → engine 401 *through Caddy*). Also fixed: a
  reconnect crash (`terminate()` on a CONNECTING socket emitted an uncaught async
  'error' after `removeAllListeners`) and an infinite retry loop on 403.
  Artifact: `engine/scripts/caddy/desktop.Caddyfile`.

### Deploy method (updated 2026-06-04)
The engine is now installed/updated on the server **via git** — `git clone`
the (public / MIT) repo → `~/mrcall-desktop/engine`, `git pull` to update; no
credentials. The initial bring-up used `rsync` to `~/zylch-engine`, and the
systemd unit's `ExecStart` now points at the git path
(`~/mrcall-desktop/engine/venv`). The **profile** still moves by `rsync`
(private data, not in git). Operator guide + an exact agent runbook:
[`../remote-backend.md`](../remote-backend.md). NOTE: the live <prod-uid> daemon
was NOT re-deployed — it still runs from the original `~/zylch-engine` rsync
path; only new deploys use the git layout.

### Architecture correction (2026-06-01)
"One daemon per **Linux user**" — NOT per-Firebase-tenant. The engine is **one
process per profile** (fcntl lock + single active-profile globals: `settings`,
`Storage`, `owner_id`-from-env), so a user's N profiles map to N template
instances under their Linux account, fronted as one logical service. A true
single-process-multi-profile engine would be a meaningful refactor — deferred
unless required.

### VPS landscape
Already running: `mrcall-agent` (Docker `:8000`) + postgres (`:5432`); a node on
`:8080`. `:80`/`:443` free. No reverse proxy yet. `~/.zylch/profiles/` already
holds 4 profiles. All heavy aarch64/py3.12 wheels resolved cleanly.

### Pending
- **Multi-profile / multi-user routing** — ✅ **DONE / live 2026-06-05** (see
  [`multi-profile-routing.md`](multi-profile-routing.md)): `mrcalld` service user
  + per-uid Unix sockets + static Caddy `path_regexp` + `update-daemons.sh`.
  `<prod-uid>` migrated `mal`→`mrcalld`; multi-profile proven on one URL. (Caddy no
  longer points `/ws/*` at a single TCP daemon.)
- Multi-client broadcast + reconnect-resume → Phase 5.
- App Settings card: the URL field help should read "base URL (wss://host), no path".

## Next session — multi-profile / multi-user routing (brief)

> **SUPERSEDED 2026-06-05** by [`multi-profile-routing.md`](multi-profile-routing.md).
> Mario locked the design: a dedicated `mrcalld` service user owns + runs ALL
> profiles (NOT per-Linux-user `systemctl --user`/linger), and per-uid **Unix
> sockets** (NOT TCP ports), so every user shares the one
> `wss://desktop.mrcall.ai` URL and the app needs no change. Read that plan; the
> sketch below is kept for context only.

**Goal.** Serve *many* profiles (and many Linux users) over the one
`wss://desktop.mrcall.ai` endpoint, each routed to its own engine daemon. The app
already appends `/ws/<uid>`; the missing piece is per-uid routing on the server so
each window reaches *its* backend.

**Why it's blocked today.** The `Caddyfile` proxies `/ws/* → 127.0.0.1:5174` (one
upstream = the <prod-uid> daemon). Any non-<prod-uid> token → the gate returns 403
(correct behaviour). The engine's `--unix` socket support exists and is tested
locally, but is NOT yet used on the VPS.

**Target design (already explained + agreed with Mario).**
- One daemon per profile on a **Unix socket named by uid**:
  `zylch -p <uid> serve --unix /run/zylch/<uid>.sock`. No TCP-port juggling,
  no collisions across users (the firebase uid is globally unique).
- **Caddy routes by the uid in the path:**
  ```
  desktop.mrcall.ai {
      @ws path_regexp uid ^/ws/([^/]+)
      reverse_proxy @ws unix//run/zylch/{re.uid.1}.sock
  }
  ```
- **`/run/zylch/`** is a shared dir so Caddy (user `caddy`) can reach every user's
  socket: `tmpfiles.d` `d /run/zylch 2775 <owner> caddy -` (setgid → sockets
  inherit group `caddy`), and the daemon runs with `UMask=0007` so the socket is
  group-writable (caddy can connect).
- **Per Linux user**: their own daemons via `systemctl --user`
  (`loginctl enable-linger <user>` once) — runs as that user, locks its own
  `~/.zylch/profiles/<uid>/`. (The current 3c unit is system-level `User=mal`;
  evolve it to a `--user` template, or keep system units with the per-uid socket.)
- **Security boundary stays the JWT gate** (`uid==OWNER_ID`) per daemon: a
  mis-route fails 403, so routing is a hint, not the security. (Assumes the Linux
  users are trusted — Mario's own server. For hostile multi-tenancy, namespace
  sockets per user + a registry.)

**Concrete steps.**
1. Switch the `Caddyfile` to the `path_regexp` per-uid socket form.
2. Create `/run/zylch/` (tmpfiles.d, group `caddy`, setgid); add `UMask=0007` and
   `--unix /run/zylch/%i.sock` to the systemd unit ExecStart.
3. Migrate the <prod-uid> daemon to `--unix`; verify <prod-profile> still works
   over `wss://` (regression).
4. Add the `<your-account>` (uid `<uid-2>…`) daemon: its VPS DB is **empty** —
   `rsync ~/.zylch/profiles/<uid-2>…/ claude:.zylch/profiles/<uid-2>…/` from the Mac (or
   `zylch -p <uid-2>… update` on the VPS) — then `enable --now`. Verify
   `wss://desktop.mrcall.ai/ws/<uid-2>…` with <your-account>'s token serves his data.
5. For another Linux user: `enable-linger`, their own `systemctl --user` daemons;
   sockets land in the shared `/run/zylch/`.

**Open decisions.** `systemctl --user` (linger) vs system units; flat `/run/zylch`
+ group `caddy` (trusted) vs per-user namespacing; how each user's profile data
reaches the VPS.

## What Mario asked for

*(translated from Mario's Italian)*

> "Is it possible to start the backend on one machine and the frontend
>  (Electron) on another? […] One cool thing about Claude Code is that I
>  can start it on the server and then carry on remotely from Claude
>  Desktop. Once we have it over TCP, does that open the way to an app?"

Two coupled goals:

1. **A persistent backend on the server, a thin client on the user's machine.**
   The Python `zylch` sidecar runs as a daemon on a VPS (Scaleway, the same
   one already running `mrcall-agent` / `starchat`); Electron attaches over
   WSS when the user opens the laptop. No more "if I close the MacBook
   everything stops".
2. **Client-agnostic transport.** Once cross-machine is unblocked, a future
   mobile app (iOS/Android/RN) is simply another client on the same
   WebSocket. This plan **does not build the mobile app**, but it doesn't
   foreclose it either — the transport, auth and file-handling decisions are
   taken with both clients in mind.

## Current state: what exists vs what is missing

### Already there ✅

| Piece | Where | Notes |
|---|---|---|
| Transport-agnostic RPC dispatch table | `engine/zylch/rpc/methods.py` | Takes `(method, params)`, returns result/error. Knows nothing about stdio. |
| Server-side owner identity | every RPC method | The client never sends `owner_id` — the server resolves it from the active profile (fcntl lock). Survives a transport change. |
| Firebase JWT as auth towards StarChat | `engine/zylch/account_session.py`, `MrCallProxyClient`, `make_starchat_client_from_firebase_session` | The token is in-memory in the sidecar, never persisted. The "client pushes, server uses it as an auth header" model is already proven. |
| Bidirectional notifications | `tasks.solve.event`, `update.run.progress`, `whatsapp.message.received` | Already a stream pattern; the main process re-emits them to the renderer over IPC. The transport changes, the semantics don't. |
| SSE streaming from Anthropic | `engine/zylch/llm/proxy_client.py` `stream(...)` | Reentrant; fine from remote. |
| OAuth PKCE infrastructure | `app/src/main/googleSignin.ts` (Firebase), Calendar `:19275`, MrCall legacy `:19274` | **Already client-side.** A reusable pattern for "loopback stays on the client, the token flies to the server over RPC". |

### Missing ❌

- **A WebSocket server on the sidecar side.** Today `zylch.rpc.server` speaks only line-delimited JSON-RPC over stdin/stdout.
- **Daemon mode on the sidecar side.** `zylch` is designed to run inside Electron's `spawn()→use→kill()` cycle. Missing: starting as a daemon (`zylch serve --ws 0.0.0.0:5174`), signal handling (clean SIGTERM), a restart policy, log rotation, a healthcheck.
- **TLS termination.** A decision (see Open Q #2): wss directly via a local certificate (rustls/uvicorn-ssl), or behind a reverse proxy (Caddy/nginx) doing TLS + Let's Encrypt.
- **Channel auth.** Today it is "you are my child process, I trust you". Cross-machine: the WS server must gate the bearer Firebase JWT at connect (and re-verify it periodically — Firebase tokens expire every ~1h).
- **An abstracted client-side transport.** `app/src/main/` today spawns a binary and talks over pipes. It would need an `RpcClient` abstraction with two implementations: `StdioRpcClient` (today) and `WebSocketRpcClient` (new); the choice comes from config.
- **Settings UI for the remote backend.** "Local mode (default)" vs "Remote backend at wss://…". Persistence, URL validation, disconnect/reconnect handling.
- **An OAuth callback hosting strategy.** PKCE lands on `127.0.0.1:19275` today (Calendar). Cross-machine: the user's browser is on the client, the sidecar is on the server. Three concrete options; decision in Open Q #5.
- **Cross-machine WhatsApp QR.** Today neonize prints the QR on the Python process's terminal. Cross-machine: it must be emitted as a `whatsapp.qr.event` notification carrying the QR bytes (string / PNG b64) for the renderer to draw.
- **Cross-machine file operations.** `read_document`, `download_attachment_tool` and `files.read` work against the backend's filesystem. The user's paths on the client (e.g. `~/Downloads/foo.pdf`) do NOT exist on the server. `files.upload(local_path, bytes)` / `files.download(server_path) -> bytes` RPCs are needed to bridge them.
- **Multi-client broadcast.** Today a single Electron talks to the sidecar. Cross-machine opens the "same identity, two connected clients" scenario (work laptop + home). Broadcast notifications `tasks.changed`, `emails.changed` are needed for every client subscribed to the same profile. (Notifications today are per-client; the dispatch table emits them to the caller.)
- **Reconnect + resume.** The WS drops. Sequence numbers or a resume token, so in-flight notifications aren't lost.
- **Fcntl lock semantics.** The lock already exists and is fine as it is (a singleton process per profile). Cross-machine: no change. The delicate point is that a "local spawn" client and a "remote" client must not coexist on the same profile — the fcntl lock already protects that naturally.

## Proposed architecture

```
┌──────────────── server (Scaleway VPS) ─────────────────┐
│                                                          │
│   systemd: zylch-server.service                          │
│   ──────────────────────────────────────────             │
│   zylch serve --ws 127.0.0.1:5174 \                      │
│                --profile <uid>                            │
│   │                                                       │
│   ├── fcntl lock on ~/.zylch/profiles/<uid>/             │
│   ├── WebSocket server (auth = Firebase JWT bearer)      │
│   ├── the same RPC dispatch table                        │
│   └── per-profile notification broadcast                 │
│                                                           │
│   Caddy / nginx                                          │
│   ──────────────────────────────────────────             │
│   wss://desktop.mrcall.ai/zylch  →  127.0.0.1:5174       │
│   (TLS termination + Let's Encrypt)                       │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │  wss + bearer JWT
                          │
┌──────────────── client (Mac / iOS) ────────────────────┐
│                                                          │
│   Settings → Remote backend: wss://desktop.mrcall.ai     │
│                                                          │
│   app/src/main/RpcClient.ts                              │
│   ──────────────────────────────────────────             │
│   if (cfg.mode === 'remote'):                            │
│       WebSocketRpcClient(cfg.url, firebaseJwtFactory)    │
│   else:                                                   │
│       StdioRpcClient(spawn('zylch', …))                  │
│                                                          │
│   PKCE OAuth → loopback stays local (browser is here)    │
│   → after exchange, RPC oauth.installTokens(provider,    │
│     access_token, refresh_token) to the server.          │
│                                                          │
│   WhatsApp QR → notification → rendered in the renderer  │
│                                                          │
│   File ops → files.upload / files.download over RPC      │
└──────────────────────────────────────────────────────────┘
```

### Key decisions

**D1 — WebSocket instead of HTTP+SSE.**
WebSocket is symmetric (notifications are natural, not simulated with long-polling), supports backpressure, and maps 1:1 onto the current line-delimited JSON-RPC model (one message per frame). HTTP+SSE would require two separate channels (POST for requests, GET/SSE for notifications) plus idempotency tokens. More complex for the same functionality.

**D2 — Two coexisting transports on the sidecar side (transitional).**
The sidecar keeps exposing stdio when launched without `serve`, and WebSocket when launched with `serve --ws addr:port`. One RPC code path, two I/O adapters. No regression for users who want to stay fully local: `spawn()` + stdio works identically. **We do not remove stdio** — it is useful for debugging, for dev without a server, and for the "privacy-first by default" model (no server = no data leaving the Mac).

**D3 — Auth: Firebase JWT bearer + periodic re-verification.**
- At `WebSocket connect`: header `Sec-WebSocket-Protocol: bearer.<jwt>` (the standard workaround for passing auth over WS, since a custom `Authorization` header isn't available in every client). Server: verify the JWT against Firebase's public `securetoken.google.com`, extract the uid, gate it (`uid` == the locked profile's `OWNER_ID`).
- Token refresh: every N minutes (5? 30?) the client sends `auth.refresh(<new_jwt>)`. The server verifies it and updates the in-memory token. If the client is late past expiry, the server closes the WS with close code 4401 (custom: "JWT expired, reconnect with a fresh token"); the client renegotiates.
- Server-side we do NOT persist the JWT (as today). In-memory only.

**D4 — Profile lock and multi-client.**
- The sidecar daemon keeps the fcntl lock on the profile dir as it does today. A singleton process per profile, n clients connected to the sidecar.
- Notifications are per-caller today (emitted to the caller of the method that triggered them). Extend them to a per-profile broadcast: `tasks.changed`, `emails.changed`, `whatsapp.message.received`, `update.run.progress` go to ALL clients connected to the profile session (today only to whoever called).
- Implementation: a `NotificationBus` (which today doesn't exist as a unified object) collects WebSocket subscribers per profile id and fans out. Stdio remains a single subscriber (the local Electron main process).

**D5 — The OAuth callback stays on the client.**
Three options considered; the third is the choice.
1. ❌ **SSH port-forwarding of 19275 from the server to the client.** Fragile, requires OS-specific setup, fails behind the customer's NAT.
2. ❌ **Device-code flow.** Google supports it for some scopes but it changes the UX (a code to type). MrCall delegated OAuth doesn't support it.
3. ✅ **Loopback stays on the client, the final token travels to the server over RPC.** The client runs PKCE as it does today (browser → `127.0.0.1:19275` → code exchange → access+refresh token). It then calls a NEW `oauth.installTokens(provider, access_token, refresh_token, expires_at)` RPC. The server encrypts and persists into `OAuthToken` with Fernet. It works identically for Calendar (Google), Firebase (which already does this), and a future MrCall.

   A side benefit: the `client_secret` (where needed) stays in the client (`app/src/main/oauthSecrets.ts`) and never has to travel server-side.

**D6 — WhatsApp QR over the notification stream.**
Neonize exposes the QR as a string (the "raw" otp:// URL payload). The sidecar emits it as a `whatsapp.qr.event` notification with `{ raw: string, png_b64?: string }` (the PNG generated server-side with Python `qrcode`). The renderer draws it in the dedicated `ConnectWhatsApp.tsx` view. Mario scans it from his phone.

`~/.zylch/whatsapp.db` (the neonize session) **stays on the server** — the WhatsApp session belongs to the server, not to the client. Changing client (laptop → mobile) does not require re-pairing.

**D7 — File operations: explicit upload/download.**
Two new RPCs:
- `files.upload(stream)` (chunked WS binary frames) → returns the server-side path (e.g. `~/.zylch/profiles/<uid>/uploads/<sha256>.bin`).
- `files.download(server_path, range?)` (chunked WS binary) → bytes.

`read_document` and `download_attachment_tool` keep working on server-side paths. The "user-facing" upload (drag & drop in the renderer) uses `files.upload` to get the file to the server, then hands the tool the server-side path. Same for "download attachment": the server prepares the file, the client `files.download`s it and saves it wherever the user chooses (system dialog).

**D8 — Reconnect + resume.**
- Every emitted notification carries a monotonic per-profile sequence number.
- The client keeps the last-seen sequence in volatile storage (memory; persisting it to disk is overkill for short disconnects).
- On reconnect the client sends `session.resume(last_seq)`. The server replays the notifications between `last_seq+1` and now (an in-memory per-profile ring buffer, ~the last 1000 events). If it is too old, the server answers `{ replayed: false }` and the client hard-refreshes the views.
- Buffer TTL: 10 minutes, enough for typical disconnects.

**D9 — Compat mode + onboarding.**
- Fresh-install default: **local mode** (local spawn). Zero change for anyone who wants a privacy-first stand-alone.
- Settings → "Backend location": a `Local (default)` / `Remote backend` radio. The second reveals a URL input + a "Test connection" button.
- Onboarding does not ask about the remote backend in the initial wizard. It is configurable only afterwards, in Settings.

## Phasing

### Phase 0 — preparation and decisions

- Mario answers the Open Qs below (which server, TLS strategy, recreating the client_secret for remote, the default broadcast policy).
- Sketch the WebSocket server in `engine/zylch/rpc/server_ws.py` on a throwaway branch to measure the delta against the current `server.py` (stdio).
- Decide "Caddy in front vs uvicorn-ssl directly" on the Scaleway VPS, based on whether StarChat and mrcall-agent already have a reverse proxy.

**STOP. Mario answers. Do NOT start Phase 1 before that.**

### Phase 1 — WebSocket server on the sidecar, dual transport

- `zylch serve --ws <addr:port> --profile <uid>` as a new CLI subcommand.
- `engine/zylch/rpc/server_ws.py`: the WebSocket server (FastAPI? aiohttp? raw `websockets`?), the same dispatch table as `server.py` (stdio). Owner-scoped as today.
- Auth handshake: `Sec-WebSocket-Protocol: bearer.<jwt>`. Verified against the Firebase Admin SDK (server-side). Extract the uid; gate against the profile's OWNER_ID.
- An `auth.refresh(jwt)` RPC. Disconnect on expiry with close code 4401.
- Logging of connect/disconnect/auth failures (never the JWT).
- Tests: pytest driving a WS client + a mock JWT, round-tripping `account.whoAmI()`.

No client side yet. The dual-mode sidecar (stdio + ws) is verifiable via `wscat` or a test script.

**STOP. Mario boots `zylch serve --ws 127.0.0.1:5174 --profile <uid>` on the server (or on the Mac for a local test), attaches with `wscat`, and verifies that `whoAmI()` returns the right identity with the bearer JWT.**

### Phase 2 — thin client: the RpcClient abstraction + Remote backend in Settings

- `app/src/main/RpcClient.ts`: an interface `{ call(method, params, timeout), subscribe(event, handler), close() }`.
- Refactor `app/src/main/index.ts`: extract the current spawn+pipe as `StdioRpcClient implements RpcClient`. No behaviour change.
- A new `WebSocketRpcClient implements RpcClient`. Connects with the bearer Firebase JWT (taken from the renderer as today). Auto-reconnect with backoff. `auth.refresh` every ~30 min.
- Settings UI: `LLMProviderCard` already has the radio pattern. A new `BackendLocationCard`: `Local` / `Remote (wss://…)`. A "Test connection" button → `whoAmI()`.
- Persisted in `~/Library/Preferences/...` (Electron `app.getPath('userData')`) — NOT in the profile dir (the backend choice is per-client, not per-profile).
- A window reload is required when the mode changes (simpler than re-attaching at runtime — the sidecar lifecycle was designed as "one per window-session").

**STOP. Mario opens Settings, sets the wss://… of his own test deployment, restarts the window, IdentityBanner shows the identity correctly, and the Email/Tasks/Workspace tabs populate over WS.**

### Phase 3 — production-grade TLS + a systemd daemon

- A `zylch-server.service` unit for the Scaleway VPS (Mario provides the specific machine).
- Caddy or nginx in front for Let's Encrypt TLS + HTTP→HTTPS redirect + WS upgrade.
- An HTTP GET `/health` endpoint (separate from the WS) for probes.
- Deploy documentation in `docs/execution-plans/cross-machine-transport.md#deploy` (below, once the decisions are made).
- The `engine/zylch/cli/main.py` `serve` subcommand documented in `engine/docs/guides/`.

**STOP. Mario clicks "Test connection" against the real VPS from the Mac, sees reasonable latency (< 200 ms RTT), and runs `zylch -p <uid> update` over WS (no longer via a local spawn).**

### Phase 4 — client-side OAuth callback hosting + the `oauth.installTokens` RPC

- A new `oauth.installTokens(provider, access_token, refresh_token?, expires_at?)` RPC on the sidecar. Fernet-encrypted, persisted in `OAuthToken`. Owner-scoped.
- `app/src/main/calendarSignin.ts` (mirroring `googleSignin.ts`): PKCE on `127.0.0.1:19275`, local code exchange, then `await zylch.oauth.installTokens('google_calendar', …)`.
- Settings → "Connect Google Calendar" works identically for local and remote.
- `Firebase` sign-in: already client-side (PKCE in `googleSignin.ts`), the JWT flies over `account.set_firebase_token` as today. No change.

**STOP. Mario clicks Connect Google Calendar in remote mode, completes OAuth in the local browser, the remote sidecar receives the tokens, and a `calendar.listEvents()` RPC returns real events.**

### Phase 5 — cross-machine WhatsApp QR + multi-client broadcast + reconnect resume

- The `whatsapp.qr.event` notification (`{ raw, png_b64 }`). The renderer in `ConnectWhatsApp.tsx` renders the b64 PNG.
- A server-side `NotificationBus`: a per-profile subscriber list, fan-out on `tasks.changed`, `emails.changed`, `update.run.progress`.
- Sequence numbers + a 1000-event ring buffer + the `session.resume(last_seq)` RPC.
- File operations: the `files.upload(chunks)` + `files.download(server_path, range?)` RPCs.

**STOP. Mario: (a) connects WhatsApp from the Mac by scanning the QR with his phone while the sidecar runs on the VPS; (b) opens the same profile from a second Electron (e.g. the home laptop), modifies a task, and verifies the main window updates; (c) drops the connection (kill Wi-Fi), waits 30s, reconnects, and verifies recent notifications are replayed.**

### Phase 6 — documentation + harness gaps

- `docs/cross-machine-deploy.md`: the server deploy guide.
- `engine/docs/guides/zylch-serve.md`: the CLI reference.
- `docs/active-context.md` + `engine/docs/active-context.md` + `app/docs/active-context.md` updated with the new transport.
- `docs/ipc-contract.md` extended with `auth.refresh`, `oauth.installTokens`, `session.resume`, `files.upload`, `files.download`, `whatsapp.qr.event`.
- `docs/harness-backlog.md`: new gates (a `WebSocketRpcClient`/`StdioRpcClient` API-surface mismatch; expired Let's Encrypt certificates; replay-buffer overflow logging).

## Files touched

```
engine/zylch/rpc/server_ws.py                NEW (WebSocket server, same dispatch)
engine/zylch/rpc/notification_bus.py         NEW (subscriber list + fan-out + resume ring buffer)
engine/zylch/rpc/methods.py                  +auth.refresh, +oauth.installTokens, +session.resume,
                                              +files.upload, +files.download
engine/zylch/cli/main.py                     +serve subcommand
engine/zylch/account_session.py              auth.refresh handler (in-memory token update)
engine/zylch/storage/storage.py              (nothing new — install_oauth_tokens uses existing helpers)
engine/zylch/whatsapp/client.py              emit whatsapp.qr.event instead of printing the QR
engine/scripts/systemd/zylch-server.service  NEW (deploy artifact)
engine/scripts/caddy/zylch.caddyfile          NEW (deploy artifact, if Caddy)

app/src/main/RpcClient.ts                    NEW (interface)
app/src/main/StdioRpcClient.ts               NEW (refactor of the current spawn+pipe)
app/src/main/WebSocketRpcClient.ts           NEW
app/src/main/calendarSignin.ts               NEW (local PKCE → oauth.installTokens RPC)
app/src/main/index.ts                        refactored to use RpcClient
app/src/preload/index.ts                     bindings for auth.refresh, oauth.installTokens, session.resume, files.*
app/src/renderer/src/types.ts                extended ZylchAPI surface
app/src/renderer/src/views/Settings.tsx      +BackendLocationCard
app/src/renderer/src/views/ConnectWhatsApp.tsx  renders the b64 PNG QR from the notification
app/src/renderer/src/components/IdentityBanner.tsx  shows "Remote: wss://…" when active

docs/ipc-contract.md                         +auth.refresh, +oauth.installTokens, +session.resume,
                                              +files.upload, +files.download, +whatsapp.qr.event
docs/active-context.md                       cross-cutting state updated
docs/harness-backlog.md                      new gates
docs/cross-machine-deploy.md                 NEW (operator guide)
engine/docs/guides/zylch-serve.md            NEW (CLI ref)
```

## Open design questions for Mario (answer BEFORE Phase 1)

1. **Backend host.** A dedicated Scaleway VPS (a new container?), or does it ride on a machine already running `mrcall-agent`/`starchat`? Which unix user owns the `~/.zylch/profiles/<uid>/` profile dir, and under what backup policy?

2. **TLS termination.** Caddy in front (auto Let's Encrypt + zero-conf), nginx (more control), or uvicorn/aiohttp directly with an SSL context? My recommendation: Caddy, it's simple.

3. **`auth.refresh` cadence + close-code policy.** Refreshing every 30 min is a compromise between "don't hammer the server" and "don't leave tokens about to expire". Suggestion: a preventive refresh every 30 min + a forced refresh when the server answers 4401. Is that fine?

4. **Broadcast notification policy.** When two Electrons are connected to the same profile, do we want:
   - **(a)** ALWAYS broadcast — every `tasks.changed` goes to every client, even if one of them is the source of the event; or
   - **(b)** broadcast to everyone EXCEPT the sender — the client that called `tasks.complete` gets the standard RPC confirmation, the others get `tasks.changed`.
   Recommendation: **(b)** — less traffic, fewer UI-side race conditions (the caller can update optimistically).

5. **OAuth callback hosting, confirm.** To confirm: the PKCE loopback stays on the client (Mac), the final token goes to the server via `oauth.installTokens`. Cost: Google's client_secret still has to live in the Electron bundle (as today). The alternative — recreating a "server-side" OAuth client and doing the whole flow on the server — would require Mario to open a browser on the server (impractical on a headless VPS) and is discarded. OK?

6. **Profile-per-client vs shared profile.** Cross-machine opens three scenarios:
   - **(a)** one profile per client (Mario at work: profile A; Mario at home: profile B). No broadcast, no lock issues.
   - **(b)** a single profile, two clients connected simultaneously (multi-window cross-machine).
   - **(c)** a single profile, only one client at a time (the fcntl lock protects you from the second connect; or the server kicks the old one).
   Recommendation: **(b)**, because it is the use case you stated ("backend always on, different clients"). It implies D4 + Phase 5 broadcast. Confirm?

7. **Compat-mode persistence.** When the user chooses "Remote", is the choice per-installation (on that specific Mac) or per-profile? Recommendation: per-installation, in Electron's `userData` — the Firebase identity is the same, but "where I talk from" is a property of the machine you're on.

## Out of scope for this plan

- **A mobile app (iOS/Android/RN).** The WS transport is the foundation, but a mobile app has decisions of its own: push notifications via APNs/FCM (the server must be able to notify new tasks to a closed app), a reduced UI, an offline cache, background fetch. It will be a separate execution plan after this one's Phase 5.
- **End-to-end encryption on the channel.** TLS is enough for the current threat model ("a server I own on my own VPC, traffic in the clear internally"). E2E on top of TLS only if it is ever hosted on a third-party PaaS.
- **Automatic migration of an existing profile dir.** If Mario already has `~/.zylch/profiles/<uid>/` on the Mac and wants to move it to the server: a manual rsync. Documented in the deploy guide, not automated.
- **Multi-region / load balancing.** One backend per profile (fcntl lock). No HA.
- **Outbound tools** (`InitiateCallTool`, `SendSMSTool`): orthogonal, see `mrcall-pipeline-parity.md` Out of scope.

## How to start the next session

1. Open this file. Re-read the discipline header.
2. **Phase 0 BEFORE touching code**: Mario answers the 7 Open Qs above. Do NOT start Phase 1 first.
3. Phase 1 = a single PR (`zylch serve --ws`, `server_ws.py`, the auth handshake, a smoke test via `wscat`). Land it. Mario tests the connection from the CLI. Then Phase 2.
4. One phase at a time. Tell Mario exactly what to test at every STOP. Wait for his confirmation.
5. NEVER push to origin. NEVER commit without an explicit go-ahead.
