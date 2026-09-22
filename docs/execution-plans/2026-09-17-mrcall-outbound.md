---
status: completed
---

# Restore MrCall outbound calling

<!-- doc-scope:start -->
Scope: execution and verification of the approved outbound-call restoration brief.
<!-- doc-scope:end -->

Brief: [intent and acceptance](../briefs/2026-09-17-mrcall-outbound.md). Fresh brief review approved on 2026-09-17.

## Milestone 1 — implementation and offline verification

Owner: primary session. Update the existing StarChat call method to use realm-scoped atom outbound and `toNumber` only. Reject unsupported legacy overrides rather than silently claiming they work. Validate international number input, preserve Italian leading zeros, and retain the dashboard's blocked destination prefixes. Return submitted/unknown states honestly, including non-JSON or empty success bodies; do not retry ambiguous transport failures.

Make InitiateCallTool acquire and close the current Firebase client at execution time; register without the disabled legacy client. Require an explicit caller business ID in every request; never fall back to mutable session selection while approval is pending. Add the tool to canonical APPROVAL_TOOLS with destination/caller preview. Clarify in its schema and prompt that the caller uses its saved assistant configuration and submission does not prove answer/audio.

Run focused tests using HTTP MockTransport for actual client path/body/header/response handling, tool auth/cleanup/errors, factory registration, and denied/missing/approved gate behavior. Baseline: 19 adjacent tests passed before changes. Fresh integration review must approve before deployment.

## Milestone 2 — scoped runtime verification

Owner: primary session. Confirm dev and service checkouts share the baseline and changed runtime files are otherwise unchanged. Back up each deployed file before applying only this patch, restart only support's `zylch-server@9nXeYF8OXPetUFsSP4zDC3F2i673`, and reauthenticate with cs whoami. Preserve the authoritative `/home/mrcalld/.zylch` profile. Rollback restores backed-up code and restarts that same unit; no profile copying, Git commits, or changes to other profiles.

Verify the live tool is available and approval-gated. Use caller `70060cbc-f7fa-35a4-b557-232eaaa9836d` only after confirming its ownership by support (read-only business lookup has confirmed this). If safe with its existing configuration, submit one approved call to Litio's MrCall number +390289040671. Record the actual returned result; do not equate HTTP acceptance with a completed diagnostic. No blind retry. If a backend prerequisite blocks the call, report the precise response and keep provider/config mutations out of scope.

## Completion

Separate final review checks the final-user path, code/tests, and deployment evidence. Update engine living context and a durable phone-tool contract, record any remaining audio/diagnostic limitation, and reconcile this plan. No email to Litio and no USER_NOTES change are part of this implementation.

## Verification evidence

- Fresh brief and plan reviews approved. Integration review required explicit caller binding across pending approval and removal of an obsolete report-back promise; both repaired and approved.
- 42 focused tests passed; focused Ruff passed. Tests include an approval-time session-selection change, which cannot change the explicit caller.
- Dev and service baseline: `855f6501e015cab8c1608e79cc84817f16d8bce3`. Seven runtime files deployed and byte-compared with reviewed source. Backup: `/home/mrcalld/mrcall-outbound-backup-344bybgs/`, with manifest and originals. Two new modules are listed as previously absent. Rollback restores the five original files, removes only those two new modules, and restarts support's unit. No profile data changed and no Git commit made.
- Only support's unit restarted; active PID 2662314 at 2026-09-17 15:27:27 UTC. `cs whoami` then verified support identity. Initial immediate health read saw startup HTTP 502; subsequent authenticated read passed.
- Live user path: `cs chat --allow initiate_call`, one concrete request to +390289040671 using caller `70060cbc-f7fa-35a4-b557-232eaaa9836d`. Exactly one tool approval reported. HTTP 200, provider `status=started`, direction outbound, uuid `3f16f92a-2c6c-450c-8f10-34e4c7edceb2`, conversation `CON-583c6800-45ee-42a7-aa4c-cb37a51f283a`. No repeat request.
- Mailbox read after submission found no matching transcript. Latest notification was Mario's earlier call at 15:16:41 UTC. The caller's dashboard conversation search did not include the returned conversation ID; the target assistant search returned no rows. This is missing outcome evidence, not proof of failure or success. Transcript retrieval/diagnostic scripting are outside this submission tool's contract.

- Follow-up after the operator pointed to the notification: Gmail All Mail contains the matching transcript, dated 2026-09-17 15:30:16 UTC, subject `MrCall. 📩 +390289040671  for MrCall`, Message-ID `<1847363001.2967.1789659016291@starchat-7bd4cd589d-kdnc7>`. Its support footer names caller business and exactly `CON-583c6800-45ee-42a7-aa4c-cb37a51f283a`. The transcript opens with Litio's assistant identifying itself and contains a multi-turn exchange, confirming answer and bidirectional speech for this direct call. It does not test the customer's forwarding or certify recording quality.
- Caller configuration observation: our voice assistant initially says it is not authorized to talk to robots, then continues. That is an existing saved voice-policy issue, not an API/tool failure. No assistant configuration was changed. The API uses saved configuration and does not accept a per-call diagnostic script.
- Final formatting added only a blank line in call_tools.py; that byte-identical formatted source was copied to the service checkout. Focused test capture: `/tmp/mrcall-outbound-tests.txt` (42 passed). Source remains uncommitted.

- Separate final end-to-end review: APPROVED. Reviewer independently checked all seven deployed/source files, the captured 42-pass result, approval dispatch and the matching transcript evidence. Submission restoration and the authorized live-call test are complete.
