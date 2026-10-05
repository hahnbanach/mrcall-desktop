---
status: active
---

# Opaque selected-business ID repair

Brief: [intent and acceptance](../briefs/2026-10-05-business-id-resolution.md).
Fresh reviewer `opaque_id_brief`: APPROVED.

1. In isolated worktree `/home/mal/hb/mrcall-r5-business-picker`, the lead adds
   an explicit exact-ID request variant to the existing serialized lookup helper.
   Selected/saved label resolution passes this variant; discovery keeps its
   current UUID/email/name behavior. Update the obsolete UUID-only comment.
   Preserve cancellation, bounds, authority and exact Save validation.
2. Extend the actual-picker browser fixture with synthetic numeric and other
   opaque IDs. Prove selection and remount label resolution send only exact ID
   filters, reopened selection is preserved, Save validation uses the exact ID,
   missing IDs are invalid and failed lookups are errors. All existing picker
   cases, typecheck and build must pass. Fresh integration review before release.
3. Record the regression under R5 and app context. Determine next unused patch
   version and align package metadata. Two fresh independent final source
   approvals precede publication (`git pull --rebase origin main` then
   `git push origin HEAD:main`) and the signed Apple Silicon tag. Verify source,
   signing, notarization and release asset; obtain both delivery rereviews.
   Complete only this repair; sandbox R5 remains active pending real app/scratch.

The prior fixture covered only UUID identifiers and missed this regression.
No real identifier is copied into fixtures/docs. No live configuration change,
paid call or service-checkout edit. The existing Save path remains available to
the CTO; no successful save or paid chat is claimed until reported.

Fresh plan reviewer `opaque_id_plan`: APPROVED.

## Verification

Integration reviewer `opaque_id_integration`: APPROVED. Actual-picker browser
checks pass, including synthetic numeric and opaque IDs through selection,
remount and reopening, plus the actual Save validator's exact-ID request,
missing-ID rejection and uncertain failure. This invokes the Save validator,
not a full Settings Save interaction. The fixture now applies realistic
substring filters, so IDs cannot accidentally match every name response.
Command: `MRCALL_PLAYWRIGHT_MODULE=/tmp/mrcall-qonto-browser/node_modules/playwright node app/scripts/test-business-picker.mjs`.
Final typecheck/build and `git diff --check` pass (lead tool sessions 23024,
79411). No live account search or paid call is part of these checks.

Version 0.1.55 was unoccupied at preparation and package metadata is aligned.
Fresh independent source reviewers `opaque_id_final_a` and `opaque_id_final_b`
both return APPROVED for `1c04412`. Both independently execute the browser
suite successfully. Reviewer A's first run timed out on an existing click case
while another browser run was active; its retry passed. Signed delivery and
post-CI rereviews remain pending.
