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

Milestone 10 ([model selection](features/model-selection.md)) is on branch
`model-selection-m10a`, not merged to `main`, not deployed. Every paid call
names one of sixteen roles; its model comes from the model table's rankings
per preset (OpenRouter: first ranked; personal Anthropic key: first of the
Anthropic ranking, pausing the role with a remedy when it is empty; credits:
first ranked id the billing server serves on v2 `/capabilities`). Prices come
from the catalogue snapshot. The build copy is the table the daily job
published on 2026-10-12 (`f1847561…`, snapshot `571b55d2…`, `model-table`
`4bbbdf89`); engines download the published table daily. Only NARRATION under
economy has no Anthropic model. Records: [measurement](../../docs/evaluations/2026-10-11-role-measurement.md)
(USD 15.03 counted of 20), [end to end](../../docs/evaluations/2026-10-12-m10-end-to-end.md)
(AC 10). The daily job has run locally only (October: USD 5.37 of 10); the
workflow's push trigger is TEMPORARY, for the CI proof run.

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
- M10's merge to `main` waits on CTO and operator actions: the
  `OPENROUTER_API_KEY` repository secret for the CI proof run; the billing
  server promoted to production first (`main`/`dev` `89deceb`, production
  `37f330d`), with its egress to `raw.githubusercontent.com` and push
  protection on `model-table`; a valid Anthropic key and the Firebase test
  account for the remaining paid legs; the CTO's go, including on the
  NARRATION pause for legacy Anthropic-key profiles (recommended: accept).
- Without a republish, M10 release and server builds fail the 14-day snapshot
  gate after 2026-10-26T17:43:41Z.
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
3. Finish milestone 10: after the secret, the CI proof run, then remove the
   temporary push trigger; merge on the CTO's go after the server promotion.
   Review the mnemonic rollout and migration rehearsal before product
   acceptance; preserve the rejected corpus evidence.
4. Continue telephone knowledge detail/adverse/latency acceptance from its plan.
5. Resume other workstreams from their existing owners when requested.
