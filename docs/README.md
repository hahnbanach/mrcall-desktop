# MrCall Desktop — monorepo docs

This directory holds documentation that **spans the whole monorepo** —
things that touch both `engine/` and `app/` or describe the repository
as a whole.

## What lives here vs. elsewhere

| If the doc is about… | It belongs in… |
|----------------------|----------------|
| The Python engine (CLI, channels, memory, storage, internal architecture, features, QA) | [`../engine/docs/`](../engine/docs/) — the long-standing engine doc tree |
| The Electron app (UI, packaging, IPC client side, electron-builder quirks) | [`../app/CLAUDE.md`](../app/CLAUDE.md) — and a future `../app/docs/` once we split that out |
| **Both** subsystems together (release process, JSON-RPC contract between sidecar and renderer, brand / rename rollout, monorepo conventions) | here, in `docs/` |

Engine docs that are particularly worth knowing about from anywhere in
the repo:

- [`../engine/docs/active-context.md`](../engine/docs/active-context.md) — the freshest "what's working / in-flight" record
- [`../engine/docs/ARCHITECTURE.md`](../engine/docs/ARCHITECTURE.md) — engine system map
- [`../engine/docs/CONVENTIONS.md`](../engine/docs/CONVENTIONS.md) — code style, logging, security patterns

## Contents

(To be filled in. The first entries here will likely be: the JSON-RPC
contract between `engine/` and `app/`, the unified release pipeline,
and the engine→`mrcall` rename rollout plan.)
