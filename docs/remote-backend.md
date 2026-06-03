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

## 1 · Install the engine on the server

A Linux box with **Python 3.11+** and outbound internet (for IMAP / the LLM):

```bash
# from a checkout of this repo, copy the engine over and install it in a venv
rsync -az engine/ user@server:zylch-engine/
ssh user@server 'cd zylch-engine && python3 -m venv venv && ./venv/bin/pip install -e .'
```

## 2 · Put your profile on the server

The engine reads a profile from `~/.zylch/profiles/<firebase-uid>/` (credentials
in `.env`, data in `zylch.db`). Copy yours from your Mac, or create + sync it on
the server with `zylch init` / `zylch -p <uid> update`:

```bash
rsync -az ~/.zylch/profiles/<uid>/ user@server:.zylch/profiles/<uid>/
```

Your `<uid>` is the Firebase UID shown next to your email in the app's
IdentityBanner (it's also the profile directory name).

## 3 · Run the engine as a WebSocket server

Quick check, foreground:

```bash
zylch -p <uid> serve --ws 127.0.0.1:5174
```

For a real daemon (starts at boot, restarts on crash) use the systemd template at
[`../engine/scripts/systemd/zylch-server@.service`](../engine/scripts/systemd/zylch-server@.service):

```bash
sudo cp engine/scripts/systemd/zylch-server@.service /etc/systemd/system/
printf 'ZYLCH_WS_ADDR=127.0.0.1:5174\n' | sudo tee /etc/zylch/<uid>.conf
sudo systemctl enable --now zylch-server@<uid>      # start now + at boot
```

Adjust `User=` and the binary path in the unit to match your server. Logs:
`journalctl -u zylch-server@<uid>` (warnings) and
`~/.zylch/profiles/<uid>/zylch.log` (full).

## 4 · Reach it from your Mac

Pick one:

**A — SSH tunnel** (simplest; no domain or certificate). Keep this open on your
Mac, and the app's URL is `ws://127.0.0.1:5174`:

```bash
ssh -L 5174:127.0.0.1:5174 user@server
```

**B — Public endpoint with TLS** (no tunnel; reachable as `wss://…`). Put
[Caddy](https://caddyserver.com) in front of the engine — it provisions a Let's
Encrypt certificate automatically. You need a hostname pointing at the server: a
real domain, or a free `<server-ip>.sslip.io`. Minimal Caddyfile (see
[`../engine/scripts/caddy/desktop.Caddyfile`](../engine/scripts/caddy/desktop.Caddyfile)):

```caddy
your-host.example.com {
    reverse_proxy /ws/* 127.0.0.1:5174
}
```

The app's URL is then `wss://your-host.example.com`.

## 5 · Point the app at it

In the app: **Settings → Backend location → Remote**, enter the URL from step 4,
hit **Test connection**, then **Apply & reconnect**. The app appends
`/ws/<your-uid>` to the URL itself. To switch back, choose **Local**.

The choice is stored per-machine in `~/.zylch/backend-config.json`; a fresh
install (no such file) always runs local.

---

Today this is a **single-operator** setup: you provision the daemon yourself, one
per profile. Running several profiles (or several people) behind one endpoint with
automatic per-user routing is designed but not yet built — see the full design and
the multi-profile brief in
[`execution-plans/cross-machine-transport.md`](execution-plans/cross-machine-transport.md).

## Agent runbook — provision one profile's daemon (exact commands)

For an agent (or a script) bringing up the backend for one profile on a server.
Run from a checkout of this repo on your Mac. Set `PROF` to the Firebase UID,
`SSH` to the server (`user@host` or an ssh-config alias), and `PORT` to a free
port (one per profile: 5174, 5175, …).

> Use `PROF`, **not** `UID` — `UID` is a read-only shell variable, so the
> assignment silently fails and you target the wrong path (`/profiles/501`).

```bash
PROF=<firebase-uid>; SSH=<user@host>; PORT=5174

# 1 · engine onto the server + venv install (idempotent)
rsync -az --exclude venv --exclude __pycache__ engine/ "$SSH:zylch-engine/"
ssh "$SSH" 'cd ~/zylch-engine && [ -x venv/bin/zylch ] || (python3 -m venv venv && ./venv/bin/pip install -e .)'

# 2 · this profile's data onto the server
rsync -az ~/.zylch/profiles/"$PROF"/ "$SSH:.zylch/profiles/$PROF/"

# 3 · systemd unit (once) + this profile's port + enable & start
ssh "$SSH" "set -e
  sudo cp ~/zylch-engine/scripts/systemd/zylch-server@.service /etc/systemd/system/
  sudo mkdir -p /etc/zylch
  printf 'ZYLCH_WS_ADDR=127.0.0.1:$PORT\n' | sudo tee /etc/zylch/$PROF.conf >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now zylch-server@$PROF
  sleep 6
  systemctl is-active zylch-server@$PROF
  ss -tlnp 2>/dev/null | grep ':$PORT' || echo 'NOT listening'"
```

The systemd unit hard-codes `User=mal` and `/home/mal/zylch-engine/…`; edit it for
a different server user. Then expose the port (§4 — SSH tunnel or Caddy) and set
the app's URL (§5).

**Traps a prior agent hit on this exact task — don't repeat them:**

- **`pkill -f "serve --ws …"` kills its own SSH shell.** The remote command line
  *contains* that string, so `pkill -f` matches the shell running it (→ exit 255,
  no output). Kill by port instead: `fuser -k "$PORT"/tcp`.
- **Backgrounding a daemon over SSH with a bare `&` hangs / exits 255** — the job
  keeps the SSH channel open. Use systemd (above) or detach fully:
  `( setsid CMD </dev/null >/tmp/log 2>&1 & )`.
- **The "serving" line is INFO**, which lands in the profile log, not the console.
  An empty console after start is normal — check `systemctl is-active` + `ss`, or
  `~/.zylch/profiles/$PROF/zylch.log` for `[ws] serving`.
- **The server clock must be roughly correct** — Firebase ID-token verification
  checks `exp`; a badly skewed clock rejects valid tokens. `timedatectl` should
  report synchronized.
