# CLAUDE.md

Zylch — the MrCall Desktop engine: local AI assistant for business communication (email / WhatsApp / SMS / MrCall phone). Python 3.11+ / SQLite / IMAP / WhatsApp (neonize) / BYOK or MrCall-credits LLM. One profile per user, one memory store per company (`MEMORY_KEY`); runs as the app's stdio sidecar or as a per-profile VPS daemon (`zylch serve`).

## Documentation

All knowledge lives in `./docs/`. This file is the index.

| Doc | What |
|-----|------|
| [system-rules.md](docs/system-rules.md) | Tech stack, coding standards, dependency rules, imperatives |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System map, data flow, module boundaries |
| [CONVENTIONS.md](docs/CONVENTIONS.md) | Code style, patterns, logging, security |
| [active-context.md](docs/active-context.md) | Current state, in-progress work, known issues |
| [quality-grades.md](docs/quality-grades.md) | Per-module quality assessment |
| [guides/cli-commands.md](docs/guides/cli-commands.md) | CLI and slash command reference |
| [guides/quick-start.md](docs/guides/quick-start.md) | Install, setup, first use |
| [features/daily-llm-budget.md](docs/features/daily-llm-budget.md) | Per-request spending admission, supported billing and recovery |
| [features/project-memory.md](docs/features/project-memory.md) | Shared authored project documents, revisions and RPC contract |
| [agents/README.md](docs/agents/README.md) | Agent system (memory, tasks, emailer) |
| [qa/testing-live.md](docs/qa/testing-live.md) | Live testing: use Zylch, compare against Gmail |

## Sibling tree

The engine lives inside the `mrcall-desktop` monorepo next to `app/` (the
Electron + React shell that embeds this sidecar via JSON-RPC over stdio) and
the cross-cutting `../docs/`. When a change cuts across engine ↔ app (e.g. an
RPC rename the UI relies on), check the sibling tree before merging — see
[`../AGENTS.md`](../AGENTS.md). (The pre-merge `zylch`/`zylch-desktop` repos
were subtree-merged here and archived.)

## Memory discipline

Claude Code keeps a per-user, per-machine memory at `~/.claude/projects/<encoded-path>/memory/`. **It is not in git, not shared with the team, not portable.** The project's source of truth is `./docs/` and this `CLAUDE.md`.

Rules for any agent working in this repo:

- **Project knowledge → `docs/`.** Architecture, decisions, current state, rules: write or edit a doc under `docs/`. Propose the change to the user; do not silently auto-save it to your local CC memory under a `project` or `reference` type.
- **`active-context.md` is the freshest source.** It's updated continuously; it overrides anything in older strategy/business-model files when they disagree.
- **Personal notes → CC memory.** User preferences, working-style feedback, your own session-local recall — these are appropriate for `~/.claude/.../memory/` because they're per-developer.
- **Before quoting CC memory**, verify against the current state of `docs/` or the code. Memory can be stale; the repo cannot.

## Install

The engine ships as a PyInstaller sidecar bundled inside the **MrCall Desktop**
app, built in CI from `engine/` on each `v*` tag (see
`.github/workflows/release.yml`). There is no standalone installer.
`pip install -e .` is for **dev only**.

## Quick Reference

```bash
# Dev mode (contributors only) — the engine ships inside MrCall Desktop
pip install -e .

# Setup
zylch init                          # Profile wizard (LLM → Email → WhatsApp → Telegram → MrCall)

# Usage
zylch -p user@example.com update    # Sync + analyze + detect tasks (cron-friendly)
zylch -p user@example.com sync      # Fetch only (email + WhatsApp, no AI)
zylch -p user@example.com tasks     # Show action items
zylch -p user@example.com status    # Show sync stats
zylch -p user@example.com           # Interactive chat (REPL)
zylch profiles                      # List profiles
zylch telegram                      # Start Telegram bot + proactive digest

# Lint
black --check zylch/
ruff check zylch/
```

## Channels

| Channel | Protocol | Status |
|---------|----------|--------|
| Email | IMAP/SMTP | Working |
| WhatsApp | neonize (whatsmeow) | Working — QR code login, sync on demand |
| MrCall | StarChat HTTP + OAuth2 | Channel adapter |
| Telegram | python-telegram-bot | Bot interface |
| Calendar | CalDAV | Planned |

## MrCall credits mode (since 2026-05)

Saved `LLM_PROVIDER` selects Anthropic BYOK, OpenRouter BYOK or MrCall credits.
An unset selector preserves legacy saved-key routing. All paid calls go through
`zylch/llm/client.py` and the durable daily reservation ledger. Default models
are inexpensive; saved explicit models remain until changed deliberately.

- `llm/model_policy.py`: saved provider, economy/balanced/custom role defaults.
- `llm/bounded_proxy.py`: quoted maximum debit and actual receipt protocol;
  old unbounded proxy servers refuse. Firebase JWT remains in memory.
- `llm/openrouter_client.py`: GLM Messages adapter with provider price caps.
- `rpc/usage_queries.py`: spending, effective models and paged receipt recovery.
- `MRCALL_PROXY_URL`: default `https://zylch.mrcall.ai`.
- `MRCALL_CREDITS_MODEL`: explicit custom model; unset defaults to Haiku.

[Spending protection](docs/features/daily-llm-budget.md) specifies scope,
pricing, uncertainty and recovery. [Bounded preparation](docs/features/bounded-preparation.md)
specifies source-stage limits, pause and retry checkpoints. Automatic processing
is off by default; enabling it permits bounded paid runs. Top-up remains on
`https://dashboard.mrcall.ai/plan`, without API-key entry.

## Critical Rules

- **NO OUTPUT TRUNCATION**: Never use `[:8]`, `[:50]`, `[:100]` slicing for display
- **DEBUG LOGGING MANDATORY**: `logger.debug(f"[/cmd] func(param={param}) -> result={result}")`
- **NEVER log secrets**: Only "present"/"absent"
- **FILES < 500 LINES**: Keep modules small and focused
- **SQLITE STORAGE**: All data in SQLite — the profile `zylch.db` plus one memory store per company key (`~/.zylch/memory/<MEMORY_KEY>.db`); entity-blob rows use the `memory/scope.py` predicates, never `owner_id` alone; authored project documents use the bound company store and space identity. Embeddings in BLOB, search in-memory
- **NO HARDCODED SECRETS**: Pydantic Settings from profile `.env`
- **NO ROOT FILES**: Use `/zylch`, `/tests`, `/docs`, `/scripts`
- **PROFILE MATCH**: Exact match only, no substring/fuzzy
