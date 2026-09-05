# Memory-code findings — brief

Small, verified defects and hygiene items in the engine's memory code, found
by two independent code reviews on 2026-09-05 while designing the shared
company memory (meta-repo brief `docs/briefs/2026-09-05-shared-company-memory.md`).
Each item carries the evidence; none is urgent, all are cheap.

## Bugs

1. **The chat CLI's entity count is always zero.**
   `engine/zylch/cli/chat.py:176` calls `BlobStorage()` with no arguments,
   which raises `TypeError` (the constructor requires a session factory);
   the enclosing `except` swallows it, so the status line reports 0 entities
   regardless of what memory holds. Fix: construct it the way every other
   call site does, and let a real failure surface instead of reading as an
   empty memory.

## Dead knobs (config that does nothing)

2. **`MemoryConfig.db_path`** (`engine/zylch/memory/config.py:17`, env prefix
   `MEMORY_`, default `.swarm/memory.db`): declared, never read anywhere.
   Setting `MEMORY_DB_PATH` silently does nothing.
3. **`Settings.database_url`** (`engine/zylch/config.py:33-36`): declared,
   never read. Same trap.
   Both mislead an operator into believing the storage location is
   configurable. Delete them, or wire them for real as part of the
   shared-memory work — never leave a knob connected to nothing.

## Hardening

4. **One owner-unscoped memory read.** `engine/zylch/agents/emailer_agent.py:234-241`
   (`_get_blobs_by_ids`) hydrates blobs by UUID with no `owner_id` filter —
   harmless today because the ids arrive from owner-scoped searches upstream,
   but it is the only read that trusts its caller. An owner filter costs one
   line.
5. **No `busy_timeout` pragma.** `engine/zylch/storage/database.py:61-66`
   sets WAL but no busy timeout: tuned for one writer per DB file, which is
   today's reality. Becomes mandatory the moment two processes share a
   memory DB — owned by the shared-company-memory work, listed here so it is
   not rediscovered.

## Acceptance

- The chat CLI status line reports the real entity count on a profile with
  memory.
- Grep finds no config field in `engine/zylch/` that no code reads.
- Every `Blob`/`BlobSentence` read is owner-scoped (or key-scoped, once the
  shared memory lands).
