---
description: Initialize Session Context
allowed-tools: Bash(git *) Bash(ls *) Bash(make *) Bash(npm *) Bash(sbt *) Bash(pytest *)
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

Load project knowledge: durable layer on demand, volatile state up front. Pull the smallest high-signal set into context — not everything.

## Already in context — do NOT re-read
Project + user `CLAUDE.md` are auto-loaded at session start; re-reading them wastes context. Verify the project `CLAUDE.md` is still a thin index (pointers, not prose) — flag it if it has grown into a full document. Monorepos: nested `CLAUDE.md` files not on the root path (see profile) are NOT auto-loaded — read those.

## Phase 1 — Durable layer (read on demand)
These rarely change; do not bulk-load them. Run `ls ./docs/` to map the knowledge base, then open a static doc (see profile) only when the task enters its area. Absolute constraints (system-rules / "Core Rules") are the exception — know them before touching code.

## Phase 2 — Volatile layer (read now)
1. Read the active-context file(s) in the profile — last done / in progress / next. The primary one's frontmatter carries `doc_baseline_commit`.
2. Doc drift: `git rev-list --count <doc_baseline_commit>..HEAD` = commits landed since docs were last synced. (Absent ⇒ baseline not established yet; note it.)
3. List active plans in the execution-plans dir (see profile) whose `status` is not `completed`.

Working tree + recent commits (pre-injected):
!`git status --short`
!`git log --oneline -n 8`

## Phase 3 — Constraint smoke check (conditional)
The smoke command (see profile) guards code work — it is NOT a session-start blocker. Skip it when only orienting, or on a clean, in-sync tree; don't pay a multi-minute build to read docs. Run it before modifying code and surface any pre-existing breakage.

## Output
No summaries or greetings. One line:
`Context loaded. [N] docs indexed. Baseline <sha> (<N> commits behind HEAD). [active plans / violations]. Ready to work.`
