---
status: completed
date: 2026-10-05
brief: ../briefs/2026-10-05-mailboxes-qonto-release-integration.md
---

# PEC and Qonto integration for the next release

<!-- doc-scope:start -->
Scope: source integration, compatibility verification and shared-main delivery
of PEC/additional mailboxes and Qonto; no installer or hosted rollout.
<!-- doc-scope:end -->

Brief gate: `pec_qonto_brief_review`, APPROVED. Lead owns integration and
corrections. Prior feature reviews remain evidence for unchanged source;
fresh integration and separate final reviewers judge the combined result.

## M1 — Combine and verify the source

1. Capture local main `a68ea7b`, latest origin/main, feature `83a6700`, dirty
   root paths and hashes. Use a new integration worktree from local main.
   Merge current origin/main, preserving its 0.1.55 metadata, business-picker
   and opaque-ID fixes. Retain Qonto's stricter immediate auth-gate invalidation.
2. Import only the eight-commit PEC delta `65659b3..83a6700`, excluding the
   unrelated predecessor/voice history. Three-way resolve each changed path
   using that exact feature base. Preserve root AGENTS edits and current
   living documentation/baselines; import the original PEC brief/plan as its
   historical work trace. Inspect overlapping Settings/preload/types, RPC
   registration, storage filters/upserts, worker identity, migration order,
   attachment confinement, preparation limits and auth boundaries.
3. Correct demonstrated integration defects, not unrelated baseline behavior.
   Make the two Settings cards reachable together, preserve the current auth
   gate and fence mailbox secrets/late replies on profile/engine changes.
   Legacy engines must report unsupported mailbox/Qonto methods clearly.
   Keep existing email ownership semantics and source-specific bank privacy.
4. Verify disposable fresh/legacy migration paths with both Qonto and mailbox
   rows, second boot/idempotency, backups and restart. Run focused mailbox
   parsing/sync/RPC/storage/identity suites plus Qonto and affected boundary
   regressions. Use RAM-backed temporary test stores; never live profiles.
5. Run auth, billing-picker, onboarding, mailbox and Qonto component/native
   journeys, plus a real combined Settings render with both cards and deferred
   logout cases. Run TypeScript/build and relevant lint. Verify PyInstaller's
   real module collection includes the mailbox and Qonto RPC/provider/migration
   modules, and the renderer bundle contains both Settings entry points.

**Gate:** fresh integration reviewer sees complete affected files, resolved
conflicts, exact check results, baseline failures distinguished by reproduction,
and preserved changes. Repair findings with the same reviewer before M2.

## M2 — Review and deliver shared source without a release

Reconcile docs and record release provenance: tags 0.1.54/0.1.55 lacked the local
Qonto commit; the integrated shared source includes both cards. Remote profiles
still require compatible engine deployment after this source-only task.
Keep installed Desktop, live PEC and bank-provider UI acceptance explicitly open.
A separate fresh final reviewer checks the complete user path and readiness.

After APPROVED, commit only the reviewed integration. Fetch again before the
main update; incorporate concurrent remote commits without rewriting history,
review/recheck any overlapping behavior. Fast-forward the local main checkout
while retaining unrelated dirty files, then push main only (normal fast-forward,
never force). Verify the remote tree/ancestry and both renderer/engine surfaces.
Leave all release tags, workflow dispatch and services untouched. No version
bump is needed for source integration; the next release owns its version.

## Risk and recovery

Mailbox integration rebuilds the email table. Verify backup/restore only on
disposable SQLite copies; old binaries must not run against a migrated schema.
The source-only task never migrates a hosted profile, changes egress or sends
mail. On a merge/check failure repair the isolated tree; the main checkout and
feature branch remain available. Before the shared push, all integration work
is recoverable locally. A later source rollback is a reviewed revert, never
resetting shared history or replacing live profile databases.

## Evidence

Brief and plan gates: APPROVED (`pec_qonto_brief_review`,
`pec_qonto_plan_review`). M1 integration gate: APPROVED
(`pec_qonto_integration_review`). Separate final gate: APPROVED
(`pec_qonto_final_review`). Shared-main delivery completed.

Integrated local Qonto commit `a68ea7b` with shared main `7b4e7d2` and only
PEC delta `65659b3..83a6700`. Package metadata remains 0.1.55. Auth immediate
invalidation and current opaque-business-ID selection remain in place.
The seven conflict resolutions preserve both migration registrations and
backup ordering, both Settings surfaces and safe per-mailbox attachments.

Review corrections cover: cancelled probes and late responses after engine or
account changes; legacy-engine upgrade guidance; additional-mailbox download
without primary credentials; refusal of an explicit unknown mailbox ID; and
sanitized typed IMAP causes so exception tracebacks cannot log passwords.

Verification (disposable profiles, synthetic credentials/providers):

- Combined email/storage/Qonto/RPC/identity run: 721 passed, three obsolete
  single-backup-count assertions failed. Assertions now distinguish Qonto's
  protected pre-install backup from the destructive mailbox/company backup.
- Final email/storage/mailbox-RPC/setup/identity/confinement run: 340 passed.
  Combined migration, reopen, attachment confinement, primary-password absence,
  unknown-mailbox refusal and actual sync-log secret regressions pass.
- Expanded RPC contract checks: 17 passed, two pre-existing failures reproduced
  exactly on untouched `a68ea7b`: `llm.models` parameter declaration and
  task dedup minimal-payload behavior. They are outside this integration.
- Actual Settings + preload + Python dispatcher browser journey renders both
  Mailboxes/PEC and Qonto; Qonto sync/tasks/publication/restart path passes.
  Mailboxes UI tests exercise add/edit/remove, Cancel, deferred replies,
  account/engine invalidation, unsupported engines, filtering and archive rollback.
- Qonto component, credential and managed-history suites; actual App offline
  logout; auth main/renderer; onboarding; business-picker and Settings recovery
  browser checks pass. TypeScript and production renderer build pass.
- Actual PyInstaller `collect_all('zylch')` contains mailbox/PEC and Qonto
  provider/RPC/migration modules. Changed Python boundary files pass Black and
  Ruff; `git diff --check` passes. No platform installer was built.

Evidence logs are under `/tmp/mrcall-ai-kit/pec-qonto-integration/` on the
integration machine; this plan preserves the portable conclusions. The isolated
checkout inherits tracked AGENTS.md at 204 lines (200-line mechanical limit);
the operator's existing local rewrap already satisfies that limit and is left
uncommitted. The Qonto brief's link to an ignored local transcript is replaced
with the durable PEC brief. No release tag, workflow, live profile or service
has been changed. Installed Desktop and live PEC/provider acceptance remain open.


## Delivery

Reviewed integration commit: `a89e261`. A concurrent documentation-only shared
commit, `fddf760`, was retained in merge `63f1916`; `app/` and `engine/` are
byte-identical to the reviewed integration. Local main was fast-forwarded with
all unrelated operator files preserved, and a normal push delivered `63f1916`
to origin/main. The source now carries both Settings cards and their native
engine methods for the next release. No tag, installer, workflow dispatch or
hosted update was performed. This completion record is a documentation-only
follow-up; installed/live acceptance remains in the original feature plans.
