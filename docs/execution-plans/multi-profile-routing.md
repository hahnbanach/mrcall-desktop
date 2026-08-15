---
status: completed
completed: 2026-06-05
owner: cross-cutting (engine + ops/Caddy + deploy)
created: 2026-06-05
supersedes: the "Next session — multi-profile / multi-user routing (brief)" section in cross-machine-transport.md
discipline: |
  Mario's standard rules. This is PRODUCTION: <prod-profile> runs live on
  desktop.mrcall.ai. NEVER claim "done"/"verified" until Mario has
  reconnected his Electron and seen HIS OWN data flow AFTER the migration.
  Unit tests / RPC probes / logs do NOT count: the real test is "two
  different profiles, the SAME url wss://desktop.mrcall.ai, each seeing its
  own data, and a re-run of the script breaking nothing". One phase at a
  time; at every STOP tell Mario exactly what to test and wait for his
  confirmation. NEVER push without an explicit go-ahead. Italian register
  in the chat.
---

# Multi-profile routing + daemon auto-update (`mrcalld` + per-uid Unix sockets)

## Development status — 2026-06-05

**Phase 0 + Phase 1 done and PROVEN on the real VPS** (engine + ops, zero impact
on the live `<prod-uid>`):
- `server_ws.py` patched: `chmod(0o660)` after bind + `unlink` of the stale
  socket before bind (RISK #1 + C2). py_compile OK.
- The `zylch-server@.service` unit rewritten (mrcalld / `--unix` / UMask /
  StartLimit); new `tmpfiles.d/mrcalld.conf`; `update-daemons.sh` written
  (`--dry-run` / `--prune` / `--restart-all`); `bash -n` OK + dry-run on the VPS OK.
- VPS: `mrcalld` user created; `/run/mrcalld` = `drwxr-s--- mrcalld caddy`
  (2750, setgid, group caddy ✅); git clone + venv (all aarch64 wheels fine,
  `zylch --help` OK).
- **RISK #1 closed**: the real daemon's socket is created as
  `srw-rw---- mrcalld:caddy`; `caddy` connects, `www-data` (outside the group)
  is denied.
- **C2 closed**: `kill -9` → the respawn re-binds the same socket; the log shows
  `removing stale socket`, **zero EADDRINUSE**.
- **Auth gate**: `caddy → unix socket → engine` returns `HTTP 401` without a
  token (this is the real production path, minus TLS).

**Cutover (Phase 2 + Phase 4) — DONE live 2026-06-05** (Mario: "there is no real
production, go ahead"). `<prod-uid>` (<prod-profile>) migrated `mal`→`mrcalld`,
data intact (54 emails / 18 tasks), onto a unix socket; Caddy switched to
`path_regexp`. Verified `https://desktop.mrcall.ai/ws/<prod-uid>` → 401, and a
non-existent uid → 502. **Multi-profile demonstrated**: a 2nd synthetic profile →
two daemons/two sockets on the SAME url, then removed with `--prune` (which
disables only the orphan). Added `ExecStopPost=rm <socket>` to the unit (clean
state on stop); `update-daemons.sh` dogfooded (idempotent / `--restart-all` /
`--prune`). The deploy was done by scp into the clone (the clone stays "dirty"
until the changes are committed+pushed and the VPS runs `git pull`).

**Still open:** (1) `git commit` + push of the worktree changes (gated on an
explicit go-ahead) → then the VPS runs `git pull` instead of today's scp;
(2) an end-to-end test from the app with **Mario's token** (app → Remote →
`wss://desktop.mrcall.ai`: signing as the owner of <prod-uid> he sees his data;
another uid → 403); (3) optional: bring the `<uid-2>` profile (<your-account>)
onto the VPS to test it with his own account; (4) remove the old
`~mal/zylch-engine` + `/etc/zylch/` (kept for now as a rollback).

## Goal

Serve *many* profiles (and in prospect many users) behind the single
`wss://desktop.mrcall.ai` endpoint, each routed to its own engine daemon,
with **one idempotent `sudo` script** that updates the code, discovers every
profile, guarantees one daemon per profile, and shuts down the orphans.

**The key property — the reason it is built this way.** With per-uid sockets +
per-uid routing, **every user uses the SAME url** `wss://desktop.mrcall.ai`:
the app appends `/ws/<its-own-uid>` by itself. No per-user url, no ports to
remember, no "change the url in Settings" at the next migration (the ports
problem Mario raised). **The app does NOT change** — the Electron-side client
is already there and already appends `/ws/<uid>`.

## Decisions locked (Mario, 2026-06-05)

- **D1 — a dedicated `mrcalld` service user.** It owns the engine checkout +
  ALL profiles and runs ALL daemons. A system user, no login. No more
  per-human `systemctl --user` / linger (as the previous brief assumed):
  **system-level** units with `User=mrcalld`. Simpler and standard for a
  service.
- **D2 — one Unix socket per uid, NOT a TCP port.**
  `zylch -p <uid> serve --unix /run/mrcalld/<uid>.sock`. No ports to
  assign/remember, no collisions, no per-user url.
  (NB: `--unix` is an **alternative** to `--ws`, not additive — `--ws` has a
  default and takes a value, so `serve --ws --unix …` is a parse error that
  makes the daemon fail. Real signature: `engine/zylch/cli/main.py:401-473`.)
- **D3 — Caddy routes by the uid in the path** → socket, with ONE static rule:
  ```
  desktop.mrcall.ai {
      @ws path_regexp uid ^/ws/([^/]+)$
      reverse_proxy @ws unix//run/mrcalld/{re.uid.1}.sock
  }
  ```
  Security remains the **per-daemon JWT gate** (`uid == OWNER_ID`): a mis-route
  fails with 403; routing is a hint, not the security.
- **D4 — `/run/mrcalld/`** owned `mrcalld:caddy`, mode `2750` (setgid → sockets
  inherit group `caddy`); the daemon runs with `UMask=0007` so the socket is
  group-writable and Caddy (group `caddy`) can connect. Created via
  `tmpfiles.d` (it's on tmpfs, it must be recreated at every boot).
- **D5 — the updater script is the only operational entry point.** The systemd
  template and the Caddy snippet are versioned artifacts the script uses.

## An important consequence: Caddy is STATIC

With the generic `^/ws/([^/]+)$` regex the socket path is computed from the uid
at runtime (`{re.uid.1}`). So **the Caddyfile is written ONCE and never touched
again** when profiles are added or removed. The updater script manages **only
the daemons** (enable/restart/disable) — it neither regenerates nor reloads
Caddy. A uid with no socket → Caddy 502 (no data exposed, acceptable).

## What changes relative to today

| Today (live) | After |
|---|---|
| daemon `User=mal`, from `~/zylch-engine` (rsync) | `User=mrcalld`, from `/home/mrcalld/mrcall-desktop/engine` (git) |
| `serve --ws 127.0.0.1:5174` (a port) | `serve --unix /run/mrcalld/<uid>.sock` |
| `/etc/zylch/<uid>.conf` with `ZYLCH_WS_ADDR` | **no longer needed** (the socket path derives from `%i`) |
| Caddy `reverse_proxy /ws/* 127.0.0.1:5174` (1 upstream) | `path_regexp uid` → per-uid socket (static, N upstreams) |
| 1 reachable profile (<prod-uid>); the others → 403 | every profile reachable, same url |
| manual provisioning (per-profile runbook in remote-backend.md) | `sudo update-daemons.sh` (auto-discovery) |

## Phases (one at a time, STOP + Mario's verification at each)

### Phase 0 ✅ — preparation (no downtime on the live profile)
- Create `mrcalld` (system user, `HOME=/home/mrcalld`, shell `nologin`).
- `tmpfiles.d`: `d /run/mrcalld 2750 mrcalld caddy -`; `systemd-tmpfiles --create`.
- **Confirm Caddy's real group** on the VPS (`caddy`? `www-data`?) → this fixes D4.
- `git clone` → `/home/mrcalld/mrcall-desktop`; venv + `pip install -e .` (as mrcalld).

**STOP.** `/run/mrcalld` exists with the right owner/perms; `sudo -u mrcalld
/home/mrcalld/mrcall-desktop/engine/venv/bin/zylch --help` runs.

### Phase 1 ✅ — unit template + RISK #1: socket permissions
- Rewrite `zylch-server@.service`: `User=mrcalld`, `Group=mrcalld`,
  `Environment=HOME=/home/mrcalld`, `UMask=0007`, ExecStart
  `…/venv/bin/zylch -p %i serve --unix /run/mrcalld/%i.sock` (NOT `--ws --unix`,
  see D2); **remove** `EnvironmentFile`; add to `[Unit]`
  `StartLimitIntervalSec=60` + `StartLimitBurst=5` so a mis-configured profile
  (e.g. without `OWNER_ID`, which makes the engine exit with code 1) doesn't
  crash-loop forever every `RestartSec` (R3).
- Copy ONE **test** profile (NOT production) under
  `/home/mrcalld/.zylch/profiles/<uid-test>/`, `chown -R mrcalld:mrcalld`,
  `enable --now zylch-server@<uid-test>`.
- **RISK #1 — VERIFY THIS FIRST**: the socket created by `--unix` must be
  openable by Caddy (group `caddy`, group-write). `ls -l
  /run/mrcalld/<uid>.sock`. **Real state of the code (verified 2026-06-05):
  `engine/zylch/rpc/server_ws.py` did NEITHER `chmod` NOR `unlink`.** The fix is
  therefore already written in that file: `os.chmod(0o660)` AFTER the bind (a
  group-writable socket regardless of what umask/setgid produce) + `os.unlink()`
  of the stale socket BEFORE the bind (C2 below). What remains is **proving on
  the real VPS** that with this Caddy (group `caddy`) it really connects.
- **C2 — stale socket at restart**: on `kill -9` the socket file stays in
  `/run/mrcalld` (tmpfs survives until reboot); at restart
  `asyncio.create_unix_server` on py3.12 raises `EADDRINUSE` (it does no
  pre-unlink). The fix in `server_ws.py` removes the stale socket before the
  bind — safe because the profile's fcntl lock (`cli/main.py` `acquire_lock`)
  guarantees a single instance, so a leftover socket is always ours.

**STOP.** (a) `sudo -u caddy python3 -c "import socket; socket.socket(socket.AF_UNIX).connect('/run/mrcalld/<uid>.sock')"`
connects without permission denied; (b) `kill -9` on the daemon → `systemctl`
restarts it and it re-binds the same socket without `EADDRINUSE`.

### Phase 2 ✅(Caddy done; app e2e = Mario) — per-uid Caddy + end-to-end test (one profile)
⚠️ **Coupled with Phase 4.** Today the live `<prod-uid>` runs on **TCP** (`mal`,
`127.0.0.1:5174`) and the current Caddy is `reverse_proxy /ws/* 127.0.0.1:5174`.
Switching Caddy to the `path_regexp` → socket form would route <prod-uid>'s
traffic to `/run/mrcalld/<prod-uid>….sock`, which **does not exist** until
<prod-uid> is migrated under mrcalld → **production 502**. Two options:
- **(A) recommended** — do Phase 2 + Phase 4 in the SAME window: migrate
  <prod-uid> to mrcalld/socket first (Phase 4), then switch Caddy. A single
  downtime.
- **(B) temporary dual-route** — keep <prod-uid> on TCP and send only the OTHER
  uids to the socket, until it is migrated too:
  ```
  desktop.mrcall.ai {
      @prod path /ws/<prod-uid>
      reverse_proxy @prod 127.0.0.1:5174
      @ws path_regexp uid ^/ws/([^/]+)$
      reverse_proxy @ws unix//run/mrcalld/{re.uid.1}.sock
  }
  ```
- Bring `engine/scripts/caddy/desktop.Caddyfile` to the `path_regexp` form
  (D3); `caddy validate`; reload.

**STOP.** Mario: app → `wss://desktop.mrcall.ai` (the app appends
`/ws/<uid-test>`), the test profile populates (Email/Tasks). A token from
ANOTHER uid → 403; a non-existent uid → a clean 502.

### Phase 3 ✅(written) — the updater script `engine/scripts/server/update-daemons.sh`
Written and dry-run-verified on the VPS (`bash -n` OK; `--dry-run` /
`--prune` / `--restart-all` flags). The full live run (installing the template +
real daemons + a possible `--prune`) belongs to the cutover (Phase 4).
Idempotent, runs as root/`sudo`:
1. `git -C /home/mrcalld/mrcall-desktop pull --ff-only`; `pip install -e .`
   **only if** `pyproject.toml` changed between the old and the new `HEAD`
   (there is no lockfile: it's `pip install -e .`). Otherwise the editable
   install suffices: the restart picks up the new code.
2. glob `/home/mrcalld/.zylch/profiles/*/` → the uid list (filtered: the
   directory must contain a `.env` **with `OWNER_ID` set** — without it the
   daemon would exit with code 1 and keep restarting up to the `StartLimit`).
3. for each uid: `systemctl enable zylch-server@<uid>` + `restart`.
   `daemon-reload` once if the template changed.
4. `disable --now zylch-server@<uid>` for active instances whose profile
   directory is gone (orphans). **Opt-in `--prune` (OFF by default)**: a
   pre-cutover prune would see the live `mal` <prod-uid> as an orphan and shut
   it down → production down. Pass `--prune` ONLY after every profile is under
   mrcalld.
5. a summary log: N profiles found / N started / N orphans. It does NOT touch
   Caddy (static).

**STOP.** Mario: creates a fake profile directory → re-run → a new daemon comes
up, reachable; removes the directory → re-run → the daemon goes down; an empty
re-run is a no-op (same sockets, no pointless restart if we decide to skip
already-active ones).

### Phase 4 ✅ — migrating the live profile (`mal` → `mrcalld`) + cutover
- A short downtime window agreed with Mario.
- `systemctl stop zylch-server@<uid>` (<prod-uid> = <prod-profile>, the only
  live `mal` daemon) → releases the fcntl lock.
- Move `~mal/.zylch/profiles/<uid>` → `/home/mrcalld/.zylch/profiles/`,
  `chown -R mrcalld:mrcalld`.
- **WhatsApp (R2)**: `~/.zylch/whatsapp.db` (the neonize session) is **global,
  not per-profile** (engine known-issues) and lives in `~mal/.zylch/whatsapp.db`,
  OUTSIDE `profiles/` → the move above does NOT carry it: move it by hand to
  `/home/mrcalld/.zylch/whatsapp.db` if the migrated profile uses WhatsApp, or
  accept a post-cutover QR re-pairing. ⚠️ With several profiles under `mrcalld`
  **they all share the same `whatsapp.db`**: two profiles with WhatsApp active
  conflict (`<conflict type="replaced"/>`, data from the wrong account). Until
  whatsapp.db is per-profile, multi-profile is safe only with **≤1 WhatsApp
  profile**. To be closed before promising "many profiles with WhatsApp".
- `sudo update-daemons.sh` → everything comes back up under mrcalld/socket.
- Decommission the old `mal` unit (NB: its on-disk ExecStart already points at
  `/home/mal/mrcall-desktop`, which **does not exist** — the live process still
  runs from the old `~mal/zylch-engine`, so restarting it today would fail),
  `/etc/zylch/*.conf`, `~mal/zylch-engine`.

**STOP.** Mario: <prod-profile> AND <your-account>, same url, each seeing its
own data simultaneously; `kill -9` a daemon → respawn; `reboot` the server →
`/run/mrcalld` recreated by tmpfiles + all daemons come back up.

## Files touched
```
engine/scripts/systemd/zylch-server@.service   rework: mrcalld, --unix (NOT --ws --unix), UMask, HOME, no EnvironmentFile, StartLimit (R3); unit name unchanged (rename -> zylch->mrcall sweep)
engine/scripts/caddy/desktop.Caddyfile         path_regexp uid -> unix socket (static)
engine/scripts/tmpfiles.d/mrcalld.conf         NEW: d /run/mrcalld 2750 mrcalld caddy - -- DONE (already installed on the VPS in /etc/tmpfiles.d/)
engine/scripts/server/update-daemons.sh        NEW: idempotent updater (git pull + discovery + enable/restart/disable) -- DONE (--dry-run/--prune/--restart-all; prune opt-in; dry-run OK on the VPS)
engine/zylch/rpc/server_ws.py                  chmod(0o660) after bind + unlink of the stale socket before bind (RISK #1 + restart-after-kill C2) -- DONE
docs/remote-backend.md                         rewrite: the mrcalld model + "run update-daemons.sh" instead of the per-profile runbook
docs/execution-plans/cross-machine-transport.md  mark the multi-profile brief as superseded -> point here
```

## Open questions / to verify during the session
- **RISK #1 — Unix socket permissions** (see Phase 1): make-or-break. The fix is
  written in `server_ws.py` (chmod+unlink); it must be **proven on the real VPS**
  that Caddy connects + the respawn after `kill -9` works. Prove it before
  writing the script.
- **Caddy's group** on the VPS: ✅ confirmed as `caddy` (gid 987; caddy is also
  in `www-data`). D4 uses `caddy`.
- **Profile path under mrcalld**: `/home/mrcalld/.zylch/profiles/` (keeping the
  `~/.zylch` convention with `HOME=/home/mrcalld`) — recommended — vs
  `/var/lib/mrcalld/`. The engine already uses `~/.zylch`.
- **WhatsApp (R2)**: `~/.zylch/whatsapp.db` is global/not-per-profile → with
  several profiles under a single `mrcalld` the neonize session is shared. Safe
  only with ≤1 WhatsApp profile until whatsapp.db is made per-profile. See
  Phase 4.
- **Missing OWNER_ID (R3)**: discovery (Phase 3) filters profiles by `.env`; add
  a filter on `OWNER_ID` being present too, because the daemon exits with code 1
  without it — the unit's `StartLimit` is the safety net.
- **Unit naming**: `zylch-server@.service` is kept (an existing artifact); the
  rename to `mrcalld@.service` belongs to the zylch→mrcall sweep, not to this
  plan (it avoids rippling into remote-backend.md + the transport doc halfway
  through the work).
- **Provisioning a new profile's DATA**: the script DISCOVERS profiles, it does
  not CREATE them. Getting the data onto the server (rsync of the profile from
  the Mac, or `sudo -u mrcalld zylch -p <uid> update` on the server) stays a
  separate step — to be documented in remote-backend.md.
- **`caddy reload` and open WS connections**: with a STATIC Caddy (D3) the
  reload happens only at the initial cutover to `path_regexp`, not per profile →
  a minimal concern (and the client already handles a brief reconnect).
- **Idempotent `restart`**: consider having the script skip daemons that are
  already active and unchanged (so it doesn't drop connections on every run when
  the code hasn't changed) — e.g. `restart` only if `git pull` brought new
  commits.

## Out of scope
- Mobile app / web client → [`cross-machine-thin-clients.md`](cross-machine-thin-clients.md).
- HOSTILE multi-tenancy (untrusted Linux users): here `mrcalld` is trusted and
  owns everything. Real per-tenant isolation is a separate plan.
- HA / multi-region (one daemon per profile, fcntl lock; no fan-out).

## How to start the next session
1. Open this file + `cross-machine-transport.md` (context: Phase 1–3b already live).
2. Phase 0 → Phase 1 and **prove RISK #1** (socket perms): the fix
   (`chmod`+`unlink`) is already in `server_ws.py`; it remains to be verified on
   the real VPS (Caddy connects + respawn after `kill -9`).
3. One phase at a time, STOP + Mario verifies end-to-end. NEVER push without a
   go-ahead.
