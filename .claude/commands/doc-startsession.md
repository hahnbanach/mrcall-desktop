---
description: Initialize session context for mrcall-desktop (engine + app).
---
Load project knowledge in two phases: stable (cacheable) first, volatile last.
This monorepo splits docs across the root, `app/`, and `engine/`. Read accordingly.

## Phase 1 — Static Layer (cacheable across sessions)

Read in parallel — these change rarely and form the durable mental model:

1. `./CLAUDE.md` — monorepo index. Pointers to engine + app + cross-cutting docs. Should stay short (≤ ~100 lines).
2. `./engine/CLAUDE.md` — engine-side index.
3. `./app/CLAUDE.md` — app-side index.
4. `./engine/docs/system-rules.md` — absolute constraints for the Python sidecar.
5. `./engine/docs/ARCHITECTURE.md` — engine module map, dependency direction, data flow.
6. `./engine/docs/CONVENTIONS.md` — code style and patterns.

Then run `ls ./docs/ ./engine/docs/` and skim headers (`head -n 10`) of any other `*.md` to map the rest of the knowledge base.

## Phase 2 — Dynamic Layer (session-volatile)

7. `./engine/docs/active-context.md` — **freshest source**. What is built, what is in progress, what is next. Overrides older strategy/plan files when they disagree.
8. `./engine/docs/quality-grades.md` — current quality assessment.
9. `./engine/docs/harness-backlog.md` — known enforcement / tooling gaps.
10. `./docs/execution-plans/` and `./engine/docs/execution-plans/` — check for active plans (`status:` not `completed`).

## Phase 3 — Constraint Smoke Check

11. Mechanical enforcement, in parallel:
    - `cd engine && make lint` if `engine/Makefile` and `engine/venv/` exist (skip if env not bootstrapped — note as a gap, do not invent a venv).
    - `cd app && npm run typecheck` if `app/node_modules/` exists.
    - Surface any violations before starting new work.

## Phase 4 — Naming-rename awareness

The `zylch → mrcall` rename is mid-flight. Existing `zylch.*` package, `zylch` CLI, `~/.zylch/` data dir, `ZYLCH_*` env vars are intentional until the dedicated sweep lands. Do not rewrite them as a side-effect; do not introduce new `zylch` strings in new code.

## Output

Do not output summaries or greetings. Output only one line:

```
Context loaded. [N] docs indexed. [active plans / constraint violations / rename-sweep status if relevant]. Ready to work.
```
