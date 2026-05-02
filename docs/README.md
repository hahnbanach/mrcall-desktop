# MrCall Desktop — monorepo docs

This directory holds documentation that **spans the whole monorepo** —
things that touch both `engine/` and `app/`, or describe the repository
as a whole.

The repo has three parallel doc trees, mirroring the three `CLAUDE.md`
files. Each tree owns one concern; cross-cutting state lives here.

| If the doc is about… | It belongs in… |
|----------------------|----------------|
| The Python engine (CLI, channels, memory, storage, internal architecture, features, QA) | [`../engine/docs/`](../engine/docs/) |
| The Electron app (UI, packaging, IPC client side, electron-builder quirks, sidecar spawn from main process) | [`../app/docs/`](../app/docs/) |
| **Both** subsystems together (release process, JSON-RPC contract between sidecar and renderer, brand / rename rollout, monorepo conventions) | here, in `docs/` |

## Index

The cross-cutting doc tree is the youngest. Files appear here as
content moves out of the engine's active-context (which historically
played a dual role) and as new cross-cutting concerns surface. Likely
first entries:

- `active-context.md` — cross-cutting state: IPC contract drift, release pipeline, rename rollout
- `ipc-contract.md` — the JSON-RPC method surface between `app/src/main/` and `engine/zylch/rpc/`
- `release.md` — tag-driven matrix, signing, notarization, electron-builder quirks
- `harness-backlog.md` — cross-cutting enforcement / tooling gaps

## Existing entries

- [`execution-plans/`](execution-plans/) — active workstreams that span both subsystems

Engine-side and app-side counterparts (worth knowing about from
anywhere in the repo):

- [`../engine/docs/active-context.md`](../engine/docs/active-context.md) — engine-side "what's working / in-flight"
- [`../engine/docs/ARCHITECTURE.md`](../engine/docs/ARCHITECTURE.md) — engine system map
- [`../engine/docs/CONVENTIONS.md`](../engine/docs/CONVENTIONS.md) — engine code style, logging, security patterns
- [`../app/CLAUDE.md`](../app/CLAUDE.md) — app-side index (long-form until `app/docs/` fills in)
