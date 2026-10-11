# Role measurement: milestone 10's paid run and `measured.json`, 2026-10-11

Scope: the record of the one-off paid measurement behind
`engine/zylch/llm/roles/measured.json` (branch `m10-s4b6`, commit `9e622233`):
what was run, on which prompts, snapshots and commits, and what it cost. It
also gives each role's result, the audit and its fixes, the CHAT re-measure,
the 402 incident, the resolver's picks, mnemonic AC 5 and what the
measurement does not certify. The method is in
[`engine/tests/fixtures/measurement/README.md`](../../engine/tests/fixtures/measurement/README.md),
and the role, rule and table contract is in
[model selection](../../engine/docs/features/model-selection.md).

## What was measured

| Input | Rows | Engine commit | Snapshot |
|---|---|---|---|
| 12 roles with case sets (all but CHAT), `measure_roles.py`, 2026-10-04 | 790 rows, 6 arms per role (5 for TASK_SOLVE) | `8b18ea69` | `81998270` (read 2026-10-02T19:57Z) |
| CHAT, re-measured on today's prompt, rerun 3, 2026-10-11 | Sonnet 5.5, Qwen 3.8 Max, GLM 5.3, K3 (the reference) | `1785352c` | `8df61cff` (read 2026-10-10T12:01Z, before S2's forced_tool change) |
| CHAT, rerun 4, 2026-10-11 | Opus 5.5 | `f827ae19` | `b3196ae2` |
| Memory corpus (MNEMONIC, MEMORY_EXTRACT, MEMORY_MERGE), seven arms, 2026-10-02 records | 10 cases + 4 checks per arm | `8b18ea69` | `81998270` |
| Corpus, mimo-v2.6-pro re-run, 2026-10-04 | 10 cases | `e9bd6d02` | `81998270` |
| Corpus, Sonnet 5.5 re-run, 2026-10-11c | 10 cases | `f827ae19` | `b3196ae2` |

The **build snapshot in force** is `f2939ddb`'s `snapshot.json`: version
`b3196ae2…`, read 2026-10-10T12:01:52Z. Most of the measurement ran on
`81998270…` (read 2026-10-02T19:57:28Z). A snapshot sets prices, admitted
endpoints and caps; it does not change a request's bytes. `measured.json`
records each role's snapshot version(s). CHAT lists two.

Every request was today's, byte for byte. The re-score compared each case of
every role with the `requests.json` committed at the run's commit under the
rows' hashes, and refused no case. CHAT's earlier rows (prompt `64a1a517`)
were left out. Main's attachment-evidence and Qonto changes (`86bf2f10`,
`a68ea7b8`) moved CHAT's prompt to `c55f551c` (`185bd1a3`), and CHAT was
measured again on it.

`measured.json` was written by `scripts/derive_thresholds.py` alone:

```
derive_thresholds.py --arms arms-final.json --results ROWS --corpus <9 manifests>
  --rescore --answered-at 8b18ea69 1785352c f827ae19
  --rescore-from fa1518f0… acb2e224… --out zylch/llm/roles/measured.json
```

`check_measured` passes: its hashes are today's `requests.json` and corpus
prompts, and its passes and thresholds follow from its own results
(`tests/measurement/test_derive_thresholds.py`).

### The CHAT reference

K3 answered CHAT completely twice on today's prompt. In rerun 3 it scored
10/11, missing chat-09: no behavioural-rule `create_memory`. In rerun 4 it
scored 11/11. **The reference is rerun 3's K3**, for three reasons:

- it is the first complete run of the reference on this prompt;
- it ran in the same run, commit and snapshot as three of the four other arms;
- rerun 4 was launched only to complete Opus.

The choice matters. With rerun 4's K3 (1.000 ± 0), Opus 5.5 and Sonnet 5.5
(10/11 each, both missing chat-12) fail CHAT, and CHAT's Anthropic ranking is
empty. One case of reference noise decides an Anthropic pass. That is the
clearest instance of the yardstick limit described below.

## Spend

The figures below were checked against the ledgers: `measure_roles`'s
`ledger.jsonl`, and each corpus profile's `llm_usage` and `llm_reservations`
tables. Every settled figure is the provider's receipt.

| Item | USD | Source |
|---|---|---|
| 2026-10-03 aborted attempt (K3 corpus) | 0.97 counted | Settled 0.093 (6 calls). One reservation (0.187) and one open intent stayed unsettled; the remaining 0.877 is that intent's bound. The run counted the whole 0.97 as committed. |
| Corpus, nine arms (2026-10-02 records) | 1.299 | sum of the nine manifests' `totals_usd.settled` |
| Roles with case sets (2026-10-04) | 5.478 | 961 intents, 961 settled, none open |
| Sonnet corpus attempt, 2026-10-04 (S4b5; cases refused by a 0.40 cap) | 0.016 | canary and checks only |
| mimo-v2.6-pro corpus re-run | 0.034 | |
| CHAT rerun 3 | 2.293 | 91 settled; 2 failed with HTTP 402, nothing charged |
| CHAT rerun 4 | 1.520 | |
| Sonnet corpus, rerun 3 (402) | 0 settled | The 402 came before any work. The 0.099 hold and 0.526 open bound in that disposable profile predate S3e, which releases a 402's hold. |
| Sonnet corpus, rerun 4 (stopped by its 0.60 cap) | 0.095 | 0.077 of cases plus 0.017 of checks |
| Sonnet corpus, rerun 5 (the record used) | 0.157 | |
| **Total** | **10.99 settled; 11.86 counted** | Counted takes the aborted attempt at its 0.97 bound. Of the USD 20 the CTO approved. |

Corrections to the figures the task listed:

- "corpus 2.27" is the run's own running total. It includes the aborted
  attempt's 0.97, so the corpus itself is 1.299.
- The 2026-10-04 Sonnet attempt (0.016) was missing from the list.
- The Sonnet rerun 4 attempt is 0.095, not 0.077: the 0.077 left out its
  checks.

The 2026-10-03 rehearsal ledger's 4.57 is a dry run's scripted receipts, not
spend.

## Per-role result

Each arm is judged against the reference (K3) from the same run:

- it must be complete;
- every mechanical bar must be met;
- it must have no critical failure;
- its score must be at least p − se.

A maximise role ranks the arms that pass. A satisfice role's threshold is the
lowest index score at and above which every measured arm passes. When index
score and result disagree, the role is `measured_only`.

| Role | Rule (index) | Reference p ± se | Threshold | Passing arms (passes/n) | Failing arms | Incomplete | Anthropic passing |
|---|---|---|---|---|---|---|---|
| MNEMONIC | maximise (intelligence) | 1.000 ± 0 | – | Opus 5.5 10/10, K3 10/10, GPT-6 Sol 10/10, GPT-6.1 Sol 10/10 | Sonnet 5.5 (bar), deepseek-v4-flash (critical), mimo-flash (critical), mimo-pro (bar), glm-flash (bar, critical) | – | Opus 5.5 |
| MEMORY_EXTRACT | satisfice (intelligence) | 1.000 ± 0 | measured_only | Opus, deepseek-v4-flash, K3, GPT-6 Sol, GPT-6.1 Sol (6/6) | Sonnet (bar), mimo-flash (critical), mimo-pro (bar), glm-flash | – | Opus 5.5 |
| MEMORY_MERGE | maximise (intelligence) | 1.000 ± 0 | – | Opus, deepseek-v4-flash, K3, GPT-6 Sol, GPT-6.1 Sol (7/7) | Sonnet, mimo-flash, mimo-pro, glm-flash | – | Opus 5.5 |
| TASK_DETECTION | satisfice | 1.000 ± 0 | measured_only | Sonnet, deepseek, K3, mimo-pro (16/16) | mimo-flash, glm-flash (bar) | – | Sonnet 5.5 |
| REANALYZE | satisfice | 1.000 ± 0 | measured_only | Sonnet, deepseek, K3, mimo-pro, glm-flash (15/15) | mimo-flash (bar) | – | Sonnet 5.5 |
| DEDUP | satisfice | 1.000 ± 0 | **24.4** | all six (14/14) | – | – | Sonnet 5.5 |
| REPLY_NEED | satisfice | 0.929 ± 0.069 | measured_only | Sonnet, mimo-flash, mimo-pro, glm-flash (14/14) | deepseek, K3 (critical) | – | Sonnet 5.5 |
| INTENT | satisfice | 1.000 ± 0 | measured_only | Sonnet, deepseek, K3, mimo-flash, glm-flash (14/14) | mimo-pro 13/14 | – | Sonnet 5.5 |
| CHAT | maximise (agentic) | 0.909 ± 0.087 | – | Opus 10/11, Sonnet 10/11, K3 10/11, Qwen 3.8 Max 11/11, GLM 5.3 11/11 | – | – | Opus, Sonnet |
| TASK_SOLVE | maximise (agentic) | 0.909 ± 0.087 | – | Opus 11/11, Sonnet 11/11, GLM 5.3 10/11 | K3, Qwen (bar) | – | Opus, Sonnet |
| TRAIN | satisfice | 1.000 ± 0 | measured_only | Sonnet, deepseek, K3, mimo-flash, glm-flash (5/5) | mimo-pro (bar) | – | Sonnet 5.5 |
| COMPACTION | satisfice | 1.000 ± 0 | measured_only | Sonnet, deepseek, K3, mimo-flash, mimo-pro (5/5) | glm-flash (bar) | – | Sonnet 5.5 |
| SYNC_ANALYSIS | satisfice | 0.929 ± 0.069 | measured_only | Sonnet, deepseek, K3 (13/14) | mimo-flash, mimo-pro, glm-flash | – | Sonnet 5.5 |
| WEB_SEARCH | satisfice | 1.000 ± 0 | measured_only | Sonnet, K3, glm-flash (5/5) | deepseek (critical), mimo-flash, mimo-pro (bar) | – | Sonnet 5.5 |
| CORRECTION_LEARNING | satisfice | 1.000 ± 0 | measured_only | Sonnet, deepseek, K3, mimo-flash (14/14) | mimo-pro (bar), glm-flash | – | Sonnet 5.5 |
| NARRATION | satisfice | 1.000 ± 0 | measured_only | K3 5/5 | Sonnet, deepseek, mimo-flash, mimo-pro, glm-flash (bar) | – | **empty** |

"Bar" means a mechanical bar was missed: truncation at `max_tokens`, the
language bar, a tool not called, or an operation left pending. No arm is
incomplete in `measured.json`. The reference fails two roles itself: REPLY_NEED
(critical) and TASK_SOLVE (a bar). Its score is still the yardstick.

## The audit and its fixes

Every failing cell of the 2026-10-04 run was read by hand: 49 cells, each
classed by what decides it.

| Class | Cells |
|---|---|
| A, a genuine model failure | 24 |
| B, a scorer bug | 3 |
| C, a label or case error | 9 |
| D, truncation at `max_tokens` (requests as production sends them; a real fail) | 7 |
| Unresolved: a corpus extraction left pending, raw output not recorded | 6 |

Fixed in S4b5 (`e9bd6d02`):

- **B1**: a text with no function-word hit in either language has an
  unreadable language. It skips the language bar and label instead of
  failing them.
- **B2**: the corpus check "a child inherited the sender's identity" reads
  the identifier header's email only. Opus's multi_entity_source child said
  "the sender address is not known to be her own" and failed on that sentence.
- **C1**: `must_preserve` accepts the substance in either language.
- **C2**: REVIEW is allowed where the M9 prompt prescribes it.
- **C3**: sync_analysis-11's `critical_on` is `["invalid"]`.
- **C4**: a `matches_none` hit the answer itself calls wrong is a
  counter-example.
- **C5**: `run_python` is not an `unmatched_write`.
- A failed extraction keeps its raw text (`extraction_failures`).

**S4b6 correction (`a7d53054`).** S4b5's re-score path scored again only the
rows of a changed case set. A scorer fix changes no hash, so B1, C4 and C5
never reached CORRECTION_LEARNING, WEB_SEARCH and TASK_SOLVE, and S4b5's
candidate was wrong on those roles. `--rescore` now scores every recorded
answer again. Each changed verdict is listed in `measured.json`'s
`rescored_from.*.verdicts_changed`:

- deepseek correction_learning-01;
- mimo-pro web_search-03;
- qwen task_solve-04;
- sync_analysis-11 for three arms;
- 20 corpus case verdicts across seven arms, each counted once in all three
  memory roles, including Opus's and mimo-flash's multi_entity_source
  (critical to pass).

**The six unresolved cells** were Sonnet and mimo-pro, each pending on one
extraction in all three memory roles. Their re-runs recorded the raw text,
and both are model output the worker refuses:

- mimo-pro wrote `# SKIP` / `SKIP` followed by an explanation
  (shared_switchboard, planned_not_completed);
- Sonnet wrote prose about the sender instead of an `#IDENTIFIERS` block
  (unrelated_same_name_people).

The worker accepts only a bare `SKIP` or a block. These are failed cells, not
harness errors. Whether the worker should accept "SKIP + reason" is an engine
question, recorded under the limits below.

The case labels and their reasons are in each role's `cases.json` (`why`)
and in `tests/fixtures/mnemonic/incidents.json`.

## The 402 incident (2026-10-11)

During CHAT rerun 3 the OpenRouter account ran out of credit:

- Opus's chat-13 and chat-14 got HTTP 402 Payment Required before any
  inference;
- the Sonnet corpus re-run's first case got the same.

The engine and the measurement ledger then kept those holds open as possibly
charged. S3e (`fe528f9c`, merged at `f2939ddb`) fixed this:

- a 402 is a no-work status: it releases the daily-budget hold, and the
  ledger settles it as `denied` at zero;
- a 402 stops the measurement run with an out-of-credit message, and the
  cell is never sent again.

After the top-up, rerun 4 completed Opus (11 cases). The rerun 3 Sonnet
corpus attempt is not used.

## Trims and reserve (IR2)

The case sets were trimmed before the paid run to fit the projection under
USD 16, by the deterministic rule in the fixtures README.

| Measured / reserve | Roles |
|---|---|
| 16 / 6 | TASK_DETECTION |
| 15 / 5 | REANALYZE |
| 14 / 7 | DEDUP |
| 14 / 6 | REPLY_NEED, INTENT, SYNC_ANALYSIS |
| 14 / 10 | CORRECTION_LEARNING |
| 11 / 3 | CHAT (reviewed exception: chat-07 kept, chat-06 to the reserve) |
| 11, untrimmed | TASK_SOLVE |
| 5, untrimmed | COMPACTION, NARRATION, TRAIN, WEB_SEARCH |

The corpus is 10 live cases plus four checks. The eleventh case,
`malformed_output`, runs dry only.

Every critical case was kept by rule, so the trims shift each set towards its
critical cases. The reserve stays authored and reviewed.

## Mnemonic AC 5, restated on the measured pick

M9's AC 5 ("every critical case passes") failed on 2026-10-01 on the rejected
`claude-haiku-4-5` arm. On the measured table the resolver ranks MNEMONIC as
follows:

- **balanced** (ceiling 20): Opus 5.5 first, then GPT-6.1 Sol, GPT-6 Sol, K3;
- **economy** (ceiling 10): GPT-6.1 Sol first, then GPT-6 Sol.

Both picks' corpus records, judged on today's labels:

| Case | Class | Opus 5.5 (balanced pick) | GPT-6.1 Sol (economy pick) |
|---|---|---|---|
| unrelated_same_name_people | automatic | pass | pass (was noncritical: REVIEW, C2) |
| shared_switchboard | automatic | pass | pass |
| corroborated_same_person | automatic | pass | pass |
| planned_not_completed | automatic | pass (was noncritical: C2) | pass (was noncritical: C2) |
| contradictory_legacy_fact_rule | automatic | pass | pass |
| multi_entity_source | automatic | pass (**was critical_failure: B2**) | pass |
| customer_forwarding_number_correction | verified correction | pass (was noncritical: C1/C2) | pass (was noncritical: C1/C2) |
| customer_price_correction | verified correction | pass (was noncritical: C1) | pass (was noncritical: C1) |
| global_opening_hours | verified correction | pass | pass |
| account_feedback | verified correction | pass | pass |

Neither record has a critical failure, and the merge canary is `refused`
(healthy) on both. **On today's labels, every critical case passes on both
picks.**

- Opus 5.5 passes only after B2. Its raw record showed one
  `critical_failure`; the audit read the committed text and found the check
  wrong, not the model.
- GPT-6.1 Sol's record never had a critical failure.
- The budget and unpriced refusals behaved as specified on both.
- The truncation check did not: both picks answered `skipped`, see below.

## Picks per preset and role (`resolve_models.py --apply`)

The run read the 2026-10-10T12:01Z payloads (`--fixture`). It rewrote
`snapshot.json` byte-identical (`b3196ae2`), and **did not write
`table.json`**, for two reasons.

1. **Economy's ceiling would rise from 10 to 14.** NARRATION's only passing
   arm is K3, billed at 14. A raised ceiling is never published, and
   `gates.check_table` refuses a ceiling above the one in force.
2. **DEDUP ranks a model the gates refuse.** DEDUP's threshold (24.4) admits
   unmeasured models with an intelligence score of 24.4 or more. The first
   is `inclusionai/ling-3.1-flash`, priced 0, and the static gate refuses
   it: "no positive input and output price". The candidate screen admits it
   and the gate refuses it.

A scratch copy with economy at 14 and `ling-3.1-flash` excluded wrote a
table that passes `gates.check_table`. These are therefore the only two
blockers. Neither change is committed: both are CTO decisions.

The picks on the resolver's report:

| Role | economy pick (raised to 14) | economy Anthropic | balanced pick (20) | balanced Anthropic |
|---|---|---|---|---|
| MNEMONIC | GPT-6.1 Sol | none | Opus 5.5 | Opus 5.5 |
| MEMORY_EXTRACT | deepseek-v4-flash | none | deepseek-v4-flash | Opus 5.5 |
| MEMORY_MERGE | GPT-6.1 Sol | none | Opus 5.5 | Opus 5.5 |
| TASK_DETECTION | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| REANALYZE | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| DEDUP | ling-3.1-flash (gate-refused; next ling-3.0-flash-vl, unmeasured) | Sonnet 5.5, Sonnet 5 | same | Sonnet 5.5, Sonnet 5, Sonnet 4.6, Opus 5.5 |
| REPLY_NEED | mimo-v2.6-flash | Sonnet 5.5 | mimo-v2.6-flash | Sonnet 5.5 |
| INTENT | mimo-v2.6-flash | Sonnet 5.5 | mimo-v2.6-flash | Sonnet 5.5 |
| CHAT | Sonnet 5.5 | Sonnet 5.5 | Opus 5.5 | Opus 5.5, Sonnet 5.5 |
| TASK_SOLVE | Sonnet 5.5 | Sonnet 5.5 | Opus 5.5 | Opus 5.5, Sonnet 5.5 |
| TRAIN | mimo-v2.6-flash | Sonnet 5.5 | mimo-v2.6-flash | Sonnet 5.5 |
| COMPACTION | mimo-v2.6-flash | Sonnet 5.5 | mimo-v2.6-flash | Sonnet 5.5 |
| SYNC_ANALYSIS | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| WEB_SEARCH | glm-5.3-flash | Sonnet 5.5 | glm-5.3-flash | Sonnet 5.5 |
| CORRECTION_LEARNING | mimo-v2.6-flash | Sonnet 5.5 | mimo-v2.6-flash | Sonnet 5.5 |
| NARRATION | K3 ($14, the raise) | **none** | K3 | **none** |

Empty Anthropic rankings:

- NARRATION, under both presets;
- the three memory roles under economy: Opus 5.5 is above 10, and Sonnet
  5.5 failed them.

A BYOK-Anthropic profile has no model for these roles. `table.json` stays
uncommitted on this branch; it ships with S6 at the switch-over.

## What this measurement does not certify

- **Small samples, one repetition.** Each role has 5 to 16 synthetic cases,
  answered once. The reference's second repetition was skipped. Where the
  reference scores 1.0, se is 0 and a single miss fails an arm. Reference
  noise decides CHAT's Anthropic ranking (above).
- **Unmeasured models above a threshold.** DEDUP's 24.4 is the lowest score
  of six arms that all passed. Every unmeasured model scoring 24.4 or more
  qualifies, which is how a zero-priced and a vision model reach the top.
- **Imputed agentic scores.** Opus's and Sonnet's agentic scores (60.4,
  58.3) are imputed from intelligence (sd 4.8), not published.
- **The truncation check.** M9's D6 check (decision `max_tokens` patched to
  16; refusal and `review_needed` expected) gave `review_needed` only on the
  two mimo arms. Seven arms answered `skipped` or `committed` in one call,
  Opus and GPT-6.1 Sol among them. Sonnet's committed decision returned 215
  output tokens. So the 16-token limit did not bind on OpenRouter for these
  models, and fail-closed truncation is unverified there. This is an engine
  question for the next slice, not a model score.
- **The extraction parser.** "SKIP + reason" and prose answers leave a source
  pending (above). Their cost is re-paid on every run.
- **The transports.** Everything ran through OpenRouter. The direct-Anthropic
  transport and the MrCall credits column (`mrcall_served`) were not
  measured.
- **Production equivalence.** These are synthetic cases built from the
  engine's real request shapes, not production traffic. Like the 2026-09
  comparisons, they do not establish production quality.
- **Uncertain holds.** The 2026-10-03 attempt's open intent (bound 0.877)
  and the rerun 3 Sonnet hold stay counted, not proven charged.
