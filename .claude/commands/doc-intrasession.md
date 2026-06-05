---
description: Architecture & Rules Alignment Check
allowed-tools: Bash(git *) Bash(make *) Bash(npm *) Bash(sbt *) Bash(pytest *)
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

Lightweight mid-session tick. Decide whether to act or stay quiet. Budget: ~15 seconds of attention; surface only what needs action now.

## Step 1 — Refresh constraints
Reload the relevant static layer for the area you are touching (see profile) — absolute rules first.

## Step 2 — Inspect recent changes (pre-injected)
!`git diff --stat`
Focus on structural change: new files / imports, changed module boundaries, new public surface. Run `git diff` on anything that looks structural.

## Step 3 — Mechanical enforcement
Run the smoke command (see profile) when code moved. Automated checks are the source of truth, not subjective review.

## Step 4 — Manual alignment (only what automation misses)
- New files / modules respect layering and dependency direction?
- New deps flow only in the permitted direction?
- Data validated at boundaries, not deep in business logic?
- Cross-cutting concerns enter through designated interfaces?
- Plus the repo-specific checks in the profile.

## Step 5 — Harness gaps
If a violation was possible because nothing automated catches it:
`Harness gap: [description]. Recommend [enforcement] → harness-backlog (see profile).`

## Output
- All clear: `Aligned.`
- Violations: bullets — rule, location, fix. Mechanical > style.
- Harness gaps: append `Harness gaps detected:` + recommendations.
