---
description: |
  App-side state of mrcall-desktop as of 2026-05-02. Electron + React shell
  embeds the Python sidecar via JSON-RPC over stdio. This file captures
  what is in flight on the UI/preload/main side — engine internals live
  in ../../engine/docs/active-context.md, cross-cutting state in
  ../../docs/active-context.md.
---

# Active Context — App

This file is young: app-side state historically lived inside
`engine/docs/active-context.md` (which doubled as the monorepo's
freshest source). Facts migrate here as they get touched.

## What Is Built and Working

### Views
- **Chat** — assistant conversation, attachments, prompt-cached system prompt.
- **Tasks** — open/closed toggle, search, pin, skip, close (with optional note), reopen, reanalyze, open-in-workspace. Thread-filter mode when entered from Inbox "Open".
- **Emails** — Inbox + Sent tabs, thread reading pane with HTML body in sandboxed iframe, archive (IMAP MOVE) + delete (local soft-delete) buttons, "Open" jumps to Tasks filtered by thread.
- **Settings** — schema-driven editor over the engine's profile `.env`. `USER_SECRET_INSTRUCTIONS` unmasked. `DOWNLOADS_DIR` shown with directory picker hint.
- **Onboarding wizard** — first-launch flow.

### IPC client (preload)
- All `window.zylch.*` calls go through `ipcRenderer.invoke('rpc:call', method, params, timeout)`. Single chokepoint at `app/src/preload/index.ts`.
- Notification fan-out for streaming RPCs (`tasks.solve.event`, `update.run` progress).
- Optional timeout per method — pin/reanalyze/listByThread have explicit longer timeouts (15–120s).

### Sidecar lifecycle (main)
- Sidecar binary path resolves from `ZYLCH_BINARY` env or default `~/private/zylch-standalone/venv/bin/zylch` (dev). Packaged builds use the bundled `app/bin/zylch`.
- `cwd` defaults to `homedir()` (`f1969bb5`) so signed/notarized builds don't reach into a dev path.
- Profile-aware: each Electron window owns one profile (one email). Profile dir is locked via fcntl by the sidecar.

### Packaging
- electron-builder produces `MrCall Desktop-<ver>-arm64.dmg` (macOS Apple Silicon), `MrCall Desktop-<ver>-x64.dmg` (macOS Intel, opt-in via `v*-intel` tag), `MrCall Desktop-Setup-<ver>-x64.exe` (Windows NSIS).
- macOS code-signed + notarized via afterSign hook (`3a3eb522`). Windows installers not yet signed.
- Sidecar built by `.github/workflows/release.yml` via PyInstaller in the same run, downloaded into `app/bin/` before electron-builder runs.

## What Was Completed This Session

**Tasks.tsx — close with optional note (2026-05-02, uncommitted).**

- `ZylchTask.close_note?: string | null` added to `app/src/renderer/src/types.ts`.
- `tasks.complete(task_id, note?)` signature updated in `types.ts` (ZylchAPI) + `app/src/preload/index.ts` (param passed as `note: note ?? null`).
- `Tasks.tsx`: clicking **Close** on an open task swaps the action row for an inline composer (textarea + "Save & close" / "Cancel"). Empty textarea = close without a note. Esc cancels, Cmd/Ctrl+Enter commits. The submit button label flips to "Close (no note)" when the textarea is empty so the no-note path is obvious. In the **Closed** view, each task with a `close_note` shows it in a subdued box ("Closing note") above the action row.
- Workspace.tsx's existing `tasks.complete(taskId)` call is unaffected — the new `note` param is optional.

## What Is In Progress

- Mac validation of the close-note UI flow (composer keyboard shortcuts, closed-view rendering, reopen clears note).
- Mac validation of prior pending UI flows: IMAP archive (Gmail/Outlook/iCloud/Fastmail folder discovery), Open → Tasks filter (0-task thread, N-task thread, Clear filter, sidebar back-nav).

## Immediate Next Steps

1. Mac validation listed above, then commit the close-note feature alongside the engine-side migration + RPC changes.
2. Optional polish: a "+ note" affordance hint on the Close button itself for the Open view (currently only the title attribute communicates that notes are possible).

## Known Issues

- Renderer's `tasks.complete` notification path: there is no `tasks.complete.changed` notification, so other windows on the same profile won't update their task list until the user refreshes. (Same gap as `tasks.skip`, `tasks.reopen`.)
- No unit test coverage on the renderer side. The IPC contract is the only enforcement; payload shape mismatches surface only at runtime.
