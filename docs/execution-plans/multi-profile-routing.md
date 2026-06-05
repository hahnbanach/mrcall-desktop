---
status: planned
owner: cross-cutting (engine + ops/Caddy + deploy)
created: 2026-06-05
supersedes: the "Next session — multi-profile / multi-user routing (brief)" section in cross-machine-transport.md
discipline: |
  Standard regole Mario. È PRODUZIONE: production@cafe124 gira live su
  desktop.mrcall.ai. NEVER claim "fatto"/"verificato" finché Mario non ha
  riconnesso il suo Electron e visto i SUOI dati passare DOPO la migrazione.
  Unit test / RPC probe / log NON contano: il test reale è "due profili
  diversi, STESSO url wss://desktop.mrcall.ai, ognuno vede i propri dati, e
  un re-run dello script non rompe niente". Una phase alla volta, ad ogni
  STOP dire a Mario esattamente cosa testare e aspettare "funziona". NEVER
  push senza ok esplicito. Italian register in chat.
---

# Multi-profile routing + daemon auto-update (`mrcalld` + per-uid Unix sockets)

## Obiettivo

Servire *tanti* profili (e in prospettiva tanti utenti) dietro l'unico
endpoint `wss://desktop.mrcall.ai`, ognuno instradato al proprio daemon
engine, con **un solo script `sudo` idempotente** che aggiorna il codice,
scopre tutti i profili, garantisce un daemon per profilo, e spegne gli
orfani.

**Proprietà chiave — è il motivo per cui si fa così.** Con socket per-uid +
routing per-uid, **ogni utente usa lo STESSO url** `wss://desktop.mrcall.ai`:
l'app aggiunge da sé `/ws/<il-suo-uid>`. Niente url diverso per utente, niente
porte da ricordare, niente "cambia l'url in Settings" alla prossima migrazione
(era il problema delle porte sollevato da Mario). **L'app NON cambia** — il
client lato Electron è già pronto, appende già `/ws/<uid>`.

## Decisioni bloccate (Mario, 2026-06-05)

- **D1 — utente di servizio dedicato `mrcalld`.** Possiede il checkout
  dell'engine + TUTTI i profili + fa girare TUTTI i daemon. System user, no
  login. Niente più `systemctl --user` / linger per-umano (come ipotizzava il
  brief precedente): unit **system-level** `User=mrcalld`. Più semplice e
  standard per un servizio.
- **D2 — un socket Unix per uid, NON una porta TCP.**
  `zylch -p <uid> serve --ws --unix /run/mrcalld/<uid>.sock`. Niente porte da
  assegnare/ricordare, niente collisioni, niente url-per-utente.
- **D3 — Caddy instrada per uid nel path** → socket, con UNA regola statica:
  ```
  desktop.mrcall.ai {
      @ws path_regexp uid ^/ws/([^/]+)$
      reverse_proxy @ws unix//run/mrcalld/{re.uid.1}.sock
  }
  ```
  La sicurezza resta il **gate JWT per-daemon** (`uid == OWNER_ID`): un
  mis-route fallisce 403; il routing è un hint, non la sicurezza.
- **D4 — `/run/mrcalld/`** di proprietà `mrcalld:caddy`, mode `2750` (setgid →
  i socket ereditano group `caddy`); il daemon gira con `UMask=0007` così il
  socket è group-writable e Caddy (group `caddy`) può connettersi. Creata via
  `tmpfiles.d` (è su tmpfs, va ricreata a ogni boot).
- **D5 — lo script updater è l'unico entry-point operativo.** Il template
  systemd + lo snippet Caddy sono artefatti versionati che lo script usa.

## Conseguenza importante: Caddy è STATICO

Con la regex generica `^/ws/([^/]+)$` il path del socket si calcola dall'uid a
runtime (`{re.uid.1}`). Quindi **la Caddyfile si scrive UNA volta e non si
tocca più** quando si aggiungono/tolgono profili. Lo script updater gestisce
**solo i daemon** (enable/restart/disable) — non rigenera né ricarica Caddy.
Un uid senza socket → Caddy 502 (nessun dato esposto, accettabile).

## Cosa cambia rispetto a oggi

| Oggi (live) | Dopo |
|---|---|
| daemon `User=mal`, da `~/zylch-engine` (rsync) | `User=mrcalld`, da `/home/mrcalld/mrcall-desktop/engine` (git) |
| `serve --ws 127.0.0.1:5174` (porta) | `serve --ws --unix /run/mrcalld/<uid>.sock` |
| `/etc/zylch/<uid>.conf` con `ZYLCH_WS_ADDR` | **non serve più** (il path socket deriva da `%i`) |
| Caddy `reverse_proxy /ws/* 127.0.0.1:5174` (1 upstream) | `path_regexp uid` → socket per-uid (statico, N upstream) |
| 1 profilo raggiungibile (Gn9Icu); gli altri → 403 | tutti i profili raggiungibili, stesso url |
| provisioning a mano (runbook per-profilo in remote-backend.md) | `sudo update-daemons.sh` (auto-discovery) |

## Fasi (una alla volta, STOP + verifica di Mario ad ognuna)

### Phase 0 — preparazione (no downtime sul live)
- Crea `mrcalld` (system user, `HOME=/home/mrcalld`, shell `nologin`).
- `tmpfiles.d`: `d /run/mrcalld 2750 mrcalld caddy -`; `systemd-tmpfiles --create`.
- **Conferma il gruppo reale di Caddy** sul VPS (`caddy`? `www-data`?) → fissa D4.
- `git clone` → `/home/mrcalld/mrcall-desktop`; venv + `pip install -e .` (come mrcalld).

**STOP.** `/run/mrcalld` esiste con owner/perms giusti; `sudo -u mrcalld
/home/mrcalld/mrcall-desktop/engine/venv/bin/zylch --help` gira.

### Phase 1 — template unit + RISCHIO #1: perms del socket
- Riscrivi `zylch-server@.service`: `User=mrcalld`, `Group=mrcalld`,
  `Environment=HOME=/home/mrcalld`, `UMask=0007`, ExecStart
  `…/venv/bin/zylch -p %i serve --ws --unix /run/mrcalld/%i.sock`; **togli**
  `EnvironmentFile`.
- Copia UN profilo di **test** (NON production) sotto
  `/home/mrcalld/.zylch/profiles/<uid-test>/`, `chown -R mrcalld:mrcalld`,
  `enable --now zylch-server@<uid-test>`.
- **RISCHIO #1 — VERIFICARE PER PRIMO**: il socket creato da `--unix` deve
  essere apribile da Caddy (group `caddy`, group-write). `ls -l
  /run/mrcalld/<uid>.sock`. Se nasce `srwxr-xr-x mrcalld:mrcalld` (no
  group-write / group sbagliato) malgrado `UMask`+setgid, l'engine deve fare
  un `os.chmod(0o660)` (e/o affidarsi al setgid della dir) sul socket dopo il
  bind in `engine/zylch/rpc/server_ws.py`. **Questo è il rischio che può far
  saltare tutto il piano: provarlo prima di andare avanti.**

**STOP.** `sudo -u caddy python -c "import socket; socket.socket(socket.AF_UNIX).connect('/run/mrcalld/<uid>.sock')"`
(o equivalente) si connette senza permission denied.

### Phase 2 — Caddy per-uid + test end-to-end (un profilo)
- Porta `engine/scripts/caddy/desktop.Caddyfile` alla forma `path_regexp`
  (D3); `caddy validate`; reload.

**STOP.** Mario: app → `wss://desktop.mrcall.ai` (l'app appende `/ws/<uid-test>`),
il profilo di test si popola (Email/Tasks). Token di un ALTRO uid → 403; uid
inesistente → 502 pulito.

### Phase 3 — lo script updater `engine/scripts/server/update-daemons.sh`
Idempotente, gira da root/`sudo`:
1. `git -C /home/mrcalld/mrcall-desktop pull --ff-only`; `pip install -e .`
   **solo se** `pyproject.toml`/lock sono cambiati (altrimenti l'install `-e`
   basta: il restart riprende il codice nuovo).
2. glob `/home/mrcalld/.zylch/profiles/*/` → lista uid (filtra: deve contenere
   un `.env`).
3. per ogni uid: `systemctl enable zylch-server@<uid>` + `restart`.
   `daemon-reload` una volta se il template è cambiato.
4. `disable --now zylch-server@<uid>` per le istanze attive senza più dir
   profilo (orfani).
5. log riassuntivo: N profili trovati / N avviati / N orfani spenti. NON tocca
   Caddy (statico).

**STOP.** Mario: crea una dir profilo finta → re-run → nuovo daemon su,
raggiungibile; rimuove la dir → re-run → daemon spento; re-run a vuoto = no-op
(stessi socket, nessun restart inutile se si decide di skippare i già-attivi).

### Phase 4 — migrazione del live (`mal` → `mrcalld`) + cutover
- Finestra di downtime breve concordata con Mario.
- `systemctl stop` dei daemon `mal` (Gn9Icu + production@cafe124) → rilascia il
  fcntl lock.
- Sposta `~mal/.zylch/profiles/*` → `/home/mrcalld/.zylch/profiles/`,
  `chown -R mrcalld:mrcalld`.
- `sudo update-daemons.sh` → tutto risale sotto mrcalld/socket.
- Dismetti la vecchia unit `mal`, `/etc/zylch/*.conf`, `~mal/zylch-engine`.

**STOP.** Mario: production@cafe124 E mario.alemi, stesso url, ognuno i propri
dati in contemporanea; `kill -9` un daemon → respawn; `reboot` del server →
`/run/mrcalld` ricreata da tmpfiles + tutti i daemon risalgono.

## File toccati
```
engine/scripts/systemd/zylch-server@.service   rework: mrcalld, --unix, UMask, HOME, no EnvironmentFile
engine/scripts/caddy/desktop.Caddyfile         path_regexp uid -> unix socket (statico)
engine/scripts/tmpfiles.d/mrcalld.conf         NEW: d /run/mrcalld 2750 mrcalld caddy -
engine/scripts/server/update-daemons.sh        NEW: updater idempotente (git pull + discovery + enable/restart/disable)
engine/zylch/rpc/server_ws.py                  forse: chmod(0o660) del socket dopo bind se UMask non basta (RISCHIO #1)
docs/remote-backend.md                         riscrivi: modello mrcalld + "lancia update-daemons.sh" invece del runbook per-profilo
docs/execution-plans/cross-machine-transport.md  marca il brief multi-profilo come superseded -> punta qui
```

## Nodi aperti / da verificare nella sessione
- **RISCHIO #1 — perms del socket Unix** (vedi Phase 1): è il make-or-break.
  Provarlo subito, prima di scrivere lo script.
- **Gruppo di Caddy** sul VPS (`caddy` vs altro): confermare prima di D4.
- **Path profili sotto mrcalld**: `/home/mrcalld/.zylch/profiles/` (tiene la
  convenzione `~/.zylch` con `HOME=/home/mrcalld`) — raccomandato — vs
  `/var/lib/mrcalld/`. L'engine usa già `~/.zylch`.
- **Provisioning dei DATI** di un nuovo profilo: lo script SCOPRE i profili,
  non li CREA. Portare i dati sul server (rsync del profilo dal Mac, oppure
  `sudo -u mrcalld zylch -p <uid> update` sul server) resta uno step separato —
  documentarlo in remote-backend.md.
- **`caddy reload` e le connessioni WS aperte**: confermare che il reload è
  graceful (o accettare un breve reconnect lato app, che il client già gestisce).
- **`restart` idempotente**: valutare se lo script salta i daemon già attivi e
  invariati (per non droppare le connessioni ad ogni run quando il codice non è
  cambiato) — es. `restart` solo se `git pull` ha portato commit nuovi.

## Out of scope
- App mobile / web client → [`cross-machine-thin-clients.md`](cross-machine-thin-clients.md).
- Multi-tenant OSTILE (utenti Linux non fidati): qui `mrcalld` è fidato e
  possiede tutto. Isolamento per-tenant vero = piano a parte.
- HA / multi-region (un daemon per profilo, fcntl lock; nessun fan-out).

## Come iniziare la prossima sessione
1. Apri questo file + `cross-machine-transport.md` (contesto Phase 1–3b già live).
2. Phase 0 → Phase 1 e **fermati sul RISCHIO #1** (perms socket): se serve il
   `chmod` in `server_ws.py`, è una micro-modifica engine da testare reale.
3. Una phase alla volta, STOP + Mario verifica end-to-end. NEVER push senza ok.
