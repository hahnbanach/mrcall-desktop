---
status: active
---

# Billing-business picker recovery

Approved brief: [scope and acceptance](../briefs/2026-10-05-business-picker-recovery.md).
Fresh brief reviewer `business_picker_brief_review`: REVISE for implicit sole
selection; explicit no-auto-selection requirement added, then APPROVED.

## Execution

1. Lead implements only picker/search support and focused browser fixtures in
   isolated worktree `/home/mal/hb/mrcall-r5-business-picker`, based on current
   main. Preserve concurrent Qonto changes; do not edit the service checkout.
   - Add a typed search helper with existing exact UUID/email routes and four
     parallel text queries (companyName, nickname, name, surname). Each query
     uses the existing server role-scoped RPC and a bounded result limit;
     union by business ID without broad unfiltered client-side enumeration.
   - One active raw batch per picker. Superseded queued work does not dispatch;
     RPC's existing 30-second deadline bounds raw requests. A separate UI
     deadline bounds waiting (including queued work); show a retryable timeout
     instead of indefinite Searching. Ignore old responses after query change,
     close, unmount or auth/transport change. A retry may wait for the bounded
     previous RPC batch to finish, never launch unbounded overlapping batches.
   - Distinguish successful zero matches, authentication failure, malformed
     response, transport failure and partial failed searches. Do not label a
     failed/partial search as a complete empty result. Never print error bodies
     or business data in regression output.
   - Remove automatic sole-business `onChange`; only selecting a result changes
     selection. Failed lookup never clears an existing selection. Save retains
     the existing backend-authorized ID validation; no new billing authority.
2. Real browser tests mount the actual picker with synthetic RPC boundaries:
   company/personal-name/surname/nickname matches, UUID/email routing, duplicate
   results, bounded concurrency, successful empty results, rejected/timeout and
   retry, partial failure, late responses on query/close/unmount, sole-result
   nonselection and explicit selection. Existing Settings browser tests plus
   app typecheck/build. Fresh integration reviewer must APPROVE before delivery.
3. Record source findings versus incident uncertainty under sandbox R5, update
   app living context narrowly, and obtain two fresh independent final reviews.
   Publish scoped source after `git pull --rebase origin main`, then
   `git push origin HEAD:main`. Determine the next unused patch tag; use the
   existing signed Apple Silicon workflow and verify source/tag alignment,
   actual signing/notarization and uploaded asset. Same final reviewers assess
   post-CI delivery. Mark only this repair completed after both approve delivery;
   sandbox R5 remains active until real app and scratch criteria pass.

## Constraints and evidence

No token extraction, voice-file access, mail/business contents in output, paid
calls, live identity/configuration changes or arbitrary billing selection.
Host metadata: initial list lookups succeed; no typed-filter call is correlated
yet. App version/current connection reply is pending, so exact incident cause
is not claimed. This source repair addresses independently verified defects.
The root clone is concurrently edited; all owned work is isolated and only
scoped files are committed. A newly published patch is not an installed-patch
acceptance result.

Fresh plan reviewer `business_picker_plan_review`: APPROVED.
