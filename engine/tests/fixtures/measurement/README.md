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
| Rehearse | `python scripts/measure_roles.py --arms ARMS.json --out DIR --dry-run` | no |
| Measure the roles with case sets | `python scripts/measure_roles.py --arms ARMS.json --out DIR --cap 20` | yes |
| Measure the memory roles, one run per arm | `MNEMONIC_CORPUS_EXECUTE=1 MNEMONIC_CORPUS_ARMS=ARMS.json MNEMONIC_CORPUS_ARM=<id> MNEMONIC_CORPUS_PROFILE_DIR=… MNEMONIC_CORPUS_CAP_USD=… pytest tests/memory/test_mnemonic_corpus_live.py` | yes |
| Derive the thresholds | `python scripts/derive_thresholds.py --arms ARMS.json --results DIR/results.jsonl --corpus REC/*-manifest.json --write` | no |

Keys come from the environment only (`OPENROUTER_API_KEY`), are written to a
disposable profile's `.env` (mode 600, deleted after) and never printed.

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

## The measurement

Each arm (the bootstrap's plus the reference, K3, run first in every role)
answers each case through the engine's real OpenRouter transport: the model
is the arm's, the request shaped as production shapes it, K3 through its
adapter, the datetime line pinned to the case's `capture_now`. CHAT and
TASK_SOLVE continue the turn through their harness's `run_case`. Before each
dispatch the engine's reservation bound is checked against the cap with
everything spent or uncertain and written to `DIR/ledger.jsonl` as an
intent; the receipt settles it. Nothing is retried; a resumed run skips every
cell with an intent. `DIR/results.jsonl` holds per cell the tool calls, text,
usage, cost, latency and the scoring of `scripts/measurement_scoring.py`
(label match, critical, mechanical bars).

## The thresholds

`derive_thresholds.py` scores each arm against the reference's score less its
binomial standard error, with every mechanical bar met and no critical
failure; a `satisfice` role's threshold is the lowest index at and above
which every measured arm passes, or `measured_only` when index and result
disagree. It writes `measured.json` in the shape `resolver.validate_measured`
reads, with the hashes it measured; `tests/measurement/test_derive_thresholds.py`
refuses a committed `measured.json` whose hashes are not today's or whose
thresholds its own results do not give.
