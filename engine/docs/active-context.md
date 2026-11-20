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

The [contextual-email
candidate](../../docs/execution-plans/2026-10-08-contextual-email-assignment-guard.md), its
[enrollment](features/assignment-enrollment.md) and the typed Qonto credentials are not in
`main`'s tree. Tag `main-before-hosted-line-20261120` holds their modules. No hosted service
or installed clone ran them.

The statements about hosted services below are the latest recorded acceptance,
not live rechecks by the local hardening closure. Detailed historical trial
receipts and diagnostic sequences are in the archive and owning plans.

Native [Qonto](features/qonto.md) has authenticated support-only banking,
restart/reconnect, source-comparison and managed-answer acceptance. Packaged
GUI and provider-UI comparison remain unverified. Released source combines
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
and awaits M10 re-measurement using the resolver-selected model. The paid corpus
retains one critical failure; incomplete automatic extraction can remain pending
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

The local hardening closure repairs the model-catalog parameter declaration and
preserves typed preparation refusal through task dispatch. Synthetic contract,
task ownership/stale-view, transport, memory, cursor and billing checks pass.
The [closure plan](../../docs/execution-plans/2026-10-07-desktop-kernel-hardening-closure.md)
owns exact results and limitations. No installed-app, fleet or live-data cleanup
acceptance is implied.

The hosted daemon runs a mail loop: every `MAIL_SYNC_INTERVAL_MINUTES` it
runs the email-only intake of `sync.run {scope: "email"}` by itself, so an
engine that clients only read keeps its archive current. Its
[plan](../../docs/execution-plans/2026-11-18-engine-owned-mail-sync.md) owns
that evidence.

Seven hosted units run one package since 2026-11-20: tag
`hosted-engine-0.1.57.dev4` on `main`, release
`/home/mrcalld/releases/hosted-engine-0.1.57.dev4-9f6812dbd997`, in one
Python environment. `main`'s `engine/zylch` is the tree those units run. The
[plan](../../docs/execution-plans/2026-11-20-main-is-the-hosted-line.md) owns
the per-unit state, the release and each rollback.

A member's own message holds a thread for people until the customer's newest
mail has waited `MEMBER_ACTIVITY_HOLD_HOURS`, 72 by default, with no member
answer after it. Then the thread is the operator's again. The
[assignment contract](features/task-assignment.md) holds the rule.

## Unresolved

- The contextual email guard with its enrollment and the typed Qonto
  credentials wait to be brought onto `main` again. The engine looks the
  guard's modules up with `find_spec`: with them present it applies the guard
  to stores that were never enrolled.
- 26 Qonto cases of the engine's test tree pin a finance-content rule no
  unit runs: a session authenticated as the profile's owner reuses that
  profile's finance content on every unit. No test covers
  `qonto/owner_content.py`.
- The repository's checks on `main` fail: the RPC contract check, and the
  engine test tree, which has cases that fail on every package that ran it.
  `docs/ipc-contract.md` and `docs/rpc-contract-inventory.json` are not
  reconciled with the engine's method registry.
- A Desktop build from this engine is unverified.
- Six hosted units carry drop-ins that sort after `tenant.conf`. The nightly
  reconcile exits 3 and a `tenant.conf` change does not reach them.
- `zylch-reconcile.path` runs the reconcile when the profiles directory
  changes, and `mrcall-tenant create` changes it. With new commits on `main`
  the reconcile then restarts every unit at once, the telephone unit
  included, with no check for a call.
- The seven units log at DEBUG to the journal, mailbox and customer
  addresses included. `checks/journal-address-shapes.txt` in the one-build
  plan's evidence folder lists the line shapes of the two MrCall units.
- The operator kernel lists a held thread among those that wait for a person
  before it checks whether a member answered it, works on two conversations
  per tick, and keeps a contact with a person through its own `escalated`
  record whatever the engine answers.
- A thread stays held without a limit when a member answered last from their
  own mailbox and the customer then wrote only to another account's mailbox.
- An email intake after a long gap is slow. On Café 124 production it took
  177 seconds after two hours without a sync, against 5 to 20 seconds on its
  earlier package and the 180 seconds the operator kernel waits. Each run
  reads the message ids of the last seven days in every folder. With the
  mail loop on, a run takes 6 to 10 seconds there.
- No reply has left on `hosted-engine-0.1.57.dev4`: the first tick on it
  found nothing owed in the two conversations it took.
- Staff units `C06x…` and `YZNI…` log about 230 `reanalyze_task` refusals a
  day: the request exceeds the 200000-token window
  (`llm/budget_pricing.py`). The mailbox of staff unit `ZwpL…` rejects its
  login.
- On the MrCall support profile the assignment projection of three threads
  that carry a waiting draft is `unknown` on the primary account: two with
  `REPLY_SOURCE_UNAVAILABLE`, one of them from `SENT_REPLY_NOT_SYNCED`
  evidence, and one with `SOURCE_UNAVAILABLE`. Each of the 29 operator ticks
  since 2026-11-16 that kept its review lists them, on three engine
  releases. The cause is not established. `rollout/m3-tick-1850.txt` in the
  one-build plan's evidence folder holds the counts.
- Live PEC.net acceptance and provider marker comparison,
  Qonto installed Electron and provider UI remain open in their owning plans.
- Remaining Café124 billing choices and funded credit acceptance remain open;
  do not replay uncertain requests or resume preparation implicitly.
- Mnemonic AC 5/M10, extraction retry observability and reviewed rollout/migration
  rehearsal remain open. A M8-migrated store cannot reopen in a M5–M7 build.
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
3. Re-measure mnemonic AC 5 and review rollout plus migration rehearsal before
   product acceptance. Preserve the rejected corpus evidence.
4. Continue telephone knowledge detail/adverse/latency acceptance from its plan.
5. Resume other workstreams from their existing owners when requested.
