# CLAUDE.md

**MrCall Desktop** — local AI assistant for business communication. This
is a **monorepo**: a Python sidecar (the engine) and an Electron + React
frontend (the app), shipped together as a single desktop application
for macOS and Windows.

## Layout

| Path | What | Owns |
|------|------|------|
| `engine/` | Python 3.11+ sidecar — IMAP / SMTP, WhatsApp (neonize), MrCall phone, blob memory, hybrid search, local SQLite store. | The `zylch` CLI binary, the on-disk profile directory, all business logic. |
| `app/` | Electron + React frontend that embeds the engine via JSON-RPC over stdio. Three views: chat, tasks, emails. | The desktop UI, packaging via `electron-builder`, GitHub release pipeline. |
| `docs/` | Monorepo-wide docs: things that span engine ↔ app or describe the repo as a whole. | Cross-cutting decisions, release process, IPC contracts. |

Each subdir has its own `CLAUDE.md` and `docs/` (mirroring the three-tree
structure). Read those for details:

- [`engine/CLAUDE.md`](engine/CLAUDE.md) + [`engine/docs/`](engine/docs/) — engine doc index, install, channel matrix, critical rules.
- [`engine/docs/active-context.md`](engine/docs/active-context.md) — **freshest source** for what's working / in-flight on the engine side.
- [`app/CLAUDE.md`](app/CLAUDE.md) + [`app/docs/`](app/docs/) — Electron layout, dev workflow, packaging.
- [`docs/`](docs/) — cross-cutting docs: IPC contract, release pipeline, brand/rename rollout.

## Identity (Firebase) — added 2026-05-02

The Electron renderer now gates the entire UI behind a Firebase Auth
sign-in (same `talkmeapp-e696c` project the dashboard uses, so the
account is shared). The renderer pushes the resulting ID token to the
Python sidecar over JSON-RPC (`account.set_firebase_token`); the
sidecar holds it in memory and uses it as the `auth:` header for
outgoing StarChat calls. The token is never persisted to disk.

Profiles created post-Firebase are keyed by the immutable Firebase
UID (`~/.zylch/profiles/<firebase_uid>/`), not the email — emails can
change. The user's email is stored as `EMAIL_ADDRESS` in the
profile's `.env` for display, alongside `OWNER_ID = <firebase_uid>`
which the engine's owner-scoped storage (OAuthToken etc.) uses as the
foreign key.

Google Calendar is a *separate* OAuth — PKCE flow on
`127.0.0.1:19275`, scope `calendar.readonly`, tokens stored encrypted
in the existing `OAuthToken` table with `provider='google_calendar'`.
The Calendar OAuth is incremental: Firebase signin doesn't ask for it,
the user clicks "Connect Google Calendar" in Settings to grant it
later. Configure `GOOGLE_CALENDAR_CLIENT_ID` (Desktop-app or Web
loopback OAuth client) in profile settings before the first
connect — no client secret is used.

The legacy CLI MrCall PKCE flow on `:19274` (`zylch init`) is left
intact for users who never sign in to the desktop UI.

## LLM billing modes — BYOK vs MrCall credits (since 2026-05)

The desktop has two LLM billing modes, picked from the Settings card:

- **BYOK** (`anthropic` / `openai`) — user supplies their own API key in
  the profile `.env`. Direct SDK calls, no server hop. Default.
- **Use MrCall credits** (`mrcall`) — calls route through `mrcall-agent`'s
  `POST /api/desktop/llm/proxy` and bill the user's `CALLCREDIT` balance
  on StarChat. Same unified pool that funds phone calls and the
  configurator chat — there is no separate LLM-only category. The
  Anthropic API key lives server-side; the desktop only sends the
  Firebase JWT. Top-up happens on `https://dashboard.mrcall.ai/plan`.

Engine pieces: `engine/zylch/llm/proxy_client.py` (`MrCallProxyClient`),
`engine/zylch/rpc/account.py` (`account.balance` JSON-RPC),
`MRCALL_PROXY_URL` env var (default `https://zylch.mrcall.ai`, the production `mrcall-agent` deployment).
See [`engine/CLAUDE.md`](engine/CLAUDE.md) for full details.

App pieces: new `LLMProviderCard` in `app/src/renderer/src/views/Settings.tsx`
(BYOK ↔ MrCall-credits radio + balance display + "Top up" via
`shell.openExternal`). See [`app/CLAUDE.md`](app/CLAUDE.md).

## Naming and identifiers — the rename in flight

This monorepo was assembled by subtree-merging two predecessor repos
(`malemi/zylch` and `malemi/zylch-desktop`, now private/archived). Until
the planned rename completes, the engine still uses **`zylch`** as its
internal identifier in many places:

- Python package: `zylch.*`
- CLI binary: `zylch`
- Data directory: `~/.zylch/profiles/<email>/`
- Env var prefix: `ZYLCH_*`

Treat these as synonyms for `mrcall` until the rename PR lands. Don't
re-introduce `zylch` strings in **new** code or docs; mention `mrcall`
where natural and leave existing `zylch` references for the dedicated
sweep.

## Memory discipline

Claude Code keeps a per-user, per-machine memory at
`~/.claude/projects/<encoded-path>/memory/`. **It is not in git, not
shared with the team, not portable.** The project's source of truth is
this `CLAUDE.md`, the per-subdir `CLAUDE.md` files, and the docs under
`docs/` and `engine/docs/`.

Rules for any agent working in this repo:

- **Project knowledge → in git.** Architecture, decisions, current
  state, rules: write or edit a doc under `docs/` (cross-cutting) or
  `engine/docs/` (engine-specific). Propose the change to the user; do
  not silently auto-save it to your local CC memory under a `project`
  or `reference` type.
- **`engine/docs/active-context.md` is the freshest source** for
  engine-side state. It overrides anything in older strategy /
  business-model files when they disagree.
- **Personal notes → CC memory.** User preferences, working-style
  feedback, your own session-local recall — these are appropriate for
  `~/.claude/.../memory/` because they're per-developer.
- **Before quoting CC memory**, verify against the current state of the
  repo. Memory can be stale; the repo cannot.

## Quick reference

```bash
# Engine — see engine/CLAUDE.md for the full set
cd engine
pip install -e .                  # dev install
zylch -p user@example.com update  # sync + analyze + detect tasks
zylch -p user@example.com         # interactive REPL

# App — see app/CLAUDE.md for full dev / packaging
cd app
npm ci
npm run dev                       # hot-reload, expects engine sidecar at ZYLCH_BINARY
npm run dist:mac                  # produce .dmg
```

## License

MIT. See [`LICENSE`](LICENSE).
