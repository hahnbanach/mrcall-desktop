# MrCall Desktop — app docs

Documentation specific to the **Electron + React frontend** in `app/` —
window/sidecar lifecycle, IPC client (preload + renderer), packaging
via electron-builder, view layer (chat / tasks / emails / settings /
onboarding).

## What lives here vs. elsewhere

| If the doc is about… | It belongs in… |
|----------------------|----------------|
| The Python engine (CLI, channels, memory, storage, internal architecture, features, QA) | [`../../engine/docs/`](../../engine/docs/) |
| The Electron app (UI, packaging, IPC client side, electron-builder quirks, sidecar spawn from main process) | here, in `app/docs/` |
| **Both** subsystems together (release process, JSON-RPC contract between sidecar and renderer, brand / rename rollout, monorepo conventions) | [`../../docs/`](../../docs/) |

## Index

The app-side doc tree is younger than the engine's. Files appear here as
state crystallises out of `app/CLAUDE.md` — the long-form starting
point. Likely first entries:

- `active-context.md` — what's working / in-flight on the app side
- `ARCHITECTURE.md` — main / preload / renderer boundaries, sidecar lifecycle
- `CONVENTIONS.md` — TypeScript, React, Tailwind, electron-vite patterns
- `harness-backlog.md` — app-side enforcement / tooling gaps

For now, [`../CLAUDE.md`](../CLAUDE.md) is the authoritative app-side
index.
