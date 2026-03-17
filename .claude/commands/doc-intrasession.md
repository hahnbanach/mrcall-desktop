---
description: Architecture & Rules Alignment Check
---
1. **Re-read constraints.** Read `./docs/system-rules.md` and `./docs/architecture.md` to refresh the rules in active context.
2. **Inspect recent changes.** Review code changes made in the last few interactions. If available, run `git diff --stat` and `git diff` to see exactly what changed.
3. **Run mechanical enforcement.** If custom linters, structural tests, or boundary-check scripts exist, run them now. These are the source of truth for conformance — not subjective review.
4. **Manual alignment check.** For anything not covered by automated enforcement, verify:
   - Do new files/modules respect the defined layering and dependency direction?
   - Are data shapes validated at module boundaries, not deep inside business logic?
   - Do new dependencies flow in the permitted direction only?
   - Are cross-cutting concerns (auth, telemetry, feature flags) entering through the designated interface, not ad-hoc imports?
5. **Check for harness gaps.** If a violation was possible because no linter or structural test catches it, flag this explicitly: `Harness gap: [description]. Recommend adding [enforcement mechanism].`
6. **Output:**
   - If everything passes: `Aligned.`
   - If violations exist: list each as a bullet with the violated rule, the offending code location, and the fix. Prioritize mechanical enforcement gaps over style issues.
   - If harness gaps were found: append `Harness gaps detected:` followed by recommendations.