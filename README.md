# MrCall Desktop

Local AI assistant for business communication — email (IMAP / SMTP),
WhatsApp, SMS, and phone (via MrCall) — with **one memory per company**:
what every colleague's mailbox teaches it about your customers, suppliers
and deals, digested into a single memory that every account draws on.
It watches your inbox, figures out what needs doing, and
drafts replies for you to review.

## What stays on your machine

Your inbox, contacts, and credentials live in a local profile on your own
computer — none of it is uploaded anywhere. The only thing that leaves
your machine is your sign-in, used to talk to MrCall's own services
(phone, SMS, business lookups). The company memory lives wherever your
profile runs: on this machine, or on the server that keeps it running
when your laptop is closed (below).

## Get started

1. **Create a (free) MrCall account** if you don't have one — the app
   signs in with the same account as the
   [web dashboard](https://mrcall.ai).
2. **Download** the installer from
   [Releases](https://github.com/hahnbanach/mrcall-desktop/releases).
3. **First launch on Mac:** the app is signed but not yet notarized, so macOS
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

## Keep it running when your laptop is closed

In the app's left
sidebar, a row shows whether this profile is running on MrCall's servers,
with an **Activate** button.

Click it and, in under a minute, a copy of your profile is running on
MrCall's servers — same assistant, same mailbox, still syncing and
drafting replies overnight, on weekends, while you travel. Nothing to
configure.

If you'd rather run your own always-on server instead of using MrCall's,
that's the advanced route: see
[`docs/remote-backend.md`](docs/remote-backend.md).

## One memory for the whole company

Every mailbox the assistant reads teaches it something — who a customer
is, what was agreed, which supplier answers slowly. MrCall Desktop keeps
all of it in **one memory per company**, not one per inbox: what
`production@` learns this morning, the colleague writing from `sales@`
uses this afternoon. The memory holds people, companies and facts,
digested from the mail and WhatsApp of everyone who shares it, and
duplicates unite by themselves as new mail comes in. What stays personal
is how *you* write: your reply templates and preferences never leave your
own account.

The company is a **memory key** — a random 22-character string minted the
first time an account is created, shown once and always available in
**Settings → Company memory** with a copy button. To bring a colleague
in, send them the key the way you would send a Wi-Fi password: they paste
it in the "memory key" field when they create their account (or later, in
the same Settings card), the app echoes what they are about to join — the
company's name and how much it already knows — and their account joins
the shared memory. Whoever holds the key is in; nobody else can read it.

The memory is shared between accounts running on the same server:
MrCall's always-on servers (the **Activate** button above) or a server of
your own ([`docs/remote-backend.md`](docs/remote-backend.md)). Two
laptops each running the app locally keep two separate memories.

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
repo, see [`AGENTS.md`](AGENTS.md).

## License

MIT. See [`LICENSE`](LICENSE).
