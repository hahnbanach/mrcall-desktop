# MrCall Desktop

Local AI assistant for business communication — email (IMAP / SMTP),
WhatsApp, SMS, and phone (via MrCall), unified with a shared memory of
every contact. It watches your inbox, figures out what needs doing, and
drafts replies for you to review. Available today as a desktop app for
**macOS on Apple Silicon**.

## What stays on your machine

Your inbox, contacts, and credentials live in a local profile on your own
computer — none of it is uploaded anywhere. The only thing that leaves
your machine is your sign-in, used to talk to MrCall's own services
(phone, SMS, business lookups).

## Get started

1. **Create a (free) MrCall account** if you don't have one — the app
   signs in with the same account as the
   [web dashboard](https://mrcall.ai).
2. **Download** the macOS (Apple Silicon) installer from
   [Releases](https://github.com/hahnbanach/mrcall-desktop/releases) and
   open the `.dmg`, then drag **MrCall Desktop** into **Applications**.
3. **First launch.** The app is signed but not yet notarized, so macOS
   will refuse to open it with *"Apple could not verify…"* — the usual
   right-click → Open trick no longer works around this on current
   macOS. Instead:
   - **System Settings → Privacy & Security**, scroll down, click
     **Open Anyway** next to the MrCall Desktop warning, or
   - run this once in a terminal:
     ```bash
     xattr -d com.apple.quarantine "/Applications/MrCall Desktop.app"
     ```
4. **Sign in**, then follow the onboarding wizard to connect your email
   and, optionally, WhatsApp and your MrCall phone number.

That's it — the assistant runs locally while the app is open. (For the AI
itself you pick a mode in **Settings**: your own LLM key, or MrCall
credits.)

## Keep it running when your Mac is closed

Normally the assistant only works while the app is open — close it, or
shut the Mac, and it stops. There's a one-click fix: in the app's left
sidebar, a row shows whether this profile is running on MrCall's servers,
with an **Activate** button.

Click it and, in under a minute, a copy of your profile is running on
MrCall's servers — same assistant, same mailbox, still syncing and
drafting replies overnight, on weekends, while you travel. Nothing to
configure. Click the small **(i)** next to the row in the app for the
full explanation.

If you'd rather run your own always-on server instead of using MrCall's,
that's the advanced route: see
[`docs/remote-backend.md`](docs/remote-backend.md).

---

## Everything technical

### Repository layout

- **[`engine/`](engine/)** — Python 3.11+ sidecar (the brain). IMAP /
  SMTP, WhatsApp (neonize), SMS, MrCall phone, blob memory, hybrid
  lexical + semantic search over local SQLite. BYOK LLM (Anthropic or
  OpenAI).
- **[`app/`](app/)** — Electron + React desktop frontend that embeds
  the engine via JSON-RPC over stdio. Builds `.dmg` and `.exe`
  installers via `electron-builder`.
- **[`docs/`](docs/)** — monorepo-wide documentation.

This is a monorepo containing both halves: the Python engine that talks
to mail / WhatsApp / phone / LLMs, and the Electron + React desktop
frontend that embeds it.

### The sign-in token, mechanically

On signin the renderer pushes a short-lived Firebase ID token to the
engine, which uses it to authenticate outgoing calls to MrCall's
backends (phone, SMS, business lookups, and MrCall-credits billing); the
token itself is held in memory only and never persisted.

### Run from source (dev)

Build the two halves and run the app against the engine you just built:

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

### Windows and Intel Mac builds

Windows (x64) and macOS Intel x64 are not published on
[Releases](https://github.com/hahnbanach/mrcall-desktop/releases) yet —
both are opt-in legs of the CI build, off by default. Until they're
published, get them by building from source (above) on the target
platform, or by triggering the opt-in CI build yourself; see
[`app/README.md`](app/README.md) for the flags.

For Linux: install the engine directly from source via the CLI; see
[`engine/README.md`](engine/README.md). The Electron frontend isn't
packaged for Linux.

### Develop

Each subdir has its own dev flow — see [`engine/README.md`](engine/README.md)
and [`app/README.md`](app/README.md).

For the orientation of agents (Claude Code, etc.) landing in this
repo, see [`CLAUDE.md`](CLAUDE.md).

## License

MIT. See [`LICENSE`](LICENSE).
