---
description: Mid-session alignment check — engine + app + IPC contract.
---
Lightweight tick prompt. Decide whether to act or stay quiet. Budget: 15 seconds of user attention.

## Step 1 — Refresh constraints

Re-read `./engine/docs/system-rules.md` and `./engine/docs/ARCHITECTURE.md` to reload the static layer into context. Skim `./CLAUDE.md` if the cross-engine/app boundary is in play.

## Step 2 — Inspect recent changes

Run in parallel:

- `git status`
- `git diff --stat`
- `git diff` (focus on structural changes — new files, new imports, changed module boundaries, IPC contract surface)

## Step 3 — Mechanical enforcement

If anything in `engine/zylch/**` changed: `cd engine && make lint`.
If anything in `app/src/**` changed: `cd app && npm run typecheck`.

Run only the relevant one; don't run both if only one side moved.

## Step 4 — Manual alignment (only what automation doesn't cover)

- **IPC contract**: did anything change in the JSON-RPC method names, payload shapes, or error envelopes? If yes, both `engine/` (server) and `app/src/main/` (client) must be in sync. The contract is the most common silent breakage in this monorepo.
- **Layering**: do new files respect dependency direction? (Renderer → preload → main → sidecar; never the reverse. Engine never imports app types.)
- **Boundaries**: is data validated at the IPC boundary, not deep inside business logic?
- **Sidecar lifecycle**: are spawn / stdio / shutdown semantics still correct if `app/src/main/` was touched?
- **Profile dir**: anything writing under `~/.zylch/profiles/<email>/` should still go through the profile abstraction, not raw paths.

## Step 5 — Harness gaps

If a violation was possible because no automated check catches it:

```
Harness gap: [description]. Recommend adding [enforcement mechanism] to engine/docs/harness-backlog.md.
```

## Output

- All clear: `Aligned.`
- Violations: bullet list — violated rule, offending location, fix. Mechanical gaps > style issues.
- Harness gaps: append `Harness gaps detected:` with recommendations.
