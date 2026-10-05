# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

The native [Qonto source](features/qonto.md) has reviewed source, privacy, tasks,
managed-history and publication fixtures. Support now has authenticated hosted banking acceptance: a single
account is connected, initial and manual source sync complete across restart,
and real provider comparisons and a managed assistant balance/source answer
pass. Engine-formatted UTC retrieval strings now match the actual managed answer.
Installed Desktop and provider-UI comparison remain unverified. The active
[delivery plan](../../docs/execution-plans/2026-10-04-qonto-connection.md) owns
release, rollback, usage and remaining acceptance state.

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
The production listener uses the scoped company-knowledge trial; the owner accepts the October 1 handset trial.

Company-knowledge conversion reads stored `operator-instructions/phone.md`
revision 1, SHA256 `cf61cd70…`, through the M1 operator-instructions reader.
Production imports `mrcall-voice-cafe124-phone-md-5ebe3fa`: origin `706fe2a`
plus the reviewed voice/confinement patch. Prompt/schema remain 8/6 and voice
configuration revision 6. The reviewed artifact has a 270-character initial
view and one complete detail with the six prior approved aliases, rebased to
current source offsets after one K3 conversion. Source/query review passes;
active readback, authenticated binding, health and unsigned callbacks pass.
Production instruction preview matches its unchanged revision-1 mailbox and
procedures documents. All six stored documents remain unchanged at revision 1.
Both clone pause files are absent. Mario imports the service checkout on his
tenant socket; his accepted source preview is recorded in the source-migration
plan. His project-local permissions deny instruction writes, including `instructions.store`,
in twelve supported command spellings. Astra's P1 re-review is APPROVED;
read-only preview and the engine drafting reader remain available. No Mario operator schedule
exists; 124's schedule only reads his inbox. The three former K3 pins are in
root-only backups; those engines import the checkout. All four company stores
are relocated, and all seven daemon identities are migrated, production
voice included with its release unchanged; all seven run under an enforced
egress allow-list (M3). Self-serve provisioning stays closed. Production
voice was accepted under enforcement with a call from a second telephone. See the
[VPS rollout record](../../docs/execution-plans/2026-09-29-toward-sandbox.md#m2-record--vps-rollout-2026-10-02).
See the [source migration plan](../../docs/execution-plans/2026-10-01-telephone-notes-source-is-phone-md.md).

The owner accepted the October 1 handset trial; independent review approved its
direct service answer against the prior USER_NOTES artifact. The manual pilot
is completed. The [knowledge plan](../../docs/execution-plans/2026-09-28-voice-company-knowledge.md)
retains spoken detail, broader-case and quantitative-latency acceptance gates;
no new handset call certified this source migration. Credit refusals are settled
at zero and old uncertainty remains quarantined.

Engine chat now supports negotiated read-only policy version 1. The policy is
enforced before slash/semantic/task routing and again at assistant and task
executor tools; read-only turns do not acknowledge notifications or enqueue
auto-sync work. Kernel `cs ask` requires this capability. The focused M1 suite
proves that explicit mutation refusal leaves complete persisted table values
unchanged and never initializes the agent, creates a background job or requests
an LLM budget reservation. It also covers a real kernel-client → RPC →
dispatcher refusal, while help and search tools remain available. This is
implemented and tested locally; its source is present in the checkout imported
by five nonproduction daemons and retained in support's isolated Qonto release,
without a new read-only product acceptance.

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
are on `main`, in the five nonproduction checkout daemons and in support's
isolated Qonto release; mnemonic rollout acceptance remains pending.

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
`main` (`71bbc21`) and present in that deployed checkout. This sandbox window
does not establish mnemonic product acceptance. A store it migrates cannot
be opened by a milestone 5–7 build.

**Milestone 9 source through `19639d2` is retained in five nonproduction checkout
daemons and support's isolated release; its product rollout acceptance remains open.**
The kernel template audit reads the cron deny list in either of
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
Rollout remains pending. The previously referenced hb plan
`docs/execution-plans/2026-09-30-mnemonic-rollout.md` is absent from this workspace;
a reviewed rollout plan and migration rehearsal on a store copy are required
for the mnemonic product rollout. Five nonproduction daemons import the service
checkout; support's isolated Qonto release retains its current M5–M9 source.
Production voice remains on its older release. Source deployment is verified; mnemonic corpus/product acceptance
and AC 5 re-measurement were not performed in that window.

Support's engine exposes approval-gated `initiate_call` through the dashboard's
Firebase atom API, with an explicit calling assistant ID. A live request on
2026-09-17 returned HTTP 200 / provider `started`; the matching notification at
15:30:16 UTC confirms a conversation with Litio's assistant. The caller's saved
voice configuration initially refused a robot interlocutor, then conversed;
automatic diagnostic scripting is not configured. The restoration is committed as
`4cd23b7`; support's isolated Qonto release retains that service source. See
[outbound contract](features/outbound-calls.md) and
[verification/rollback](../../docs/execution-plans/2026-09-17-mrcall-outbound.md).

The three formerly pinned Café124 units import the service checkout; production
runs the M1-based `phone-md-5ebe3fa` voice release with confinement protections
under its tenant identity. The billing server runs
`prod-99091c35`. Production selects personal OpenRouter/custom K3 for its base
model, five worker roles and reply classification. The other three profiles
retain their previous billing/model settings. Production's daily cap is USD20;
the other three caps are USD5. Automatic processing is off and preparation is
paused/not running in all four. Five nonproduction units import the checkout;
support imports its isolated reviewed Qonto release.

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
- Voice knowledge source/query review is approved and the guarded trial is
  active after approved direct-service handset acceptance. Spoken company detail,
  broader adverse/repeated cases and quantitative latency remain open.
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
3. Re-measure AC 5 in milestone 10 on the resolver-chosen model; deploy
   only through a reviewed rollout plan.
4. Continue the knowledge plan from untested detail and broader behavior/latency gates.
5. Continue other workstreams under their existing plans.
