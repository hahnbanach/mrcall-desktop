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

- A dedicated **system user `mrcalld`** owns the engine checkout, **all**
  profiles, and runs **all** daemons (system-level systemd — no per-human
  `systemctl --user` / linger).
- One daemon per profile on a **per-uid Unix socket**
  `/run/mrcalld/<uid>.sock` (`serve --unix …`). No TCP ports to assign or
  remember, no collisions.
- **Caddy** routes `/ws/<uid>` → that socket with one **static** rule
  (`path_regexp`), so adding/removing profiles never touches Caddy. Every user
  shares `wss://<host>`; the app already appends `/ws/<uid>`.
- Security is the per-daemon Firebase-JWT gate (`token.uid == OWNER_ID`); a
  mis-route just fails `403`, so the routing is a hint, not the boundary.
- One idempotent **`sudo update-daemons.sh`** is the operational entry-point:
  pull code, discover profiles, ensure one daemon each, prune orphans.

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
> (`d /run/mrcalld 2750 mrcalld caddy -`) assumes **Caddy's group is `caddy`**
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

The engine **discovers** profiles; it does not create them. Copy **only the
profiles you want to run remotely** (not necessarily all of them), one dir per
uid, under the service user — it's private data, not in git. Note: a profile
runs **either** locally **or** remotely, never both at once (the fcntl lock
enforces it), and there is **no two-way sync** — once a profile is served from
the server, the server copy is the source of truth; don't keep running that same
profile locally against the old Mac copy, the two SQLite DBs would diverge. (And
≤1 WhatsApp profile per server — see Caveats.) Then run the updater:

```bash
# from your Mac: profile data -> server (rsync to /tmp, then move as root)
rsync -az ~/.zylch/profiles/<uid>/ user@server:/tmp/<uid>/
ssh user@server 'sudo mkdir -p /home/mrcalld/.zylch/profiles \
  && sudo mv /tmp/<uid> /home/mrcalld/.zylch/profiles/ \
  && sudo chown -R mrcalld:mrcalld /home/mrcalld/.zylch'
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

- **Single-operator trust.** `mrcalld` owns the code and every profile; this is
  fine for your own server. Hostile multi-tenancy (untrusted Linux users sharing
  the box) would need per-tenant isolation — a separate design.
- **WhatsApp is global, not per-profile.** `~/.zylch/whatsapp.db` (the neonize
  session) is shared across **all** of `mrcalld`'s daemons. Until it's made
  per-profile, run **at most one** profile with WhatsApp; two WhatsApp profiles
  under one `mrcalld` will conflict (`<conflict type="replaced"/>`, wrong-account
  data).
- **Server clock must be ~correct.** Firebase ID-token verification checks
  `exp`; a skewed clock rejects valid tokens. `timedatectl` should report
  synchronized.

## Agent runbook — exact commands

For an agent or script bringing up / updating the backend. Run from a checkout on
your Mac; set `SSH=<user@host>` (or an ssh-config alias). Use a variable like
`PROF`, **not** `UID` — `UID` is a read-only shell variable, so the assignment
silently fails and you target the wrong path.

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
ssh "$SSH" "sudo mkdir -p /home/mrcalld/.zylch/profiles \
  && sudo rm -rf /home/mrcalld/.zylch/profiles/$PROF \
  && sudo mv /tmp/$PROF /home/mrcalld/.zylch/profiles/ \
  && sudo chown -R mrcalld:mrcalld /home/mrcalld/.zylch \
  && sudo /home/mrcalld/mrcall-desktop/engine/scripts/server/update-daemons.sh"

# verify
ssh "$SSH" "systemctl is-active zylch-server@$PROF; sudo ls -l /run/mrcalld/$PROF.sock"
curl -s -o /dev/null -w 'gate %{http_code}\n' https://<host>/ws/$PROF   # expect 401 (no token)
```

**Traps (still apply):**

- **`pkill -f "serve …"` over SSH kills its own shell** — the remote command line
  *contains* that string. Stop by unit instead: `sudo systemctl stop zylch-server@<uid>`.
- **The "[ws] serving" line is INFO**, which lands in
  `~mrcalld/.zylch/profiles/<uid>/zylch.log`, not the console. An empty console
  after start is normal — check `systemctl is-active zylch-server@<uid>` and
  `sudo ls -l /run/mrcalld/<uid>.sock` (expect `srw-rw---- mrcalld caddy`).
- **`/run/mrcalld` is on tmpfs** → recreated at boot by `systemd-tmpfiles`; the
  daemons re-bind their sockets on start, so a reboot self-heals.
- **The server clock must be roughly correct** (token `exp` check); `timedatectl`
  should report synchronized.
