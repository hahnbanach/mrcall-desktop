# Role measurement — case sets and tooling

Scope: how milestone 10 measures each role's models (brief D7, plan S4) with
the case sets in this directory, from the captured requests to
`zylch/llm/roles/measured.json`. Each `<ROLE>/README.md` documents its own
cases, labels and scoring; the scripts' docstrings are the contract.

## What is here

Per role: `README.md`, `cases.json` (synthetic inputs, reviewed labels,
`critical_on`, `expect_lang`), `capture.py` (drives the engine's own code
path with a recording client), `requests.json` (what that path sends today),
and for the task roles `score.py`. `MNEMONIC`, `MEMORY_EXTRACT` and
`MEMORY_MERGE` are measured on the milestone 9 corpus
(`tests/fixtures/mnemonic/`) by `tests/memory/test_mnemonic_corpus_live.py`.

## The flow

| Step | Command (from `engine/`) | Paid |
|---|---|---|
| Capture the requests with today's prompts | `python scripts/build_measurement_requests.py` (`--check` compares) | no |
| Choose the arms | `python scripts/resolve_models.py --bootstrap > ARMS.json` | no |
| Project the cost | `python scripts/measure_roles.py --arms ARMS.json --project` | no |
| Trim a case set to fit IR2 (below) | `python scripts/trim_measurement_cases.py --role R --keep N` (`--plan --arms ARMS.json` first; `--restore` undoes) | no |
| Rehearse | `python scripts/measure_roles.py --arms ARMS.json --out DIR --dry-run` | no |
| Measure the roles with case sets | `python scripts/measure_roles.py --arms ARMS.json --out DIR --cap 20` | yes |
| Measure the memory roles, one run per arm | `MNEMONIC_CORPUS_EXECUTE=1 MNEMONIC_CORPUS_ARMS=ARMS.json MNEMONIC_CORPUS_ARM=<id> MNEMONIC_CORPUS_PROFILE_DIR=… MNEMONIC_CORPUS_CAP_USD=… pytest tests/memory/test_mnemonic_corpus_live.py` | yes |
| Derive the thresholds | `python scripts/derive_thresholds.py --arms ARMS.json --results DIR/results.jsonl --corpus REC/*-manifest.json --write` | no |

Keys come from the environment only (`OPENROUTER_API_KEY`), are written to a
disposable profile's `.env` (mode 600, deleted after) and never printed.

## Trimming a case set (IR2)

When the projection's expected spend is over USD 16 (the cap less 20 %), the
plan reduces case counts before any paid call, never below 12 cases for a
decision role and 5 for CHAT and TASK_SOLVE. The smokes and the corpus
roles are not trimmed. `scripts/trim_measurement_cases.py --role R --keep N`
moves the cases that are not kept from `R/cases.json` to `R/reserve.json` and
captures `R/requests.json` again, so `case_set_sha256` covers the kept set.
The one-off run and the daily job then measure the same cases.

The selection is deterministic: it depends only on the authored cases and N.

1. Every case with a non-empty `critical_on` is kept.
2. For each value of the role's decision field, two cases are kept, or all of
   them when the value has fewer than two. The decision field is the label
   class the case files' balance tests count:
   - TASK_DETECTION: `task_action`;
   - REANALYZE: `action`;
   - DEDUP: duplicates or distinct, per call site;
   - REPLY_NEED: `needs_reply`;
   - INTENT: `primary_skill`;
   - CORRECTION_LEARNING: the judge and its must-record flag;
   - SYNC_ANALYSIS: the `expected_action` of a thread that needs action, else
     none;
   - CHAT and TASK_SOLVE: none.
3. The remaining cases are added one at a time until there are N.

Each pick after step 1 takes the input language (`lang`) with fewer cases
kept so far, and in it the lowest-numbered id. A tie goes to the
lowest-numbered id of either language. The languages therefore end as near
equal as the counts allow, and the highest-numbered ids go to the reserve
first.

The tool refuses, and writes nothing, when:

- N is below the minimum;
- N is below the number of critical cases;
- N is below what steps 1 and 2 must keep (the message gives that floor);
- N is above the number of authored cases;
- the role has no minimum.

`--plan` prints the moves and, with `--arms`, each arm's projection delta,
without writing anything. `--restore` gives back the files byte for byte.

The reserve stays authored and reviewed. The case files' own tests read
`cases.json` together with `reserve.json` (`tests/measurement/case_sets.py`).
Captures, replays and hashes read `cases.json` alone.

## Requests and hashes

`requests.json` is `{"schema": 1, "role", "prompt_sha256", "case_set_sha256",
"requests": [{"case_id", "request", "capture_now"}]}`. A harness that yields
no request or more than one for a case is refused. `case_set_sha256` is the
SHA-256 of `cases.json`; `prompt_sha256` covers each request's template
(system, messages, tools, tool choice, `max_tokens`) with the case's own
strings replaced, so it moves with a prompt and not with case data or the
order a trainer lists case items in (`scripts/measurement_common.py` says
exactly what is hashed). `tests/measurement/test_build_measurement_requests.py`
fails when a committed `requests.json` no longer matches a fresh capture.
TRAIN's trainers list contacts, greetings and languages from sets, whose
order follows the process's hash seed. Its capture harness sorts them (in
the capture only; production is unchanged), and the same test checks that
two processes with different seeds capture the same bytes.

## The measurement

Each arm (the bootstrap's plus the reference, K3, run first in every role)
answers each case through the engine's real OpenRouter transport: the model
is the arm's, the request shaped as production shapes it, K3 through its
adapter, the datetime line pinned to the case's `capture_now`. CHAT and
TASK_SOLVE continue the turn through their harness's `run_case`. Before each
dispatch the engine's reservation bound is checked against the cap with
everything spent or uncertain and written to `DIR/ledger.jsonl` as an
intent; the receipt settles it.

A provider sometimes refuses a dispatch before doing any work. An example is
a 429 when an upstream provider's shared pool is saturated, which
`zylch.llm.client._rejected_before_inference` recognises. Such a dispatch:

- is settled at zero, with outcome `refused`, and the cap counts it at zero;
- has its cell sent once more at the end of the role's pass, as a second
  intent, waiting at least the provider's `retry_after` or 5 s, whichever is
  longer;
- if refused a second time, leaves the cell failed and the arm incomplete.

In CHAT and TASK_SOLVE a refusal is sent again only when it hit the turn's
first dispatch. A refusal later in the turn follows dispatches already paid
for, which a second attempt would repeat, so the cell stays failed. A 401
or 403 means the key itself was refused: the run stops with that message,
and the cell is settled at zero and never sent again.

Every other failure (a 5xx, a timeout, a lost connection, an unreadable
answer) keeps its intent open at its bound and is never sent again. A resumed
run skips every cell with an intent, except a cell refused once, which still
gets its second attempt.

`DIR/results.jsonl` holds per cell the tool calls, text, usage, cost, latency
and the scoring of `scripts/measurement_scoring.py` (label match, critical,
mechanical bars). It also names the refusals: `refusals` on the cell's row.
`--repeat-disagreements` then runs
D7's last item: the reference a second time, only on the cases where some
arm's label result differs from its own. No arm runs again.

## The thresholds

`derive_thresholds.py` scores each arm against the reference's score less its
binomial standard error, with every mechanical bar met and no critical
failure; a `satisfice` role's threshold is the lowest index at and above
which every measured arm passes, or `measured_only` when index and result
disagree. An arm cut short (a transport failure, a refusal, a skip, the
cap) is not a measurement. It is kept out of `results` and named in the
role's `incomplete` (`{arm: why}`), so the resolver treats the model as
unmeasured rather than failed, and thresholds derive from complete arms
only. MEMORY_EXTRACT and MEMORY_MERGE are both judged on the corpus's
joint verdicts: a case fails both roles when either the extraction or the
decision went wrong, which is conservative for each. Everything is judged
on the first repetition. The second
repetition's answers are recorded in the role's `second_repetition`, the first
and second label result of each repeated case, and change no pass or fail.
It writes `measured.json` in the shape `resolver.validate_measured`
reads, with the hashes it measured; `tests/measurement/test_derive_thresholds.py`
refuses a committed `measured.json` whose hashes are not today's or whose
thresholds its own results do not give.
