# Engine model routing and spend enforcement audit

Date: 2026-09-11. Scope: read-only source/history audit of the daily-budget
worktree before implementation, plus the companion cs-kernel routing code.
No paid inference, credentials, customer documents, or sessions were read.
Concurrent budget changes may supersede the defects described below.

## Findings

The engine does not select OpenRouter or GLM today. This is an explicit
architectural limitation, not evidence that those models failed engine tasks.
Commit `85c1836` collapsed a partially dead Anthropic/OpenAI/MrCall abstraction
into one model provider and two billing transports. Its commit message states
that OpenAI had no live callers and that MrCall was a transport, not a provider.
Current `zylch/llm/client.py:make_llm_client` chooses a profile Anthropic key or
the Firebase-backed proxy. `SYSTEM_LLM_PROVIDER` no longer selects anything.

The kernel is further ahead. `cs/llm_client.py` builds Anthropic-wire clients
with provider-specific authentication; `cs/model_config.py` and
`cs/model_catalog.py` resolve providers, role overrides, model families and
prices. These do not automatically alter the engine selected through RPC.
Its `ROLE_FAMILIES` assigns the classifier role to `@glm` on OpenRouter.

The kernel source records a July 28 campaign classifier evaluation on 61
replies: GLM 5.2 matched the engine on jointly completed items (56/58), completed
61/61 versus the engine's 58, and had 3.1s versus 33s median latency at a measured
$1.17 per thousand calls. These are historical recorded results, not a new
independent reproduction. The underlying customer-bearing benchmark was not
opened. They support evaluating GLM for engine classification, not assuming
that memory extraction, merging, task closure and drafting are equivalent tasks.

## Dispatch inventory and enforcement points

| Path | Dispatch and exposure |
|---|---|
| `zylch/llm/client.py:create_message_sync` | Main synchronous dispatch to `self._client.messages.create`; records usage only after success. No pre-dispatch daily cap at audit start. |
| `zylch/llm/client.py:create_message` | Async executor wrapper over the same method, preserving contextvars. One central reservation hook covers both entry points. |
| `zylch/llm/client.py:LLMClient.__init__` | Direct Anthropic SDK has `max_retries=5`, `timeout=120.0`: up to six attempts hidden below the current meter. |
| `zylch/llm/proxy_client.py:_do_create` | One synchronous HTTP stream to MrCall proxy. `_build_body` forces SSE; `_accumulate_events` reconstructs the final response. No client retry loop here. Upstream proxy retries are outside this audit. |
| `zylch/services/chat_compaction.py:_summarize` | Direct `anthropic.AsyncAnthropic()` and `messages.create`, bypassing transport choice and metering. Ambient credential resolution is possible. Called by `chat_service.py` through `compact_if_needed`. Must use the unified client. |
| `zylch/tools/web_search.py:WebSearchTool.execute` | Unified client plus Anthropic server-side search; already bounded to `max_uses=3`. Token-only meter omits search fees and provider-generated input can exceed the original prompt. |

The source-wide SDK search found no other direct billable model SDK bypass in
`engine/zylch`. Embeddings use local fastembed/ONNX rather than a paid embeddings
API. Telephony and other non-LLM channel billing are outside this inventory.

Unified-client callers include:

- Memory extraction in `workers/memory.py`; merge/canary/reconsolidation in
  `memory/llm_merge.py`.
- Task creation, reanalysis, thread dedup and topic dedup in
  `workers/task_creation.py`, `task_reanalyze.py`, `task_dedup_sweep.py`, and
  `task_topic_dedup.py`; reply adjudication in `utils/reply_need.py`.
- Agent generation and trainers in `agents/base_agent.py`, `emailer_agent.py`,
  `task_orchestrator_agent.py`, and `agents/trainers/`.
- Chat dispatch in `assistant/core.py`, task execution in
  `services/task_executor.py`, correction learning in
  `services/correction_learning.py`, and solve summarization in
  `services/solve_tools.py`.
- Intent classification in `router/intent_classifier.py`, legacy email-sync
  classification in `tools/email_sync.py`, and the pipeline health probe in
  `services/process_pipeline.py`.

## Existing guards and holes

`services/process_pipeline.py` checks `budget_state(owner_id)` once before the
background pipeline. Its comment explicitly exempts interactive chat and task
solve. A large background run can exceed the cap after admission. Independent
concurrent calls are not reserved against a shared remaining balance.

`llm/usage.py` meters successful responses only. `record` swallows write
failures; `spent_today_usd` returns zero on database failure. Therefore the
existing cap is neither universal nor fail-closed. An interrupted stream or
SDK timeout may have incurred charges without producing a usage record.

The estimator matches model names by substring, assumes a five-minute cache
write, and drops non-token provider usage. The claim that an unknown model
priced as Opus cannot undercount is false: models, older Opus versions and
premium request modes can cost more. Reject unsupported billing shapes for
hard admission control or price them explicitly; do not silently invent a rate.
Provider cost and customer MrCall credit debit/markup are distinct quantities.

Chat `assistant/core.py` loops while `stop_reason == "tool_use"` without a
step ceiling. It does enforce a prompt-size check before every model dispatch,
but that limits context, not cumulative money. Task execution defaults to ten
turns. Memory CAS conflicts can repeat model merge calls (`workers/memory.py`);
those retries must each pass the same money gate. The compaction threshold also
needs alignment with the actual route's context and the chat prompt ceiling.

## Implementation priorities

1. Reserve money atomically immediately before each unified-client dispatch,
   keyed by owner and UTC day in the profile store. Admission must include
   settled usage and outstanding reservations. Database or pricing failures
   must stop billable dispatch. Reconcile successful usage against reservations;
   retain conservative liability for ambiguous failures instead of refunding
   a potentially billed request. Do not hold the database lock across the API.
2. Route compaction through the client. Disable hidden SDK retries or implement
   explicit individually admitted attempts. Cover both direct and proxy modes,
   sync and async callers, cancellation, restart recovery, UTC rollover, and
   concurrent processes. A per-profile cap is not a shared-key/company cap.
3. Account for search fees and provider-generated input. Bound paid server
   tools, cache TTLs, model-specific prices and premium modes explicitly.
   A rough character-to-token estimate is not a formal maximum invoice bound;
   the UI must state what the budget actually guarantees.
4. Apply a per-turn call ceiling and show a persistent budget pause with the
   amount, reset time and resumable work. Pending classification stays pending;
   a blocked or failed model call must not become an invented semantic label.
5. Preserve existing event gating, selective retrieval and cache prefixes.
   Attribute cost by worker and count calls, input/output/cache tokens and
   retries so a change can be assessed per completed useful task.
6. Introduce provider selection independently from billing transport. Reuse the
   kernel's Anthropic-wire auth/base-URL and response-normalization lessons.
   Expose only supported model/role combinations. For credits, routing and
   pricing must also be implemented in the server-side MrCall gateway; setting
   an engine model string alone cannot provide that capability.
7. Evaluate cheaper models on frozen representative extraction, merge,
   classification and task-judgement fixtures. Keep actual LLM semantic
   decisions throughout; no regex or keyword replacement for labels. Compare
   correctness, valid structured outputs, latency and total cost including
   reasoning/retries. Promote only roles that pass; do not silently escalate
   to an unbudgeted expensive fallback.

## Current pricing evidence

Checked 2026-09-11; USD per million input/output tokens, excluding additional
features. These are rate snapshots, not measured engine costs.

| Model | Input / output | Primary source |
|---|---|---|
| Claude Sonnet 4.5, current proxy default | $3 / $15 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Claude Opus 4.6, current direct default | $5 / $25 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Claude Haiku 4.5 | $1 / $5 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Claude Sonnet 5 | $2 / $10 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| GLM 5.2 on OpenRouter | $0.966 / $3.036 | [Live model catalog](https://openrouter.ai/api/v1/models) |
| GLM 4.7 on OpenRouter | $0.40 / $1.75 | [Live model catalog](https://openrouter.ai/api/v1/models) |

The official Anthropic page also lists five-minute cache writes at 1.25 times
input, one-hour writes at twice input, and web search at $0.01 per search.
Batch processing discounts token rates by 50%; it is an option for future
asynchronous backfills, not an implemented engine transport.
[Pricing details](https://platform.claude.com/docs/en/about-claude/pricing).

OpenRouter officially exposes the Anthropic Messages API at `/api/v1/messages`.
This supports the kernel's existing approach; the engine still needs explicit
integration and compatibility tests for cache blocks, forced tools, reasoning
blocks, truncation, provider-specific usage and server-side tools.
[Messages API](https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-messages).

The live catalog was fetched without authentication and filtered to model IDs,
prices, context lengths and supported parameters. Provider endpoint prices can
vary; refreshed catalog pricing and actual returned cost must replace stale
hardcoded GLM rates. No claim is made that the cheapest token rate wins on cost
per correct completed engine task.
