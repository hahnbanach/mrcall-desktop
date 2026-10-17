# MrCall Desktop

Local AI assistant for business communication — email (IMAP / SMTP),
WhatsApp, SMS, and phone (via MrCall) — with **one memory per company**:
what every colleague's mailbox teaches it about your customers, suppliers
and deals, digested into a shared memory for the profiles joined to it.
It helps you find messages, identify what needs doing, and draft replies
for you to review. Automatic processing is optional and off by default.

## What stays on your machine

Your inbox, contacts and credentials live on the machine running your engine:
your computer for a local profile, or the selected remote server. AI processing
sends relevant message and memory content to the configured LLM service. MrCall
services receive the authentication and request data needed for phone, SMS,
business lookups and credit billing. Company memory stays on the engine host.

## Get started

1. **Create a MrCall account** if you don't have one — the app
   signs in with the same account as the
   [web dashboard](https://mrcall.ai).
2. **Download** the installer from
   [Releases](https://github.com/hahnbanach/mrcall-desktop/releases).
3. **First launch on Mac:** check the installer release notes for signing
   and notarization status. If macOS blocks an installer you obtained from
   the official release, open **System Settings → Privacy & Security** and
   look for **Open Anyway** next to the MrCall Desktop warning.
4. **Sign in**, then follow the onboarding wizard to connect your email
   and, optionally, WhatsApp and Google Calendar.

That's it — the assistant runs locally while the app is open. (For the AI
itself you pick a mode in **Settings**: an Anthropic or OpenRouter key,
or MrCall credits.)

## Keep it running when your laptop is closed

A profile can run on an always-on server, so you can use the same assistant
from the app while its engine stays running after your laptop closes.
Hosted activation currently requires operator setup; self-serve enrollment
is not open. Contact your administrator to set up remote access.

For your own server, see the [remote setup guide](docs/remote-backend.md).

## One memory for the whole company

Colleagues on the same server can share what their assistants learn about
customers, suppliers and agreements. Each hosted profile runs separately:
its mailbox, credentials and downloaded files stay private, while the
assistant uses shared company knowledge and each person's reply preferences.
Other companies have separate memories.

Hosted sharing requires administrator setup. Separate laptops running
locally do not automatically share memory. See
[how sharing and isolation work](docs/cross-cutting-contracts.md#separate-profiles-shared-company-memory).

---

## Everything technical

### Desktop, MCP and daemon data flows

See the [sequence diagrams](docs/operator-data-flows.md) for sign-in,
Claude/ChatGPT authorization, all nine candidate MCP tools, local-file access
and revocation. The diagrams distinguish existing Desktop behavior, the
unreleased local connector candidate and the proposed remote service.

### Development documentation

[AGENTS.md](AGENTS.md) maps the repository and its responsibilities.
See [engine development](engine/README.md), [app development](app/README.md)
and the [documentation index](docs/README.md) for technical guidance.

### The sign-in token, mechanically

On signin the renderer pushes a short-lived Firebase ID token to the
engine, which uses it to authenticate outgoing calls to MrCall's
backends (phone, SMS, business lookups, and MrCall-credits billing).
The engine keeps that ID token in memory. Refresh tokens have a separate
storage contract; see [authentication and credentials](docs/cross-cutting-contracts.md#identity-firebase--added-2026-05-02).

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

The default release build targets macOS Apple Silicon. Windows x64 and
macOS Intel x64 builds are opt-in and off by default; check the
[release assets](https://github.com/hahnbanach/mrcall-desktop/releases)
for available installers. Developers can build on the target platform or
trigger the opt-in CI build; see [app development](app/README.md) for flags.

For Linux: install the engine directly from source via the CLI; see
[`engine/README.md`](engine/README.md). The Electron frontend isn't
packaged for Linux.

### Develop

Each subdir has its own dev flow — see [`engine/README.md`](engine/README.md)
and [`app/README.md`](app/README.md).

For the orientation of agents (Claude Code, etc.) landing in this
repo, see [`AGENTS.md`](AGENTS.md).

## License

MIT. See [`LICENSE`](LICENSE).
