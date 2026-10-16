# M10 runtime preservation source evidence

This candidate composes the installed runtime protections with the approved M10
implementation. This is source preservation and isolated local acceptance. It
establishes no installed GUI acceptance, provider fit, deployment readiness or
permission to switch services. No live profile settings, credentials, memory
records, sends, drafts, services or migrations were changed or read for this work.

## Source identity and frozen evidence

The private evidence root is
`/tmp/mrcall-ai-kit/m10-memory-readiness-20261015/m10_runtime_integration/`.
`frozen-production-manifest.json` identifies every installed Python source and its
SHA256. All **348 modules** were copied from the actual installed package and
verified against the original runtime inventory before integration. The original
inventory records 257 modules identical to M10, 75 differing and 16 absent.
`frozen-production/` retains the exact bytes; candidate formatting is independent
of this source receipt. `production-startup-current.txt` retains the selected
systemd identity fields and confirms the original PID and command still run.
Its command includes both `--voice-config` and `--operator-config`.

`frozen-mario-manifest.json` separately captures Mario's actual active unit,
selected process PYTHONPATH and **334 Python modules** in that source overlay.
`frozen-mario/` retains those bytes; `mario-process-source.json` records the
selected live process executable, argv and only its PYTHONPATH source field. His command uses the ordinary Unix WebSocket
listener without a voice or operator configuration flag. Of those modules, 326
match production and eight differ: `cli/main.py`, `email/imap_client.py`,
`rpc/methods.py`, `rpc/server_ws.py`, `rpc/setup.py`,
`services/process_pipeline.py`, `storage/storage.py`, and `tools/gmail_tools.py`.
Those eight differences are the production MCP, exact-draft, operator-origin,
Sent-reference and email-only integrations preserved below. Production adds ten
MCP modules and four exact-draft/origin modules absent from Mario. This preserves
an optional installation surface; it does not enable it for Mario. Both profiles
already have the same bounded ancestry/evidence/Sent-index and Qonto source.
These captures identify source bytes and startup commands, not already-loaded
Python objects, bytecode, native dependencies or live operational behavior.

## Noncanonical MCP source and dependency boundary

Installed `operator_mcp/read_port.py` is SHA256
`e249e3ad0de77bfa7e829a452d09657b52af2ff8fc5ec0618cb4098722fed5ff`.
Installed `operator_mcp/server.py` is SHA256
`61e353722aa3bddfb8e128f4eae9a49c5785deeb4fe9b8166a1ebc5db509b006`.
Neither matches its nominal retained release sibling. The candidate preserves
these actual installed implementations; the exact sibling comparisons are
`noncanonical-read_port.py.diff` and `noncanonical-server.py.diff` in the private
root. No sibling was substituted. The installed additions expose partial
`customer_context`, enforce selected-source participant and profile-owner
binding, reject malformed participant headers, cap search/thread responses, and
reject boolean/non-integer limits at the actual MCP SDK tool boundary.

The listener also needs the installed `cs.operator_read` contract, including
`ReadOperator.customer_context` and `customer_address`. Its exact installed
source SHA256 is
`3ab4969b3c3d61af473d418438edd82623cdeda9356337ef342979d9ac79e911`.
`cs-read-contract.json` and `dependency-source/cs/` retain this source and its
package initializer. Distribution metadata says `cs-kernel 0.51.0`, but the
nominal local kernel source lacks this module and a retained operator worktree
has different bytes. Version metadata therefore cannot establish compatibility.
A later installation must retain this dependency contract and review its actual
source. This engine work does not publish a kernel replacement or invent a PyPI
constraint. The existing production `operator-mcp` extra is restored with
`mcp==1.30.0`, `uvicorn>=0.54,<0.55`, and `jsonschema>=4.23,<5`.

## Composed behavior

- `serve --operator-config` creates the profile listener and enters the same
  WebSocket lifecycle. A failed MCP listener retires the daemon lifecycle. The
  optional listener preserves strict grant introspection and owner/company/mailbox
  checks; its catalog contains only the five authenticated read tools.
- Exact-draft inspection, snapshot discard/preflight and independently verified
  external Sent reconciliation are registered in the actual RPC dispatcher.
  Snapshot/CAS, private transaction, read-only policy and M10 company effect
  authority remain in force. Duplicate RPC registration refuses.
- Scheduled operator origin is version-validated before service construction.
  Exact source/assignment admission occurs before the send claim. The claimed
  draft is reread, and origin handoff wraps M10's guarded send. The SMTP path
  marks only a genuine admitted automatic reply. Manual, delayed and failed
  requests do not inherit this provenance. Emitted References are persisted;
  existing incomplete Sent rows are not backfilled.
- Assignment projection retains the installed 40-second shared deadline,
  bounded memoized RFC ancestry and complete Sent inventory. Stored/live ancestry
  disagreement, unsynced manual Sent candidates and incomplete observations hold
  automatic reply. Active human assignment remains authoritative without waiting
  for closure I/O. M10's managed enrollment and contextual-email effect guards
  remain the writer authority.
- Email-only synchronization is retained in both RPC dispatch and the pipeline.
  Its single-flight reservation belongs to the worker after request cancellation;
  email-only scope does not enter WhatsApp or the AI stages. The actual wrapper
  declares optional `days_back` and `scope` parameters, so the M10 dispatcher
  rejects unknown keys before either synchronization scope enters work.
- Qonto's explicit read-only bootstrap source, status and disconnect availability
  remain until separate installed-GUI acceptance authorizes retirement. Hosted
  development override refusal remains. Bootstrap shares M10's credential value
  type/parser, so encrypted typed values and bootstrap values remain compatible.
  Existing encryption, identity, consent, private/company and publication guards
  remain. No Qonto credentials were inspected.

## Complete preservation disposition

`preservation-disposition.json` and `.tsv` enumerate all 348 modules with original
and candidate SHA256, AST parity and a reason. The 257 originally identical
modules remain unchanged. Every other module is listed below. `retain-M10`
means the approved M10 change intentionally supersedes the older installed
implementation. `M2-owned` names the separately reviewed admission integration;
this milestone did not edit those files. `preserve` allows formatting/import-only
cleanup after retaining exact original bytes; `compose` combines required
installed behavior with M10.

| Module | Disposition | Reason |
|---|---|---|
| `agents/base_agent.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `agents/emailer_agent.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `agents/task_orchestrator_agent.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `agents/trainers/base.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `agents/trainers/memory_message.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `agents/trainers/task_email.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `assistant/core.py` | retain-M10 | Retain M10 run clock, role routing and reasoning-aware transcript; installed read-only, Qonto and tool-dispatch checks remain in this source. |
| `assistant/models.py` | retain-M10 | Retain M10 per-role default resolution instead of hard-coded Opus fallback. |
| `cli/chat.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `cli/main.py` | compose | Restore installed --operator-config parsing/listener creation alongside existing voice startup. |
| `cli/profiles.py` | retain-M10 | Retain M10 profile-local model-table distribution and cached/build fallback. |
| `cli/tenant_commands.py` | retain-M10 | Retain M10 offboarding across both actual account identities and stand-in refusal; no offboarding is executed. |
| `config.py` | retain-M10 | Retain M10 nullable explicit model fields; profile values remain owned by saved settings. |
| `email/imap_client.py` | compose | Compose installed deadline/DNS/header inventory and genuine automatic-reply marking with M10 contextual transport guards. |
| `llm/__init__.py` | retain-M10 | Retain M10 role resolver and credential-only llm_available probe. |
| `llm/bounded_proxy.py` | retain-M10 | Retain M10 bounded-v2 snapshot/receipt protocol and reasoning blocks; server-first gate remains external. |
| `llm/budget_pricing.py` | M2-owned | Retain M10 role/pricing/reasoning transport; only reviewed M2 context-admission repair supersedes it. M1 does not edit this file. |
| `llm/client.py` | retain-M10 | Retain M10 request shape, clock, free preflight and conservative hold release behavior. |
| `llm/k3_reasoning.py` | M2-owned | Retain M10 role/pricing/reasoning transport; only reviewed M2 context-admission repair supersedes it. M1 does not edit this file. |
| `llm/model_policy.py` | retain-M10 | Retain M10 table/served-set role resolution, explicit overrides, pauses and policy fingerprint. |
| `llm/openrouter_client.py` | M2-owned | Retain M10 role/pricing/reasoning transport; only reviewed M2 context-admission repair supersedes it. M1 does not edit this file. |
| `llm/openrouter_pricing.py` | M2-owned | Retain M10 role/pricing/reasoning transport; only reviewed M2 context-admission repair supersedes it. M1 does not edit this file. |
| `llm/sdk_request.py` | retain-M10 | Retain M10 sampling removal and direct adaptive-reasoning binding. |
| `llm/usage.py` | retain-M10 | Retain M10 exact snapshot pricing rather than model-family substring rates. |
| `memory/config.py` | retain-M10 | Retain M10 removal of unused hard-coded merge-model field; actual roles use saved overrides/table. |
| `memory/consolidation.py` | retain-M10 | Retain M10 credential-only availability probe; no live consolidation is performed. |
| `memory/join_import.py` | retain-M10 | Retain M10 assignment enrollment digest/merge receipt; no migration/import is executed. |
| `memory/mnemonic/agent.py` | retain-M10 | Retain M10 separate MNEMONIC role instead of reusing MEMORY_EXTRACT. |
| `memory/offboard.py` | retain-M10 | Retain M10 two-identity offboarding safeguards; no offboarding is executed. |
| `memory/store.py` | retain-M10 | Retain M10 assignment enrollment install hooks; tests use disposable stores only. |
| `operator_mcp/__init__.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/__main__.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/auth.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/broker_store.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/grant_api.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/issuer.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/policy.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/read_port.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/runtime.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `operator_mcp/server.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `qonto/bootstrap.py` | compose | Preserve explicit read-only bootstrap file boundary; reuse M10 Credentials/parser for one compatible value type. |
| `qonto/challenges.py` | compose | Preserve installed bootstrap credential import; bootstrap reuses M10 value type/parser. |
| `qonto/connection.py` | compose | Preserve explicit installed bootstrap test/connect and safe status/disconnect availability. |
| `qonto/errors.py` | compose | Preserve installed content-free bootstrap error outcomes. |
| `qonto/provider.py` | compose | Preserve installed bootstrap credential import without provider/network changes. |
| `qonto/secrets.py` | compose | Preserve installed bootstrap credential import and existing private encryption checks. |
| `router/intent_classifier.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `rpc/agents.py` | retain-M10 | Retain M10 credential-only training availability probe. |
| `rpc/exact_drafts.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `rpc/methods.py` | compose | Compose installed scheduled-origin validation/admission/scope/capability and exact-draft RPC registry with M10 contextual-email, role and read-only paths; duplicate registration refuses. |
| `rpc/qonto.py` | compose | Preserve installed bootstrap-aware status/disconnect API descriptions. |
| `rpc/server_ws.py` | compose | Restore installed shared lifecycle and fail-closed operator-listener supervision. |
| `rpc/setup.py` | compose | Preserve installed email-only scope, history validation and worker-owned cancellation; declare wrapper parameters to enforce M10 unknown-key rejection in real dispatch. |
| `rpc/usage_queries.py` | retain-M10 | Retain M10 dynamic role/model catalogue, served-set thread isolation and saved choices. |
| `services/chat_compaction.py` | retain-M10 | Retain M10 COMPACTION role and reasoning removal after transcript rewrite; Qonto authorization remains. |
| `services/chat_service.py` | retain-M10 | Retain M10 contextual-email scope and credential-only availability probe; request policy remains composed by RPC. |
| `services/command_handlers.py` | retain-M10 | Retain M10 contextual-email guarded send paths and credential-only probes. |
| `services/correction_learning.py` | retain-M10 | Retain M10 auto tool choice and CORRECTION_LEARNING routing. |
| `services/error_messages.py` | retain-M10 | Retain M10 explicit per-role paused status and remedy. |
| `services/exact_draft_delivery.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `services/exact_draft_transaction.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `services/job_executor.py` | retain-M10 | Retain M10 credential-only chaining probes. |
| `services/operator_reply_origin.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `services/process_pipeline.py` | compose | Restore installed include_whatsapp scope while retaining M10 role/preflight/pause handling. |
| `services/project_store.py` | retain-M10 | Retain M10 assignment enrollment binding to actual company space. |
| `services/settings_schema.py` | retain-M10 | Retain M10 model-table choices, suggestions and explicit pause/help surfaces. |
| `services/solve_tools.py` | retain-M10 | Retain M10 contextual guarded send and WEB_SEARCH routing. |
| `services/task_assignment_draft_policy.py` | retain-M10 | Retain M10 shared contextual-email effect guard as sole company transaction; runtime projection now supplies its stricter evidence. |
| `services/task_assignment_evidence.py` | compose | Preserve installed shared provider deadlines and stored/live ancestry equality. |
| `services/task_assignment_mail.py` | compose | Preserve installed bounded memoized exact RFC graph and immutable-header projection. |
| `services/task_assignment_projection.py` | compose | Preserve installed active-assignment authority and complete Sent discovery under one deadline. |
| `services/task_assignment_sent_index.py` | preserve | Add actual frozen installed source, with formatting/import-only cleanup as needed. |
| `services/task_assignment_store.py` | retain-M10 | Retain M10 managed-enrollment admission before assignment writes. |
| `services/task_assignment_trust.py` | retain-M10 | Retain M10 strict missing-only probe and shared parser; protected-file checks remain. |
| `services/task_executor.py` | retain-M10 | Retain M10 contextual source scope, stable run clock and reasoning replay through complete run. |
| `services/task_interactive.py` | retain-M10 | Retain M10 TASK_SOLVE routing and authoritative email task binding. |
| `storage/assigned_task_models.py` | retain-M10 | Retain M10 enrollment model alongside existing assignment models. |
| `storage/database.py` | retain-M10 | Retain M10 enrollment company-table ownership and private draft reply_binding install column. |
| `storage/models.py` | retain-M10 | Retain M10 private draft contextual reply_binding. |
| `storage/storage.py` | compose | Restore emitted References persistence; retain M10 draft transaction/effect guards and fresh-claim fast refusal. |
| `tools/calendar_sync.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `tools/config.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `tools/email_sync.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `tools/gmail_tools.py` | compose | Compose installed origin admission/claimed-draft reread/handoff and References mirror with M10 guarded send and approval-card transaction. |
| `tools/web_search.py` | retain-M10 | Retain M10 explicit role routing/common request shape and contextual guards; installed version has no unique preservation repair. |
| `utils/reply_need.py` | retain-M10 | Retain M10 auto tool choice and common sampling-free request shape. |
| `workers/task_creation.py` | retain-M10 | Retain M10 auto tool selection/common request shape; installed version has no unique preservation repair. |
| `workers/task_dedup_sweep.py` | retain-M10 | Retain M10 auto tool selection/common request shape; installed version has no unique preservation repair. |
| `workers/task_prompt.py` | retain-M10 | Retain M10 named task_decision instruction for non-forced tool selection. |
| `workers/task_reanalyze.py` | retain-M10 | Retain M10 auto tool choice and explicit reanalyze_decision instruction; no installed ancestry repair is in this file. |
| `workers/task_topic_dedup.py` | retain-M10 | Retain M10 auto tool selection/common request shape; installed version has no unique preservation repair. |

The candidate-only `qonto/credentials.py` is absent from the installed inventory.
It retains M10's shared credential value/parser. Its module/function descriptions
now identify the actual lifecycle selector in `bootstrap.request_credentials`;
its narrower typed-only parser still reads no file. This docstring alignment
changes no member of the 257 originally identical installed modules.

## Local verification and limits

The current M1 revision repairs the restored installed wrapper's missing RPC
parameter declaration. Without it, the dispatcher classified `sync.run` as open
and silently accepted unknown keys. The wrapper now declares exactly optional
`days_back` and `scope='all'`; scope validation, worker ownership and cancellation
behavior are unchanged. The focused tests reject a misspelled key through real
JSON-RPC dispatch in both scopes before work, while the registry contract suite
checks every registered method. Current receipts are under `r2/` in the private
root. The previous approved report, wheel and receipts remain retained; copies
of the prior disposition and 49-artifact manifest are under `r2/prior/`.

| Current revision check | Actual receipt |
|---|---|
| Registry contracts and email-only behavior | `r2/focused.log`: **36 passed, 26 warnings in 5.97s** using `bash r2/check.sh`; 26 registry cases plus 10 email-only cases. |
| Frozen/current source, enforced sync parameters and wheel parity | `r2/source-smoke.log`: **PASS** for 348 production + 334 Mario frozen hashes, all 348 current source hashes, 91 dispositions, 257 unchanged modules, 10 MCP AST matches/imports, actual optional sync parameter registry and 348 wheel source byte matches. |
| Two touched Python files | `r2/ruff.log`: **All checks passed!** `r2/black.log`: **2 files would be left unchanged.** Scoped whitespace check passes in `r2/whitespace.log`. |
| Revised scratch wheel | `r2/wheel-build.log`: built `r2/wheels/zylch-0.1.52-py3-none-any.whl`; SHA256 `c4b208fb408fb65f92f889c0caeb1670ab39e5bb0342e2a678de7647adafcc71`. |

The following receipts describe the prior approved source checkpoint. The
416-case sensitive suite was not repeated for this wrapper declaration and
focused assertion revision; the current 36-case run covers the affected boundary.

| Check | Actual receipt |
|---|---|
| Added exact/origin/ancestry/Sent, Qonto secret/bootstrap, email-only/deadline regressions | `added-regressions-final.log`: **144 passed, 474 warnings in 95.06s**. |
| Actual MCP SDK contracts and isolated CLI/listener startup | `mcp-startup-final.log`: **26 passed, 13 warnings in 2.26s**. |
| Focused sensitive integration suite | `sensitive-final.log`: **416 passed, 1018 warnings in 314.65s**. Exact command is `bash check-sensitive.sh` under the private evidence root. |
| Frozen/current source, RPC/help imports and wheel source parity | `source-smoke.log`: **PASS** for 348 production + 334 Mario frozen hashes, 91 dispositions, 257 unchanged modules, 10 MCP AST matches/imports and all 348 installed paths in the wheel. |
| Touched Python lint | `ruff-final.log`: **All checks passed!** `black-final.log`: **47 files would be left unchanged.** |
| Scratch wheel build | `wheel-build.log`: built `zylch-0.1.52-py3-none-any.whl`; SHA256 `9974b4fcc489ef8c83dd24116ad4227c59af6e6c075d8b24fbe80a63dea13713`. |

The optional warning helper was checked against the existing completion task
`m10-memory-readiness-20261015`. `r2/verification-warnings.log` reports missing
focused/mechanical completion receipts, which the parent closure owns. No native
runtime binding was attempted because no actual session identifier was available.

The default interpreter is the existing local engine venv. HOME, ZYLCH_HOME,
ZYLCH_DB_PATH and candidate PYTHONPATH are isolated before imports. MCP checks use
only a scratch venv with the declared SDK dependencies, existing engine package
paths and the exact frozen installed `cs.operator_read` source. The shared venv
was not modified. The bootstrap tests read only fixture credentials in disposable
files. SMTP, IMAP and introspection use in-process fixtures; the startup test
opens only private temporary Unix sockets. Its protected configuration/tenant
lookup is supplied by fixtures, so it is not an attestation of production
configuration permissions, real Firebase introspection or installed tenancy.

The new checks cover missing RPC registration, stale/full-row snapshots,
read-only mutation refusal, ancestry conflicts and expired deadlines, unsynced
complete Sent discovery, provenance/assignment holds, email-only worker
cancellation, explicit bootstrap/override refusal and secret confinement. MCP
checks exercise actual SDK catalog/argument validation, per-request
introspection, participant/owner/mailbox/PEC boundaries, partial evidence and
response bounds. Isolated real CLI startup proves argument parsing, both Unix
listener lifecycles, unauthenticated HTTP/WebSocket refusal and cleanup.

The whole-tree lint baseline already has unrelated failures; only touched-file
lint is this milestone's gate. Formatting was confined to files changed here.
The previously failing source-inspection run overlapped normalization and is
retained as diagnostic evidence, not final acceptance. The prior stable-source focused
receipts remain historical evidence; the revision receipts above verify the
current wrapper and wheel. Required live two-profile operational
acceptance, actual dependency installation, protected-config permissions,
provider transport/factual-quality acceptance and the separate Qonto GUI gate
remain pending. No frontend or app packaging/IPC bridge source was changed. Engine RPC
additions and synchronization parameters are part of this preservation work.
