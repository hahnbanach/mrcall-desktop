# CLAUDE.md

Zylch — local AI-powered sales intelligence CLI. Python 3.11+ / SQLite / IMAP / WhatsApp (neonize) / BYOK or MrCall-credits LLM. Mono-user, no server.

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
| [agents/README.md](docs/agents/README.md) | Agent system (memory, tasks, emailer) |
| [qa/testing-live.md](docs/qa/testing-live.md) | Live testing: use Zylch, compare against Gmail |

After context compaction, run /doc-intrasession before resuming work!

## Sibling repos

This product spans three repos under `~/private/`:

- **`zylch-standalone/`** — this one. Python CLI + Python sidecar (the "brain").
- **`zylch-desktop/`** — Electron + React shell that embeds the sidecar via JSON-RPC over stdio. Repo: `malemi/zylch-desktop`.
- **`zylch-website/`** — static marketing site at https://zylchai.com. Repo: `malemi/zylch-website`.

When a change cuts across repos (e.g. a CLI flag rename that the desktop UI also relies on), check the matching repo before merging.

## Memory discipline

Claude Code keeps a per-user, per-machine memory at `~/.claude/projects/<encoded-path>/memory/`. **It is not in git, not shared with the team, not portable.** The project's source of truth is `./docs/` and this `CLAUDE.md`.

Rules for any agent working in this repo:

- **Project knowledge → `docs/`.** Architecture, decisions, current state, rules: write or edit a doc under `docs/`. Propose the change to the user; do not silently auto-save it to your local CC memory under a `project` or `reference` type.
- **`active-context.md` is the freshest source.** It's updated continuously; it overrides anything in older strategy/business-model files when they disagree.
- **Personal notes → CC memory.** User preferences, working-style feedback, your own session-local recall — these are appropriate for `~/.claude/.../memory/` because they're per-developer.
- **Before quoting CC memory**, verify against the current state of `docs/` or the code. Memory can be stale; the repo cannot.

## Install

Zylch is distributed as a **prebuilt binary** via `scripts/install.sh` (curl one-liner).
The installer downloads from GitHub Releases and puts the binary in `/usr/local/bin/zylch`.
Re-running the same script upgrades in place. `pip install -e .` is for **dev only**.

## Quick Reference

```bash
# Install / Upgrade
curl -sL https://raw.githubusercontent.com/malemi/zylch/main/scripts/install.sh | bash

# Dev mode (contributors only)
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

The engine supports two LLM billing modes, selected by `SYSTEM_LLM_PROVIDER`:

- **BYOK** (`anthropic`, `openai`) — user supplies their own API key. Direct SDK calls. Default.
- **MrCall credits** (`mrcall`) — calls route through `mrcall-agent`'s `POST /api/desktop/llm/proxy` and bill the user's `CALLCREDIT` balance on StarChat. Same unified pool that funds phone calls and configurator chat — there is no separate LLM-only category. The Anthropic API key lives server-side; the desktop only sends the Firebase JWT.

Implementation:

- `zylch/llm/proxy_client.py` — `MrCallProxyClient`, a drop-in for the subset of `anthropic.Anthropic().messages.create` the engine uses (sync + async + streaming context manager). Httpx-based; parses Anthropic SSE; reconstructs Message/event objects with `.content`, `.usage`, `.stop_reason`. Typed exceptions: `MrCallInsufficientCredits(available, topup_url)`, `MrCallAuthError`, `MrCallProxyError`.
- `zylch/llm/client.py` — `LLMClient.__init__` branches on `provider == "mrcall"`: requires a live Firebase session (raises if absent) and constructs `MrCallProxyClient(proxy_base_url=settings.mrcall_proxy_url, firebase_session=zylch.auth.session)`. Reuses the existing `_call_anthropic` codepath because the proxy returns Anthropic-format objects.
- `zylch/llm/providers.py` — `"mrcall"` entry with `is_metered=True`; same flag (with `False`) added to `anthropic` and `openai` for consistent caller branching.
- `zylch/rpc/account.py` — new JSON-RPC method `account.balance()` that calls `GET /api/desktop/llm/balance` on `mrcall-agent` with the cached Firebase ID token. Returns the server payload verbatim so a server-side schema change doesn't require an engine release.
- `zylch/services/settings_schema.py` — `"mrcall"` added to `LLM_PROVIDER` choices.

Config (in `zylch/config.py`):

- `MRCALL_PROXY_URL` — default `https://zylch-test.mrcall.ai`. Base URL of the proxy.
- `MRCALL_CREDITS_MODEL` — default `claude-sonnet-4-5`. The model the engine asks the proxy to run; controls what we charge for, independent of any BYOK env.

Tests: `engine/tests/llm/test_proxy_client.py` (8 cases — happy SSE, 401, 402, auth header shape, body forwarding, streaming reconstruction).

Top-up flow lives on `dashboard.mrcall.ai/plan`; the desktop client just opens the URL via `shell.openExternal` (renderer-side concern, see `app/CLAUDE.md`). The engine never logs the JWT — only `len()` / first 8 chars at most, per the secret-logging rule.

## Critical Rules

- **NO OUTPUT TRUNCATION**: Never use `[:8]`, `[:50]`, `[:100]` slicing for display
- **DEBUG LOGGING MANDATORY**: `logger.debug(f"[/cmd] func(param={param}) -> result={result}")`
- **NEVER log secrets**: Only "present"/"absent"
- **FILES < 500 LINES**: Keep modules small and focused
- **SQLITE STORAGE**: All data in SQLite. Embeddings in BLOB, search in-memory
- **NO HARDCODED SECRETS**: Pydantic Settings from profile `.env`
- **NO ROOT FILES**: Use `/zylch`, `/tests`, `/docs`, `/scripts`
- **PROFILE MATCH**: Exact match only, no substring/fuzzy
