---
status: active
---

# Engine-owned mail sync — execution plan

Brief: [engine-owned mail sync](../briefs/2026-11-18-engine-owned-mail-sync.md),
approved by a fresh reviewer on 2026-11-18 after one revision.

## Classification

Substantial development: a new daemon loop, a new process setting and a changed
answer of `sync.run` under contention. Not a fast path.

## Ownership and dependencies

One session owns the source change, its tests, the brief and this plan. The
change for `main` is in the worktree `mrcall-desktop-engine-mail-loop`, branch
`feat/engine-mail-loop-20261118`, from `origin/main` `05bf7a20`. The hosted
release is in the worktree `mrcall-desktop-hosted-engine`, branch
`release/hosted-engine-20261118`. On 2026-11-18 18:11Z the operator authorized
the merge, the tag, the push and the rollout to both MrCall units. The kernel,
the clones and every other hosted instance stay untouched.

Four source lines carry the touched files:

| Line | Location | Email-only intake | `observability_producers` |
|---|---|---|---|
| `origin/main` | this worktree, `engine/zylch` | absent | absent |
| hosted release | branch `release/hosted-engine-20261118`, commit `c5bd4bb5`; both MrCall units run it | present | present |
| second account's earlier family | `/home/mrcalld/releases/source-read-repair-mario-20261027-d2f7e66c6078/zylch` | absent | present |
| support's earlier family | `/home/mrcalld/releases/interactive-reply-d78411b2122a547a5f4d4760/mrcall/venv/lib/python3.12/site-packages/zylch` | present | present |

The hosted release is not `main`: it has 184 commits that `main` lacks and
lacks 16 that `main` has. The two earlier families stay on disk as rollback
targets.

Tests run with `/home/mal/zylch-engine/venv/bin/python -m pytest` from the
`engine` directory of the tree under test, one suite at a time.

## M1 — source and focused tests on `origin/main`

`engine/zylch/services/process_pipeline.py`

- `run_sync_only(..., include_whatsapp: bool = True)`: the support family's
  hunk. With `False` the WhatsApp stage is skipped and
  `wa_skipped_reason` is `Email-only scope.`.
- `_run_sync`: a mailbox progress line is a log record,
  `logger.info("[sync] <mailbox>: <message>")`, where `origin/main` prints it
  to a console bound to stderr. One line changes. The line names its mailbox
  and a failure quotes the provider's error. A daemon's stderr is its journal,
  and the private log scope of the hosted families masks log records only: as
  a record the line is masked there on every scope of `sync.run`, and it stays
  readable in the log of a family without that scope.

`engine/zylch/rpc/setup.py`

- The handler's docstring signature becomes `sync.run(days_back?, scope?)`, so
  the dispatcher keeps checking the method and accepts `scope`
  (`rpc/param_spec.py` derives accepted names from that line).
- `scope` is `all` or `email`; any other value, and a `days_back` outside
  1 to 60 on the email scope, is refused before any effect, as in the support
  family.
- `_email_intake(params, notify, *, from_loop)` takes `_email_intake_lock`
  without blocking. The caller that takes it sets `_email_intake_loop_run` on
  the event loop thread, in the same step: `None` first, then the run's future
  when the daemon's loop is the caller. It starts the worker with
  `asyncio.get_running_loop().run_in_executor` and registers the future. The
  worker runs `_sync_run(..., email_only=True)` in its own event loop and
  releases the lock in `finally`. The request's context is copied into the
  worker with `contextvars.copy_context()`.
- When the lock is taken: an RPC caller joins the run if
  `_email_intake_loop_run` is a future, and is answered `busy` if it is
  `None`. A loop caller is always answered `busy`. Because every caller that
  takes the lock resets the variable, an RPC caller never joins a loop run
  that ended before another RPC run began.
- One helper, `_await_intake(future)`, is the only place a run is awaited. The
  starter and the joiner both use it. It awaits `asyncio.shield(future)`, so a
  cancelled caller never cancels the shared future: the worker still starts,
  still releases the lock, and the loop's own await is not cancelled. It turns
  a worker exception into the failure result of the email scope
  (`scope: "email"`, `success: false`, `busy: false`), for both callers.
- `email_intake_from_daemon()`: the loop's entry. It calls `_email_intake` with
  `EMAIL_INTAKE_PARAMS = {"scope": "email", "days_back": 14}` and a notify that
  does nothing.

`engine/zylch/rpc/server_ws.py`

- `_mail_sync_interval_seconds()`: `MAIL_SYNC_INTERVAL_MINUTES`, default 10,
  `0` or a negative value disables, other values clamp to 2..360, a value that
  is not an integer means the default.
- `_mail_sync_loop()`: waits 90 seconds after start, then once per interval
  writes exactly one log line at INFO or above, so a skip is distinguishable
  from a missing run:
  - `[mail-sync] skipped: disabled` when the interval is `0`;
  - `[mail-sync] skipped: no mail credentials` without `EMAIL_ADDRESS` and
    `EMAIL_PASSWORD`;
  - `[mail-sync] skipped: pipeline run in flight` while the paid pipeline
    holds `process_pipeline._pipeline_lock`, which already syncs mail;
  - `[mail-sync] skipped: intake already in flight` on a `busy` answer;
  - `[mail-sync] run completed new=N` on success;
  - a WARNING with the humanized error titles when the run reports errors.
- An exception is logged with its traceback and the loop continues. A
  `CancelledError` ends the loop only when the loop's own task is being
  cancelled (`asyncio.current_task().cancelling()`); otherwise it is logged
  and the loop continues. A disabled loop re-reads the setting every 10
  minutes.
- The daemon starts the task beside `_auto_update_loop` and
  `_whatsapp_refresh_loop` and cancels it with them.

Tests

- `engine/tests/rpc/test_email_scope_sync.py`: the existing test of the
  email-only intake, taken from the main checkout's working tree, where it is
  untracked. It covers the channel split, refusal before effects, worker
  ownership after cancellation, the `scope` echo on failures, storage with
  cursor reuse and release on submission failure.
- `engine/tests/rpc/test_mail_sync_loop.py`, new:
  - interval parsing;
  - the loop sends `EMAIL_INTAKE_PARAMS` and reaches neither WhatsApp nor
    `update_run`;
  - disabled, no credentials and a held pipeline lock each run nothing and log
    their line;
  - a raising intake is logged and the next interval runs;
  - cancelling the loop's task during a run ends the loop at once, without
    waiting for the worker;
  - an RPC during a loop run returns that run's result with the mailbox sync
    called once;
  - a joiner cancelled during a loop run: the run completes, the lock is
    free, the loop's next interval runs;
  - a joined run that raises: the joiner receives the failure result with
    `scope: "email"` and `busy: false`, and the loop continues;
  - an RPC during an RPC run is `busy`, also right after a loop run ended;
  - a loop tick during an RPC run starts nothing;
  - while a worker is blocked the event loop answers another `sync.run`
    within one second;
  - `dispatch_raw` accepts `sync.run {scope: "email"}` and still refuses an
    unknown name;
  - a loop run stores fresh fake-provider mail, from INBOX and from Sent,
    that is read back, and prints nothing to the pipeline's console;
  - a failing loop run prints nothing to the pipeline's console;
  - on both scopes of `sync.run` the mailbox progress line is a log record and
    no console line: it names the mailbox on a family without the private log
    scope and is metadata only on one that has it.

Documentation in this worktree

- `docs/ipc-contract.md`: the `sync.run` row and section gain `scope`, the
  `busy` answer, the joined result and the `scope` echo; a short section names
  the daemon's mail loop and `MAIL_SYNC_INTERVAL_MINUTES`.
- `docs/rpc-contract-inventory.json`: the `sync.run` entry accepts `scope`.
  The file is a generated snapshot that CI does not compare. It is regenerated
  with `--write` from a kernel revision that reproduces its committed
  `kernel_calls`; the first candidate is `eb6dc1a`, which the plan review
  found to reproduce all 64 calls. If no revision reproduces them, it is
  regenerated from CI's pinned kernel and the rewritten `kernel_calls` is
  reported under "Verification evidence".
- `docs/README.md`: one routing line for the brief and this plan.
- `engine/docs/active-context.md`: the loop as local, uninstalled source.

Verification of M1

- The two test files pass. `tests/email` and `tests/rpc` give the same result
  as on unmodified `origin/main`, each run once before the change and once
  after.
- CI's contract check, run locally as CI runs it:
  `node scripts/rpc-contract-inventory.cjs --negative-proof` from `app`, with
  `ENGINE_PYTHON=/home/mal/zylch-engine/venv/bin/python`, `CS_KERNEL_ROOT` set
  to a `git archive` of kernel `ba79cc13`, the revision
  `.github/workflows/rpc-contracts.yml` pins, and `NODE_PATH` set to an
  installed `app/node_modules` of another worktree, because this worktree has
  none.
- `ruff check` is clean on the three source files. `ruff format --diff` shows
  no hunk inside lines this change adds; `server_ws.py` and
  `process_pipeline.py` already differ from `ruff format` on unmodified
  `origin/main`, and those lines are left alone. `black` is not installed on
  this host and is not run.

M1 ends with a milestone review by a fresh reviewer before M2.

## M2 — candidate for the second account's family

A candidate tree outside `/home/mrcalld`: a copy of the installed family with
three files changed. The family already has the diagnostics module,
`_pipeline_lock` and the same `rpc/param_spec.py`.

- `services/process_pipeline.py`: the same hunk as M1.
- `rpc/setup.py`: M1's logic with the support family's diagnostics calls
  (`observed`, `observe`, `failure`, `copied`) in the places that family has
  them.
- `rpc/server_ws.py`: M1's loop hunks on the family's own file.
- Private logs. In the hosted families `sync.run` is decorated
  `@observed("acquisition", "sync.run", private=True)`: while it runs, every
  log record of the process context, the worker thread included, is replaced
  by a metadata-only line (`qonto/logging.py`, `private_scope`). The loop's
  entry `email_intake_from_daemon` carries the same decorator in the family
  port. Without it a loop run, and an RPC caller that joins one, would log the
  owner's address, mailbox addresses and IMAP error text in clear. The loop's
  own `[mail-sync]` lines are written outside that scope and stay readable.

Verification of M2: the M1 test files run against the candidate tree with
`PYTHONPATH` set to it, from a directory that holds the tests and no `zylch`
package; one more test, skipped where `zylch.observability_producers` is
absent, proves that a record logged inside a loop run carries no mailbox
address; `python -m compileall` is clean; a diff of the candidate against the
installed family shows the three files and nothing else. The candidate's
tree digest is recorded here.

M2 ends with a milestone review by a fresh reviewer.

## M3 — rollout to the second account's instance

Needs the operator's word. Steps, each reversible:

0. Confirm that the installed family still differs from the candidate in the
   three files only, and that the unit's last drop-in is still
   `zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-source-read-repair-20261027.conf`. If
   another change reached the instance first, the candidate is rebuilt.
1. Install the candidate as a directory under `/home/mrcalld/releases/`,
   root-owned and world-readable like the existing ones, so the instance's
   user can read it through the sandbox's read-only mount. Copy it without
   `__pycache__`. Verify the installed copy against the recorded digest.
2. Add one drop-in for `zylch-server@x59G6SnymAN2lkFny0JDGJgdFz33.service`
   that sorts after that last one. Its `PYTHONPATH` is the last drop-in's
   list with the first entry, the `source-read-repair` release, replaced by
   the new release directory; the other entries stay. `systemctl
   daemon-reload`, restart that one unit, away from the clone's ticks at
   06:50Z, 10:50Z, 14:50Z and 18:50Z.
3. Confirm from the unit's log that the three loops started and that the
   first mail run completed.

Rollback: remove the drop-in, `daemon-reload`, restart the unit. The mail the
loop stored stays in the archive; no database change is reversed.

Hosted acceptance as the brief states it. The hand-sent reply is observed when
the mailbox's owner next sends one.

## M4 — one hosted release for both MrCall units

The package that served support was in no commit: `31d52fe9` of branch
`fix/assignment-imap-round-trips-20261030` plus 9 changed and 14 added files.
Branch `release/hosted-engine-20261118` records it as commit `91e2f654`,
byte-identical to the installed package, and carries the mail loop as commit
`c5bd4bb5`: `rpc/setup.py` as on the second account's family, and M1's hunks
on this family's `rpc/server_ws.py` and `services/process_pipeline.py`. Tag
`hosted-engine-0.1.57.dev2` names that commit; the package is
`zylch 0.1.57.dev2+hosted20261118.mrcall`.

The release is the environment that served support with the package replaced
by the wheel built from `c5bd4bb5`:
`/home/mrcalld/releases/hosted-engine-0.1.57.dev2-00fdc039d4e3/venv`. Each
unit selects it with one drop-in named `…-hosted-engine-20261118.conf` that
sorts last, resets `ExecStart` to the release's interpreter and sets
`UnsetEnvironment=PYTHONPATH`.

Rollback, per unit: remove that drop-in, `systemctl daemon-reload`, restart
the unit. The second account's store keeps the table
`draft_provider_operations` and the stamps of steps `0007` and `0008`; its
earlier family ignores step ids it does not know.

The line's own `engine/tests/conftest.py` imports `zylch.llm.roles`, which the
package does not ship, so its suite is not collectable as committed. The
ported package is tested with `main`'s test tree and `PYTHONPATH` naming it.

Open, each on the operator's word: the kernel change that drops
`_mail_intake`; bringing `main` and the hosted branch to one line; the Café
124 unit, which runs a third build. Scheduled ticks of the MrCall clone
observed after the rollout close the plan.

## Verification evidence

### M1, 2026-11-18

- Focused tests: `tests/rpc/test_mail_sync_loop.py`, 26 passed, and
  `tests/rpc/test_email_scope_sync.py`, 19 passed. The loop tests ran 12 times
  in a row without a failure before the milestone review added the 26th.
- Each property was broken on purpose in a scratch copy of the engine, 14
  mutants in all, and each was caught by the test written for it: an
  unshielded joiner, no reset at acquisition, intake on the event loop,
  WhatsApp included, other loop parameters, each of the three skips removed,
  a loop that dies on a crash, a loop caller that joins, an RPC that never
  joins, `scope` not declared, a disabled loop that exits, a loop that
  swallows its own cancellation.
- Milestone review, first pass REVISE: two sentences of `docs/ipc-contract.md`
  were false against the code and are corrected; the review's surviving
  mutant, the swallowed cancellation, has its test; the loop test now also
  fails on any entry into `process_pipeline.handle_process`.
- `tests/email`: 149 passed before and after. `tests/rpc`: 5 failed, 160
  passed and 18 skipped before; the same 5 failed, 204 passed and 18 skipped
  after, measured with 44 focused tests. The 5 fail on unmodified
  `origin/main` on this host:
  `test_contract_boundaries.py::test_every_method_accepts_its_documented_minimal_payload`
  and four tests of `test_ws_cancels_inflight.py`.
- CI's contract check with kernel `ba79cc13`: passed, 133 engine methods, 86
  preload calls, 114 renderer methods, 54 kernel candidates.
- `docs/rpc-contract-inventory.json`, regenerated from kernel `eb6dc1a`:
  `kernel_calls` is unchanged, 64 calls. Besides `sync.run` accepting `scope`,
  the file gains what `origin/main` already had and the committed snapshot
  lacked: nine `stripe.*` engine methods, four preload calls and four renderer
  entries, with the two source hashes that follow from them.
- `ruff check`: clean on the three source files and on the new test file.
  `ruff format --diff`: no hunk on an added line; `server_ws.py` keeps the two
  hunks it has on unmodified `origin/main`. The test file taken over from the
  main checkout is byte-identical to its source and keeps that file's two
  findings, `F401` and `F811` on the imported `env` fixture.
- Milestone review, second pass: APPROVED. The routing line in
  `docs/README.md` and the paragraph in `engine/docs/active-context.md` are
  written; the documentation's mechanical gate is clean on this worktree.

### M2, 2026-11-18

- Milestone review, first pass REVISE: an email-only run printed its mailbox
  progress lines to stderr, outside the private log scope. The repair the
  second pass APPROVED silenced the console for the email-only scope with a
  keyword on `_run_sync`. The reviewer found no other writer to stdout or
  stderr on the email-only path.
- That repair is replaced on the operator's direction of 2026-11-18: the
  progress line is a log record for every caller, one changed line, and the
  keyword is gone. The figures below are from after this change.
- Candidate tree:
  `/home/mal/.local/share/mrcall-operational-evidence/2026-11-18/engine-mail-sync/candidate-second-account/zylch`,
  355 files, no bytecode, file modes equal to the installed family's. Digest
  `d13efd60e5a0f6bcfd76d6157a5c14bbe7773d8687dac6bbc8a2d334ddc005c9`, computed
  from the candidate directory with
  `find zylch -type f -not -name '*.pyc' | LC_ALL=C sort | xargs sha256sum | sha256sum`.
- Against the installed family it changes `rpc/setup.py`, `rpc/server_ws.py`
  and `services/process_pipeline.py`, and adds or removes no file.
  `process_pipeline.py` is byte-identical to this branch's: it differs from
  the family's file by the email-only hunk and by the one progress line. The
  loop code in `server_ws.py` is identical to this branch's. `setup.py`
  differs from this branch's only by the family's diagnostics calls and the
  private decorator on both entries.
- The two test files against the candidate: 49 passed, the private-logs test
  among them. On this branch that test is skipped: 48 passed, 1 skipped;
  `tests/email` 149 passed; `tests/rpc` the same 5 failed, 208 passed and 19
  skipped. CI's contract check last ran before this change, which touches no
  RPC signature, and passed.
- With the private decorator removed from the loop's entry in a copy of the
  candidate, the private-logs test fails. With the progress line printed to
  the console again, four loop tests fail on both families; with the line
  removed, the two cases of the progress test fail.
- The M2 reviewer's two probes, real processes against a fake mail service:
  one drives `_mail_sync_tick`, one a default-scope `sync.run`, each with a
  successful and a failing mailbox. On the installed family's code stderr
  held `box@example.test: Stored 3 emails` and, for a failing mailbox, the
  address with the resolver's error. On the candidate, in all four runs,
  stderr names no mailbox, no log record names it, and the pipeline's
  progress record is the masked line. On this branch the record reads
  `[sync] box@example.test: Stored 3 emails` and stderr names no mailbox.
- The three files parse and `ruff check` is clean on them.
- The daemon's real entry, `serve_ws`, started in an isolated home directory
  on a Unix socket with the first delay shortened to one second:
  - default settings, no credentials: the four background tasks start,
    `[ws] mail sync started (every 10 min)`, then
    `[mail-sync] skipped: no mail credentials`, and the daemon stops cleanly;
  - `MAIL_SYNC_INTERVAL_MINUTES=0`: `[ws] mail sync started (disabled)`, then
    `[mail-sync] skipped: disabled`;
  - placeholder credentials on a `.test` domain: a run starts, the record
    logged inside it is the metadata-only line, and the loop writes
    `[mail-sync] run finished with errors`;
  - the default case gives the same lines on this branch.
- Not proven before rollout: a run against a real mailbox from inside the
  daemon. The fake-provider test covers storage; M3's acceptance covers the
  rest.

### M3, 2026-11-18

- The operator's word at 16:16Z. Release
  `/home/mrcalld/releases/engine-mail-sync-mario-20261118-d13efd60e5a0`,
  root-owned, identical to the candidate, digest verified in place. Drop-in
  `zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-engine-mail-sync-20261118.conf`: the
  previous last drop-in with its first `PYTHONPATH` entry replaced. The unit
  restarted at 16:18:10Z and has not restarted since.
- The unit's log: `[ws] mail sync started (every 10 min)` at 16:18:14Z beside
  the auto-update loop (`enabled=False`), the WhatsApp refresh and the reaper;
  `[mail-sync] run completed new=12` at 16:19:57Z; no traceback, and no
  mailbox line printed to the journal.
- The one-line change to the progress record has no milestone review of its
  own. The final review covers it.
- Open: the hosted acceptance items of the brief.

### M4, 2026-11-18

- Source. Commit `91e2f654`: `engine/zylch` equals the package installed on
  support, 453 files, none different. Commit `c5bd4bb5`: three package files
  change. `rpc/setup.py` equals the file of the second account's release;
  `rpc/server_ws.py` differs from that release's by this family's five
  `workflow_interactive` lines.
- Tests on the ported package, with `main`'s test tree: the two focused files
  49 passed. `tests/email` 149 passed on the installed package and on the
  ported one. `tests/rpc`: installed package 32 failed, 5 errors, 176 passed,
  19 skipped; ported package 6 failed, 207 passed, 19 skipped; no test fails
  on the ported package and passes on the installed one.
- Review of the port and of the rollout by a fresh reviewer: approved, no
  blocking finding. Two things it names: a stop that lands during a mail run
  waits for the worker, up to the unit's 90 seconds; an RPC call that joins a
  loop run gets a result whose fetch began before the call.
- Environment. Against the one that served support, 23 files differ: the
  three package files, the package's metadata directory and `bin/zylch`.
  `uv pip check` clean, no bytecode file. Package digest
  `00fdc039d4e32c2d154185846d63cd35b8a5c3b95b72f3a4f410506c2fb5760e`,
  environment digest
  `7865e71b42a6b243728c67c4a301f5314cadb308b869a8f5e89795c0518ac85c`, verified
  in place after the root-owned install.
- Start on a throwaway profile: the four loops start and the mail loop logs
  `skipped: no mail credentials` at 90 seconds.
- Rehearsal on a SQLite-backup copy of the second account's store, as its own
  Unix user, no credentials, in a transient unit with a private `/tmp`: the
  first start writes a backup and applies `0007_draft_provider_operations` and
  `0008_exact_operator_send`; the second applies nothing; the new table is
  empty; integrity check `ok`.
- Support unit, restarted 18:39:36Z: active, no restart since;
  `system.capabilities` equal to the answer before the restart, 13 keys;
  `[ws] mail sync started (every 10 min)`; `[mail-sync] run completed new=0`
  at 18:41:16Z; no error line and no mailbox line in the journal.
- Second account's unit, restarted 18:42:29Z: backup written, steps `0007`
  and `0008` applied, encryption self-check passed;
  `system.capabilities` now equal to support's, 13 keys, where the earlier
  family answered 5; `[mail-sync] run completed new=1` at 18:44:10Z.
- Pushed: branch `release/hosted-engine-20261118` and tag
  `hosted-engine-0.1.57.dev2`. The tag does not match `v*`, so no Desktop
  release build starts.
