# Restore the upstream K3 reasoning budget in the inactive pilot

The rebase follow-up `44af27b` incorrectly preserved the pilot's former
1,024-token output limit as K3's combined reasoning/output limit. Upstream
deliberately promotes implicit K3 limits to 8,192 before quotation/reservation
because reasoning consumes the same budget. The CTO requested removing this
pilot exception, not changing the upstream model policy.

Scope: remove the model-specific override in `ProcedurePolicy`, update focused
real-client compatibility tests and current engine documentation. Preserve
non-K3 behavior, invocation deadlines, call/tool/read limits, controlled output,
authority checks, concurrency, spending admission and actual-cost settlement.
No deployment, activation, provider traffic, StarChat changes or shared-checkout
changes. StarChat test rehearsal may precede the PR; the CTO coordinates Angelo,
but deployment is a separate step from this correction.

Acceptance: the actual pilot/core/client path sends K3's upstream adaptive/max
controls and 8,192 ceiling both to OpenRouter and to the credit quotation
boundary; spending admission uses the promoted request, insufficient budget
refuses before dispatch, and successful receipts settle actual cost. Existing
evidence/refusal and non-K3 bounds continue to pass. Offline fixtures do not
establish live quality or compatibility with the unchanged 15-second deadline.
