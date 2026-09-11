# Bounded preparation

Preparation uses a durable per-profile SQLite ledger, separate from the dollar
ledger. `PREPARATION_BATCH_SIZE` defaults to 25 and accepts 1–100. One run shares
that allowance across memory extraction, task decisions, and ancillary paid
calls such as prompt training, merge canaries, and maintenance. A message's
memory and task stages count separately. Merge calls within an admitted source
item remain subject to the central daily dollar budget and candidate shortlist;
the batch limit is not a promise of exactly 25 provider requests.

The profile's immutable `OWNER_ID` keys the preparation ledger where available;
legacy email identities still select source rows. Changing a display email does
not reset preparation failures. SQLite transactions serialize run and item
admission across processes. A live PID blocks a competing run; an interrupted
run's unfinished items retain failure evidence. There is no automatic timeout
that assumes dispatched work was free.

A source/stage can fail three times. Failures back off for at least 60 seconds; ordinary extraction failures
increase the delay with each attempt. Restarting or clicking resume does not clear attempts.
A genuine pre-dispatch budget refusal leaves semantic attempts unchanged;
provider failures, uncertain usage, partial work and cancellation after work
starts count as failed attempts. The central client's `record_dispatch` marker
makes that distinction durable. Explicit `SKIP` is successful memory analysis.
Task inference alone is insufficient: task checkpoint writes complete the
attempt only after the task mutation commits. An incomplete decision, truncated
output or failed persistence leaves its source pending. The update pipeline no
longer expires old pending task checkpoints merely because of their age.

## RPC contract

- `preparation.status()` returns `paused`, `running`, current/last-run `attempted`,
  `completed`, `failed`, `limit`, `next_run_limit`, `stop_reason`, `suspended`,
  `retry_waiting`, up to 100 `failed_items` (stage/source/attempts/retry time), source checkpoint `pending`, `checkpoints_completed`, and a
  `channels` breakdown. Counts use source-stage units, not unique messages.
- `preparation.pause()` persists a pause. New dispatches in the active run stop;
  already dispatched requests may finish and are still charged/accounted.
- `preparation.resume()` performs one bounded **analysis-only** run, returning
  the status plus `success`, `summary`, and stage `errors`. It does not fetch
  messages or enable recurring automatic processing, and preserves saved pause.
- `preparation.reset_failures(stage, source)` explicitly resets one inactive
  item's retry history. Stage examples are `memory:email` and `task:calendar`.
- `sync.run()` remains the free synchronization operation.

Normal `update.run` and CLI update use the same bounded run. Standalone memory
batches, task refresh, trainers and maintenance RPCs also use run admission.
Legacy private paid preparation paths without an admitted scope are refused
with guidance to use bounded preparation. Interactive chat is separate and has
a maximum of ten tool rounds per user turn, in addition to the daily budget.

## Validation

`tests/services/test_preparation.py` exercises real SQLite transactions,
concurrent run refusal, shared limits, durable backoff, interrupted work,
pause/resume, uncertain dispatched failures, immutable account identity and
actual MemoryWorker/Storage checkpoint writes with fake semantic extraction.
RPC contract and existing memory/task worker suites exercise integration. No
customer analysis or paid upstream call is needed by these tests.
