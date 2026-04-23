---
description: Commit Session State to Documentation
---
Consolidate session knowledge using the Dream pattern: Orient → Gather → Consolidate → Prune.

## Gate Check — Is consolidation needed?
Before doing anything, verify at least one gate passes:
- **Change gate**: `git status` or `git diff` shows uncommitted or recently committed changes.
- **Context gate**: active-context.md is stale (doesn't reflect current state).
- **Plan gate**: an execution plan has steps that were completed but not checked off.
If no gate passes, output `No consolidation needed.` and stop.

## Phase 1 — Orient
Ground truth comes from git, not from conversation memory.
1. Run `git status` and `git diff` for uncommitted work.
2. Run `git log --oneline -n 10` and `git diff HEAD~3` (or appropriate range) for committed work.
3. If unsure what was this session vs. prior, ask rather than guess.
4. Read current documentation baseline: `./docs/active-context.md`, `./docs/ARCHITECTURE.md`.

## Phase 2 — Gather Signal
Identify what changed that is worth persisting. Priority order:
- Structural changes (new modules, changed boundaries, new dependencies)
- Completed execution plan steps
- New decisions or constraints discovered
- Quality changes (tests added/broken, tech debt created/resolved)
- Harness gaps identified

## Phase 3 — Consolidate (reconsolidate, don't append)
Write or update docs. **Merge knowledge into existing content — do not append changelogs.**
All docs are declarative, present-tense, living documents.

5. **`./docs/active-context.md`** — Overwrite to reflect the state *right now*:
   - What is built and working (from git inspection)
   - What was completed this session
   - Unresolved issues, failing tests, incomplete work
   - Immediate next steps
6. **`./docs/ARCHITECTURE.md`** — Update ONLY if structural changes occurred. Remove stale descriptions of things that no longer exist. No changelogs.
7. **Execution plans** (`./docs/execution-plans/*.md`) — Check off completed steps, log decisions under `## Decisions Made`, add open questions, set `status: completed` if done.
8. **`./docs/quality-grades.md`** — Update only if test coverage, tech debt, or module quality changed.

## Phase 4 — Prune and Index
9. **Harness backlog** — If enforcement gaps were found, append to `./docs/harness-backlog.md`:
   ```
   - [ ] [Description of missing enforcement or tooling]
     Discovered: [date]
     Impact: [what errors this would prevent]
   ```
10. **`./CLAUDE.md` index** — Update only if new docs were created or pointers are stale. Keep under ~100 lines. Remove pointers to deleted docs. Resolve contradictions.

## Output
`Session state committed. Active context updated. [N execution plan steps completed. N harness gaps logged.]`