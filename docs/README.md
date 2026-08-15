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

- [`active-context.md`](active-context.md) — cross-cutting living snapshot: `State now` / `Unresolved` / `Next`, nothing else
- [`active-context-archive.md`](active-context-archive.md) — dated narrative pruned out of the living snapshot
- [`ipc-contract.md`](ipc-contract.md) — the JSON-RPC method surface between `app/src/main/` and `engine/zylch/rpc/`
- [`remote-backend.md`](remote-backend.md) — running the engine as a remote daemon (mrcalld, per-uid sockets, Caddy/TLS), operator guide + runbook
- [`harness-backlog.md`](harness-backlog.md) — cross-cutting enforcement / tooling gaps
- [`claude-agent-sdk-analysis.md`](claude-agent-sdk-analysis.md) — evaluation of the Claude Agent SDK against the engine's own agent loop
- [`execution-plans/`](execution-plans/) — workstreams that span both subsystems, one file each, `status:` in the frontmatter
- `.doc-profile` — doc-harness configuration (leaf mode, `CLAUDE.md` as the single index)

The release pipeline (tag-driven matrix, signing, notarization,
electron-builder quirks) is documented inside
[`execution-plans/release-and-rename-l2.md`](execution-plans/release-and-rename-l2.md).

Engine-side and app-side counterparts (worth knowing about from
anywhere in the repo):

- [`../engine/docs/active-context.md`](../engine/docs/active-context.md) — engine-side "what's working / in-flight"
- [`../engine/docs/ARCHITECTURE.md`](../engine/docs/ARCHITECTURE.md) — engine system map
- [`../engine/docs/CONVENTIONS.md`](../engine/docs/CONVENTIONS.md) — engine code style, logging, security patterns
- [`../app/CLAUDE.md`](../app/CLAUDE.md) — app-side index (long-form until `app/docs/` fills in)
