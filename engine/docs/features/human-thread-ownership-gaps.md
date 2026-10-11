# Human thread assignment — engine gaps

Date: 2026-10-07. Historical requirements for the selected assignment implementation.
The kernel design deliverable is
[human thread ownership](../../../../cs-kernel/docs/2026-10-07-human-thread-ownership-design.md),
under the meta-repository's October 6 bounded fan-out brief. Its operator
mechanism choice was resolved on 2026-10-08: explicit engine task assignments.
The [implementation brief](../../../docs/briefs/2026-10-08-explicit-task-assignment.md)
and [plan](../../../docs/execution-plans/2026-10-08-explicit-task-assignment.md)
own fresh implementation gates. The requirements below record the original gap;
the [assignment contract](task-assignment.md) describes current implementation
and verification limits.

## Original ordinary-task boundary

Ordinary TaskItem rows remain private. Their legacy `owner_id` is the mailbox
email, not a stable human UID or assignee; company memory membership does not
share these profile task stores. `sources.thread_id` and referenced email IDs provide thread lookup.
TaskItem itself has no assigned-human identity, assignment revision or company-level
thread-ownership uniqueness contract. The new company subtype adds those fields
separately rather than changing private TaskItem ownership.

`tasks.list_by_thread` returns open ordinary tasks. `tasks.get` can retrieve one
visible open/closed row with close audit, but requires its ID. Storage currently
converts lookup errors into empty/null, so neither result can prove authoritative
absence after an unreadable store. `tasks.create` has event-key idempotence and
closed-target refusal, without assignment-specific source validation or a
compare-and-swap revision.

## Original implementation requirements

- The selected mechanism is an explicit company-assigned task subtype. No
  clone-local ledger.
- Define verified company membership, stable human IDs and mailbox aliases;
  distinguish profile owner, company and assignee. Cross-company assignments
  refuse regardless of displayed email or shared thread header.
- Specify one authoritative company/thread assignment despite separate profile
  stores. Define how authorized profiles query it without broadening access to
  private ordinary tasks, including financial task visibility.
- Validate actual Sent/source provenance and the engine's human-reply judgement;
  an address-wide exchange or arbitrary `sources` JSON is not proof of takeover.
- Add atomic revision/idempotence and audit for assignment, reassignment and
  closure. Reject stale detector writes and conflicting human answers; preserve
  human changes and closed targets across replay/restart.
- Expose complete thread lookup including closed assignment audit and explicit
  unavailable/error outcomes. Unknown storage or membership cannot mean no owner.
- Define thread/task closure and explicit revision-checked handled supersession
  against inbound watermarks. A local handled record alone cannot close engine
  ownership; failed closure stays active/unknown and visible. Acknowledged
  handled closure ends assignment, and later inbound reopens operator work
  without reviving the old assignee. A verified answer awaiting human assignment
  remains visible in a needs-assignment queue with automatic replies held.
- Enforce scheduled read-only detection and denied ownership writes server-side;
  raw/generic RPC access must not bypass this boundary. Existing ordinary
  escalation tasks remain separate from an assertion of human takeover.
- Define source retention, assignment-history migration and rollback before any
  persistence change. Test real transport, concurrent writes and tenant isolation.

Kernel detection/rendering follows the separately reviewed implementation plan
and engine contract. This historical requirement record does not authorize a release,
deployment, live mailbox action or new unattended write.

## Source contract references

- `engine/zylch/storage/models.py`: `TaskItem` and its profile/event unique key.
- `engine/zylch/storage/storage.py`: `get_tasks_by_thread`, `get_task_by_id`.
- `engine/zylch/rpc/methods.py`: `tasks_create`, `tasks_complete`.
- `engine/zylch/rpc/task_queries.py`: open-only thread RPC and closed single-row RPC.
- `engine/zylch/qonto/task_access.py`: ordinary/private task visibility boundary.
