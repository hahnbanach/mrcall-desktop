---
description: Initialize Session Context
---
Load project knowledge in two phases: stable (cacheable) first, volatile last.

## Phase 1 — Static Layer (cacheable across sessions)
These docs change rarely. Read them to build the durable mental model.
1. Read `./CLAUDE.md`. This is the **index** — max ~100 lines, pointers only. If it doesn't exist or exceeds 100 lines, flag it.
2. Read in parallel:
   - `./docs/system-rules.md` — absolute constraints. Violations are never acceptable.
   - `./docs/ARCHITECTURE.md` — module boundaries, dependency direction, data flow.
   - `./docs/CONVENTIONS.md` — coding standards, patterns, style.
3. Run `ls ./docs/` and skim headers (`head -n 10`) of any other `*.md` to map the knowledge base.

## Phase 2 — Dynamic Layer (session-volatile)
These docs reflect the current execution state and change every session.
4. Read `./docs/active-context.md` — what was last completed, what is in progress, what is next.
5. If `./docs/execution-plans/` exists, check for active plans (not marked `status: completed`).

## Phase 3 — Constraint Smoke Check
6. Run mechanical enforcement:
   - Check `Makefile`, `package.json` scripts, or `./tools/` for linters/structural tests.
   - If they exist, run them. Surface violations before starting new work.
   - If none exist, note as a harness gap.

## Output
Do not output summaries or greetings. Output only:
`Context loaded. [N] docs indexed. [any active execution plans or constraint violations found]. Ready to work.`