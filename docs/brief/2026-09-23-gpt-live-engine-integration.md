---
status: draft
date: 2026-09-23
---

# GPT-Live: a telephone channel for customer service

<!-- doc-scope:start -->
Scope: product brief for a customer-service voice agent using GPT-Live, Python,
Vonage and the existing engine. Defines the first memory-backed conversation,
operator configuration and the direction for repeatable service integrations.
M1–M3 are approved for the isolated prototype.
M4 is active with a revised Live-context design; acceptance requires new
correlated traces and listening. Older GPT-6 design entries are historical.
<!-- doc-scope:end -->

Execution: [four-milestone plan](../execution-plans/2026-09-23-gpt-live-engine-integration.md).

## Objective

Add telephone conversations to customer service alongside email and WhatsApp.
The voice agent serves the company's customers using selected company memory
and permitted engine tools. **cs-operator configures this agent; it does
not conduct the calls.** Calls must work while cs-operator is stopped.

Start with incoming calls. Later, outgoing calls use the same agent and
configuration, with a destination and purpose supplied when initiating the call.
Python, Vonage and GPT-Live are the starting stack. Full duplex is required:
customers can speak while the assistant speaks or backend work proceeds.

The first useful delivery needs only company memory. External services and the
meta-skill for creating their integrations follow; Google Calendar is a candidate,
not a prerequisite for the telephone channel.

## Historical M3 model and test correction — 2026-09-24

The isolated M3 telephone prototype used `gpt-live-1` with a direct
`gpt-6-sol` Responses/function-calling backend under the dedicated test
key/project. The unactivated GPT-4.1 draft sent no inference. Integrated phone
demonstration and independent M3 review were approved, but their evidence does
not accept M4 or keep GPT-6 in the replacement path. The operator removed all
local experiment ceilings in the isolated profile; ledger holds, usage
accounting, profile isolation and indefinite service/tunnel lifetime remain
required. The approved test history uses blue replacement filters and the
prior-email Thursday agreement.

## Superseded M4 telephone backend direction — 2026-09-24

The prior isolated telephone path delegated substantive questions and tool
selection to GPT-6. Its reviewed M3 integration and subsequent M4 calls remain
historical evidence; they are not an M4 implementation option. The call traces
showed waiting even when selected facts were already loaded, and the operator
replaced that design with the Live-context direction below. The earlier wording
and detailed test history remain available in Git and the execution evidence.

## Current M4 direction: one conversational model — 2026-09-25

The preceding GPT-6 answer-ownership correction is superseded for M4. The
telephone runtime must remove that mandatory GPT-6 path rather than retain it as
an option or fallback. The engine selects permitted information and capabilities;
GPT-Live uses that context for ordinary phone conversation. No demonstrated
telephone task requires a separate GPT-6 turn. Its across-the-board delegation
caused waiting even for facts already retrieved. Previous milestone approvals and
failed M4 traces remain historical evidence, not acceptance of this replacement.

At session creation, provide Live with instructions for the greeting, tone,
delegation, historical-versus-current language and one response per caller
request. Greet before caller recognition completes. The engine concurrently
selects authorized caller/company facts and sends them as quiet `thinking` when
ready; a phone-number match alone never proves identity. Reuse validated StarChat
opening-hours/state inputs where applicable, computing time-sensitive “open
now” with a fresh clock, timezone and exceptions. Live answers directly from
current permitted facts and conversation without a second model call.

When a caller asks before initial context arrives, Live may delegate. The engine
joins its existing lookup, sends the selected baseline through `thinking` for
subsequent turns and supplies a task-bound `commentary` result for the pending
question. When fresh information is needed, such as the time in Rome, Live
delegates and the engine invokes the specific enabled function directly, then
returns a speakable `commentary` result. Missing capability or data is stated
as unavailable; no order/tracking check is invented. The engine's data selection
and tool permissions remain code-enforced. `thinking` and `commentary` are
different session updates, and a received append acknowledgement is not proof
of what the caller heard.

Start with a clear instruction not to repeat an answer already given. Do not
pre-build a special duplicate-suppression controller for a hypothetical race;
inspect correlated speech and delegation traces, then fix any repetition actually
observed. Preserve real interruption, correction, unknown-caller, failure,
closure, cost and human listening requirements. The [revised M4 execution
plan](../execution-plans/2026-09-23-gpt-live-engine-integration.md#current-m4-plan--live-uses-selected-context-engine-supplies-new-results)
owns the delivery sequence and acceptance matrix. Official basis checked
2026-09-25: [Live context](https://developers.openai.com/api/docs/guides/live-conversations),
[client delegation](https://developers.openai.com/api/docs/guides/live-delegation),
[prompting](https://developers.openai.com/api/docs/guides/live-prompting).

### Autonomous phone tests authorized — 2026-09-24

The operator must leave and explicitly requests autonomous test calls. Use a
standalone diagnostic caller to dial ONLY the already-authorized test number,
with that same owned number as caller ID; never impersonate the frozen customer
or call the operator's personal number. Vonage NCCO text-to-speech and waits
exercise the real incoming carrier/audio path. This is a test driver, not a
production outbound feature. Keep a private durable attempt/receipt ledger before
origination, retain uncertain reservations, do not automatically retry an
uncertain create, and collect actual provider closure/price evidence. The existing
incoming ledger is unchanged. No recordings, routing changes or tunnel restart.
A scripted test has finite dialogue steps and hangs up when done; it adds no
runtime expiry or general conversation ceiling. Calls from this test number may
correctly be unidentified; label identity scenarios honestly. Pair the incoming
correlated transcript with the exact scripted caller text and observed tool
results. These calls can prove provider paths and failures, but cannot stand in
for human handset listening or certify known-caller recognition when unidentified.

## First experience: recognize the caller and use company memory

A customer calls. The agent greets them while the engine looks up their phone
number in company memory. Relevant facts from previous email or WhatsApp exchanges
arrive during the conversation, letting the agent continue an existing discussion
without making the customer repeat everything.

The customer says, “I'm calling about my earlier request.” The engine has
already started selecting relevant memory at call establishment. If that context
is ready, Live answers from it; otherwise the delegated request joins the
lookup in progress. While it works, the customer clarifies which request they
mean. The agent answers the corrected question using the selected facts. If
memory lacks an answer, it acknowledges the gap and asks what it needs.
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
| GPT-Live | Greet, listen, interrupt, answer from selected facts and conversation, delegate missing/fresh work and present engine results. |
| Engine | Select permitted facts and available functions, execute enabled tools, return new results and maintain storage/accounting. |
| Python call adapter | Connect Vonage and GPT-Live, maintain per-call context and schedule delegated work. |

Use GPT-Live client delegation to connect the engine. The adapter retains the
transcript, caller context and pending work: delegation events identify work but
do not contain the complete request. The engine correlates transcripts with
delegations, executes a concrete supported function when needed and returns
the result to Live. The revised telephone path does not require another LLM.

Keep listening while the asynchronous caller lookup or a delegated function
runs. If new customer input arrives, let the engine reconcile it with the
pending result before returning an answer for speech. It may reuse a current
result or report unavailable data. Keep one logical conversation rather than
starting independent work for every transcript fragment. Communicate useful
facts when available without inventing progress.
Check late results against current context before passing them to the voice;
if a correction concerns something already spoken, rectify it clearly.

The existing authenticated voice configuration interface lets cs-operator read
and update company/profile binding, voice instructions, caller-context policy,
enabled capabilities and the isolated profile's saved settings. Each call loads
its configuration at start; changes affect subsequent calls. Accounting and
ledger preservation are engine boundaries, separate from conversational prompts.
Credentials stay server-side.

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
3. A follow-up question uses selected context directly when sufficient; only a
   missing or fresh fact triggers a new lookup or enabled function. Answers use
   stored facts, acknowledge gaps and distinguish new caller statements from stored knowledge.
   Include an internal note and another customer's fact in the test store and
   check that neither reaches the caller's conversation.
4. Try a correction during a slow lookup and another during speech. Listen to
   the whole exchange: the answer follows the corrected request, and anything
   already spoken that needs correcting is clearly rectified.
5. Hangup and lookup failure are handled explicitly, with call
   work stopped on closure. Trace lookup, delegation, results and closure;
   record conversational continuity, response latency and test cost.

For M4, capture an opt-in private transcript of the isolated test, correlated
with selected-memory retrieval, engine/tool results and voice delivery/interruptions.
This is required diagnostic evidence after the caller reported possible failure
to recall the blue filters despite a successful lookup. Verify actual use of the
facts in the answer; retrieval counts alone do not pass conversational acceptance.
Keep credentials and unselected facts out of the trace, retain real listening
checks, and keep raw audio retention off by default. Capture must be enabled only in the explicit isolated profile, stored in a private
SQLite diagnostic file outside Git, and off for ordinary profiles. Record the
provider's playback offsets separately from local receipt timestamps: generated
voice text is not proof of handset delivery. Never persist hidden thinking,
provider payloads or raw audio. Diagnostic failure must be visible in sanitized
call evidence and must not obstruct hangup or accounting.

The current operator request authorizes M4 implementation, necessary isolated
restarts, unrestricted local retests and an independent final review. Preserve
the existing tunnel, frozen fixture and every ledger reservation. Use reversible,
explicit isolated test controls for delayed/failed lookup; simulated identity
scenarios must be labeled as simulations, never as real caller recognition.
Do not claim the earlier repetition's cause without new reproducible evidence.

Verify one audio transport first: prefer direct Vonage-to-OpenAI SIP if project
access and compatibility are confirmed; otherwise use a Python audio bridge.
There is no need to implement both. Electron need not carry audio or remain open.

Preserve Firebase UID profile boundaries, in-memory-only Firebase ID tokens and
company-memory scope. Never log or disclose MEMORY_KEY. Expose only the call's
configured capabilities. Start with read-only memory; subsequent writes must use
the engine's existing memory policy and write paths. Preserve usage accounting
for voice, engine and carrier charges separately; existing engine budgets do not
cover all three. Record incomplete usage as such without restoring local
experiment limits.

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
M3 memory-backed integration also passes its demonstration and independent review.
M4 is in progress; its listening scenario matrix remains unverified. See the execution plan.

Existing engine boundaries:
[company memory](../../engine/docs/features/entity-memory-system.md),
[chat entry point](../../engine/zylch/services/chat_service.py),
[operator configuration and execution boundaries](../operator-setup.md#ai-execution-and-controls),
[outbound calling](../../engine/docs/features/outbound-calls.md) and
[spending controls](../../engine/docs/features/daily-llm-budget.md).
The current chat entry point returns a final answer; per-call adaptation is new
work, and richer progress events are optional for this first delivery.


## Historical waiting-steering result — 2026-09-25

Carrier tests did not validate the attempted prompt-only and early-delegation
silent-wait steering. The changes were withdrawn, and the GPT-6 telephone
implementation was restored only as the historical checkpoint before the M4
redesign above. Traces of repeated fresh-clock reads and waiting phrases remain
failure evidence, not a requirement to keep that backend or a reason to impose
artificial local limits. The replacement design starts with direct answers from
selected context and uses new correlated traces to diagnose actual repetition.
