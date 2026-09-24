# Mnemonic decisions and origin-bound paid admission

<!-- doc-scope:start -->
Scope: the decision half of the mnemonic harness — what a memory event is, what
the role may propose, what the validator refuses, and who may pay for the call.
The commit, the operation journal, retention and the tool adapters are
[mnemonic-commit.md](mnemonic-commit.md); the writers still writing directly
are [mnemonic-writer-inventory.md](mnemonic-writer-inventory.md).
<!-- doc-scope:end -->

`zylch/memory/mnemonic/` is the semantic write boundary for company memory.
`contracts.py` holds the event side, the vocabularies and the bounds;
`proposals.py` holds the answer side.
Callers submit an event and receive a decision; they never receive a database
writer, a permit factory or a commit function.

`agent.decide()` stops at the decision and never writes. An accepted mutation
proposal comes back with **no result of its own** — `MnemonicDecision.result`
is `None` exactly when `accepted` is true — because deciding is not an outcome
and only `commit.py` can say what happened to the memory. A SKIP, a REVIEW or a
failed round does carry a result, since for those nothing further will happen.

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
target authoritative. Its `identifiers` are `(kind, value)` pairs in the
identity index's canonical form — an email lowercased as written, a phone
canonical, a lid as parsed — and they are the hint's identity; a `name` or a
`company` is a retrieval token (`candidates.retrieval_query` drives the search
with it) and never evidence. A FACT hint carries at most the exact row it pins
(`target_blob_id`); any other populated field makes `names_entity_subject`
true, which forbids a company FACT.

Whether an observation may be read for identity at all is
`candidates.mines_observation`: only an interactive event from a mined source
kind (`chat`, `cli`, `rpc`, `task`, `task_instruction`) whose hint states no
identity. An automatic event's observation is a whole channel message, and a
correction's is the drafted and sent texts with their recipients — envelopes,
never mined, so a sender or a recipient can never select a candidate for an
entity that is not them. The index is asked in its own form
(`identity_pairs_of`): an address as written and lowercased, dots kept.

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
  against the actual inputs (`mnemonic/evidence.py`). For a PERSON that means a
  shared email address, or a shared phone or lid plus the same stated name — a
  shared company or a shared switchboard is not evidence that two people are
  one person. For a COMPANY or a FACT the shared retrieval tokens, names
  included, are the evidence.
- CREATE is the mirror of that gate: an entity that corroborates with a visible
  candidate of the same family may not be created a second time. Where the
  evidence is absent — a similar name, a shared company, a shared switchboard —
  nothing fires and the new entity is created.
- An automatic observation cannot propose a STYLE rule: a channel message is
  not one account's instruction about how to write.
- A REVIEW may name `ineligible` FACT candidates — ids it was shown whose text
  is one customer's knowledge rather than the company's — and only ids it was
  shown. The commit records them as read `restrictions` on the operation and
  bumps the store's mutation sequence in the same transaction;
  `memory/eligibility.py` then excludes those rows, and every facts-family row
  whose own header states an entity scope or type, from category reads,
  counts, `get_facts_by_category` and hybrid search before ranking.
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
admission** is the `DispatchGrant`. **Commit authority** is neither: `commit.py`
re-checks authorization under the company write lock and refuses without a
`CommitPermit`. A proposal that changed the action, subject, scope or
destructive effects the caller asked for is written, and the difference is
recorded with the operation ([the departure](mnemonic-commit.md#the-departure)).

The authority is the dispatch scope, not the usage label. `call_site` tags stay
what they were — diagnostics for spend attribution — and a call relabelled
`chat` or left untagged inside a mnemonic dispatch is checked identically,
because `check_dispatch` reads the grant, not the tag.

A grant is bound to owner, company, event, source revision, origin and a shared
cancellation handle, and is verified by object identity against the issuing
registry, so a value-identical copy is refused. `issue_grant` performs the
request authorization itself, so a grant cannot exist without it.

That handle has an owner outside the event: `mnemonic/turn.py` holds one per
turn, and the adapters build their events with it, so revoking the turn revokes
every decision it raised. The drivers that own a turn — `chat.send` and
`tasks.solve` — open it and revoke on cancellation, which is what reaches a
grant a worker thread already holds by reference. Without that owner the handle
was unreachable and a cancelled turn left its decision running.

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

That in-process table is a **cache** over the operation journal's `allowance`
column: a grant reads what is left from the journal, and every dispatch
decrements it there before the request goes out, so a restart resumes the event
instead of handing it a fresh budget. For an event with no operation row — a
decision taken outside a commit-capable path — the cache is the only bound
there is, and it holds for its most recent 1024 events, evicting entries that
have spent nothing first.

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
automatic one, whatever the event calls itself. The paths that reach it:

- the channel workers and the pipeline admit each source as a `bounded_item`,
  and every child of it dispatches under that item's stage and source;
- the background memory job runs the same worker coroutine per item inside one
  `preparation_run` and one `revocable_turn`, on a thread that carries the
  job's context, so its grants are the same automatic grants;
- a helper writer takes its contract from where it is called
  (`mnemonic/entry.py`): automatic inside an admitted item, refused inside a
  run with no admitted item, interactive on the turn otherwise;
- correction learning is interactive on the solve turn that produced the send,
  so a preparation pause does not stop it and the daily budget is its bound;
  `/memory store` is interactive on the chat turn with `explicit_request` set.

An UPDATE whose *prose* absorbs another entity remains the role's judgment,
measured by semantic evaluation rather than by the validator; the structural
disguised-MERGE check above compares blob ids and says nothing about wording.

`llm/client.py` refuses `tools`/`tool_choice` inside a mnemonic dispatch scope:
the role returns a proposal, so it never receives a write tool.

## Results

One result type, four outcomes: `committed`, `skipped`, `review_needed`,
`retryable_failure`, produced by `commit.submit`. Only a committed result names
committed ids; every other outcome must carry a reason. Non-semantic follow-up work is listed in
`pending_effects` rather than demoting a real commit to a failure. A
`retryable_failure` met at a refused dispatch carries the refusal itself
(`refusal`), so an ingestion loop can stop its batch on the exception class
preparation raised. Ingestion aggregates its children into one `Ingestion`
outcome ([children of a source](mnemonic-commit.md#children-of-a-source)): a
source's checkpoint advances only when every child is committed or
deliberately skipped, an empty valid extraction is an explicit skip, a review
parks the source visibly, and a failed child keeps its retry evidence.

## Tests

`tests/memory/test_mnemonic_contracts.py`, `test_mnemonic_validator.py`,
`test_mnemonic_evidence.py`, `test_mnemonic_candidates.py`,
`test_mnemonic_agent.py` and `tests/llm/test_mnemonic_admission.py`; the commit
half and the ingestion suites have their own, listed in
[mnemonic-commit.md](mnemonic-commit.md). The
validator and agent tests replay the frozen milestone 0 incident corpus
(`tests/fixtures/mnemonic/incidents.json`) through the deterministic decisions
in `tests/fixtures/mnemonic/decisions.json`. Budget, truncation and admission
tests run the real `LLMClient` and the real reservation ledger with only the
provider transport replaced.
