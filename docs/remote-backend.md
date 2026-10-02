# Running the backend on another machine

By default MrCall Desktop runs its engine **locally**, on the same machine as
the app — you don't have to do anything. This guide is for the optional setup
where you run the engine on a separate, always-on machine (a server / VPS) so it
keeps syncing and answering even with your laptop closed, and the app reaches it
over the network.

It's the same `zylch` engine either way; "remote" just means the app talks to it
over a WebSocket instead of spawning it locally. Auth is unchanged: the app sends
your Firebase ID token on the connection, and the engine only serves the profile
whose `OWNER_ID` matches your account (a token for any other account is rejected
with `403`).

Two ways to run it remotely:

- **[A] Quick (one profile, no domain)** — a loopback TCP WebSocket reached
  through an SSH tunnel. Good for trying it out.
- **[B] Production (many profiles, one public URL)** — a dedicated `mrcalld`
  service user runs one daemon per profile on a per-uid **Unix socket**, behind
  **Caddy** (TLS + Let's Encrypt). Every profile shares one URL
  `wss://<host>`; the app appends `/ws/<uid>` itself. This is what runs on the
  Scaleway VPS today.

Your `<uid>` is the Firebase UID shown next to your email in the app's
IdentityBanner — it is also the profile directory name.

**Automated provisioning (in progress, branch `phase-b-provisiond`).** A
vendor-side service, `zylch-provisiond`, is replacing the by-hand rsync
step in B.2 below with a POST from the desktop app itself, authenticated
with the same Firebase ID token the app already carries — see
[`../engine/scripts/server/README-provisiond.md`](../engine/scripts/server/README-provisiond.md)
for what it does, the install steps, and curl examples for both routes.
Service-first: not yet wired into the app, so B.2's rsync flow remains
how profiles actually land on the server today.

---

## A · Quick: one profile over an SSH tunnel

A Linux box with **Python 3.11+** and outbound internet (for IMAP / the LLM):

```bash
# the engine code is public (MIT) — clone it, no credentials, install into a venv
git clone https://github.com/hahnbanach/mrcall-desktop.git
cd mrcall-desktop/engine && python3 -m venv venv && ./venv/bin/pip install -e .
```

Copy your profile (private data, **not** in git):

```bash
rsync -az ~/.zylch/profiles/<uid>/ user@server:.zylch/profiles/<uid>/
```

Run it on loopback and tunnel from your Mac:

```bash
# on the server (foreground; for a daemon use option B's systemd unit)
zylch -p <uid> serve --ws 127.0.0.1:5174
# on your Mac — keep this open
ssh -L 5174:127.0.0.1:5174 user@server
```

In the app: **Settings → Backend location → Remote**, URL `ws://127.0.0.1:5174`,
**Test connection**, **Apply & reconnect**.

---

## B · Production: many profiles behind one URL (`mrcalld` + Caddy)

The model:

- A dedicated **system user `mrcalld`** owns the engine checkout and the venv
  (the **deploy identity**) and runs provisiond and every **unmigrated**
  daemon (system-level systemd — no per-human `systemctl --user` / linger).
- **One Unix user per profile** (since plan
  [toward-sandbox](execution-plans/2026-09-29-toward-sandbox.md) M2, in
  rollout): a migrated profile's daemon runs as `mc-<sha256(uid)[:12]>`,
  owns only its profile directory, is a member of its company's group
  `mc-c-<sha256(key)[:12]>` for the shared memory store, and runs inside a
  systemd sandbox (read-only checkout, `ProtectHome=tmpfs`, private `/tmp`,
  no capabilities) written as a per-instance drop-in by
  `mrcall-tenant create <uid>`. Names never carry the uid or the key. The
  template `zylch-server@.service` stays transitional (an unmigrated
  instance behaves exactly as before) until every profile is migrated.
- One daemon per profile on a **per-uid Unix socket**: migrated
  `/run/mrcalld/<uid>/ws.sock`, unmigrated `/run/mrcalld/<uid>.sock`
  (`serve --unix …`). No TCP ports to assign or remember, no collisions.
- **Caddy** routes `/ws/<uid>` → `/run/mrcalld/<uid>.sock` with one
  **static** rule (`path_regexp`, a single upstream), so adding/removing or
  migrating profiles never touches Caddy: a migrated profile's tmpfiles
  fragment makes that flat name a link to `<uid>/ws.sock`. Every user
  shares `wss://<host>`; the app already appends `/ws/<uid>`.
- A daemon **pinned** to a release (a drop-in with
  `Environment=PYTHONPATH=` naming a tree under `/home/mrcalld/releases`)
  stays pinned when migrated and when rolled back: the sandbox binds that
  tree read-only and `mrcall-tenant unmigrate` leaves the operator's
  drop-ins alone. `mrcall-tenant create` refuses a pin it cannot vouch
  for — outside the checkout and the releases tree, through a symbolic
  link or `..`, unreadable by the tenant, or set by an `EnvironmentFile` —
  and any other drop-in that sets `ExecStart`: a migrated unit runs
  `tenant.conf`'s command line only.
- Security over the network is the per-daemon Firebase-JWT gate
  (`token.uid == OWNER_ID`); a mis-route just fails `403`, so the routing is
  a hint, not the boundary. Security **on the host**, once a profile is
  migrated, is its Unix user: another company's daemon cannot read or write
  this profile's files; and the engine's own tools are confined to the
  profile's `downloads/` and `scratch/` folders on a hosted engine (M1, on
  `main` since `c2b3ca5`). Rollout state (2026-10-01): M1 is deployed to
  all seven daemons (the four pinned Café124 ones as backports); **no
  profile is migrated yet**, so every daemon still runs as `mrcalld`. The
  plan's records are the authority.
- One idempotent **`sudo update-daemons.sh`** is the operational entry-point:
  pull code, discover profiles, re-apply the identity of already-migrated
  profiles, ensure one daemon each, prune orphans. It never migrates a
  profile by itself: migration is the operator's explicit `mrcall-tenant
  create <uid>`, one profile per day, per the plan's runbook.

### B.1 · One-time server setup

```bash
SVC=mrcalld
# 1. service user (no login)
sudo useradd --system --create-home --home-dir /home/$SVC --shell /usr/sbin/nologin $SVC
# 2. engine checkout + venv, owned by the service user
sudo -u $SVC git clone https://github.com/hahnbanach/mrcall-desktop.git /home/$SVC/mrcall-desktop
sudo -u $SVC /usr/bin/python3 -m venv /home/$SVC/mrcall-desktop/engine/venv
sudo -u $SVC /home/$SVC/mrcall-desktop/engine/venv/bin/pip install -e /home/$SVC/mrcall-desktop/engine
ENG=/home/$SVC/mrcall-desktop/engine
# 3. runtime dir for the sockets (creates /run/mrcalld, group = Caddy's group)
sudo install -m 644 "$ENG/scripts/tmpfiles.d/mrcalld.conf" /etc/tmpfiles.d/
sudo systemd-tmpfiles --create /etc/tmpfiles.d/mrcalld.conf
# 4. systemd template
sudo install -m 644 "$ENG/scripts/systemd/zylch-server@.service" /etc/systemd/system/
sudo systemctl daemon-reload
# 5. Caddy site (static path_regexp) — EDIT the hostname inside first
sudo install -m 644 "$ENG/scripts/caddy/desktop.Caddyfile" /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
```

> **Confirm two assumptions for your box.** The unit template hard-codes user
> `mrcalld` and `/home/mrcalld/mrcall-desktop/engine`. The tmpfiles entry
> (`d /run/mrcalld 2751 mrcalld caddy -`; the other-execute bit lets a
> migrated profile's user traverse to its own socket dir) assumes **Caddy's group is `caddy`**
> — check with `id caddy`; if it differs (e.g. `www-data`), edit
> `scripts/tmpfiles.d/mrcalld.conf` before installing. The setgid dir + the
> daemon's `chmod(0o660)` on its socket are what let Caddy connect.

**Working as `mrcalld`.** It is a **nologin service account** by design, so
`su - mrcalld` / SSH login is refused (`This account is currently not
available`) — that's expected, not a misconfiguration. You never need to log in
as it; operate through `sudo`:

```bash
sudo -u mrcalld git -C /home/mrcalld/mrcall-desktop pull   # run one command as mrcalld
sudo -u mrcalld -H bash                                    # interactive shell as mrcalld
sudo su -s /bin/bash - mrcalld                             # su-style (-s overrides the nologin shell)
```

Day-to-day you don't even need that — admin runs as root: `sudo update-daemons.sh`,
`sudo systemctl {status,restart} zylch-server@<uid>`, `journalctl -u zylch-server@<uid>`.

### B.2 · Per profile: bring the data, then run the updater

> Being replaced by `zylch-provisiond` (branch `phase-b-provisiond`) —
> see the note above. This rsync-by-hand flow stays the documented path
> until that service is wired into the app; nothing below is deleted or
> deprecated yet.

The engine **discovers** profiles; it does not create them. Copy **only the
profiles you want to run remotely** (not necessarily all of them), one dir per
uid, under the service user — it's private data, not in git. Note: a profile
runs **either** locally **or** remotely, never both at once (the fcntl lock
enforces it), and there is **no two-way sync** — once a profile is served from
the server, the server copy is the source of truth; don't keep running that same
profile locally against the old Mac copy, the two SQLite DBs would diverge.
Then run the updater:

```bash
# from your Mac: profile data -> server (rsync to /tmp, then move as root)
rsync -az ~/.zylch/profiles/<uid>/ user@server:/tmp/<uid>/
ssh user@server 'sudo mkdir -p /home/mrcalld/.zylch/profiles \
  && sudo mv /tmp/<uid> /home/mrcalld/.zylch/profiles/ \
  && sudo chown -R mrcalld:mrcalld /home/mrcalld/.zylch/profiles/<uid>'   # only this dir: never -R the whole tree on a host with migrated profiles (`mrcall-tenant list`)
# discover + start every profile
ssh user@server 'sudo /home/mrcalld/mrcall-desktop/engine/scripts/server/update-daemons.sh'
```

`update-daemons.sh` (idempotent, run as root):

1. `git pull`, then `pip install -e .` **only** if `engine/pyproject.toml`
   changed (an editable install already tracks code edits).
2. ensures the systemd template + tmpfiles are current.
3. discovers every profile dir whose `.env` sets `OWNER_ID`, and enables +
   (re)starts one `zylch-server@<uid>` daemon for each.
4. with `--prune`, disables daemons whose profile dir is gone (orphans).

Flags: `--dry-run` (print actions, change nothing), `--restart-all` (restart
every daemon even with no new commits — default restarts only when `git pull`
brought new commits, so a no-op run doesn't drop live WebSocket connections),
`--prune` (**off by default**: only pass it when every profile you still want is
present under the discovery dir, or it will stop the missing ones).

**Several profiles at once.** Stage them under a disk dir you own, move them in,
then a single updater run picks them all up (use real disk, not `/tmp` if it's
`tmpfs` — the email DBs can be hundreds of MB each):

```bash
# from your Mac — rsync the profiles you want remote (exclude any already on the
# server) into a staging dir under your own home, then move + chown as root:
rsync -az --exclude='<uid-already-on-server>' ~/.zylch/profiles/ user@server:_stage/profiles/
# chown only the dirs just moved — never the whole tree once `mrcall-tenant list` is non-empty
ssh user@server 'for d in ~/_stage/profiles/*/; do u=$(basename "$d"); sudo mv "$d" /home/mrcalld/.zylch/profiles/ \
  && sudo chown -R mrcalld:mrcalld "/home/mrcalld/.zylch/profiles/$u"; done \
  && sudo /home/mrcalld/mrcall-desktop/engine/scripts/server/update-daemons.sh \
  && rm -rf ~/_stage'
```

`update-daemons.sh` enables + starts one daemon per discovered profile;
already-running ones with no new commits are left alone (live connections kept).

### B.3 · Point the app at it

**Settings → Backend location → Remote**, URL `wss://<host>` (base URL only — no
path; the app appends `/ws/<your-uid>`), **Test connection**, **Apply &
reconnect**. To switch back, choose **Local**. The choice is stored per-machine
in `~/.zylch/backend-config.json`; a fresh install always runs local.

### B.4 · Updating later

```bash
sudo /home/mrcalld/mrcall-desktop/engine/scripts/server/update-daemons.sh           # pull + restart changed
sudo /home/mrcalld/mrcall-desktop/engine/scripts/server/update-daemons.sh --prune   # + remove orphans
```

---

## Caveats

- **This host is multi-tenant, and the boundary between tenants is the
  per-profile Unix user.** Until a profile is migrated (`mrcall-tenant
  create`), its daemon still runs as `mrcalld` next to every other
  unmigrated one, with only the M1 tool confinement between them. The
  threat model, the evidence and the acceptance criteria are in
  [the toward-sandbox brief](briefs/2026-09-29-toward-sandbox.md); the
  migration runbook (M2.7) and its rollback (`mrcall-tenant unmigrate`)
  in [the plan](execution-plans/2026-09-29-toward-sandbox.md). Root
  executes, from the `mrcalld`-writable checkout, the unit and tmpfiles
  files `update-daemons.sh` installs and the helper it copies to
  `/usr/local/sbin` (`install -m 750`, the only path a sudoers rule may
  name). `/etc/logrotate.d/mrcalld` is generated by that helper
  (`mrcall-tenant logrotate`, re-run by `create`, `unmigrate`, `delete` and
  every `update-daemons.sh`): unmigrated logs rotate as `mrcalld`, each
  migrated profile's log as its own user. Do not edit it by hand.
- **WhatsApp is per profile.** The neonize session lives at
  `<profile>/whatsapp.db`; the global `~/.zylch/whatsapp.db` is a legacy
  fallback the daemons never use (`ZYLCH_PROFILE_DIR` is always set).
- **Server clock must be ~correct.** Firebase ID-token verification checks
  `exp`; a skewed clock rejects valid tokens. `timedatectl` should report
  synchronized.
- **Never open a live profile DB or company store as any user but the
  daemon's — not even read-only.** `sqlite3 'file:.../zylch.db?mode=ro'` run
  as your login user (or as root, or as `mrcalld` on a migrated profile)
  creates a `zylch.db-shm` owned by *you*; the daemon then can't write the
  WAL and every write dies with `attempt to write a readonly database` (the
  `.db` itself looks fine — check the `-wal`/`-shm` owners). For diagnostics,
  copy the DB out first, or read via `sudo -u <daemon user> sqlite3 <db>`
  (`mrcalld` unmigrated, `mc-…` migrated; `mrcall-tenant names <uid>` prints
  it; `?immutable=1` only on a copy — it ignores the WAL, so it shows a stale
  snapshot of a live DB). Every store-touching operator command runs as the
  tenant with `umask 007` (the helper's `as_tenant`, `join-company.sh`);
  `rekey` is the one root step, followed by `mrcall-tenant create` to re-own
  what root created. Recovery: `chown <daemon user>` the `-wal`/`-shm` (safe when `-wal` is
  0 bytes = nothing pending) and `systemctl restart` the unit.

## Agent runbook — exact commands

For an agent or script bringing up / updating the backend.

### First: are you ON the server, or remote?

**Deploying from the server itself** (hostname `desktop`, user `mrcalld` exists,
`/run/mrcalld/` has sockets) — NO SSH needed, run directly:

```bash
sudo /home/mrcalld/mrcall-desktop/engine/scripts/server/update-daemons.sh   # pull + restart changed daemons
```

If `sudo` needs a password you don't have, or you're on another machine, use SSH
below. The script is idempotent: run it repeatedly, it only restarts daemons
when `git pull` brought new commits (pass `--restart-all` to force).

### Remote (from your Mac or a checkout elsewhere)

Set `SSH=<user@host>` (or an ssh-config alias; the production box answers at
`mal@desktop.mrcall.ai`). Use a variable like `PROF`, **not** `UID` — `UID` is a
read-only shell variable, so the assignment silently fails and you target the
wrong path.

```bash
SSH=<user@host>; PROF=<firebase-uid>

# one-time: service user + engine + runtime dir + units + Caddy (idempotent)
ssh "$SSH" 'set -e
  id mrcalld >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /home/mrcalld --shell /usr/sbin/nologin mrcalld
  [ -d /home/mrcalld/mrcall-desktop/.git ] || sudo -u mrcalld git clone https://github.com/hahnbanach/mrcall-desktop.git /home/mrcalld/mrcall-desktop
  ENG=/home/mrcalld/mrcall-desktop/engine
  [ -d "$ENG/venv" ] || sudo -u mrcalld /usr/bin/python3 -m venv "$ENG/venv"
  sudo -u mrcalld "$ENG/venv/bin/pip" install -e "$ENG" -q
  sudo install -m 644 "$ENG/scripts/tmpfiles.d/mrcalld.conf" /etc/tmpfiles.d/
  sudo systemd-tmpfiles --create /etc/tmpfiles.d/mrcalld.conf
  sudo install -m 644 "$ENG/scripts/systemd/zylch-server@.service" /etc/systemd/system/
  sudo install -m 644 "$ENG/scripts/caddy/desktop.Caddyfile" /etc/caddy/Caddyfile   # EDIT hostname
  sudo systemctl daemon-reload
  sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy'

# per profile: PRIVATE data up (rsync, not git), then discover + start
rsync -az ~/.zylch/profiles/"$PROF"/ "$SSH:/tmp/$PROF/"
# chown only this profile dir — never the whole tree once `mrcall-tenant list` is non-empty
ssh "$SSH" "sudo mkdir -p /home/mrcalld/.zylch/profiles \
  && sudo rm -rf /home/mrcalld/.zylch/profiles/$PROF \
  && sudo mv /tmp/$PROF /home/mrcalld/.zylch/profiles/ \
  && sudo chown -R mrcalld:mrcalld /home/mrcalld/.zylch/profiles/$PROF \
  && sudo /home/mrcalld/mrcall-desktop/engine/scripts/server/update-daemons.sh"

# verify
ssh "$SSH" "systemctl is-active zylch-server@$PROF; sudo ls -l /run/mrcalld/$PROF.sock /run/mrcalld/$PROF/ws.sock 2>/dev/null"   # flat = unmigrated, <uid>/ws.sock = migrated
curl -s -o /dev/null -w 'gate %{http_code}\n' https://<host>/ws/$PROF   # expect 401 (no token)
```

**Traps (still apply):**

- **`pkill -f "serve …"` over SSH kills its own shell** — the remote command line
  *contains* that string. Stop by unit instead: `sudo systemctl stop zylch-server@<uid>`.
- **The "[ws] serving" line is INFO**, which lands in
  `~mrcalld/.zylch/profiles/<uid>/zylch.log`, not the console. An empty console
  after start is normal — check `systemctl is-active zylch-server@<uid>` and
  `sudo ls -l /run/mrcalld/<uid>.sock` (expect `srw-rw---- mrcalld caddy`;
  a migrated profile has `/run/mrcalld/<uid>/ws.sock`, `srw-rw---- mc-… caddy`).
- **`/run/mrcalld` is on tmpfs** → recreated at boot by `systemd-tmpfiles`; the
  daemons re-bind their sockets on start, so a reboot self-heals.
- **The server clock must be roughly correct** (token `exp` check); `timedatectl`
  should report synchronized.

## Shared company memory on the host (since 2026-09)

The six original entity-memory tables no longer live in a profile's `zylch.db`: each
company has one SQLite store under `~mrcalld/.zylch/memory/`, and every
profile holding that key shares it. Its file is named after a hash of the
key, in a per-company subdirectory owned by the company group
(`mc-c-<sha256(key)[:12]>/<sha256(key)[:32]>.db`, mode `2770`); stores
created before the toward-sandbox plan still carry the legacy name
`<MEMORY_KEY>.db` until the operator relocates them (`zylch -p <uid>
memory-relocate-store`, with **all** of the company's daemons stopped —
plan step 2a), and the engine opens whichever exists, never creating a
second one. `zylch -p <uid> memory-names` prints the derived names; the
legacy path is never printed because it is the key. The key is a 128-bit
capability in the profile `.env` (`MEMORY_KEY`, with `MEMORY_KEY_SOURCE`
saying how it was obtained: `mint`, `provision`, `join`). The company store
also owns its metadata/history tables and the three authored-project tables;
see [written project memory](../engine/docs/features/project-memory.md).

**First boot after the deploy that ships it.** Each daemon runs two
migration steps under its own lock: `0001_company_key` mints a key (the
profile has none), backs up `zylch.db` to `<profile>/backups/`, stamps every
memory row; `0002_memory_split` copies the six tables into a new
`memory/<key>.db` and drops them from `zylch.db`. Five daemons therefore
start with five separate memories — exactly what they had, now keyed.

**Converging profiles of one company.** Joining is a merge (facts converge
one row per key, entities are all kept, rules stay personal) and the old
store file is left on disk. From the host, as root:

```bash
engine/scripts/server/join-company.sh table                  # uid, email, key, store size per profile
engine/scripts/server/join-company.sh <uid> <MEMORY_KEY>     # stop the daemon, echo, confirm, join, start it
```

The second form runs `zylch -p <uid> memory-join <key>` as the service
user: the preview echo (self-notion, size, contributors), a confirmation
prompt, then the merge and the switch (`--yes` as a third argument skips
the prompt, for scripts). **There is no company check**: the key is the
capability, so joining `support@` to a Café 124 key merges MrCall's memory
into Café 124's store — read the echo before confirming. A join is refused
while the profile's own memory work in its current company is unsettled;
the refusal lists each operation and the command that settles it
(`zylch -p <uid> memory-join --drain <key>`, which first runs one memory pass
and may pay, or `zylch -p <uid> memory-reviews --retry|--dismiss <id>`).
While a join runs, the source company's memory writes are refused for every
profile on it; a join that stopped is finished or undone by its profile's
next boot, or `memory-join --release-fence` releases it
([contract](../engine/docs/features/company-memory-join.md)). The same join is available to a signed-in user from
the desktop app (Settings → Company memory → paste, Test, Join) over the
WebSocket.

**New profiles (provisiond).** `provisiond` injects the company key from
the host's map, `PROVISIOND_COMPANY_MAP` (default
`/etc/mrcalld/company-map.json`, a JSON object of `"<uid>": "<MEMORY_KEY>"`
pairs, operator-maintained). A uid the map does not name is **refused**
(403) rather than given a default key: this host is multi-tenant, and a
fallback is how two tenants end up in one memory. A `MEMORY_KEY` in the
provision request body is refused too.

**Duplicates after a join.** Both memories' entities are kept, so a person
both knew exists twice until consolidation folds the two — when both
headers state the same identity. The daemon runs consolidation after every
update whenever the store changed since the last sweep (a join, a merge, a
new entity, a new identifier on an entity), once per company (the other
daemons see "another engine is sweeping"); the desktop Settings →
Maintenance → Reconsolidate button and `zylch -p <uid> memory-sweep` run it
on demand. Each pair decision is one to three LLM calls, each pair an
admitted preparation item, at most 50 per run and never more than the
preparation batch (re-run to continue). Every run also prunes old memory
versions and reports the sinks — memories kept whole until their owner
restores a version.

**Memory unavailable** (no key, an unknown typed key, a missing store) is
never a unit failure: the daemon serves mail sync, `memory.status` says why
memory is off, and the memory worker leaves mail unprocessed — no LLM call
is spent — until the store exists. `zylch -p <uid> memory-status` shows the
same from the host.

**LLM credential and daily budget.** A profile provisioned by hand has no
desktop app pushing a Firebase token, so the MrCall-credits mode has no
session there: mail syncs, but the memory and task stages skip until the
profile `.env` carries a BYOK key (`LLM_PROVIDER=anthropic` +
`ANTHROPIC_API_KEY=…`), and the daemon reads `.env` only at start
(`systemctl restart zylch-server@<uid>`). Spend is capped per profile and
per UTC day by `LLM_DAILY_BUDGET_USD` (default 10, `0` = no cap; the
`[llm-budget]` line of the tick names the numbers); consolidation spends
from the budget of the profile whose tick runs it. A large
backlog is analysed in daily instalments at the cap — raise it for a day
with a line in `.env` and a restart.

**Upgrading to the mnemonic harness (milestones 5–9).** Design and milestone
acceptance are tracked in the
[cross-repository harness plan](../../docs/execution-plans/2026-09-20-mnemonic-harness.md).
The previously referenced `2026-09-30-mnemonic-rollout.md` is absent from this
workspace. Its detailed rollout gates and rollback stages cannot be verified;
a reviewed rollout plan is required before any live upgrade. Host prerequisites:

- *The per-unit pin.* This guide documents one checkout that
  `update-daemons.sh` pulls and one `ExecStart` for every instance, so before
  anything else read what actually serves each unit (`git rev-parse` in the
  checkout, `systemctl show -p FragmentPath,DropInPaths,ExecStart
  zylch-server@<uid>` per profile) and record it here. If no per-unit pin
  exists, the plan's proposal is a second checkout with its own venv and a
  systemd drop-in `zylch-server@<uid>.service.d/release.conf` that resets
  `ExecStart=` to that venv — a host change the CTO authorizes.
- *The rehearsal on a copy.* Before the first live unit, copy the profile's
  `zylch.db`, its `.env` and the company store through the SQLite backup API
  (see Caveats: never open a live DB as another user) under a scratch root,
  and boot the new engine on the copy twice with `ZYLCH_HOME` and
  `MEMORY_DB_DIR` pointing at it: the first boot runs the store steps (the
  destructive one is preceded by a backup under `<store dir>/backups/`), the
  second is a no-op. A store the new build migrates cannot be opened by a
  milestone 5–7 build; the hosted engines never ran one.
- *The order per unit:* pause saved (preparation paused, `AUTO_UPDATE_ENABLED`
  not `Yes`, the clone's operator paused with `CS_PAUSE`) → restart the unit
  on the new commit → `zylch -p <uid> memory-status` and `memory-reviews`
  clean → one bounded run and one supervised correction → soak on the plan's
  measures → resume only on the CTO's yes.

The milestone's paid corpus never runs on a host profile: it runs on a
disposable profile under a scratch root, the provider key enters only as
`ANTHROPIC_API_KEY` in the process environment — never on argv, in a log or
in the record — is copied once into that profile's `.env` (mode 600), and the
profile directory is deleted once the record is extracted.
