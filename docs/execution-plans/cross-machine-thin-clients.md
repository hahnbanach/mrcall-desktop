---
status: proposed — NICE-TO-HAVE / deferred (brief pronto; NON si fa ora)
priority: |
  nice-to-have. Electron resta il client primario; web/mobile è comodità
  "di emergenza", non è in roadmap e non blocca nulla. Se Mario lo
  richiede in futuro (e magari ha dimenticato che esiste): ricordaglielo e
  riparti DA QUESTO BRIEF, non da zero.
owner: cross-cutting (engine + app + IPC + nuovo client web)
created: 2026-06-02
depends-on: cross-machine-transport.md (Phase 1–3 devono essere live PRIMA)
discipline: |
  Standard regole Mario. Questo è un BRIEF di analisi, non codice: quando
  verrà ripreso, una phase alla volta, e NEVER claim "fatto"/"funziona"
  finché Mario non l'ha usato end-to-end (daemon su una macchina, client
  PWA dal browser/telefono) e confermato. Unit tests / typecheck / probe
  RPC NON contano. Tell Mario exactly what to test, wait, NEVER commit
  senza "funziona". Italian register in chat.
---

# Client thin web/mobile sopra il transport cross-machine

> **Brief, non piano esecutivo — NICE-TO-HAVE differito.** Cattura
> l'analisi del 2026-06-02. Electron resta il client primario; questo non
> è in roadmap e non blocca nulla. Non si parte finché
> `cross-machine-transport.md` non ha consegnato WS server + auth JWT +
> TLS (le sue Phase 1–3). Il documento esiste perché l'analisi non vada
> persa e perché — se Mario lo richiede e l'avesse dimenticato — gli si
> ricordi che il brief c'è già: ripartire da qui, non da zero.

## Il modello che Mario ha fissato

- **Electron resta il client preferito.** Web/mobile sono client thin
  **"di emergenza"**: ti ci attacchi quando non hai il Mac davanti.
- **Single-tenant.** Un daemon, un profilo, su una macchina che è tua.
  Te lo fai partire e ti ci connetti. Niente SaaS, niente multi-utente,
  niente supervisor per-tenant. (Quel costo grosso è fuori scope —
  vedi sotto.)
- **Single-active-client con eviction "vince l'ultimo".** *Correzione
  esplicita di Mario:* NON "un profilo / N client insieme". È **un solo
  client attivo alla volta**: se apri da remoto, **il daemon chiude la
  sessione dell'Electron a casa**. È l'opzione **Q6=(c)** di
  `cross-machine-transport.md`, variante "il server kick-a il vecchio".

Conseguenza che semplifica tutto: niente broadcast multi-client, niente
race fra client, un cursore solo, uno stato solo.

## Perché è quasi gratis: il punto di sutura già esiste

Il renderer (`app/src/renderer/`, ~9.000 righe `.tsx`, 12 view) **non
importa mai Electron** — parla solo con `window.zylch.*`, cioè
l'interfaccia `ZylchAPI` (`app/src/renderer/src/types.ts`). Chi fornisce
`window.zylch` è intercambiabile. Spaccando il preload
(`app/src/preload/index.ts`):

- **~40 metodi sono RPC puri** (`call(method, params)` → sidecar): tutto
  `tasks.*`, `emails.*`, `chat.*`, `update.run`, `settings.*`,
  `account.*`, `mrcall.*`, `memory.*`, `narration.*`, e i `connect/status`
  di `google.calendar` e `whatsapp`. **Non cambiano di una riga**: cambia
  solo *chi* esegue `call()` — non più preload→main→stdio ma una
  connessione WS diretta dal browser. È lo stesso `RpcClient` del transport
  plan (Phase 2), solo che nel PWA vive nel browser, non nel main process.
- **~13 sono IPC "main-only"** (`ipcRenderer.invoke` su canali non-RPC) =
  la colla Electron da rifare. Due famiglie:
  1. **Shim di piattaforma, banali:** `files.select` (dialog → `<input
     type=file>`), `shell.openExternal` (→ `window.open`),
     `signin.googleStart` (loopback PKCE `:19276` → Firebase **Web SDK**
     `signInWithPopup`, *più semplice* nel browser).
  2. **Stato/lifecycle che per qualunque client remoto deve stare
     server-side:** `onboarding.createProfile*` (oggi scrive su disco
     locale), `profiles.list`, `profile.current`, `auth.bindProfile`.
     **Nel nostro modello questi NON servono al client urgenza**: il
     profilo lo crei e configuri da Electron; il PWA assume un daemon già
     pronto e si limita a connettersi.

Il main process Electron (~2.176 righe) è il delta concettuale; ma per il
client urgenza ne serve solo una frazione (gli shim della famiglia 1).

## Decisioni raggiunte

### W1 — Client urgenza = PWA, NON app nativa
Una sola codebase web copre browser desktop *e* mobile; installabile in
home-screen come PWA (sembra un'app, zero App Store, zero review, zero
signing). **L'access pattern "apro quando ho urgenza" elimina il bisogno
di push APNs/FCM** — che era il costo #1 e l'unica vera ragione del
nativo. Non dipendi dalla consegna in background: apri on-demand e fai un
full load al connect. Se un giorno vuoi "pingami a client chiuso", la
**Web Push del PWA** (service worker; Android Chrome, iOS 16.4+ su PWA
installata) copre buona parte senza nativo. **Native mobile: deferred a
tempo indefinito.**

### W2 — Single-active-session: l'eviction è logica nuova nel daemon, NON il fcntl
Distinzione critica (il transport plan in Q6c la confonde):
- **fcntl flock** (`engine/zylch/cli/profiles.py`) garantisce **un solo
  *daemon* per cartella-profilo**. Tutti i client colpiscono *lo stesso*
  processo daemon → il lock NON li distingue.
- L'**eviction del client** è una **policy nuova dentro il WS server**:
  "al massimo una sessione WS attiva per profilo; vince l'ultima". Nuovo WS
  autenticato per il profilo → il daemon chiude il WS precedente.

### W3 — Il takeover deve essere pulito (la trappola della guerra di riconnessione)
Il transport plan (Phase 2) prevede "auto-reconnect con backoff". Se è
generico → ping-pong infinito: A chiuso → A si riconnette → chiude B → B
si riconnette → … Nessuno usabile. Fix = **close code semantici**:
- **"superseded"** (es. close code custom `4409`) → client va **passivo**,
  banner "Sessione aperta altrove", **NIENTE auto-reconnect**; solo un
  bottone manuale **"Riprendi qui"** riprende il controllo (ed espelle
  l'altro).
- **"network drop"** (1006/1001) → quello sì, auto-reconnect con backoff.

Distinguere i due casi è *l'unica* cosa che separa "funziona" da "due
finestre che si scannano". Da aggiungere alla D3 del transport plan come
gemello dell'auth handshake.

### W4 — Resume ri-mansionato: è la feature-firma, non un dettaglio
Il resume (D8 del transport plan) **non serve** a sincronizzare più client
(ce n'è uno). Serve a **ri-attaccare l'unico client attivo a operazioni
daemon-side long-running attraverso un takeover**: fai partire un `update`
o un `tasks.solve` dall'Electron, chiudi il laptop, apri il telefono → il
telefono prende il controllo e **si ri-aggancia allo stream di progresso
dell'operazione che gira ancora sul daemon**. È letteralmente ciò che
Mario ha chiesto all'origine ("inizio sul server, continuo in remoto").
Quindi: **versione leggera** — al connect → full state load +
re-subscribe alle operazioni in corso. Niente ring-buffer elaborato da
fan-out multi-client.

### W5 — "Un cervello solo": anche l'Electron di casa è remote-mode
Perché "se apro da remoto si chiude quello a casa" abbia senso, deve
esserci **un solo cervello** e tutti devono attaccarsi a quello — Electron
incluso. Se l'Electron-casa girasse in local-spawn (sidecar suo, lock suo
sulla *sua* cartella) e il telefono parlasse col daemon, sarebbero **due
cervelli su due dischi**, e "chiudere quello a casa" non vorrebbe dire
niente. Quindi per l'utente-con-daemon il default è **Electron in
remote-mode**. Il local-spawn resta solo per l'utente "tutto-locale,
privacy puro" — che per definizione non ha web, né mobile, né eviction.
**Due mondi distinti**; l'eviction vive solo nel primo.

### W6 — Superficie ridotta del client urgenza
Non replicare le 12 view. Setup, Onboarding, Settings, OAuth, gestione
profili → **restano su Electron**. Il PWA è **"read + act"**: Tasks (lista
+ solve/Open), chat, lettura Email/WhatsApp, trigger `update`. ~4-5 view,
le più semplici (niente wizard, niente form di config).

### W7 — OAuth: public client + PKCE, niente client_secret nel bundle web
Un browser non può nascondere un secret. OAuth Calendar nel PWA = **public
client + PKCE con redirect ospitato** (es. `https://<host>/oauth/callback`),
non loopback. *Forza l'igiene giusta* che il transport plan lasciava
come compromesso (secret nel bundle Electron). E comunque il client
urgenza normalmente **non inizia un OAuth**: usa i token già installati da
Electron (server-side via `oauth.installTokens`).

### W8 — Raggiungibilità / self-host (l'unica rogna nuova)
"Una macchina" decide la Phase 3 del transport plan:
- **VPS con dominio** → `wss://desktop.mrcall.ai` + Caddy/Let's Encrypt.
  Pulito, è già il disegno.
- **Box di casa dietro NAT** → serve un tunnel (Cloudflare Tunnel /
  Tailscale / reverse-proxy + DDNS): il telefono in 4G non raggiunge un IP
  privato. Cambia il deploy, non l'architettura.

## Come ricade sulle Open Q di `cross-machine-transport.md`

| Punto | Risoluzione dal modello di Mario |
|---|---|
| **Q6** | → **(c)** "server kicks old" (NON (b) multi-client). |
| **D4** broadcast | → **eliminato** in questo scenario (un client solo). |
| **D8** resume | → **ridotto** a "re-attach a operazioni in corso + full load al connect". È la feature-firma. |
| **D3** auth | → **aggiungere** single-active-session + close code semantico + no-auto-reconnect-on-eviction. |
| **Q7** persistenza compat | → per l'utente-con-daemon, Electron è **remote-mode** di default. |
| **Q1/Q2** host + TLS | → dipendono dal bivio W8 (VPS vs box di casa). |

## Gratis vs costo proprio

- **Gratis (ereditato dal transport plan):** WS client, auth JWT, files
  bridge (`files.upload/download`), `whatsapp.qr.event`,
  `oauth.installTokens`, le ~40 RPC pure. Lato engine il PWA aggiunge
  quasi nulla oltre a ciò che il transport plan già elenca.
- **Costo proprio del PWA:** host web del renderer riusato + i pochi shim
  main-only (famiglia 1) riportati a browser + la **policy
  single-session/eviction** nel WS server + le 4-5 view ridotte + manifest
  PWA + service worker.
- **Mobile nativo:** NON lo facciamo. Il PWA è la storia mobile.

## Leva architetturale da prendere ORA (anche se il PWA non si fa adesso)

Quando il transport plan scrive `WebSocketRpcClient` in **Phase 2**, NON
farne una classe accoppiata al main process Electron. Progettarlo come
**core-di-protocollo + socket pluggable**: framing JSON-RPC, correlazione
request/response, demux notification, loop `auth.refresh`, reconnect +
re-attach sono tutti agnostici alla piattaforma. Sotto, una sottile socket
binding per piattaforma — Node `ws` (Electron-main), browser `WebSocket`
(PWA), RN `WebSocket` (eventuale futuro). Così il PWA eredita gratis la
parte più facile da sbagliare (reconnect/re-attach/refresh corretti). È
l'Obiettivo 2 del transport plan ("trasporto agnostico al client"):
decisione a costo ~zero adesso, che non preclude il PWA dopo.

## Files che verrebbero toccati (indicativo — è un brief)

```
# Riuso del renderer come web app
app/  (o nuovo package web/)        entry-point web che inietta un
                                    `window.zylch` WS-backed al posto del
                                    preload; build Vite "pure web"
app/src/.../WebSocketRpcClient      condiviso col core del transport plan
                                    (vedi leva architetturale sopra)
web manifest + service worker       PWA installabile + (futuro) Web Push

# Engine — sopra a quanto già previsto dal transport plan
engine/zylch/rpc/server_ws.py       + policy single-active-session
                                    + close code "superseded" (4409)
engine/zylch/rpc/notification_bus   degenerato a "1 subscriber, swap su
                                    takeover" (NON fan-out multi-client)
```

## Out of scope (di questo brief)

- **App mobile nativa (iOS/Android/RN).** Il PWA la copre. Riconsiderare
  solo se servisse push aggressiva a client chiuso oltre Web Push.
- **Multi-tenant / SaaS.** Single-tenant only. Il supervisor per-uid +
  routing WS + lifecycle profilo server-side restano fuori.
- **Push a client chiuso.** Deferred; Web Push come upgrade graduale.
- **E2E encryption sul canale.** TLS basta per la threat model
  ("macchina mia, traffico interno in chiaro").

## Come iniziare la prossima sessione (quando si farà)

1. Pre-requisito: `cross-machine-transport.md` Phase 1–3 LIVE e verificate
   da Mario (daemon WS + auth JWT + TLS).
2. Verificare che la leva architetturale (W "core + socket pluggable") sia
   stata presa in Phase 2 del transport plan; se no, rifattorizzare lì
   prima.
3. Rileggere questo brief + il discipline header.
4. NON è un'urgenza. Electron resta il client primario; il PWA è comodità.
