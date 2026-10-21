---
date: 2026-10-16
kind: execution-plan
task: m10-poststripe-preservation-20261016
status: active
brief: ../briefs/2026-10-16-m10-poststripe-preservation.md
owner: M10 release lead
---
# Preserve post-Stripe behavior in the M10 artifact

## Classification and boundary

Substantial development: this composes existing RPC, credential, IMAP and
assignment behavior into a different installed artifact. It is not fast-path
work. There are two local milestones, with a fresh source integration review
before artifact work and a separate final review after documentation closure.
Neither milestone authorizes a hosted switch, paid inference or a customer send.

The approved brief SHA-256 is
`565d5f3114d468539011ce04e8d71e64e00f4c37eba6383e1953b9e6490b0a5c`.
Work only in `/home/mal/worktrees/mrcall-desktop-m10-poststripe`, based on
`652c00079e8a59770bd242a7a63fa3529ff17703`. The parallel paid-budget helper,
original working trees, live installations, profile/company stores, service
configuration and three retained clone locks are outside implementation scope.
Billing source 01909353 and its separate release remain independently owned.

Evidence root: `/home/mal/worktrees/.evidence/m10-execution-20261016/`.
`post-stripe-runtime/` contains the immutable current production and Mario
packages, per-file manifests, identity descriptors and complete V8 delta diffs.
`post-stripe-plan/support-facts.json` records the planning checks. Before edits,
bind the approved brief, plan, these manifests and the prior disposition by hash.

## Observed inputs and proof reuse

The two frozen inputs contain 355 and 341 Python modules and four resources each.
All 704 frozen files were independently hash-checked during planning. Relative
to their effective V8 inputs, each has seven new Stripe modules and four changed
paths, with no deletions. Their shared variants remain eight paths; fourteen
modules exist only in production. Do not treat absent runtime paths as a request
to delete M10 modules. The checkout's 369 modules exactly match the prior final
source manifest.

Reuse `/home/mal/worktrees/.evidence/m10-current-runtime-20261016/M1/` source
disposition and prior immutable reports only after recording current equality of
their relevant source, fixtures and dependencies. Extend every existing row with
the two current input hashes and successor output hash; do not replace the old
semantic account with a claim that the new four-path patch is the whole runtime.
The expected successor has 376 modules if no further justified source is needed.
Derive and verify counts from manifests rather than hardcoding old 369 assertions.

Planning ran the actual isolated source tests
`tests/assignments/test_projection_observation.py`,
`tests/assignments/test_current_runtime_composition.py` and
`tests/email/test_imap_uid_scan.py`: 53 passed, 0 skipped, 233 warnings in 23.81s.
This is a base check, not proof of the unimplemented successor. The checkout has
no Stripe tests; add bounded native coverage rather than claim inherited tests.
Unchanged unrelated portions of the prior 746-case selection need no full rerun.

## M1 — Source composition and authority regressions

**Owner:** one execute worker owns `engine/zylch/stripe/*.py`,
`engine/zylch/rpc/stripe.py`, the four changed Python paths below, and narrowly
affected Stripe/assignment/IMAP tests. The lead owns evidence and the evaluation
`docs/evaluations/2026-10-16-m10-poststripe-source.md`. A fresh reviewer independently
judges the resulting source and authority evidence. Do not delegate overlapping
source edits. M2 depends on this review being APPROVED.

1. Preserve the seven identical frozen Stripe modules without adding features.
   In `rpc/dispatch.py`, compose parameter redaction and safe Stripe errors with
   current M10 refusal handling. In `rpc/methods.py`, add the existing nine Stripe
   methods, duplicate-registration refusal and `stripe:1` discovery while keeping
   all M10 and operator capabilities and admission checks.
2. In `email/imap_client.py`, compose the existing request-owned projection
   connection with the M10 send/context guards and deadline lock. In
   `services/task_assignment_evidence.py`, retain borrowed protocol reuse, the
   standalone no-reuse path and malformed Sent target re-observation. Preserve
   actor/root/deadline/mailbox fencing and teardown; never substitute stale
   positive evidence for a failed or incomplete observation.
3. Produce the complete successor disposition: both runtime variants, original
   M10 modules, resources and each changed function's retained behavior. Carry
   forward the prior eight-variant/fourteen-exclusive decisions by verified hash.
   No company-name or UID branch may select behavior. If a conflict lacks an
   existing contract, stop that path and give the lead its concrete alternatives.
4. Account explicitly for all four current resources. The shared classifier
   prompt remains packaged. The two SQL files and `email_triage.txt` currently
   have no filename references in the candidate or either frozen Python tree;
   prove their actual loading disposition, including dynamic loaders. Package
   each used resource or justify exclusion as obsolete/unreachable with source
   evidence; resource counts alone do not establish preservation. All three are
   already within this brief. The six M10 role resources remain required. Any
   unrelated resource or dependency expansion returns to scoped review. Never
   execute migrations or backlogs against live stores; use copied fixtures only.

**Verification:** run the native RPC dispatcher against disposable local stores
and scripted HTTP transport. Check discovery and all nine registrations; missing
or expired session, foreign profile/company/host, joining company, stale or reused
challenge, absent consent, changed key/account/generation and disconnect during
an in-flight read must refuse. Check encrypted private-file roundtrip, secret
redaction in logs/errors, fixed-host GET-only transport, blocked write/unknown
methods, bounded pages and malformed identifiers/responses. Connect/disconnect
may write only synthetic profile files. Assert no outbound Stripe call or payment.

Run the three 53-case base files above plus new focused tests. Exercise the real
IMAP client with scripted connection objects: one connection per projection,
no repeated health probe inside reuse, fresh standalone scopes, mismatched
thread/deadline/nested scope refusal, lost/replaced connection refusal, timed-out
read, provider/cleanup failure and cleared scope/timer/connection state. Update
test clients to implement the protocol rather than bypassing the new guard.
Retain UNKNOWN and automatic-reply hold on incomplete proof.

Re-run affected existing contextual email, exact draft, read-only and cancellation
cases: `tests/assignments/test_contextual_chat.py`,
`test_draft_binding_races.py`, `test_scheduled_reply_origin.py`,
`test_current_runtime_composition.py`, `tests/rpc/test_exact_drafts.py`,
`test_memory_readonly.py`, `test_ws_cancels_inflight.py` and
`tests/operator_mcp/test_read_contract.py` where changed imports exercise them.
Test SMTP/HTTP effects use scripted adapters only. Record command, private
environment, source/import hashes, complete logs, JUnit totals and actual skips.
Use the retained network guard and no real credentials. Run focused syntax/style
and diff checks. A fresh review must also exercise independent negative authority
cases; a report that only repeats worker assertions does not close M1.

**Completion:** exact successor manifest and delta, all current input dispositions,
actual passing affected checks and separate M1 approval are retained together.
Any repair invalidates the affected evidence and returns to the same reviewer.

## M2 — New installed artifact, copied data and documentation

**Owner:** the lead owns packaging identity, new private environment, installed
proof drivers, copied stores, engine/server proof and documentation. One bounded
execute worker may own private proof tooling if its isolation saves coordination.
The existing retained environment and wheel remain immutable because the parallel
budget task uses them. The server is a test dependency only; no source edit or
deployment is included.

1. After M1 approval, create one new wheel with explicit local candidate version
   `0.1.52+poststripe.20261016.1`, dedicated output path and SHA-256. This is not a
   published release number. Bind build inputs and reviewed packaging declaration;
   assert every packaged Python/resource byte equals the approved source manifest.
   Do not re-label, overwrite or overlay the old wheel.
2. Preserve each selected profile's actual dependency environment separately.
   Fresh original-interpreter captures under `post-stripe-dependency-inputs/`
   find93 production and75 Mario distributions. Production uses Anthropic1.8.0,
   OpenAI3.19.0, SQLAlchemy2.1.1, cryptography50.0.1 and existing MCP1.30.0/
   Uvicorn0.54.0; Mario uses Anthropic0.105.2, OpenAI2.41.0, SQLAlchemy2.0.50,
   cryptography48.0.0 and no optional MCP server. The earlier retained M10
   environment uses different versions and is not dependency-preservation proof.
   Keep its environment immutable for the parallel budget-helper task.

   Build two separate private venv shells with the captured Python3.12 binary.
   Copy original installed dependency packages/metadata without hardlinking or
   changing live trees; exclude the old engine package/metadata/editable loaders.
   Bind complete per-profile dependency byte/version manifests, audit .pth and
   module origins, and install only the new engine wheel offline with --no-deps.
   No product import may resolve to an older source checkout. Retain the exact
   approved cs.operator_read contract for production's existing optional MCP;
   do not enable optional services on Mario. This changes no dependency graph.
   Record any separately isolated test-only harness additions and prove they
   do not replace runtime packages. Keep deployment locks distinct from tooling.

   Current source venv sizes are634/571MiB; measure free space before copying
   and run large copied stores sequentially. Never delete other owners' data.
   Equal Python hashes establish neither venv dependencies nor loaded origins.
   Exercise native SDK/request/receipt/read-only behavior in BOTH new environments,
   production additionally retaining voice/MCP startup boundaries. An actual
   incompatibility stops the affected proof and returns to reviewed scope;
   no silent dependency upgrade or use of the old test prefix as a substitute.
3. Install offline with exact wheel/hash and run `pip check` in each environment.
   Preserve the exact original check alongside the candidate result. The current
   production environment already reports that cs-kernel0.51.0 lacks firebase-admin,
   google-auth and jinja2; Mario's original check passes. Do not install packages,
   delete distribution metadata or relabel the production result green to hide
   this inherited defect. A qualified preservation result may retain ONLY these
   identical original findings after byte/version/origin equality and actual
   production voice/MCP/read-contract paths prove that their imports and behavior
   remain operational. Independently review that qualification before accepting
   M2. Any additional missing/conflicting dependency or affected runtime failure
   still stops the affected proof. Full cs-kernel installation health is not
   established by this engine-only artifact, and the outstanding defect remains
   explicit in deployment evidence and current docs.

   From outside every
   source tree, invoke each new interpreter with `-I -B`, no source PYTHONPATH and
   private HOME/profile paths. Verify CLI/serve options, native RPC discovery and
   the M1 Stripe discovery/refusal journey from installed imports. Record every
   loaded zylch/read-contract module path and hash. Exercise actual Unix/listener,
   Firebase/session refusal and production-enabled MCP/voice startup boundaries
   with synthetic protected configuration and scripted effects; keep Mario's
   optional features disabled as captured.
4. Assert installed source/wheel parity and real loaders for all seven required
   JSON/schema/prompt assets and any used current resource identified in M1.
   Invoke the resolver/schema/prompt readers and affected current loader so that
   checking archive membership alone cannot pass. Review any actual distribution
   metadata difference. Preserve the same read-contract hash and relevant runtime
   dependency versions unless separately reviewed.
5. Reuse protected snapshot inputs by hash, not previously mutated copies. For
   each profile, boot the new installed candidate cold and warm, then reopen with
   that profile's complete frozen post-Stripe reader. Adapt the old copied-data
   harness to these roots and new artifact identity; do not keep its V8 label or
   hardcoded 369 assertions. Check every original table/column/row, enrollment
   provenance, Qonto and relevant credential metadata, and stable warm/reopen
   snapshots. Preserve encrypted Stripe file bytes using an authorized protected
   copy if available; otherwise prove synthetic encrypted-file compatibility and
   name the missing live-file coverage. Never copy plaintext capability values
   into logs or use a live profile as the fixture. Retain lossless archives with
   verified streaming hash/size before deleting only owned expanded test copies.
6. Re-run the installed engine-to-real billing FastAPI/disposable PostgreSQL
   receipt journeys using the new wheel and the reviewed server source. Reuse
   unchanged scripted provider adapters and existing fixtures by hash. Include
   K3, GLM and Sonnet normal/lost-response continuations; require receipt-only
   recovery without duplicate inference/debit and preserve full billed markup.
   These scripted checks establish transport/accounting behavior, not real funding.

**Documentation and review:** publish actual M2 evidence in
`docs/evaluations/2026-10-16-m10-poststripe-artifact.md`; reconcile root/engine
indexes, living contexts and affected model-selection/operator-runtime contracts.
Document the existing Stripe surface where coverage is missing without expanding
the product. Preserve historical narrative in archives. Record the shared unit
template change and new v9 drop-ins as protected current state; never restore
older templates because this local artifact passes. Mechanical completion checks,
explicit doc-critic over affected and unchanged contracts and active-context shape,
and a fresh M2 review precede the separate final review. Advance the applicable
local baseline only after that final approval; record no live gate as completed.

**Completion:** one hash-bound installed artifact, both-profile copy/reopen proof,
affected installed RPC/receipt evidence, reconciled docs and final approval. Failed
or unavailable required proof leaves the affected milestone open.

## Remaining live obligations and rollback

This plan establishes a locally reviewed successor that preserves the captured
runtime behavior. It does not establish running-process cached-module identity,
live Stripe access, paid direct/credit settlement, twenty independent ordinary
source-grounded company answers, successful ordinary operations, both-clone
acceptance or a successful hosted rollout. The last ordinary batch remains failed.
The separate additional USD 5 guard and its approvals remain a prerequisite to
paid acceptance; old unknown reservations are preserved, not forgiven or counted
as newly established charges.

Before any later authorized per-unit canary, refresh both services' exact source,
interpreter/dependency/argv and protected configuration descriptors. Changed bytes
reopen the affected disposition and checks. Keep provider/model policy unchanged.
Require current whole-package backups, quiescent ownership, effective unit/drop-in
capture and verified rollback before switching a service. Do not rewrite memory,
extract/reconsolidate data, start a backlog, release locks or publish merely to
complete this local plan. The lead owns the later acceptance/release gate ledger.

Local rollback discards only this checkout's unaccepted changes and private owned
candidate environment after retaining evidence; it never changes live state.
Every prior wheel/report remains historical proof for its own exact bytes.
