# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

Four Café124 engine units run reviewed isolated release `83075a0` behind
`wss://desktop.mrcall.ai`. Bounded MrCall receipts, explicit provider/role policy,
OpenRouter GLM and persistent preparation/retry limits are implemented. The
compatible billing server runs `prod-c238edf8` with its additive accounting
migration. Authenticated capabilities and free quote pass.

All four affected profiles retain USD5 daily caps, explicit economy Haiku,
batch size 25, disabled automatic processing and durable preparation pause.
Three use their existing direct Anthropic keys; one uses MrCall credits. RPC
status verifies model policy and limits; no paid acceptance calls are made.
Other hosted units retain the previous checkout until normal reconciliation.
New automatic processing defaults off; existing explicit settings remain.

Failed extraction checkpoints (1,962 + 40) remain pending, with private backups
and task checkpoints preserved. Three-candidate merge selection and complete-
response validation retain LLM judgement without runaway comparisons or false
completion. See [spending protection](features/daily-llm-budget.md).
Desktop v0.1.48 source includes shared project RPC; its installer publication
is pending. GLM semantic task quality is unmeasured.

Shared written project memory is deployed. Dedicated project documents,
immutable revisions and a space identity live in the company memory database,
separate from entity blobs. `projects.*` supports selective reads and revision-
checked writes through cs-kernel v0.44.0. The company store contains
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

## Unresolved

- Desktop v0.1.48 installer publication and Mac installation remain to verify.
- Existing engine backlog remains separate: Calendar token integration,
  phone-call memory parity, additional RPC error humanization, and multi-profile
  WhatsApp session isolation. See [harness backlog](harness-backlog.md) and
  [remote backend](../../docs/remote-backend.md).
- Earlier incident counts, memory cleanup observations and packaged-platform
  acceptance gaps are retained in the archive. They were not re-measured during
  this project-memory rollout and must be rechecked before acting on them.
- A comprehensive security review and product chat remain deferred by the CTO.

## Next

1. Validate cheaper models per memory/task role before resuming automatic backlogs.
2. Ship the project RPC surface in the next Desktop bundled-engine release.
3. Continue the existing Calendar, phone-memory and error-handling workstreams
   under their owning plans rather than merging them into project storage.
