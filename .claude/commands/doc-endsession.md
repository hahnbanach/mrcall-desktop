---
description: Commit session state to documentation (engine + app + cross-cutting).
---
Consolidate session knowledge using the Dream pattern: Orient → Gather → Consolidate → Prune.

## Gate Check — Is consolidation needed?

Before doing anything, verify at least one gate passes:

- **Change gate**: `git status` or `git diff` shows uncommitted or recently committed changes.
- **Context gate**: `engine/docs/active-context.md` is stale (doesn't reflect current state).
- **Plan gate**: an execution plan has steps that were completed but not checked off.

If no gate passes, output `No consolidation needed.` and stop.

## Phase 1 — Orient

Ground truth comes from git, not from conversation memory.

1. Run `git status` and `git diff` for uncommitted work.
2. Run `git log --oneline -n 10` and `git diff HEAD~3` (or appropriate range) for committed work.
3. If unsure what was *this session* vs. prior, ask rather than guess.
4. Read the current documentation baseline:
   - `./engine/docs/active-context.md`
   - `./engine/docs/ARCHITECTURE.md` (if structural change is suspected)
   - `./CLAUDE.md` (only if the engine/app boundary or naming-rename status changed)

## Phase 2 — Gather Signal

Identify what changed that is worth persisting. Priority order:

- **Structural changes**: new modules, changed boundaries, new IPC methods, new dependencies.
- **Completed execution plan steps**.
- **New decisions or constraints** discovered (especially around the JSON-RPC contract, profile layout, or sidecar lifecycle).
- **Quality changes**: tests added/broken, tech debt created/resolved.
- **Harness gaps identified** — anything where the lack of a mechanical check let a regression slip through.
- **Release-pipeline changes**: signing, notarization, electron-builder config, sidecar bundling.

## Phase 3 — Consolidate (reconsolidate, don't append)

All docs are declarative, present-tense, living documents. **Merge knowledge into existing content — do not append changelogs.**

5. **`./engine/docs/active-context.md`** — Overwrite to reflect the state *right now*:
   - What is built and working (from git inspection).
   - What was completed this session.
   - Unresolved issues, failing tests, incomplete work.
   - Immediate next steps.

6. **`./engine/docs/ARCHITECTURE.md`** — Update ONLY if structural changes occurred (new module, changed dependency direction, changed IPC surface). Remove stale descriptions of things that no longer exist.

7. **`./engine/docs/CONVENTIONS.md`** — Update ONLY if a new convention was introduced or an existing one was deliberately broken with a documented reason.

8. **Execution plans** (`./docs/execution-plans/*.md`, `./engine/docs/execution-plans/*.md`) — Check off completed steps, log decisions under `## Decisions Made`, add open questions, set `status: completed` if done.

9. **`./engine/docs/quality-grades.md`** — Update only if test coverage, tech debt, or module quality changed.

10. **`./engine/docs/harness-backlog.md`** — Append any harness gap discovered this session.

11. **`./CLAUDE.md`** / **`./app/CLAUDE.md`** / **`./engine/CLAUDE.md`** — Update only if pointers became stale or the layout changed. These are indexes; keep them ≤ ~100 lines and pointer-only.

## Phase 4 — Prune

If a doc references a feature, file, or decision that no longer exists, delete the stale reference. Stale docs are worse than no docs.

## Output

One line per doc touched:

```
Updated engine/docs/active-context.md (new IPC method, profile dir change).
Updated engine/docs/quality-grades.md (added IMAP test coverage).
Logged harness gap: no typecheck CI for app/.
```

If nothing was written: `No consolidation needed.`
