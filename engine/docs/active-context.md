# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

Four Café124 units run reviewed isolated release `10477fd` behind
`wss://desktop.mrcall.ai`. Billing server `prod-a522596c` provides bounded
OpenRouter calls charged from actual decimal costs and a configured model
catalog. Personal-key routing supports Claude, GLM and K3 with provider caps.
Authenticated `llm.models` checks pass for personal and MrCall-credit catalogs.

All four affected profile files are unchanged byte-for-byte: USD5 daily caps,
saved economy Haiku, batch size 25, automatic processing off and preparation
paused. Three retain personal Anthropic keys; one retains MrCall credits.
Services are active and no mailbox processing was resumed. Other hosted units
follow normal source reconciliation. New automatic processing defaults off.
A synthetic production GLM credit call returned OK with a verified one-credit
debit. The isolated comparison budget includes that debit and prior holds.

Failed extraction checkpoints (1,962 + 40) remain pending, with private backups
and task checkpoints preserved. Three-candidate merge selection and complete-
response validation retain LLM judgement without runaway comparisons or false
completion. See [spending protection](features/daily-llm-budget.md).
Published Desktop v0.1.49 includes shared project RPC and the new model catalog.
The [model comparison](../../docs/evaluations/2026-09-15-controlled-model-quality.md)
and [reasoning comparison](../../docs/evaluations/2026-09-16-k3-reasoning-quality.md)
have superseded semantic grades and withdrawn quality recommendations. Neither
original nor intermediate counts establish business-decision error rates. The
[disputed cases](../../docs/evaluations/2026-09-16-disputed-case-review.md) distinguish
wrong tasks from unverified explanations. The offline preparer emits complete
per-label evidence; version 2 reviews require exact quotations and separately
assess decision, grounding, truth and impact. Legacy grades remain unassessed
under that protocol. The [selected source review](../../docs/evaluations/2026-09-16-reviewed-model-comparison.md)
covers all 240 selected outputs with separate action and explanation judgments.
The captured saved memory prompt has contradictory FACT-format instructions;
source review does not repair its runtime integration or change production.
Reasoning transport, evaluation provider pins and increased experiment ceilings
are not production configuration. Saved profiles remain paused.

Source email extraction and task detection ceilings are 4096 and 2048 output
tokens, with completion guards and spending admission preserved. Complete tool
responses labelled `end_turn` are normalized by the shared compatible-response
wrapper; malformed, refused or truncated responses remain rejected. Generic
trainer FACT instructions and FACT value parsing are corrected in source.
These changes are absent from the pinned hosted release; saved trained prompts
and model selections remain unchanged. The earlier three-case evaluation is
superseded by the controlled comparison for model-selection decisions.

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

- Desktop v0.1.49 installation on the CTO's Mac remains unverified.
- Existing engine backlog remains separate: Calendar token integration,
  phone-call memory parity, additional RPC error humanization, and multi-profile
  WhatsApp session isolation. See [harness backlog](harness-backlog.md) and
  [remote backend](../../docs/remote-backend.md).
- Earlier incident counts, memory cleanup observations and packaged-platform
  acceptance gaps are retained in the archive. They were not re-measured during
  this OpenRouter rollout and must be rechecked before acting on them.
- A comprehensive security review and product chat remain deferred by the CTO.

## Next

1. Keep automatic backlogs paused; apply the controlled comparison's role-specific
   quality findings before any model or hosted-release change.
2. Verify Desktop v0.1.49 installation on the CTO's Mac.
3. Continue the existing Calendar, phone-memory and error-handling workstreams
   under their owning plans rather than merging them into project storage.
