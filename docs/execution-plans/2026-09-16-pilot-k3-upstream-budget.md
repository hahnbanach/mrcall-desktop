---
status: completed
---

# Restore upstream K3 budget — bounded correction

Brief: [intent and acceptance](../briefs/2026-09-16-pilot-k3-upstream-budget.md).
Brief review: `k3_correction_brief_review` APPROVED; shared client promotion
precedes paid admission, and live deadline compatibility remains unproven.

## Single implementation milestone

Lead owns the small local correction in the dedicated Desktop pilot worktree.
Remove only the K3 override from `ProcedurePolicy`; explain why the guarded
client owns model-specific reasoning budgets. Update the real-wire and proxy
quotation assertions to 8,192. Check the exact real ledger reservation against
the final promoted request and add insufficient-budget refusal before outbound
HTTP. Reuse existing non-K3, evidence, cancellation and bounded-call tests.
Update current engine docs, distinguishing the default 1,024 output request
from K3's combined 8,192 ceiling and preserving live-test caveats.

## Verification and handoff

- Run focused compatibility, email-policy and upstream K3 tests against the
  canonical StarChat procedure artifact, synthetic network edges and temporary
  SQLite. No paid/live calls or test deployment.
- Run changed-file formatting/lint and the mechanical documentation gate.
- Independent integration review, then a separate final review of the actual
  ChatService → policy → client → wire/quote path and documentation.
- Record evidence and commit only this correction; do not rewrite rebase history
  or touch shared checkouts. Rollback is a selective revert of the correction
  commit, not restoration of an entire pre-rebase tree.

## Evidence

- Baseline compatibility tests: 6 passed before changes.
- Plan review: `k3_correction_plan_review` APPROVED.
- Focused compatibility, email integration, procedure policy and upstream K3:
  63 passed (13 existing deprecation warnings), using the canonical StarChat
  procedure and temporary SQLite; HTTP/quotation responses are fixtures.
- Black, Ruff and `git diff --check`: passed for changed Python files.
- Mechanical documentation gate: clean; existing 4 oversized-doc and 7 undated
  trace advisories unchanged. Root/engine living snapshots retain canonical
  State now / Unresolved / Next shape. No repo-wide baseline advancement is
  claimed by this scoped correction.
- Integration review: `k3_correction_integration_review` APPROVED; independent
  run of 58 focused tests passed. No blocking changes to non-K3 or safety bounds.
- Final review: `k3_correction_final_review` APPROVED; actual email/core/client
  path inspected independently. Delegated `doc-critic`: living shape OK, no
  STALE findings in the correction. Inherited deployment claims were not checked
  remotely; test counts are the recorded command evidence, not a final-review
  rerun. Live pilot quality, phone/email latency and compatibility with the
  existing deadline remain unverified.
