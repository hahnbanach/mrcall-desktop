# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

[K3 max adoption](features/k3-reasoning.md) is deployed on four Café124 units
in isolated release `8d83193`. The credit server is `prod-99091c35`. Both payment
paths bind maximum reasoning and an 8192-token combined cap before admission.
Production is configured as custom K3 through MrCall credits, including all five
worker roles and reply classification. The other three profiles retain their
previous billing/model settings pending the CTO's billing preference.

Authenticated production identity, credit model catalog and paused preparation
checks pass. The production K3 quote passes. A synthetic execute returned HTTP402
before provider dispatch because MrCall credits were insufficient; no paid K3
response was verified. Its isolated USD0.30 test ledger retains a USD0.209 hold,
separate from hosted profile budgets. No inference retry was attempted.

Production retains its current USD20/day cap; the other three retain USD5/day.
All four retain automatic processing off and preparation paused/not running.
No mailbox backlog was resumed. Other hosted units were not restarted.

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
Captured saved memory prompts have contradictory FACT-format instructions.
Source now appends a serialization-only contract without retraining or changing
business rules. This has not been re-evaluated for model quality. K3 max runtime
support is deployed; saved profiles remain paused.

Email extraction and task detection request 4096 and 2048 output tokens; the
K3 adapter promotes both to its combined 8192-token reasoning/final ceiling.
Completion guards and spending admission are preserved. Complete tool
responses labelled `end_turn` are normalized by the shared compatible-response
wrapper; malformed, refused or truncated responses remain rejected. Generic
trainer FACT instructions and FACT value parsing are corrected in source.
These changes are included in the pinned hosted release. Saved prompt records
are unchanged; the serialization instruction is appended at runtime. The earlier three-case evaluation is
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
