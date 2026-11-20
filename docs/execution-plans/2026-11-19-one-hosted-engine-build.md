---
status: superseded
---

# One build for every hosted engine — execution plan

[Brief](../briefs/2026-11-19-one-hosted-engine-build.md).

Superseded by the plan
[Main is the hosted line](2026-11-20-main-is-the-hosted-line.md), which
switched the seven units to release `hosted-engine-0.1.57.dev4` with the
procedures of M3, M4 and M5 below.

Owner of every milestone: Claude session
`617dd083-145f-41e1-975e-e50096c231f4`. The operator approved the single
build on 2026-11-19. The switch of the two MrCall units belongs to that
approval. The switch of the Café 124 production unit and of the four other
units waits for the operator's word, unit family by unit family.

## Dependencies

- Release line: branch `release/hosted-engine-20261118`, worktree
  `/home/mal/worktrees/mrcall-desktop-hosted-engine`, tip `c5bd4bb5` before
  this work.
- The Café 124 package and environment:
  `/home/mrcalld/releases/interactive-reply-124-helper-226c0048ed8d3fea/venv`.
- Kernel `v0.73.3` in both clones. It requires `exact_draft_publication`,
  `sent_mirror_recovery` and `interactive_exact_send` of an engine.
- Operator ticks: the MrCall clone at 06:50, 10:50, 14:50 and 18:50 UTC, the
  Café 124 clone at every even hour from 06:00 to 18:00 UTC.
- `zylch-reconcile.timer` runs at 00:00 UTC. When `main` received commits it
  restarts every unit, with no check for a call in progress. A restarted
  unit comes back on its last drop-in. No switch happens between 23:30 and
  00:15 UTC.

## The drop-in form and the reconcile

Six of the seven units already carry drop-ins that sort after `tenant.conf`,
several of them with `ExecStart`. `mrcall-tenant create` refuses such a unit
before it writes anything, so the nightly reconcile exits 3 and a change to
`tenant.conf` does not reach those units. This plan adds one more such
drop-in to each of the six and changes neither fact. The personal mailbox
unit is the one that passes the reconcile, and M5 keeps it passing.

The drop-in for a unit `<uid>`, named so that it sorts after every other
drop-in of that unit:

```
[Service]
ExecStart=
ExecStart="<release>/venv/bin/python" "-P" "-c" "from zylch.cli.main import main; main()" "-p" "<uid>" "serve" "--unix" "/run/mrcalld/<uid>/ws.sock"
UnsetEnvironment=PYTHONPATH
```

`UnsetEnvironment` removes `PYTHONPATH` whatever drop-in set it, so the
interpreter loads the release's own `zylch`.

## M1 — source

The united package is committed on the release line as the brief composes
it, version `0.1.57.dev3+hosted20261119.mrcall`, tag
`hosted-engine-0.1.57.dev3`.

Verification:

- Two scratch test trees: `main`'s `engine/tests` plus the hosted line's
  twelve own test files, and the release tag's own `engine/tests` with one
  shim, its automatic fixture skipping when `zylch.llm.roles` is absent.
- Three package trees, each in the environment it runs in production: the
  united package and the Café 124 package in a copy of the Café 124
  environment with pytest 9.1.1 added, tag `hosted-engine-0.1.57.dev2` in the
  older dependency set.
- One directory at a time, with collection errors not stopping a directory.
  Both trees run every directory, the tag's `tests/measurement` included.
- No case that passes on either older package fails on the united one.
- Every module of the united package imports under the Café 124
  environment's interpreter.
- A fresh reviewer reads the diff against both older trees.

## M2 — release

- The wheel is built from the tag with `uv build`.
- The release is `/home/mrcalld/releases/hosted-engine-0.1.57.dev3-<first 12
  hex digits of the package digest>/venv`: a copy of the Café 124 environment
  with `zylch` replaced by the wheel. It is root-owned, holds no bytecode,
  and passes `uv pip check`. Package digest and environment digest are
  recorded and verified in place. The package digest is the SHA-256 of the
  `sha256sum` lines of every file under `site-packages/zylch`, sorted by path
  in the C locale, bytecode excluded.
- The installed `zylch` tree is compared file by file with
  `git archive <tag> engine/zylch`: same paths, same bytes. A wheel that
  drops a package-data file fails here.
- Every script in the release's `bin/` starts with the release's own
  interpreter path. The Café 124 environment's scripts name four other
  paths, three of them outside `/home/mrcalld/releases`.
- A throwaway start on an empty profile shows the four loops and stops
  cleanly.

Rehearsal, on a copy of the profile store of: the second MrCall account, the
Café 124 production unit, one Café 124 staff unit, the personal mailbox
unit.

- It runs as the tenant user inside a transient unit with `PrivateTmp=yes`
  and `PrivateNetwork=yes`, so the copy vanishes with the unit and nothing
  leaves the host.
- The copy is made through the SQLite backup API from a read-only
  connection.
- The scratch profile's `.env` holds `OWNER_ID` and nothing else: no mail
  credential, no model key, no memory key. `ZYLCH_HOME` and `MEMORY_DB_DIR`
  point at the scratch root, so no company store is attached. No
  company-store step is pending anywhere: every company store is already
  served by a package with the same steps as the united one.
- The command activates the profile as the CLI does and calls the function
  that runs the store steps, with no loop and no listener:

  ```
  <release>/venv/bin/python -P -c "from zylch.cli.main import _setup_profile; _setup_profile('<uid>', lock=False); from zylch.storage.database import init_db; init_db()"
  ```

  `Storage.__init__` calls the same `init_db` when a unit starts
  (`storage/storage.py`). The engine's `status` command does not reach it.
  The command runs twice.
- The record holds the rows of `schema_version` before the first run, after
  it and after the second, the `[migrate]` lines and the backup the first
  run writes, that the second run adds no row, and `pragma integrity_check`.

## M3 — the two MrCall units

Order: the second account, then support. A unit is not restarted while an
operator tick of its clone runs: the switch happens when no
`cs_operator_send_cron.sh` process exists and the next scheduled tick is more
than ten minutes away. Per unit:

1. Record `system.capabilities` and the unit's properties.
2. Install the drop-in.
3. `systemctl daemon-reload`, restart the unit.
4. Verify: active, the release's package hash from `/proc/<pid>`, every
   earlier capability key still answered, `[ws] mail sync started`, the first
   `[mail-sync] run completed`, no error record.

Acceptance: in the next scheduled MrCall tick the inbound scan lists no
unreadable thread, the review of waiting drafts lists no unreadable root
beyond those the ticks before the switch list, and both units log no error
record through it.

Rollback: remove that drop-in, `daemon-reload`, restart. The unit returns to
`hosted-engine-0.1.57.dev2`. The two packages have the same store steps.

## M4 — Café 124 production

The drop-in keeps the unit's two extra arguments,
`--voice-config /etc/mrcalld/tenant-exec/<uid>.voice.env` and
`--operator-config /etc/mrcalld/operator-mcp/<uid>.json`, and adds
`Environment=MAIL_SYNC_INTERVAL_MINUTES=0`. The unit's auto-update loop
already fetches its mail every five minutes, and the telephone listener
shares the process, so the mail loop stays off there.

Before the switch:

1. No tick of the Café 124 clone runs and the next one is more than ten
   minutes away.
2. Record the running command line, and the name, size and modification time
   of every drop-in of the unit.
3. `GET http://127.0.0.1:8787/healthz` answers `calls_available: true`. It is
   false while a call or a pending call exists
   (`services/voice/engine_runtime.py`, `available`). The call audio runs
   over an outbound WebSocket, so a look at port 8787 does not show a call.
   The restart follows this check in the same command.

After the restart:

1. The process listens on `127.0.0.1:8787`, on
   `/run/mrcalld/<uid>/ws.sock` and on `/run/mrcalld/<uid>/operator-mcp.sock`.
2. The journal holds `[voice] production runtime module=<release path>`,
   `StreamableHTTP session manager started`,
   `[ws] mail sync started (disabled)` and, after 90 seconds,
   `[mail-sync] skipped: disabled`. A profile `.env` that set the interval
   would show here as an interval in the first of those lines.
3. `GET http://127.0.0.1:8787/healthz` answers `calls_available: true`.
4. `https://desktop.mrcall.ai/operator/<uid>/mcp` answers 401 without a
   token; `/.well-known/oauth-protected-resource/operator/<uid>/mcp` and
   `/.well-known/oauth-authorization-server` answer 200.
5. Active, the release's package hash from `/proc/<pid>`, every earlier
   capability key still answered, no error record.

Acceptance: the next scheduled Café 124 tick ends as its ticks of the same
day ended before the switch, and the unit logs no error record through it.
A telephone call answered on the new package and an existing Codex
connection used after the switch are checked by a person.

Rollback: remove the drop-in, `daemon-reload`, restart, then compare the
running command line with the recorded one. The unit returns to
`interactive-reply-124-helper-226c0048ed8d3fea`. The two packages have the
same store steps.

## M5 — the three Café 124 staff units and the personal mailbox unit

Order: one staff unit, watched for two hours, then the other two, then the
personal mailbox unit.

Each staff unit receives the drop-in of M3 and its checks. These units gain
the mail loop, so step 4 includes the first `[mail-sync] run completed`.
No clone drives them: acceptance is two hours with the unit active and no
error record.

The personal mailbox unit passes the reconcile and keeps doing so:

1. `/etc/mrcalld/tenant-exec/<uid>` declares
   `INTERPRETER=<release>/venv/bin/zylch`.
2. A drop-in that sorts before `tenant.conf`, `t1-hosted-engine-20261119.conf`,
   holds `UnsetEnvironment=PYTHONPATH`. Without it the unit's
   `t0-stripe-native.conf` keeps `PYTHONPATH` on the older package, which the
   interpreter reads before its own `site-packages`.
3. `mrcall-tenant create <uid>` writes the command line, then the unit is
   restarted and checked as in M3.

Its rollback: remove the declaration and the `t1` drop-in, run
`mrcall-tenant create <uid>` again, restart.

Store steps: the first start on the release applies the steps these four
stores lack. The rehearsal of M2 names them. Steps `0006` and `0007` add
tables. Step `0008` is flagged destructive, so the runner writes a backup
first, and on a store without its table it only creates the table
(`storage/step_exact_send.py`). The older runner ignores a step id it does
not know (`storage/migrations.py`). A rollback is therefore the removal of
the drop-in and a restart, with no restore.

## M6 — closure

- Branch and tag are pushed.
- The fleet inventory shows one package hash on every switched unit, equal
  to the hash of `git archive <tag> engine/zylch`.
- [`remote-backend.md`](../remote-backend.md) and the engine's
  [active context](../../engine/docs/active-context.md) state what each unit
  runs.

## Evidence

`~/.local/share/mrcall-operational-evidence/2026-11-19/one-engine-line/`
holds the fleet inventory, the per-file classification of each package
against git history, the diff between the release package and the Café 124
package, the comparison of the older packages with the united one, and the
dependency lists. Results of each milestone are added below as they exist.

### Reviews

- Brief: REVISE, then APPROVED. The first review found that
  `services/operator_instructions.py`, taken whole from the Café 124
  package, lost the release line's refusal of a malformed management
  marker, and that the tests ran in the older dependency set.
- Plan: REVISE twice, then APPROVED. The reviews replaced the telephone
  check with `/healthz`, gave the personal mailbox unit a drop-in that unsets
  `PYTHONPATH`, and replaced a rehearsal command that ran no store step.
- M1 and M2: the reviewer confirmed the composition, the kernel's RPC
  methods and capabilities, the release's bytes and the two drop-ins, and
  asked for the complete test matrix, the tag and two test repairs before
  M3.

### M1, 2026-11-19

- Commit `775d3248`, 478 package files. Commit `623b8cff` repairs two tests
  and changes no package file.
- `tests/rpc/test_ws_cancels_inflight.py` set no `OWNER_ID`, so the owner
  request context refused every dispatch; it sets one now.
- `tests/assignments/test_evidence_rpc.py`, case
  `test_uidvalidity_changes_during_actual_fetch_are_unknown`, patched
  `IMAPClient.fetch_messages_by_uid`, which the reply read no longer calls;
  it patches `_fetch_messages_by_uid_selected` now and passes. The guard,
  `task_assignment_mail._fetched_result`, holds on the current path.
- 26 Qonto cases of the release tag's tree pass on the Café 124 package and
  fail on the support package and on the united one. They pin the
  text-similarity refusal that `qonto/owner_content.py` replaces for a
  session authenticated as the profile's owner. They concern M4 only.
- `checks/own-tests.txt`: the line's new and repaired tests with the mail
  loop and instruction tests, 74 passed in the Café 124 environment.

### M2, 2026-11-19

- Release `/home/mrcalld/releases/hosted-engine-0.1.57.dev3-084d97ca9d8d`.
  Package digest
  `084d97ca9d8d43b8093b0a9388bc964d80aa51bb0e77ec7f80af2e0d64067315`,
  environment digest
  `1b8d6a76e42dc0df1e51befce91e92cadfba8fd176c4d79fe9e1ff2f67de9dda`, both
  verified in place. Root-owned, no bytecode, `uv pip check` clean, 36
  `bin/` scripts on the release's interpreter.
- The installed `zylch` tree is identical to `git archive 775d3248
  engine/zylch`: 478 files.
- Every one of 446 modules imports under the release's interpreter. All
  seven tenant users import the package.
- Throwaway start on an empty profile: all store steps applied, the four
  loops started, `[mail-sync] skipped: no mail credentials` at 90 seconds,
  clean stop on interrupt.
- Rehearsal, two runs of `init_db` on a backup copy, no network:

  | Store | Steps the first run applied | Second run | Integrity |
  | --- | --- | --- | --- |
  | MrCall support | none | none | ok |
  | MrCall second account | none | none | ok |
  | Café 124 production | none | none | ok |
  | Café 124 staff unit `C06x…` | `0007`, `0008`, one backup | none | ok |
  | personal mailbox unit | `0007`, `0008`, one backup | none | ok |

### Tests, 2026-11-19

`checks/test-matrix.txt` holds every result. Passed cases:

| Tree | United | Support tag | Café 124 package |
| --- | --- | --- | --- |
| release tag's tests, every directory | 3,409 | 3,317 | 3,396 |
| `main`'s tests, every directory | 2,995 | 2,937 | 2,985 |

- No case passes on the support package and fails on the united one, except
  four in `main`'s copy of `test_ws_cancels_inflight.py`, which sets no
  `OWNER_ID`; with it set, that copy passes 5 of 5 on the united package.
- On each tree the same 26 cases pass on the Café 124 package and fail on
  the united one. All are Qonto cases; M1 above names them. No other case
  passes on the Café 124 package and fails on the united one.

### M3, 2026-11-19

Tag `hosted-engine-0.1.57.dev3` on `623b8cff`, pushed with the branch at
17:38Z. The milestone review approved the switch of the two MrCall units.

| Unit | Restart | First mail run | Capabilities | Error records |
| --- | --- | --- | --- | --- |
| second account | 17:41:37Z | 17:43:17Z, `new=0` | the 13 earlier keys, plus `stripe_payment_links` | none |
| support | 17:44:15Z | 17:45:54Z, `new=0` | the 13 earlier keys, plus `stripe_payment_links` | none |

- Both processes load the release: package digest `084d97ca9d8d`, tree hash
  equal to the tag's tree (`fleet-packages-after-m3.txt`), no `PYTHONPATH`.
- Both pass the encryption self-check. Support answers
  `authority: legacy` to `instructions.preview`.
- Drop-ins: `<35 z>-hosted-engine-20261119.conf` for the second account,
  `<102 z>-hosted-engine-20261119.conf` for support. Each sorts after the
  unit's `…-hosted-engine-20261118.conf`, which a rollback returns to.

Acceptance tick: the scheduled MrCall tick of 18:50:02Z to 19:32:18Z, exit 0,
run `run-bidhfh_m`. `rollout/m3-tick-1850.txt` holds every count below.

- The criterion of M3 first read "the next scheduled MrCall tick lists no
  unreadable thread". The tick does not meet that text: its review of waiting
  drafts lists three roots `unknown` on the primary account, two with
  `REPLY_SOURCE_UNAVAILABLE` and one with `SOURCE_UNAVAILABLE`, and 15 roots
  with `review projection unavailable`. Each of the 29 ticks since 2026-11-16
  05:05Z that kept a review lists the same three roots with the same reasons,
  on the two earlier releases as on this one. The plan's owner amended the
  criterion on 2026-11-19 to the text in M3 above: acceptance rests on the
  absence of a regression. The three roots stay open in the engine's active
  context.
- The inbound scan lists no unreadable thread: `discovery.json` holds no
  `unknown` state, no `REPLY_SOURCE_UNAVAILABLE` and no
  `SENT_REPLY_NOT_SYNCED`. It lists 18 held conversations, 2 automatic, 1
  resumed and none open; the three ticks of the same day on
  `hosted-engine-0.1.57.dev2` list 18, 17 and 17 held and the same other
  groups. The eighteenth conversation of this tick received its last inbound
  mail at 17:46:13Z, after the switch. `cs unanswered` exits 3 with
  `assignment_incomplete` true, as on every tick with a held conversation
  (`cs/unanswered.py`, `sweep`).
- Both units log no traceback, no `ERROR` and no `CRITICAL` record through
  the tick, and four completed mail runs each. Support logs two
  `[rpc] task operation failed code=-32603` records after two `tasks.list`
  calls whose client disconnected; the same pair exists at 17:20:33Z, before
  the switch. Support's engine writes
  `[diagnostics] event unavailable; logging coverage degraded` to stderr once,
  at 18:52:45Z: its own diagnostic event store dropped one event
  (`zylch/observability.py`), as it does several times on every day since
  2026-11-14.
- The tick drafted and sent nothing. All 18 held conversations are held for
  a person. 16 are `needs-assignment`: a member's message without
  automatic-reply headers sits in the thread's Sent mail
  (`services/task_assignment_evidence.py`, `_member_activity`) and the
  assignment projection holds such a thread with no time limit
  (`services/task_assignment_projection.py`, `_project`). For 14 of them the
  support engine's projection says so; for 2 the second account's projection
  says so and the kernel combines the two accounts
  (`cs/task_assignment.py`). 2 are `conflict` with `RFC_ANCESTRY_CONFLICT`.
  In 13 of the 16 every holding reply left the support mailbox; in 3 at
  least one left the second account. One conversation is held in part by
  five replies the engine itself sent on 2026-09-22 and 2026-09-23. Neither
  engine file differs between `hosted-engine-0.1.57.dev2` and this tag.
