# Zylch Desktop

Local AI-powered sales intelligence, as a desktop app. Electron + React
front-end that talks to a bundled Python sidecar (JSON-RPC over stdio).
All data — inbox, tasks, embeddings, credentials — stays on your
machine under `~/.zylch/`.

## Download (alpha testers)

Grab the latest installer from the
[Releases page](https://github.com/malemi/zylch-desktop/releases):

- **macOS (Apple Silicon)**: `Zylch-<ver>-arm64.dmg`
- **macOS (Intel)**: `Zylch-<ver>.dmg`
- **Windows (x64)**: `Zylch-Setup-<ver>.exe`

The installers are **not code-signed** — your OS will warn you the
first time you open the app. Read on for how to bypass the warning.

## Install — macOS

1. Double-click the `.dmg`, drag **Zylch** into **Applications**.
2. Open **Applications**, **right-click** (or Ctrl-click) on
   `Zylch.app` and pick **Open**.
3. You'll see a dialog: _"macOS cannot verify the developer of
   Zylch"_. Click **Open**.
4. From now on you can launch Zylch normally from the Dock /
   Spotlight / Launchpad.

If you just double-click the app the first time, macOS only gives you
a **Cancel** button with no option to override — the right-click →
**Open** path is what lets you through.

## Install — Windows

1. Double-click `Zylch-Setup-<ver>.exe`.
2. Windows SmartScreen will say _"Windows protected your PC"_.
   Click the small **More info** link, then the **Run anyway**
   button that appears.
3. Follow the installer prompts (you can pick the install directory).
4. Launch Zylch from the Start menu.

## First launch — onboarding

The very first time you run Zylch there is no profile configured, so
the app opens a **"Welcome to Zylch"** window instead of the normal
interface. Fill in:

- **Email address** — identifies the profile.
- **LLM provider** + **API key** — Anthropic or OpenAI.
- **Email app password** — from your provider's account settings. Not
  your login password. (Zylch uses IMAP directly; no OAuth dance.)
- **IMAP / SMTP host + port** — auto-filled from common providers
  (Gmail, Outlook, iCloud, Yahoo); override if needed.
- **Telegram bot token** — optional.

On **Create profile and continue**, the wizard writes
`~/.zylch/profiles/<email>/.env` (file perms 600, dir perms 700) and
opens the main window. You're done.

Everything else (personal data, MrCall credentials, notes…) can be
edited from **Settings** after setup.

## Troubleshooting

- **"Profile already in use"** — another Zylch window or `zylch` CLI
  has the profile open. Close it and try again.
- **Crashes or "sidecar not running"** — the Python sidecar is
  bundled inside the app as `resources/bin/zylch`. If it fails to
  spawn, check `~/.zylch/<email>/logs/` for details and file an issue.
- **Reset** — delete `~/.zylch/profiles/<email>/` to wipe a profile.
  Delete `~/.zylch/` entirely to start from scratch.

## Build from source (contributors)

```bash
npm ci
# The desktop app expects a prebuilt `zylch` sidecar in ./bin/ — grab
# it from https://github.com/malemi/zylch/releases
mkdir -p bin
# macOS ARM:
gh release download --repo malemi/zylch --pattern zylch-macos-arm64 \
  --output bin/zylch && chmod +x bin/zylch
npm run dist:mac      # → dist/*.dmg
npm run dist:win      # → dist/*.exe (on Windows; Wine on others)
```

For dev (hot-reload, no packaged sidecar):

```bash
npm run dev
# Expects ~/private/zylch-standalone/venv/bin/zylch to exist. Override
# with ZYLCH_BINARY=/path/to/zylch if different.
```

## CI

`.github/workflows/release.yml` fires on tag push (`v*`) or manual
dispatch. It downloads the sidecar binary from the `malemi/zylch`
release matching each platform/arch, runs electron-builder, uploads
the installers as artifacts, and — on tag builds — attaches them to
the matching Desktop release.
