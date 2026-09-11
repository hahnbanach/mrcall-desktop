# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

Daily spending admission is deployed to four Café124 engine units from isolated
`da85537`: three direct-key profiles have per-call reservations; the credits-mode
profile refuses paid AI pending a debit-bound proxy contract. All four automatic
pipelines are paused; RPC/read access is available. Confirmed failed extraction
checkpoints (1,962 + 40) are restored to pending, with backups and task checkpoints
preserved. New merge candidate selection and complete-response validation retain
LLM judgement while preventing runaway comparisons and false completion.
See [spending protection](features/daily-llm-budget.md) for scope and limitations.

The unchanged hosted engine units run `b875cb5` behind `wss://desktop.mrcall.ai`. Seven profile
services, provisiond and Caddy are active. The companion Desktop installer is
v0.1.47; its bundled sidecar predates shared project RPC.

Shared written project memory is deployed. Dedicated project documents,
immutable revisions and a space identity live in the company memory database,
separate from entity blobs. `projects.*` supports selective reads and revision-
checked writes through cs-kernel v0.44.0. Import and independent downloads verify
six 124 projects (28 documents) and four MrCall projects (23 documents), including
binary attachments. Original clone folders are archived byte-exactly in private Git histories
(124 `abd48c8`, MrCall `3f53462`) and removed from working trees. A second 124 owner
sees the same six projects. See [project memory](features/project-memory.md).

Company membership is a capability held in the profile; `memory.join` is its
only write path. Company records share visibility while owner-scoped rules stay
private. Project joins retain compatible revision histories and refuse divergent
histories before membership changes. Profile databases retain mailbox data,
tokens and cursors; the company store owns shared memory. The binding inventory
is `zylch/storage/database.py:MEMORY_TABLE_NAMES`.

Setup evidence, Firebase identity and billing policy are served to Desktop and
kernel through the existing authenticated RPC transports. `setup.state` reports
mailbox preparation evidence without claiming reply quality. Firebase ID tokens
remain memory-only. The hosted source includes the earlier chat-context budget,
IMAP transport deadlines and processing cost controls; their dated delivery notes in
the archive are not current deployment claims.

Project storage, joins, RPC contracts and the installed kernel journey were
verified with isolated SQLite stores and a real local WebSocket. Production
project import used authenticated remote RPC and byte-exact downloaded checks.
No sending, draft creation or paid agent tick was used as project acceptance.

## Unresolved

- Project RPC needs inclusion in the next bundled-engine Desktop release.
- Existing engine backlog remains separate: Calendar token integration,
  phone-call memory parity, additional RPC error humanization, and multi-profile
  WhatsApp session isolation. See [harness backlog](harness-backlog.md) and
  [remote backend](../../docs/remote-backend.md).
- Earlier incident counts, memory cleanup observations and packaged-platform
  acceptance gaps are retained in the archive. They were not re-measured during
  this project-memory rollout and must be rechecked before acting on them.
- A comprehensive security review and product chat remain deferred by the CTO.

## Next

1. Establish bounded MrCall-credit debits before broader guard rollout; validate
   cheaper models per memory/task role before resuming automatic backlogs.
2. Ship the project RPC surface in the next Desktop bundled-engine release.
3. Continue the existing Calendar, phone-memory and error-handling workstreams
   under their owning plans rather than merging them into project storage.
