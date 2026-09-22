# Mnemonic decisions and origin-bound paid admission

<!-- doc-scope:start -->
Scope: the decision half of the mnemonic harness — what a memory event is, what
the role may propose, what the validator refuses, and who may pay for the call.
The commit capability, the operation journal and the legacy writer conversions
are not part of this and do not exist yet; the writer inventory they will
convert is [mnemonic-writer-inventory.md](mnemonic-writer-inventory.md).
<!-- doc-scope:end -->

`zylch/memory/mnemonic/` is the semantic write boundary for company memory.
`contracts.py` holds the event side, the vocabularies and the bounds;
`proposals.py` holds the answer side.
Callers submit an event and receive a decision; they never receive a database
writer, a permit factory or a commit function. There is no commit module: a
validated mutation proposal ends as `retryable_failure` with the reason
`commit capability not installed`, carried on `MnemonicDecision.accepted` for
the commit step to consume.

## The event

`contracts.MemoryEvent` is frozen. The authenticated adapter binds the owner,
the company, the caller class, the origin, the source kind/id/revision and the
original observation before any model runs. `with_model_arguments()` is the only
way model output touches an event and it can set nothing but `suggestion` — a
payload carrying `owner_id`, `observation` or `caller_class` changes nothing.

`caller_class` is `verified_human_correction`, `operator_delegated` or
`automatic_observation`. The first is for an actual authenticated human
instruction. Token possession, a callback, `--allow` or a caller-supplied
`human=true` is not evidence of one.

A `SubjectHint` widens retrieval and narrows classification. It never makes its
target authoritative.

## The role

`agent.decide()` authorizes, dispatches, adapts and validates, at most
`MAX_DECISION_ATTEMPTS` (3) rounds, each paying its own ordinary reservation.
A rejected proposal is re-asked with the validator's reasons and the original
observation turn intact; it never falls through to CREATE. Exhaustion is
`review_needed`.

`prompts.MNEMONIC_INSTRUCTIONS` is the complete identity and refusal rule set
and goes into the cached system block whole; the user turn carries only the
event and the candidates. `tests/memory/test_mnemonic_agent.py` locks both
halves, as `tests/workers/test_merge_gate.py` does for the merge gate.

A response is adapted only if `response_validation.complete_memory_text`
accepts it (finished stop reason, text only, no tool call) and
`strict_json_object` accepts its body (exactly one non-empty JSON object, no
trailing prose, at most one code fence). Anything else is no proposal at all.

The role is shown at most `MAX_CANDIDATES` (3) visible blobs, a caller-named
target pinned first and counted inside that bound. It is shown how many
structured identifiers each candidate shares with the observation, and never a
similarity score.

## What the validator refuses

Only rules that are stable, cheap and valuable. It does not decide whether a
conversation implies a changed relationship or how two histories reconcile.

- PERSON/COMPANY need `entity` scope, FACT needs `company`, STYLE needs
  `account`; the envelope, the blob header and the target's namespace family
  must agree.
- An event carrying a structured entity subject cannot be committed as a
  company FACT. Genuinely unbound prose stays the role's classification.
- UPDATE takes exactly one visible target at the exact version it was read at,
  and must keep the subject it started from — the target's stated `Name`/`Key`,
  or, for a legacy row that states neither, the subject the caller's hint
  named. With no anchor at all the update cannot be shown to stay on the same
  subject and is refused; an account rule has no entity subject and is exempt.
  An UPDATE carrying a donor, or an absorbing effect naming a blob other than
  its own target, is refused as a disguised MERGE. That check is structural —
  it compares blob ids — and it says nothing about an UPDATE whose *prose*
  absorbs another entity: that stays the role's judgment, measured by semantic
  evaluation.
- Every entry in `declared_effects` parses as `verb:blob_id` or
  `verb:blob_id->blob_id` with a verb from a closed set, and may name only
  blobs already in the write set. The effects are part of what the proposal
  asks to touch, so they are checked like a write set rather than trusted as a
  note about one.
- MERGE takes one keeper and one donor, both visible at exact versions, with
  the alias/reference effects declared, and needs identity evidence checked
  against the actual inputs. For a PERSON that means a shared email address, or
  a shared identifier plus the same stated name — a shared company or a shared
  switchboard is not evidence that two people are one person.
- CREATE is the mirror of that gate: an entity that corroborates with a visible
  candidate of the same family may not be created a second time. Where the
  evidence is absent — a similar name, a shared company, a shared switchboard —
  nothing fires and the new entity is created.
- Moving a memory between families requires an explicit `reclassification`
  matching the envelope; it is never inferred from an UPDATE's prose. So does
  retyping one inside a family — PERSON and COMPANY share `user:`, so the
  family rule alone would miss it. A target carrying an unsupported legacy type
  (`PROJECT`, `TASK`, `NOTE`, `EVENT`) requires review.
- A target that arrives without a namespace is refused rather than assumed
  harmless: it means the caller did not say where the row lives.
- A proposal may touch only its declared write set, within the size bounds.
- An explicit remember/correct request cannot be answered with a silent SKIP.
  A semantic no-op is valid only when the proposal names the memory that
  already holds it, at its exact visible version, with a reason. Otherwise the
  refusal must be a visible REVIEW.

Legacy rows stay readable. A blob without a header, or a plain rule, is a
usable candidate and target; missing metadata is interpreted from the family at
validation time and never backfilled on read.

## Who pays

Three separate questions. **Request authorization** (`authorize_request`)
refuses a read-only origin and a cross-account submission before a grant
exists, so a refusal costs zero reservations and zero provider calls. **Paid
admission** is the `DispatchGrant`. **Commit approval** is neither and does not
exist yet.

The authority is the dispatch scope, not the usage label. `call_site` tags stay
what they were — diagnostics for spend attribution — and a call relabelled
`chat` or left untagged inside a mnemonic dispatch is checked identically,
because `check_dispatch` reads the grant, not the tag.

A grant is bound to owner, company, event, source revision, origin and a shared
cancellation handle, and is verified by object identity against the issuing
registry, so a value-identical copy is refused. `issue_grant` performs the
request authorization itself, so a grant cannot exist without it.

At each dispatch the grant is re-checked against the process: a changed acting
account, or a profile that has since joined another company memory, refuses it.
A process that cannot name the account it is acting as refuses outright.

The allowance is `EVENT_DISPATCH_ALLOWANCE` — one bounded extraction plus the
three decision rounds — and it belongs to the **event**, not to the grant, so
re-issuing for the same event continues from what is left. It is spent at the
provider, not at the admission check, so a call the budget or preparation
refuses afterwards costs the event nothing. A revocation between the
reservation and the dispatch gives the hold back on the unmetered transports;
on MrCall credits the reservation is receipt-gated by design and stands until
the in-flight horizon resolves it.

That ledger is a bounded, in-process table: the guarantee holds for its most
recent 1024 events, and eviction prefers entries that have spent nothing.
Beyond that bound, and across a restart, what makes it durable is the operation
journal — which does not exist yet.

- **Interactive** grants ride the caller's own turn. They leave bounded
  preparation untouched: its pause, its busy flag, its batch allowance and its
  per-source retry state are the same before and after. Company fencing,
  cancellation and the shared daily dollar budget still apply.
- **Automatic** grants must match the admitted preparation item — same stage,
  same source, and an item that was genuinely admitted to a run — and then face
  every ordinary preparation check on top. No admitted item means no paid
  dispatch.

`origin` is set by the adapter, so the interactive contract has a structural
guard: inside an admitted preparation item the only contract available is the
automatic one, whatever the event calls itself. That guard reaches exactly as
far as `bounded_item` does — the engine's synchronous job paths
(`services/job_executor.py`) set no item context and are not covered by it.
They are unconverted legacy writers listed for milestone 6; until they are
converted, nothing routes them through here at all.

`llm/client.py` refuses `tools`/`tool_choice` inside a mnemonic dispatch scope:
the role returns a proposal, so it never receives a write tool.

## Results

One result type, four outcomes: `committed`, `skipped`, `review_needed`,
`retryable_failure`. Only a committed result names committed ids; every other
outcome must carry a reason. Non-semantic follow-up work is listed in
`pending_effects` rather than demoting a real commit to a failure. Automatic
workers advance a processed checkpoint only on `committed` or a deliberate
`skipped`.

## Tests

`tests/memory/test_mnemonic_contracts.py`, `test_mnemonic_validator.py`,
`test_mnemonic_agent.py` and `tests/llm/test_mnemonic_admission.py`. The
validator and agent tests replay the frozen milestone 0 incident corpus
(`tests/fixtures/mnemonic/incidents.json`) through the deterministic decisions
in `tests/fixtures/mnemonic/decisions.json`. Budget, truncation and admission
tests run the real `LLMClient` and the real reservation ledger with only the
provider transport replaced.
