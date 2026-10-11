# Role measurement: milestone 10's paid run and `measured.json`, 2026-10-11

Scope: the record of the one-off paid measurement behind
`engine/zylch/llm/roles/measured.json` (branch `m10-s4b7`, commit `61ff02e0`;
the code that derives it is `fcd5a0a1`). It covers:

- what was run, on which prompts, snapshots and commits, and what it cost;
- the per-run reference rule and the shaped-request check;
- each role's result;
- the audit and its fixes;
- the CHAT re-measure, the headroom re-measure and the 402 incident;
- the resolver's table, mnemonic AC 5, and what the measurement does not
  certify.

The method is in
[`engine/tests/fixtures/measurement/README.md`](../../engine/tests/fixtures/measurement/README.md).
The role, rule and table contract is in
[model selection](../../engine/docs/features/model-selection.md).

## What was measured

| Run | Rows used | Engine commit | Snapshot |
|---|---|---|---|
| `s4c`, `measure_roles.py`, 2026-10-04 | 10 roles with case sets. Not used: CHAT (old prompt) and NARRATION (re-measured). MiMo flash/pro on INTENT, WEB_SEARCH and TRAIN were also re-measured; their old rows are not used. | `8b18ea69` | `81998270` (read 2026-10-02T19:57Z) |
| `rerun3`, CHAT on today's prompt, 2026-10-11 | Sonnet 5.5, Qwen 3.8 Max, GLM 5.3, K3 | `1785352c` | `8df61cff` (read 2026-10-10T12:01Z, before S2's forced_tool change) |
| `rerun4`, CHAT, 2026-10-11 | Opus 5.5, K3 | `f827ae19` | `b3196ae2` |
| `rerun6`, the headroom re-measure, 2026-10-11 | NARRATION: every arm and K3. INTENT, WEB_SEARCH, TRAIN: MiMo flash, MiMo pro and K3. | `1221b0a4`, inferred (below) | `b3196ae2` |
| `corpus`, memory corpus (MNEMONIC, MEMORY_EXTRACT, MEMORY_MERGE) | The 2026-10-02 records of seven arms, mimo-pro's re-run (10-04, `e9bd6d02`) and Sonnet's (10-11c, `f827ae19`) | `8b18ea69` | `81998270` |

`measure_roles` records no commit. Rerun 6 started at 18:17Z, three minutes
after `1221b0a4` (the merge of the headroom fix), and no later commit exists
on the branch, so `1221b0a4` is the inferred commit. Every other commit is the
one the run recorded or the run script enforced.

The **build snapshot in force** is `b3196ae2…` (read 2026-10-10T12:01:52Z).
`measured.json` records each role's snapshot version(s).

`measured.json` was written by `scripts/derive_thresholds.py` alone, from the
row sets in `scratchpad/s4b7/runs/`:

```
derive_thresholds.py --arms arms-final.json
  --run s4c@8b18ea69=s4c.jsonl  --run rerun3@1785352c=rerun3.jsonl
  --run rerun4@f827ae19=rerun4.jsonl  --run rerun6@1221b0a4=rerun6.jsonl
  --corpus corpus=<nine manifests>
  --rescore --rescore-from fa1518f0… acb2e224… --shape-check
```

`check_measured` passes. Its hashes are today's `requests.json` and corpus
prompts, and its passes, yardsticks and thresholds follow from its own
results.

## Each arm against the reference of its own run

D7 judges an arm against "the binomial standard error of its score, from the
same run". S4b6 instead judged every CHAT arm against one K3 run, chosen
afterwards. K3 scored 10/11 in rerun 3 and 11/11 in rerun 4, so that choice
alone decided whether Opus passed CHAT.

The rule is now general (`scripts/measurement_runs.py`):

- each run where K3 is complete is a yardstick;
- each arm is judged against its own run's yardstick, and the result records
  it as `judged_by`;
- the role's `reference.runs` lists every yardstick.

The rule applied to this data:

- CHAT: Opus 5.5 (rerun 4) is judged against K3 11/11, and its 10/11 fails.
  Sonnet 5.5, Qwen and GLM 5.3 (rerun 3) are judged against K3 10/11 and
  pass.
- INTENT, WEB_SEARCH and TRAIN: MiMo is judged against rerun 6's K3, the
  other arms against s4c's K3.
- The corpus has one K3 record, 2026-10-02's, and each arm's record is its
  own pytest run. All nine records are therefore judged against that one K3
  record. There was no choice among K3 records.

## The shaped request

The re-score compares the captured request, before the shape, case by case
against the `requests.json` committed at each run's commit. It refused
nothing.

The engine then shapes every request from the snapshot's metadata
(`request_shape.py`). The headroom fix (`bf9b520d`, `ced704cb`) changed that
shape: MiMo v2.6 publishes a `reasoning` parameter and now gets `max_tokens +
1024` on every role.

`--shape-check` (`scripts/measurement_shape.py`) therefore shapes each row
twice:

- **as it was sent:** with `request_shape.py` as committed at the run's
  commit, and the snapshot version the row records;
- **as it would be sent today:** with this checkout's code and the build
  snapshot.

A corpus row is compared on a probe of the decision call. The comparison
gave:

- **Every MiMo v2.6 row outside rerun 6 is stale**: TASK_DETECTION,
  REANALYZE, DEDUP, REPLY_NEED, COMPACTION, SYNC_ANALYSIS, CORRECTION_LEARNING
  and the three corpus roles. MiMo is therefore unmeasured (`incomplete`) in
  those roles, not failed. Its cases are named in `shape_refused`.
- **Every other arm's shaped request is today's.** deepseek's CHAT tools did
  differ under the 2026-10-02 snapshot, but CHAT was measured on rerun 3 and
  rerun 4.

The check covers the request the model receives. It does not cover the
transport's routing and caps (provider object, `max_price`).

## Spend

Checked against the ledgers: `measure_roles`'s `ledger.jsonl`, and each corpus
profile's `llm_usage` and `llm_reservations` tables.

| Item | USD | Source |
|---|---|---|
| 2026-10-03 aborted attempt (K3 corpus) | 0.97 counted | 0.093 settled. 0.877 is an open intent's bound. |
| Corpus, nine arms (2026-10-02 records) | 1.299 | the manifests' `totals_usd.settled` |
| Roles with case sets (2026-10-04) | 5.478 | 961 intents, all settled |
| Sonnet corpus attempt, 2026-10-04 (cases refused by a 0.40 cap) | 0.016 | checks only |
| mimo-v2.6-pro corpus re-run | 0.034 | |
| CHAT rerun 3 | 2.293 | 91 settled; 2 failed with HTTP 402, nothing charged |
| CHAT rerun 4 | 1.520 | |
| Sonnet corpus, rerun 3 (402) | 0 settled | The 402 came before any work. The hold predates S3e's release. |
| Sonnet corpus, rerun 4 (stopped by its 0.60 cap) | 0.095 | cases 0.077, checks 0.017 |
| Sonnet corpus, rerun 5 (the record used) | 0.157 | |
| Headroom re-measure, rerun 6 | 0.591 | 102 intents, all settled |
| **Total** | **11.58 settled; 12.45 counted** | Counted takes the aborted attempt at its 0.97 bound. Of the USD 20 the CTO approved. |

The 2026-10-03 rehearsal ledger's 4.57 is a dry run's scripted receipts, not
spend.

## Per-role result

An arm passes when it is complete, meets every mechanical bar, has no
critical failure and scores at least p − se of its own run's K3.

- A maximise role ranks the arms that pass.
- A satisfice role's threshold is the lowest index score at and above which
  every measured arm passes. When index score and result disagree, the role
  is `measured_only`.

| Role | Rule | K3 yardstick per run | Threshold | Passing (run) | Failing | Unmeasured (stale) | Anthropic passing |
|---|---|---|---|---|---|---|---|
| MNEMONIC | maximise | corpus 10/10 | – | Opus 5.5, K3, GPT-6 Sol, GPT-6.1 Sol | Sonnet 5.5 (bar), deepseek (critical), glm-flash | mimo flash, pro | Opus 5.5 |
| MEMORY_EXTRACT | satisfice | corpus 6/6 | measured_only | Opus, deepseek, K3, GPT-6 Sol, GPT-6.1 Sol | Sonnet (bar), glm-flash | mimo flash, pro | Opus 5.5 |
| MEMORY_MERGE | maximise | corpus 7/7 | – | Opus, deepseek, K3, GPT-6 Sol, GPT-6.1 Sol | Sonnet (bar), glm-flash | mimo flash, pro | Opus 5.5 |
| TASK_DETECTION | satisfice | s4c 16/16 | measured_only | Sonnet, deepseek, K3 | glm-flash (bar) | mimo flash, pro | Sonnet 5.5 |
| REANALYZE | satisfice | s4c 15/15 | **24.4** | Sonnet, deepseek, K3, glm-flash | – | mimo flash, pro | Sonnet 5.5 |
| DEDUP | satisfice | s4c 14/14 | **24.4** | Sonnet, deepseek, K3, glm-flash | – | mimo flash, pro | Sonnet 5.5 |
| REPLY_NEED | satisfice | s4c 13/14 | measured_only | Sonnet, glm-flash | deepseek, K3 (critical) | mimo flash, pro | Sonnet 5.5 |
| INTENT | satisfice | s4c 14/14; rerun6 14/14 | **24.4** | Sonnet, deepseek, glm-flash (s4c); mimo flash, pro (rerun6); K3 (both) | – | – | Sonnet 5.5 |
| CHAT | maximise | rerun3 10/11 (0.909 ± 0.087); rerun4 11/11 | – | Sonnet 10/11, Qwen 11/11, GLM 5.3 11/11 (rerun3); K3 (both) | **Opus 5.5 10/11 (rerun4)** | – | Sonnet 5.5 |
| TASK_SOLVE | maximise | s4c 10/11 | – | Opus, Sonnet, GLM 5.3 | K3, Qwen (bar) | – | Opus, Sonnet |
| TRAIN | satisfice | s4c 5/5; rerun6 5/5 | **24.4** | Sonnet, deepseek, glm-flash (s4c); mimo flash, pro (rerun6); K3 | – | – | Sonnet 5.5 |
| COMPACTION | satisfice | s4c 5/5 | measured_only | Sonnet, deepseek, K3 | glm-flash (bar) | mimo flash, pro | Sonnet 5.5 |
| SYNC_ANALYSIS | satisfice | s4c 13/14 | measured_only | Sonnet, deepseek, K3 | glm-flash | mimo flash, pro | Sonnet 5.5 |
| WEB_SEARCH | satisfice | s4c 5/5; rerun6 5/5 | measured_only | Sonnet, glm-flash (s4c); mimo-flash (rerun6); K3 | deepseek (critical), mimo-pro (bar) | – | Sonnet 5.5 |
| CORRECTION_LEARNING | satisfice | s4c 14/14 | measured_only | Sonnet, deepseek, K3 | glm-flash | mimo flash, pro | Sonnet 5.5 |
| NARRATION | satisfice | rerun6 5/5 | measured_only | deepseek, K3, mimo-pro | Sonnet, mimo-flash, glm-flash (bar) | – | **empty** |

"Bar" means a mechanical bar was missed: truncation, language, a tool not
called, or an operation left pending. The reference fails two roles itself:
REPLY_NEED (critical) and TASK_SOLVE (a bar).

**REANALYZE, INTENT and TRAIN gain a threshold of 24.4.** In REANALYZE every
remaining measured arm passes once MiMo is unmeasured. In INTENT and TRAIN,
MiMo passes with the headroom.

## The audit and its fixes

Every failing cell of the 2026-10-04 run was read by hand: 49 cells.

| Class | Cells |
|---|---|
| A, a genuine model failure | 24 |
| B, a scorer bug | 3 |
| C, a label or case error | 9 |
| D, truncation at `max_tokens` | 7 |
| Unresolved: an extraction left pending, raw output not recorded | 6 |

Fixed in S4b5 (`e9bd6d02`):

- **B1**: a text with no function-word hit skips the language bar and label.
- **B2**: the "child inherited the sender's identity" check reads only the
  identifier header's email.
- **C1**: `must_preserve` accepts either language.
- **C2**: REVIEW is allowed where the M9 prompt prescribes it.
- **C3**: sync_analysis-11's `critical_on` is `["invalid"]`.
- **C4**: an address the answer calls wrong is a counter-example.
- **C5**: `run_python` is not an `unmatched_write`.

S4b6 (`a7d53054`) made `--rescore` reach the rows a scorer fix changes no
hash for. `rescored_from.*.verdicts_changed` lists each changed verdict.

The truncation cells (D) the audit examined were MiMo spending its whole
`max_tokens` on reasoning, on INTENT, WEB_SEARCH and TRAIN. The headroom fix
addresses them, and rerun 6 re-measured those roles together with NARRATION. The six
unresolved cells were recorded on re-run: "SKIP + reason" or prose, which the
worker refuses.

## The 402 incident (2026-10-11)

During CHAT rerun 3 the OpenRouter account ran out of credit:

- Opus's chat-13 and chat-14 got HTTP 402 before any inference;
- the Sonnet corpus re-run's first case got the same.

S3e (`fe528f9c`) fixed the handling. A 402 now releases its hold, settles at
zero as `denied`, and stops the run. Rerun 4 completed Opus after the
top-up.

## Trims and reserve (IR2)

The case sets were trimmed to fit the projection under USD 16, by the
fixtures README's deterministic rule.

| Measured / reserve | Roles |
|---|---|
| 16 / 6 | TASK_DETECTION |
| 15 / 5 | REANALYZE |
| 14 / 7 | DEDUP |
| 14 / 6 | REPLY_NEED, INTENT, SYNC_ANALYSIS |
| 14 / 10 | CORRECTION_LEARNING |
| 11 / 3 | CHAT (reviewed exception: chat-07 kept, chat-06 reserved) |
| 11, untrimmed | TASK_SOLVE |
| 5, untrimmed | COMPACTION, NARRATION, TRAIN, WEB_SEARCH |

The corpus is 10 live cases plus four checks. Every critical case was kept by
rule.

## The table (`resolve_models.py --apply`)

The resolver ran on the 2026-10-10T12:01Z payloads (`--fixture`):

- `snapshot.json` was rewritten byte-identical (`b3196ae2`);
- **`table.json` was written** (version `c6d9e9f2…`), and
  `gates.check_table` passes;
- `table.json` is not committed: it lands with S6 at the switch-over. A
  copy is in `scratchpad/s4b7/table.json`.

Both S4b6 blockers are gone. Economy's ceiling stays at 10, because
NARRATION now has deepseek-v4-flash and mimo-v2.6-pro. The zero-priced model
is screened out (`558ff4ad`).

| Role | Economy pick (10) | Economy Anthropic head | Balanced pick (20) | Balanced Anthropic head |
|---|---|---|---|---|
| MNEMONIC | GPT-6.1 Sol | **none** | Opus 5.5 | Opus 5.5 |
| MEMORY_EXTRACT | deepseek-v4-flash | **none** | deepseek-v4-flash | Opus 5.5 |
| MEMORY_MERGE | GPT-6.1 Sol | **none** | Opus 5.5 | Opus 5.5 |
| TASK_DETECTION | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| REANALYZE | ling-3.0-flash-vl (unmeasured) | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| DEDUP | ling-3.0-flash-vl (unmeasured) | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| REPLY_NEED | glm-5.3-flash | Sonnet 5.5 | glm-5.3-flash | Sonnet 5.5 |
| INTENT | ling-3.0-flash-vl (unmeasured) | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| CHAT | Sonnet 5.5 | Sonnet 5.5 | Sonnet 5.5 | Sonnet 5.5 |
| TASK_SOLVE | Sonnet 5.5 | Sonnet 5.5 | Opus 5.5 | Opus 5.5 |
| TRAIN | ling-3.0-flash-vl (unmeasured) | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| COMPACTION | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| SYNC_ANALYSIS | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| WEB_SEARCH | mimo-v2.6-flash | Sonnet 5.5 | mimo-v2.6-flash | Sonnet 5.5 |
| CORRECTION_LEARNING | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| NARRATION | deepseek-v4-flash | **none** | deepseek-v4-flash | **none** |

**Empty Anthropic rankings:**

- NARRATION, under both presets;
- MNEMONIC, MEMORY_EXTRACT and MEMORY_MERGE under economy: Opus 5.5 is above
  10, and Sonnet 5.5 failed them.

**Four roles pick an unmeasured model.** In REANALYZE, DEDUP, INTENT and TRAIN
the threshold of 24.4 admits every model with an intelligence score at or
above it. The cheapest such model is `inclusionai/ling-3.0-flash-vl` (24.6,
USD 0.06 output), a vision variant this measurement never ran. This is the
satisfice threshold working as specified, and a product decision before S6.

## Mnemonic AC 5 on the measured picks

M9's AC 5 ("every critical case passes") failed on 2026-10-01 on the rejected
Haiku arm. The table's MNEMONIC picks are Opus 5.5 (balanced) and GPT-6.1
Sol (economy). The second-ranked models are GPT-6.1 Sol and GPT-6 Sol
respectively. Both picks' corpus records, judged on today's labels against
the corpus K3:

| Case | Class | Opus 5.5 (balanced) | GPT-6.1 Sol (economy) |
|---|---|---|---|
| unrelated_same_name_people | automatic | pass | pass (was noncritical: C2) |
| shared_switchboard | automatic | pass | pass |
| corroborated_same_person | automatic | pass | pass |
| planned_not_completed | automatic | pass (was noncritical: C2) | pass (was noncritical: C2) |
| contradictory_legacy_fact_rule | automatic | pass | pass |
| multi_entity_source | automatic | pass (**was critical_failure: B2**) | pass |
| customer_forwarding_number_correction | verified correction | pass (was noncritical: C1/C2) | pass (was noncritical: C1/C2) |
| customer_price_correction | verified correction | pass (was noncritical: C1) | pass (was noncritical: C1) |
| global_opening_hours | verified correction | pass | pass |
| account_feedback | verified correction | pass | pass |

**Every critical case passes on both picks.** The merge canary is `refused`
(healthy), and the budget and unpriced refusals behave as specified.

- Opus 5.5 passes only after B2. Its raw `critical_failure` was the check
  matching a sentence in which Opus disowned the sender's address.
- Neither pick's shaped request changed.
- The truncation check did not bind for either pick (below).

## What this measurement does not certify

- **Small samples, one repetition.** Each role has 5 to 16 synthetic cases,
  answered once. Where K3 scores 1.0, se is 0 and one miss fails an arm. In
  CHAT, Opus's pass turns on rerun 4's K3 answering chat-09, which rerun 3's
  K3 missed.
- **Unmeasured models above a threshold.** See the four ling-3.0-flash-vl
  picks above.
- **Imputed agentic scores.** Opus's and Sonnet's agentic scores (60.4,
  58.3) are imputed from intelligence.
- **The truncation check.** M9's D6 check patches the decision call's
  `max_tokens` to 16. It gave `review_needed` only on the MiMo arms; Sonnet
  committed with 215 output tokens. On OpenRouter the 16-token limit did not
  bind for seven of nine arms.
- **The extraction parser.** "SKIP + reason" and prose answers leave a
  source pending, and their cost is re-paid on every run.
- **MiMo on the roles it was not re-measured on** is unmeasured, not failed.
  So is MiMo on the memory roles.
- **The transports.** Everything ran through OpenRouter. The direct-Anthropic
  transport and the MrCall credits column were not measured.
- **Production equivalence.** These are synthetic cases built from the
  engine's real request shapes, not production traffic.
- **Uncertain holds.** The 2026-10-03 open intent (0.877) stays counted, not
  proven charged.
