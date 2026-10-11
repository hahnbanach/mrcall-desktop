# Task management

## Private ordinary tasks

Ordinary tasks are `TaskItem` rows in the selected profile's `zylch.db`.
Their legacy `owner_id` is the mailbox email returned by `cli/utils.py`,
not a human assignee or Firebase UID. Sharing company memory does not share
these rows. Qonto task visibility has its own authenticated finance predicates;
ordinary task access must not expose financial tasks through company memory.

A task records an event, contact, title, required action, urgency, reason,
suggested action and source references. The unique key is
`(owner_id, event_type, event_id)`. Multiple tasks can refer to the same contact;
there is no database guarantee of one task per person. `sources.emails` links
email-backed tasks to archived messages and their threads. Task detection and
reanalysis are engine work; their paid calls use the saved engine billing and
preparation controls.

## RPC lifecycle

| Method | Behavior |
|---|---|
| `tasks.list` | Open visible tasks by default; `include_completed` and `include_skipped` opt in to those rows. Default limit is 200. |
| `tasks.list_by_thread(thread_id)` | Open ordinary tasks whose referenced emails belong to the exact thread. |
| `tasks.get(task_id)` | One visible open or closed row, including close audit; null for unavailable/missing results in the legacy storage path. |
| `tasks.create(contact_email, title, event_id, ...)` | Upserts the event key; refuses a closed target unless `reopen_if_closed=true`. |
| `tasks.complete(task_id, note?, actor?, why?)` | Closes a visible task and records close audit. |
| `tasks.reopen(task_id)` | Reopens a closed task and protects it temporarily from deduplication. |
| `tasks.snooze(task_id, due_at? , days?, actor?, why?)` | Requires exactly one absolute UTC epoch or relative day interval; parks an open task. |
| `tasks.pin(task_id, pinned)` | Changes the pin used in list ordering. |
| `tasks.skip(task_id)` | Records `sources.skipped_at`; ordinary listing omits it unless explicitly requested. |

`tasks.list(due_filter="all")` includes snoozed tasks. `due_filter="due_now"`
returns only tasks with no future `due_at`. Urgency uses critical, high, medium
and low; pinning takes precedence in list ordering. `due_at` means when to act;
`dedup_skip_until` protects a task against deduplication and is a separate field.

`completed_at`, `close_note` and `close_actor` retain the current close state.
Close and snooze history are retained in source metadata across ordinary upserts.
The legacy `actor` argument is caller-supplied audit text, including its default
`human`; it does not prove human presence or authorize company assignments.
Legacy storage getters can turn read failures into empty/null results. Such
results cannot establish authoritative absence of an assigned human.

## Company-assigned task subtype

The explicit assignment implementation has a separate company-bound subtype,
with `assigned_tasks`, `assigned_task_events` and `assigned_task_receipts`.
It retains stable Firebase identities, exact RFC thread identity, revisions,
operator-approved operations and closed audit without moving private TaskItem
rows into shared storage. Company joins refuse assignment-bearing source stores
until a lossless history migration is available.

The [assignment brief](../../../docs/briefs/2026-10-08-explicit-task-assignment.md)
and [delivery plan](../../../docs/execution-plans/2026-10-08-explicit-task-assignment.md)
own implementation and verification status. The APIs ship in Desktop `v0.1.56`;
six hosted company engines and both kernel `v0.51.0` clones have verified
assignment reads. [Assignment availability](task-assignment.md) records the
company-space limits and signed-write boundary. Installed GUI acceptance remains
separate from these API and CLI checks.

## Contextual email effects — unreleased candidate

Ordinary tasks remain private. Known email source context must retain its exact
original-message binding through contextual composition and sending; neither an
ordinary task's audit actor nor tool approval overrides a company assignment.
Multiple original sources in the same exact thread form a restrictive source
set; selecting one original can narrow it. Unavailable sources or conflicting
threads hold effects, including when a model drops reply headers.
The candidate [assignment contract](task-assignment.md#contextual-email-enforcement--unreleased-development)
covers the central draft and transport guard, enrollment, stale draft refusal and
source-free composition limit. The published releases retain their previous
scoped policy until a separately authorized rollout.

## Implementation references

- `zylch/storage/models.py`: private `TaskItem` schema.
- `zylch/storage/storage.py`: task CRUD, due filtering and retained audit.
- `zylch/rpc/methods.py` and `rpc/task_queries.py`: ordinary task handlers.
- `zylch/qonto/task_access.py`: ordinary versus finance visibility.
- `zylch/storage/assigned_task_models.py`: company assignment schema.
- [IPC contract](../../../docs/ipc-contract.md): transport and parameter rules.
