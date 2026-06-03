# MrCall Desktop

Local AI assistant for business communication — email (IMAP / SMTP),
WhatsApp, and phone (via MrCall) unified with a shared semantic memory
of every contact. Runs as a desktop app on **macOS** and **Windows**.

Your inbox, tasks, embeddings, and credentials live in a local profile
directory under `~/.zylch/<firebase-uid>/`; nothing syncs to the cloud.
The only network identity is a Firebase Auth signin that gates the
app — the same MrCall account you use on the [web
dashboard](https://mrcall.ai). On signin the renderer pushes a short-
lived ID token to the engine purely to authenticate outgoing MrCall
phone calls; the token is held in memory only and never persisted.

This is a monorepo containing both the Python engine that talks to
mail / WhatsApp / phone / LLMs, and the Electron + React desktop
frontend that embeds it.

## Getting started

1. **Create a (free) MrCall account** if you don't have one — the app signs
   in with the same account as the [web dashboard](https://mrcall.ai).
2. **Download and launch** the installer for your platform from
   [Releases](https://github.com/hahnbanach/mrcall-desktop/releases)
   (per-platform notes under [Install](#install-alpha)).
3. **Sign in** and follow the onboarding wizard — connect your email and,
   optionally, WhatsApp and your MrCall phone number.

That's it: the **backend runs locally on your machine** by default, nothing
else to set up. (For the AI itself you pick a mode in **Settings** — your own
LLM key, or MrCall credits.)

**Backend on another machine (optional).** You can run the engine on an
always-on server instead, so it keeps working with your laptop closed. Follow
[`docs/remote-backend.md`](docs/remote-backend.md), then point the app at your
server in **Settings → Backend location → Remote**.

**Run from source (dev).** Build the two halves and run the app against the
engine you just built:

```bash
# 1 · engine (Python sidecar) — needs Python 3.11+
cd engine
python3 -m venv venv && ./venv/bin/pip install -e .

# 2 · desktop app
cd ../app
npm ci
ZYLCH_BINARY="$PWD/../engine/venv/bin/zylch" npm run dev
```

Full dev / packaging details: [`app/README.md`](app/README.md) and
[`engine/README.md`](engine/README.md).

## Repository layout

- **[`engine/`](engine/)** — Python 3.11+ sidecar (the brain). IMAP /
  SMTP, WhatsApp (neonize), MrCall phone, blob memory, hybrid lexical +
  semantic search over local SQLite. BYOK LLM (Anthropic or OpenAI).
- **[`app/`](app/)** — Electron + React desktop frontend that embeds
  the engine via JSON-RPC over stdio. Builds `.dmg` and `.exe`
  installers via `electron-builder`.
- **[`docs/`](docs/)** — monorepo-wide documentation.

## Install (alpha)

Installers are produced by the GitHub Actions release pipeline and
attached to releases at:

- https://github.com/hahnbanach/mrcall-desktop/releases

Three platform variants per release: macOS (Apple Silicon), macOS
(Intel, opt-in `v*-intel` builds), Windows (x64).

- **macOS** installers are code-signed with a Developer ID certificate
  and notarized — they should open without Gatekeeper warnings.
- **Windows** installers are not yet code-signed; SmartScreen will
  prompt on first launch. The bypass and the full first-run guide
  (signin → onboarding wizard → main window) live in
  [`app/README.md`](app/README.md).

For Linux: install the engine directly from source via the CLI; see
[`engine/README.md`](engine/README.md). The Electron frontend isn't
packaged for Linux.

## Develop

Each subdir has its own dev flow — see [`engine/README.md`](engine/README.md)
and [`app/README.md`](app/README.md).

For the orientation of agents (Claude Code, etc.) landing in this
repo, see [`CLAUDE.md`](CLAUDE.md).

## License

MIT. See [`LICENSE`](LICENSE).
 
