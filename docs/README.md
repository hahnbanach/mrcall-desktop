# MrCall Desktop — monorepo docs

<!-- doc-scope:start -->
Scope: the router for the documents under `docs/` — the ones that span
`engine/` and `app/` or describe the repository as a whole. It navigates and
nothing else: the repo's layout, roles and ownership live only in the index
file ([`../AGENTS.md`](../AGENTS.md)), and cross-cutting volatile state only in
[`active-context.md`](active-context.md).
<!-- doc-scope:end -->

This directory holds documentation that **spans the whole monorepo** —
things that touch both `engine/` and `app/`, or describe the repository
as a whole.

The repo has three parallel doc trees, mirroring the three index files. Each tree owns one concern; cross-cutting state lives here.

| If the doc is about… | It belongs in… |
|----------------------|----------------|
| The Python engine (CLI, channels, memory, storage, internal architecture, features, QA) | [`../engine/docs/`](../engine/docs/) |
| The Electron app (UI, packaging, IPC client side, electron-builder quirks, sidecar spawn from main process) | [`../app/docs/`](../app/docs/) |
| **Both** subsystems together (release process, JSON-RPC contract between sidecar and renderer, brand / rename rollout, monorepo conventions) | here, in `docs/` |

## Index

- [Cross-cutting runtime contracts](cross-cutting-contracts.md) — identity, company memory, hosted isolation and LLM billing; operating rules remain in AGENTS.md.

- [Qonto connection](briefs/2026-10-04-qonto-connection.md) — native Desktop setup and engine-owned financial source; [development plan](execution-plans/2026-10-04-qonto-connection.md), including the authorized support-only rollout.
- [Qonto IPC](qonto-ipc.md) — native bank methods, managed chat history and verification boundaries.
- [Qonto bootstrap removal](briefs/2026-10-08-qonto-bootstrap-removal.md) — typed login and key as the only Qonto credential source, and what Desktop `v0.1.56` does against it; [plan and evidence](execution-plans/2026-10-08-qonto-bootstrap-removal.md).
- [Additional mailboxes and PEC](../engine/docs/features/mailboxes.md) — multiple IMAP sources, PEC envelope extraction and Desktop Settings; [original plan](execution-plans/2026-09-30-pec-net-mailbox-integration.md).
- [PEC and Qonto next-release integration](execution-plans/2026-10-05-mailboxes-qonto-release-integration.md) — combined source, migration/auth verification and shared-main delivery; no installer or hosted rollout.
- [GPT-Live customer-service channel](brief/2026-09-23-gpt-live-engine-integration.md) — incoming calls with asynchronous company memory first; agent configured by cs-operator. [Four-milestone plan](execution-plans/2026-09-23-gpt-live-engine-integration.md); repeatable integrations and outbound support follow.
- [Desktop voice alpha UX](briefs/2026-09-25-desktop-voice-assistant-alpha-ux.md) — customer setup and preview journey; the [original Café 124 pilot plan](execution-plans/2026-09-25-desktop-voice-assistant-alpha-ux.md) is superseded by the existing-business test input.
- [Café 124 production voice brief](briefs/2026-09-27-cafe124-voice-daemon.md) — one-number GPT-Live alpha in the existing `production@` daemon; [execution plan](execution-plans/2026-09-27-cafe124-voice-daemon.md) completed for the scoped manual/identity/archive and source-grounded service-answer gates.
- [Shared company knowledge for GPT-Live](briefs/2026-09-28-voice-company-knowledge.md) — approved brief for shared sources, initial company context and detail retrieval; [reviewed execution plan](execution-plans/2026-09-28-voice-company-knowledge.md) with source authority and caller disclosure as its first gate.
- [Telephone source migration](briefs/2026-10-01-telephone-notes-source-is-phone-md.md) — production uses stored `phone.md`; [execution and review](execution-plans/2026-10-01-telephone-notes-source-is-phone-md.md), including Mario’s migrated reader; [initial Astra review](evaluations/2026-10-01-astra-company-instructions-migration-review.md) and [APPROVED P1 repair](evaluations/2026-10-01-astra-instruction-write-denial-rereview.md).

- [Complete selected-case review](evaluations/2026-09-16-reviewed-model-comparison.md) — all 60 selected cases / 240 outputs, concrete errors, separate uncertainty and measured costs.
- [Disputed case evidence](evaluations/2026-09-16-disputed-case-review.md) — exact source/model excerpts, equal Opus/K3 criteria and withdrawn operational-error claims.
- [Grading correction](evaluations/2026-09-16-grading-correction.md) — corrected company facts, concrete payment evidence, revised labels and withdrawn quality recommendations.
- [K3 reasoning comparison](evaluations/2026-09-16-k3-reasoning-quality.md) — controlled disabled/max reasoning quality, observed costs and deployment boundary.
- [Controlled model comparison](evaluations/2026-09-15-controlled-model-quality.md) — 360-response role-specific quality, costs, compatibility and deployment decision.

- [OpenRouter credits](briefs/2026-09-13-openrouter-credits.md) — payment/model boundaries and [delivery plan](execution-plans/2026-09-13-openrouter-credits.md).
- [Model comparison](evaluations/2026-09-13-openrouter-models.md) — blinded synthetic evidence and limitations.
- [Actual-prompt comparison](evaluations/2026-09-15-real-engine-prompts.md) — K3/GLM source-grounded checks, availability and prompt corrections.

- [Desktop setup to operator workspace](briefs/2026-09-10-desktop-to-operator-onboarding.md) — proposed end-to-end setup journey, current evidence, and future delegation boundary.
- [Desktop, MCP and daemon data flows](operator-data-flows.md) — English sequence diagrams for authentication, all nine candidate tools, local files and revocation; existing behavior, unreleased local candidate and remote proposal are labeled separately.
- [Chat approval isolation](briefs/2026-09-10-chat-approval-isolation.md) — scoped existing cross-client approval defect and acceptance criteria.
- [`active-context.md`](active-context.md) — cross-cutting living snapshot: `State now` / `Unresolved` / `Next`, nothing else
- [`active-context-archive.md`](active-context-archive.md) — dated narrative pruned out of the living snapshot
- [`ipc-contract.md`](ipc-contract.md) — the JSON-RPC method surface between `app/src/main/` and `engine/zylch/rpc/`
- [`remote-backend.md`](remote-backend.md) — running the engine as a remote daemon (mrcalld, per-uid sockets, Caddy/TLS), operator guide + runbook
- [`briefs/2026-09-08-shared-company-memory-implementation.md`](briefs/2026-09-08-shared-company-memory-implementation.md) — shared company memory: the key, per-family scope, one store per company, join; plan in [`execution-plans/2026-09-08-shared-company-memory-implementation.md`](execution-plans/2026-09-08-shared-company-memory-implementation.md), host operations in `remote-backend.md` ("Shared company memory on the host")
- [`harness-backlog.md`](harness-backlog.md) — cross-cutting enforcement / tooling gaps
- [`claude-agent-sdk-analysis.md`](claude-agent-sdk-analysis.md) — evaluation of the Claude Agent SDK against the engine's own agent loop
- [`briefs/`](briefs/) — the what/why half of a work trace, paired with the execution plan of the same `YYYY-MM-DD-<slug>`
- [`execution-plans/`](execution-plans/) — workstreams that span both subsystems, one file each, `status:` in the frontmatter
- `.doc-profile` — doc-harness configuration (leaf mode, `AGENTS.md` as the project index and managed v9 harness entry point)

The release pipeline (tag-driven matrix, signing, notarization,
electron-builder quirks) is documented inside
[`execution-plans/release-and-rename-l2.md`](execution-plans/release-and-rename-l2.md).

Engine-side and app-side counterparts (worth knowing about from
anywhere in the repo):

- [`../engine/docs/active-context.md`](../engine/docs/active-context.md) — engine-side "what's working / in-flight"
- [`../engine/docs/ARCHITECTURE.md`](../engine/docs/ARCHITECTURE.md) — engine system map
- [`../engine/docs/CONVENTIONS.md`](../engine/docs/CONVENTIONS.md) — engine code style, logging, security patterns
- [`../app/CLAUDE.md`](../app/CLAUDE.md) — app-side index (long-form until `app/docs/` fills in)

- [Desktop-to-operator setup guide](operator-setup.md) — released Desktop and public-kernel installation, with verification limits.

- [Shared written project memory](briefs/2026-09-10-shared-project-memory.md) — engine-owned project records and kernel workflows; [execution plan](execution-plans/2026-09-10-shared-project-memory.md).

- [Daily LLM budget and spend incident](briefs/2026-09-11-daily-llm-budget.md) — [implementation plan](execution-plans/2026-09-11-daily-llm-budget.md) and [engine spending contract](../engine/docs/features/daily-llm-budget.md).

- [Operator versus engine AI: models, costs and pauses](operator-setup.md#ai-execution-and-controls).

- [Desktop/kernel hardening closure](execution-plans/2026-10-07-desktop-kernel-hardening-closure.md) — local contract/gate evidence, historical dispositions and explicit remaining owners; [brief](briefs/2026-10-07-desktop-kernel-hardening-closure.md).
- [RPC call inventory](rpc-contract-inventory.json) — generated names, payload keys and declared types; limits and verification in [IPC contract](ipc-contract.md#parameter-contract--what-the-dispatcher-refuses).

- [Company task assignments](../engine/docs/features/task-assignment.md) — local implementation and approval/source boundaries; [brief](briefs/2026-10-08-explicit-task-assignment.md) and [delivery plan](execution-plans/2026-10-08-explicit-task-assignment.md).
- [Human thread-assignment gaps](../engine/docs/features/human-thread-ownership-gaps.md) — original requirements and selected mechanism; current verification status belongs to the delivery plan.

- [Contextual email assignment enforcement](execution-plans/2026-10-08-contextual-email-assignment-guard.md) — local unreleased guard, exact caller binding and verification; [brief](briefs/2026-10-08-contextual-email-assignment-guard.md).

- [MrCall company sharing](execution-plans/2026-10-08-mrcall-company-memory-sharing.md) — authorized fenced join, authenticated shared reads and private-data preservation; [brief](briefs/2026-10-08-mrcall-company-memory-sharing.md).
