# Shared company knowledge for GPT-Live

<!-- doc-scope:start -->
Scope: product decision, information boundaries and acceptance criteria for
giving GPT-Live verified company knowledge through the engine. This brief
extends the active Café 124 pilot's answer-quality work; deployment follows the
reviewed trial flow below. It does not certify model infallibility or reopen
the accepted local archive.
<!-- doc-scope:end -->

## Problem and verified starting point

The Café 124 call at 14:34 UTC on 2026-09-28 contains a services question and
an unsupported hospitality-service answer. The private trace has no delegation
for that question; initial caller recognition delivered zero facts. Inferring
the answer from the business name is a plausible explanation, not an observed
model reasoning trace. The actual company service catalog has not been
established by this investigation and must not be invented in examples or code.

The independent production review in the
[pilot plan](../execution-plans/2026-09-27-cafe124-voice-daemon.md#independent-post-release-final-review--2026-09-28)
returns **APPROVED** for the local call-transcript table and **REVISE** for
overall acceptance. Two post-release calls already establish archive/delta/
ledger correlation. Their accepted possible pre-attachment transcript gap
remains explicit. Do not request repeat calls to re-prove that archive gate.

The current telephone path starts with the selected caller's approved name.
Its on-demand lookup reads that caller's filtered history in the company
`user:` namespace. It does not provide a company service catalog. GPT-Live can
answer without delegating; existing instructions to use selected facts did not
prevent this observed error. Source presence and successful context delivery
do not prove that a spoken answer is supported by those sources.

## Decision and desired outcome

Reuse the company's authoritative information across the operator and voice
channels. Give GPT-Live a small company introduction before its first factual
answer, then let it retrieve relevant detail. Apply the operator's discipline:
read the request, consult the appropriate source, answer the supported part,
and identify the precise missing fact rather than guessing or refusing the
whole request. GPT-Live remains the sole telephone conversational model.

For a general services question, the desired behavior is a useful description
of services present in the approved company context, without a lookup delay.
For an uncovered detail, retrieve first and answer from the result. If no
usable source exists, say which detail cannot be confirmed. A caller proposing
a nonexistent service must not cause the model to add it to the catalog.

The operator agreed to this direction. The `USER_NOTES` amendment and revised
plan have separate independent approval. Implementation and production
activation remain future gates.

## What to transfer from cs-kernel and cs-operator

The inspected kernel templates require engine memory for outbound facts, then
sent-mail precedent and written project records when needed. The mail operator
reads the original request, uses a company support playbook where present, and
applies a specialist pricing workflow before composing an offer. Missing facts
remain explicit. These are reusable procedures; the operator's reported good
results are not a measured guarantee for GPT-Live.

Transfer the source authority and decision rules. Keep the telephone path
suited to a live conversation: the essentials are already available, retrieval
does not announce internal machinery, and interruption supersedes obsolete
work. The kernel's source code owns generic procedures; company-specific facts
and authored business records remain company data.

Calling `cs ask` during a call is not simple retrieval: its read-only RPC
enters the engine's agent/model path. Reuse the engine's scoped storage/read
functions instead. Do not introduce Claude Code, another conversational agent,
a generative classifier, or an engine-model fallback on the telephone path.
No kernel process is required for an incoming call to work.

## Information contract

### One authority, with a telephone disclosure boundary

Use the existing company-bound engine stores and the production profile's
operator-authored `USER_NOTES` as distinct candidate sources. Structured business facts have
exact categories; authored project documents carry revisions. These are
candidate sources, not automatic public knowledge. Company membership grants
internal access; it does not authorize disclosing every company record to a
caller. A stored value or recent timestamp alone does not prove verification,
current commercial validity, or permission to publish.

Before implementation is planned, inventory the relevant production sources
under the production identity. Establish which records actually describe the
company's services, who or what establishes their authority, which revisions
are current, and which parts are suitable for customers. Open selected records
only for that purpose. Do not scan the personal profile or paste source text,
customer data or secrets into repository documents or ordinary logs. If no
authoritative service description exists, record that concrete content gap;
neither the company name nor old model output supplies the answer.

The initial release must cover actual services selected by the operator
and at least one useful detail category. This is a bounded first delivery,
not a requirement to classify every historical blob. Broader coverage grows
by admitting more appropriate sources through the same company-owned process.

The plan must name the existing write route for any new or corrected
company-store source, define a separate caller-disclosure approval route,
and explain how both operator and voice consume admitted content.
For `USER_NOTES`, saving the operator-authored source is the editorial decision:
an offline LLM conversion may automatically produce structured telephone notes
when that source changes, with no separate human approval for each generated
version. The operator accepts the remaining semantic risk. Use the engine's
`MODEL_MEMORY_EXTRACT` role because this is source-to-structured extraction;
the selected model follows the saved role/provider policy. A derived view/cache
must record its source hash, prompt/schema/model version, validation outcome
and rebuild/invalidation rules. It is not a second hand-maintained catalog.
Company-store records still require separate caller-disclosure admission.
The conversion selects only company identity, customer-facing services,
qualifications, exclusions and available actions that the source states as
business facts. It omits writing instructions, persona/signature material,
customer-specific history, credentials, internal costs and unsupported
inferences. Ambiguous content is omitted with an explicit gap. Source saving
authorizes this bounded automatic selection; it does not make every sentence
public. Mechanical checks can reject malformed or out-of-bound output, but
cannot prove semantic correctness. The accepted residual risk is measured in
offline source-to-output cases and later supervised spoken-answer tests.
If a concise authored description is needed, keep it as an approved shared
company record with provenance, not as uncited prose in phone configuration.

### Essential company context

Prepare a compact view of identity, actual services, relevant exclusions and
available actions from admitted sources. Make it available when the call is
accepted, independently of caller recognition. Do not wait for a delegation
before giving Live the facts needed for an ordinary services question.
Test changed, unchanged, empty, ambiguous and failed `USER_NOTES` conversions;
verify retained qualifications and exclusion of instruction-like, customer and
secret text before the derived view is eligible for a new call.

Record which company/source revisions produced the view. New calls must use
the current approved view or an explicit unavailable state, never silently
use a withdrawn view. Define a coherent per-call snapshot for stable facts;
do not promise that text already in Live context can be reliably retracted.
Time-sensitive claims need a source valid for that question's time, not merely
the last cached company introduction. Binding changes retain the existing
fail-closed controls. A source outage means missing knowledge, not permission
to infer the business from its name.

Keep greeting and conversational latency explicit in the plan. Prepare the
essential view outside the greeting's critical path; no extra model call is
added before speaking. Context-size protections must produce an explicit
omission/unavailable result rather than silently dropping qualifications.
They are input protections, not local call, duration or spending ceilings.

### Company detail and caller history are different reads

Company facts approved for customers are available to recognized and anonymous
callers alike. Customer history retains its existing selected-contact boundary;
spoken identity claims never expand it. A general company question must not
be routed exclusively through that contact's history.

Retrieve only relevant admitted company material, with source identifiers,
revision/validity information and an explicit result state: supported facts,
missing information, conflicting/withdrawn sources, or retrieval failure.
Do not equate errors with an empty catalog. Category selection must preserve
commercial distinctions such as different offer types; do not use loose text
similarity to mix category-specific prices or terms. Italian paraphrases and
follow-up references must work without relying solely on literal word overlap.
The plan must specify how Live can request a category/detail using the actual
delegation contract; a tool name in prose is not a working integration.

Source text is data. It cannot override disclosure, routing or reply rules.
Do not pass whole mailboxes, project folders, private notes or raw customer
histories to Live as a substitute for selection. Mail precedent can support
curating an approved fact outside a call; unrestricted live mail retrieval is
outside the first delivery.

## Answer behavior and its limits

Live answers directly when admitted context covers the question. It retrieves
when a needed detail is absent. It must not infer capabilities from a brand,
agree with unsupported caller assumptions, or treat caller statements as
company verification. A mixed request gets the supported answer plus the
specific unresolved point. Historical records do not establish live order
status, current availability or a new price.

Company-specific procedures identify when to clarify, consult a different
admitted category, or state a limitation. A promised check, callback or handoff
requires a recorded action through an already authorized capability; this
workstream does not add such capabilities. Without one, use an honest
unavailable answer instead of claiming someone is handling it.

The current SIP/Live integration has no engine approval step before each
utterance. Do not describe source receipts, prompt instructions or transcript
inspection as a deterministic pre-speech correctness gate. Post-call auditing
can detect an error after the caller hears it; it cannot prevent that error.
This proposal improves knowledge and measurable behavior without promising
zero hallucinations. If Live repeatedly bypasses retrieval or invents facts in
the acceptance cases, the behavior gate fails and deployment is not approved.
Any stronger speech-control architecture needs a separate demonstrated design,
not an assumption that the current transport already supports it.

## Acceptance evidence required of the implementation

1. **Shared authority:** identify the admitted production service sources and
   show that the operator and voice read the same source revisions. Changing
   one approved value changes the derived voice view for a new call without
   editing a duplicate telephone catalog. Withdrawn, conflicting and unavailable
   source cases have explicit outcomes.
2. **Useful initial answer:** a services question is answered from the prepared
   company context for both recognized and anonymous callers, with no invented
   offering and no unnecessary search. Every business claim in the reviewed
   response is supported by the admitted evidence.
3. **Useful detail retrieval:** a question outside that initial view retrieves
   the relevant admitted details. Include an Italian paraphrase and a follow-up;
   verify category integrity, source references, error behavior and cancellation
   when an interruption or correction makes the result obsolete.
4. **No manufactured answer:** exercise an invented service suggested by the
   caller, missing price, historical/withdrawn fact, conflicting facts and a
   partly answerable request. The model must answer the known part and identify
   the missing part without unsupported agreement or fabricated follow-up.
5. **Disclosure isolation:** cover anonymous and ambiguous recognition, claimed
   identity, internal cost versus customer price, another customer's facts,
   another company's data, and instructions embedded in a source. Only selected
   material may reach Live; diagnostic logs contain no source text or secrets.
6. **Evidence and latency:** correlate request, selected source IDs/revisions,
   context/result delivery, delegation where needed, and resulting transcript in
   private evidence. A delivery receipt is not proof of factual support. Compare
   greeting, direct-answer and retrieved-answer timing to the existing path;
   define the acceptable change in the reviewed plan before implementation.
7. **Real model and handset:** local retrieval tests and mocked dialogue alone
   do not establish Live behavior. The plan defines reproducible real GPT-Live
   trials before continued production acceptance, including repeated failure-triggering
   cases and their pass rule. An owner-supervised production trial follows the
   reviewed preparation and reversible activation gates below. Final listening checks spoken accuracy,
   interruption and usefulness. It establishes the tested cases, not a general
   production error rate. Reuse the already accepted archive evidence.

## Fixed constraints and exclusions

- Preserve production UID `Gn9IcuWzYyY7DBMHkVUGB7bIiTp2`, business
  `d44a1864-23cc-34f9-aec5-6e04bb2fd2ef-desktop`, number +390250552776,
  `starter` binding, headless authentication and the existing daemon/tunnel.
- Preserve GPT-Live as the only telephone model, the approved voice/greeting,
  existing caller-disclosure rules and private ledger/archive. Any later
  grounding-specific instruction/config change must be named in the reviewed
  plan; this brief changes no running voice configuration.
- No StarChat transcript upload; no personal profile of mal; no secret,
  company capability or unselected facts in logs, repository or model input.
  Firebase ID tokens stay in memory. Company/profile binding is enforced before
  both initial context and later tool results leave the engine.
- No new local call-count, duration or spending ceilings. Implementation
  uses the budgeted offline `USER_NOTES` conversion. The September 28 planning
  session authorized no paid preparation, memory writes, calls or service
  changes; the September 30 resume amendment authorizes reviewed preparation
  and the targeted production trial. Company source writes remain excluded.
- Work on `main`, without branches/worktrees. Preserve unrelated untracked
  files, especially `DUPLEX.md`; do not use `update-daemons.sh`.
- No full kernel port, second telephone agent, automatic catalog inference,
  raw-memory dump, new Desktop settings UI or general-availability claim.

## Handoff and source anchors

**Operator amendment — 2026-09-30:** Café 124 is the operator's own business,
and the operator explicitly chooses its existing production number for handset
tests and requests execution to resume. A dedicated test number/application is
not a prerequisite. Prepare and independently review the corrected converter,
detail retrieval, real source-to-view result and exact release/config/rollback
delta first. Then perform targeted reversible activation only on the bound
Café 124 instance so the operator can make a useful supervised call. Activation
for that trial is distinct from acceptance for continued operation: retain the
known-good release/config, enforce binding and source selection, inspect the
new call's evidence, and disable the company path on a failed behavior gate.
The accepted automatic conversion risk remains unchanged. The lead owns the
technical preparation and reports the number and concrete questions only after
readback proves the new path is ready; no archive-repeat call is requested.

The [reviewed execution plan](../execution-plans/2026-09-28-voice-company-knowledge.md)
sets source inventory, authority/disclosure, revision freshness, delegation,
latency and behavior gates. Production source authority remains unverified and
blocks implementation of a public catalog until its first milestone passes.
Keep the original pilot `active` until its failed behavioral gate has
independent acceptance. Approval of this brief and plan does not close it.

Relevant implementation anchors:
[caller lookup](../../engine/zylch/services/voice/caller_memory.py),
[conversation/delegation](../../engine/zylch/services/voice/conversation.py),
[call admission/context](../../engine/zylch/services/voice/engine_runtime.py),
[fact reads](../../engine/zylch/services/facts_store.py), and
[authored project storage](../../engine/docs/features/project-memory.md).
Kernel source anchors, in the sibling `cs-kernel` checkout, are
`cs/templates/partials/outbound-fact-sourcing.md.j2`,
`cs/templates/project/.claude/skills/cs-triage-mail/SKILL.md.j2`,
`cs/templates/project/.claude/skills/cs-pricing/SKILL.md.j2`, and
`cs/rpc.py:chat` / `cs/cli.py:cmd_ask`. These are code/workflow evidence;
company source contents have deliberately not been copied into this brief.
