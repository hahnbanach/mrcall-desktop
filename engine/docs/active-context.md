# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

GPT-Live M1–M3 remain approved as historical isolated milestones. M4 now runs a
single conversational model, `gpt-live-1`, in the isolated telephone listener.
The engine validates carrier admission and company binding, selects pinned
caller-safe facts, sends quiet `thinking`, executes only enabled direct tools on
client delegation and supplies task-bound `commentary`. Its previous telephone
GPT-6 agent, dispatch and fallback are removed from the active runtime. Ordinary
engine LLM workflows and all historical usage/reservation rows remain intact.

The revised M4 implementation passed the voice suite (171 passed, 1 skipped)
and 90 unaffected LLM budget/transport tests. The isolated carrier setup has
private correlated traces and receipts for seven autonomous calls covering
clock follow-up, unknown-caller privacy, spoken correction, delayed lookup, and
lookup failure. Those are operator-observed private records, not repository
artifacts or proof of handset audio. The autonomous diagnostic caller is unknown
to the frozen customer fixture. Operator handset feedback confirms correct
blue-filter/Thursday facts, immediate fluent greeting, and a successful
interruption for a recognized caller, correlated with a private closed trace.
Delayed-lookup hangup has private evidence of closure without a late result,
cancelled lookup and retained ledger hold. Deterministic
tests cover ambiguous identity and lookup failure; the operator accepted the
completed interruption test as sufficient. Final independent review approved
M4 within the operator-adjusted scope. The hangup trace proves cancellation of
the in-flight lookup; deterministic tests cover a completed delegated result
racing with closure. The experiment sequence and private trace references are
in the [completed plan](../../docs/execution-plans/2026-09-23-gpt-live-engine-integration.md).
The isolated ledger retains 41 closed historical smoke calls and 41 carrier
receipts, but its service is currently absent. Its saved provider endpoint now
reaches the production listener, so it is not an isolated route for new tests.
The production listener remains pinned to `8fb21d3`.

The company-knowledge notes-only path is built locally on `main`: an offline
`MODEL_MEMORY_EXTRACT` converter, versioned private artifact, failed-request
cooldown, short initial context and distinct company-detail delegation. It is
not deployed; the protected company switch defaults off. A real K3 conversion
produced an exact-span artifact, but independent source review rejected its
selected facts and Italian detail matching. The artifact was removed from the
production profile. M3 detail mapping is reopened, and M4 has no spoken-answer
or latency acceptance; see the [blocked plan](../../docs/execution-plans/2026-09-28-voice-company-knowledge.md).

Engine chat now supports negotiated read-only policy version 1. The policy is
enforced before slash/semantic/task routing and again at assistant and task
executor tools; read-only turns do not acknowledge notifications or enqueue
auto-sync work. Kernel `cs ask` requires this capability. The focused M1 suite
proves that explicit mutation refusal leaves complete persisted table values
unchanged and never initializes the agent, creates a background job or requests
an LLM budget reservation. It also covers a real kernel-client → RPC →
dispatcher refusal, while help and search tools remain available. This is
implemented and tested locally, not deployed.

The mnemonic decision boundary exists in `zylch/memory/mnemonic/`: frozen memory
events whose observation, source revision and authority a model cannot reach; a
bounded three-round role whose complete identity/refusal prompt sits in the
cached system block; a small symbolic validator; and origin-bound paid
admission enforced in `check_dispatch` by the dispatch scope rather than the
usage label. Interactive grants leave bounded preparation untouched; automatic
grants must match the admitted item.
Contract and bounds: [mnemonic decisions](features/mnemonic-decisions.md).

The boundary now commits. `mnemonic/commit.py` writes a validated CREATE,
UPDATE or — for a consolidation pair, inside its admitted item, and nowhere
else — MERGE: blob, sentences, identifier index, source links, the alias,
mutation sequence and the operation receipt, in one transaction on the company
store, under a single-use `CommitPermit` checked at the storage boundary and a
CAS against the versions re-read inside that transaction. A `memory_operations`
table in the same store makes an event idempotent, fences concurrent attempts
and carries the per-event dispatch allowance across a restart.
Reclassification, and a MERGE anywhere else, return `review_needed`.

No write asks a human. A validated proposal is written, and the difference
between what the calling tool asked for and what the role decided — a different
action, subject, scope, or an effect that absorbs another memory — is recorded
as a `departure` on the operation row, in the tool's response and in the solve's
answer. The three standing grants in the estate (`cs --allow`, the engine's
session grant, the Desktop session button) grant the tool, which is the one
permission a memory write needs. Every rewrite first retains the replaced text
in `blob_versions` (`append`); a consolidation MERGE retains the keeper's
replaced text and the donor's final text (`consolidate`); a restore retains
what it replaces (`restore`); the owner's delete and reset are the only paths
that leave no version behind. A retained version is restorable through
`memory.restore_version` and `/memory restore`, mechanically and gated like
every other memory mutation. Consolidation alone prunes versions: older than
90 days and beyond a blob's 10 newest, never a sink's — a live blob with more
than 25 `append` versions since its latest restore, reported by id on every run
until its owner restores a version or deletes it.

`create_memory`, `update_memory`, the task solve — chat, RPC and the
interactive CLI solve, which carries its solve context — `/memory store`, the
four ingestion channels through the pipeline and through the background memory
job, the fact and rule stores and correction learning go through the semantic
commit and nothing else: the direct writes they had are deleted, and no setting
selects a writer. An ingested source is one parent operation with one child per
extracted entity, persisted as a manifest before any child is decided; the
source is marked processed only when every child is committed or deliberately
skipped, a review parks it visibly, a crash resumes the unfinished children,
and an edited source is a new revision. An extracted entity carries its own
identifiers and never the sender's. A known customer-shaped FACT — by its own
header or by a review's restriction — is absent from every ordinary fact read
and from hybrid search before ranking. Consolidation
(`memory/consolidation.py`) is the one operation that removes memory: the
Settings button, `zylch memory-sweep` (inside its own preparation run) and the
post-update run call it. It replays this account's recorded task-reference
follow-ups, applies retention, then decides each duplicate pair through the
role — pairs the validator's identity rule could never accept cost no call —
and commits a MERGE; its merge gate follows the canary, which asks the role.
Outside the harness stay only the owner's delete, reset and restore, and the
reviewed exempt primitives the writer inventory names. Contracts:
[mnemonic commit](features/mnemonic-commit.md),
[mnemonic decisions](features/mnemonic-decisions.md),
[writer inventory](features/mnemonic-writer-inventory.md). Tested locally
against the frozen milestone 0 incident corpus and real split profile/company
databases. Milestones 5–7 and the account check that accepts either identity
of the profile, uid or email ([who the account is](features/mnemonic-decisions.md#who-pays)),
are on `main` and pushed; **not deployed**.

Milestone 8 seals the boundary ([join, reviews and maintenance](features/company-memory-join.md)):
a company-memory join is a fenced, crash-safe cutover that refuses while the
account's own work in the source is unsettled, imports what it can see
without laundering a restricted FACT, and tells its three crash states apart
at boot; `zylch memory-reviews` retries or dismisses parked work; the
maintenance routes retain what they drop, touch only their own rows and roll
back a tampered rebuild; `store_blob`, `update_blob` and the `Storage` link
and identifier writers exist only in the test seeding module; a static
boundary test and its CI workflow fail on a new scanned writer edge, a new
caller of the row internals or the permit factory by any spelling, and a new
statement built from strings ([what it cannot see](features/mnemonic-writer-inventory.md#what-is-scanned)); the inert
`memory_operations.approval` column is removed by a table rebuild. Merged into
`main` (`71bbc21`); **not deployed**. A store it migrates cannot be opened by a milestone 5–7 build.

**2026-09-30 — Milestone 9, on branch `mnemonic-m9`, not merged, not deployed.**
On the branch: the kernel template audit reads the cron deny list in either of
its two forms and refuses neither/both, so it passes against `cs-kernel`
`258c927` and against current kernel `main` (`ba79cc1`) with every inventory
count unchanged; the installed-client journey — the real `cs` entry point of an
installed kernel against the engine's own WebSocket handler, seventeen cases
([entity memory](features/entity-memory-system.md#the-installed-client-journey-milestone-9)),
Firebase verification not in the loop; the journey CI,
`.github/workflows/mnemonic-journey.yml`, which clones the kernel at the commit
pinned in the file, sets `CS_PROJECT_KERNEL_PYTHON` and
`MNEMONIC_JOURNEY_REQUIRED=1` so a missing kernel fails rather than skips, and
runs the journey, `test_project_kernel_journey.py`, `test_memory_readonly.py`
and the kernel audit; and the priced-corpus runner, dry — ten incidents on one
disposable profile, six automatic ones as admitted items of one explicit
preparation run, four interactive ones through a real turn, a durable intent
before every dispatch, a cumulative cap over settled rows, unsettled holds and
open intents, the canary, budget, unpriced and truncation checks, a record with
the key redacted ([bounded preparation](features/bounded-preparation.md#the-priced-corpus-inside-one-explicit-run),
[spending protection](features/daily-llm-budget.md#the-corpus-runners-second-bound)).
Entry points, from `engine/`: `tests/rpc/test_mnemonic_kernel_journey.py`,
`_b.py`, `tests/rpc/test_mnemonic_engine_journey.py`, `_b.py` (skip without
`CS_PROJECT_KERNEL_PYTHON`); `tests/memory/test_mnemonic_kernel_inventory.py`
(kernel checkout beside the repository); `tests/memory/test_mnemonic_corpus_live.py`
(dry by default; `MNEMONIC_CORPUS_EXECUTE=1` plus `ANTHROPIC_API_KEY` pays).
The paid corpus ran once on 2026-10-01 (record
`docs/evaluations/2026-10-01-mnemonic-corpus*`, commit `e5ab75e`): model
`claude-haiku-4-5`, the real fastembed embedder, ten cases on one disposable
profile, 4 pass, 5 noncritical, 1 `critical_failure`; the four D6 checks
(canary `refused`, budget and unpriced refusals before the wire, truncation
`review_needed`); USD 0.0766 settled of the USD 10 cap, the sidecar fixture
turn included; the profile deleted. **AC 5 is not met**:
`customer_price_correction` CREATEd a new Boreale COMPANY blob and left the
seeded required target untouched, with the seeded legacy candidate shown first
to the role; model behaviour on the arm, correctly flagged by the harness, not
a seeding defect. The CTO's decision (2026-10-01): the `claude-haiku-4-5`
arm is rejected as a product choice, Haiku is not a default or an arm
anywhere; AC 5 is re-measured in milestone 10 on the model a
requirements-based resolver chooses for the mnemonic role; milestone 9's
model-agnostic code merges into `main` as is, the Haiku run kept in the record
as the measure of a rejected arm. The rollout's step-1 exit waits for that
re-measurement. The run found that a fresh install resolves the Anthropic
SDK to 1.x, whose `messages.create()` refuses sampling keywords; the direct
transport drops them (`88e2370`, `zylch/llm/sdk_request.py`) and both
dependency files now pin `anthropic<2`. Known issues from the run: the record
holds no per-round proposal, validator result or latency (the journal prunes
the payload at terminal states and the runner reads only the journal); two
automatic cases (`planned_not_completed`, `contradictory_legacy_fact_rule`)
stay `pending` with no child, `attempts` 0 and no reason in the journal when
the extraction worker raises on an answer that is neither bare `SKIP` nor an
`#IDENTIFIERS` block, so the same answer is re-paid on every run; the role
translated the Italian corrections into English (seven `must_preserve`
misses). The journey workflow is green on every run of the pushed branch
(runs 2 to 8, the pinned kernel cloned with the workflow's own token).
Still pending: the merge; and the rollout, which
is the CTO's step-by-step decision on the hb plan
`docs/execution-plans/2026-09-30-mnemonic-rollout.md`, with a migration
rehearsal on a store copy before any live step. The hosted engines still run
pre-milestone-5 code.

Support's engine exposes approval-gated `initiate_call` through the dashboard's
Firebase atom API, with an explicit calling assistant ID. A live request on
2026-09-17 returned HTTP 200 / provider `started`; the matching notification at
15:30:16 UTC confirms a conversation with Litio's assistant. The caller's saved
voice configuration initially refused a robot interlocutor, then conversed;
automatic diagnostic scripting is not configured. The restoration is committed as
`4cd23b7`, and the engine running on support (`f12ae60`) descends from it. See
[outbound contract](features/outbound-calls.md) and
[verification/rollback](../../docs/execution-plans/2026-09-17-mrcall-outbound.md).

Four Café124 units run isolated release `8d83193`; the billing server runs
`prod-99091c35`. Production selects personal OpenRouter/custom K3 for its base
model, five worker roles and reply classification. The other three profiles
retain their previous billing/model settings. Production's daily cap is USD20;
the other three caps are USD5. Automatic processing is off and preparation is
paused/not running in all four. Other hosted units retain their own release pins.

[K3 max](features/k3-reasoning.md) uses Chat completions pinned to DigitalOcean.
The adapter promotes worker limits to a combined 8192-token reasoning/final cap
before quote and budget admission. Synthetic live BYOK acceptance verifies a
complete response, positive reasoning usage and actual-cost settlement. The
configured client factory resolves OpenRouter/K3. A saved Anthropic key is
inactive while OpenRouter is selected.

The credit path passes authenticated quotation and offline HTTP/ledger tests;
a funded live K3 response is unverified. Its isolated test ledger retains a
USD0.209 hold after the server refused insufficient credits before dispatch.
The separate successful BYOK test ledger has no remaining hold. Neither test
ledger changes the hosted production allowance.

Memory extraction and task detection retain completion guards and budget
admission. Merge selection limits expensive candidates. Saved extraction prompts
receive a serialization-only contract for structured FACT output without
retraining or changing business rules; its quality effect remains unmeasured.
See [spending protection](features/daily-llm-budget.md) and the
[reviewed comparison](../../docs/evaluations/2026-09-16-reviewed-model-comparison.md).
The comparison separates decisions, explanations and uncertain claims; it does
not certify production error rates. Older semantic scores are superseded.

Shared written projects use company-store documents, immutable revisions and
revision-checked `projects.*` writes, separate from entity blobs. Company
membership is a capability changed only by `memory.join`; owner rules remain
private. Profile databases retain mailbox data, tokens and cursors. See
[project memory](features/project-memory.md) and `MEMORY_TABLE_NAMES` in
`zylch/storage/database.py` for the storage binding.

Authenticated RPC serves setup evidence, identity, catalogs and billing policy.
`setup.state` describes preparation evidence, not reply quality. Firebase ID
tokens stay in memory. Claude Code headless runs in a clone and is outside engine
API budgets; see [control boundaries](../../docs/operator-setup.md#ai-execution-and-controls).

## Unresolved

- The remaining three profiles await a billing choice; funded credit acceptance
  remains open. No backlog resumption is part of model configuration.
- Incident checkpoint counts and project inventories in dated records are
  historical; re-read current state before a cleanup or backlog operation.
- Voice knowledge M3 detail mapping and M4 source selection need repair and
  private semantic review. M4 also needs a separately routed isolated fixture
  and supervised answer/latency evidence before any production activation.
- Desktop v0.1.49 installation and personal-key entry on the CTO's Mac remain
  unverified. Saved-prompt format repairs have no new business-quality result.
- The Desktop app does not read `memory.status`'s `joining` or
  `memory.join`'s `blocking`: a refused join shows its reason only, and the
  settling commands exist on the engine CLI alone (M8 added no RPC for them).
- Calendar token integration, phone memory parity, RPC error humanization and
  WhatsApp multi-profile isolation remain separate [backlog](harness-backlog.md)
  work. Product chat and comprehensive security review remain deferred.

## Next

1. Resolve billing choices and finish funded credit acceptance without replaying
   uncertain requests. Keep automatic processing and preparation paused.
2. Verify the Mac application through its GUI; start a bounded batch only when
   requested and review its role-specific outputs.
3. Merge `mnemonic-m9` as is (decision taken; workflow green on the pushed
   branch first); re-measure AC 5 in milestone 10 on the resolver-chosen
   model; deploy only through the rollout plan.
4. Resolve the voice knowledge M4 findings under its active plan before M5.
5. Continue other workstreams under their existing plans.
