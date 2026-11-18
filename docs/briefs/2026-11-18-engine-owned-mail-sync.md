# Engine-owned mail sync

## Intent

A hosted engine keeps its own mail archive current. A client that only reads an
engine gets answers from a current archive without first asking for a sync.

The operator's direction of 2026-11-18: behaviour the kernel drives today moves
into the engine, so that the kernel's interface can be removed or kept for
special cases. A script outside the engine, or a wider kernel loop, goes the
other way. Triggering mail intake is the first behaviour to move.

## Observed failure

A `zylch serve` daemon fetches mail when a client asks for it, through
`sync.run`, `update.run` or a chat command, or when `AUTO_UPDATE_ENABLED` is on.
That flag also runs the paid memory and task stages (`rpc/server_ws.py`,
`_auto_update_loop`); with it off the loop logs `skipping tick` and fetches
nothing. The daemon's other loop, `_whatsapp_refresh_loop`, keeps WhatsApp
current every 15 minutes at no cost. Mail has no counterpart.

The MrCall clone reads two accounts, each served by its own engine. Its kernel
calls `sync.run {scope: "email", days_back: 14}` before every tick on the
default account only (`cs/operator_recovery.py`, `_mail_intake`) and reads
`tasks.assignment.project` from both (`cs/task_assignment.py`, `projections`).
On 2026-11-17 the second account's engine had mail cursors of 2026-10-09. Its
owner had answered one thread by hand: the reply was in the provider's Sent
folder and not in the archive. `services/task_assignment_sent_index.py`
answered `SENT_REPLY_NOT_SYNCED`, the projection answered
`REPLY_SOURCE_UNAVAILABLE`, and the kernel read that thread as `unknown` on
every tick from 2026-11-14 to 2026-11-17. The engine recorded
`assignment.sent_correspondence.archive_absent` 84 times for it. One manual
`sync.run` on that engine made the thread readable.

## Scope

1. A mail loop in the WebSocket daemon, beside the two existing loops. Every
   `MAIL_SYNC_INTERVAL_MINUTES` it runs the email-only intake with the
   parameters the kernel sends today, `{scope: "email", days_back: 14}`. The
   default is 10 minutes and `0` disables the loop. The value comes from the
   process environment, as `WHATSAPP_REFRESH_MINUTES` does. A profile without
   mail credentials runs nothing.
2. One intake implementation in `rpc/setup.py`. The loop and the RPC share the
   worker-thread entry and the lock.
3. An RPC caller that arrives while a loop run is in flight receives that run's
   result when it ends: the same shape, `scope: "email"`, `busy: false`. It
   starts no second run and it awaits a future, so it holds no thread and does
   not block the event loop. The caller therefore waits at most as long as the
   run it would otherwise have started, which keeps the kernel inside its
   180-second intake budget in every case where its own run would have been.
   Two RPC callers keep the existing `busy` refusal. A loop tick that arrives
   while an RPC run is in flight starts nothing and waits for its next
   interval.
4. The email-only intake on the source lines that lack it. Three lines exist
   for the touched files:
   - `origin/main` (`05bf7a20`), where the change and its tests are built. Its
     `sync.run` has no `scope` and awaits the synchronous IMAP sync on the
     daemon's event loop. It has no `zylch.observability_producers` module, so
     its email-only worker is the support family's worker without the
     diagnostics calls.
   - The family the second account's engine runs. It has the diagnostics
     module and no email-only intake. It receives the support family's worker
     with its diagnostics calls. This port is the one the hosted acceptance
     needs: `rpc/setup.py`, `services/process_pipeline.py`, `rpc/server_ws.py`.
   - The family the support engine runs. It has the email-only worker
     (`_email_intake_lock` in `rpc/setup.py`, `include_whatsapp` in
     `services/process_pipeline.py`). It receives the shared entry, the joined
     result of item 3, the log record of item 5 and the loop:
     `rpc/setup.py`, `rpc/server_ws.py`, `services/process_pipeline.py`. This
     port is needed before the loop runs on the support engine, not for the
     second account.
5. A mailbox progress line is a log record. Today
   `services/process_pipeline.py`, `_run_sync`, prints those lines through a
   console bound to stderr for every caller: each names its mailbox and a
   failure quotes the provider's error. They are not log records, so the
   private scope of the hosted families does not redact them, and a daemon's
   stderr is its journal. As a record, `[sync] <mailbox>: <message>` at INFO,
   the line is masked wherever that scope applies, on every scope of
   `sync.run`, and stays readable in a log without it. One line changes.

## Out of scope

- The kernel and the clones. The kernel's pre-tick `sync.run` keeps working
  against an engine that runs the loop. Removing it is a later kernel change.
- The paid pipeline. `AUTO_UPDATE_ENABLED` keeps its meaning and its default.
- A sync inside `tasks.assignment.project`.
- The Desktop app's behaviour. The stdio sidecar starts no daemon loop. On
  `origin/main` its `sync.run` gains the optional `scope` parameter. With the
  parameter absent it behaves as before, except that its mailbox progress
  lines reach the sidecar's stderr as log records and not as console lines.
- Rollout. Installing the change on a hosted instance needs the operator's
  word, instance by instance.

## Constraints

- The loop calls no language model and no paid stage: no `update.run`, memory
  extraction, task detection, training or preparation. It touches no WhatsApp,
  MrCall, Qonto or banking source.
- Intake runs in a worker thread. The daemon's event loop keeps serving RPCs
  and WebSocket keepalives during a sync. A sync awaited on the event loop is
  what cost a client its socket after 71 seconds on 2026-11-17.
- UID cursors, overlap, deduplication, mailbox error reporting and the
  `sync.run` result shape, including the `scope` echo, are unchanged.
- One sequential loop: its own runs never overlap. A failed run is logged and
  the loop continues.
- A loop run leaves no mailbox address and no provider error text in the
  daemon's output, on a family that has the private log scope: its log
  records are metadata only, and it prints nothing to stderr. The loop's own
  `[mail-sync]` line stays readable; on a failure it carries the humanized
  error titles, which can name the mail server's host.
- New text and log lines are English and name no secret.

## Acceptance

Focused tests on the source:

- with an interval set, the loop runs the email-only intake with
  `{scope: "email", days_back: 14}` and no other stage; with `0`, or without
  mail credentials, it runs nothing;
- a failing intake is logged and the next interval runs;
- an RPC `sync.run {scope: "email"}` that arrives during a loop run returns
  that run's result, not `busy`, and the mailbox sync ran once; a second RPC
  during an RPC run is answered `busy`; a loop tick during an RPC run starts
  nothing;
- while an intake run is blocked in its worker thread, the event loop answers
  another RPC, which is the property the WebSocket keepalive depends on;
- through the dispatcher, `sync.run {scope: "email"}` is accepted on the line
  that gains the parameter;
- fresh fake-provider mail is stored by a loop run and read back;
- a loop run, successful or failing, prints nothing to the pipeline's
  console; on both scopes of `sync.run` the mailbox progress line is a log
  record, readable on a family without the private log scope and metadata
  only on one that has it;
- on a family with the private log scope, a record logged inside a loop run
  carries no mailbox address.

Hosted, on the second account's instance, with no client asking for a sync:

- the daemon's log records one completed mail run per interval;
- a reply its owner sends by hand from that mailbox, in a thread the company
  holds, is read `needs-assignment` by the next scheduled MrCall tick that
  starts more than one interval later, with no `unknown` thread from that
  account and no `assignment.sent_correspondence.archive_absent` event for it
  after the run that stored it. Only the mailbox's owner can send that reply;
  the item is observed, not staged;
- the instance's usage record shows no paid request from the loop.

A mailbox's `last_sync_at` is not proof that Sent is current. It advances when
the Sent folder fails, because only an INBOX failure fails a sync
(`tools/email_archive.py`, `incremental_sync`).

Completion also needs the two-clone operational acceptance asked of every
engine change: scheduled ticks of both clones observed after rollout.

## Assumptions

- The email-only intake fetches mail and computes embeddings locally. It calls
  no language model. It scans INBOX, Sent and the archive folder of every
  mailbox of the owner, the same mailboxes and Sent folder the projection
  inspects.
- A window remains. A reply sent less than one interval before a read can be
  absent from the archive for that read: the thread reads `unknown` once and
  heals at the next intake. Such a thread is held in either state.
- Mail that arrives while a joined run is in flight, after that run has scanned
  INBOX, is not in that caller's intake. The next loop run stores it within one
  interval.
- A race remains. `tasks.assignment.project` reads the thread's component from
  the archive at its start and again at its end
  (`services/task_assignment_projection.py`, `services/task_assignment_store.py`).
  A run that stores a message of that thread in between changes the component:
  the projection answers `conflict` / `ASSIGNMENT_CHANGED` with `complete`
  false, and the kernel grades the tick `assignment_read_incomplete`. It lasts
  one tick. The same race exists today on an engine with `AUTO_UPDATE_ENABLED`.
- Each hosted instance runs its own source family, and the families differ
  from `origin/main` well beyond the touched files: `origin/main` has no
  `services/task_assignment_sent_index.py`. In the three touched files the
  second account's family differs from `origin/main` by 3 lines
  (`rpc/setup.py`), 33 lines (`rpc/server_ws.py`) and none
  (`services/process_pipeline.py`); the support family differs from the second
  account's by 84, 5 and 7 lines.

## Rejected alternatives

- A crontab script that calls `cs --account NAME rpc sync.run`. It keeps the
  trigger outside the engine. The operator rejected it on 2026-11-18.
- The kernel's `_mail_intake` over every configured account. It grows the
  interface the direction removes.
- `AUTO_UPDATE_ENABLED` on the instance. It runs the paid stages.
- A sync inside `tasks.assignment.project` when it finds a Sent reply the
  archive lacks. It removes the window, and it puts a mailbox write of
  unbounded size inside a read that has a deadline. It can follow if the window
  proves to be a problem.
- An RPC caller that waits for a loop run and then starts its own. Two runs in
  a row can exceed the kernel's 180-second budget, and a caller whose client
  has gone would start a run nobody reads.
