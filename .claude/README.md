---
name: .claude/ for mrcall-desktop
description: Project-local Claude Code scaffolding — hooks, commands, agents, config — adapted to this monorepo (Python engine + Electron app).
---

# `.claude/` — project scaffolding

Mirrors the structure used in `~/hb/.claude/` (meta-repo) and
`~/private/zylch-standalone/.claude/`, but scoped to this monorepo.

## Layout

```
.claude/
├── settings.json         hooks: TDD reminders, push/deploy gates
├── commands/             slash-commands for doc workflow + release
├── agents/               specialized subagents for engine, app, quality, release
├── scripts/hooks/        bash helpers invoked by settings.json hooks
└── config/messages.toml  customizable text shown by hooks
```

## Scope

This is **not** the per-developer CC memory at `~/.claude/.../memory/`.
It is git-tracked project scaffolding. Anything here is shared with
anyone cloning the repo.

Per the memory discipline rules in `CLAUDE.md` and `engine/CLAUDE.md`:

- **Project knowledge** lives in `docs/`, `engine/docs/`, and the
  `CLAUDE.md` files — not here.
- **`.claude/`** holds *automation* (hooks, agents, slash-commands) that
  helps Claude work effectively in this repo.
- **Personal notes / preferences** belong in `~/.claude/.../memory/`.

## Commands

| Command | Purpose |
|---------|---------|
| `/doc-startsession` | Load static + dynamic docs at session start. |
| `/doc-intrasession` | Lightweight mid-session alignment check. |
| `/doc-endsession` | Consolidate session state into `engine/docs/active-context.md` and friends. |
| `/release-checklist` | Pre-release sanity check for the Electron build (signing, notarization, IPC contract, bundled engine). |

## Agents

| Agent | Where | What it owns |
|-------|-------|--------------|
| `python-engine-specialist` | `agents/engine/` | The `zylch` Python sidecar, SQLAlchemy/SQLite, IMAP, neonize, BYOK LLM. |
| `electron-app-specialist` | `agents/app/` | Electron main/preload/renderer, electron-vite, packaging. |
| `ipc-contract-reviewer` | `agents/quality/` | The JSON-RPC stdio contract — the one cross-cutting boundary that breaks silently. |
| `release-engineer` | `agents/release/` | electron-builder, code signing, notarization, GitHub Releases, sidecar bundling. |

## Hooks

Defined in `settings.json`, all wrapped with `|| true` so a missing or
broken script never blocks tool use:

- `PreToolUse:Write` — TDD reminder for `engine/zylch/**/*.py` without a sibling test.
- `PreToolUse:Bash` — `git push` quality reminder.
- `PostToolUse:Write` — file-written notification.
- `UserPromptSubmit` — deploy/release gate when the prompt mentions release/notarize/publish.

Hooks are notification-only; they never block. Customize messages in
`config/messages.toml`.

## Naming note (zylch → mrcall, in flight)

This repo is mid-rename. Don't introduce new `zylch` strings in scripts
or agent prompts here. Use `mrcall` for new copy and leave existing
`zylch` references for the dedicated rename sweep. See the parent
`CLAUDE.md` for the canonical guidance.
