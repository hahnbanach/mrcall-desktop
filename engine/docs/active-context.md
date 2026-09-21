# Active Context — Engine

<!-- doc-scope:start -->
Scope: current engine capabilities, verified deployment and unresolved work.
Durable references are routed by [README.md](README.md); previous observations
are preserved in [active-context-archive.md](active-context-archive.md).
<!-- doc-scope:end -->

## State now

Engine chat now supports negotiated read-only policy version 1. The policy is
enforced before slash/semantic/task routing and again at assistant and task
executor tools; read-only turns do not acknowledge notifications or enqueue
auto-sync work. Kernel `cs ask` requires this capability. The focused M1 suite
proves that explicit mutation refusal leaves complete persisted table values
unchanged and never initializes the agent, creates a background job or requests
an LLM budget reservation. It also covers a real kernel-client → RPC →
dispatcher refusal, while help and search tools remain available. This is
implemented and tested locally, not deployed.

Four Café124 units run isolated release `8d83193`; the billing server runs
`prod-99091c35`. Production selects personal OpenRouter/custom K3 for its base
model, five worker roles and reply classification. The other three profiles
retain their previous billing/model settings. Production's daily cap is USD20;
the other three caps are USD5. Automatic processing is off and preparation is
paused/not running in all four. Other hosted units retain their own release pins.

[K3 max](features/k3-reasoning.md) uses Chat completions pinned to DigitalOcean.
The adapter promotes worker limits to a combined 8192-token reasoning/final cap
before quote and budget admission. Synthetic live BYOK acceptance verifies a
complete response, positive reasoning usage and actual-cost settlement. The
configured client factory resolves OpenRouter/K3. A saved Anthropic key is
inactive while OpenRouter is selected.

The credit path passes authenticated quotation and offline HTTP/ledger tests;
a funded live K3 response is unverified. Its isolated test ledger retains a
USD0.209 hold after the server refused insufficient credits before dispatch.
The separate successful BYOK test ledger has no remaining hold. Neither test
ledger changes the hosted production allowance.

Memory extraction and task detection retain completion guards and budget
admission. Merge selection limits expensive candidates. Saved extraction prompts
receive a serialization-only contract for structured FACT output without
retraining or changing business rules; its quality effect remains unmeasured.
See [spending protection](features/daily-llm-budget.md) and the
[reviewed comparison](../../docs/evaluations/2026-09-16-reviewed-model-comparison.md).
The comparison separates decisions, explanations and uncertain claims; it does
not certify production error rates. Older semantic scores are superseded.

Shared written projects use company-store documents, immutable revisions and
revision-checked `projects.*` writes, separate from entity blobs. Company
membership is a capability changed only by `memory.join`; owner rules remain
private. Profile databases retain mailbox data, tokens and cursors. See
[project memory](features/project-memory.md) and `MEMORY_TABLE_NAMES` in
`zylch/storage/database.py` for the storage binding.

Authenticated RPC serves setup evidence, identity, catalogs and billing policy.
`setup.state` describes preparation evidence, not reply quality. Firebase ID
tokens stay in memory. Claude Code headless runs in a clone and is outside engine
API budgets; see [control boundaries](../../docs/operator-setup.md#ai-execution-and-controls).

## Unresolved

- The remaining three profiles await a billing choice; funded credit acceptance
  remains open. No backlog resumption is part of model configuration.
- Incident checkpoint counts and project inventories in dated records are
  historical; re-read current state before a cleanup or backlog operation.
- Desktop v0.1.49 installation and personal-key entry on the CTO's Mac remain
  unverified. Saved-prompt format repairs have no new business-quality result.
- Calendar token integration, phone memory parity, RPC error humanization and
  WhatsApp multi-profile isolation remain separate [backlog](harness-backlog.md)
  work. Product chat and comprehensive security review remain deferred.

## Next

1. Resolve billing choices and finish funded credit acceptance without replaying
   uncertain requests. Keep automatic processing and preparation paused.
2. Verify the Mac application through its GUI; start a bounded batch only when
   requested and review its role-specific outputs.
3. Continue other workstreams under their existing plans.
