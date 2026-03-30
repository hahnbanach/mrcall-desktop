"""MrCall Configurator Trainer - Generates feature-specific sub-prompts from MrCall config.

Analyzes MrCall assistant configuration to generate self-contained sub-prompts that:
1. Document available variables and their meaning
2. Describe current behavior in plain language
3. List what can/cannot be changed
4. Include raw prompt value for modification

Each sub-prompt is stored per feature per business in the agent_prompts table.

Flusso:

/agent mrcall train
    ↓
MrCallAgentTrainer.build_prompt()
    ↓
Per ogni feature: MrCallConfiguratorTrainer.build_subprompt()
    ↓
Combina tutto → UNIFIED_META_PROMPT + feature_subprompts
    ↓
Salva come "mrcall_{business_id}"

"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


# Meta-prompt for generating welcome message sub-prompts
# Uses {variables_context} placeholder for dynamically-fetched StarChat metadata
WELCOME_MESSAGE_META_PROMPT = """You are analyzing the welcome message configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure the welcome message.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

These variables are resolved at runtime during the phone call. Use `%%var%%` or `%%var=fallback%%` syntax in prompts.

{conversation_variables_context}

## UNDERSTANDING THE PROMPT STRUCTURE

The welcome message prompt has two parts:

### Part 1: Variable Declarations
Lines that define what data the assistant has access to. Format:
```
VARIABLE_NAME=%%source.path.to.value=default_value%%
```

Example:
```
FIRST_NAME=%%crm.contact.variables.FIRST_NAME=not known%%
```
This means: "FIRST_NAME comes from the CRM contact record. If not found, use 'not known'."

### Part 2: Behavioral Instructions
After the `---` separator, the prompt contains instructions for how the assistant should behave.

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these exact sections:

### SECTION 1: AVAILABLE VARIABLES
Create a markdown table listing each %%...%% variable with:
- Variable name
- The full variable reference (MUST be preserved when modifying)
- Human-readable description
- Default value

### SECTION 2: CURRENT BEHAVIOR
Describe what the assistant DOES in plain language:
- "When a new caller phones, the assistant..."
- "When a returning caller phones, the assistant..."
Be specific about greeting style, questions asked, information disclosed.

### SECTION 3: WHAT CAN BE CHANGED
List modifications users can request (with examples):
- Greeting style (formal/informal/personalized)
- Whether to use caller's name
- Recording disclosure (remove, shorten, reword)
- What information to ask for
- How to handle returning callers
- etc.

### SECTION 4: WHAT CANNOT BE CHANGED (via this feature)
- The available variables (from StarChat system)
- Voice or language (separate configuration)
- Call routing/transfer logic (different feature)
- Business hours behavior (different feature)

### SECTION 5: CURRENT PROMPT VALUE
Include the FULL raw prompt text so another LLM can modify it.
Start with: "When modifying, preserve all `%%...%%` variable references and the `---` separator."
Then include the complete prompt in a code block.

---

---

OUTPUT ONLY THE SUB-PROMPT TEXT. No explanations, no additional markdown. Just the sub-prompt itself."""


# Meta-prompt for generating booking sub-prompts
# Uses {variables_context} placeholder for dynamically-fetched StarChat metadata
BOOKING_META_PROMPT = """You are analyzing the booking configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure booking.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

These variables are resolved at runtime during the phone call. Use `%%var%%` or `%%var=fallback%%` syntax in prompts.

{conversation_variables_context}

## CRITICAL: ALL VALUES ARE STRINGS

Every MrCall variable value is a string. There are NO native booleans, numbers, or objects.
- Booleans: "true" or "false" (strings, not true/false primitives)
- Numbers: "30", "60", "24" (strings, not integers)
- JSON, e.g. BOOKING_HOURS=" {{\\""monday\\"":[\\""09:00-08:15\\""],\\""tuesday\\"":[\\""08:00-08:15\\""],\\""wednesday\\"":[\\""08:00-08:15\\""]}}" (valid JSON serialized as string with escaped quotes)

## VARIABLE RELATIONSHIPS

Each variable in the VARIABLE METADATA above may include these annotations:
- **"Depends On: VAR_X"**: This variable is only relevant when VAR_X is enabled/configured. VAR_X is the parent switch.
- **"Modifiable: No (locked by subscription plan)"**: This variable cannot be changed for the current subscription plan. Do NOT attempt to modify it. If the user asks, explain it's locked by their subscription plan.
- **"Visible: No"**: This variable is hidden from end users. Do NOT include it in the generated sub-prompt.
- **"Admin: Yes"**: This variable is for administrators only. Do NOT include it in the generated sub-prompt.

### Rules for generating the sub-prompt
1. **Exclude** variables marked `Visible: No` or `Admin: Yes` from the generated sub-prompt entirely
2. **Include** variables marked `Modifiable: No` in the sub-prompt, but clearly mark them as locked by the subscription plan
3. Show dependency chains from "Depends On" annotations so the configurator agent understands relationships
4. When enabling a parent switch (e.g., setting it to "true"), ASK the user if they also want to configure its dependent variables (they may already have values from a previous configuration)
5. When disabling a parent switch, dependent variables become inactive — no need to modify them
6. If a parent switch is LOCKED, all its dependent variables are effectively locked too

### Value Format Reference
- BOOKING_HOURS format: "{{\\"monday\\": [{{\\"09:00-17:00\\"}}], \\"tuesday\\": [...]}}"
  (Valid JSON embedded in a string with escaped quotes)
- BOOKING_EVENTS_MINUTES determines slot granularity (e.g., "30" for 30-min slots)
- BOOKING_DAYS_TO_GENERATE: how many days ahead to show (e.g., "14")
- BOOKING_SHORTEST_NOTICE: minimum hours notice (e.g., "2")

## COMMON USER INTENTS → VARIABLE MAPPINGS

Teach the configurator these patterns:

**"Enable booking"** →
  START_BOOKING_PROCESS = "true"
  BOOKING_HOURS = "{{\\"monday\\": [{{\\"09:00-17:00\\"}}], \\"tuesday\\": [{{\\"09:00-17:00\\"}}], \\"wednesday\\": [{{\\"09:00-17:00\\"}}], \\"thursday\\": [{{\\"09:00-17:00\\"}}], \\"friday\\": [{{\\"09:00-17:00\\"}}]}}"
  BOOKING_EVENTS_MINUTES = "30"
  ENABLE_GET_CALENDAR_EVENTS = "true"

**"Disable booking"** →
  START_BOOKING_PROCESS = "false"

**"30-minute appointments"** →
  BOOKING_EVENTS_MINUTES = "30"

**"1-hour appointments"** →
  BOOKING_EVENTS_MINUTES = "60"

**"Only mornings"** →
  BOOKING_HOURS = "{{\\"monday\\": [{{\\"09:00-12:00\\"}}], \\"tuesday\\": [{{\\"09:00-12:00\\"}}], \\"wednesday\\": [{{\\"09:00-12:00\\"}}], \\"thursday\\": [{{\\"09:00-12:00\\"}}], \\"friday\\": [{{\\"09:00-12:00\\"}}]}}"

**"Require 24 hours notice"** →
  BOOKING_SHORTEST_NOTICE = "24"

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT BOOKING STATUS
Is booking enabled? What are the current hours/duration?

### SECTION 2: VARIABLE RELATIONSHIPS & RESTRICTIONS
Based on the "Depends On" and "LOCKED" annotations in the metadata above:
- Which variables are parent switches (no dependencies)
- Which variables depend on others (from their "Depends On" field)
- Which variables are locked and cannot be modified
- If a parent is locked, note that all its dependents are effectively locked too

### SECTION 3: INTENT → CHANGES MAPPING
List common requests and which variables to change. Only suggest changes to modifiable variables whose parent dependencies are enabled.

### SECTION 4: VARIABLE TYPES & VALIDATION
- Booleans: "true"/"false" (string, not primitive)
- Integers: "30" (string)
- JSON: Valid JSON string for BOOKING_HOURS

### SECTION 5: ALL CURRENT VALUES
You MUST explicitly list the current value of EVERY variable provided in the VARIABLE METADATA.
The configurator agent relies on this section to know the current state.
Format:
- VARIABLE_NAME: "exact_current_value"

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


# Meta-prompt for generating caller followup sub-prompts
CALLER_FOLLOWUP_META_PROMPT = """You are analyzing the caller followup configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure the post-call messaging system that sends WhatsApp or SMS to the CALLER after a call ends.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

{conversation_variables_context}

## CRITICAL: CHANNEL EXECUTION PRIORITY ORDER

After a call ends, channels are evaluated in this STRICT ORDER. The first enabled channel sends the message — understanding this order is essential:

```
1. WATI (official WhatsApp)     ← highest priority, runs first and independently
2. TextMeBot (unofficial WA)   ← first in the unofficial/SMS chain
3. Callbell (official WhatsApp) ← second in chain
4. MrZappa (unofficial WA)     ← third in chain (free, unreliable)
5. SMS                          ← last in chain (or fallback-only)
```

This means: if WATI is enabled AND MrZappa is enabled, only WATI sends (it wins). If you want SMS as a fallback for MrZappa, set SEND_SMS_TO_CUSTOMER_ONLY_FALLBACK = "true".

## CHANNEL TIERS

**Official (reliable, paid):** WATI, Callbell — guaranteed delivery, Meta-approved APIs
**Unofficial (unreliable, free/cheap):** MrZappa (WHATSAPP_TO_CALLER_ENABLED), TextMeBot — Meta actively blocks these; outages are expected
**SMS:** Paid per message unit; can be standalone or fallback

## MANDATORY TROUBLESHOOTING MESSAGE

When the user reports unofficial WhatsApp is not working, the configurator MUST deliver this explanation (adapt language to user's language):

"We are sorry for the disruption. The free WhatsApp service works by emulating a WhatsApp Web session — Meta does not support this and actively prevents it from working. Outages are expected and recurring. For guaranteed delivery, switch to Meta's official APIs via Callbell or WATI (cost: a few tens of euros/month)."

## COMMON USER INTENTS → VARIABLE MAPPINGS

**"Send a WhatsApp after each call (free, unreliable)"** →
  WHATSAPP_TO_CALLER_ENABLED = "true"
  TEXT_TO_CUSTOMER_ONLY_UPON_INTERACTION = "false"

**"Send WhatsApp only when caller spoke"** →
  TEXT_TO_CUSTOMER_ONLY_UPON_INTERACTION = "true"

**"Use official WhatsApp (WATI)"** →
  WATI_ENABLED = "true"
  WATI_DOMAIN = "<live-server-XXXXX.wati.io>"
  WATI_BEARER = "<bearer_token>"
  WATI_TEMPLATE = "<template_name>"

**"Personalized message based on conversation"** →
  OSCAR_DYNAMIC_TEXTMESSAGE_GENERATION = "true"

**"SMS as fallback if WhatsApp fails"** →
  SEND_SMS_TO_CUSTOMER_ENABLED = "true"
  SEND_SMS_TO_CUSTOMER_ONLY_FALLBACK = "true"

**"SMS only, no WhatsApp"** →
  WHATSAPP_TO_CALLER_ENABLED = "false"
  WATI_ENABLED = "false"
  CALLBELL_ENABLED = "false"
  SEND_SMS_TO_CUSTOMER_ENABLED = "true"
  SEND_SMS_TO_CUSTOMER_ONLY_FALLBACK = "false"

**"Disable all caller followup"** →
  WHATSAPP_TO_CALLER_ENABLED = "false"
  WATI_ENABLED = "false"
  SEND_SMS_TO_CUSTOMER_ENABLED = "true" → "false"

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT FOLLOWUP STATUS
Which channels are currently enabled? What messages are configured? Static or dynamic mode?

### SECTION 2: CHANNEL PRIORITY CHAIN
Explain the 5-step priority order. Note which channels are official vs unofficial. Warn about MrZappa reliability.

### SECTION 3: VARIABLE RELATIONSHIPS & RESTRICTIONS
From "Depends On" and visibility annotations in the metadata:
- WATI_DOMAIN, WATI_BEARER, WATI_TEMPLATE depend on WATI_ENABLED
- SEND_SMS_TO_CUSTOMER_INTERACTION_MESSAGE depends on SEND_SMS_TO_CUSTOMER_INTERACTION
- SEND_SMS_TO_CUSTOMER_NO_INTERACTION_MESSAGE depends on SEND_SMS_TO_CUSTOMER_NO_INTERACTION
- Admin/invisible variables: list them but mark as not configurable
- SMS_FROM must be max 11 characters

### SECTION 4: INTENT → CHANGES MAPPING
Common requests and which variables to set. Include the WATI/Callbell admin variable caveats.

### SECTION 5: ALL CURRENT VALUES
Explicitly list every variable's current value. The configurator agent needs this to know the state.
Format:
- VARIABLE_NAME: "exact_current_value"

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


# Meta-prompt for generating conversation sub-prompts
CONVERSATION_META_PROMPT = """You are analyzing the conversation flow configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure CONVERSATION_PROMPT — the single source of truth for what the assistant does after the welcome greeting.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

These variables can be used inside CONVERSATION_PROMPT using %%var%% syntax:

{conversation_variables_context}

## CRITICAL: READ-BEFORE-WRITE RULE

BEFORE proposing any changes to CONVERSATION_PROMPT, the configurator MUST check INBOUND_WELCOME_MESSAGE_PROMPT to avoid duplication. If the greeting already asks for the caller's name, do NOT add "ask for name" to CONVERSATION_PROMPT.

The 4 FIRST_NAME coordination scenarios:
| Welcome asks name? | FIRST_NAME known? | What happens |
|---|---|---|
| No | Yes ("Anna") | Conversation uses stored name directly |
| No | No (unknown) | Conversation should ask for the name |
| Yes | No (unknown) | Caller gives name during greeting — conversation has it |
| Yes | Yes ("Anna") | Welcome skips asking — conversation uses it |

## VALUE FORMAT

CONVERSATION_PROMPT is freeform text in two optional parts:

**Part 1: Variable declarations (optional)**
```
STORED_NAME=%%crm.contact.variables.FIRST_NAME=not available%%
BUSINESS_OPEN=%%public:BUSINESS_OPEN=true%%
```

**Part 2: Behavioral instructions (natural language)**
```
If STORED_NAME is "not available", ask the caller for their name.
Ask what brings them in today.
When all questions are answered, ask if there's anything else, then hang up.
```

Always include a hangup instruction at the end.

## LEGACY FURTHER_QUESTIONS MIGRATION

If FURTHER_QUESTIONS is non-empty (not `[]`), the configurator MUST migrate it:
1. Convert each [question, instruction] pair to natural language in CONVERSATION_PROMPT
2. Set FURTHER_QUESTIONS to "[]" in a separate API call

Example conversion:
- BEFORE: `["How many guests?", "If more than 10, inform about deposit."]`
- AFTER in CONVERSATION_PROMPT: `Ask how many people will be dining.\nIf more than 10, inform them that large groups require a deposit.`

## COMMON USER INTENTS → VARIABLE MAPPINGS

**"Add a question about [topic]"** →
  Append to CONVERSATION_PROMPT: "Ask [question about topic]. [Handle response]."

**"Use the caller's name"** →
  Add `STORED_NAME=%%crm.contact.variables.FIRST_NAME=not available%%` at the top
  Add: "If STORED_NAME is 'not available', ask for their name. Otherwise greet by name."

**"Ask for email address"** →
  Add to CONVERSATION_PROMPT: "Ask for the caller's email address."
  (Also check if EMAIL_ADDRESS is in ASSISTANT_TOOL_VARIABLE_EXTRACTION so it gets saved)

**"End call after collecting info"** →
  Add at the end: "When all questions are answered, ask if there's anything else, then hang up."

**"Handle returning callers differently"** →
  Add `RECURRENT_CALLER=%%RECURRENT_CONTACT%%`
  Add: "If RECURRENT_CALLER is 'true', greet them as a returning customer and ask how you can help."

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT CONVERSATION FLOW
Describe in plain language what the assistant currently does step by step after the greeting.
Note if FURTHER_QUESTIONS is non-empty (migration needed).

### SECTION 2: AVAILABLE VARIABLES
Table of %%...%% variables that can be used in CONVERSATION_PROMPT.
Include the full syntax (e.g., `%%crm.contact.variables.FIRST_NAME=not available%%`) and what it means.

### SECTION 3: COORDINATION WITH WELCOME MESSAGE
What does the welcome message currently cover? What should NOT be duplicated in CONVERSATION_PROMPT?

### SECTION 4: HOW TO MODIFY
Rules for editing CONVERSATION_PROMPT:
- Adding a question: append natural language
- Using a variable: add declaration at top
- Always end with hangup logic
- Do NOT re-ask what the welcome message already covers
- If FURTHER_QUESTIONS is non-empty: migrate before modifying

### SECTION 5: ALL CURRENT VALUES
- CONVERSATION_PROMPT: (full current value in a code block)
- FURTHER_QUESTIONS: (current value — if non-empty, flag migration needed)

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


# Meta-prompt for generating knowledge base sub-prompts
KNOWLEDGE_BASE_META_PROMPT = """You are analyzing the knowledge base configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure the Q&A knowledge base that the assistant uses to answer caller questions during phone calls.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

{conversation_variables_context}

## TWO-COMPONENT STRUCTURE

The knowledge base has TWO independent components:

**1. `OSCAR2_KNOWLEDGE_BASE`** (type: verbatim, plain text)
→ Admin-level instructions placed at the TOP of the knowledge base section.
→ Controls: how the assistant handles questions not in the Q&A list, tone, expertise level, off-topic handling.
→ Example: "You are an expert dental assistant. For questions not covered here, say you will pass the request to a dentist who will call back."

**2. `KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS`** (type: tuples, JSON array)
→ Structured Q&A pairs. Format: `[["topic or keywords", "answer instructions"], ...]`
→ Each pair renders in the prompt as: "IF THE CALLER ASKS QUESTIONS LIKE OR ABOUT: {{topic}}\n→ {{answer}}"

Modifying one does NOT affect the other.

## AUTO-GENERATED ENTRIES (DO NOT ADD MANUALLY)

The following Q&A entries are ALWAYS auto-generated by the runtime. Do NOT add these to KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS:
- Business address
- Opening hours
- Current date
- Current time
- Booking availability (handled by booking configuration)

## JSON FORMAT FOR KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS

```json
[
  ["question topic or keywords", "answer instructions"],
  ["second topic", "second answer"]
]
```

Rules:
- Each inner array MUST have exactly 2 elements
- Both elements MUST be non-empty strings (pairs with empty elements are silently dropped)
- The value is stored as a JSON string

## ADDITIVE OPERATIONS

When the user says "add a question about X":
→ READ the current value first
→ APPEND the new pair to the existing array
→ Do NOT replace the entire array

## COMMON USER INTENTS → VARIABLE MAPPINGS

**"Add Q&A about [topic]"** →
  Append `["topic keywords", "answer instructions"]` to KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS

**"Set general behavior for unknown questions"** →
  OSCAR2_KNOWLEDGE_BASE = "For questions not covered here, say you will [action]."

**"Remove Q&A about [topic]"** →
  Read current value, filter out the matching pair, write back the updated array

**"Clear all Q&A"** →
  KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS = "[]"

**"Make assistant more expert/authoritative"** →
  Update OSCAR2_KNOWLEDGE_BASE with expertise framing

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT KNOWLEDGE BASE STATE
Is OSCAR2_KNOWLEDGE_BASE set? How many Q&A pairs are in KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS?
List current Q&A topics briefly.

### SECTION 2: COMPONENT ROLES
Explain the two components and when to modify each.
List auto-generated entries that must NOT be manually added.

### SECTION 3: INTENT → CHANGES MAPPING
Common requests and which component/variable to update.
Include the additive operation rule (append, don't replace).

### SECTION 4: JSON FORMAT & VALIDATION
Rules for KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS: 2-element arrays, no empty strings.
Show how the Q&A renders in the final prompt.

### SECTION 5: ALL CURRENT VALUES
- OSCAR2_KNOWLEDGE_BASE: (full current value)
- KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS: (full current JSON in a code block)

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


# Meta-prompt for generating business notifications sub-prompts
NOTIFICATIONS_BUSINESS_META_PROMPT = """You are analyzing the business notification configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure the notification channels that inform the BUSINESS OWNER about incoming calls (not the caller — that's a different feature).

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

{conversation_variables_context}

## NOTIFICATION CHANNELS

Four independent channels, each configurable separately:

1. **Firebase push** — Mobile app notification (always active, only control: block empty calls)
2. **Email** — Call transcription + audio recording attachment
3. **WhatsApp to business** — Via WATI platform (REQUIRES purchased package)
4. **SMS to business** — Via Nexmo/Vonage (requires purchased SMS package)

Pipeline runs sequentially: Firebase → Email → WhatsApp → SMS. All enabled channels send (no priority chain — unlike caller followup).

## CRITICAL: PAYMENT GATE

`WHATSAPP_TO_BIZ_PAID` is set ONLY by the payment system. NEVER set it manually.
- If the user wants WhatsApp notifications and WHATSAPP_TO_BIZ_PAID = "false":
  → Tell them: "WhatsApp business notifications require purchasing the WhatsApp package first. Once purchased, it will be activated automatically."

## "EMPTY CALL" DEFAULTS (important — each channel differs)

An "empty call" = caller did not speak with the assistant (silent or immediate hangup).

| Channel | Variable | Default | Meaning |
|---|---|---|---|
| Firebase | NO_EMPTY_FIREBASE_NOTIFICATION | "false" | Push SENT for empty calls by default |
| Email | NO_EMAIL_EMPTY_MESSAGE | "false" | Email SENT for empty calls by default |
| WhatsApp | WHATSAPP_TO_BIZ_NO_EMPTY_MESSAGE | "false" | WhatsApp SENT for empty calls by default |
| SMS | NO_SMS_EMPTY_MESSAGE | "true" | SMS NOT sent for empty calls by default (saves credits) |

Setting a "NO_EMPTY_*" variable to "true" BLOCKS notifications for empty calls.

## WHATSAPP_MESSAGE_BIZ_TO_CUSTOMER

This is NOT the notification text itself. It is the pre-filled text for the "Send WhatsApp to caller" BUTTON embedded in the notification email. When the business owner clicks it, WhatsApp opens with this text pre-filled.

## COMMON USER INTENTS → VARIABLE MAPPINGS

**"Enable email notifications"** →
  EMAIL_SERVICE = "true"
  EMAIL_TO = "<email@address.com>"

**"Add a CC email recipient"** →
  (Admin only — not directly configurable by the agent)

**"Don't notify for silent calls"** →
  NO_EMPTY_FIREBASE_NOTIFICATION = "true"
  NO_EMAIL_EMPTY_MESSAGE = "true"
  WHATSAPP_TO_BIZ_NO_EMPTY_MESSAGE = "true" (if WhatsApp enabled)

**"Enable SMS notifications"** →
  SMS_TO_BIZ_ENABLED = "true"
  SMS_TO_NUMBER = "+<international_number>"

**"Enable WhatsApp notifications to business"** →
  Check WHATSAPP_TO_BIZ_PAID first. If "true":
    WHATSAPP_TO_BIZ_ENABLED = "true"
    WHATSAPP_TO_BIZ_NUMBER = "+<international_number>"

**"Use special characters in SMS (Cyrillic, Arabic, etc.)"** →
  SMS_TO_BIZ_UNICODE = "true" (note: doubles cost)

**"Set the pre-filled WhatsApp reply text"** →
  WHATSAPP_MESSAGE_BIZ_TO_CUSTOMER = "<text in business language>"

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT NOTIFICATION STATE
Which channels are enabled? What email address(es) are configured? Is WhatsApp paid? What phone numbers are set?

### SECTION 2: CHANNEL OVERVIEW & PAYMENT GATES
Describe each channel and its payment requirements. Emphasize WHATSAPP_TO_BIZ_PAID cannot be set manually.

### SECTION 3: EMPTY CALL BEHAVIOR
Table showing each channel's default for empty calls and how to change it.

### SECTION 4: INTENT → CHANGES MAPPING
Common requests and which variables to set. Include the WHATSAPP_TO_BIZ_PAID check rule.

### SECTION 5: ALL CURRENT VALUES
Explicitly list every variable's current value.
Format:
- VARIABLE_NAME: "exact_current_value"

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


# Meta-prompt for generating runtime data management sub-prompts
RUNTIME_DATA_META_PROMPT = """You are analyzing the runtime data management configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure external API integrations that operate during phone calls across 3 lifecycle stages.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS (available as %%VARIABLE%% in API templates)

{conversation_variables_context}

## THREE-STAGE LIFECYCLE

**PREFETCH** — Before conversation starts: call external APIs to load context into the assistant's prompt (e.g., look up caller in CRM by phone number).

**RUNNINGLOOP** — During conversation: assistant invokes external APIs based on caller intent (e.g., "check my order status"). Each configured function becomes an OpenAI function that GPT can call.

**FINAL** — After conversation ends: push collected data to external systems (e.g., create CRM lead, send webhook).

## CRITICAL: ELEMENT COUNT DIFFERENCE

PREFETCH and FINAL use **9-element** arrays. RUNNINGLOOP uses **11-element** arrays (adds Trigger at pos 2 and Variables at pos 9).

### PREFETCH / FINAL array (9 elements):
| Pos | Name | Type | Notes |
|---|---|---|---|
| 0 | Function Name | string | Unique identifier |
| 1 | Active | "true"/"false" | Enable/disable |
| 2 | Prompt Template (Success) | text | Use %%FUNCTION_RESPONSE_BODY%% for API response |
| 3 | Prompt Template (Failure) | text | What to do if API fails |
| 4 | Output Format | "JSON" or "TEXT" | Default: "JSON" |
| 5 | HTTP Method | "GET","POST","UPDATE","DELETE" | Default: "GET" |
| 6 | HTTP Headers | array of [key, value] pairs | e.g., [["Authorization","Bearer xyz"]] |
| 7 | URL | string | Supports %%VARIABLE%% substitution |
| 8 | Input JSON Body | JSON string | "" for no body; %%VARIABLE%% in string values |

### RUNNINGLOOP array (11 elements — positions 2 and 9 are extra):
| Pos | Name | Type | Notes |
|---|---|---|---|
| 0 | Function Name | string | Becomes `rest_{{FunctionName}}` in OpenAI |
| 1 | Active | "true"/"false" | |
| **2** | **Trigger** | text | **When GPT should call this function (becomes OpenAI function description)** |
| 3 | Prompt Template (Success) | text | |
| 4 | Prompt Template (Failure) | text | |
| 5 | Output Format | "JSON" or "TEXT" | |
| 6 | HTTP Method | | |
| 7 | HTTP Headers | array of [key, value] pairs | |
| 8 | URL | string | |
| **9** | **Variables** | array of [name, description, required] | **Parameters GPT extracts from conversation** |
| 10 | Input JSON Body | JSON string | |

## %%VARIABLE%% TEMPLATE SYNTAX

Always available in URL and body templates:
- `%%HB_FROM_NUMBER%%` — caller's phone number
- `%%HB_TS_MILLIS_NOW%%` — current timestamp in milliseconds
- `%%HB_TS_SEC_NOW%%` — current timestamp in seconds
- `%%FIRST_NAME%%`, `%%FAMILY_NAME%%`, `%%CALL_REASON%%` — conversation-extracted values

Syntax variants: `%%VAR%%`, `%%VAR=default%%`, `%%VAR:=default%%`

Security: Variables whose keys start with `private` or `secret` are blocked.

## PREREQUISITE CHECK

1. `OSCAR_VERSION` must be "4" — check and set if needed
2. `ENABLE_DATA_MANAGEMENT_TAB` must be "true"

## DECISIONAL GUIDE

When a user wants to set up data management, ask:
1. "Do you need to look up caller data BEFORE the conversation?" → PREFETCH
2. "Does the assistant need to query APIs based on WHAT the caller says?" → RUNNINGLOOP
3. "Do you need to PUSH data to external systems AFTER the call?" → FINAL

For each stage: collect URL, auth method, HTTP method, and stage-specific fields.

## COMMON USER INTENTS → VARIABLE MAPPINGS

**"Look up caller in CRM before call"** →
  DATA_MANAGEMENT_PREFETCH_RESTAPI_PROGRAMMATIC with GET to CRM URL using %%HB_FROM_NUMBER%%

**"Let assistant check order status during call"** →
  DATA_MANAGEMENT_RUNNINGLOOP_RESTAPI_PROGRAMMATIC with trigger describing when to call,
  variables defining what GPT extracts from conversation (e.g., ORDER_ID)

**"Create a lead after call"** →
  DATA_MANAGEMENT_FINAL_RESTAPI_PROGRAMMATIC with POST including %%FIRST_NAME%%, %%FAMILY_NAME%%, %%CALL_REASON%%

**"Enable data management tab"** →
  ENABLE_DATA_MANAGEMENT_TAB = "true"

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT DATA MANAGEMENT STATE
Is ENABLE_DATA_MANAGEMENT_TAB enabled? OSCAR_VERSION? How many functions configured per stage?

### SECTION 2: THREE-STAGE LIFECYCLE
Explain PREFETCH / RUNNINGLOOP / FINAL with the element count difference highlighted.

### SECTION 3: ELEMENT SCHEMAS
Include the 9-element (PREFETCH/FINAL) and 11-element (RUNNINGLOOP) tables as reference.

### SECTION 4: TEMPLATE VARIABLES
List %%VARIABLE%% templates available in URLs and bodies. Note security restrictions.

### SECTION 5: INTENT → CONFIGURATION GUIDE
The decisional guide (which stage for which need).

### SECTION 6: ALL CURRENT VALUES
Full current JSON for each configured stage in code blocks.

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


# Meta-prompt for generating call transfer sub-prompts
CALL_TRANSFER_META_PROMPT = """You are analyzing the call transfer/forwarding configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure transfer rules that allow the AI to forward calls to specific phone numbers based on caller intent.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

{conversation_variables_context}

## HOW TRANSFER RULES WORK

Each transfer rule = one OpenAI function with `name = "transfer"`.
GPT reads all trigger descriptions and invokes `transfer` with the matching NUMBER and MESSAGE when caller intent matches.

All functions are named "transfer" — they are distinguished ONLY by their trigger description. Therefore, triggers must be specific and non-overlapping.

## VALUE FORMAT: TRANSFER_CALL_OSCAR

JSON array of 4-element arrays:
```json
[
  ["trigger description", "phone_number", "message before transfer", "enabled_status"],
  ...
]
```

| Position | Name | Format | Notes |
|---|---|---|---|
| 0 | Trigger | Natural language condition | Becomes OpenAI function description — write specifically |
| 1 | Phone number | International format, e.g. "+393471149738" | Spaces stripped at runtime |
| 2 | Message | What to say before transferring | |
| 3 | Enabled status | "enabled", "enabled_open", or "enabled_close" | Default: "enabled" if omitted |

## ENABLED STATUS LOGIC (business hours filtering)

| Business State | "enabled" | "enabled_open" | "enabled_close" |
|---|---|---|---|
| Open (business hours) | Active | Active | **Inactive** |
| Closed (outside hours) | Active | **Inactive** | Active |

Use cases:
- `"enabled"` — always active regardless of hours
- `"enabled_open"` — only during business hours (e.g., transfer to office)
- `"enabled_close"` — only outside hours (e.g., transfer to on-call/emergency)

## COMMON USER INTENTS → VARIABLE MAPPINGS

**"Transfer to [person] when caller asks for them"** →
  Add: `["the CALLER wants to speak with [person name]", "+number", "message", "enabled"]`

**"Transfer to office during hours, emergency after hours"** →
  Add two rules:
  - `["the CALLER wants to speak with an operator", "+office", "Transferring...", "enabled_open"]`
  - `["the CALLER has an urgent issue outside business hours", "+oncall", "Transferring to emergency...", "enabled_close"]`

**"Enable call transfer"** →
  TRANSFER_CALL_ENABLED = "true"

**"Disable call transfer"** →
  TRANSFER_CALL_ENABLED = "false"

**"Remove a transfer rule"** →
  Read current TRANSFER_CALL_OSCAR, filter out matching rule, write back

**"Add a transfer rule"** →
  Read current TRANSFER_CALL_OSCAR, append new 4-element array, write back

## VALIDATION RULES

- Each inner array: 3 or 4 elements (4th optional, defaults to "enabled")
- Phone number: international format
- Enabled status: must be exactly "enabled", "enabled_open", or "enabled_close"
- Trigger must be specific enough for GPT to distinguish from other triggers
- Max trigger length: keep it concise (it's an OpenAI function description)

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT TRANSFER STATE
Is TRANSFER_CALL_ENABLED = "true"? How many rules are configured? List current rules with their trigger, number, and status.

### SECTION 2: HOW TRANSFER RULES WORK
Explain the OpenAI function model, the trigger-as-description pattern, and why triggers must be specific.

### SECTION 3: BUSINESS HOURS FILTERING
Explain enabled/enabled_open/enabled_close with the matrix table. When to use each.

### SECTION 4: INTENT → CHANGES MAPPING
Common requests mapped to variable changes. Include additive operation rule (append, don't replace).

### SECTION 5: ALL CURRENT VALUES
- TRANSFER_CALL_ENABLED: "exact_value"
- TRANSFER_CALL_OSCAR: (full current JSON in a code block)

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


class MrCallConfiguratorTrainer:
    """Generates feature-specific sub-prompts from MrCall configuration.

    Each feature (welcome_inbound, welcome_outbound, booking, etc.) has its own sub-prompt that:
    - Documents available variables
    - Describes current behavior
    - Lists what can be changed
    - Includes raw prompt for modification

    Sub-prompts are stored in agent_prompts with agent_type=mrcall_{business_id}_{feature}
    """

    # Feature definitions - maps feature name to variable(s) and meta-prompt
    FEATURES = {
        "welcome_inbound": {
            "variables": [
                "ENABLE_INBOUND_WELCOME_MESSAGE_PROMPT",
                "INBOUND_WELCOME_MESSAGE_PROMPT",
                "TEMPORARY_MESSAGE",
                "TALK_AND_HANGUP_OPEN",
                "TALK_AND_HANGUP_CLOSED",
                "TALK_AND_HANGUP_OPEN_MESSAGE",
                "TALK_AND_HANGUP_CLOSED_MESSAGE",
            ],
            "description": "Welcome greeting for inbound calls",
            "display_name": "How the assistant answers inbound calls",
            "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
            "dynamic_context": True,
        },
        "welcome_outbound": {
            "variables": [
                "ENABLE_OUTBOUND_WELCOME_MESSAGE_PROMPT",
                "OUTBOUND_WELCOME_MESSAGE_PROMPT",
                "OUTBOUND_WELCOME_MESSAGE_TEXT",
            ],
            "description": "Welcome greeting for outbound calls",
            "display_name": "How the assistant starts outbound calls",
            "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
            "dynamic_context": True,
        },
        "booking": {
            "variables": [
                "START_BOOKING_PROCESS",
                "BOOKING_TRIGGER",
                "NO_BOOKING_INSTRUCTIONS",
                "ENABLE_GET_CALENDAR_EVENTS",
                "ENABLE_CLEAR_CALENDAR_EVENTS",
                "BOOKING_HOURS",
                "BOOKING_EVENTS_MINUTES",
                "BOOKING_DAYS_TO_GENERATE",
                "BOOKING_SHORTEST_NOTICE",
                "BOOKING_ONLY_WORKING_HOURS",
                "BOOKING_MULTIPLE_ALLOWED",
                # BOOKING_CALENDAR_ID is auto-set via OAuth, not user-configurable
                "BOOKING_TITLE",
                "BOOKING_DESCRIPTION",
                "BOOKING_PRE_INSTRUCTION",
                "BOOKING_LAST_INSTRUCTION",
                "COMMUNICATE_BOOKING_MESSAGE",
            ],
            "display_name": "How your MrCall assistant manages booking requests",
            "meta_prompt": BOOKING_META_PROMPT,
            "dynamic_context": True,  # Uses _build_variables_context for metadata
        },
        "caller_followup": {
            "variables": [
                "WHATSAPP_TO_CALLER_ENABLED",
                "WHATSAPP_TO_CALLER_INSTRUCTIONS_INTERACTION",
                "WHATSAPP_TO_CALLER_INSTRUCTIONS_NO_INTERACTION",
                "TEXT_ME_BOT_ENABLED",
                "TEXT_ME_BOT_API_KEY",
                "TEXT_TO_CUSTOMER_ONLY_UPON_INTERACTION",
                "OSCAR_DYNAMIC_TEXTMESSAGE_GENERATION",
                "SEND_SMS_TO_CUSTOMER_ENABLED",
                "SMS_TO_BIZ_UNICODE",
                "SMS_FROM",
                "SEND_SMS_TO_CUSTOMER_ONLY_FALLBACK",
                "SEND_SMS_TO_CUSTOMER_INTERACTION",
                "SEND_SMS_TO_CUSTOMER_INTERACTION_MESSAGE",
                "SEND_SMS_TO_CUSTOMER_NO_INTERACTION",
                "SEND_SMS_TO_CUSTOMER_NO_INTERACTION_MESSAGE",
                "WATI_ENABLED",
                "WATI_DOMAIN",
                "WATI_BEARER",
                "WATI_TEMPLATE",
                "CALLBELL_ENABLED",
                "CALLBELL_API_KEY",
            ],
            "description": "Post-call WhatsApp/SMS messages sent to the caller",
            "display_name": "Post-call messages sent to the caller (WhatsApp/SMS)",
            "meta_prompt": CALLER_FOLLOWUP_META_PROMPT,
            "dynamic_context": True,
        },
        "conversation": {
            "variables": [
                "ENABLE_CONVERSATION_PROMPT",
                "CONVERSATION_PROMPT",
                "FURTHER_QUESTIONS",
                "ASSISTANT_TOOL_VARIABLE_EXTRACTION",
            ],
            "description": "What the assistant does after the welcome greeting",
            "display_name": "Conversation flow and questions the assistant asks",
            "meta_prompt": CONVERSATION_META_PROMPT,
            "dynamic_context": True,
        },
        "knowledge_base": {
            "variables": [
                "KNOWLEDGE_BASE_ANSWER_INSTRUCTIONS",
                "OSCAR2_KNOWLEDGE_BASE",
            ],
            "description": "Q&A pairs and instructions for answering caller questions",
            "display_name": "Knowledge base Q&A for answering caller questions",
            "meta_prompt": KNOWLEDGE_BASE_META_PROMPT,
            "dynamic_context": True,
        },
        "notifications_business": {
            "variables": [
                "NO_EMPTY_FIREBASE_NOTIFICATION",
                "EMAIL_SERVICE",
                "EMAIL_TO",
                "NO_EMAIL_EMPTY_MESSAGE",
                "WHATSAPP_MESSAGE_BIZ_TO_CUSTOMER",
                "WHATSAPP_TO_BIZ_PAID",
                "WHATSAPP_TO_BIZ_ENABLED",
                "WHATSAPP_TO_BIZ_NUMBER",
                "WHATSAPP_TO_BIZ_NO_EMPTY_MESSAGE",
                "SMS_TO_BIZ_ENABLED",
                "SMS_TO_BIZ_UNICODE",
                "SMS_TO_NUMBER",
                "NO_SMS_EMPTY_MESSAGE",
            ],
            "description": "Notification channels that inform the business owner about calls",
            "display_name": "Notifications sent to the business owner after each call",
            "meta_prompt": NOTIFICATIONS_BUSINESS_META_PROMPT,
            "dynamic_context": True,
        },
        "runtime_data": {
            "variables": [
                "ENABLE_DATA_MANAGEMENT_TAB",
                "DATA_MANAGEMENT_PREFETCH_RESTAPI_PROGRAMMATIC",
                "DATA_MANAGEMENT_RUNNINGLOOP_RESTAPI_PROGRAMMATIC",
                "DATA_MANAGEMENT_FINAL_RESTAPI_PROGRAMMATIC",
            ],
            "description": "External API integrations for PREFETCH/RUNNINGLOOP/FINAL stages",
            "display_name": "External API integrations (CRM, webhooks, real-time data)",
            "meta_prompt": RUNTIME_DATA_META_PROMPT,
            "dynamic_context": True,
        },
        "call_transfer": {
            "variables": [
                "TRANSFER_CALL_ENABLED",
                "TRANSFER_CALL_OSCAR",
            ],
            "description": "Call forwarding rules based on caller intent and business hours",
            "display_name": "Call transfer rules (forward calls to specific numbers)",
            "meta_prompt": CALL_TRANSFER_META_PROMPT,
            "dynamic_context": True,
        },
    }

    def __init__(
        self,
        storage: SupabaseStorage,
        starchat_client,
        owner_id: str,
        api_key: str,
        provider: str,
    ):
        """Initialize MrCallConfiguratorTrainer.

        Args:
            storage: SupabaseStorage instance for storing sub-prompts
            starchat_client: StarChatClient for fetching MrCall config
            owner_id: Firebase UID
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.starchat = starchat_client
        self.owner_id = owner_id
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, PROVIDER_MODELS["anthropic"])
        self.client = LLMClient(api_key=api_key, provider=provider)

    async def _build_variables_context(
        self,
        business_id: str,
        variable_names: List[str],
        business: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build variables context from StarChat metadata.

        Fetches variable schema (type, description, default) and current values,
        then formats them for injection into the meta-prompt.

        Args:
            business_id: MrCall business ID
            variable_names: List of variable names to include
            business: Pre-fetched business config (avoids redundant API call)

        Returns:
            Formatted string with metadata for each variable
        """
        # Get business config for current values and template
        logger.debug(f"[MrCallConfiguratorTrainer] _build_variables_context(business_id={business_id}, vars={variable_names})")
        if business is None:
            business = await self.starchat.get_business_config(business_id)
        logger.debug(f"[MrCallConfiguratorTrainer] get_business_config -> found={business is not None}")
        if not business:
            raise ValueError(f"Business not found: {business_id}")

        current_values = business.get("variables", {})
        template = business.get("template", "businesspro")
        # languageCountry for default value fallback (e.g. "it_IT" -> "it-IT")
        raw_lang = business.get("languageCountry", "")
        biz_lang = raw_lang.replace("_", "-") if raw_lang else ""
        biz_lang_short = biz_lang[:2] if biz_lang else ""
        logger.debug(f"[MrCallConfiguratorTrainer] template={template}, current_values_count={len(current_values)}, languageCountry={raw_lang} -> biz_lang={biz_lang}")

        # Get schema for metadata (type, description, default)
        # nested=True with languageDescriptions returns localized flat fields
        # Response is an array of collections: [{variables: [{name, type, description, defaultValue, ...}]}]
        raw_schema = await self.starchat.get_variable_schema(
            template_name=template,
            language=biz_lang or "en-US",
            nested=True,
            language_descriptions=biz_lang_short or "en",
        )
        logger.debug(f"[MrCallConfiguratorTrainer] get_variable_schema(template={template}, nested=True, langDesc={biz_lang_short or 'en'}) -> type={type(raw_schema).__name__}, len={len(raw_schema) if raw_schema else 0}")

        # Flatten collections array into {var_name: var_data}
        # variables arrays may contain nested lists (dashboard uses .flat())
        schema: Dict[str, Any] = {}
        if isinstance(raw_schema, list):
            for collection in raw_schema:
                if not isinstance(collection, dict):
                    continue
                for item in collection.get("variables", []):
                    # Handle nested lists: [[{var}, {var}], [{var}]]
                    vars_to_process = item if isinstance(item, list) else [item]
                    for var in vars_to_process:
                        if isinstance(var, dict):
                            name = var.get("name")
                            if name:
                                schema[name] = var
        elif isinstance(raw_schema, dict):
            schema = raw_schema
        logger.debug(f"[MrCallConfiguratorTrainer] flattened schema: {len(schema)} variables")

        # Build context for each variable — include ALL variables with full metadata
        # so the sub-prompt-generating LLM has the complete picture
        lines = []
        for var_name in variable_names:
            var_schema = schema.get(var_name, {})

            # Use server-localized flat keys (populated by languageDescriptions param)
            human_name = var_schema.get("humanName", "")
            desc = var_schema.get("description", "")
            default = var_schema.get("defaultValue", "")
            var_type = var_schema.get("type", "unknown")
            current = current_values.get(var_name, "Not set")
            modifiable = var_schema.get("modifiable", True)
            visible = var_schema.get("visible", True)
            admin = var_schema.get("admin", False)

            # Flatten depends_on from [["VAR"]] to ["VAR"]
            depends_on_raw = var_schema.get("depends_on", [])
            depends_on = []
            if isinstance(depends_on_raw, list):
                for dep_item in depends_on_raw:
                    if isinstance(dep_item, list) and dep_item:
                        depends_on.append(dep_item[0])
                    elif isinstance(dep_item, str):
                        depends_on.append(dep_item)

            logger.debug(f"[MrCallConfiguratorTrainer] var={var_name}, type={var_type}, humanName='{human_name}', desc='{desc}', default='{default}', current='{current}', modifiable={modifiable}, visible={visible}, admin={admin}, depends_on={depends_on}")

            if current == "Not set":
                matching_keys = [k for k in current_values.keys() if "BOOKING" in k]
                logger.warning(f"[MrCallConfiguratorTrainer] Variable {var_name} not found in current_values. BusinessID={business_id}")
                logger.warning(f"[MrCallConfiguratorTrainer] Available keys with 'BOOKING': {matching_keys}")

            var_context = f"""
**{var_name}**
- Type: {var_type}
- Human Name: {human_name}
- Description: {desc}
- Default: {default}
- Current Value: {current}"""

            if depends_on:
                var_context += f"\n- Depends On: {', '.join(depends_on)}"
            if not modifiable:
                var_context += "\n- Modifiable: No (locked by subscription plan)"
            if not visible:
                var_context += "\n- Visible: No"
            if admin:
                var_context += "\n- Admin: Yes"

            lines.append(var_context)

        return "\n".join(lines)

    async def _build_conversation_variables_context(
        self,
        business_id: str,
        business: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build conversation variables context for injection into meta-prompts.

        Fetches ASSISTANT_TOOL_VARIABLE_EXTRACTION from the business config
        to discover which caller variables are available, and combines them
        with the static public:* variables and exportable aliases.

        Args:
            business_id: MrCall business ID
            business: Pre-fetched business config (avoids redundant API call)

        Returns:
            Formatted markdown string describing all conversation variables
        """
        if business is None:
            business = await self.starchat.get_business_config(business_id)
        if not business:
            raise ValueError(f"Business not found: {business_id}")

        current_values = business.get("variables", {})

        # --- Dynamic: parse ASSISTANT_TOOL_VARIABLE_EXTRACTION ---
        # Format: [["VAR_NAME", "Description", "required", "forget"], ...]
        extraction_vars = []
        raw_extraction = current_values.get("ASSISTANT_TOOL_VARIABLE_EXTRACTION", "")
        if raw_extraction:
            try:
                parsed = json.loads(raw_extraction)
                for entry in parsed:
                    if isinstance(entry, list) and len(entry) >= 2:
                        var_name = entry[0].strip()
                        description = entry[1]
                        forget = entry[3].lower() == "true" if len(entry) > 3 else False
                        extraction_vars.append((var_name, description, forget))
            except (json.JSONDecodeError, IndexError) as e:
                logger.warning(
                    f"[MrCallConfiguratorTrainer] Failed to parse "
                    f"ASSISTANT_TOOL_VARIABLE_EXTRACTION: {e}"
                )

        logger.debug(
            f"[MrCallConfiguratorTrainer] _build_conversation_variables_context: "
            f"extraction_vars={len(extraction_vars)}"
        )

        lines = []

        # Section 1: Caller-extracted variables
        lines.append("### Caller Information (extracted from conversation)")
        lines.append("")
        lines.append(
            "| Variable | Syntax in prompts | Description | Persists across calls |"
        )
        lines.append("|---|---|---|---|")
        if extraction_vars:
            for var_name, description, forget in extraction_vars:
                syntax = f"%%crm.contact.variables.{var_name}%%"
                persists = "No (fresh each call)" if forget else "Yes"
                lines.append(f"| {var_name} | `{syntax}` | {description} | {persists} |")
        else:
            # Fallback defaults (from sanitizeBusinessVariables.sc)
            lines.append(
                "| FIRST_NAME | `%%crm.contact.variables.FIRST_NAME%%` "
                "| Caller's first name | Yes |"
            )
            lines.append(
                "| FAMILY_NAME | `%%crm.contact.variables.FAMILY_NAME%%` "
                "| Caller's family name | Yes |"
            )
            lines.append(
                "| CALL_REASON | `%%crm.contact.variables.CALL_REASON%%` "
                "| Reason for the call | Yes |"
            )

        # Section 2: Date/time and business status (static, from public:* variables)
        lines.append("")
        lines.append("### Date/Time & Business Status")
        lines.append("")
        lines.append("| Variable | Syntax in prompts | Description |")
        lines.append("|---|---|---|")
        lines.append(
            '| HUMANIZED_TODAY | `%%public:HUMANIZED_TODAY%%` '
            '| Current date in natural language (e.g., "venerdì 20 febbraio 2026") |'
        )
        lines.append(
            '| HUMANIZED_NOW | `%%public:HUMANIZED_NOW%%` '
            '| Current time in natural language (e.g., "Ore 14 e 30 minuti") |'
        )
        lines.append(
            '| HUMANIZED_DAY_OF_WEEK | `%%public:HUMANIZED_DAY_OF_WEEK%%` '
            '| Current day of week name (e.g., "venerdì") |'
        )
        lines.append(
            "| HUMANIZED_TOMORROW_DAY_OF_WEEK "
            "| `%%public:HUMANIZED_TOMORROW_DAY_OF_WEEK%%` "
            "| Tomorrow's day of week name |"
        )
        lines.append(
            '| BUSINESS_OPEN | `%%public:BUSINESS_OPEN%%` '
            '| Whether the business is currently open ("true"/"false") |'
        )
        lines.append(
            '| OPENING_HOURS_TEXT | `%%public:OPENING_HOURS_TEXT%%` '
            '| Human-readable opening hours schedule |'
        )
        lines.append(
            '| HUMANIZED_NEXT_CHANGE_STATUS_DATETIME '
            '| `%%public:HUMANIZED_NEXT_CHANGE_STATUS_DATETIME%%` '
            '| When business will next open/close (e.g., "chiuderemo alle 18:00") |'
        )

        # Section 3: Other caller info (exportable aliases from defineExportableVariables.sc)
        lines.append("")
        lines.append("### Other Caller Info")
        lines.append("")
        lines.append("| Variable | Syntax in prompts | Description |")
        lines.append("|---|---|---|")
        lines.append(
            "| CALLER_NUMBER | `%%CALLER_NUMBER%%` or `%%HB_FROM_NUMBER%%` "
            "| Caller's phone number |"
        )
        lines.append(
            '| RECURRENT_CONTACT | `%%RECURRENT_CONTACT%%` '
            '| Whether this caller has called before ("true"/"false") |'
        )
        lines.append(
            '| OUTBOUND_CALL | `%%OUTBOUND_CALL%%` '
            '| Whether this is an outbound call ("true"/"false") |'
        )

        return "\n".join(lines)

    async def train_feature(
        self,
        feature_name: str,
        business_id: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate sub-prompt for a specific feature.

        Args:
            feature_name: Feature to train (e.g., "welcome_inbound")
            business_id: MrCall business ID

        Returns:
            Tuple of (sub_prompt_content, metadata)

        Raises:
            ValueError: If feature not found or business config unavailable
        """
        if feature_name not in self.FEATURES:
            raise ValueError(
                f"Unknown feature: {feature_name}. "
                f"Available: {list(self.FEATURES.keys())}"
            )

        feature = self.FEATURES[feature_name]
        variable_names = feature["variables"]
        meta_prompt_template = feature["meta_prompt"]

        logger.info(
            f"Training MrCall {feature_name} for business {business_id}, "
            f"variables: {variable_names}"
        )

        # Fetch business config once — reused by both context builders + metadata
        business = await self.starchat.get_business_config(business_id)
        if not business:
            raise ValueError(f"Business not found: {business_id}")

        # All features use dynamic_context - fetch metadata from StarChat
        variables_context = await self._build_variables_context(
            business_id, variable_names, business=business
        )
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: variables_context prefix: {variables_context[:500]}...")

        # Build conversation variables context (caller info, public vars, aliases)
        conversation_variables_context = await self._build_conversation_variables_context(
            business_id, business=business
        )
        logger.debug(
            f"[MrCallConfiguratorTrainer] train_feature: "
            f"conversation_variables_context length: {len(conversation_variables_context)}"
        )

        meta_prompt = meta_prompt_template.format(
            variables_context=variables_context,
            conversation_variables_context=conversation_variables_context,
        )
        # For metadata, use total length of all variables
        current_values = business.get("variables", {})
        total_length = sum(
            len(str(current_values.get(v, ""))) for v in variable_names
        )

        logger.info(
            f"Generating sub-prompt for {feature_name} "
            f"(provider: {self.provider}, model: {self.model})"
        )
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: calling LLM for {feature_name}, meta_prompt_len={len(meta_prompt)}")

        response = await self.client.create_message(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}],
        )

        sub_prompt = response.content[0].text.strip()
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: sub-prompt generated, len={len(sub_prompt)}")
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: sub-prompt content start: {sub_prompt[:500]}...")
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: sub-prompt content end: ...{sub_prompt[-500:]}")

        # 3. Store in agent_prompts
        agent_type = f"mrcall_{business_id}_{feature_name}"
        metadata = {
            "business_id": business_id,
            "feature": feature_name,
            "variables": variable_names,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt_length": total_length,
        }

        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: storing agent_prompt for {agent_type}")
        self.storage.store_agent_prompt(
            owner_id=self.owner_id,
            agent_type=agent_type,
            prompt=sub_prompt,
            metadata=metadata,
        )

        logger.info(
            f"Stored sub-prompt for {agent_type} ({len(sub_prompt)} chars)"
        )

        return sub_prompt, metadata

    async def train_all(
        self,
        business_id: str,
    ) -> Dict[str, Tuple[str, Dict[str, Any]]]:
        """Generate sub-prompts for all features.

        Args:
            business_id: MrCall business ID

        Returns:
            Dict mapping feature_name to (sub_prompt, metadata)
        """
        results = {}

        for feature_name in self.FEATURES:
            try:
                sub_prompt, metadata = await self.train_feature(
                    feature_name, business_id
                )
                results[feature_name] = (sub_prompt, metadata)
            except Exception as e:
                logger.error(f"Failed to train {feature_name}: {e}")
                results[feature_name] = (None, {"error": str(e)})

        return results

    def get_feature_context(
        self,
        feature_name: str,
        business_id: str,
    ) -> Optional[str]:
        """Get stored sub-prompt for a feature (if exists).

        Args:
            feature_name: Feature name (e.g., "welcome_inbound")
            business_id: MrCall business ID

        Returns:
            Sub-prompt content or None if not found
        """
        agent_type = f"mrcall_{business_id}_{feature_name}"
        return self.storage.get_agent_prompt(self.owner_id, agent_type)

    def delete_feature_context(
        self,
        feature_name: str,
        business_id: str,
    ) -> bool:
        """Delete stored sub-prompt for a feature.

        Args:
            feature_name: Feature name
            business_id: MrCall business ID

        Returns:
            True if deleted, False if not found
        """
        agent_type = f"mrcall_{business_id}_{feature_name}"
        return self.storage.delete_agent_prompt(self.owner_id, agent_type)

    @classmethod
    def get_available_features(cls) -> Dict[str, str]:
        """Get list of available features with descriptions.

        Returns:
            Dict mapping feature_name to description
        """
        return {
            name: info["description"]
            for name, info in cls.FEATURES.items()
        }

    @classmethod
    def get_feature_variables(cls, feature_name: str) -> list:
        """Get variables for a feature.

        Args:
            feature_name: Feature name

        Returns:
            List of variable names
        """
        if feature_name not in cls.FEATURES:
            return []
        return cls.FEATURES[feature_name]["variables"]

    @classmethod
    def diff_snapshot(
        cls,
        snapshot_variables: Dict[str, str],
        live_variables: Dict[str, str],
    ) -> Dict[str, Any]:
        """Compare trained snapshot against live variables to find stale features.

        Args:
            snapshot_variables: Variable values at last training time
            live_variables: Current live variable values from StarChat

        Returns:
            Dict with:
                - changed_variables: list of {name, feature, old_value, new_value}
                - stale_features: set of feature names that need retraining
                - current_features: set of feature names that are up to date
        """
        # Build inverse map: variable_name -> feature_name
        variable_to_feature = {
            var: feature_name
            for feature_name, feature in cls.FEATURES.items()
            for var in feature["variables"]
        }

        changed_variables = []
        stale_features = set()

        for var_name, feature_name in variable_to_feature.items():
            old_val = snapshot_variables.get(var_name)
            new_val = live_variables.get(var_name)

            # Convert both to string for comparison (StarChat returns strings)
            old_str = str(old_val) if old_val is not None else None
            new_str = str(new_val) if new_val is not None else None

            if old_str != new_str:
                changed_variables.append({
                    "name": var_name,
                    "feature": feature_name,
                    "old_value": old_val,
                    "new_value": new_val,
                })
                stale_features.add(feature_name)

        all_features = set(cls.FEATURES.keys())
        current_features = all_features - stale_features

        logger.debug(
            f"[diff_snapshot] Changed: {len(changed_variables)} variables, "
            f"stale features: {stale_features}, current features: {current_features}"
        )

        return {
            "changed_variables": changed_variables,
            "stale_features": stale_features,
            "current_features": current_features,
        }

    @classmethod
    def build_snapshot_from_business(cls, business_variables: Dict[str, str]) -> Dict[str, str]:
        """Extract only the tracked variables from business config for snapshot storage.

        Args:
            business_variables: Full business variables dict from StarChat

        Returns:
            Dict with only the variables tracked by FEATURES
        """
        tracked_vars = {
            var
            for feature in cls.FEATURES.values()
            for var in feature["variables"]
        }
        return {
            var_name: str(value) if value is not None else None
            for var_name, value in business_variables.items()
            if var_name in tracked_vars
        }
