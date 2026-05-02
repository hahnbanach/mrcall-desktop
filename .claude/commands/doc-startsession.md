---
description: Initialize session context for mrcall-desktop (root + engine + app).
---
Load project knowledge in two phases: stable (cacheable) first, volatile last.
This monorepo has three parallel doc trees — root, `engine/`, `app/` — each
mirroring its `CLAUDE.md`. Read all three.

## Phase 1 — Static Layer (cacheable across sessions)

Read in parallel — these change rarely and form the durable mental model:

1. `./CLAUDE.md` — monorepo index. Pointers to engine + app + cross-cutting docs. Should stay short (≤ ~100 lines).
2. `./engine/CLAUDE.md` — engine-side index.
3. `./app/CLAUDE.md` — app-side index.
4. `./engine/docs/system-rules.md` — absolute constraints for the Python sidecar.
5. `./engine/docs/ARCHITECTURE.md` — engine module map, dependency direction, data flow.
6. `./engine/docs/CONVENTIONS.md` — engine code style and patterns.
7. `./app/docs/ARCHITECTURE.md` and `./app/docs/CONVENTIONS.md` — read if present (the app doc tree is younger than the engine's).
8. `./docs/ipc-contract.md` — read if present (the cross-cutting JSON-RPC method surface).

Then run `ls ./docs/ ./engine/docs/ ./app/docs/` and skim headers (`head -n 10`) of any other `*.md` to map the rest of the knowledge base.

## Phase 2 — Dynamic Layer (session-volatile)

Read whichever exist; missing files are not an error — the relevant tree
hasn't grown that artefact yet.

9. `./docs/active-context.md` — cross-cutting state (IPC contract drift, release pipeline, rename rollout).
10. `./engine/docs/active-context.md` — **engine-side freshest source**. What is built, what is in progress, what is next. Overrides older strategy/plan files when they disagree.
11. `./app/docs/active-context.md` — app-side freshest source.
12. `./engine/docs/quality-grades.md` and `./app/docs/quality-grades.md` — current quality assessment per tree.
13. `./docs/harness-backlog.md`, `./engine/docs/harness-backlog.md`, `./app/docs/harness-backlog.md` — known enforcement / tooling gaps.
14. `./docs/execution-plans/`, `./engine/docs/execution-plans/`, `./app/docs/execution-plans/` — check for active plans (`status:` not `completed`).

## Phase 3 — Constraint Smoke Check

15. Mechanical enforcement, in parallel:
    - `cd engine && make lint` if `engine/Makefile` and `engine/venv/` exist (skip if env not bootstrapped — note as a gap, do not invent a venv).
    - `cd app && npm run typecheck` if `app/node_modules/` exists.
    - Surface any violations before starting new work.

## Phase 4 — Naming-rename awareness

The `zylch → mrcall` rename is mid-flight. Existing `zylch.*` package, `zylch` CLI, `~/.zylch/` data dir, `ZYLCH_*` env vars are intentional until the dedicated sweep lands. Do not rewrite them as a side-effect; do not introduce new `zylch` strings in new code.

## Output

Do not output summaries or greetings. Output only one line:

```
Context loaded. [N] docs indexed across [M] trees. [active plans / constraint violations / rename-sweep status if relevant]. Ready to work.
```
