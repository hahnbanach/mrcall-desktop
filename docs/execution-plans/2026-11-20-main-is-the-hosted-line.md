---
status: active
---

# Main is the hosted line, and the member-activity hold ends after three days — execution plan

[Brief](../briefs/2026-11-20-main-is-the-hosted-line.md).

Owner of every milestone: Claude session
`617dd083-145f-41e1-975e-e50096c231f4`. The operator ordered the work on
2026-11-20 for `main`, the tag, the push and the seven units.

## Dependencies

- Tag `hosted-engine-0.1.57.dev3` (`623b8cff`) and its release
  `/home/mrcalld/releases/hosted-engine-0.1.57.dev3-084d97ca9d8d`, which the
  two MrCall units run.
- The [one-build plan](2026-11-19-one-hosted-engine-build.md): its drop-in
  form, its release procedure (M2), its store rehearsals and its per-unit
  procedures (M3, M4, M5) apply here with the new release name.
- Work branch `integrate/one-engine-line-20261119`, worktree
  `/home/mal/worktrees/mrcall-desktop-one-line`. `main` moves to its tip by
  fast-forward.
- Kernel `v0.73.3` in both clones, unchanged.
- Operator ticks: the MrCall clone at 06:50, 10:50, 14:50 and 18:50 UTC, the
  Café 124 clone at every even hour from 06:00 to 18:00 UTC.
- `zylch-reconcile.timer` at 00:00 UTC. After a push to `main` it pulls the
  base checkout, runs `pip install -e` on the base environment because
  `engine/pyproject.toml` changed, and restarts every unit with no check for
  a call in progress. A restarted unit comes back on its last drop-in.
  `zylch-reconcile.path` runs the same script when a new profile directory
  appears.
- `zylch-provisiond.service` is the one service that runs code from `main`'s
  checkout (`python -m zylch.provisiond`). Its import chain is the same in
  `ecba4c06` and in the merged tree, and the reconcile does not restart it.

## M1 — `main` takes the production engine

One merge commit on the work branch, parents the branch tip and `623b8cff`:
`git merge -s ours --no-commit 623b8cff`, then
`git restore --source=623b8cff --staged --worktree` for `engine/zylch`,
`engine/tests` and `engine/pyproject.toml`, then `main`'s `engine/tests/stripe`
files beside the tag's, and `engine/scripts/server/assignment_enroll.py`
removed.

Verification:

- `git diff 623b8cff <merge> -- engine/zylch engine/pyproject.toml` is empty.
- `git diff <branch tip> <merge>` names no path outside `engine/zylch`,
  `engine/tests` and `engine/pyproject.toml` except the removed script.
- `tests/stripe` passes on the merged tree.
- Tag `main-before-hosted-line-20261120` on `ecba4c06`.

Rollback before the push: drop the commit. After the push: one commit on
`main` that restores `engine/zylch`, `engine/tests`, `engine/pyproject.toml`
and the removed script from `main-before-hosted-line-20261120`. No hosted
unit loads its engine from `main`'s checkout once M6 is done.

## M2 — the limit

`services/task_assignment_projection.py` gains `_member_hold_seconds` and
`_member_hold_lapsed`, and `_project` uses them as the brief's rule states.
`services/task_assignment_mail.py` gains `timestamps`.
`storage/storage.py` gains `_own_sent_replies_stay_answers`, which
`store_emails_batch` applies before it writes. Version
`0.1.57.dev4+hosted20261120.mrcall`.

Verification:

- `tests/assignments/test_member_hold_limit.py`: release past the limit with
  each time column, hold inside the limit, hold while a member wrote last,
  the setting, a missing time, the complete Sent membership, one evidence
  item per holding message, two holding messages around the customer's
  newest mail, another member's mail, an automatic reply from outside.
- `tests/storage/test_insert_sent_email.py`: a sync after a send, a sync
  that stores the first copy, an automatic message no draft sent, another
  owner's draft.
- Nine deliberate bugs, each in its own copy of the package: no Sent
  recheck, no member-last test, an inverted limit, a release that never
  happens, the oldest holding message in place of the newest, another
  member's mail counted as the customer's, an automatic reply counted as
  the customer's, the flag rule removed, the flag rule without its owner.
  Each fails at least one new test.
- The tag's test tree of 2026-11-19, with its shim, runs one directory at a
  time against the new package in the same environment. No case that passed
  on the `dev3` package fails.
- A fresh reviewer reads the diff.

Rollback before the push: drop the commit. After the push: revert it on
`main`; the units return through their own drop-ins.

## M3 — tag, push, release

1. The branch tip becomes `main` by fast-forward. Tag
   `hosted-engine-0.1.57.dev4` on it. `main`, the tag and
   `main-before-hosted-line-20261120` are pushed after a scan of the pushed
   additions for secrets, addresses and customer names.
2. Release `/home/mrcalld/releases/hosted-engine-0.1.57.dev4-<first 12 hex
   digits of the package digest>/venv`, built as M2 of the one-build plan
   builds it: the wheel from the tag, in a copy of the `dev3` release's
   environment, root-owned, no bytecode, `uv pip check`, digests recorded,
   the installed `zylch` tree compared file by file with
   `git archive <tag> engine/zylch`, every script in `bin/` on the release's
   own interpreter, a throwaway start.

The store steps of the new package are those of `dev3`: the two differ in
two service files and in one method of `storage/storage.py` that adds no
step. The rehearsals of 2026-11-19 stand.

Rollback: a release directory no unit loads changes nothing. The tag stays.

## M4 — the two MrCall units

The procedure of M3 of the one-build plan, the second account first, with a
drop-in named to sort after the one of 2026-11-19.

Acceptance: the brief's criteria for the first MrCall tick on the new
package and for the tick after a reply to a released thread.

Rollback, per unit: remove the new drop-in, `daemon-reload`, restart. The
unit returns to `hosted-engine-0.1.57.dev3`.

## M5 — Café 124 production

The procedure of M4 of the one-build plan: the drop-in with the two extra
arguments, the checks before the restart with `calls_available: true` in the
same command, the checks after it. The unit runs the mail loop like every
other unit; the evidence of M5 below says why the drop-in no longer turns it
off.

Acceptance: the next scheduled Café 124 tick ends as its ticks of the same
day ended before the switch, and the unit logs no error record through it.

Rollback: remove the drop-in, `daemon-reload`, restart, compare the command
line with the recorded one. The unit returns to
`interactive-reply-124-helper-226c0048ed8d3fea`.

## M6 — the three Café 124 staff units and the personal mailbox unit

The procedure of M5 of the one-build plan, with one change of order: the
three staff units follow one another once the first has logged its first
`[mail-sync] run completed` and no error record, and the two-hour watch runs
for all of them together. The order of 2026-11-20 asks for the fleet on one
build without a wait between units.

Rollback, per unit: as M5 of the one-build plan. The personal mailbox
unit's rollback runs `mrcall-tenant create`, which changes the profiles
directory and so runs the reconcile: with a commit on `main` that the base
checkout has not pulled, every unit restarts at that moment.

## M7 — closure

- The fleet inventory shows one package hash on seven units, equal to the
  hash of `git archive hosted-engine-0.1.57.dev4 engine/zylch`.
- [`remote-backend.md`](../remote-backend.md), the engine's
  [active context](../../engine/docs/active-context.md) and the
  [task assignment contract](../../engine/docs/features/task-assignment.md)
  state the one line, the release and the limit.
- The one-build plan is `superseded` by this one.
- The reconcile that follows the push of `main` ran at 10:49 UTC, not at
  00:00 UTC: the Evidence section holds its record.
- The closing documentation commits change no code. They reach `main` with
  a pull of the base checkout by hand, as the service user, right after the
  push: `git -C /home/mrcalld/mrcall-desktop pull --ff-only`. The 00:00 UTC
  reconcile then finds no new commit and restarts no unit. Its record is
  read the next morning: expected exit 3 with the same six units refused, no
  `pip install`, no restart.
- No completion record of the documentation checker exists for this work.
  The record needs the approved version of the brief, of the plan and of
  each milestone as files retained at review time, and they were not
  retained. The documentation baseline is not advanced.

## Evidence

`~/.local/share/mrcall-operational-evidence/2026-11-20/main-is-the-hosted-line/`.
Results of each milestone are added below as they exist.

### Reviews

- Brief: REVISE twice, then APPROVED. The first review counted the tick's
  rows by the engine's component, asked for the reconcile as a stated
  exception and for the cases in which a hold ends although a person
  answered, and traced a second answer to a released thread. The second
  found the window in which a mail sync flags the engine's own sent reply
  automatic; the storage fix closes it.
- Plan: APPROVED. Its notes are in the plan: `zylch-provisiond.service`, the
  rollback of each milestone, `zylch-reconcile.path`, the expected result of
  the first reconcile.
- M1 and M2: APPROVED on commits `63b2fb5d`, `81bf192a`, `6244b480` and
  `6454b9a2`. Its notes became the single release decision, the automatic
  reply from outside and three test cases.

### M1, 2026-11-20

- Merge commit `63b2fb5d`, parents `e695ce0a` and `623b8cff`.
  `git diff 623b8cff 63b2fb5d -- engine/zylch engine/pyproject.toml` is
  empty. Against `623b8cff`, `engine/tests` adds the four `tests/stripe`
  files of `main`. Against `e695ce0a`, the one path outside the package, its
  tests and `pyproject.toml` is the removed
  `engine/scripts/server/assignment_enroll.py`.
- `tests/stripe` on the merged tree: 35 passed.
- Tag `main-before-hosted-line-20261120` on `ecba4c06`.

### M2, 2026-11-20

- Commits `81bf192a`, `6244b480` and `6454b9a2`.
  `git diff hosted-engine-0.1.57.dev3 hosted-engine-0.1.57.dev4 -- engine/zylch
  engine/pyproject.toml` names `services/task_assignment_mail.py`,
  `services/task_assignment_projection.py`, `storage/storage.py` and the
  version line.
- New cases: 17 in `tests/assignments/test_member_hold_limit.py` and 4 in
  `tests/storage/test_insert_sent_email.py`. All pass.
- The nine deliberate bugs fail 7, 5, 9, 6, 1, 1, 1, 2 and 1 of the new
  cases, in the order M2 lists them.
- Test comparison, `checks/test-comparison.txt`. The eleven directories that
  exercise the changed code ran on the tagged commit: 2,527 cases pass
  against 2,495 on the `dev3` package, none lost, 32 gained. The twelve
  other directories ran on the first of the three commits: 903 pass on both
  packages, none lost.

### M3, 2026-11-20

- `main` is `58ee858f`, a fast-forward from `ecba4c06`, pushed at 10:45:48
  UTC with tag `hosted-engine-0.1.57.dev4` on `6454b9a2` and tag
  `main-before-hosted-line-20261120`. The added lines of the pushed commits
  hold addresses of test fixtures only.
- Release `/home/mrcalld/releases/hosted-engine-0.1.57.dev4-9f6812dbd997`:
  root-owned, no bytecode, no writable file, every script on its own
  interpreter, `uv pip check` clean, 478 package files identical to
  `git archive hosted-engine-0.1.57.dev4 engine/zylch`, imported by each of
  the seven tenant users. Digests in `release/release-facts.txt`. Throwaway
  start: four loops, `[mail-sync] skipped: no mail credentials`.

### The reconcile of 10:49 UTC, not planned

`mrcall-tenant create` for the personal mailbox unit modified the profiles
directory. `zylch-reconcile.path` then ran the reconcile, which pulled
`main` from `ecba4c06` to `58ee858f`, ran `pip install -e` on the base
environment and restarted all seven units between 10:49:35 and 10:49:39 UTC,
exit 3. The telephone unit restarted with no call check and during a tick of
the Café 124 clone.

- Café 124 production: no voice call line in its journal from 10:30:06 UTC
  to the restart; `calls_available: true` at 10:36:46 and 10:50:10 UTC; voice
  runtime line at 10:49:49 UTC.
- The Café 124 tick that ran through it ended at 10:54:17 UTC with exit 1:
  `assignment_read_incomplete` and `execution_read_failed`, with transport
  and connection failures in its report. The tick before it ended with exit
  0.
- Each unit came back on its last drop-in: the three already switched on
  `dev4`, the other four on the package they ran.

After a push to `main`, `mrcall-tenant` and any change to the profiles
directory restart every unit at once.

### M6, 2026-11-20

| Unit | Switch (UTC) | Store steps | First mail run | Errors after |
| --- | --- | --- | --- | --- |
| staff `YZNI…` | 10:45:56 | `0007`, `0008`, backup written | `run completed new=0` | the `reanalyze_task` budget refusal it logged before |
| staff `ZwpL…` | 10:48:14 | `0007`, `0008`, backup written | `run finished with errors: Email login rejected` | the IMAP login rejection it logged before |
| personal mailbox | 10:49:09 | `0007`, `0008`, backup written | `run completed new=772` | none |
| staff `C06x…` | 10:56:36 | `0007`, `0008`, backup written | `run completed new=0` | the `reanalyze_task` budget refusal it logged before |

- Each: active, package digest `9f6812dbd997`, the release's interpreter, no
  `PYTHONPATH` in the process.
- The personal mailbox unit: declaration
  `/etc/mrcalld/tenant-exec/<uid>` with `INTERPRETER=<release>/venv/bin/zylch`,
  drop-in `t1-hosted-engine-20261120.conf`, `mrcall-tenant create`. The
  reconcile of 10:49 UTC restarted it and it came back on the release.
- `system.capabilities` of `C06x…`, the one staff unit a clone reads: 5 keys
  before, 14 after, none lost. No client of ours holds a session for the
  other three units.
- The watch of these four units, read at 12:57 UTC, two hours after the
  last of their switches (`rollout/two-hour-watch.txt`): each active with
  `NRestarts=0`; 13, 12 and 11 completed mail runs on `YZNI…`, the personal
  mailbox unit and `C06x…`; 13 mail runs on `ZwpL…`, each ended by its
  rejected login. No error type appears that the unit did not log before:
  the budget refusals of `reanalyze_task`, the rejected login, and on
  `YZNI…` the entity-extraction failures it has logged every day since
  2026-11-10. The mail loop of `ZwpL…` writes its login failure as error
  records without text, through the private logging scope.
- The error shapes of every unit before its switch are in
  `rollout/errors-before-switch.txt`. `YZNI…` and `C06x…` log about 230
  `reanalyze_task` refusals a day, "request exceeds the supported
  200000-token context window", from `llm/budget_pricing.py`, which is the
  same file in their earlier package and in this one.

### M5, 2026-11-20

- Switch at 10:56:07 UTC, after `calls_available: true` in the same command
  and with no tick of the Café 124 clone running.
- After it: `calls_available: true` at 10:56:21 UTC; the process listens on
  `127.0.0.1:8787`, `ws.sock` and `operator-mcp.sock`;
  `[voice] production runtime module=<release path>` at 10:56:13 UTC;
  `StreamableHTTP session manager started` at 10:56:14 UTC;
  `[ws] mail sync started (disabled)` and `[mail-sync] skipped: disabled`;
  the public MCP route answers 401 and both OAuth metadata documents answer
  200; package digest `9f6812dbd997`; no store step; no error record.
- `system.capabilities`: 13 keys before, 14 after, none lost,
  `stripe_payment_method_links` gained.
- Its automatic cycle logs the warning it logged before the switch,
  "Preparation is paused".

### M4, 2026-11-20

- The MrCall tick of 10:50 UTC ran on `dev3` and ended at 11:28:34 UTC. The
  second account switched at 11:29:01 UTC and support at 11:29:19 UTC: each
  active, package digest `9f6812dbd997`, no store step, the encryption
  self-check passed, `[ws] mail sync started (every 10 min)`, no error
  record, the 14 capability keys of before.
- The fleet inventory after it, `fleet-packages-after.txt`: seven units, one
  package digest, `9f6812dbd997`.
- The projection asked of both engines for five held rows of the 10:50 UTC
  scan, through the clone's `cs rpc tasks.assignment.project`:

  | Row's component | Support engine | Second account's engine |
  | --- | --- | --- |
  | customer last, past the limit | `normal`, `MEMBER_ACTIVITY_HOLD_EXPIRED`, two holding items kept | `normal`, no evidence |
  | customer last, past the limit, both mailboxes answered earlier | `normal`, `MEMBER_ACTIVITY_HOLD_EXPIRED` | `normal`, `MEMBER_ACTIVITY_HOLD_EXPIRED` |
  | a member wrote last from the support mailbox | `needs-assignment` | `normal`, no evidence |
  | a member wrote last from the second account's mailbox | `normal`, no evidence | `needs-assignment`, three holding items |
  | customer last, inside the limit | `needs-assignment` | `normal`, no evidence |
- The MrCall clone ran one tick by hand on the new package, with the
  schedule's own command: 11:34:25 to 12:20:46 UTC, exit 0, run
  `run-df8whgxh`. Row by row against the scan of 10:50 UTC,
  `rollout/mrcall-hand-tick-expect.txt`:
  - the six rows the rule releases left the held list: one is `open`, one
    is `resumed`, one is `courtesy`, one is not listed because a member's
    answer follows that row's mail, and two share one thread key, which the
    scan lists as `resumed` and, for the contact with the kernel's record,
    as `escalated`;
  - the six member-last rows and the four rows inside the limit are still
    `needs-assignment`, the two `conflict` rows are still `conflict`.
- The tick's work queue took the `open` row and one older root, and both
  owed nothing: the open row's newest mail is a closing thanks. It deferred
  one `resumed` row by its limit of two, and held the root of the other two
  released rows by the kernel's own `escalated` record of 2026-09-11.
  Result: 0 drafted, 0 sent, 0 escalated.
- Through that tick the support engine logged 26 release records and the
  second account's engine 2; neither logged a traceback, an `ERROR` or a
  `CRITICAL` record, and neither restarted.
- The scheduled MrCall tick of 14:50 UTC took the released conversation
  that the hand tick had deferred, and composed a reply. `create_draft`
  refused the model's first call, "Draft references contain a line break"
  (`tools/gmail_tools.py`): the model passed the thread's References chain
  as the archive stores it, folded over lines. The second call, on one line,
  saved the draft, and the scoped draft policy admitted it. The kernel's
  `cs draft-reply` exits 4 when a `create_draft` call of the turn failed, so
  the reply was not sent and the tick ended with exit 1. The draft waits for
  a person.
- In the support store 575 of 1,202 mails with a References value hold a
  line break, 73 of 128 in the last 30 days. Branch
  `fix/draft-references-unfold-20261120` (`fbcf0c8f`) makes a line break
  between two identifiers whitespace; a fresh reviewer approved it. Its
  release, a new package on the seven units, waits for the operator's word.
- No reply has left on `dev4`. The criterion for the tick after a reply to a
  released thread is not exercised yet.

### M5, after its first scheduled tick

- **The acceptance criterion of M5 failed.** The Café 124 tick of 12:00 UTC
  ended after three minutes with exit 1, `mail intake failed
  (TimeoutError)`, without its work. Earlier that day the tick of 08:00 UTC
  ended with exit 0 and those of 06:00 and 10:00 UTC with exit 1, each
  after its work: `assignment_read_incomplete` and `execution_read_failed`.
- The engine's email intake for that tick ran from 12:00:03 to 12:03:00 UTC,
  177 seconds; the kernel allows 180 seconds for the connection and the call
  together. The journal shows the time between the records of
  `zylch.email.imap_client`, 6 to 25 seconds apart. It was the first sync
  of a process started at 10:56:07 UTC.
- **The cause is not established.** On the earlier package the same call
  took 5 to 20 seconds in the ticks of 06:00, 08:00 and 10:00 UTC, after the
  same two-hour gaps. Between that package and this one
  `tools/email_archive.py`, `services/sync_service.py` and
  `email/sync_cursor.py` are identical, `email/imap_client.py` differs in
  its connection bookkeeping (25 lines) and `rpc/setup.py` in the intake
  worker (153 lines). The same call repeated from the clone took 30 seconds
  at 12:14 UTC, then 9, 6 and 10 seconds. In the process started at 12:19
  UTC the first sync took 6 seconds and the next tick's intake 5 seconds.
- The unit's auto-update loop fetches no mail: its pipeline stops at the
  spending gate, "Preparation is paused", before the sync stage. With
  `MAIL_SYNC_INTERVAL_MINUTES=0` the unit therefore synced only when a tick
  asked.
- **Decision taken after the plan's approval, and against the one-build
  plan's choice for this unit:** the drop-in no longer sets
  `MAIL_SYNC_INTERVAL_MINUTES`, so the unit runs the mail loop every ten
  minutes like the other six. A slow sync then falls in a loop run and not
  inside the kernel's wait. The telephone listener shares that process. To
  go back, add `Environment=MAIL_SYNC_INTERVAL_MINUTES=0` to the drop-in and
  restart the unit after `calls_available: true`.
- The unit restarted with that drop-in at 12:19:12 UTC after
  `calls_available: true`: `[ws] mail sync started (every 10 min)`, the
  first `[mail-sync] run completed new=0` at 12:20:56 UTC, and the checks of
  the first switch pass again.
- The Café 124 clone ran one tick by hand in place of the lost one, with the
  schedule's own command: 12:21:50 to 13:21:13 UTC, exit 0, run
  `run-u79z3gaj`. Its mail intake took 5 seconds. It drafted one reply and
  escalated one conversation, deferred 51 roots by the kernel's limit of
  two, and ended with the notice `assignment_read_incomplete`, as the ticks
  before the switch did. Through it the production unit logged 6 mail runs,
  19 release records and no error record; staff unit `C06x…` logged the
  budget refusals it logged before.
- The scheduled Café 124 tick of 14:00 UTC, the first scheduled one with
  the mail loop on, ended at 14:55:36 UTC with exit 0 after its work: one
  conversation escalated, one held for a person, the notice
  `assignment_read_incomplete`. Its mail intake took 5 seconds and the unit
  logged no error record through it.

