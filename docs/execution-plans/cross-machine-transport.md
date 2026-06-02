---
status: in-progress
owner: cross-cutting (engine + app + IPC + release)
created: 2026-05-31
discipline: |
  Standard regole Mario. NEVER claim a feature is "fixed", "done", or
  "verified" until Mario has used it himself end-to-end (Electron
  client su Mac, backend su VPS Scaleway) e ha confermato. Unit tests,
  typecheck, RPC probes, log lines NON contano — il sistema reale è
  "il backend gira H24 sul server, l'Electron si attacca via WSS, le
  notifications arrivano in real time". Una phase alla volta. Tell
  Mario exactly what to test. Wait. NEVER commit senza "funziona".
  Italian register in chat.
---

# Cross-machine transport (backend remoto + client thin)

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
  `serve --ws --unix <socket>`; the app's `WebSocketRpcClient` appends `/ws/<uid>`
  to a BASE URL (one machine-global config, per-window routing; an unrouted
  direct engine ignores the path → backward-compatible with the tunnel). Live-
  validated end-to-end: production@cafe124 over `wss://desktop.mrcall.ai`, no
  tunnel; auth gate proven (no token → engine 401 *through Caddy*). Also fixed: a
  reconnect crash (`terminate()` on a CONNECTING socket emitted an uncaught async
  'error' after `removeAllListeners`) and an infinite retry loop on 403.
  Artifact: `engine/scripts/caddy/desktop.Caddyfile`.

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
- **Multi-profile / multi-user routing** — the next milestone (brief below). Today
  Caddy sends every `/ws/*` to the single Gn9Icu daemon on `:5174`, so any other
  profile gets a (correct) 403.
- Multi-client broadcast + reconnect-resume → Phase 5.
- App Settings card: the URL field help should read "base URL (wss://host), no path".

## Next session — multi-profile / multi-user routing (brief)

**Goal.** Serve *many* profiles (and many Linux users) over the one
`wss://desktop.mrcall.ai` endpoint, each routed to its own engine daemon. The app
already appends `/ws/<uid>`; the missing piece is per-uid routing on the server so
each window reaches *its* backend.

**Why it's blocked today.** The `Caddyfile` proxies `/ws/* → 127.0.0.1:5174` (one
upstream = the Gn9Icu daemon). Any non-Gn9Icu token → the gate returns 403
(correct behaviour). The engine's `--unix` socket support exists and is tested
locally, but is NOT yet used on the VPS.

**Target design (already explained + agreed with Mario).**
- One daemon per profile on a **Unix socket named by uid**:
  `zylch -p <uid> serve --ws --unix /run/zylch/<uid>.sock`. No TCP-port juggling,
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
3. Migrate the Gn9Icu daemon to `--unix`; verify production@cafe124 still works
   over `wss://` (regression).
4. Add the `mario.alemi@mrcall.ai` (uid `x59G6…`) daemon: its VPS DB is **empty** —
   `rsync ~/.zylch/profiles/x59G6…/ claude:.zylch/profiles/x59G6…/` from the Mac (or
   `zylch -p x59G6… update` on the VPS) — then `enable --now`. Verify
   `wss://desktop.mrcall.ai/ws/x59G6…` with mario.alemi's token serves his data.
5. For another Linux user: `enable-linger`, their own `systemctl --user` daemons;
   sockets land in the shared `/run/zylch/`.

**Open decisions.** `systemctl --user` (linger) vs system units; flat `/run/zylch`
+ group `caddy` (trusted) vs per-user namespacing; how each user's profile data
reaches the VPS.

## Cosa Mario ha chiesto

> "È possibile far partire il backend su una macchina e il frontend
>  (Electron) su un'altra? […] Una cosa figa di Claude Code è che posso
>  iniziarlo sul server e poi continuare in remoto da Claude Desktop.
>  Una volta che l'abbiamo via TCP si apre la strada per un'app?"

Due obiettivi accoppiati:

1. **Backend persistente sul server, client thin sulla macchina dell'utente.** Il
   sidecar Python `zylch` gira come daemon su un VPS (Scaleway, lo stesso
   dove gira già `mrcall-agent` / `starchat`); l'Electron si attacca via
   WSS quando l'utente apre il laptop. Niente "se chiudo il MacBook si
   ferma tutto".
2. **Trasporto agnostico al client.** Sbloccato il cross-machine, una
   futura app mobile (iOS/Android/RN) è semplicemente un altro client
   sullo stesso WebSocket. Lo plan **non costruisce l'app mobile**, ma
   non la preclude — le decisioni di trasporto, auth, e file-handling
   sono prese pensando a entrambi i client.

## Stato attuale: cosa esiste vs cosa manca

### Già pronto ✅

| Pezzo | Dove | Note |
|---|---|---|
| Dispatch table RPC agnostica al trasporto | `engine/zylch/rpc/methods.py` | Riceve `(method, params)`, ritorna result/error. Non sa di stdio. |
| Owner identity server-side | tutti i metodi RPC | Il client non manda mai `owner_id` — il server lo risolve dal profilo attivo (fcntl lock). Survives trasporto. |
| Firebase JWT come auth verso StarChat | `engine/zylch/account_session.py`, `MrCallProxyClient`, `make_starchat_client_from_firebase_session` | Token in-memory nel sidecar, mai persistito. Il modello "il client pusha, il server usa come auth header" è già rodato. |
| Notifications bidirezionali | `tasks.solve.event`, `update.run.progress`, `whatsapp.message.received` | Già stream pattern; il main process le re-emette al renderer via IPC. Trasporto cambia, semantica resta. |
| Streaming SSE da Anthropic | `engine/zylch/llm/proxy_client.py` `stream(...)` | Reentrant; ok da remote. |
| OAuth PKCE infrastruttura | `app/src/main/googleSignin.ts` (Firebase), Calendar `:19275`, MrCall legacy `:19274` | **Già lato client.** Pattern riusabile per "loopback resta sul client, token vola al server via RPC". |

### Manca ❌

- **WebSocket server lato sidecar.** Oggi `zylch.rpc.server` parla solo line-delimited JSON-RPC su stdin/stdout.
- **Daemon mode lato sidecar.** `zylch` è progettato per girare nel ciclo `spawn()→use→kill()` di Electron. Manca: avvio come daemon (`zylch serve --ws 0.0.0.0:5174`), gestione signal (SIGTERM clean), restart policy, log rotation, healthcheck.
- **TLS termination.** Decisione (vedi Open Q #2): wss diretto via certificato locale (rustls/uvicorn-ssl), oppure dietro reverse-proxy (Caddy/nginx) che fa TLS + Let's Encrypt.
- **Auth del canale.** Oggi "sei mio child process, ti fido". Cross-machine: il WS server deve gate il bearer Firebase JWT al connect (e re-verificarlo periodicamente — i token Firebase scadono ogni ~1h).
- **Client-side trasporto astratto.** `app/src/main/` oggi spawnna un binario e parla via pipe. Servirebbe una `RpcClient` abstraction con due implementazioni: `StdioRpcClient` (oggi) e `WebSocketRpcClient` (nuovo); la scelta viene da config.
- **Settings UI per il remote backend.** "Local mode (default)" vs "Remote backend at wss://…". Persistenza, validazione URL, gestione disconnect/reconnect.
- **OAuth callback hosting strategy.** PKCE oggi atterra su `127.0.0.1:19275` (Calendar). Cross-machine: il browser dell'utente è sul client, il sidecar è sul server. Tre opzioni concrete, decisione vedi Open Q #5.
- **WhatsApp QR cross-machine.** Oggi neonize stampa il QR sul terminale del processo Python. Cross-machine: serve emetterlo come notification `whatsapp.qr.event` con bytes QR (string / PNG b64), renderer lo disegna.
- **File operations cross-machine.** `read_document`, `download_attachment_tool`, `files.read` lavorano col filesystem del backend. Path dell'utente sul client (es. `~/Downloads/foo.pdf`) NON esistono sul server. Servono RPC `files.upload(local_path, bytes)` / `files.download(server_path) -> bytes` per il bridge.
- **Multi-client broadcast.** Oggi un solo Electron parla con il sidecar. Cross-machine apre lo scenario "stessa identità, due client connessi" (laptop al lavoro + a casa). Servono broadcast notifications `tasks.changed`, `emails.changed` a tutti i client sub-scribed allo stesso profilo. (Notifications oggi sono per-client; la dispatch table le emette al chiamante.)
- **Reconnect + resume.** WS cade. Sequence numbers o resume token per non perdere notifications in-flight.
- **Fcntl lock semantics.** Il lock c'è già e va bene così (singleton process sul profilo). Cross-machine: nessun cambiamento. Il punto delicato è che il client "spawn locale" e il client "remote" non devono coesistere sullo stesso profilo — il fcntl lock già protegge naturalmente.

## Architettura proposta

```
┌──────────────── server (VPS Scaleway) ─────────────────┐
│                                                          │
│   systemd: zylch-server.service                          │
│   ──────────────────────────────────────────             │
│   zylch serve --ws 127.0.0.1:5174 \                      │
│                --profile <uid>                            │
│   │                                                       │
│   ├── fcntl lock su ~/.zylch/profiles/<uid>/             │
│   ├── WebSocket server (auth = Firebase JWT bearer)      │
│   ├── stessa dispatch table RPC                          │
│   └── notifications broadcast per profile                │
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
│   PKCE OAuth → loopback resta locale (browser è qui)     │
│   → after exchange, RPC oauth.installTokens(provider,    │
│     access_token, refresh_token) al server.              │
│                                                          │
│   WhatsApp QR → notification → render in renderer        │
│                                                          │
│   File ops → files.upload / files.download via RPC       │
└──────────────────────────────────────────────────────────┘
```

### Decisioni chiave

**D1 — WebSocket invece di HTTP+SSE.**
WebSocket è simmetrico (le notifications sono naturali, non simulate con long-polling), supporta backpressure, e mappa 1:1 sul modello attuale di JSON-RPC line-delimited (un messaggio per frame). HTTP+SSE richiederebbe due canali separati (POST per request, GET/SSE per notifications) + idempotency tokens. Più complesso a parità di funzionalità.

**D2 — Doppio trasporto coesistente lato sidecar (transitional).**
Il sidecar continua a esporre stdio quando lanciato senza `serve`, e WebSocket quando lanciato con `serve --ws addr:port`. Una sola code path RPC, due adapters di I/O. Niente regressione per gli utenti che vogliono restare "tutto locale": l'`spawn()` + stdio funziona identico. **Non rimuoviamo stdio** — utile per debug, per dev senza server, e per il modello "default privacy-first" (no server = no dati che escono dal Mac).

**D3 — Auth: Firebase JWT bearer + re-verifica periodica.**
- Al `WebSocket connect`: header `Sec-WebSocket-Protocol: bearer.<jwt>` (workaround standard per passare auth via WS, dato che WS non ha header `Authorization` custom in tutti i client). Server: verifica JWT contro Firebase pubblica `securetoken.google.com`, estrae uid, gate (`uid` == `OWNER_ID` del profilo lockato).
- Token refresh: ogni N minuti (5? 30?) il client invia `auth.refresh(<new_jwt>)`. Server lo verifica e aggiorna l'in-memory token. Se il client tarda oltre la scadenza, il server chiude il WS con close code 4401 (custom: "JWT expired, reconnect with fresh token"); il client rinegozia.
- Lato server, NON persistiamo il JWT (come fatto oggi). In-memory only.

**D4 — Profile lock e multi-client.**
- Il sidecar daemon mantiene il fcntl lock sul profile dir come oggi. Singleton process per profilo, n client connessi al sidecar.
- Notifications oggi sono per-caller (emesse al chiamante del metodo che le ha innescate). Estendere a broadcast per-profile: `tasks.changed`, `emails.changed`, `whatsapp.message.received`, `update.run.progress` vanno a TUTTI i client connessi alla profile session (oggi solo a chi ha chiamato).
- Implementazione: il `NotificationBus` (oggi inesistente come oggetto unificato) raccoglie subscriber WebSocket per profile id, e fa fan-out. Stdio resta singolo subscriber (il main process Electron locale).

**D5 — OAuth callback resta sul client.**
Tre opzioni considerate; scelta = la terza.
1. ❌ **Port-forward SSH del 19275 dal server al client.** Fragile, richiede setup OS-specifico, fallisce dietro NAT del cliente.
2. ❌ **Device-code flow.** Google lo supporta per alcuni scope ma cambia la UX (codice da digitare). MrCall delegated OAuth no.
3. ✅ **Loopback resta sul client, token finale viaggia al server via RPC.** Il client esegue il PKCE come oggi (browser → `127.0.0.1:19275` → exchange code → access+refresh token). Poi chiama una NUOVA RPC `oauth.installTokens(provider, access_token, refresh_token, expires_at)`. Il server cifra e persiste in `OAuthToken` con Fernet. Funziona identico per Calendar (Google), Firebase (già fa così), e MrCall futuro.

   Vantaggio collaterale: il `client_secret` (se serve) resta nel client (`app/src/main/oauthSecrets.ts`), non deve girare lato server.

**D6 — WhatsApp QR via notification stream.**
Neonize espone il QR come stringa (il payload "raw" di otp:// URL). Il sidecar la emette come notification `whatsapp.qr.event` con `{ raw: string, png_b64?: string }` (PNG generato server-side via `qrcode` Python). Renderer disegna nell'apposita view `ConnectWhatsApp.tsx`. Mario scansiona dal telefono.

Lo `~/.zylch/whatsapp.db` (la session neonize) **rimane sul server** — la sessione WhatsApp è "del server", non del client. Cambiare client (laptop → mobile) non richiede ri-pairing.

**D7 — File operations: upload/download espliciti.**
Due nuove RPC:
- `files.upload(stream)` (chunked WS binary frames) → ritorna server-side path (es. `~/.zylch/profiles/<uid>/uploads/<sha256>.bin`).
- `files.download(server_path, range?)` (chunked WS binary) → bytes.

`read_document` e `download_attachment_tool` continuano a lavorare su server-side paths. Il "user-facing" upload (drag&drop nel renderer) usa `files.upload` per portare il file al server, e poi passa al tool il server-side path. Idem per "scarica allegato": il server prepara il file, il client lo `files.download` e lo salva dove l'utente sceglie (system dialog).

**D8 — Reconnect + resume.**
- Ogni notification emessa porta un sequence number monotono per-profile.
- Client persiste il last-seen sequence in storage volatile (memoria; persisterlo su disco è over-kill per disconnect brevi).
- Sul reconnect, client manda `session.resume(last_seq)`. Server replay le notifications tra `last_seq+1` e ora (buffer in-memory ringbuffer per-profile, ~1000 ultimi eventi). Se troppo vecchio, il server risponde `{ replayed: false }` e il client fa hard refresh delle view.
- TTL del buffer: 10 min sufficienti per disconnect tipici.

**D9 — Compat mode + onboarding.**
- Default fresh install: **local mode** (spawn locale). Zero change per chi vuole privacy-first stand-alone.
- Settings → "Backend location": radio `Local (default)` / `Remote backend`. Il second campo svela un input URL + bottone "Test connection".
- L'onboarding non chiede remote backend nel wizard iniziale. Configurabile solo dopo, in Settings.

## Phasing

### Phase 0 — preparazione e decisioni

- Mario risponde alle Open Q sotto (numero del server, TLS strategy, ricreare client_secret per remote, broadcast policy default).
- Sketch del WebSocket server in `engine/zylch/rpc/server_ws.py` su un branch throwaway per misurare il delta vs `server.py` attuale (stdio).
- Decisione "Caddy davanti vs uvicorn-ssl diretto" sul VPS Scaleway, basato sul fatto che StarChat e mrcall-agent già hanno un reverse-proxy o no.

**STOP. Mario risponde. NON partire con Phase 1 prima.**

### Phase 1 — WebSocket server lato sidecar, doppio trasporto

- `zylch serve --ws <addr:port> --profile <uid>` come nuovo CLI subcommand.
- `engine/zylch/rpc/server_ws.py`: WebSocket server (FastAPI? aiohttp? raw `websockets`?), stessa dispatch table di `server.py` (stdio). Owner-scoped come oggi.
- Auth handshake: `Sec-WebSocket-Protocol: bearer.<jwt>`. Verifica contro Firebase Admin SDK (server-side). Estrae uid; gate vs profile OWNER_ID.
- `auth.refresh(jwt)` RPC. Disconnect su scadenza con close code 4401.
- Logging dei connect/disconnect/auth failure (mai il JWT).
- Test: pytest che spinge un WS client + JWT mock e round-trippa `account.whoAmI()`.

Niente client side ancora. Sidecar dual-mode (stdio + ws) verificabile via `wscat` o test script.

**STOP. Mario boota `zylch serve --ws 127.0.0.1:5174 --profile <uid>` sul server (o sul Mac per test locale), si attacca con `wscat`, verifica che `whoAmI()` torna l'identità giusta col bearer JWT.**

### Phase 2 — client thin: RpcClient abstraction + Remote backend in Settings

- `app/src/main/RpcClient.ts`: interface `{ call(method, params, timeout), subscribe(event, handler), close() }`.
- Refactor di `app/src/main/index.ts`: estrarre l'attuale spawn+pipe come `StdioRpcClient implements RpcClient`. Nessun cambio di comportamento.
- Nuovo `WebSocketRpcClient implements RpcClient`. Connect con bearer Firebase JWT (lo prende dal renderer come oggi). Auto-reconnect con backoff. `auth.refresh` ogni ~30 min.
- Settings UI: `LLMProviderCard` ha già il pattern radio. Nuovo `BackendLocationCard`: `Local` / `Remote (wss://…)`. Bottone "Test connection" → `whoAmI()`.
- Persistenza in `~/Library/Preferences/...` (Electron `app.getPath('userData')`) — NON nel profile dir (la scelta del backend è per-client, non per-profile).
- Reload window richiesto al cambio mode (più semplice che riattaccare a runtime — il sidecar lifecycle è stato pensato come "one per window-session").

**STOP. Mario apre Settings, imposta wss://… del proprio test deployment, restart window, IdentityBanner mostra l'identità correttamente, tab Email/Tasks/Workspace si popolano via WS.**

### Phase 3 — TLS production-grade + systemd daemon

- Service unit `zylch-server.service` per Scaleway VPS (Mario fornisce la macchina specifica).
- Caddy o nginx davanti per TLS Let's Encrypt + HTTP→HTTPS redirect + WS upgrade.
- Health endpoint HTTP GET `/health` (separato dal WS) per i probe.
- Documentazione di deploy in `docs/execution-plans/cross-machine-transport.md#deploy` (qui sotto, post-decisioni).
- `engine/zylch/cli/main.py` `serve` subcommand documented in `engine/docs/guides/`.

**STOP. Mario clicca "Test connection" verso il VPS reale dal Mac, vede latency ragionevole (< 200ms RTT), e fa `zylch -p <uid> update` via WS (non più via spawn locale).**

### Phase 4 — OAuth callback hosting client-side + `oauth.installTokens` RPC

- Nuova RPC `oauth.installTokens(provider, access_token, refresh_token?, expires_at?)` lato sidecar. Cifra Fernet, persiste in `OAuthToken`. Owner-scoped.
- `app/src/main/calendarSignin.ts` (mirror di `googleSignin.ts`): PKCE su `127.0.0.1:19275`, scambio code locale, poi `await zylch.oauth.installTokens('google_calendar', …)`.
- Settings → "Connect Google Calendar" funziona identico per local e remote.
- `Firebase` signin: già lato client (PKCE in `googleSignin.ts`), il JWT vola via `account.set_firebase_token` come oggi. Niente cambio.

**STOP. Mario clicca Connect Google Calendar in modalità remote, completa OAuth nel browser locale, il sidecar remoto riceve i token, e una RPC `calendar.listEvents()` torna eventi reali.**

### Phase 5 — WhatsApp QR cross-machine + multi-client broadcast + reconnect resume

- `whatsapp.qr.event` notification (`{ raw, png_b64 }`). Renderer in `ConnectWhatsApp.tsx` renderizza il PNG b64.
- `NotificationBus` server-side: subscriber list per profile, fan-out su `tasks.changed`, `emails.changed`, `update.run.progress`.
- Sequence numbers + ringbuffer 1000-eventi + `session.resume(last_seq)` RPC.
- File operations: `files.upload(chunks)` + `files.download(server_path, range?)` RPC.

**STOP. Mario: (a) connette WhatsApp dal Mac scansionando QR dal telefono mentre il sidecar gira sul VPS; (b) apre lo stesso profilo da un secondo Electron (es. laptop di casa), modifica una task, verifica che la finestra principale si aggiorna; (c) chiude la connessione (kill Wi-Fi), aspetta 30s, riconnette, verifica che notifications recenti vengono replayed.**

### Phase 6 — documentazione + harness gaps

- `docs/cross-machine-deploy.md`: guida deploy server.
- `engine/docs/guides/zylch-serve.md`: CLI reference.
- `docs/active-context.md` + `engine/docs/active-context.md` + `app/docs/active-context.md` aggiornati con il nuovo trasporto.
- `docs/ipc-contract.md` esteso con `auth.refresh`, `oauth.installTokens`, `session.resume`, `files.upload`, `files.download`, `whatsapp.qr.event`.
- `docs/harness-backlog.md`: gates nuovi (mismatch `WebSocketRpcClient`/`StdioRpcClient` API surface; certificati Let's Encrypt scaduti; replay buffer overflow logging).

## Files toccati

```
engine/zylch/rpc/server_ws.py                NEW (WebSocket server, stesso dispatch)
engine/zylch/rpc/notification_bus.py         NEW (subscriber list + fan-out + ringbuffer resume)
engine/zylch/rpc/methods.py                  +auth.refresh, +oauth.installTokens, +session.resume,
                                              +files.upload, +files.download
engine/zylch/cli/main.py                     +serve subcommand
engine/zylch/account_session.py              auth.refresh handler (in-memory token update)
engine/zylch/storage/storage.py              (nothing new — install_oauth_tokens uses existing helpers)
engine/zylch/whatsapp/client.py              emit whatsapp.qr.event invece di stampare il QR
engine/scripts/systemd/zylch-server.service  NEW (deploy artefact)
engine/scripts/caddy/zylch.caddyfile          NEW (deploy artefact, se Caddy)

app/src/main/RpcClient.ts                    NEW (interface)
app/src/main/StdioRpcClient.ts               NEW (refactor dell'attuale spawn+pipe)
app/src/main/WebSocketRpcClient.ts           NEW
app/src/main/calendarSignin.ts               NEW (PKCE locale → oauth.installTokens RPC)
app/src/main/index.ts                        refactor a usare RpcClient
app/src/preload/index.ts                     binding di auth.refresh, oauth.installTokens, session.resume, files.*
app/src/renderer/src/types.ts                ZylchAPI surface esteso
app/src/renderer/src/views/Settings.tsx      +BackendLocationCard
app/src/renderer/src/views/ConnectWhatsApp.tsx  renderer QR PNG b64 dalla notification
app/src/renderer/src/components/IdentityBanner.tsx  mostra "Remote: wss://…" quando attivo

docs/ipc-contract.md                         +auth.refresh, +oauth.installTokens, +session.resume,
                                              +files.upload, +files.download, +whatsapp.qr.event
docs/active-context.md                       cross-cutting state aggiornato
docs/harness-backlog.md                      gates nuovi
docs/cross-machine-deploy.md                 NEW (operator guide)
engine/docs/guides/zylch-serve.md            NEW (CLI ref)
```

## Open design questions per Mario (rispondere PRIMA di Phase 1)

1. **Host del backend.** VPS Scaleway dedicato (nuovo container?), oppure si appoggia a una macchina dove gira già `mrcall-agent`/`starchat`? Il profile dir `~/.zylch/profiles/<uid>/` va sotto quale utente unix, con quale backup policy?

2. **TLS termination.** Caddy davanti (auto-Let's Encrypt + zero-conf), nginx (più controllo), o uvicorn/aiohttp diretti con SSL context? Mia raccomandazione: Caddy, semplice.

3. **`auth.refresh` cadence + close code policy.** Il refresh ogni 30 min è un compromesso tra "non bombardare il server" e "non lasciare token che stanno per scadere". Suggerimento: ogni 30 min preventivo + force-refresh quando il server risponde 4401. Va bene così?

4. **Broadcast notifications policy.** Quando due Electron sono connessi allo stesso profilo, vogliamo:
   - **(a)** broadcast SEMPRE — ogni `tasks.changed` va a tutti i client, even if uno dei client è la fonte dell'evento; oppure
   - **(b)** broadcast a tutti TRANNE il sender — il client che ha chiamato `tasks.complete` riceve la conferma RPC standard, gli altri ricevono `tasks.changed`.
   Raccomandazione: **(b)** — meno traffico, meno race condition lato UI (il chiamante può aggiornare ottimisticamente).

5. **OAuth callback hosting confirm.** Conferma: PKCE loopback resta sul client (Mac), il token finale via `oauth.installTokens` al server. Costo: il client_secret di Google deve ancora vivere nel bundle Electron (come oggi). Alternativa: ricreare un OAuth client "server-side" e fare l'intero flusso sul server, ma richiede Mario di aprire il browser sul server (impractical su VPS headless) — scartata. OK?

6. **Profile-per-client vs profile-condiviso.** Cross-machine apre tre scenari:
   - **(a)** un profilo per client (Mario sul lavoro: profilo A; Mario a casa: profilo B). Niente broadcast, niente lock issue.
   - **(b)** un solo profilo, due client connessi simultaneamente (multi-window-cross-machine).
   - **(c)** un solo profilo, solo un client alla volta (lock fcntl ti protegge dal secondo connect; oppure il server kick-a il vecchio).
   Raccomandazione: **(b)**, perché è il caso d'uso che hai dichiarato ("backend sempre acceso, client diversi"). Implica D4 + Phase 5 broadcast. Conferma?

7. **Compat mode persistenza.** Quando l'utente sceglie "Remote", la scelta è per-installazione (su quel Mac specifico) o per-profilo? Raccomandazione: per-installazione, in Electron `userData` — l'identità Firebase è la stessa, ma "da dove parlo" è una proprietà della macchina su cui sei.

## Out of scope di questo plan

- **App mobile (iOS/Android/RN).** Il trasporto WS fa da fondamenta, ma l'app mobile ha decisioni proprie: push notifications via APNs/FCM (il server deve poter notificare task nuove a app chiusa), UI ridotta, offline cache, background fetch. Sarà un separate execution plan post-Phase 5 di questo.
- **End-to-end encryption sul canale.** TLS basta per la threat model attuale ("server di mia proprietà su VPS my-vpc, traffico in chiaro internamente"). E2E sopra TLS solo se in futuro si ospita su PaaS terzo.
- **Migrazione automatica del profile dir esistente.** Se Mario ha già `~/.zylch/profiles/<uid>/` sul Mac e vuole spostarlo sul server: rsync manuale. Documentato in deploy guide, non automatizzato.
- **Multi-region / load balancing.** Un solo backend per profilo (fcntl lock). Niente HA.
- **Outbound tools** (`InitiateCallTool`, `SendSMSTool`): ortogonale, vedi `mrcall-pipeline-parity.md` Out of scope.

## Come iniziare la prossima sessione

1. Apri questo file. Re-read discipline header.
2. **Phase 0 PRIMA di toccare codice**: Mario risponde alle 7 Open Q sopra. NON partire con Phase 1 prima.
3. Phase 1 = single PR (`zylch serve --ws`, `server_ws.py`, auth handshake, smoke test via `wscat`). Land. Mario testa connessione da CLI. Poi Phase 2.
4. Una phase alla volta. Tell Mario exactly what to test ad ogni STOP. Aspetta "funziona".
5. NEVER push to origin. NEVER commit senza ok esplicito.
