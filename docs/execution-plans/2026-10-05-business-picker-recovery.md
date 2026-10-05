---
status: completed
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

Implementation baseline correction: the initial isolated worktree inherited the
other session's unpublished Qonto commit. Only this repair's diff was transplanted
onto origin/main (`0ab1849`), leaving that session and its commit untouched.
The picker needs a narrow auth-utils invalidation subscription and active-session
predicate to enforce the approved logout cancellation requirement even when
Firebase sign-out fails; these two helpers are included without Qonto features.
All final checks/reviews target the corrected baseline.

## Source verification and delivery

Integration reviewer `business_picker_integration`: APPROVED after reviewing
source, auth invalidation hooks and actual synthetic browser/auth logs.
The final corrected-baseline app typecheck and build pass. Actual-picker browser
checks pass for name routing/union, explicit selection, empty/error/partial states,
UI timeout/retry, bounded raw concurrency and stale auth/transport responses.
Existing Settings cold/reconnect/discard checks pass after stale fixture contracts
were updated to current provider/key-preservation behavior. Actual renderer auth
checks: 14 pass, including invalidation notification and unsubscribe cleanup.
Logs: `/tmp/mrcall-ai-kit/2026-10-05-business-picker-recovery/`.
No real business data, token, voice value, mail content or paid call is used.

The next unused patch version is 0.1.54; package and lockfile metadata are aligned.
Fresh independent final source reviewers `business_picker_final_a` and
`business_picker_final_b` both return APPROVED for `b3023a3`. Signed CI and
post-CI delivery reviews are recorded below.
The installed application has not changed; R5 remains active.

### Published delivery evidence

Source/tag `0ab1bd7233ed982ad79ebcfbc6bf92519180ec67` (`v0.1.54`) is
published on main. CI [37289911832](https://github.com/hahnbanach/mrcall-desktop/actions/runs/37289911832)
completed successfully: sidecar, installer and release attachment all succeed.
Notary credential validation succeeds and the un-notarized fallback step is
skipped. Filtered build evidence shows Darwin distribution signing, custom
`[notarize] submitting`, and no custom notarization skip. The awaited pinned
notarization library requires Apple's Accepted status and stapling before the
successful installer step completes. No credential or raw log is recorded.

[Release 0.1.54](https://github.com/hahnbanach/mrcall-desktop/releases/tag/v0.1.54)
is published (not a draft or prerelease), with Apple Silicon asset
`MrCall.Desktop-0.1.54-arm64.dmg`, 240719271 bytes, GitHub digest
`sha256:fbd9281004b8201815b11272cb53c2f576cb33373d0f013078dc0a84d1227380`.
Filtered metadata: `/tmp/mrcall-picker-release-metadata-20261005.json` (0600).
Native macOS signature inspection and the installed-patch business lookup are
not performed on this Linux VPS. Both post-CI delivery reviewers,
`business_picker_final_a` and `business_picker_final_b`, return APPROVED. This
repair delivery is completed; the CTO must install the patch, choose the intended business, save and retry a new chat.
The separate sandbox R5 acceptance remains active.
