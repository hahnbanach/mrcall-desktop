---
name: agents/
description: Specialized subagents for mrcall-desktop. Each is scoped to one boundary in the monorepo.
---

# Agents

Four specialists, scoped to the boundaries that matter most in this monorepo.

| Agent | Where | What it owns | When to delegate |
|-------|-------|--------------|------------------|
| `python-engine-specialist` | `engine/` | The `zylch` Python sidecar (CLI, RPC server, IMAP, neonize, BYOK LLM, SQLite/SQLAlchemy, profile layout). | Anything under `engine/zylch/**` or `engine/tests/**`. Schema migrations. New RPC method **server side**. |
| `electron-app-specialist` | `app/` | The Electron + React frontend (main / preload / renderer, electron-vite, Tailwind, packaging). | Anything under `app/src/**`. UI changes. Sidecar lifecycle. New RPC method **client side**. |
| `ipc-contract-reviewer` | `quality/` | The JSON-RPC stdio contract — the cross-cutting boundary between engine and app. **Review-only.** | Whenever a method name, payload shape, or error envelope changes. When in doubt whether a change crosses the boundary. |
| `release-engineer` | `release/` | `electron-builder`, code signing, macOS notarization, GitHub Releases, sidecar bundling. | Tagging a release. Debugging a signed/notarized build. Changing how the sidecar is bundled. CI workflow changes. |

## How they fit together

A typical change touching the IPC boundary uses three of them in sequence:

1. `python-engine-specialist` and `electron-app-specialist` work in parallel to land matching method changes on each side.
2. `ipc-contract-reviewer` reads both sides post-hoc and confirms they line up — flagging any drift before it ships.
3. `release-engineer` is only pulled in when the change ships in a release (e.g. a contract bump that needs a coordinated client/server upgrade for existing users).

## What's deliberately missing

- **No `prime-orchestrator`.** The meta-repo at `~/hb/.claude/` has one because it coordinates several sibling repos via git worktrees. This monorepo is one product with two surfaces; the user is the orchestrator.
- **No `principal-engineer` / `system-design-architect` / etc.** Cross-cutting design questions go to the user directly. We don't keep generalists in `.claude/agents/` because they duplicate context that's already in `CLAUDE.md` and `engine/docs/`.
- **No agent for `docs/`.** The doc workflow lives in `.claude/commands/doc-*.md`, not in an agent.

If a new boundary becomes load-bearing (e.g. a separate mobile client, a server-side service that this app talks to over HTTP), add a specialist scoped to that boundary. Don't add one for every module.
