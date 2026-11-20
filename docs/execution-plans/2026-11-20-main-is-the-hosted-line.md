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
arguments and `MAIL_SYNC_INTERVAL_MINUTES=0`, the checks before the restart
with `calls_available: true` in the same command, the checks after it.

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

Rollback, per unit: as M5 of the one-build plan.

## M7 — closure

- The fleet inventory shows one package hash on seven units, equal to the
  hash of `git archive hosted-engine-0.1.57.dev4 engine/zylch`.
- [`remote-backend.md`](../remote-backend.md), the engine's
  [active context](../../engine/docs/active-context.md) and the
  [task assignment contract](../../engine/docs/features/task-assignment.md)
  state the one line, the release and the limit.
- The one-build plan is `superseded` by this one.
- The first reconcile after the push is read the next morning. Expected:
  exit 3 with the same six units refused, `pip install -e` on the base
  environment, seven units restarted, each back on the `dev4` package hash.

## Evidence

`~/.local/share/mrcall-operational-evidence/2026-11-20/main-is-the-hosted-line/`.
Results of each milestone are added below as they exist.
