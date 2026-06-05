---
status: planned
owner: cross-cutting (engine + ops/Caddy + deploy)
created: 2026-06-05
supersedes: the "Next session — multi-profile / multi-user routing (brief)" section in cross-machine-transport.md
discipline: |
  Standard regole Mario. È PRODUZIONE: <prod-profile> gira live su
  desktop.mrcall.ai. NEVER claim "fatto"/"verificato" finché Mario non ha
  riconnesso il suo Electron e visto i SUOI dati passare DOPO la migrazione.
  Unit test / RPC probe / log NON contano: il test reale è "due profili
  diversi, STESSO url wss://desktop.mrcall.ai, ognuno vede i propri dati, e
  un re-run dello script non rompe niente". Una phase alla volta, ad ogni
  STOP dire a Mario esattamente cosa testare e aspettare "funziona". NEVER
  push senza ok esplicito. Italian register in chat.
---

# Multi-profile routing + daemon auto-update (`mrcalld` + per-uid Unix sockets)

## Stato sviluppo — 2026-06-05

**Phase 0 + Phase 1 fatte e PROVATE sul VPS reale** (engine + ops, zero impatto
sul live `<prod-uid>`):
- `server_ws.py` patchato: `chmod(0o660)` dopo bind + `unlink` del socket stale
  prima del bind (RISCHIO #1 + C2). py_compile OK.
- unit `zylch-server@.service` riscritta (mrcalld / `--unix` / UMask / StartLimit);
  nuovo `tmpfiles.d/mrcalld.conf`; `update-daemons.sh` scritto
  (`--dry-run` / `--prune` / `--restart-all`); `bash -n` OK + dry-run sul VPS OK.
- VPS: utente `mrcalld` creato; `/run/mrcalld` = `drwxr-s--- mrcalld caddy`
  (2750, setgid, gruppo caddy ✅); clone git + venv (wheel aarch64 tutte OK,
  `zylch --help` OK).
- **RISCHIO #1 chiuso**: il socket del daemon reale nasce
  `srw-rw---- mrcalld:caddy`; `caddy` connette, `www-data` (fuori dal gruppo)
  viene negato.
- **C2 chiuso**: `kill -9` → respawn ri-binda lo stesso socket; log mostra
  `removing stale socket`, **zero EADDRINUSE**.
- **Auth gate**: `caddy → unix socket → engine` ritorna `HTTP 401` senza token
  (è il path reale di produzione, meno il TLS).

**Cutover (Phase 2 + Phase 4) — FATTO live 2026-06-05** (Mario: «non c'è
produzione vera, continua pure»). `<prod-uid>` (<prod-profile>) migrato
`mal`→`mrcalld`, dati intatti (54 email / 18 task), su unix socket; Caddy
passato a `path_regexp`. Verificato `https://desktop.mrcall.ai/ws/<prod-uid>` →
401, uid inesistente → 502. **Multi-profilo dimostrato**: un 2° profilo
sintetico → due daemon/due socket sullo STESSO url, poi rimosso con `--prune`
(disabilita solo l'orfano). Aggiunto `ExecStopPost=rm <socket>` all'unit (stato
pulito allo stop); `update-daemons.sh` dogfooded (idempotente / `--restart-all`
/ `--prune`). Deploy fatto via scp nel clone (il clone resta "dirty" finché non
si committa+pusha e il VPS fa `git pull`).

**Restano:** (1) `git commit` + push delle modifiche worktree (gated su ok
esplicito) → poi il VPS gira `git pull` invece dello scp di oggi; (2) test
end-to-end dall'app col **token di Mario** (app → Remote → `wss://desktop.mrcall.ai`:
firmando come owner di <prod-uid> vede i suoi dati; un altro uid → 403); (3)
opzionale: portare il profilo `<uid-2>` (<your-account>) sul VPS per provarlo col
proprio account; (4) rimuovere il vecchio `~mal/zylch-engine` + `/etc/zylch/`
(tenuti ora come rollback).

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
  `zylch -p <uid> serve --unix /run/mrcalld/<uid>.sock`. Niente porte da
  assegnare/ricordare, niente collisioni, niente url-per-utente.
  (NB: `--unix` è **alternativo** a `--ws`, non additivo — `--ws` ha un default
  e prende un valore, quindi `serve --ws --unix …` è un errore di parsing che fa
  fallire il daemon. Firma reale: `engine/zylch/cli/main.py:401-473`.)
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
| `serve --ws 127.0.0.1:5174` (porta) | `serve --unix /run/mrcalld/<uid>.sock` |
| `/etc/zylch/<uid>.conf` con `ZYLCH_WS_ADDR` | **non serve più** (il path socket deriva da `%i`) |
| Caddy `reverse_proxy /ws/* 127.0.0.1:5174` (1 upstream) | `path_regexp uid` → socket per-uid (statico, N upstream) |
| 1 profilo raggiungibile (<prod-uid>); gli altri → 403 | tutti i profili raggiungibili, stesso url |
| provisioning a mano (runbook per-profilo in remote-backend.md) | `sudo update-daemons.sh` (auto-discovery) |

## Fasi (una alla volta, STOP + verifica di Mario ad ognuna)

### Phase 0 ✅ — preparazione (no downtime sul live)
- Crea `mrcalld` (system user, `HOME=/home/mrcalld`, shell `nologin`).
- `tmpfiles.d`: `d /run/mrcalld 2750 mrcalld caddy -`; `systemd-tmpfiles --create`.
- **Conferma il gruppo reale di Caddy** sul VPS (`caddy`? `www-data`?) → fissa D4.
- `git clone` → `/home/mrcalld/mrcall-desktop`; venv + `pip install -e .` (come mrcalld).

**STOP.** `/run/mrcalld` esiste con owner/perms giusti; `sudo -u mrcalld
/home/mrcalld/mrcall-desktop/engine/venv/bin/zylch --help` gira.

### Phase 1 ✅ — template unit + RISCHIO #1: perms del socket
- Riscrivi `zylch-server@.service`: `User=mrcalld`, `Group=mrcalld`,
  `Environment=HOME=/home/mrcalld`, `UMask=0007`, ExecStart
  `…/venv/bin/zylch -p %i serve --unix /run/mrcalld/%i.sock` (NON `--ws --unix`,
  vedi D2); **togli** `EnvironmentFile`; aggiungi in `[Unit]`
  `StartLimitIntervalSec=60` + `StartLimitBurst=5` così un profilo
  mal-configurato (es. senza `OWNER_ID`, che fa uscire l'engine con codice 1)
  non va in crash-loop infinito ogni `RestartSec` (R3).
- Copia UN profilo di **test** (NON production) sotto
  `/home/mrcalld/.zylch/profiles/<uid-test>/`, `chown -R mrcalld:mrcalld`,
  `enable --now zylch-server@<uid-test>`.
- **RISCHIO #1 — VERIFICARE PER PRIMO**: il socket creato da `--unix` deve
  essere apribile da Caddy (group `caddy`, group-write). `ls -l
  /run/mrcalld/<uid>.sock`. **Stato reale del codice (verificato 2026-06-05):
  `engine/zylch/rpc/server_ws.py` NON faceva né `chmod` né `unlink`.** Il fix è
  quindi già scritto in quel file: `os.chmod(0o660)` DOPO il bind (socket
  group-writable a prescindere da cosa producono umask/setgid) + `os.unlink()`
  del socket stale PRIMA del bind (C2 sotto). Resta da **provare sul VPS reale**
  che con questo Caddy (group `caddy`) connette davvero.
- **C2 — socket stale al restart**: su `kill -9` il file-socket resta in
  `/run/mrcalld` (tmpfs sopravvive fino al reboot); al restart
  `asyncio.create_unix_server` su py3.12 dà `EADDRINUSE` (non fa pre-unlink). Il
  fix in `server_ws.py` rimuove il socket stale prima del bind — sicuro perché
  il fcntl lock sul profilo (`cli/main.py` `acquire_lock`) garantisce una sola
  istanza, quindi un socket residuo è sempre nostro.

**STOP.** (a) `sudo -u caddy python3 -c "import socket; socket.socket(socket.AF_UNIX).connect('/run/mrcalld/<uid>.sock')"`
si connette senza permission denied; (b) `kill -9` del daemon → `systemctl` lo
fa ripartire e ri-binda lo stesso socket senza `EADDRINUSE`.

### Phase 2 ✅(Caddy fatto; app e2e = Mario) — Caddy per-uid + test end-to-end (un profilo)
⚠️ **Accoppiata con Phase 4.** Oggi il live `<prod-uid>` gira su **TCP** (`mal`,
`127.0.0.1:5174`) e il Caddy attuale è `reverse_proxy /ws/* 127.0.0.1:5174`.
Passando Caddy alla forma `path_regexp` → socket, il traffico di <prod-uid> verrebbe
instradato a `/run/mrcalld/<prod-uid>….sock` che **non esiste** finché <prod-uid> non è
migrato sotto mrcalld → **production 502**. Due opzioni:
- **(A) consigliata** — fare Phase 2 + Phase 4 nella STESSA finestra: prima
  migra <prod-uid> a mrcalld/socket (Phase 4), poi switcha Caddy. Un solo downtime.
- **(B) dual-route temporaneo** — tieni <prod-uid> su TCP e manda solo gli ALTRI uid
  sul socket, finché non migri anche lui:
  ```
  desktop.mrcall.ai {
      @prod path /ws/<prod-uid>
      reverse_proxy @prod 127.0.0.1:5174
      @ws path_regexp uid ^/ws/([^/]+)$
      reverse_proxy @ws unix//run/mrcalld/{re.uid.1}.sock
  }
  ```
- Porta `engine/scripts/caddy/desktop.Caddyfile` alla forma `path_regexp`
  (D3); `caddy validate`; reload.

**STOP.** Mario: app → `wss://desktop.mrcall.ai` (l'app appende `/ws/<uid-test>`),
il profilo di test si popola (Email/Tasks). Token di un ALTRO uid → 403; uid
inesistente → 502 pulito.

### Phase 3 ✅(scritto) — lo script updater `engine/scripts/server/update-daemons.sh`
Scritto e dry-run-verificato sul VPS (`bash -n` OK; flag `--dry-run` /
`--prune` / `--restart-all`). Il run live completo (con install del template +
daemon reali + eventuale `--prune`) va fatto col cutover (Phase 4).
Idempotente, gira da root/`sudo`:
1. `git -C /home/mrcalld/mrcall-desktop pull --ff-only`; `pip install -e .`
   **solo se** `pyproject.toml` è cambiato fra il vecchio e il nuovo `HEAD`
   (non c'è lockfile: è `pip install -e .`). Altrimenti l'editable install
   basta: il restart riprende il codice nuovo.
2. glob `/home/mrcalld/.zylch/profiles/*/` → lista uid (filtra: la dir deve
   contenere un `.env` **con `OWNER_ID` valorizzato** — senza, il daemon
   uscirebbe con codice 1 e finirebbe in restart fino allo `StartLimit`).
3. per ogni uid: `systemctl enable zylch-server@<uid>` + `restart`.
   `daemon-reload` una volta se il template è cambiato.
4. `disable --now zylch-server@<uid>` per le istanze attive senza più dir
   profilo (orfani). **Opt-in `--prune` (OFF di default)**: un prune
   pre-cutover vedrebbe il live `mal` <prod-uid> come orfano e lo spegnerebbe →
   production giù. Passare `--prune` SOLO dopo che ogni profilo è sotto mrcalld.
5. log riassuntivo: N profili trovati / N avviati / N orfani. NON tocca Caddy
   (statico).

**STOP.** Mario: crea una dir profilo finta → re-run → nuovo daemon su,
raggiungibile; rimuove la dir → re-run → daemon spento; re-run a vuoto = no-op
(stessi socket, nessun restart inutile se si decide di skippare i già-attivi).

### Phase 4 ✅ — migrazione del live (`mal` → `mrcalld`) + cutover
- Finestra di downtime breve concordata con Mario.
- `systemctl stop zylch-server@<uid>` (<prod-uid> = <prod-profile>, l'unico
  daemon `mal` live) → rilascia il fcntl lock.
- Sposta `~mal/.zylch/profiles/<uid>` → `/home/mrcalld/.zylch/profiles/`,
  `chown -R mrcalld:mrcalld`.
- **WhatsApp (R2)**: `~/.zylch/whatsapp.db` (sessione neonize) è **globale, non
  per-profilo** (known-issues engine) e sta in `~mal/.zylch/whatsapp.db`, FUORI
  da `profiles/` → il move sopra NON la porta: spostala a mano in
  `/home/mrcalld/.zylch/whatsapp.db` se il profilo migrato usa WhatsApp, oppure
  accetta un re-pairing QR post-cutover. ⚠️ Con più profili sotto `mrcalld`
  **condividono tutti la stessa `whatsapp.db`**: due profili con WhatsApp
  attivo confliggono (`<conflict type="replaced"/>`, dati dell'account
  sbagliato). Finché la whatsapp.db non è per-profilo, il multi-profilo è
  sicuro solo con **≤1 profilo WhatsApp**. Da chiudere prima di promettere
  "tanti profili con WhatsApp".
- `sudo update-daemons.sh` → tutto risale sotto mrcalld/socket.
- Dismetti la vecchia unit `mal` (NB: il suo ExecStart su disco punta già a
  `/home/mal/mrcall-desktop` che **non esiste** — il processo live gira ancora
  dal vecchio `~mal/zylch-engine`, quindi un suo restart oggi fallirebbe),
  `/etc/zylch/*.conf`, `~mal/zylch-engine`.

**STOP.** Mario: <prod-profile> E <your-account>, stesso url, ognuno i propri
dati in contemporanea; `kill -9` un daemon → respawn; `reboot` del server →
`/run/mrcalld` ricreata da tmpfiles + tutti i daemon risalgono.

## File toccati
```
engine/scripts/systemd/zylch-server@.service   rework: mrcalld, --unix (NON --ws --unix), UMask, HOME, no EnvironmentFile, StartLimit (R3); nome unit invariato (rename -> sweep zylch->mrcall)
engine/scripts/caddy/desktop.Caddyfile         path_regexp uid -> unix socket (statico)
engine/scripts/tmpfiles.d/mrcalld.conf         NEW: d /run/mrcalld 2750 mrcalld caddy - -- FATTO (gia' installato su VPS in /etc/tmpfiles.d/)
engine/scripts/server/update-daemons.sh        NEW: updater idempotente (git pull + discovery + enable/restart/disable) -- FATTO (--dry-run/--prune/--restart-all; prune opt-in; dry-run OK sul VPS)
engine/zylch/rpc/server_ws.py                  chmod(0o660) dopo bind + unlink del socket stale prima del bind (RISCHIO #1 + restart-after-kill C2) -- FATTO
docs/remote-backend.md                         riscrivi: modello mrcalld + "lancia update-daemons.sh" invece del runbook per-profilo
docs/execution-plans/cross-machine-transport.md  marca il brief multi-profilo come superseded -> punta qui
```

## Nodi aperti / da verificare nella sessione
- **RISCHIO #1 — perms del socket Unix** (vedi Phase 1): make-or-break. Fix
  scritto in `server_ws.py` (chmod+unlink); **da provare sul VPS reale** che
  Caddy connette + respawn dopo `kill -9`. Provarlo prima di scrivere lo script.
- **Gruppo di Caddy** sul VPS: ✅ confermato `caddy` (gid 987; caddy è anche in
  `www-data`). D4 usa `caddy`.
- **Path profili sotto mrcalld**: `/home/mrcalld/.zylch/profiles/` (tiene la
  convenzione `~/.zylch` con `HOME=/home/mrcalld`) — raccomandato — vs
  `/var/lib/mrcalld/`. L'engine usa già `~/.zylch`.
- **WhatsApp (R2)**: `~/.zylch/whatsapp.db` globale/non-per-profilo → con più
  profili sotto un solo `mrcalld` la sessione neonize è condivisa. Sicuro solo
  con ≤1 profilo WhatsApp finché non si rende la whatsapp.db per-profilo. Vedi
  Phase 4.
- **OWNER_ID mancante (R3)**: la discovery (Phase 3) filtra i profili con
  `.env`; aggiungere il filtro anche su `OWNER_ID` presente, perché il daemon
  esce con codice 1 senza — lo `StartLimit` nell'unit è la rete di sicurezza.
- **Naming unit**: si tiene `zylch-server@.service` (artefatto esistente); il
  rename a `mrcalld@.service` lo fa lo sweep zylch→mrcall, non questo piano
  (evita di rippleare in remote-backend.md + transport doc a metà lavoro).
- **Provisioning dei DATI** di un nuovo profilo: lo script SCOPRE i profili,
  non li CREA. Portare i dati sul server (rsync del profilo dal Mac, oppure
  `sudo -u mrcalld zylch -p <uid> update` sul server) resta uno step separato —
  documentarlo in remote-backend.md.
- **`caddy reload` e le connessioni WS aperte**: con Caddy STATICO (D3) il
  reload avviene solo al cutover iniziale a `path_regexp`, non a ogni profilo →
  preoccupazione minima (e il client già gestisce un reconnect breve).
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
2. Phase 0 → Phase 1 e **prova il RISCHIO #1** (perms socket): il fix
   (`chmod`+`unlink`) è già in `server_ws.py`; resta da verificarlo sul VPS
   reale (Caddy connette + respawn dopo `kill -9`).
3. Una phase alla volta, STOP + Mario verifica end-to-end. NEVER push senza ok.
