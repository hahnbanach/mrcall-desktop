---
description: |
  Cross-cutting state of mrcall-desktop as of 2026-05-02. Things that span
  the engine ↔ app boundary or the repo as a whole — JSON-RPC contract
  drift, release pipeline, brand/rename rollout, monorepo conventions.
  Engine-only state lives in ../engine/docs/active-context.md; app-only
  state in ../app/docs/active-context.md.
---

# Active Context — Cross-cutting

This file is young. Cross-cutting facts historically lived inside
`engine/docs/active-context.md` (the engine doc tree played a dual role).
Facts migrate here as they get touched.

## What Is Built and Working

### JSON-RPC contract (engine ↔ app)
- Server: `engine/zylch/rpc/methods.py` (dispatch table) + per-domain modules (`email_actions.py`, `task_queries.py`).
- Client: `app/src/preload/index.ts` (`window.zylch.*` surface) + main-process bridge (`ipcMain.handle('rpc:call', …)`).
- Transport: stdio JSON-RPC. Sidecar spawned by main process.
- Notification fan-out: streaming methods (`tasks.solve.event`, `update.run` progress) emit `notify` events that the main process forwards to the renderer via `webContents.send`.
- Method surface tracked in [`ipc-contract.md`](ipc-contract.md).

### Release pipeline
- Tag-driven matrix: `v*` → macOS arm64 + Windows x64; `v*-intel` → also macOS Intel x64 on a paid larger runner.
- Sidecar built in-flight via PyInstaller in `engine/`, copied to `app/bin/` before electron-builder runs. No external sidecar repo to fetch from.
- macOS code-signed + notarized via the afterSign hook (`3a3eb522`); APPLE_TEAM_ID passed explicitly to notarytool (`5b8ad979`); creds validated before build (`2477b23a`).
- Windows installers not yet code-signed.
- Plan: [`execution-plans/release-and-rename-l2.md`](execution-plans/release-and-rename-l2.md) (status: in-progress).

### Brand / rename rollout (Level 2)
- User-visible everywhere: "MrCall Desktop". `appId = ai.mrcall.desktop`.
- Engine-internal (intentional, deferred to Level 3 sweep): `zylch.*` Python package, `zylch` CLI, `~/.zylch/` data dir, `ZYLCH_*` env vars. Treat as synonyms; do not introduce new `zylch` strings.

### Documentation structure (three-tree model)
- Three `docs/` trees parallel to three `CLAUDE.md` files:
  - `./docs/` — cross-cutting (this file lives here)
  - `./engine/docs/` — Python sidecar
  - `./app/docs/` — Electron + React frontend
- Single set of `/doc-startsession`, `/doc-intrasession`, `/doc-endsession` slash commands at `.claude/commands/` — they read from and write to all three trees, routing each fact to the tree that owns it.

## What Was Completed This Session

**`tasks.complete` IPC contract change (2026-05-02, uncommitted).** Optional `note: string | null` parameter added; engine + preload + renderer moved together in one change. See [`ipc-contract.md`](ipc-contract.md) for the surface delta.

**Three-tree documentation structure (2026-05-02, uncommitted).**
- Created `app/docs/` (with skeleton `README.md`) so the three doc trees mirror the three CLAUDE.md files.
- Updated `docs/README.md` to drop the "future ../app/docs/" hedge and document the three-tree routing rules.
- Rewrote the three `/doc-*` commands at `.claude/commands/` to read all three trees in `/doc-startsession`, refresh-with-routing in `/doc-intrasession`, and route writes to the right tree in `/doc-endsession`. The `## Decisions Made` section that didn't match plan reality is dropped; a rolling "recent commits" window in `active-context.md` is now explicitly allowed (cap ~10).
- Updated `app/CLAUDE.md` and root `CLAUDE.md` to point at the new structure.
- Decision: keep engine-internal docs (system-rules.md, CONVENTIONS.md, agents/, guides/, qa/, strategy/, features/) inside `engine/docs/` because they're Python-specific. Same model applies to `app/docs/` once app-side conventions / architecture are crystallised. Cross-cutting concerns (IPC contract, release, brand) live here.

## What Is In Progress

- Migration of cross-cutting facts out of `engine/docs/active-context.md` is on-demand: when a section gets touched and is clearly cross-cutting, route it here rather than re-editing engine. No big-bang move planned.
- Release pipeline: see `execution-plans/release-and-rename-l2.md`. Tag-driven matrix done; signing on macOS done; Windows signing pending; Level 3 rename sweep pending.

## Immediate Next Steps

1. First production use of the three-tree commands at the next `/doc-endsession` (this session is the dogfood).
2. Mac validation of the close-note flow (engine + app side) before committing the contract change.
3. Decide whether to add a `tasks.complete.changed` notification so multi-window setups stay in sync (gap noted in `app/docs/active-context.md`).

## Known Issues

- No automated check that engine RPC payload shapes match preload's TypeScript signatures. A field renamed on one side and missed on the other surfaces only at runtime. Logged in [`harness-backlog.md`](harness-backlog.md).
- `engine/docs/active-context.md` still carries some content that is arguably cross-cutting (release / brand mentions). Migrate on-demand.
