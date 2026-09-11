# Predictable AI spending and economical mailbox processing

## Product goal

An operator connects a mailbox, sees how much AI may spend today, chooses a
clear cost/quality preset, and processes new mail or a historical backlog in
bounded batches. Spending stops before authorization is exhausted. Progress
survives failures and restarts, and the operator can pause/resume deliberately.
The engine keeps semantic decisions with LLMs. Codex/Claude subscriptions remain
separate. The CTO prioritizes preventing charges over availability and requests
brief, plan, implementation and independent reviews between phases.

## Existing foundation

Build on the reviewed daily-budget branch and repaired memory candidate and
checkpoint behavior. Current affected engines are reachable but automatic work
is paused. Three use direct Anthropic keys; production uses credits and paid AI
is refused until a bounded debit contract exists. Preserve incident backups and
restored pending messages. Do not re-enable automatic work or make paid calls
as a side effect of developing/testing this improvement.

## Required outcomes

1. **One understandable allowance.** Saved per-account daily USD limits govern
   every engine LLM path, with durable reservations, fail-closed accounting,
   explicit UTC reset and no hidden provider retries. Preserve existing USD5
   limits; zero pauses AI. Disclose engine/account scope, estimated versus
   settled debit and ambiguous holds. Never silently route around a refusal.
2. **Credits actually bounded.** Implement an authoritative, versioned proxy
   pricing/debit contract including markup and credit rounding. The server
   must honor a client maximum debit and refuse invalid/stale/unsupported
   requests before upstream dispatch. Replays cannot repeat paid work or debit.
   Return a verifiable final charge; incomplete/unknown outcomes retain client
   liability. Existing clients receive compatible behavior or explicit upgrade
   guidance; never disable working billing silently. No changes to unrelated
   configurator, phone or SMS business behavior.
3. **Intentional model selection.** Add OpenRouter to the engine through a
   maintained wire adapter and explicit profile credentials/provider selection.
   Central admission covers it too, with a checked price catalog and refusal
   on unknown pricing. Economy/balanced/custom presets map explicit models per
   work role and show the effective provider/model; no hidden expensive fallback.
   New configurations should not inherit the most expensive model by default.
   Preserve existing explicit settings until intentionally changed. Prior GLM
   classifier evidence does not establish memory quality: deliver reproducible
   task-specific evaluation and label unmeasured quality honestly.
4. **Backlogs are bounded work.** Pause/resume, per-run item limits and clear
   pending/completed/failed progress; failed or uncertain work is never complete.
   Retain shared-company membership and selective evidence access. Improve the
   actual high-cost paths, not semantic regex rules. Repeated errors must not
   turn the backlog into a paid retry loop. No automatic destructive data cleanup.
5. **Usable operations.** Desktop settings/setup and RPC expose daily spending,
   reservations, active models, preparation progress and actionable stop reasons.
   Read-only access and mail synchronization remain separate from paid AI.
   Shared memory, auth and existing operator commands continue to work.

## Scope limits and acceptance

Budget enforcement covers engine-controlled requests and the new proxy contract,
not unrelated applications or copied profile stores using the same API key.
Supported request features must have demonstrated bounds: standard text/function
calls first; native server tools/multimodal may remain explicitly unsupported
when their prices cannot be bounded. No promise of exact bank charges/taxes.
No replacement of semantic classification with regex or cheap guesswork.

Use independent reviews for brief, plan, each integration milestone and a final
user-path review. Test actual adapters/dispatch with fake upstreams and real
local stores, concurrency/process crashes, replay, cancelled/partial streams,
pricing changes, stale settings, provider switches and resume checkpoints.
Server credit mutation tests must use fake credit stores, never customer debits.
No paid benchmark or live customer processing is required to claim protocol
correctness; keep any unmeasured semantic-quality qualification explicit.

Complete source, tests, docs and reviewable PRs; deploy compatible reviewed
services and validate read-only health. Retain the CTO's current automatic-work
pause. A new packaged release follows compatibility and release gates; never
claim a source-only UI is already installed on the CTO's Mac.
