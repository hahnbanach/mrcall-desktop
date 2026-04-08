---
description: Architecture & Rules Alignment Check
---
Lightweight mid-session check. Like a tick prompt — decide whether to act or stay quiet.

## Budget: 15 seconds of user attention
Keep output minimal. Only surface things that need action *now*.

## Step 1 — Refresh constraints
Re-read `./docs/system-rules.md` and `./docs/ARCHITECTURE.md` to reload the static layer into context.

## Step 2 — Inspect recent changes
Run `git diff --stat` and `git diff` to see what changed since last check. Focus on structural changes — new files, new imports, changed module boundaries.

## Step 3 — Mechanical enforcement
Run linters/structural tests if they exist (`Makefile`, `package.json` scripts, `./tools/`). Automated checks are the source of truth — not subjective review.

## Step 4 — Manual alignment (only what automation doesn't cover)
- Do new files/modules respect layering and dependency direction?
- Do new dependencies flow in the permitted direction only?
- Are data shapes validated at boundaries, not deep inside business logic?
- Are cross-cutting concerns entering through designated interfaces?

## Step 5 — Harness gaps
If a violation was possible because no automated check catches it:
`Harness gap: [description]. Recommend adding [enforcement mechanism].`

## Output
- All clear: `Aligned.`
- Violations: bullet list — violated rule, offending location, fix. Mechanical gaps > style issues.
- Harness gaps: append `Harness gaps detected:` with recommendations.