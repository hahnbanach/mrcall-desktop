---
description: Commit session state to documentation (root + engine + app).
---
Consolidate session knowledge using the Dream pattern: Orient → Gather → Consolidate → Prune.

This monorepo has three parallel doc trees mirroring the three `CLAUDE.md`
files. **Route each fact to the tree that owns it**:

| If the change is about… | Write to… |
|--------------------------|-----------|
| Engine internals (storage, workers, channels, memory, LLM client, CLI) | `./engine/docs/` |
| Electron app internals (views, preload, main process, sidecar lifecycle, packaging) | `./app/docs/` |
| Both subsystems together (JSON-RPC contract, brand/rename rollout, release pipeline) | `./docs/` |

Engine `active-context.md` historically doubled as the monorepo's freshest
source. The migration to the three-tree split is in progress: don't
duplicate facts, route them.

## Gate Check — Is consolidation needed?

Before doing anything, verify at least one gate passes:

- **Change gate**: `git status` or `git diff` shows uncommitted or recently committed changes.
- **Context gate**: any of the three `active-context.md` files (or one that should exist but doesn't) is out of sync with what the code now does.
- **Plan gate**: an execution plan in `./docs/execution-plans/`, `./engine/docs/execution-plans/`, or `./app/docs/execution-plans/` has steps that were completed but not checked off.

If no gate passes, output `No consolidation needed.` and stop.

## Phase 1 — Orient

Ground truth comes from git, not from conversation memory.

1. Run `git status` and `git diff` for uncommitted work.
2. Run `git log --oneline -n 10` and `git diff HEAD~3` (or appropriate range) for committed work.
3. If unsure what was *this session* vs. prior, ask rather than guess.
4. Read the current documentation baseline from whichever trees the change touched:
   - `./CLAUDE.md`, `./engine/CLAUDE.md`, `./app/CLAUDE.md`
   - `./docs/active-context.md` (if exists)
   - `./engine/docs/active-context.md` (if exists)
   - `./app/docs/active-context.md` (if exists)
   - `./engine/docs/ARCHITECTURE.md` (if structural change is suspected)

## Phase 2 — Gather Signal

Identify what changed that is worth persisting. Priority order:

- **Structural changes**: new modules, changed boundaries, new IPC methods, new dependencies.
- **Completed execution plan steps**.
- **New decisions or constraints** discovered (especially around the JSON-RPC contract, profile layout, or sidecar lifecycle).
- **Quality changes**: tests added/broken, tech debt created/resolved.
- **Harness gaps identified** — anything where the lack of a mechanical check let a regression slip through.
- **Release-pipeline changes**: signing, notarization, electron-builder config, sidecar bundling.
- **Rename progress**: `zylch → mrcall` strings touched, scope of remaining sweep.

## Phase 3 — Consolidate (reconsolidate, don't append)

All docs are declarative, present-tense, living documents. **Merge knowledge into existing content — do not append changelogs.** A short rolling "recent commits" section in `active-context.md` is acceptable, but cap it at ~10 entries and prune older items into the relevant "What is built" section.

Route each fact to the tree that owns it. If a single change touches two trees (e.g. a new RPC method = engine impl + app client + IPC contract), write the engine-side facts to engine, the app-side facts to app, and the contract delta to `./docs/`.

5. **`./engine/docs/active-context.md`** — engine-side state. What is built and working, what was completed this session on the engine, unresolved engine issues, immediate engine next steps. Create if it doesn't yet hold the right scope; otherwise overwrite to reflect current reality.

6. **`./app/docs/active-context.md`** — app-side state. UI views, preload/main wiring, sidecar lifecycle from the Electron side, packaging quirks. Create the file the first time an app-side change needs to land here.

7. **`./docs/active-context.md`** — cross-cutting state. IPC contract drift, release pipeline, rename rollout, brand. Create the first time a cross-cutting change needs to land here.

8. **`./engine/docs/ARCHITECTURE.md`** / **`./app/docs/ARCHITECTURE.md`** — update ONLY if structural changes occurred (new module, changed dependency direction, changed IPC surface). Remove stale descriptions of things that no longer exist.

9. **`./engine/docs/CONVENTIONS.md`** / **`./app/docs/CONVENTIONS.md`** — update ONLY if a new convention was introduced or an existing one was deliberately broken with a documented reason.

10. **Execution plans** (`./docs/execution-plans/`, `./engine/docs/execution-plans/`, `./app/docs/execution-plans/`) — check off completed steps, append a one-line completion note (date + outcome), set `status: completed` if done. Don't fabricate a `## Decisions Made` section if the plan didn't have one — match the existing structure of each plan.

11. **`./docs/ipc-contract.md`** — if a JSON-RPC method was added, removed, or changed shape, log the delta here. Create the file if missing the first time a contract change needs to land.

12. **Quality grades** (`./engine/docs/quality-grades.md`, `./app/docs/quality-grades.md`) — update only if test coverage, tech debt, or module quality changed.

13. **Harness backlog** (`./docs/harness-backlog.md`, `./engine/docs/harness-backlog.md`, `./app/docs/harness-backlog.md`) — append any harness gap discovered this session. Pick the tree the gap belongs to.

14. **`./CLAUDE.md`** / **`./engine/CLAUDE.md`** / **`./app/CLAUDE.md`** — update only if pointers became stale or the layout changed. These are indexes; keep them ≤ ~100 lines and pointer-only.

## Phase 4 — Prune

If a doc references a feature, file, or decision that no longer exists, delete the stale reference. Stale docs are worse than no docs.

If `engine/docs/active-context.md` still carries cross-cutting facts (release, IPC contract drift, brand) that now have a home in `./docs/active-context.md` or `./docs/ipc-contract.md`, migrate them — don't duplicate.

## Output

One line per doc touched, naming the tree:

```
Updated engine/docs/active-context.md (new tasks.complete note column).
Updated app/docs/active-context.md (Tasks.tsx inline note composer).
Updated docs/ipc-contract.md (tasks.complete gained optional note param).
Logged harness gap: no contract test for tasks.complete payload (engine/docs/harness-backlog.md).
```

If nothing was written: `No consolidation needed.`
