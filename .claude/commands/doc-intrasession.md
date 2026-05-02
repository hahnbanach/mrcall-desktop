---
description: Mid-session alignment check — root + engine + app + IPC contract.
---
Lightweight tick prompt. Decide whether to act or stay quiet. Budget: 15 seconds of user attention.

## Step 1 — Refresh constraints

Re-read the relevant static layer. Default to `./engine/docs/system-rules.md` and `./engine/docs/ARCHITECTURE.md` for engine work; add `./app/docs/ARCHITECTURE.md` (if present) and `./app/CLAUDE.md` for app work; add `./docs/ipc-contract.md` (if present) when the engine ↔ app boundary is in play. Skim `./CLAUDE.md` if you've lost the monorepo shape.

## Step 2 — Inspect recent changes

Run in parallel:

- `git status`
- `git diff --stat`
- `git diff` (focus on structural changes — new files, new imports, changed module boundaries, IPC contract surface)

## Step 3 — Mechanical enforcement

Run only the relevant one; don't run both if only one side moved.

- If anything in `engine/zylch/**` changed: `cd engine && make lint`.
- If anything in `app/src/**` changed: `cd app && npm run typecheck`.

## Step 4 — Manual alignment (only what automation doesn't cover)

- **IPC contract** (most common silent breakage in this monorepo): did anything change in JSON-RPC method names, payload shapes, or error envelopes? If yes, both sides must move together — `engine/zylch/rpc/` (server) and `app/src/preload/index.ts` + `app/src/main/` (client). Cross-cutting; surface in `./docs/ipc-contract.md` if it exists.
- **Layering**: do new files respect dependency direction? (Renderer → preload → main → sidecar; never the reverse. Engine never imports app types.)
- **Boundaries**: is data validated at the IPC boundary, not deep inside business logic?
- **Sidecar lifecycle**: are spawn / stdio / shutdown semantics still correct if `app/src/main/` was touched?
- **Profile dir**: anything writing under `~/.zylch/profiles/<email>/` should still go through the profile abstraction, not raw paths.

## Step 5 — Harness gaps

If a violation was possible because no automated check catches it:

```
Harness gap: [description]. Recommend adding [enforcement mechanism] to:
  - ./docs/harness-backlog.md       (cross-cutting / IPC / release)
  - ./engine/docs/harness-backlog.md (engine-only)
  - ./app/docs/harness-backlog.md   (app-only)
```

Pick the tree the gap belongs to. Don't duplicate.

## Output

- All clear: `Aligned.`
- Violations: bullet list — violated rule, offending location, fix. Mechanical gaps > style issues.
- Harness gaps: append `Harness gaps detected:` with recommendations.
