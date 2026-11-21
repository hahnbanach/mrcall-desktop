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

Native [Qonto](features/qonto.md) has authenticated support-only banking,
restart/reconnect, source-comparison and managed-answer acceptance. Packaged
GUI and provider-UI comparison remain unverified. Released source combines
Qonto and [additional mailboxes/PEC](features/mailboxes.md). Six company units
have verified mailbox migration, primary registration, encryption startup and
row preservation; the personal mailbox unit runs the same release. The
[Qonto plan](../../docs/execution-plans/2026-10-04-qonto-connection.md) and
[integration plan](../../docs/execution-plans/2026-10-05-mailboxes-qonto-release-integration.md)
own remaining acceptance and rollout.

The production telephone listener is off: the Café 124 production unit runs
without `--voice-config`, because with it the daemon exits at start while
the voice admission is not ready. Production telephone service uses GPT-Live
and the scoped company-knowledge
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

The hosted daemon runs a mail loop: every `MAIL_SYNC_INTERVAL_MINUTES` it
runs the email-only intake of `sync.run {scope: "email"}` by itself, so an
engine that clients only read keeps its archive current. Its
[plan](../../docs/execution-plans/2026-11-18-engine-owned-mail-sync.md) owns
that evidence.

Seven hosted units run one package: tag `hosted-engine-0.1.57.dev5` on
`main`, release
`/home/mrcalld/releases/hosted-engine-0.1.57.dev5-e1c1af32d0d0`. `main`'s
`engine/zylch` at that tag is the tree they run.

A person's request through the profile's operator MCP is admitted on every
assignment state: `prepare_reply` saves a plain-text draft bound to the
exact source row, with root-first References, and publishes its review copy
in the mailbox's Gmail Drafts inside the same operation; `recover_reply`
finishes an interrupted publication from the operation journal and never
generates; `send_reply` sends one saved draft on the person's explicit
instruction, gated per call on `operator.use`, refused by `operator_action`,
idempotent on its request key, and retires the review copy after the verified
send. Before a new send, a review copy edited in Gmail or a reply to the same
message already sent from Gmail refuses, named. The admission is one
in-process marker (`services/person_request.py`) that the MCP effects set
around a request; under it the draft write, the review write, the exact send
and `resolve()` keep the binding to the source row and compute no projection,
component or ancestry proof. Scheduled ticks and the kernel's RPC routes keep
every refusal. `resolve()` roots an In-Reply-To-only ordinary source at its
stored `thread_id` on every route. This is on `main` after
`hosted-engine-0.1.57.dev5` and not released; the
[plan](../../../docs/execution-plans/2026-11-21-interactive-drafts-through-operator-mcp.md)
in the hb repository owns its release and live acceptance. A member's own message holds a thread
until the customer's newest mail has waited `MEMBER_ACTIVITY_HOLD_HOURS`, 72
by default, with no member answer after it
([assignment contract](features/task-assignment.md)). The
[plan](../../docs/execution-plans/2026-11-20-main-is-the-hosted-line.md) owns
the per-unit state, each rollback and the evidence of the bullets below that
name it.

## Unresolved

- Out of `main`'s tree: the contextual email guard with its enrollment and
  the typed Qonto credentials. Tag `main-before-hosted-line-20261120` holds
  them. With the guard's modules present the engine applies it to stores
  that were never enrolled.
- `main`'s checks fail: the RPC contract check, and the engine test tree,
  whose failing cases include 26 Qonto cases of a finance-content rule no
  unit runs. `docs/ipc-contract.md` is not reconciled with the method
  registry. A Desktop build from this engine is unverified.
- Six units carry drop-ins that sort after `tenant.conf`, so the reconcile
  exits 3. `zylch-reconcile.path` runs the reconcile when the profiles
  directory changes, as `mrcall-tenant create` does: with new commits on
  `main` every unit then restarts at once, with no check for a telephone
  call.
- The seven units log at DEBUG to the journal, addresses included.
- The operator kernel lists a held thread as waiting before it checks for a
  member's answer, works on two conversations per tick, and keeps a contact
  with a person through its own `escalated` record. A thread also stays held
  when a member answered last from their own mailbox and the customer then
  wrote only to another account's mailbox.
- One email intake of the Café 124 production unit took 177 seconds against
  the 180 the operator kernel waits; the cause is not established. The plan
  holds the record.
- No scheduled tick has sent a reply on this release; one left on the
  operator's request on 2026-11-20. The kernel sends no reply whose
  preparation had a refused `create_draft` call, and its draft then stays in
  the engine, which the Desktop app does not list. This release removes one
  cause: the refusal of a References chain folded over lines.
- The MCP route for a person's drafts and sends is unreleased and has no live
  acceptance: no client of this work is connected, the route exists for the
  Café 124 production profile only, and every full delegation already
  approved gains `send_reply` at release. The Drafts inventories it runs read
  the whole folder (1,000 messages, 8 MiB, 2 MiB per message); a folder beyond
  that refuses with the cause named.
- With the telephone listener configured, a voice admission that is not
  ready stops the whole daemon at start, its WebSocket and its MCP listener
  included. The admission of the Café 124 number is not ready since
  2026-11-20 16:39 UTC and its cause is not established; the plan holds the
  record.
- `emails.search` with `folder: sent` keeps only threads whose latest message
  is the user's, unlike Gmail's `in:sent`: a Café 124 subject search over 33
  sent threads returned 4. Superhuman reminders are stored with
  `is_auto_reply = 0`, so they count as written by an outside person.
- Staff units `C06x…` and `YZNI…` log about 230 `reanalyze_task` refusals a
  day (`llm/budget_pricing.py`, the 200000-token window). The mailbox of
  staff unit `ZwpL…` rejects its login.
- On the MrCall support profile the assignment projection of three threads
  that carry a waiting draft is `unknown` on the primary account, on four
  engine releases since 2026-11-16. The cause is not established.
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
