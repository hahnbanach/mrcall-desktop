---
status: planned
priority: |
  nice-to-have. Electron stays the primary client; web/mobile is an
  "emergency" convenience, is not on the roadmap and blocks nothing. If
  Mario asks for it in the future (possibly having forgotten it exists):
  remind him and restart FROM THIS BRIEF, not from scratch.
owner: cross-cutting (engine + app + IPC + a new web client)
created: 2026-06-02
depends-on: cross-machine-transport.md (Phase 1–3 must be live FIRST)
discipline: |
  Mario's standard rules. This is an analysis BRIEF, not code: when it is
  picked up, one phase at a time, NEVER claim "done"/"it works" until
  Mario has used it end-to-end (daemon on one machine, PWA client from a
  browser/phone) and confirmed. Unit tests / typecheck / RPC probes do
  NOT count. Tell Mario exactly what to test, wait, NEVER commit without
  his confirmation. Italian register in the chat.
---

# Thin web/mobile client on top of the cross-machine transport

> **A brief, not an execution plan — NICE-TO-HAVE, deferred.** It captures
> the 2026-06-02 analysis. Electron stays the primary client; this is not
> on the roadmap and blocks nothing. Work does not start until
> `cross-machine-transport.md` has delivered the WS server + JWT auth +
> TLS (its Phase 1–3). The document exists so the analysis isn't lost, and
> so that — if Mario asks for it having forgotten — he can be reminded the
> brief already exists: restart from here, not from scratch.

## The model Mario fixed

- **Electron stays the preferred client.** Web/mobile are thin
  **"emergency"** clients: you attach to one when you don't have the Mac
  in front of you.
- **Single-tenant.** One daemon, one profile, on a machine that is yours.
  You start it and you connect to it. No SaaS, no multi-user, no per-tenant
  supervisor. (That large cost is out of scope — see below.)
- **Single-active-client with "last one wins" eviction.** *Mario's explicit
  correction:* NOT "one profile / N clients together". It is **one active
  client at a time**: if you open remotely, **the daemon closes the session
  of the Electron back home**. This is option **Q6=(c)** of
  `cross-machine-transport.md`, the "the server kicks the old one" variant.

The consequence simplifies everything: no multi-client broadcast, no races
between clients, one cursor, one state.

## Why it is nearly free: the seam already exists

The renderer (`app/src/renderer/`, ~9,000 lines of `.tsx`, 12 views)
**never imports Electron** — it talks only to `window.zylch.*`, i.e. the
`ZylchAPI` interface (`app/src/renderer/src/types.ts`). Whoever provides
`window.zylch` is interchangeable. Splitting the preload
(`app/src/preload/index.ts`):

- **~40 methods are pure RPC** (`call(method, params)` → sidecar): all of
  `tasks.*`, `emails.*`, `chat.*`, `update.run`, `settings.*`,
  `account.*`, `mrcall.*`, `memory.*`, `narration.*`, and the
  `connect/status` pairs of `google.calendar` and `whatsapp`. **They don't
  change by a single line**: only *who* executes `call()` changes — no
  longer preload→main→stdio but a direct WS connection from the browser.
  It is the same `RpcClient` as the transport plan (Phase 2), except that
  in the PWA it lives in the browser, not in the main process.
- **~13 are "main-only" IPCs** (`ipcRenderer.invoke` on non-RPC channels) =
  the Electron glue to be redone. Two families:
  1. **Platform shims, trivial:** `files.select` (dialog → `<input
     type=file>`), `shell.openExternal` (→ `window.open`),
     `signin.googleStart` (loopback PKCE `:19276` → Firebase **Web SDK**
     `signInWithPopup`, which is *simpler* in the browser).
  2. **State/lifecycle that must be server-side for any remote client:**
     `onboarding.createProfile*` (today it writes to the local disk),
     `profiles.list`, `profile.current`, `auth.bindProfile`.
     **In our model the emergency client does NOT need these**: you create
     and configure the profile from Electron; the PWA assumes a
     ready daemon and only connects to it.

The Electron main process (~2,176 lines) is the conceptual delta; but the
emergency client needs only a fraction of it (the family-1 shims).

## Decisions reached

### W1 — The emergency client is a PWA, NOT a native app
A single web codebase covers desktop *and* mobile browsers; installable to
the home screen as a PWA (feels like an app, no App Store, no review, no
signing). **The "I open it when it's urgent" access pattern removes the
need for APNs/FCM push** — which was cost #1 and the only real reason to go
native. You don't depend on background delivery: you open on demand and do
a full load at connect. If one day you want "ping me with the client
closed", the **PWA's Web Push** (service worker; Android Chrome, iOS 16.4+
on an installed PWA) covers much of it without going native. **Native
mobile: deferred indefinitely.**

### W2 — Single-active-session: the eviction is new daemon logic, NOT the fcntl
A critical distinction (the transport plan conflates it in Q6c):
- **fcntl flock** (`engine/zylch/cli/profiles.py`) guarantees **one
  *daemon* per profile directory**. All clients hit the *same* daemon
  process → the lock does NOT distinguish between them.
- **Client eviction** is a **new policy inside the WS server**: "at most
  one active WS session per profile; the last one wins". A new
  authenticated WS for the profile → the daemon closes the previous one.

### W3 — The takeover must be clean (the reconnection-war trap)
The transport plan (Phase 2) foresees "auto-reconnect with backoff". If it
is generic → an endless ping-pong: A closed → A reconnects → closes B → B
reconnects → … Nobody can use it. The fix is **semantic close codes**:
- **"superseded"** (e.g. custom close code `4409`) → the client goes
  **passive**, with a "Session open elsewhere" banner and **NO
  auto-reconnect**; only a manual **"Resume here"** button takes control
  back (evicting the other).
- **"network drop"** (1006/1001) → that one does auto-reconnect with backoff.

Distinguishing the two cases is the *only* thing separating "it works" from
"two windows tearing each other apart". To be added to the transport plan's
D3 as the twin of the auth handshake.

### W4 — Resume re-scoped: it is the signature feature, not a detail
Resume (D8 of the transport plan) is **not** for synchronising several
clients (there is only one). It is for **re-attaching the single active
client to long-running daemon-side operations across a takeover**: you
start an `update` or a `tasks.solve` from Electron, close the laptop, open
the phone → the phone takes control and **re-attaches to the progress
stream of the operation still running on the daemon**. That is literally
what Mario asked for originally ("start on the server, continue remotely").
So: a **light version** — at connect → full state load + re-subscribe to
in-flight operations. No elaborate ring buffer for multi-client fan-out.

### W5 — "One brain only": the Electron at home is in remote mode too
For "if I open remotely the one at home closes" to mean anything, there
must be **one brain** and everyone must attach to it — Electron included.
If the Electron at home ran in local-spawn (its own sidecar, its own lock
on *its own* directory) and the phone talked to the daemon, there would be
**two brains on two disks**, and "closing the one at home" would mean
nothing. So for the user-with-a-daemon the default is **Electron in remote
mode**. Local-spawn remains only for the "all-local, pure privacy" user —
who by definition has no web, no mobile, and no eviction. **Two distinct
worlds**; eviction lives only in the first.

### W6 — Reduced surface for the emergency client
Don't replicate the 12 views. Setup, Onboarding, Settings, OAuth, profile
management → **stay in Electron**. The PWA is **"read + act"**: Tasks (list
+ solve/Open), chat, reading Email/WhatsApp, triggering `update`. ~4-5
views, the simplest ones (no wizard, no config forms).

### W7 — OAuth: public client + PKCE, no client_secret in the web bundle
A browser cannot hide a secret. Calendar OAuth in the PWA = **public client
+ PKCE with a hosted redirect** (e.g. `https://<host>/oauth/callback`), not
loopback. *This forces the right hygiene* that the transport plan left as a
compromise (the secret inside the Electron bundle). And in any case the
emergency client normally **does not start an OAuth**: it uses the tokens
Electron already installed (server-side, via `oauth.installTokens`).

### W8 — Reachability / self-hosting (the one genuinely new nuisance)
"One machine" decides the transport plan's Phase 3:
- **VPS with a domain** → `wss://desktop.mrcall.ai` + Caddy/Let's Encrypt.
  Clean, and already the design.
- **Home box behind NAT** → a tunnel is needed (Cloudflare Tunnel /
  Tailscale / reverse proxy + DDNS): a phone on 4G cannot reach a private
  IP. That changes the deploy, not the architecture.

## How this lands on the Open Qs of `cross-machine-transport.md`

| Point | Resolution from Mario's model |
|---|---|
| **Q6** | → **(c)** "server kicks old" (NOT (b) multi-client). |
| **D4** broadcast | → **eliminated** in this scenario (a single client). |
| **D8** resume | → **reduced** to "re-attach to in-flight operations + full load at connect". It is the signature feature. |
| **D3** auth | → **add** single-active-session + a semantic close code + no-auto-reconnect-on-eviction. |
| **Q7** persistence compat | → for the user-with-a-daemon, Electron is in **remote mode** by default. |
| **Q1/Q2** host + TLS | → they depend on the W8 fork (VPS vs home box). |

## Free vs its own cost

- **Free (inherited from the transport plan):** the WS client, JWT auth,
  the files bridge (`files.upload/download`), `whatsapp.qr.event`,
  `oauth.installTokens`, the ~40 pure RPCs. Engine-side the PWA adds almost
  nothing beyond what the transport plan already lists.
- **The PWA's own cost:** a web host for the reused renderer + the few
  main-only shims (family 1) ported to the browser + the
  **single-session/eviction policy** in the WS server + the 4-5 reduced
  views + a PWA manifest + a service worker.
- **Native mobile:** we are not doing it. The PWA is the mobile story.

## Architectural leverage to take NOW (even if the PWA isn't built yet)

When the transport plan writes `WebSocketRpcClient` in **Phase 2**, do NOT
make it a class coupled to the Electron main process. Design it as a
**protocol core + pluggable socket**: JSON-RPC framing, request/response
correlation, notification demux, the `auth.refresh` loop, reconnect +
re-attach are all platform-agnostic. Underneath, a thin per-platform socket
binding — Node `ws` (Electron main), browser `WebSocket` (PWA), RN
`WebSocket` (a possible future). That way the PWA inherits for free the
part that is easiest to get wrong (correct reconnect/re-attach/refresh). It
is Objective 2 of the transport plan ("client-agnostic transport"): a
~zero-cost decision now that doesn't foreclose the PWA later.

## Files that would be touched (indicative — this is a brief)

```
# Reusing the renderer as a web app
app/  (or a new web/ package)       web entry point injecting a WS-backed
                                    `window.zylch` in place of the preload;
                                    a "pure web" Vite build
app/src/.../WebSocketRpcClient      shared with the transport plan's core
                                    (see architectural leverage above)
web manifest + service worker       installable PWA + (future) Web Push

# Engine — on top of what the transport plan already foresees
engine/zylch/rpc/server_ws.py       + single-active-session policy
                                    + "superseded" close code (4409)
engine/zylch/rpc/notification_bus   degenerated to "1 subscriber, swapped on
                                    takeover" (NOT multi-client fan-out)
```

## Out of scope (of this brief)

- **A native mobile app (iOS/Android/RN).** The PWA covers it. Reconsider
  only if aggressive push to a closed client were needed beyond Web Push.
- **Multi-tenant / SaaS.** Single-tenant only. The per-uid supervisor + WS
  routing + server-side profile lifecycle stay out.
- **Push to a closed client.** Deferred; Web Push as a gradual upgrade.
- **E2E encryption on the channel.** TLS is enough for the threat model
  ("my machine, internal traffic in the clear").

## How to start the next session (whenever it happens)

1. Prerequisite: `cross-machine-transport.md` Phase 1–3 LIVE and verified
   by Mario (WS daemon + JWT auth + TLS).
2. Check that the architectural leverage (the "core + pluggable socket" W)
   was taken in the transport plan's Phase 2; if not, refactor there first.
3. Re-read this brief + the discipline header.
4. This is NOT urgent. Electron stays the primary client; the PWA is a
   convenience.
