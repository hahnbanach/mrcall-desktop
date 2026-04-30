# MrCall Desktop

Local AI-powered desktop assistant for email, WhatsApp, and the MrCall
phone. Electron + React front-end that talks to a bundled Python sidecar
(JSON-RPC over stdio). All data — inbox, tasks, embeddings, credentials —
stays on your machine under `~/.zylch/`.

## Download (alpha testers)

Grab the latest installer from the
[Releases page](https://github.com/hahnbanach/mrcall-desktop/releases):

- **macOS (Apple Silicon)**: `MrCall Desktop-<ver>-arm64.dmg`
- **macOS (Intel)**: `MrCall Desktop-<ver>-x64.dmg` *(opt-in build; see CI)*
- **Windows (x64)**: `MrCall Desktop-Setup-<ver>-x64.exe`

The installers are **not code-signed** — your OS will warn you the
first time you open the app. Read on for how to bypass the warning.

## Install — macOS

1. Double-click the `.dmg`, drag **MrCall Desktop** into **Applications**.
2. Open **Applications**, **right-click** (or Ctrl-click) on
   `MrCall Desktop.app` and pick **Open**.
3. You'll see a dialog: _"macOS cannot verify the developer of
   MrCall Desktop"_. Click **Open**.
4. From now on you can launch MrCall Desktop normally from the Dock /
   Spotlight / Launchpad.

If you just double-click the app the first time, macOS only gives you
a **Cancel** button with no option to override — the right-click →
**Open** path is what lets you through.

## Install — Windows

1. Double-click `MrCall Desktop-Setup-<ver>-x64.exe`.
2. Windows SmartScreen will say _"Windows protected your PC"_.
   Click the small **More info** link, then the **Run anyway**
   button that appears.
3. Follow the installer prompts (you can pick the install directory).
4. Launch MrCall Desktop from the Start menu.

## First launch — onboarding

The very first time you run MrCall Desktop there is no profile
configured, so the app opens a **"Welcome to MrCall Desktop"** window
instead of the normal interface. Fill in:

- **Email address** — identifies the profile.
- **LLM provider** + **API key** — Anthropic or OpenAI.
- **Email app password** — from your provider's account settings. Not
  your login password. (MrCall Desktop uses IMAP directly; no OAuth dance.)
- **IMAP / SMTP host + port** — auto-filled from common providers
  (Gmail, Outlook, iCloud, Yahoo); override if needed.
- **Telegram bot token** — optional.

On **Create profile and continue**, the wizard writes
`~/.zylch/profiles/<email>/.env` (file perms 600, dir perms 700) and
opens the main window. You're done.

Everything else (personal data, MrCall credentials, notes…) can be
edited from **Settings** after setup.

## Troubleshooting

- **"Profile already in use"** — another MrCall Desktop window or
  `zylch` CLI has the profile open. Close it and try again.
- **Crashes or "sidecar not running"** — the Python sidecar is
  bundled inside the app as `resources/bin/zylch`. If it fails to
  spawn, check `~/.zylch/<email>/logs/` for details and file an issue.
- **Reset** — delete `~/.zylch/profiles/<email>/` to wipe a profile.
  Delete `~/.zylch/` entirely to start from scratch.

## Develop locally (hot-reload)

After cloning the repo and checking out the branch you want to test:

```bash
cd app
npm ci                                # installs Node deps from package-lock.json
```

The renderer spawns the Python `zylch` sidecar over stdio. It looks
for the binary at `~/private/zylch-standalone/venv/bin/zylch` by
default; override with `ZYLCH_BINARY=/path/to/zylch`.

If you don't already have a `zylch` venv on disk, install the engine
in dev mode from this same repo:

```bash
cd ../engine && pip install -e .       # exposes a `zylch` script in your venv
export ZYLCH_BINARY=$(which zylch)     # confirm Python finds it
cd ../app && npm run dev               # opens Electron with hot-reload
```

Hot-reload picks up renderer (TSX / CSS) changes live. Edits to the
Electron main process under `src/main/` need a restart of `npm run dev`.

A fresh checkout has no profiles, so first launch shows the
**Welcome to MrCall Desktop** onboarding form — see "First launch" above.

## Build installers (release path)

The PyInstaller-bundled sidecar is what ships in the released `.dmg`
/ `.exe`; the release workflow does this on every CI run. Locally:

```bash
# 1. Build the sidecar from the engine subdir.
cd ../engine
pip install -e . pyinstaller
pyinstaller --noconfirm zylch.spec
cp dist/zylch ../app/bin/zylch && chmod +x ../app/bin/zylch

# 2. Build the installer.
cd ../app
npm ci
npm run dist:mac      # → dist/*.dmg
npm run dist:win      # → dist/*.exe (run on Windows; Wine cross-build is fragile)
```

## CI

`.github/workflows/release.yml` (in the repo root):

- Tag push `v*` → builds macOS arm64 + Windows x64, attaches installers
  to a GitHub Release.
- Tag push `v*-intel` (e.g. `v0.1.25-intel`) → adds macOS Intel x64 on
  the paid `macos-13-large` runner.
- `workflow_dispatch` with `include_intel: true|false` → manual run,
  artifacts only.
