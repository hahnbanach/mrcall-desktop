# Main is the hosted line, and the member-activity hold ends after three days

## Intent

The engine has one line of code, `main`. Every hosted unit runs one package
built from one tag on `main`. A thread that a team member answered by hand
returns to the operator when the customer has then waited three days without
an answer.

The operator ordered both on 2026-11-20: every unit on the same build, on
`main`, and a limit of three days for the hold.

## What exists on 2026-11-20

- `main` (`ecba4c06`) runs on no unit. The two MrCall units run tag
  `hosted-engine-0.1.57.dev3` of branch `release/hosted-engine-20261118`.
  Café 124 production, its three staff units and the personal mailbox unit
  run three older packages. The
  [one-build brief](2026-11-19-one-hosted-engine-build.md) holds the
  inventory.
- The engine holds a thread as `needs-assignment` when a member's own message
  without automatic-reply headers is in the thread
  (`services/task_assignment_evidence.py`, `_member_activity`;
  `services/task_assignment_projection.py`, `_project`). Nothing ends that
  hold except an assignment task that is closed and followed by a new inbound
  mail.
- The MrCall operator tick of 2026-11-20 06:50 UTC lists 18 inbound
  conversations and holds every one. Two are `conflict`
  (`RFC_ANCESTRY_CONFLICT`). Sixteen are held by member activity:
  - in six, a member's message is newer than the customer's newest mail;
  - in five, the customer's newest mail is newer than every holding member
    message and older than 72 hours;
  - in five, it is newer than every holding member message and younger than
    72 hours.
- The kernel lists a held thread before it checks whether the thread is
  answered (`cs/unanswered.py`, `sweep`: `split_inbound` runs before
  `_partition`). So the six answered conversations appear in its list of
  conversations that wait for a person.

## Scope

1. **`main` takes the production engine.** One merge commit on `main` whose
   `engine/zylch` and `engine/pyproject.toml` are the tree of tag
   `hosted-engine-0.1.57.dev3`, and whose `engine/tests` is that tag's test
   tree plus `main`'s Stripe connection and identity tests. Every other path
   keeps `main`'s content.
2. **The hold gets a limit.** `_project` releases a thread held by member
   activity when the rule below says so.
3. **One release from `main`.** Tag `hosted-engine-0.1.57.dev4` on `main`,
   one release directory, the seven units, with the per-unit procedure of the
   [one-build plan](../execution-plans/2026-11-19-one-hosted-engine-build.md).

Out of scope, each its own work:

- Bringing the two candidates that `main` loses back onto the one line: the
  contextual email guard with its enrollment, and the typed Qonto
  credentials. No unit ever ran them. Tag `main-before-hosted-line-20261120`
  marks the commit that holds them.
- The kernel. It lists answered threads among the held ones, and it works on
  two conversations in a tick.
- The `RFC_ANCESTRY_CONFLICT` hold.
- The three review roots that read `unknown` on the MrCall support profile.
- The units' drop-in stacks, and the mailbox addresses in DEBUG RPC lines of
  the journal.
- The repository's checks on `main`. The RPC contract check fails on `main`
  today, and the tag's test tree has cases that fail on every package that
  ran it.
- A Desktop release built from the united engine.

## What the merge leaves out

Both sets stay in history.

- From `main`: five engine modules, `services/contextual_email_policy.py`,
  `services/task_assignment_draft_transaction.py`,
  `services/task_assignment_email_effect.py`,
  `services/task_assignment_enrollment.py` and `qonto/credentials.py`. The
  production package looks the first three up with `find_spec` and runs
  without them
  (`services/operator_reply_generation.py`,
  `services/exact_draft_transaction.py`,
  `services/exact_operator_send_admission.py`); with them present it applies
  the guard to stores that were never enrolled. It does not refer to the
  other two. Also `scripts/server/assignment_enroll.py`, which imports the
  enrollment module, and 33 test files: 32 written for `main`'s variants of
  the operator MCP, operator reply and rule modules, whose recorded cases
  fail on the united package, and one Stripe egress test that errors on it.
- From the hosted line: the 51 files outside the engine package and its tests
  that only that line has. They are M10 evaluations and plans, measurement
  scripts and the app's model-role settings code.

`engine/scripts/server` and `engine/scripts/systemd` keep `main`'s content.
The nightly reconcile runs `update-daemons.sh` from that directory as root
and installs the unit file from it, and the base checkout carries a local
change to that unit file, so a merge that touched it would stop the pull.

`engine/pyproject.toml` differs from `main`'s in the version and the
package-data list, not in a dependency. The reconcile reinstalls the base
environment when that file changes; the dependency set stays the same.

## The rule

A member's own message keeps a thread for people. The hold ends when both
hold:

- the newest message of the thread from outside the company is newer than
  every holding member message;
- that message is older than the limit.

While a member wrote last, the hold stays: the customer has an answer from a
person.

Terms, as the engine computes them:

- The thread is the RFC component of the root in the engine's archive
  (`task_assignment_mail.rows`).
- A message from outside the company is a stored row whose sender is not a
  member address of the company space. This is the test that already builds
  `current_message_ids`.
- A holding member message is a reply-evidence item judged
  `MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION`,
  `NONAUTOMATIC_MEMBER_REPLY_CANDIDATE`, `INTERNAL_MEMBER_CORRESPONDENCE` or
  `OWN_SENT_EXTERNAL_FOLLOWUP`. Its time is the stored time of its archive
  row.
- The limit is `MEMBER_ACTIVITY_HOLD_HOURS`, default 72. `0` or a negative
  value keeps the hold without a limit.

A released thread answers `state: normal`, `complete: true`,
`hold_auto_reply: false`, `reason: MEMBER_ACTIVITY_HOLD_EXPIRED`, with its
reply evidence unchanged. Kernel `v0.73.3` accepts that answer
(`cs/task_assignment.py`, `_validate_projection`) and reads no reason of a
`normal` projection.

A release reads the complete Sent membership first. When archive rows alone
would release the thread, the projection still runs the live Sent discovery
(`task_assignment_sent_index.candidates`). A newer member message that only
the Sent folder holds then answers `SENT_REPLY_NOT_SYNCED`, and the thread
stays `unknown` until the mail loop stores it.

A missing time keeps the hold.

Each engine applies the rule to what it holds: its own archive and the Sent
folders of its own mailboxes. The kernel holds a thread while any account's
engine holds it. One case stays held: a member answered last from their own
mailbox, and the customer then wrote only to another account's mailbox. That
member's engine does not see the later mail.

## What changes for a unit

- The two MrCall units: the rule, and nothing else. The package differs from
  the one they run in `services/task_assignment_projection.py`,
  `services/task_assignment_mail.py` and the version.
- The Café 124 production unit, its three staff units and the personal
  mailbox unit: what the one-build brief lists under "What changes for a
  unit", and the rule. The rule applies to the Café 124 operator as well.

## Constraints

- Those of the one-build brief: a live store is opened only as the daemon's
  user, no secret is printed or recorded, a release directory is root-owned
  and holds no bytecode, one unit at a time, a rollback is the removal of the
  unit's newest drop-in and a restart.
- The repository is public. No customer name, address or subject enters a
  commit.
- No unit restarts between 23:30 and 00:15 UTC, or while a tick of its clone
  runs. The Café 124 production unit restarts only after
  `calls_available: true`.
- The kernel and the clones do not change.

## Acceptance

Source:

- `git diff hosted-engine-0.1.57.dev3 <new tag> -- engine/zylch
  engine/pyproject.toml` names the two service files and the version line.
- The new tests pass, and each of four deliberate bugs in the rule, run on a
  copy, fails at least one of them.
- No case that passed on the `dev3` package on 2026-11-19 fails on the new
  package, in the same test tree and environment.

Each unit, after its switch: the checks of the one-build plan for that unit.

The MrCall operator, in its first tick on the new package:

- the conversations whose customer mail is older than the limit and newer
  than every holding member message are no longer among the held ones;
- the conversations where a member wrote last, or whose customer mail is
  younger than the limit, are still held;
- both engines log `[tasks.assignment] member hold expired` and no error
  record;
- the tick drafts, sends or escalates what it selects, and its exit code and
  health verdict are recorded.

The fleet: the package inventory shows one hash on seven units, equal to the
hash of `git archive <new tag> engine/zylch`.

Not covered: a telephone call answered on the new package and an existing
Codex connection used after the switch. Both need a person.

## Assumptions

- The stored time of a mail is its `Date` header in UTC. In the MrCall
  support store the two time columns agree on all 3,078 rows.
- The operator's order covers `main`, the tag, the push and the seven units.
