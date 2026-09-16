# Controlled engine quality grading protocol

This protocol evaluates model outputs against source messages and binding owner
instructions. Opus is a paired comparator, never ground truth. Raw mail, prompts,
responses, source excerpts and output-to-model mappings remain private. Public
reports contain aggregate results and sanitized error classes only.

## Freeze before outputs

Record dataset/source revision, candidate inventory, seed, inclusion/exclusion
rules, stratum, language, thread length, development/held-out assignment and
repeat selection. Count distinct thread IDs: two roles or repeated generations
from one thread are not independent observations. The three previously exposed
threads belong to development. Freeze the candidate before anyone developing it
sees held-out responses. Changes after unblinding require a new labeled study.

For each thread/role preregister evidence locators, required facts or actions,
forbidden inferences, acceptable alternatives and material ambiguities. Existing
memory/task descriptions can contain earlier model errors; they are context,
not truth. Record source snapshot date and evaluation date separately. A single
incoming email cannot establish that no subsequent reply exists. Record which
source context the model actually receives, not just what the reviewer can read.

## Keep four outcomes separate

1. **Availability/completion:** attempted, completed, provider error, timeout,
   truncated, refused, or not attempted with reason. Preserve every attempt and
   hold. A diagnostic retry is a separate labeled attempt; never substitute its
   answer for the first failure.
2. **Production parser acceptance:** run the actual completion guard/parser on
   the captured response with the original context. This measures current code
   behavior, including its permissiveness; do not call it full validation.
3. **Contract adequacy:** independently check the documented tool schema and
   application requirements (including meaningful identity and existing target
   task). A parser-accepted response can still be unusable.
4. **Semantic quality:** source-grounded identity, facts, chronology, commitments,
   own-entity exclusions, task lifecycle, ownership and calibrated uncertainty.

A missing output is not semantically gradable and never a pass. Report both
semantic results among returned outputs and end-to-end acceptable results among
attempted cells, alongside planned-but-unattempted coverage.

## Blinded grading sheet

Each private row contains:

| Field | Required content |
|---|---|
| Identity | Opaque output ID, opaque thread ID, role, input-context hash |
| Availability | Completion state and production parser outcome; no provider identity |
| Contract | Pass/fail/uncertain, violated schema/application requirement |
| Facts | Required fact/action present, missing or contradicted, with evidence locator |
| Errors | Consequential/minor classification, category, source locator, short rationale |
| Ambiguity | Competing source/owner instructions and acceptable alternative interpretations |
| Verdict | Acceptable, unacceptable, or indeterminate; reason and reviewer confidence |
| Provenance | Reviewer, rubric version, timestamp and any later adjudication |

Hide model, provider, prompt-variant identity, cost and latency. Repetitions retain
opaque IDs; graders must not infer which is a retry or treat a matching answer as
proof. Grade all returned outputs with the same rubric. A factual challenge is
resolved while identities remain hidden; retain initial and adjudicated grades.

**Consequential errors** can change who an entity is, what the business knows or
must do, or whether work is complete: unsupported person identifiers; extracting
excluded own-company entities; invented companies or learned styles; requirements
stated as proven capabilities; planned invoices/payments/shipments stated as
completed; false closures, duplicate issues, invented commitments or deadlines;
wrong ownership; and missing information essential to the next action.

**Minor errors** are unsupported peripheral details or ambiguities that do not
change the operative decision. Omissions are not automatically minor: grade their
consequence. A qualifier such as “likely” does not justify storing speculative
identity or behavior as durable memory. Correct facts elsewhere do not cancel a
contradictory authoritative field. Do not penalize equivalent wording or a
source-supported alternative simply because it differs from a reference answer.

A semantic pass requires the operative required information, respected binding
constraints and no consequential error. Missing context or contradictory binding
instructions may make a case indeterminate. Do not silently remove it: report its
frequency and whether the uncertainty prevents a deployment decision.

## Actual parser limitations to record

`MemoryWorker._parse_entities` in `engine/zylch/workers/memory.py` splits entity
blocks and requires the `#IDENTIFIERS` marker. It does not establish that an
identity exists, validate every entity type/field, require all three sections,
or enforce source truth and own-company exclusion. `complete_memory_text`
requires completed nonempty text; valid `SKIP` is handled outside the entity
parser. A bare identity marker passes the entity parser, not this quality rubric.

The response block in `TaskWorker._analyze_event` checks completion, tool name,
required keys, action boolean, action/urgency enums and reason/action string types.
It does not enforce every `TASK_DECISION_TOOL` constraint: minimum string lengths,
optional-field types, conditional title/target requirements or target existence.
The persistence caller resolves target IDs separately. Record these checks as
contract adequacy without pretending that stricter checks already run in the
production parser. Do not persist tasks during evaluation.

The private `parse-responses.py` helper extracts this response block from the
production AST. Pin and hash that source; assert the expected AST structure.
Pass the exact thread-history section: omitting it skips the production
silent-follow-up urgency adjustment. Keep raw and adjusted urgency separately.
Ignore generated `analyzed_at` timestamps in model comparisons. Its raw-response
namespace conversion can throw before its internal exception handler; the runner
must catch malformed envelopes and append a failure outcome rather than crash or
lose the attempt. Record production-parser exceptions separately from transport.

## Paired analysis and recommendation

Unblind only after grades are frozen. Report each role separately, with thread
counts, strata, model completion/contract rates, source error categories, and
paired wins/ties/losses against Opus on the same input. Show discordant cases:
which model fails which requirement, rather than only a mean score. Both models
failing the same case is a tie, not evidence of acceptable quality.

Report first attempts separately from repeats. On the preselected repeated subset,
measure changes in completion and semantic verdict; do not pool repeats as extra
threads. A candidate comparison must state its development gate and exact held-out
coverage. If budget or availability stops an arm, report the missing cells and
reason; make no whole-matrix conclusion from only its surviving easy examples.

Report provider cost, settled ledger debit and outstanding holds distinctly.
Cost per acceptable completed task includes failed-attempt costs; an inexpensive
but unusable output is not a saving. Compare actual observed cost and output
length with their limitations, not token prices alone. Historical spend/holds
remain part of the cumulative experimental cap across UTC midnight.

Apply the preregistered role-level go/no-go rule. No newly consequential error
versus Opus, no unresolved availability/contract failure, and lower observed cost
are prerequisites for a monitored pilot, not proof of equivalence. State cases
where Opus itself is unacceptable. Stratified purposeful selection does not
estimate mailbox-wide prevalence, and 50 threads cannot certify rare-error safety.
If intervals are reported, describe the sampling assumption and retain clustering
by thread; do not present calls or roles as independent binomial observations.

## Version 2 evidence and separate judgments

`engine/scripts/prepare_model_quality_grading.py` writes private
`evidence-by-label.json` beside the blinded packs. Each returned output binds to
its own captured system instructions, every message block, tool schema, tool
choice and resolved clock. Paired variants cannot borrow another variant's
context. Model/provider/effort/output-ceiling controls are excluded from these
semantic sections. Section, input, output and bundle hashes preserve the binding.
Missing responses do not receive evidence bundles.

Optional configuration `review_authorities` names a JSON array of later review
facts. Every record requires an `authority:` ID, exact text, timezone-aware ISO
`timestamp`, `source` and `scope`. These facts remain separate from captured
inputs and cannot change the original input hash. A sent message or generated
memory is not automatically verified company policy; record its authorship,
date, conflicts and authority limitations.

A version 2 review includes `version`, `case_id`, `bundle_sha256`, `coverage`
(the complete set of original section IDs), substantive `claims`, and four
independent dimensions:

| Dimension | Allowed judgments |
|---|---|
| `task_decision` | acceptable, unacceptable, indeterminate, not_applicable |
| `explanation_grounding` | supported, contradicted, unsupported, not_applicable |
| `claim_truth` | supported_true, supported_false, unknown, not_applicable |
| `operational_impact` | decision_changed, explanation_only, unknown, not_applicable |

Each claim gives a rationale, exact `output_quote`, and `source_refs` containing
section ID, hash and exact source quotation. `model_quality_evidence.py` validates
these bindings, declared coverage and category consistency. The summarizer invokes
that validator before counting any version 2 review or separate dimension and
checks that the bundle contains the actual packed output. An unacceptable task
requires a grounded changed-decision judgment. Unsupported payment confirmation
can coexist with a correct no-action decision; its real-world truth remains
unknown. Grounding refers to cited review evidence, including separately recorded
later authority, and does not claim that the model received that authority.

This is a traceability check, not a truth detector: a reviewer can still overlook
context or draw a wrong conclusion from a genuine quotation. Independent source
review remains necessary. Legacy semantic scores are not automatically translated
into these dimensions; they remain unassessed until explicitly reviewed. Usable
response counts require actual recorded production-parser acceptance as well as
completion and acceptable semantic/contract grades. An absent parser assessment
is unassessed rather than a demonstrated paired loss.
