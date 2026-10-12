# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

[Company assignments](features/task-assignment.md) ship in Desktop `v0.1.56`. Six hosted company
engines have verified assignment reads, root-owned public trust and tenant-inaccessible signing
keys. Scoped draft and three-host workflows retain local acceptance. Ordinary/Qonto tasks remain
private. Café 124 shares one space; MrCall support/Mario share company memory and projects
in support's space after an authorized fenced join. Both identities have complete assignment
reads and shared project acceptance; private task/email cross-owner probes refuse.
[Operational record](../../docs/execution-plans/2026-10-08-mrcall-company-memory-sharing.md).
No real assignment or paid work is part of this acceptance.

The unreleased [contextual-email
candidate](../../docs/execution-plans/2026-10-08-contextual-email-assignment-guard.md) guards
actual reply create/update/send and preserves known email/task context across chat and worker
hops. [Enrollment](features/assignment-enrollment.md) distinguishes never-enabled, managed and
ambiguous legacy stores; managed authority cannot be removed by deleting trust. No candidate
source, enrollment or caller patch is activated in hosted services or installed clones.

The statements about hosted services below are the latest recorded acceptance,
not live rechecks by the local hardening closure. Detailed historical trial
receipts and diagnostic sequences are in the archive and owning plans.

Native [Qonto](features/qonto.md) has authenticated support-only banking,
restart/reconnect, source-comparison and managed-answer acceptance. Packaged
GUI and provider-UI comparison remain unverified. Current source accepts Qonto
credentials only as typed request arguments; no published Desktop or hosted
engine has that change. Released source combines
Qonto and [additional mailboxes/PEC](features/mailboxes.md). Six company units
have verified mailbox migration, primary registration, encryption startup and
row preservation; personal Gmail keeps its separate attachment source pin. The
[Qonto plan](../../docs/execution-plans/2026-10-04-qonto-connection.md) and
[integration plan](../../docs/execution-plans/2026-10-05-mailboxes-qonto-release-integration.md)
own remaining acceptance and rollout.

Production telephone service uses GPT-Live and the scoped company-knowledge
trial. Its pinned release reads revisioned `operator-instructions/phone.md`;
private call archives and the owner handset trial are accepted. Its saved test
provider endpoint reaches production, so the absent isolated listener is not a
safe route for new experiments. Spoken detail, broader/adverse cases and measured
latency remain open in the [knowledge plan](../../docs/execution-plans/2026-09-28-voice-company-knowledge.md).
Mario has no operator schedule; 124's schedule reads his inbox and Mario's
permissions deny instruction writes. Source and exact release references belong
to the [migration plan](../../docs/execution-plans/2026-10-01-telephone-notes-source-is-phone-md.md).
All seven hosted identities run as separate Unix users with enforced outbound
allow-lists; company stores have hashed hosted paths. Provisioning remains closed.
See the [sandbox plan](../../docs/execution-plans/2026-09-29-toward-sandbox.md).

Read-only chat policy version 1 refuses mutations before routing and at tool
boundaries. Kernel `cs ask` requires that capability. Local persisted-state and
installed-kernel journeys verify refusal without a paid reservation; no renewed
live product acceptance is asserted.

Mnemonic source is included in the six company engines' reviewed release pin.
Its product-quality acceptance remains separate from source activation. Its role, symbolic validator, origin-bound
admission, atomic commit/receipt/CAS, fenced join and maintenance boundaries are
wired. Replaced text is retained; the owner can restore a version. Customer-shaped
FACT eligibility applies before ordinary fact retrieval and search ranking;
this is a narrow known-shape restriction, not proof that all legacy facts are
correctly classified. Current contracts: [decisions](features/mnemonic-decisions.md),
[commit](features/mnemonic-commit.md), [join](features/company-memory-join.md) and
[writer inventory](features/mnemonic-writer-inventory.md).

Mnemonic product rollout remains pending. AC 5 failed on the rejected Haiku arm
and is met on M10's measured MNEMONIC picks on today's labels: Opus 5.5
(balanced, only after the B2 scorer fix) and GPT-6.1 Sol (economy)
([restatement](../../docs/evaluations/2026-10-01-mnemonic-corpus.md)). Those
picks run only once M10 merges. Haiku's paid corpus retains one critical failure; incomplete automatic extraction can remain pending
without a reason and be repaid. The corpus also lacks per-round proposal/latency
evidence and recorded Italian preservation misses. The hb plan at
`docs/execution-plans/2026-09-30-mnemonic-rollout.md` is present as historical
planned work. Refresh its host/source pins and prerequisites, review the current
product-rollout plan and rehearse migration on a store copy before use. Accepted
source activation and sandbox acceptance do not establish mnemonic product quality.

The engine owns revisioned company [written projects](features/project-memory.md).
Company membership is the capability changed only by `memory.join`; account
rules stay private. Profile stores retain mail, tasks, tokens and sync cursors.
N active IMAP mailboxes are supported; PEC envelopes retain provider identity
and original-message content, with per-mailbox sync, cursors and encrypted secrets.

Production K3 uses personal OpenRouter with USD20/day; the other three Café124
profiles retain prior billing choices and USD5/day. Their saved host configuration
enables automatic work and leaves preparation unpaused; the release preflight
finds no active preparation run. Preserve actual controls during rollout. Personal-key synthetic K3 acceptance
passes; funded credits remain unverified and an isolated uncertain hold remains.
Model configuration does not authorize backlog work. Engine API budgets and pauses
are independent from clone headless Claude Code and kernel classifiers. See
[control boundaries](../../docs/operator-setup.md#ai-execution-and-controls),
[spending protection](features/daily-llm-budget.md), [K3](features/k3-reasoning.md)
and [bounded preparation](features/bounded-preparation.md).

Support exposes approval-gated [outbound calls](features/outbound-calls.md) with
prior authenticated started/conversation evidence. Automatic diagnostic scripting
is not configured; caller permission and assistant ID remain required.

Milestone 10 ([model selection](features/model-selection.md)): the S6
switch-over is merged on `model-selection-m10a` (`08858d1f`, IR3 APPROVED);
not merged to `main`, not deployed. No model is a default in engine code:
every paid call names one of sixteen roles, and its model comes from the
model table's rankings per preset. OpenRouter runs the first ranked model; a
personal Anthropic key the first of the Anthropic ranking, pausing the role
(`RolePaused`, with a remedy) when it is empty; credits the first ranked id
the billing server serves on its v2 `/capabilities`. `resolved.json`, the
allowlist, `mrcall_served` and the `mrcall` column are gone. Prices and
request metadata come from the catalogue snapshot; every request has the one
shape (`zylch/llm/request_shape.py`).

The first table is the build copy and is published on the `model-table` data
branch (`8087fbf2`: table `304ab3b7…`, snapshot `b3196ae2…` read
2026-10-10T12:01:52Z); engines download it daily (`roles/distribution.py`).
Its picks, economy / balanced where they differ:

- MNEMONIC, MEMORY_MERGE: GPT-6.1 Sol / Opus 5.5.
- MEMORY_EXTRACT, TASK_DETECTION, COMPACTION, CORRECTION_LEARNING,
  SYNC_ANALYSIS: deepseek-v4-flash.
- CHAT: Sonnet 5.5. TASK_SOLVE: Sonnet 5.5 / Opus 5.5.
- REANALYZE, DEDUP, INTENT, TRAIN: ling-3.0-flash-vl.
- NARRATION: mimo-v2.6-pro. REPLY_NEED: glm-5.3-flash. WEB_SEARCH:
  mimo-v2.6-flash.

Anthropic rankings are empty for NARRATION under both presets and for the
three memory roles under economy. The measurement
([record](../../docs/evaluations/2026-10-11-role-measurement.md)) spent USD
14.15 settled, 15.03 counted, of 20; every satisfice role is measured-only.
The daily job (`scripts/model_table_job.py`, `model-resolution.yml`, 05:17
UTC, USD 10 a month) has not run from CI yet. The workflow carries a
TEMPORARY push trigger on the milestone branch for one proof run; it is
removed before the merge to `main`.

The local hardening closure repairs the model-catalog parameter declaration and
preserves typed preparation refusal through task dispatch. Synthetic contract,
task ownership/stale-view, transport, memory, cursor and billing checks pass.
The [closure plan](../../docs/execution-plans/2026-10-07-desktop-kernel-hardening-closure.md)
owns exact results and limitations. No installed-app, fleet or live-data cleanup
acceptance is implied.

## Unresolved

- Live PEC.net acceptance and provider marker comparison,
  Qonto installed Electron and provider UI remain open in their owning plans.
- Remaining Café124 billing choices and funded credit acceptance remain open;
  do not replay uncertain requests or resume preparation implicitly.
- M10's merge to `main` waits for the job's proof run (the repository secret
  `OPENROUTER_API_KEY`), the billing server's production promotion (`main`
  and `dev` at `bb8f553`; production `37f330d` lacks the M10 code, so a
  credits profile would pause with "update the billing server") and the
  CTO's go. Open with the CTO: legacy Anthropic-key profiles (no saved
  preset, so economy) pause on memory and narration; the recommendation is
  to accept the pause.
- Until the job republishes, a Desktop release with M10's `release.yml` or a
  billing-server image built after 2026-10-24T12:01:52Z fails the 14-day
  snapshot gate.
- Several mnemonic items remain open:
  - the OpenRouter truncation check, which did not bind on seven of nine
    arms;
  - the extraction parser's refusal of "SKIP + reason";
  - extraction retry observability;
  - reviewed rollout and migration rehearsal.

  A M8-migrated store cannot reopen in a M5–M7 build.
- Telephone detail/repetition/adverse cases and quantitative latency remain open.
- Installed/fresh-account Desktop GUI and Windows launch remain unverified.
- The app still renders a refused company join's reason only; `joining` and
  `blocking` details are not consumed and settling commands remain engine CLI only.
- Calendar, phone memory parity, RPC error humanization, WhatsApp multi-profile
  isolation, product chat and broad security review remain separately owned
  [backlog](harness-backlog.md) work. Prompt-format fixes have no new quality score.

## Next

1. Continue Qonto/PEC GUI and provider acceptance under their existing plans.
2. Resolve billing choices without replaying uncertain requests; preserve actual
   saved controls and initiate no paid preparation for release verification.
3. Finish milestone 10 (branch `model-selection-m10a`):
   - the job's proof run, then S8's end to end and final review; remove the
     temporary push trigger before the merge;
   - review the mnemonic rollout and the migration rehearsal before product
     acceptance.

   Preserve the rejected corpus evidence.
4. Continue telephone knowledge detail/adverse/latency acceptance from its plan.
5. Resume other workstreams from their existing owners when requested.
