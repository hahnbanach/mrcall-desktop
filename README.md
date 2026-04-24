# MrCall Desktop

Local AI assistant for business communication — email (IMAP / SMTP),
WhatsApp, and phone (via MrCall) unified with a shared semantic memory
of every contact. Runs as a desktop app on **macOS** and **Windows**.
All data stays on your machine in a local profile directory; no cloud
sync.

This is a monorepo containing both the Python engine that talks to
mail / WhatsApp / phone / LLMs, and the Electron + React desktop
frontend that embeds it.

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
(Intel), Windows (x64). The installers are not yet code-signed —
gateway / SmartScreen bypass steps live in [`app/README.md`](app/README.md).

For Linux: install the engine directly from source via the CLI; see
[`engine/README.md`](engine/README.md).

## Develop

Each subdir has its own dev flow — see [`engine/README.md`](engine/README.md)
and [`app/README.md`](app/README.md).

For the orientation of agents (Claude Code, etc.) landing in this
repo, see [`CLAUDE.md`](CLAUDE.md).

## License

MIT. See [`LICENSE`](LICENSE).
