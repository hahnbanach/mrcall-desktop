# AGENTS.md

**Stack**: Electron + React (app), Python 3.11+ (engine), SQLite
**Entry point**: `engine/` (Python sidecar) and `app/` (Electron + React) — each has its own CLAUDE.md
**Do not break**: The Firebase ID token is never persisted to disk; profiles are keyed by the immutable Firebase UID (`~/.zylch/profiles/<firebase_uid>/`), never by email; the company memory key (`MEMORY_KEY`) is a capability — never logged, never in git, written only by `memory.join`

<!-- orientation ends -->

<!-- doc-scope:start -->
Scope: the thin index of this monorepo — what each of the three trees owns, and
the cross-cutting facts a session needs before it routes anywhere (identity,
LLM billing modes, the naming rename in flight). Engine detail is
[`engine/CLAUDE.md`](engine/CLAUDE.md), app detail
[`app/CLAUDE.md`](app/CLAUDE.md), cross-cutting volatile state
[`docs/active-context.md`](docs/active-context.md).
<!-- doc-scope:end -->

**MrCall Desktop** — local AI assistant for business communication. This
is a **monorepo**: a Python sidecar (the engine) and an Electron + React
frontend (the app), shipped together as a single desktop application
for macOS and Windows.

## Layout

| Path | What | Owns |
|------|------|------|
| `engine/` | Python 3.11+ sidecar — IMAP / SMTP, WhatsApp (neonize), MrCall phone, company memory (one SQLite store per memory key), hybrid search, local SQLite profile store. | The `zylch` CLI binary, the on-disk profile directory, all business logic. |
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

The legacy CLI MrCall PKCE flow on `:19274` (`zylch init`) was **removed
2026-05** — MrCall connection today happens exclusively via the Firebase
sign-in in the desktop UI (`tools/mrcall/starchat_firebase.py`); `zylch init`
no longer runs any OAuth/PKCE code for MrCall (corrected 2026-07-14,
doc-critic pass).

## Shared company memory (since 2026-09)

Memory is per company, not per account. A profile carries `MEMORY_KEY`
(`secrets.token_urlsafe(16)`, 22 chars) in its `.env`, and every profile on
the same engine host holding that key reads and writes one SQLite store,
`~/.zylch/memory/<MEMORY_KEY>.db` (`MEMORY_DB_DIR` overrides the directory);
the profile's `zylch.db` keeps mail, tasks, tokens and sync cursors.
Company families (`user:<key>`, `facts:<key>`) are visible to every key
holder; rule families (`template:<owner>`, `prefs:<owner>`) only to their
owner; `owner_id` on a company row is provenance, not a wall — the one
predicate is `engine/zylch/memory/scope.py:blob_visible`. The key is a
capability: `memory.join` is its only write path (`settings.update` refuses
it), a key the host does not know is refused rather than turned into an
empty store, and duplicates left by a join are united by the sweep that
runs after each update. Design:
[`docs/briefs/2026-09-08-shared-company-memory-implementation.md`](docs/briefs/2026-09-08-shared-company-memory-implementation.md);
engine detail in [`engine/docs/features/entity-memory-system.md`](engine/docs/features/entity-memory-system.md)
("Scope"); host operations in [`docs/remote-backend.md`](docs/remote-backend.md)
("Shared company memory on the host"); app surface in [`app/CLAUDE.md`](app/CLAUDE.md).

## LLM billing and spending controls

Saved `LLM_PROVIDER` explicitly selects `anthropic`, `mrcall`, or `openrouter`.
Anthropic and OpenRouter use the corresponding personal API key. MrCall credits
use Firebase authentication and the shared StarChat `CALLCREDIT` pool; top-up
opens `https://dashboard.mrcall.ai/plan`. Switching providers preserves keys
and never falls back to another provider. Legacy profiles without a provider
use their saved Anthropic key when present, otherwise MrCall credits.

The engine reserves each request's maximum cost against the saved daily USD
budget before dispatch. Uncertain requests retain their holds across restarts
and UTC midnight. MrCall calls use the versioned bounded quote/execute/status
contract; an older server without that contract refuses paid work. OpenRouter
supports the explicitly priced GLM model with provider price caps. Economy,
balanced and custom presets expose effective role models; GLM semantic quality
is unmeasured. Automatic preparation is off by default and explicit runs have
a saved batch limit (default 25 steps).

Engine contracts: [`engine/docs/features/daily-llm-budget.md`](engine/docs/features/daily-llm-budget.md)
and [`engine/docs/features/bounded-preparation.md`](engine/docs/features/bounded-preparation.md).
`MRCALL_PROXY_URL` selects the billing server (default `https://zylch.mrcall.ai`).
App behavior: [`app/docs/bounded-preparation.md`](app/docs/bounded-preparation.md).

## Naming and identifiers — the rename in flight

This monorepo was assembled by subtree-merging two predecessor repos
(`example-owner/zylch` and `example-owner/zylch-desktop`, now private/archived). Until
the planned rename completes, the engine still uses **`zylch`** as its
internal identifier in many places:

- Python package: `zylch.*`
- CLI binary: `zylch`
- Data directory: `~/.zylch/profiles/<firebase_uid>/`
- Env var prefix: `ZYLCH_*`

Treat these as synonyms for `mrcall` until the rename PR lands. Don't
re-introduce `zylch` strings in **new** code or docs; mention `mrcall`
where natural and leave existing `zylch` references for the dedicated
sweep.

## Memory discipline

Claude Code keeps a per-user, per-machine memory at
`~/.claude/projects/<encoded-path>/memory/`. **It is not in git, not
shared with the team, not portable.** The project's source of truth is
this `AGENTS.md`, the per-subdir `CLAUDE.md` files, and the docs under
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
