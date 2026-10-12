# Role measurement: milestone 10's paid run and `measured.json`, 2026-10-11

Scope: the record of the one-off paid measurement behind
`engine/zylch/llm/roles/measured.json` (branch `m10-s4b10`, commit `679cfa47`).
The file is derived from committed data only:
`engine/tests/fixtures/measurement/records/2026-10-11/plan.json`. The code
that derives it is `fcd5a0a1`, `12ef7b08`, `f8e70f89` and `679cfa47`. It covers:

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
| `s4c`, `measure_roles.py`, 2026-10-04 | 12 roles with case sets. CHAT is excluded (old prompt). MiMo's stale-shape rows are superseded where MiMo was measured again. Both follow the selection rule below. | `8b18ea69` | `81998270` (read 2026-10-02T19:57Z) |
| `rerun3`, CHAT on today's prompt, 2026-10-11 | Sonnet 5.5, Qwen 3.8 Max, GLM 5.3, K3. Opus 5.5 is excluded (HTTP 402). | `1785352c` | `8df61cff` (read 2026-10-10T12:01Z, before S2's forced_tool change) |
| `rerun4`, CHAT, 2026-10-11 | Opus 5.5, K3 | `f827ae19` | `b3196ae2` |
| `rerun6`, the headroom re-measure, 2026-10-11 | NARRATION: every arm and K3. INTENT, WEB_SEARCH, TRAIN: MiMo flash, MiMo pro and K3. | `1221b0a4`, inferred (below) | `b3196ae2` |
| `rerun7`, the threshold entrants, 2026-10-11 | REANALYZE, DEDUP, INTENT, TRAIN: ling-3.0-flash-vl, deepseek-v4-flash-0731 and upstage/solar-pro4. REANALYZE and DEDUP also: mimo-v2.6-flash. K3 in every role. | `1221b0a4` (`head.txt`) | `b3196ae2` |
| `rerun8`, the D8 entrants, 2026-10-11 | DEDUP: gpt-6-luna, Sonnet 5, Sonnet 4.6, Opus 5.5. INTENT: Sonnet 5, Sonnet 4.6, Opus 5.5. TRAIN: gpt-6-luna, Sonnet 5, Sonnet 4.6, Opus 5.5. K3 in every role. | `1221b0a4` (`head.txt`) | `b3196ae2` |
| `corpus`, memory corpus (MNEMONIC, MEMORY_EXTRACT, MEMORY_MERGE) | The 2026-10-02 records of seven arms, mimo-pro's re-run (10-04, `e9bd6d02`) and Sonnet's (10-11c, `f827ae19`) | `8b18ea69` | `81998270` |

`measure_roles` records no commit. Rerun 6 started at 18:17Z, three minutes
after `1221b0a4` (the merge of the headroom fix), and no later commit exists
on the branch, so `1221b0a4` is the inferred commit. Every other commit is the
one the run recorded or the run script enforced.

The **build snapshot in force** is `b3196ae2…` (read 2026-10-10T12:01:52Z).
`measured.json` records each role's snapshot version(s).

`measured.json` was written by `scripts/derive_thresholds.py` alone, from
records committed byte for byte in
`engine/tests/fixtures/measurement/records/2026-10-11/`: the six runs'
`results.jsonl`, the nine corpus records, the arms documents, `plan.json`
and `exclusions.json`.

```
python scripts/derive_thresholds.py --plan tests/fixtures/measurement/records/2026-10-11/plan.json --write
```

Two tests guard it:

- `test_measurement_plan.py::test_the_committed_measured_json_is_derived_from_the_committed_plan`
  derives the plan and requires the committed file byte for byte. The
  derivation reads git history: the re-score and the shape check look up
  earlier committed versions.
- `check_measured` (`test_derive_thresholds.py`) passes: the hashes are
  today's `requests.json` and corpus prompts, and the passes, yardsticks
  and thresholds follow from the file's own results.

### The selection rule

S4b8 and S4b9 chose rows with an uncommitted script, which dropped every s4c
NARRATION row (IR3, blocking). Now a row leaves the derivation only in two
ways.

**By a rule in code.** `measurement_runs.supersede_stale` drops an arm's
stale-shape run only when the same arm has a complete current-shape run of
the role. A stale run is one the shape check refuses: see "The shaped
request" below. A current-shape row is never dropped, whatever its verdict.

**By a committed exclusion.** Each entry in `exclusions.json` states a claim
that `measurement_plan.apply_exclusions` verifies before it applies the
entry.

| Rows | Status | Rule or kind | Why |
|---|---|---|---|
| s4c CHAT, every arm | excluded | `prompt` | Measured on the replaced prompt `64a1a517`; today's is `c55f551c`. |
| rerun3 CHAT, Opus 5.5 | excluded | `denied` | chat-13 and chat-14 refused with HTTP 402 before inference; Opus answered in full in rerun4. |
| s4c NARRATION, MiMo flash and pro | superseded | stale shape | Re-measured in rerun6. |
| s4c NARRATION, deepseek, Sonnet 5.5, GLM-flash, K3 | **kept** | current shape | S4b8–S4b9 dropped them by hand; IR3's finding. |
| s4c INTENT, WEB_SEARCH, TRAIN, MiMo flash and pro | superseded | stale shape | Re-measured in rerun6. |
| s4c REANALYZE, DEDUP, MiMo-flash | superseded | stale shape | Re-measured in rerun7. |
| s4c other roles, MiMo; corpus, MiMo | kept, MiMo unmeasured | stale shape, no current run | MiMo is `incomplete` on these roles. |

**Index scores.** `arms-scores.json` (in `records/2026-10-11/arms/`)
holds the resolver's own index score for every model measured, from the
same 2026-10-10T12:01Z fixture the table is resolved on. The entrant arms
files of reruns 7 and 8 carried no score, so their rows had `arm_score`
null. `threshold_of` left those arms out of the ladder. In S4b8 this kept
DEDUP at a 24.4 threshold while mimo-v2.6-flash (37.9) and solar-pro4 (28.2)
failed it. `derive_thresholds` now fills a missing score from the `--arms`
files (`f8e70f89`) and never replaces a recorded one. Only the imputed
agentic scores of Opus and Sonnet differ between the two reads. They feed
CHAT and TASK_SOLVE, which are maximise roles with no threshold.

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
- REANALYZE, DEDUP, INTENT and TRAIN: rerun 7's entrants are judged against
  rerun 7's K3. DEDUP, INTENT and TRAIN: rerun 8's entrants are judged
  against rerun 8's K3.
- The corpus has one K3 record, 2026-10-02's, and each arm's record is its
  own pytest run. All nine records are therefore judged against that one K3
  record. There was no choice among K3 records.

### A reference that misses a bar

In rerun 7, K3 answered reanalyze-08 and reanalyze-18 without calling the
tool. Each answer was empty, so it missed both the `tool_called` and
`non_empty` bars and the label. Before S4b8, `derive_thresholds` built the
yardstick from the reference's label passes alone. Those two mechanical
failures would have counted as misses: p = 13/15, se 0.088. The run's arms
would then have been judged against 0.779, so 12 of 15 would have passed,
and nothing in the document said why.

What derive now does (`12ef7b08`, `measurement_runs.bar_misses` and
`yardstick_of`):

- **The yardstick credits the miss.** A reference case that misses a bar
  *and* the label counts as a pass for the yardstick. A bar failure can
  therefore never lower the bar the run's arms must clear. Rerun 7's
  REANALYZE yardstick is 15/15, 1.0 ± 0.
- **A bar missed on a matched label is not credited.** TASK_SOLVE's
  task_solve-09 language bar is one; its label pass is already counted.
- **The credited cases are named:** `reference.runs.rerun7.bar_misses_credited`.
- **The reference itself still fails the bar.** K3's own REANALYZE result in
  rerun 7 is 13/15 with a failed bar, so it does not pass there. Measured in
  two runs, it passes a role only when it passes in both, so **K3 fails
  REANALYZE**. Lower-scored arms pass where K3 does not, so the role becomes
  `measured_only`.

No other run's reference missed a bar on a missed label.

**An accepted deviation from D7.** D7 sets the yardstick at "the binomial
standard error of its score", the reference's score as recorded. The credit
departs from that literal reading on purpose. A reference that answered
nothing measured no judgement, and counting that as a miss would lower the
bar for its run's arms without anyone deciding so.

Its effect here is one yardstick: rerun 7's REANALYZE, 15/15, se 0, instead
of 13/15, se 0.088. **No verdict changed.** All four rerun 7 entrants scored
15/15, which passes either yardstick. Only the se went to 0.

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
profile's `llm_usage` and `llm_reservations` tables. IR3's ledger audit
confirmed the total: **USD 14.15 settled, 15.03 counting the aborted attempt
at its 0.97 bound.**

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
| Threshold entrants, rerun 7 | 0.745 | 221 intents, all settled |
| D8 entrants, rerun 8 | 1.831 | 151 intents, all settled, none open (cap 5.5) |
| **Total** | **14.15 settled; 15.03 counted** | Counted takes the aborted attempt at its 0.97 bound. Of the USD 20 the CTO approved. |

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
| REANALYZE | satisfice | s4c 15/15; rerun7 15/15 (2 bar misses credited) | measured_only | Sonnet, deepseek, glm-flash (s4c); ling-3.0-flash-vl, v4-flash-0731, solar-pro4, mimo-flash (rerun7) | **K3** (bar in rerun7) | mimo-pro | Sonnet 5.5 |
| DEDUP | satisfice | s4c, rerun7, rerun8 14/14 | measured_only | Sonnet 5.5, deepseek, glm-flash (s4c); ling-3.0-flash-vl, v4-flash-0731 (rerun7); gpt-6-luna, Sonnet 5, Sonnet 4.6, Opus 5.5 (rerun8); K3 | solar-pro4 13/14, mimo-flash (critical, bars) | mimo-pro | Sonnet 5.5, Sonnet 5, Sonnet 4.6, Opus 5.5 |
| REPLY_NEED | satisfice | s4c 13/14 | measured_only | Sonnet, glm-flash | deepseek, K3 (critical) | mimo flash, pro | Sonnet 5.5 |
| INTENT | satisfice | s4c, rerun6, rerun7, rerun8 14/14 | measured_only | Sonnet 5.5, deepseek, glm-flash (s4c); mimo flash, pro (rerun6); ling-3.0-flash-vl, v4-flash-0731 (rerun7); Sonnet 5, Sonnet 4.6, Opus 5.5 (rerun8); K3 | solar-pro4 (bar, 13/14) | – | Sonnet 5.5, Sonnet 5, Sonnet 4.6, Opus 5.5 |
| CHAT | maximise | rerun3 10/11 (0.909 ± 0.087); rerun4 11/11 | – | Sonnet 10/11, Qwen 11/11, GLM 5.3 11/11 (rerun3); K3 (both) | **Opus 5.5 10/11 (rerun4)** | – | Sonnet 5.5 |
| TASK_SOLVE | maximise | s4c 10/11 | – | Opus, Sonnet, GLM 5.3 | K3, Qwen (bar) | – | Opus, Sonnet |
| TRAIN | satisfice | s4c, rerun6, rerun7, rerun8 5/5 | measured_only | Sonnet 5.5, deepseek, glm-flash (s4c); mimo flash, pro (rerun6); ling-3.0-flash-vl (rerun7); gpt-6-luna, Sonnet 5, Sonnet 4.6 (rerun8); K3 | **Opus 5.5** (5/5, a bar, rerun8), v4-flash-0731, solar-pro4 (bars) | – | Sonnet 5.5, Sonnet 5, Sonnet 4.6 |
| COMPACTION | satisfice | s4c 5/5 | measured_only | Sonnet, deepseek, K3 | glm-flash (bar) | mimo flash, pro | Sonnet 5.5 |
| SYNC_ANALYSIS | satisfice | s4c 13/14 | measured_only | Sonnet, deepseek, K3 | glm-flash | mimo flash, pro | Sonnet 5.5 |
| WEB_SEARCH | satisfice | s4c 5/5; rerun6 5/5 | measured_only | Sonnet, glm-flash (s4c); mimo-flash (rerun6); K3 | deepseek (critical), mimo-pro (bar) | – | Sonnet 5.5 |
| CORRECTION_LEARNING | satisfice | s4c 14/14 | measured_only | Sonnet, deepseek, K3 | glm-flash | mimo flash, pro | Sonnet 5.5 |
| NARRATION | satisfice | s4c 5/5; rerun6 5/5 | measured_only | K3 10/10 (both); mimo-pro 5/5 (rerun6) | **deepseek-v4-flash 9/10** (bar: s4c narration-04, empty), Sonnet, mimo-flash, glm-flash (bars) | – | **empty** |

"Bar" means a mechanical bar was missed: truncation, language, a tool not
called, or an operation left pending. The reference fails three roles itself:
REPLY_NEED (critical), TASK_SOLVE (a bar) and REANALYZE (its rerun 7 bar).

**NARRATION (S4b10).** deepseek-v4-flash's s4c NARRATION request is today's
request, so its s4c rows count. On narration-04 it spent 1064 output tokens
thinking, reached `max_tokens` and returned empty text, so it missed the
non-empty bar (4/5). In rerun 6 it scored 5/5. Measured in two runs, it
passes only when it passes in both, the rule that fails K3 on REANALYZE. So
**deepseek fails NARRATION**. S4b8–S4b9 had passed it only because the s4c
rows were dropped by hand. NARRATION's pick moves to mimo-v2.6-pro (below).

**Thresholds.** With every measured arm's index score in the ladder, **every
satisfice role is `measured_only`**: in each, an arm fails while a
lower-scored arm passes. Only measured, passing models rank, so no threshold
admits an unmeasured model.

- REANALYZE: K3 (43.6) fails on its rerun 7 bar.
- DEDUP: mimo-flash (37.9) and solar-pro4 (28.2) fail.
- INTENT: solar-pro4 fails.
- TRAIN: Opus 5.5 (57.6), v4-flash-0731 (34.3) and solar-pro4 fail.

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

The resolve ran on **the requirements in force after S6**, which removes the
allowlist and `mrcall_served`. It used the S6 candidate's
`requirements.json` (sha256 `91f20375…`), resolver and roles code, with
this `measured.json`, on the 2026-10-10T12:01Z payloads (`--fixture`). The
table's `requirements_sha256` therefore matches what ships. The roster,
rules and reference in those requirements are the same as before S6, so the
derivation does not change. `snapshot.json` was rewritten byte-identical
(`b3196ae2`). **The table was written and passes both checks:**

- `table.json` version `304ab3b7…`; its `requirements_sha256` is
  `91f203752a717456df4ffa61d6b1ea680288d16a025dc01a358edca8ad11e5f6`, and
  its `measured_sha256` is `403601759cfe…`;
- `gates.check_table` passes;
- D8 holds: 0 ranked entries are unmeasured or failing.

It is not committed: it lands with S6 at the switch-over. It is saved at
`scratchpad/s4b10/table.json`, sha256
`9d40bbf363670c4dd5b964af19b5088d66884155513825c3bb1980eea47c1c15`. The
table stamps `resolved_at`, so another `--apply` gives another sha256.

**D8** is the rule the daily job applies: no unmeasured model enters a
published satisfice ranking for the first table. It took two rounds:

- **S4b8:** rerun 7's failures let four unmeasured models move up: gpt-6-luna,
  Sonnet 5, Sonnet 4.6, and Opus 5.5 on these roles.
- **Rerun 8:** measured all four. All passed, except Opus 5.5 on TRAIN.

Every entry of every ranking and every Anthropic ranking under both presets
is now a model `measured.json` shows measured and passing; the check found
0 exceptions. Opus's TRAIN failure removed Opus from TRAIN's balanced
Anthropic ranking and pulled no new model in. Every satisfice role is
`measured_only`, so none can.

Changes against S4b9's table:

- **NARRATION's pick moves from deepseek-v4-flash to mimo-v2.6-pro** under
  both presets (above).
- Opus 5.5 leaves TRAIN's balanced Anthropic ranking.
- No other pick or Anthropic head changes.

The economy ceiling stays at 10: NARRATION has mimo-v2.6-pro under it. The
zero-priced model is screened out (`558ff4ad`).

| Role | Economy pick (10) | Economy Anthropic head | Balanced pick (20) | Balanced Anthropic head |
|---|---|---|---|---|
| MNEMONIC | GPT-6.1 Sol | **none** | Opus 5.5 | Opus 5.5 |
| MEMORY_EXTRACT | deepseek-v4-flash | **none** | deepseek-v4-flash | Opus 5.5 |
| MEMORY_MERGE | GPT-6.1 Sol | **none** | Opus 5.5 | Opus 5.5 |
| TASK_DETECTION | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| REANALYZE | ling-3.0-flash-vl | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| DEDUP | ling-3.0-flash-vl | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| REPLY_NEED | glm-5.3-flash | Sonnet 5.5 | glm-5.3-flash | Sonnet 5.5 |
| INTENT | ling-3.0-flash-vl | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| CHAT | Sonnet 5.5 | Sonnet 5.5 | Sonnet 5.5 | Sonnet 5.5 |
| TASK_SOLVE | Sonnet 5.5 | Sonnet 5.5 | Opus 5.5 | Opus 5.5 |
| TRAIN | ling-3.0-flash-vl | Sonnet 5.5 | ling-3.0-flash-vl | Sonnet 5.5 |
| COMPACTION | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| SYNC_ANALYSIS | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| WEB_SEARCH | mimo-v2.6-flash | Sonnet 5.5 | mimo-v2.6-flash | Sonnet 5.5 |
| CORRECTION_LEARNING | deepseek-v4-flash | Sonnet 5.5 | deepseek-v4-flash | Sonnet 5.5 |
| NARRATION | **mimo-v2.6-pro** | **none** | **mimo-v2.6-pro** | **none** |

**Empty Anthropic rankings:**

- NARRATION, under both presets;
- MNEMONIC, MEMORY_EXTRACT and MEMORY_MERGE under economy: Opus 5.5 is above
  10, and Sonnet 5.5 failed them.

**ling-3.0-flash-vl is now measured.** In S4b7, REANALYZE, DEDUP, INTENT and
TRAIN picked it unmeasured through the 24.4 threshold. Rerun 7 measured it
against K3 in the same run, and it passes all four at full marks.

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
  CHAT, Opus fails because rerun 4's K3 answered chat-09, which rerun 3's K3
  missed. In NARRATION, deepseek fails on one empty answer in one run.
- **The first table ranks only measured models; the daily job does not stop
  there.** Every satisfice role is `measured_only`, so this hand-resolved
  table ranks only models measured here. The daily job
  (`model_table_decide.view`) treats every pool model without a recorded
  result as a challenger that would pass in a role that ranks only passing
  models. A cheaper unmeasured model is therefore considered: it is smoked
  and measured before it may enter.
- **The job's backlog.** On its first run against this record, the IR3 dry
  run listed 128 entrant smokes, plus a CHAT measurement deferred as over
  the per-role cap. The budget is USD 10 a month (`MONTHLY_CAP_USD`), with
  at most USD 2 per role measurement and USD 0.20 per smoke admitted
  (about USD 0.05 expected). So the backlog takes months, not one run.
  The job makes checks in this priority order:
  - urgency first: an empty ranking or a pick that failed a gate, then a
    challenger to a pick, then an entrant lower in a ranking;
  - then the roster's role order, then the preset (economy before balanced),
    then the main ranking before the Anthropic one.
  A check the month cannot cover is deferred, and its entrant is skipped.
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
