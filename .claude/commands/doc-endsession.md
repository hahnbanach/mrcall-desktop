---
description: Commit Session State to Documentation
disable-model-invocation: true
allowed-tools: Bash(git *)
---

## Repo profile — monorepo, three doc trees (root / engine / app)
*Only this block varies per repo; everything below it is identical across all repos.*
- Smoke/build: engine `cd engine && make lint`; app `cd app && npm run typecheck`. Run only the side that moved.
- Static docs (on demand): root `CLAUDE.md` is auto-loaded, but `engine/CLAUDE.md` + `app/CLAUDE.md` are NOT — read them; `engine/docs/system-rules.md`, `engine/docs/ARCHITECTURE.md`, `engine/docs/CONVENTIONS.md`, `app/docs/ARCHITECTURE.md`, `docs/ipc-contract.md`.
- Active-context: primary `docs/active-context.md` (root — one git repo, one `doc_baseline_commit`); plus `engine/docs/active-context.md` and `app/docs/active-context.md`.
- Execution plans: `docs/execution-plans/`, `engine/docs/execution-plans/`, `app/docs/execution-plans/`.
- Routing (multi-tree — route each fact to the owning tree): engine internals (storage, workers, channels, memory, LLM client, CLI) → `engine/docs/`; Electron app (views, preload, main, sidecar lifecycle, packaging) → `app/docs/`; both / JSON-RPC contract / brand-rename / release → `docs/`. Size caps: engine active-context ≤150 lines, root ≤130, app ≤120; each `CLAUDE.md` ≤100, pointer-only; "Recent landings" ≤12 rows / ~2 weeks, older rows deleted (git keeps them).
- Repo-specific alignment checks: IPC contract is the most common silent breakage — a JSON-RPC method / payload / error change must move `engine/zylch/rpc/` (server) and `app/src/preload` + `app/src/main` (client) together and log the delta in `docs/ipc-contract.md`; layering renderer → preload → main → sidecar (never reverse; engine never imports app types); profile writes go through the `~/.zylch/profiles/<email>/` abstraction; sidecar spawn / stdio / shutdown intact.
- Notes: `zylch → mrcall` rename is mid-flight — existing `zylch.*`, `ZYLCH_*`, `~/.zylch/` are intentional until the dedicated sweep; don't rewrite them as a side effect or add new `zylch` strings.

Consolidate session knowledge — Dream pattern: Orient → Gather → Consolidate → Prune. Ground truth is git plus the session transcript, never half-remembered context.

## Gate check — is consolidation needed?
At least one must hold, else output `No consolidation needed.` and stop:
- Change gate: `git status` / `git diff` shows uncommitted or recently committed work.
- Context gate: the primary active-context (see profile) no longer matches reality.
- Plan gate: an execution plan has completed-but-unchecked steps.

## Phase 1 — Orient (ground truth, pre-injected)
Uncommitted work:
!`git status --short`
Recent commits:
!`git log --oneline -n 15`

1. Read `doc_baseline_commit` from the primary active-context frontmatter (see profile). The change set to consolidate is everything in `git diff <doc_baseline_commit>..HEAD` — precise; do not guess a `HEAD~N` range. If the field is absent, fall back to `git diff HEAD~5..HEAD` and note you are establishing the baseline now.
2. If unsure what landed this session vs. earlier, ask rather than guess.
3. Read the docs you will edit: the active-context file(s), and the static doc for any area with a real structural change (see profile).

## Phase 2 — Gather signal
Two kinds. The second is the one git CANNOT show you and is most often lost:
- From the diff (code / structure): new modules, resources, endpoints; changed boundaries; new deps; completed plan steps; tests added or broken; tech debt; harness gaps.
- From the session, NOT the diff: decisions made and why; approaches tried and rejected and why; user corrections and preferences stated this session; constraints and gotchas discovered. None of this appears in `git diff` — capture it here or it is gone.

## Phase 3 — Consolidate (reconsolidate, don't append)
Merge into existing content — no changelogs (git log is the changelog). Living docs are declarative and present-tense.
Verify-before-done gate: record a feature as built / working ONLY if it was verified end-to-end this session, the way the user runs it (CLI / API / browser / REPL) — not because code was written or unit tests passed. Coded-but-unverified ⇒ in progress / needs verification, never working.
- Primary active-context (see profile): overwrite to the state right now — built & verified, completed this session, unresolved / failing / incomplete, immediate next steps. Route each fact per the profile's routing (single tree ⇒ all here; multi-tree ⇒ to the owning tree). Respect any size caps / pruning rules in the profile.
- Static docs (architecture / conventions — see profile): update ONLY on real structural change; delete descriptions of things that no longer exist.
- Execution plans: check off completed steps, record decisions, set `status: completed` when done; match each plan's existing shape.
- Quality / harness docs (see profile, where the repo keeps them): update quality grades if coverage / debt / quality moved; log enforcement gaps to harness-backlog.

## Phase 4 — Prune & advance the baseline
- Delete stale references — a doc naming a file, feature, or decision that no longer exists is worse than no doc. Rename or merge; don't accumulate.
- Keep the index `CLAUDE.md` thin and its pointers valid.
- Advance the baseline: set `doc_baseline_commit` to the output of `git rev-parse HEAD` and update `doc_baseline_date` in the primary active-context frontmatter. This is what the next session diffs from.

## Output
`Session state committed. Baseline advanced to <sha>. [docs touched]. [N plan steps completed. N harness gaps logged.]`
