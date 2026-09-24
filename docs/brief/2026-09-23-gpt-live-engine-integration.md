---
status: draft
date: 2026-09-23
---

# GPT-Live: a telephone channel for customer service

<!-- doc-scope:start -->
Scope: product brief for a customer-service voice agent using GPT-Live, Python,
Vonage and the existing engine. Defines the first memory-backed conversation,
operator configuration and the direction for repeatable service integrations.
Memory-backed delivery remains proposed; M1's transport-only live smoke is complete.
<!-- doc-scope:end -->

Execution: [four-milestone plan](../execution-plans/2026-09-23-gpt-live-engine-integration.md).

## Objective

Add telephone conversations to customer service alongside email and WhatsApp.
The voice agent serves the company's customers using the engine's reasoning,
company memory and permitted tools. **cs-operator configures this agent; it does
not conduct the calls.** Calls must work while cs-operator is stopped.

Start with incoming calls. Later, outgoing calls use the same agent and
configuration, with a destination and purpose supplied when initiating the call.
Python, Vonage and GPT-Live are the starting stack. Full duplex is required:
customers can speak while the assistant speaks or backend work proceeds.

The first useful delivery needs only company memory. External services and the
meta-skill for creating their integrations follow; Google Calendar is a candidate,
not a prerequisite for the telephone channel.

## First experience: recognize the caller and use company memory

A customer calls. The agent greets them while the engine looks up their phone
number in company memory. Relevant facts from previous email or WhatsApp exchanges
arrive during the conversation, letting the agent continue an existing discussion
without making the customer repeat everything.

The customer says, “I'm calling about my earlier request.” The engine searches
memory for the relevant details. While it works, the customer clarifies which
request they mean. The agent answers the corrected question using the retrieved
facts. If memory lacks an answer, it acknowledges the gap and asks what it needs.
Historical information is not presented as a fresh check of an external system.

Caller lookup starts when the call is established, independently of the first
conversational request. Route the called number to the configured company/profile,
normalize the caller number and search that company's identifiers. The greeting
never waits for this lookup. Late context enriches the conversation without
restarting it or forcing an announcement.

Withheld, unknown or ambiguous numbers leave the caller unidentified. Ask for
clarification instead of selecting an arbitrary match. A number match helps
recognition; private information and operations still follow the configured
customer-service verification and permission rules.

The existing memory scope separates companies, not caller permissions. The new
customer-service entry uses its own instructions and read-only memory tools,
without inheriting the owner's full chat context and commands. For this prototype,
explicitly select the controlled facts suitable for the caller; internal notes
and unrelated customer facts stay in the backend. A general permission system
is outside this first delivery.

## Responsibilities and conversation flow

| Component | Responsibility |
|-----------|----------------|
| cs-operator | Configure the agent and enabled capabilities; create integrations through the meta-skill during setup. |
| GPT-Live | Listen, speak, clarify and communicate verified backend results. |
| Engine customer-service agent | Interpret requests and corrections, retrieve memory, apply business rules and use permitted tools. |
| Python call adapter | Connect Vonage and GPT-Live, maintain per-call context and schedule delegated work. |

Use GPT-Live client delegation to connect the engine. The adapter retains the
transcript, caller context and pending work: delegation events identify work but
do not contain the complete request. The engine interprets this accumulated
context. The adapter needs no additional general-purpose LLM.

Initially run one business request at a time per call, alongside the asynchronous
caller lookup. Keep listening while work proceeds. If new customer input arrives,
let the engine reconcile it with the pending result before returning an answer
for speech. It may reuse the result, ask a question or perform another lookup.
This avoids requiring changes to an in-flight model request. Keep one logical
conversation rather than starting an independent agent for every transcript
fragment. Communicate useful facts when available without inventing progress.
Check late results against current context before passing them to the voice;
if a correction concerns something already spoken, rectify it clearly.

Expose a small authenticated configuration interface that cs-operator can read
and update: company/profile binding, voice instructions, caller-context policy,
enabled capabilities and call limits. Each call loads its configuration at start;
changes affect subsequent calls. This interface is new work. Credentials stay
server-side and are not included in conversational prompts.

## Repeatable integrations: skills and a meta-skill

A communication skill packages a capability's usage instructions, tool inputs and
outputs, configuration and connector code where needed. The engine executes its
tools. A common result format carries facts, missing information, operation
outcomes and errors, independently of the channel that will communicate them.

The meta-skill is a creation procedure for cs-operator. It knows our tool and
channel conventions, reads the service documentation, reuses existing connectors
where possible and produces the skill plus focused checks of its behavior.
Authentication, timeouts and permissions belong in the connector/tool boundary;
instructions alone cannot implement or enforce them.

Create each service integration once. Voice presents concise speakable results;
email composes a complete reply; WhatsApp uses short conversational messages.
Shared channel handling owns these differences. For example, a calendar tool
returns available times; each channel chooses how to present them. Record any
channel-specific limitations explicitly.

Adding an account to an installed integration should require configuration.
Adding a new service may require connector code, but should follow the same
creation procedure without changes to the telephone transport. Creation and
verification happen during setup, outside live customer conversations.

Use consistent inputs and results for the initial memory tools. Build the
meta-skill with the first external integration, then prove repeatability with a
second. A new plugin framework is not needed for the first voice delivery.

## Small first delivery and acceptance

Use an isolated, continuously running engine, one company, a Vonage test number
and one active call at a time. Exercise real company-memory reads with controlled
customer history. The first delivery passes when:

1. An incoming call reaches the agent with cs-operator stopped. A configuration
   change affects the next call without editing runtime code.
2. A deliberately delayed caller lookup does not delay the greeting. Relevant
   prior context becomes usable during the call; unknown and ambiguous callers
   are handled without invented identity.
3. A follow-up question triggers another memory lookup. Answers use stored facts,
   acknowledge gaps and distinguish new caller statements from stored knowledge.
   Include an internal note and another customer's fact in the test store and
   check that neither reaches the caller's conversation.
4. Try a correction during a slow lookup and another during speech. Listen to
   the whole exchange: the answer follows the corrected request, and anything
   already spoken that needs correcting is clearly rectified.
5. Hangup, lookup failure and duration limits are handled explicitly, with call
   work stopped on closure. Trace lookup, delegation, results and closure;
   record conversational continuity, response latency and test cost.

Verify one audio transport first: prefer direct Vonage-to-OpenAI SIP if project
access and compatibility are confirmed; otherwise use a Python audio bridge.
There is no need to implement both. Electron need not carry audio or remain open.

Preserve Firebase UID profile boundaries, in-memory-only Firebase ID tokens and
company-memory scope. Never log or disclose MEMORY_KEY. Expose only the call's
configured capabilities. Start with read-only memory; subsequent writes must use
the engine's existing memory policy and write paths. Set explicit duration and
test-spend limits: voice, engine and carrier charges are separate, and existing
engine budgets do not cover all three. Record incomplete usage as such.

Outgoing support follows through provider origination into this same runtime.
The existing StarChat outbound tool does not provide that connection. External
services, mutations, concurrent calls, automatic reconnect/replay, production
number migration and a new Electron calling UI are outside the first delivery.

## References and remaining verification

OpenAI documentation checked on 2026-09-23:
[GPT-Live](https://developers.openai.com/api/docs/guides/live),
[client delegation](https://developers.openai.com/api/docs/guides/live-delegation),
[telephony and SIP](https://developers.openai.com/api/docs/guides/voice-sip).
Project access and the isolated Vonage SIP route passed M1's real-call check;
memory-backed customer-service acceptance remains pending in the execution plan.

Existing engine boundaries:
[company memory](../../engine/docs/features/entity-memory-system.md),
[chat entry point](../../engine/zylch/services/chat_service.py),
[operator configuration and execution boundaries](../operator-setup.md#ai-execution-and-controls),
[outbound calling](../../engine/docs/features/outbound-calls.md) and
[spending controls](../../engine/docs/features/daily-llm-budget.md).
The current chat entry point returns a final answer; per-call adaptation is new
work, and richer progress events are optional for this first delivery.
