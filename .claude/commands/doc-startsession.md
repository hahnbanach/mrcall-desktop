---
description: Initialize Session Context
---
1. Read `./CLAUDE.md` (or `./AGENTS.md`). This is the **table of contents**, not the full knowledge base. It must be concise (<100 lines) and contain pointers to deeper sources of truth in `./docs/`.
2. Follow its pointers to read:
   - `./docs/system-rules.md` — absolute constraints, coding standards, and enforcement rules. Violations are never acceptable.
   - `./docs/architecture.md` — module boundaries, layering rules, dependency direction, data flow. Understand what imports what and why.
   - `./docs/active-context.md` — current execution state: what was last completed, what is in progress, what is next.
3. Run `ls ./docs/` and `head -n 10` on any other `*.md` files to map the rest of the knowledge base (design specs, execution plans, quality grades, tech debt tracker).
4. If `./docs/execution-plans/` exists, check for any active plans (files not marked `status: completed`) — these define multi-step work in progress.
5. Run a quick constraint smoke check:
   - If custom linters or structural tests exist (check `package.json` scripts, `Makefile`, or `./tools/`), run them. Surface any current violations before starting new work.
   - If none exist, note this as a harness gap.
6. Do not output summaries or greetings. Output only:
   `Context loaded. [N] docs indexed. [any active execution plans or constraint violations found]. Ready to work.`