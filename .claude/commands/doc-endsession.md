---
description: Commit Session State to Documentation
---
1. **Ground truth from git, not memory.** Overcome context truncation by inspecting actual changes:
   - Run `git status` and `git diff` for uncommitted work.
   - Run `git log --oneline -n 10` and `git diff HEAD~3` (or appropriate range) for committed work this session.
   - If unsure what was this session vs. prior, ask rather than guess.
2. **Read current documentation baseline.** Read `./docs/active-context.md`, `./docs/architecture.md`, and `./docs/quality-grades.md`.
3. **Update `./docs/active-context.md`.** Overwrite to reflect the state *right now*:
   - What is built and working (based on the git inspection, not memory)
   - What was completed this session
   - Unresolved issues, failing tests, incomplete work
   - Immediate next steps for the next session
   - Declarative, present-tense only.
4. **Update `./docs/architecture.md`** ONLY if structural changes occurred: new modules, new dependencies, changed boundaries, new infrastructure components. Keep it declarative — no changelogs.
5. **Update execution plans.** If any `./docs/execution-plans/*.md` files relate to this session's work:
   - Check off completed steps
   - Log decisions made under `## Decisions Made`
   - Add new open questions if they arose
   - If a plan is fully complete, set `status: completed`
6. **Update `./docs/quality-grades.md`** if the session changed test coverage, fixed or introduced tech debt, or improved/degraded any module's quality.
7. **Log harness improvements.** If during this session you identified enforcement gaps, missing linters, or documentation that should exist but doesn't, append them to `./docs/harness-backlog.md` (create if it doesn't exist). Format:
   ```
   - [ ] [Description of missing enforcement or tooling]
     Discovered: [date or session context]
     Impact: [what kind of errors this would prevent]
   ```
8. **Update `./CLAUDE.md`** (or `./AGENTS.md`) only if new docs were created or existing pointers are now stale.
9. Output only:
   `Session state committed. Active context updated. [N execution plan steps completed. N harness gaps logged.]`