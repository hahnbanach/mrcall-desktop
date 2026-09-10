# Setup billing and connection recovery

<!-- doc-scope:start -->
Scope: defects reproduced from the CTO's macOS acceptance recording; the bounded
renderer correction and its acceptance criteria. Engine billing policy is unchanged.
<!-- doc-scope:end -->

The recording shows a saved Anthropic BYOK configuration, selection of MrCall
credits as an unsaved edit, and navigation away with Save (1) still pending.
The credit balance becomes visible before the change is applied; the optional
API-key field looks required. Update then reports a direct Anthropic 400 balance
error. This does not establish insufficient MrCall funds.

Setup also reads the removed LLM_PROVIDER setting instead of the current
profile-key-or-Firebase transport policy. Check connection executes activation,
backend selection and restart even for an already verified selected engine,
producing a transient failure message during its own restart.

Correct billing readiness to match current engine policy. Show saved billing
mode separately from a pending choice, explicitly requiring Save before paid
work uses that choice. Keep optional BYOK entry out of the default credits path,
while preserving the ability to configure it. Top up continues opening the MrCall
dashboard and never edits a key. No automatic paid actions or live-profile edits.

Checking an already selected authenticated remote engine must use the existing
connection, verify matching identity, and report durable success/failure without
provisioning, backend writes, secondary sockets or restart. Initial activation
and backend selection keep their existing path.

Acceptance: current no-key signed-in configuration is ready without LLM_PROVIDER;
BYOK is identified by configured key; unsigned-in no-key is incomplete. A pending
switch is visibly unsaved, key entry is optional, top-up opens only the dashboard.
Browser tests prove zero connection mutation on Check connection, identity refusal,
and Settings pending choice/save behavior. Existing activation recovery still passes.

No engine/proxy payment policy changes, production deployment, balance changes,
credential removal or interpretation of screenshot balances beyond observed values.
