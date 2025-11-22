# MrPark - Implementation Specification

## Project Overview

Evolve the existing MCP Gateway codebase into MrPark, a single-agent Multi-Channel Sales Intelligence System that helps sales professionals manage email communications and follow-up actions. The system prioritizes contacts based on relationships, enriches contact data from multiple sources, drafts responses, and manages task scheduling via Google Calendar.

**Critical architectural decisions** (based on technical due diligence):
- Single-agent with specialized tools (NOT multi-agent orchestration)
- Direct Anthropic SDK (NOT langchain-anthropic)
- Native function calling (NOT MCP protocol)
- Human-in-the-loop for all actions (goal is assistance, not automation)

## Core Objective

Help a sales person with:
1. Understanding who sent an email (relationship, priority, history)
2. Enriching unknown contacts via web search and external services
3. Drafting appropriate responses
4. Scheduling follow-up tasks and deadlines on Google Calendar
5. Tracking commitments and deliverables

**This is NOT an email automation system.** It's an intelligent assistant that provides recommendations and drafts, with the human making all final decisions.

## Core Philosophy

### Performance Over Cost
MrPark prioritizes PRECISION and SPEED over cost optimization:
- Uses Claude Sonnet (not Haiku) for all analysis - accuracy is non-negotiable
- Full context analysis preferred over shortcuts
- Real-time responsiveness is the goal

### What is a THREAD?
A thread represents ALL messages in a Gmail conversation thread.
- Grouped by Gmail's native thread_id
- Analyzed as a complete conversation history
- The "last message" is determined by ACTUAL datetime, not alphabetic sort

### What is a TASK?
The ONLY question that matters: **Does Mario need to do something?**

NOT about classification (answer/reminder/follow-up/etc).
NOT about categories or types.
ONLY: Is there an action Mario expects from himself OR others expect from him?

If YES → Create TASK
If NO → Thread is CLOSED

Examples of TASKs:
- Rispondere a una domanda
- Mantenere una promessa ("ti mando il pptx")
- Sistemare qualcosa ("vedo se troviamo un workaround")
- Inviare documenti/informazioni
- Qualsiasi cosa Mario ha detto di fare
- **Customer was expected to write but did not** → Mario needs to remind them

NOT a task:
- Cliente ringrazia e chiude
- Conversazione conclusa positivamente
- Mario ha già fatto tutto quello che doveva

## Technology Stack

### LLM Integration
- **Direct Anthropic SDK** (`anthropic` Python package)
- **Model tiering for cost optimization:**
  - Haiku 4.5: Classification, priority scoring, simple categorization (~$0.92/1K emails)
  - Sonnet 4.5: Enrichment synthesis, draft generation, complex analysis (~$7/1K emails)
  - Opus 4.1: High-stakes executive communications only (<5% of volume)
- **Prompt caching**: Enable for system prompts, contact templates, category definitions (20-30% cost savings)
- **Native function calling**: Use Anthropic's tool_use feature, not external orchestration

### Email Services
- **Gmail API**: Multi-account access via OAuth 2.0, push notifications via Cloud Pub/Sub (research this pattern)
  - **CRITICAL**: Must support multiple Gmail accounts simultaneously (e.g., mario.alemi@gmail.com, mario.alemi@mrcall.ai, mario@company.com)
  - Each account requires separate OAuth authorization
  - Agent selects sending account based on EMAIL_EXCHANGE_HISTORY
  - Token management for multiple accounts in credentials directory
- **SendGrid**: Mass email campaigns (dedicated IP, not shared - we have ~0% missing rate)
  - Webhook server for real-time event notifications (open, click, bounce)
  - Campaign automation based on events (e.g., call 5 min after email open)
- **Future consideration**: Resend as alternative for new deployments

### Phone
- **StarChat API**: Access through user / password or OAuth
- Ability to modify the behaviour of a MrCall assistant for outbound calls
- Ready-to-use endpoint for outbound calls
- **Future** Might be good to think of different MrCall assistants for different task (inbound, outbound, sales, support etc)

### SMS Services (via Vonage API)
- **SMS campaigns**: Send SMS to contacts who have authorized (GDPR compliant)
- **Vonage API**: Direct integration for SMS sending and webhook receipts
- **Webhook integration**: Receive delivery/read receipts for automation triggers
- **Campaign automation**: Same pattern as email (SMS delivered → call after X minutes)
- **Existing service**: Code already available for integration (to be provided to Claude Code)

### Webhook Server (FastAPI)
- **Purpose**: Receive SendGrid webhook events AND SMS webhooks for campaign automation
- **Events**: 
  - Email: open, click, bounce, unsubscribe
  - SMS: delivered, read, failed
- **Actions**: Trigger automated outbound calls, update contact engagement, log analytics
- **Architecture**: Lightweight FastAPI server, can run alongside CLI or standalone
- **Future**: Move this logic into StarChat as native endpoint (cleaner architecture)

### Data Persistence
- **StarChat API**: Primary data store via existing platform APIs
  - Contact variables for enrichment data
  - No separate PostgreSQL instance
  - Leverage existing platform capabilities
- **JSON-based cache**: Simple file-based caching (similar to current MCP Gateway pattern)
  - 30-day TTL (acceptable since we overwrite on significant events like lead→customer)
  - Invalidate on explicit updates
  - Start simple, optimize later if needed

### Contact Enrichment
- **Web search via Anthropic API**: Primary source for unknown contacts (search company website, news)
- **Apollo.io** (future): B2B contact database integration ($49-99/month)
- **LinkedIn** (future): Eventually integrate for professional context
- **NO web scraping**: Legal/technical risks exceed service costs

### Task Management
- **Google Calendar API ONLY**: All scheduling, deadlines, TODOs, follow-ups
- **NO Todoist/Asana/Google Tasks**: Everything stays on calendar for visibility
- Custom metadata in event descriptions using tags (MRPARK:CONTACT_ID, etc.)

### CLI Interface
- **prompt_toolkit**: Interactive CLI input (current choice, keep it)
- **Future evolution**: Consider Textual for dual terminal/browser deployment when moving to dashboard

### CRM Integration
- **Design for multi-CRM support**: System must be CRM-agnostic
- **Pipedrive as first integration** (if needed), but architecture should support:
  - HubSpot
  - Salesforce
  - Monday CRM
  - Custom CRMs
- **Note**: Token-based rate limiting in Pipedrive is concerning for scaling. Abstract CRM layer to swap implementations.

## Architecture

### Single-Agent with Tools Pattern

```
User Input (natural language)
       ↓
┌─────────────────────────────┐
│    Single Claude Agent      │
│    (Sonnet 4.5 primary)     │
│                             │
│  Orchestrates via native    │
│  function calling:          │
│  - Analyzes intent          │
│  - Selects appropriate tool │
│  - Executes tool            │
│  - Synthesizes response     │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│      Tool Catalog           │
├─────────────────────────────┤
│ • query_contacts            │
│ • update_contact            │
│ • search_gmail_history      │
│ • web_search_contact        │
│ • generate_email_draft      │
│ • send_personal_email       │
│ • send_batch_email          │
│ • create_calendar_event     │
│ • list_calendar_events      │
│ • get_campaign_stats        │
│ • initiate_outbound_call    │
└─────────────────────────────┘
           ↓
    Human Review & Approval
           ↓
      Action Execution
```

### Why NOT Multi-Agent

- Sequential workflow (classify → enrich → draft) doesn't benefit from parallelization
- Multi-agent uses 15x tokens vs 4x for single-agent (73% cost increase)
- Supervisor routing introduces hallucination risks
- Debugging complexity increases 3-5x
- Email processing has shared context needs best served by single agent

## Project Structure

Evolve from MCP Gateway structure:

```
mrpark/
├── src/
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── core.py              # Main agent orchestrator
│   │   ├── prompts.py           # System prompts, templates
│   │   └── models.py            # Model selection logic (Haiku/Sonnet/Opus)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py              # Tool interface/protocol
│   │   ├── contacts.py          # StarChat contact operations
│   │   ├── gmail.py             # Gmail API integration (multi-account)
│   │   ├── sendgrid.py          # SendGrid mass email
│   │   ├── vonage_sms.py        # Vonage SMS integration
│   │   ├── calendar.py          # Google Calendar operations
│   │   ├── enrichment.py        # Web search, Apollo (future)
│   │   ├── templates.py         # Gmail draft template management
│   │   ├── crm/
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # CRM interface (abstract)
│   │   │   ├── pipedrive.py     # Pipedrive implementation
│   │   │   └── mock.py          # Mock CRM for testing
│   │   └── starchat.py          # StarChat API client
│   ├── webhook/
│   │   ├── __init__.py
│   │   ├── server.py            # FastAPI webhook server
│   │   ├── handlers.py          # Event handlers (open → call, etc.)
│   │   └── campaigns.py         # Campaign automation rules
│   ├── cache/
│   │   ├── __init__.py
│   │   └── json_cache.py        # Simple JSON file cache (30-day TTL)
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py              # prompt_toolkit CLI interface
│   └── config.py                # Configuration management
├── tests/
│   ├── test_agent.py
│   ├── test_tools.py
│   ├── test_webhook.py
│   └── test_cache.py
├── credentials/                  # OAuth tokens, API keys (gitignored)
├── cache/                        # JSON cache files (gitignored)
├── data/
│   ├── templates.json            # Campaign template references to Gmail drafts
│   └── campaigns.json            # Active campaign rules and automation config
├── pyproject.toml
└── README.md
```

## Contact Data Model

Stored in StarChat `contacts` table via API, in `variables` field. Always remember that the variables must be strings (use json.dumps and json.loads).

```json
{
  "RELATIONSHIP_TYPE": "high_value_customer",
  "PRIORITY_SCORE": "8",
  "LAST_ENRICHED": "2025-11-17T10:30:00Z",
  "HUMANIZED_DESCRIPTION": "CTO at TechCorp, frequent technical discussions about API integration, responsive within 24h",
  "EMAIL_EXCHANGE_HISTORY": "[{\"date\": \"2024-11-29\", \"internal_email\": \"mario.alemi@gmail.com\", \"external_email\": \"pippo@company.com\", \"summary\": \"Initial outreach about MrCall integration\"}, {\"date\": \"2024-12-11\", \"internal_email\": \"mario.alemi@mrcall.ai\", \"external_email\": \"pippo@company.com\", \"summary\": \"Technical deep-dive on API requirements\"}]",
  "SMS_AUTHORIZED": "true",
  "SMS_HISTORY": "[{\"date\": \"2024-12-15\", \"message\": \"New features available! Check your email for details.\", \"status\": \"delivered\", \"campaign_id\": \"product_update_november\"}]",
  "ENRICHMENT_SOURCES": "[\"starchat\", \"gmail_history\", \"web_search\", \"apollo\", \"whatsapp\"]",
  "COMPANY_INFO": "TechCorp - B2B SaaS, Series B, 50-100 employees",
  "LINKEDIN_URL": "https://linkedin.com/in/...",
  "NOTES": "Prefers detailed technical explanations, timezone GMT+1",
  "WHATSAPP_HISTORY": "[]"
}
```

**Limit**: Last 20 significant interactions in EMAIL_EXCHANGE_HISTORY.

**Note on ENRICHMENT_SOURCES**: Includes "starchat" because contact might already exist from phone calls, MrCall customer onboarding, or WhatsApp conversations (future).

**Note on SMS_AUTHORIZED**: Only contacts with `SMS_AUTHORIZED=true` can receive SMS campaigns (GDPR compliance).

## Tool Specifications

### Contact Management

**query_contacts**
```python
def query_contacts(
    filter_expression: str,  # e.g., "PRIORITY_SCORE > 7 AND RELATIONSHIP_TYPE = 'customer'"
    limit: int = 100
) -> List[Contact]:
    """Query StarChat contacts by variables."""
    pass
```

**update_contact**
```python
def update_contact(
    contact_id: str,
    variables: Dict[str, Any]
) -> Contact:
    """Update contact variables in StarChat."""
    pass
```

**enrich_contact**
```python
def enrich_contact(
    email: str,
    force_refresh: bool = False
) -> EnrichmentResult:
    """
    Enrichment pipeline:
    1. Check cache (30-day TTL)
    2. Query StarChat contacts (might be phone contact or MrCall customer)
    3. If stale/missing: Gmail history search
    4. Web search via Anthropic API
    5. Apollo.io lookup (future)
    6. Synthesize with Sonnet
    7. Update StarChat contact
    8. Update cache
    
    Note: StarChat query is essential - contact might exist from:
    - Inbound phone calls to MrCall
    - MrCall customer onboarding
    - Previous manual entry
    - WhatsApp conversations (future)
    """
    pass
```

### Email Operations

**search_gmail_history**
```python
def search_gmail_history(
    query: str,  # Gmail search syntax
    account: str,  # Which Gmail account to search
    max_results: int = 50
) -> List[EmailThread]:
    """Search past conversations across Gmail accounts."""
    pass
```

**generate_email_draft**
```python
def generate_email_draft(
    to: str,
    context: str,  # What to communicate
    tone: str = "professional",  # professional, friendly, formal
    include_history: bool = True
) -> EmailDraft:
    """
    Generate draft using Sonnet 4.5.
    Returns draft for human review, NOT auto-sent.
    """
    pass
```

**send_personal_email**
```python
def send_personal_email(
    draft: EmailDraft,
    from_account: str,  # Auto-selected based on EMAIL_EXCHANGE_HISTORY
    confirm: bool = True  # ALWAYS require confirmation
) -> SendResult:
    """Send via Gmail API after human approval."""
    pass
```

**send_batch_email**
```python
def send_batch_email(
    contacts: List[Contact],
    template_id: str,  # Reference to Gmail draft
    campaign_name: str,
    confirm: bool = True  # ALWAYS require confirmation
) -> BatchSendResult:
    """Send mass email via SendGrid after human approval."""
    pass
```

**create_email_draft_in_gmail**
```python
def create_email_draft_in_gmail(
    subject: str,
    body: str,
    account: str,
    labels: List[str] = ["EMAIL_INTELLIGENCE_TEMPLATE"]
) -> GmailDraft:
    """
    Create draft directly in Gmail via API.
    User can then edit in Gmail UI: add attachments, images, formatting.
    Returns draft ID for future reference.
    """
    pass
```

**list_gmail_drafts**
```python
def list_gmail_drafts(
    account: str,
    label_filter: str = "EMAIL_INTELLIGENCE_TEMPLATE"
) -> List[GmailDraft]:
    """List drafts in Gmail, optionally filtered by label."""
    pass
```

**save_draft_as_campaign_template**
```python
def save_draft_as_campaign_template(
    draft_id: str,
    template_id: str,
    account: str,
    description: str = ""
) -> CampaignTemplate:
    """
    Save reference to Gmail draft as campaign template.
    The draft stays in Gmail - email-intelligence just stores the reference.
    
    Template metadata stored in templates.json:
    {
        "product_update_november": {
            "gmail_draft_id": "r123456789",
            "gmail_account": "mario.alemi@mrcall.ai",
            "description": "November product update with new features",
            "created_at": "2025-11-17T10:00:00Z",
            "last_used": "2025-11-17T14:30:00Z"
        }
    }
    """
    pass
```

**get_template_content**
```python
def get_template_content(
    template_id: str
) -> EmailContent:
    """
    Fetch current content of template from Gmail draft.
    Supports variable substitution: {{contact.FIRST_NAME=Customer}}
    
    Content includes:
    - Subject line
    - Body (HTML or plain text)
    - Attachments (references)
    - Inline images
    """
    pass
```

### Template Management via Gmail Drafts

**Why Gmail drafts instead of local files:**
- Full email client features (attachments, inline images, HTML formatting, signatures)
- Visual editing in familiar Gmail UI
- No new infrastructure to maintain
- Agent reads/references via Gmail API

**Workflow for creating campaign templates:**

```
User: "draft a product update email"

Agent: [Generates initial draft content]
"I've created a draft in your Gmail (mario.alemi@mrcall.ai).
Subject: MrCall November Update - New Features

You can now:
- Edit the content in Gmail
- Add attachments (PDF brochures, etc.)
- Insert images
- Adjust formatting

When ready, tell me to save it as a campaign template."

User: [Opens Gmail, edits draft, adds product screenshot, attaches PDF]

User: "save this draft as template product_update_november"

Agent: [Reads draft ID, saves reference]
"Template 'product_update_november' saved. 
It references your Gmail draft with:
- 1 inline image (product_screenshot.png)
- 1 attachment (features_brochure.pdf)
- HTML formatting preserved

Use with: 'send campaign product_update_november to [contacts]'"

User: "send campaign product_update_november to contacts with MAIL_CAMPAIGN=true"

Agent: [Fetches draft from Gmail, applies {{variable}} substitution, sends via SendGrid]
"Ready to send to 1,247 contacts.
Template includes: inline image + PDF attachment
Variables to personalize: {{contact.FIRST_NAME}}, {{contact.COMPANY_INFO}}

[CONFIRM SEND] [PREVIEW] [CANCEL]"
```

**Variable substitution in Gmail drafts:**
```
Subject: {{campaign.subject=MrCall Update}} for {{contact.COMPANY_INFO=Your Company}}

Hi {{contact.FIRST_NAME=there}},

I wanted to share some exciting updates...
```

**Template identification in Gmail:**
- Label: `EMAIL_INTELLIGENCE_TEMPLATE`
- Draft ID stored in local `templates.json`
- Subject line can include template name for easy finding

**Future enhancements:**
- A/B testing with multiple draft variants
- Template versioning
- Analytics on which templates perform best
- Rich template editor (web dashboard phase)

**get_campaign_stats**
```python
def get_campaign_stats(
    campaign_id: str
) -> CampaignStats:
    """Poll SendGrid API for open/click/bounce stats."""
    pass
```

### Campaign Automation

**configure_campaign_automation**
```python
def configure_campaign_automation(
    campaign_id: str,
    rules: List[AutomationRule]
) -> CampaignConfig:
    """
    Configure automated actions for campaign events.
    
    Example rules:
    - On email open: call contact after 5 minutes
    - On link click: update contact priority
    - On bounce: mark contact as invalid
    - On no open after 3 days: send reminder
    
    Rules stored in campaigns.json with assistant configuration.
    """
    pass
```

**configure_outbound_assistant**
```python
def configure_outbound_assistant(
    campaign_id: str,
    message_context: str,
    tone: str = "professional",
    max_duration: int = 120  # seconds
) -> AssistantConfig:
    """
    Configure MrCall assistant behavior for campaign calls.
    Uses existing mrcall_configurator capabilities.
    
    Example: "Hi, I'm calling from MrCall. I noticed you just opened 
    our product update email. Do you have a moment to discuss how 
    these new features could help your business?"
    """
    pass
```

### Webhook Server (FastAPI)

**Webhook endpoint for SendGrid and SMS events:**

```python
# src/webhook/server.py
from fastapi import FastAPI, Request
from datetime import datetime, timedelta
import asyncio

app = FastAPI()

@app.post("/webhooks/sendgrid")
async def handle_sendgrid_webhook(request: Request):
    """
    Receive SendGrid events and trigger automated actions.
    
    Event types:
    - open: Contact opened email
    - click: Contact clicked link
    - bounce: Email bounced
    - unsubscribe: Contact unsubscribed
    """
    events = await request.json()
    
    for event in events:
        await process_sendgrid_event(event)
    
    return {"status": "ok"}

@app.post("/webhooks/sms")
async def handle_sms_webhook(request: Request):
    """
    Receive SMS delivery/read events and trigger automated actions.
    
    Event types:
    - delivered: SMS successfully delivered
    - read: SMS read by recipient (if supported by carrier)
    - failed: SMS delivery failed
    """
    event = await request.json()
    await process_sms_event(event)
    return {"status": "ok"}

async def process_sendgrid_event(event: dict):
    """Process single SendGrid event based on campaign rules."""
    event_type = event.get("event")
    email = event.get("email")
    campaign_id = event.get("campaign_id")  # Custom field in SendGrid
    
    # Load campaign rules
    rules = load_campaign_rules(campaign_id)
    
    if event_type == "open" and rules.get("call_on_open"):
        delay = rules.get("call_delay_seconds", 300)  # Default 5 min
        asyncio.create_task(
            delayed_outbound_call(email, campaign_id, delay)
        )
    
    # Update contact engagement in StarChat
    update_contact_engagement(email, event_type, campaign_id)

async def process_sms_event(event: dict):
    """Process SMS event based on campaign rules."""
    event_type = event.get("status")  # delivered, read, failed
    phone = event.get("phone")
    campaign_id = event.get("campaign_id")
    
    # Load SMS campaign rules
    rules = load_sms_campaign_rules(campaign_id)
    
    if event_type == "delivered" and rules.get("call_on_delivery"):
        delay = rules.get("call_delay_seconds", 120)  # Default 2 min
        asyncio.create_task(
            delayed_outbound_call_by_phone(phone, campaign_id, delay)
        )
    
    # Update contact SMS history in StarChat
    update_contact_sms_status(phone, event_type, campaign_id)

async def delayed_outbound_call(email: str, campaign_id: str, delay: int):
    """Wait then initiate outbound call."""
    await asyncio.sleep(delay)
    
    # Get contact from StarChat
    contact = get_contact_by_email(email)
    if not contact:
        return
    
    # Get campaign assistant config
    assistant_config = get_campaign_assistant_config(campaign_id)
    
    # Initiate call via StarChat API
    initiate_outbound_call(
        contact_id=contact.id,
        message_context=assistant_config.message,
        business_id=assistant_config.business_id
    )

async def delayed_outbound_call_by_phone(phone: str, campaign_id: str, delay: int):
    """Wait then initiate outbound call (for SMS campaigns)."""
    await asyncio.sleep(delay)
    
    # Get contact from StarChat by phone
    contact = get_contact_by_phone(phone)
    if not contact:
        return
    
    # Get campaign assistant config
    assistant_config = get_campaign_assistant_config(campaign_id)
    
    # Initiate call via StarChat API
    initiate_outbound_call(
        contact_id=contact.id,
        message_context=assistant_config.message,
        business_id=assistant_config.business_id
    )
```

**Campaign automation workflow:**

```
User: "create campaign product_launch with automation"

Agent: "Let's configure the campaign automation:

1. Template: [select Gmail draft]
2. Recipients: [define filter]
3. Automation rules:
   - On email open: Call after how many minutes? [5]
   - Configure assistant message for calls? [yes]
   
What should the assistant say when calling?"

User: "Say that we noticed they opened our email and ask if they have 
questions about the new features"

Agent: [Configures assistant via mrcall_configurator]
"Campaign configured:
- Template: product_launch_draft
- Recipients: 500 contacts with LEAD=true
- Automation: Call 5 min after open
- Assistant: Configured for product inquiry

Start webhook server and launch campaign? [YES] [NO]"

User: "yes"

Agent: 
"✓ Webhook server started on port 8000
✓ SendGrid webhook URL configured: https://your-domain/webhooks/sendgrid
✓ Campaign 'product_launch' sent to 500 contacts
✓ Monitoring for opens...

I'll automatically call contacts 5 minutes after they open.
Check status anytime: 'how is product_launch campaign doing?'"
```

**HITL distinction for campaigns:**

- **Personal emails**: HITL for every send (draft → approve → send)
- **Campaign emails**: HITL for template + rules (approve template → approve automation rules → automated execution)
- **Campaign calls**: HITL for assistant behavior (configure what to say → automated triggering based on events)

This allows scaling while maintaining control over *what* is communicated, not *when* it's sent.

### Calendar & Task Management

**create_calendar_event**
```python
def create_calendar_event(
    title: str,
    start_time: datetime,
    end_time: datetime,
    description: str,
    contact_id: Optional[str] = None,
    email_id: Optional[str] = None,
    task_type: str = "work"  # work, followup_done, followup_pending
) -> CalendarEvent:
    """
    Create Google Calendar event with MRPARK tags in description.
    Tags:
    - MRPARK:CONTACT_ID=1234
    - MRPARK:EMAIL_ID=abc123
    - MRPARK:TASK_TYPE=work
    """
    pass
```

**list_calendar_events**
```python
def list_calendar_events(
    start_date: datetime,
    end_date: datetime,
    filter_mrpark: bool = True
) -> List[CalendarEvent]:
    """List calendar events, optionally filtering for MRPARK tags."""
    pass
```

**generate_daily_digest**
```python
def generate_daily_digest() -> DailyDigest:
    """
    Read today's calendar events with MRPARK tags.
    Correlate with StarChat contacts.
    Generate actionable digest:
    - Tasks to work on
    - Follow-ups to send
    - People to contact
    """
    pass
```

### Enrichment

**web_search_contact**
```python
def web_search_contact(
    name: str,
    email: str,
    company: Optional[str] = None
) -> WebSearchResult:
    """
    Use Anthropic API to search web for contact information.
    Search company website, news, professional info.
    NOT scraping - using search APIs.
    """
    pass
```

### Telephony (StarChat Integration)

**initiate_outbound_call**
```python
def initiate_outbound_call(
    contact_id: str,
    message_context: str,  # What the assistant should communicate
    business_id: Optional[str] = None
) -> CallResult:
    """
    Configure MrCall assistant for this specific call.
    Initiate outbound call via StarChat API.
    """
    pass
```

### Future: WhatsApp Integration (via StarChat)

**send_whatsapp_message** (Future)
```python
def send_whatsapp_message(
    contact_id: str,
    message: str,
    template_id: Optional[str] = None
) -> WhatsAppResult:
    """
    Send WhatsApp message via StarChat WhatsApp Business API.
    Supports both template messages and free-form (within 24h window).
    """
    pass
```

**get_whatsapp_history** (Future)
```python
def get_whatsapp_history(
    contact_id: str,
    limit: int = 50
) -> List[WhatsAppMessage]:
    """
    Retrieve WhatsApp conversation history from StarChat.
    Integrates with EMAIL_EXCHANGE_HISTORY for unified communication view.
    """
    pass
```

### SMS Integration (via Vonage API)

**send_sms**
```python
def send_sms(
    contact_id: str,
    message: str,
    campaign_id: Optional[str] = None
) -> SMSResult:
    """
    Send SMS via Vonage API.
    Only to contacts who have authorized SMS (GDPR compliant).
    Returns message_id for tracking.
    """
    pass
```

**send_bulk_sms**
```python
def send_bulk_sms(
    contacts: List[Contact],
    message_template: str,
    campaign_id: str,
    confirm: bool = True
) -> BulkSMSResult:
    """
    Send SMS campaign to multiple contacts via Vonage.
    Template supports variable substitution: {{crm.contact.variables.FIRST_NAME}}
    Vonage webhooks will trigger automation (e.g., call on delivery/read).
    
    Note: Existing Vonage SMS service code will be integrated here.
    """
    pass
```

**configure_sms_campaign_automation**
```python
def configure_sms_campaign_automation(
    campaign_id: str,
    rules: List[SMSAutomationRule]
) -> SMSCampaignConfig:
    """
    Configure automated actions for SMS campaign events.
    
    Example rules:
    - On SMS delivered: call contact after 2 minutes
    - On SMS read: update contact engagement score
    - On SMS failed: retry or mark contact invalid
    """
    pass
```

## CLI Interface Design

Interactive conversational interface using prompt_toolkit:

```
$ python -m mrpark.cli.main

MrPark - Email Intelligence Assistant
Type 'help' for commands, 'quit' to exit

You: show me today's digest
Assistant: Based on your calendar, you have:
- 9:00-11:00: Work on API documentation for TechCorp (CONTACT_ID: 1234)
- 14:00: Follow-up deadline for DataInc proposal

Contacts to reach out to:
[ ] Marco Rossi - sent proposal 5 days ago, no response
[ ] Laura Bianchi - promised demo scheduling, due today

Shall I draft follow-up emails for these?

You: yes, draft for Marco Rossi
Assistant: [Searching Gmail history for Marco Rossi...]
[Found 3 previous exchanges]

Draft for Marco Rossi (marco.rossi@datainc.it):

Subject: Re: MrCall Integration Proposal - Following Up

Hi Marco,

Hope you're doing well. I wanted to follow up on the integration proposal 
I sent last week. Have you had a chance to review it with your team?

I'm happy to schedule a call to discuss any questions or walk through 
the technical details. Would Thursday or Friday afternoon work for you?

Best regards,
Mario

---
Send from: mario.alemi@mrcall.ai (last used for this contact)
Tone: Professional, friendly follow-up
Priority: Medium (lead, 5 days since last contact)

[APPROVE] [EDIT] [DISCARD]

You: approve
Assistant: Email sent successfully to marco.rossi@datainc.it
Updated contact: last_contacted = 2025-11-17
Created calendar reminder: "Check Marco Rossi response" in 3 days

You: I just got an email from someone@newcompany.com, who is this person?
Assistant: [Checking StarChat contacts... not found]
[Searching Gmail history... no previous exchanges]
[Searching web for "someone@newcompany.com" and "NewCompany"...]

Found information:
- NewCompany is a B2B SaaS startup in Milan, Series A ($5M), 25 employees
- Company website: https://newcompany.com - focus on logistics optimization
- LinkedIn shows "Someone Name" is Head of Partnerships

Suggested classification:
- RELATIONSHIP_TYPE: lead (first contact, B2B relevant)
- PRIORITY_SCORE: 6 (potential partner, not existing customer)

Save this to contacts? [YES] [NO]

You: yes, and schedule 30 minutes tomorrow to research them properly
Assistant: Contact saved to StarChat.
Calendar event created: "Research NewCompany" tomorrow 10:00-10:30
Tags: MRPARK:CONTACT_ID=5678, MRPARK:TASK_TYPE=work

You: send campaign "product_update_november" to all contacts with MAIL_CAMPAIGN=true
Assistant: [Querying contacts with MAIL_CAMPAIGN=true...]
Found 1,247 contacts matching criteria.

Campaign "product_update_november" will send:
- Template: November Product Update
- Recipients: 1,247 contacts
- Via: SendGrid (dedicated IP)
- Estimated send time: ~15 minutes

⚠️  This is a mass email operation. 
Preview first 3 recipients:
1. john@company1.com (customer, priority 8)
2. sarah@company2.com (lead, priority 5)
3. mike@company3.com (customer, priority 7)

[CONFIRM SEND] [PREVIEW TEMPLATE] [CANCEL]

You: preview template
[Shows template...]

You: confirm send
Assistant: Campaign "product_update_november" queued for sending.
SendGrid batch ID: sg_batch_12345
Estimated completion: 15 minutes

I'll notify you when complete. You can check status anytime with:
"how did product_update_november campaign go?"
```

## Agent Implementation

### Core Agent Structure

```python
import anthropic
from typing import Any, Dict, List

class MrParkAgent:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.tools = self._register_tools()
        self.conversation_history = []
        
    def _register_tools(self) -> List[Dict]:
        """Register all tools for native function calling."""
        return [
            {
                "name": "query_contacts",
                "description": "Query StarChat contacts by filter expression",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter_expression": {
                            "type": "string",
                            "description": "Filter like 'PRIORITY_SCORE > 7'"
                        },
                        "limit": {"type": "integer", "default": 100}
                    },
                    "required": ["filter_expression"]
                }
            },
            {
                "name": "enrich_contact",
                "description": "Enrich contact data from multiple sources",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "force_refresh": {"type": "boolean", "default": False}
                    },
                    "required": ["email"]
                }
            },
            # ... more tools
        ]
    
    def process_message(self, user_message: str) -> str:
        """Process user message with tool use."""
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        # Select model based on task complexity
        model = self._select_model(user_message)
        
        response = self.client.messages.create(
            model=model,
            max_tokens=4096,
            system=self._get_system_prompt(),
            tools=self.tools,
            messages=self.conversation_history
        )
        
        # Handle tool use
        while response.stop_reason == "tool_use":
            tool_results = self._execute_tools(response.content)
            self.conversation_history.append({
                "role": "assistant",
                "content": response.content
            })
            self.conversation_history.append({
                "role": "user",
                "content": tool_results
            })
            
            response = self.client.messages.create(
                model=model,
                max_tokens=4096,
                system=self._get_system_prompt(),
                tools=self.tools,
                messages=self.conversation_history
            )
        
        assistant_message = response.content[0].text
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })
        
        return assistant_message
    
    def _select_model(self, message: str) -> str:
        """Select optimal model based on task."""
        # Simple heuristics - can be enhanced
        if any(word in message.lower() for word in ["classify", "categorize", "priority"]):
            return "claude-3-5-haiku-20241022"  # Fast, cheap classification
        elif any(word in message.lower() for word in ["draft", "write", "compose", "enrich"]):
            return "claude-sonnet-4-20250514"  # Quality generation
        elif any(word in message.lower() for word in ["executive", "board", "critical"]):
            return "claude-opus-4-20250514"  # High-stakes only
        else:
            return "claude-sonnet-4-20250514"  # Default
    
    def _get_system_prompt(self) -> str:
        """System prompt with caching enabled."""
        return """You are MrPark, an Email Intelligence Assistant helping a sales professional manage communications and follow-ups.

Your capabilities:
- Analyze and classify email senders by relationship and priority
- Enrich unknown contacts via web search
- Draft professional email responses
- Schedule tasks and deadlines on Google Calendar
- Track commitments and follow-ups
- Send mass email campaigns via SendGrid

CRITICAL RULES:
1. ALWAYS require human approval before sending any email
2. ALWAYS require human approval before making calendar changes
3. Present information clearly with actionable options
4. When uncertain, ask for clarification
5. Track all commitments and deadlines mentioned in conversations

You have access to:
- Multiple Gmail accounts for the user
- StarChat contact database
- SendGrid for mass emails
- Google Calendar for scheduling
- Web search for contact enrichment
- MrCall phone assistant for outbound calls

When drafting emails:
- Match tone to relationship type
- Reference conversation history when relevant
- Suggest which email account to send from based on history
- Always show draft for approval

When enriching contacts:
- Check cache first (30-day TTL)
- Search Gmail history
- Search web for company/professional info
- Synthesize findings into actionable profile
- Save to StarChat contacts"""
    
    def _execute_tools(self, content: List) -> List[Dict]:
        """Execute tool calls and return results."""
        results = []
        for block in content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                
                # Route to appropriate tool implementation
                result = self._call_tool(tool_name, tool_input)
                
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result)
                })
        return results
    
    def _call_tool(self, name: str, input: Dict) -> Any:
        """Route tool call to implementation."""
        tool_map = {
            "query_contacts": self._tool_query_contacts,
            "enrich_contact": self._tool_enrich_contact,
            "search_gmail_history": self._tool_search_gmail,
            "generate_email_draft": self._tool_generate_draft,
            "create_calendar_event": self._tool_create_event,
            # ... more tools
        }
        
        if name in tool_map:
            return tool_map[name](**input)
        else:
            return f"Unknown tool: {name}"
```

### Prompt Caching for Cost Optimization

```python
def _get_system_prompt_with_cache(self) -> List[Dict]:
    """Use prompt caching for static content."""
    return [
        {
            "type": "text",
            "text": self._get_system_prompt(),
            "cache_control": {"type": "ephemeral"}  # Cache for session
        }
    ]
```

## Implementation Phases

### Phase 1: Foundation (Week 1-2)

**Objective**: Basic agent structure with Gmail reading and contact storage

**Tasks**:
1. Set up project structure (evolve from MCP Gateway)
2. Implement direct Anthropic SDK integration
3. Basic prompt_toolkit CLI loop
4. Gmail API OAuth flow for single account
5. Gmail reading and search tools
6. StarChat API client for contact CRUD
7. Simple JSON cache implementation
8. Basic contact enrichment (Gmail history only)

**Deliverables**:
- Agent can read Gmail
- Agent can search email history
- Agent can store/retrieve contacts from StarChat
- Basic CLI interaction working

**Commands to support**:
- "show me emails from [person]"
- "who is [email]?" (basic, from Gmail history)
- "save this contact"

### Phase 2: Enrichment & Classification (Week 3-4)

**Objective**: Intelligent contact enrichment with web search

**Tasks**:
1. Web search tool using Anthropic API
2. Contact classification logic (relationship type, priority score)
3. Enrichment pipeline (cache → Gmail → web search)
4. HUMANIZED_DESCRIPTION generation with Sonnet
5. EMAIL_EXCHANGE_HISTORY tracking
6. Model tiering implementation (Haiku for classification, Sonnet for synthesis)
7. 30-day TTL cache management

**Deliverables**:
- Full contact enrichment pipeline
- Priority scoring working
- Cost-optimized model selection
- Rich contact profiles

**Commands to support**:
- "who is [email]?" (full enrichment)
- "classify this contact"
- "show high priority contacts"
- "refresh contact info for [person]"

### Phase 3: Email Drafting & Calendar (Week 5-6)

**Objective**: Draft emails and manage calendar tasks

**Tasks**:
1. Email draft generation with context
2. Tone matching based on relationship
3. Account selection logic
4. Google Calendar API integration
5. Calendar event creation with MRPARK tags
6. Daily digest generation
7. Commitment tracking from conversations
8. HITL approval flow for all actions

**Deliverables**:
- Email drafts with human approval
- Calendar event scheduling
- Daily digest working
- Task tracking via calendar

**Commands to support**:
- "draft email to [person] about [topic]"
- "schedule [task] for [time]"
- "show today's digest"
- "remind me to follow up with [person] in [days]"
- "I promised [person] to [task] by [date]"

### Phase 4: Gmail Multi-Account & Sending (Week 7-8)

**Objective**: Multi-account Gmail and actual email sending

**Tasks**:
1. Multi-account Gmail OAuth management
2. Account selection based on EMAIL_EXCHANGE_HISTORY
3. Gmail send implementation
4. Push notifications via Cloud Pub/Sub (research required)
5. Send confirmation workflow
6. Sent email tracking in StarChat
7. Automatic calendar reminder after send

**Deliverables**:
- Multiple Gmail accounts connected
- Emails sent after approval
- Push notifications for new emails (if feasible)
- Automatic follow-up scheduling

**Commands to support**:
- "send the draft" (after approval)
- "use [account] for this"
- "connect another Gmail account"

### Phase 5: Mass Email & Campaigns (Week 9-10)

**Objective**: SendGrid integration for mass emails

**Tasks**:
1. SendGrid API integration
2. Template management via Gmail drafts
3. Recipient filtering with StarChat queries
4. Batch send with confirmation
5. Campaign stats polling
6. Contact variable for campaign tracking (MAIL_CAMPAIGN, etc.)
7. Unsubscribe handling

**Deliverables**:
- Mass email campaigns working
- Campaign statistics tracking
- Template-based sends via Gmail drafts
- Safe batch operations with approval

**Commands to support**:
- "draft campaign email"
- "save draft as template [name]"
- "send campaign [name] to contacts with [filter]"
- "how did [campaign] perform?"
- "show campaign stats"

### Phase 5.5: Campaign Automation & Webhook Server (Week 11-12)

**Objective**: Automated actions based on email engagement

**Tasks**:
1. FastAPI webhook server implementation
2. SendGrid webhook configuration
3. Campaign automation rules engine
4. Delayed outbound call triggering
5. Assistant configuration for campaign calls
6. Contact engagement tracking
7. Campaign monitoring dashboard (CLI)

**Deliverables**:
- Webhook server receiving SendGrid events
- Automated calls on email open (configurable delay)
- Assistant behavior per campaign
- Real-time engagement tracking

**Commands to support**:
- "create campaign with automation"
- "configure call on email open after [X] minutes"
- "what should assistant say for this campaign?"
- "start webhook server"
- "show live campaign activity"

**Future enhancement**: Move webhook logic into StarChat as native endpoint (cleaner architecture, single deployment)

### Phase 6: CRM Integration (Week 11-12)

**Objective**: Abstract CRM layer with Pipedrive first

**Tasks**:
1. CRM abstraction interface
2. Pipedrive implementation
3. Mock CRM for testing
4. CRM data enrichment in contact profile
5. Sync logic (StarChat ↔ CRM)
6. Rate limit management for Pipedrive tokens
7. Error handling for API limits

**Deliverables**:
- Pipedrive data in contact profiles
- CRM-agnostic architecture
- Rate limit protection
- Fallback when CRM unavailable

**Commands to support**:
- "check CRM for [contact]"
- "what deals do we have with [company]?"
- "sync CRM data"

### Phase 7: Telephony Integration (Week 13-14)

**Objective**: Outbound calls via MrCall

**Tasks**:
1. MrCall assistant configuration via StarChat API
2. Outbound call initiation
3. Call context preparation (what to say)
4. Call result tracking
5. Integration with contact history

**Deliverables**:
- Phone calls via assistant
- Call tracking in contact history
- Message configuration

**Commands to support**:
- "call [person] and tell them [message]"
- "schedule call with [person]"
- "what was the result of call to [person]?"

### Phase 8: Polish & Optimization (Week 15-16)

**Objective**: Production hardening

**Tasks**:
1. Comprehensive error handling
2. Retry logic for API failures
3. Logging and monitoring
4. Performance optimization
5. Prompt refinement based on usage
6. Cost tracking and reporting
7. User preference learning
8. Documentation

**Deliverables**:
- Robust error handling
- Cost reports
- Performance metrics
- Complete documentation

## Configuration

```python
# config.py

from pydantic import BaseSettings

class Settings(BaseSettings):
    # Anthropic
    ANTHROPIC_API_KEY: str
    DEFAULT_MODEL: str = "claude-sonnet-4-20250514"
    CLASSIFICATION_MODEL: str = "claude-3-5-haiku-20241022"
    EXECUTIVE_MODEL: str = "claude-opus-4-20250514"
    
    # Gmail
    GMAIL_CREDENTIALS_PATH: str = "credentials/gmail_oauth.json"
    GMAIL_TOKEN_PATH: str = "credentials/gmail_tokens/"
    GMAIL_ACCOUNTS: list = []  # List of authorized accounts
    
    # SendGrid
    SENDGRID_API_KEY: str
    SENDGRID_FROM_EMAIL: str
    SENDGRID_WEBHOOK_SECRET: str = ""  # For webhook signature verification
    
    # Vonage SMS
    VONAGE_API_KEY: str = ""
    VONAGE_API_SECRET: str = ""
    VONAGE_FROM_NUMBER: str = ""
    
    # Webhook Server
    WEBHOOK_HOST: str = "0.0.0.0"
    WEBHOOK_PORT: int = 8000
    WEBHOOK_PUBLIC_URL: str = ""  # Public URL for SendGrid/Vonage to call
    
    # Google Calendar
    CALENDAR_CREDENTIALS_PATH: str = "credentials/calendar_oauth.json"
    CALENDAR_ID: str = "primary"
    
    # StarChat
    STARCHAT_API_URL: str
    STARCHAT_API_KEY: str
    STARCHAT_BUSINESS_ID: str
    
    # Cache
    CACHE_DIR: str = "cache/"
    CACHE_TTL_DAYS: int = 30
    
    # Campaign Data
    CAMPAIGNS_FILE: str = "data/campaigns.json"
    TEMPLATES_FILE: str = "data/templates.json"
    
    # CRM (Optional)
    PIPEDRIVE_API_TOKEN: str = ""
    PIPEDRIVE_ENABLED: bool = False
    
    # Apollo (Future)
    APOLLO_API_KEY: str = ""
    APOLLO_ENABLED: bool = False
    
    class Config:
        env_file = ".env"
```

## Testing Strategy

### Unit Tests
- Tool implementations (mock external APIs)
- Cache logic
- Contact classification
- Model selection

### Integration Tests
- Gmail API (use test account)
- StarChat API (use test business)
- Calendar API (use test calendar)

### End-to-End Tests
- Full enrichment pipeline
- Email draft to send flow
- Campaign execution
- Daily digest generation

## Security Considerations (Development Roadmap)

**Phase 1-4** (Single user, you):
- OAuth tokens encrypted at rest
- API keys in environment variables
- Basic audit logging

**Phase 5+** (When needed):
- Input sanitization for prompt injection
- Rate limiting per user
- RBAC for multi-user
- Comprehensive audit trail
- GDPR compliance (data export, deletion)

## Success Metrics

**Functional**:
- Contact enrichment accuracy (manual review)
- Email draft quality (acceptance rate)
- Calendar scheduling correctness
- Campaign delivery rates

**Performance**:
- Average response time < 3 seconds
- Cost per 1000 emails processed < €10
- Cache hit rate > 80%
- API error rate < 1%

**User Experience**:
- Time saved per email (estimate)
- Follow-ups not missed (track)
- Contact information quality (completeness score)

## Dependencies

```toml
[project]
name = "mrpark"
version = "0.1.0"
description = "MrPark - Multi-Channel Sales Intelligence System for Sales Professionals"
dependencies = [
    "anthropic>=0.39.0",
    "google-auth-oauthlib>=1.2.0",
    "google-api-python-client>=2.108.0",
    "httpx>=0.25.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.0.0",
    "prompt-toolkit>=3.0.50",
    "python-dotenv>=1.0.0",
    "fastapi>=0.104.0",
    "uvicorn>=0.24.0",
    "vonage>=3.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
]
```

## Migration from MCP Gateway

1. **Keep**: Project structure, configuration pattern, StarChat API client
2. **Remove**: MCP protocol implementation, multi-agent orchestration
3. **Add**: Direct Anthropic SDK, native function calling, new tool implementations
4. **Refactor**: CLI to use prompt_toolkit conversational loop
5. **Rename**: Project to MrPark

The MCP Gateway codebase provides a solid foundation. The migration focuses on simplifying the architecture while adding email-specific intelligence under the MrPark brand.

## Current Status (November 2025)

### ✅ Implemented
- **Email Intelligence**: Thread caching with Haiku, smart search (From/To/Cc), HTML body parsing
- **Task Management**: Person-centric task aggregation with Sonnet (one person = one task)
- **Draft Management**: Create, edit (nano), list, update Gmail drafts
- **Pipedrive Integration**: Search contacts, retrieve deals with pipeline/stage filters
- **Google Calendar**: Event management and scheduling
- **StarChat Integration**: Contact storage and enrichment
- **Email Style Preferences**: Configurable via `.env` (no emoji, plain text, etc.)
- **Contact Identification**: MY_EMAILS with wildcard support (*@domain.com)

### 🚧 In Progress
- Testing task system with real contacts
- Refining Sonnet prompts for task analysis
- Performance optimization for large contact bases

## Future Enhancements

### Phase 9: Reasoning History & Pattern Recognition

**Objective**: Add persistent reasoning memory to tasks

**Why**: Currently, Sonnet analyzes tasks from scratch each time. With reasoning history, MrPark "remembers" past decisions and actions.

**Example Use Case**:
```json
{
  "task_id": "contact_luisa",
  "reasoning_history": [
    {
      "date": "2025-11-19T10:00:00Z",
      "reasoning": "Cliente ansiosa, rischio perdita. Decision: chiamare ASAP.",
      "action_taken": "Chiamata rassicurante effettuata",
      "user": "mario"
    },
    {
      "date": "2025-11-19T15:30:00Z",
      "reasoning": "Ancora confusa su WhatsApp. Decision: inviare guida step-by-step.",
      "action_taken": "Email con screenshot inviata",
      "user": "mario"
    },
    {
      "date": "2025-11-20T09:00:00Z",
      "reasoning": "Email letta ma non risposto. Follow-up necessario se silenzio continua.",
      "action_taken": null,
      "user": "mrpark"
    }
  ]
}
```

**Benefits**:
- Continuity: Don't repeat actions already tried
- Context: Sonnet knows full history when suggesting next step
- Learning: Patterns emerge ("Luisa prefers calls over email")
- Audit trail: Complete decision history per contact

**Implementation**:
1. Add `reasoning_history` array to task object
2. Tool: `add_reasoning(contact_email, reasoning, action_taken)`
3. Update Sonnet prompt to include history in context
4. Auto-generate reasoning on task updates

**Estimated effort**: 2-3 days
**Cost impact**: Minimal (history in prompt, no extra API calls)

---

### Phase 10: Reasoning Bank (Pattern Learning)

**Objective**: Learn from past decisions and detect patterns across contacts

**Why**: Reasoning history (Phase 9) tracks decisions per contact. Reasoning Bank analyzes patterns **across all contacts**.

**What is Reasoning Bank**:
- SQLite-based persistent storage for reasoning patterns
- Learns from successful/failed strategies
- Detects patterns: "What works with anxious clients?"
- Cross-contact intelligence

**Example Patterns**:
```sql
-- Pattern detection
SELECT reasoning, action_taken, COUNT(*) as frequency
FROM reasoning_history
WHERE reasoning LIKE '%ansios%' AND action_taken IS NOT NULL
GROUP BY action_taken
ORDER BY frequency DESC;

-- Result:
-- "Chiamata telefonica" -> 8 successes
-- "Email rassicurante" -> 3 successes
-- "Reminder automatico" -> 1 failure
```

**Use Cases**:
1. **Strategy Recommendation**: "For anxious clients, calling works 8/9 times vs email 3/9"
2. **Risk Detection**: "Contacts silent >7 days after migration have 70% churn risk"
3. **Pattern Matching**: "Luisa's situation similar to 3 past contacts - here's what worked"
4. **Learning Over Time**: MrPark gets better at suggestions based on your history

**Implementation**:
```python
# Schema
CREATE TABLE reasoning_patterns (
    id INTEGER PRIMARY KEY,
    pattern_type TEXT,  -- 'anxious_client', 'migration_issue', etc.
    trigger_conditions TEXT,  -- JSON: {"sentiment": "anxious", "context": "migration"}
    successful_actions TEXT,  -- JSON: [{"action": "call", "success_rate": 0.89}]
    sample_contacts TEXT,  -- JSON: ["contact_123", "contact_456"]
    confidence REAL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

# Query patterns when analyzing task
SELECT * FROM reasoning_patterns
WHERE trigger_conditions LIKE '%anxious%'
ORDER BY confidence DESC
LIMIT 5;
```

**Integration with Sonnet**:
When analyzing a task, TaskManager:
1. Detects situation (anxious client, migration issue, etc.)
2. Queries ReasoningBank for matching patterns
3. Passes patterns to Sonnet in context
4. Sonnet suggests action based on **what worked before**

**Example Sonnet Context**:
```
Analyzing: Luisa Boni (anxious about migration)

Relevant Patterns from ReasoningBank:
- Pattern #42: "Anxious migration clients" (confidence: 0.85)
  - Successful action: "Phone call + screen share" (8/9 success rate)
  - Failed action: "Email only" (1/3 success rate)
  - Similar contacts: Mario Rossi, Laura Verdi (both resolved via call)

Recommendation: Based on pattern #42, suggest phone call with screen share.
```

**Benefits**:
- 🧠 **Cross-contact learning** (not just per-contact memory)
- 📊 **Data-driven recommendations** (not just LLM intuition)
- 🎯 **Pattern detection** (identify risk patterns early)
- 📈 **Continuous improvement** (gets smarter over time)

**When to Implement**:
- After reasoning history is working (Phase 9)
- When you have 50+ contacts with reasoning data
- When you notice recurring patterns in your work

**Estimated effort**: 1 week
**Cost impact**: Minimal (SQLite local, no API calls)

---

### Phase 11: Vector Search & Semantic Memory

**Objective**: Scale to 10K+ contacts with semantic search

**Why**: Current JSON cache works for ~200 contacts. For larger scales, need vector embeddings.

**Approach**: Three options

#### Option A: Lightweight (DIY)
Use Anthropic's embedding API directly:
```python
# Generate embeddings for contacts
embedding = anthropic.embeddings.create(
    input=f"{contact.name} {contact.view}",
    model="voyage-2"
)

# Store in simple vector index (numpy/faiss)
# Search by similarity
```

**Pros**: Simple, no dependencies
**Cons**: Manual implementation, limited features

#### Option B: Reasoning Bank + Vector Extensions
Extend SQLite with vector search extensions:
- `sqlite-vss` or `sqlite-vec` for vector similarity
- Combine with ReasoningBank from Phase 10
- Single database for reasoning + vectors

**Pros**: Unified storage, simpler architecture
**Cons**: SQLite not optimized for large-scale vector search

#### Option C: Claude-Flow Integration
Adopt [claude-flow](https://github.com/ruvnet/claude-flow) for enterprise-grade orchestration:

**What is Claude-Flow**:
- Multi-agent orchestration platform (64 specialized agents)
- AgentDB: Semantic vector search (96-164x faster with HNSW indexing)
- ReasoningBank: SQLite-based pattern matching (2-3ms latency)
- 100+ MCP tools for integrations
- Swarm intelligence for parallel task execution

**Potential Integration Points**:
1. **AgentDB for Contacts**:
   - Semantic search: "Find contacts similar to Luisa Boni"
   - Relationship graphs: "Who else works at this company?"
   - Pattern matching: "Contacts with similar problem patterns"

2. **ReasoningBank for Decisions**:
   - Store reasoning history in SQLite
   - Query patterns: "What works with anxious clients?"
   - Learn from past decisions

3. **Multi-Agent Workflows**:
   - Agent 1: Classify email (Haiku) - parallel
   - Agent 2: Search CRM (Pipedrive) - parallel
   - Agent 3: Draft response (Sonnet) - after 1+2
   - 2.8-4.4x speed improvement via swarm coordination

4. **MCP Tools**:
   - 100 pre-built tools (database, filesystem, web, GitHub, etc.)
   - Faster integration of new services

**When to Consider Claude-Flow**:
- ✅ Contacts > 5K-10K (vector search becomes necessary)
- ✅ Complex multi-step workflows (email → CRM → draft → call → follow-up)
- ✅ Need advanced reasoning patterns ("If customer anxious AND high-value AND past problem → strategy X")
- ✅ Want rapid integration with many external services

**When NOT to Use**:
- ❌ Current scale (<1K contacts) - JSON cache is perfect
- ❌ Simple single-agent workflows - over-engineering
- ❌ Tight budget - multi-agent = 15x token usage

**Decision Matrix**:

| Scenario | Recommended Approach |
|----------|---------------------|
| <1K contacts | JSON cache (current) ✅ |
| 1K-5K contacts | Option A: DIY embeddings |
| 5K-10K contacts | Option B: SQLite + vectors |
| >10K contacts + complex workflows | Option C: Claude-Flow |
| Need reasoning patterns | Phase 10 (Reasoning Bank) first |

**Recommendation for MrPark**:
1. **Now**: Stay with JSON cache (optimal for current scale)
2. **Next**: Implement Reasoning Bank (Phase 10) for pattern learning
3. **Future**: When >5K contacts, add vector search (Option A or B)
4. **Long-term**: Evaluate Claude-Flow only if multi-agent workflows needed

**Estimated effort**:
- Option A: 3-5 days
- Option B: 1 week
- Option C: 2-4 weeks

**Cost impact**:
- Option A/B: Embedding generation (~$0.10/1K contacts, one-time)
- Option C: 15x token usage but 32% savings via caching

---

### Phase 12: Claude-Flow or Similar Multi-Agent Platform (Optional)

**Objective**: Advanced multi-agent orchestration for complex workflows

**When to Consider**:
- ✅ Contacts > 10K (vector search mandatory)
- ✅ Complex multi-step workflows across multiple services
- ✅ Need swarm intelligence (parallel agent coordination)
- ✅ Want 100+ pre-built MCP integrations
- ✅ Budget allows 15x token usage

**When NOT to Consider**:
- ❌ Current scale (<5K contacts)
- ❌ Single-agent workflows sufficient
- ❌ Cost-sensitive (multi-agent = expensive)
- ❌ Simplicity priority (debugging complexity 3-5x)

**Alternative Platforms to Evaluate** (when needed):
1. **Claude-Flow** ([github.com/ruvnet/claude-flow](https://github.com/ruvnet/claude-flow))
   - Multi-agent orchestration (64 agents)
   - AgentDB (vector search) + ReasoningBank (SQLite patterns)
   - 100+ MCP tools
   - Proven: 96-164x faster search, 32% token reduction

2. **LangGraph** (LangChain)
   - Graph-based agent orchestration
   - Custom workflows with state persistence
   - Large ecosystem

3. **AutoGen** (Microsoft)
   - Multi-agent conversations
   - Code execution agents
   - Research-focused

4. **Crew AI**
   - Role-based agent teams
   - Task delegation
   - Simpler than Claude-Flow

**MrPark-Specific Evaluation** (if/when needed):

| Criterion | Claude-Flow | LangGraph | AutoGen | Crew AI |
|-----------|-------------|-----------|---------|---------|
| Vector Search | ✅ Built-in (AgentDB) | ❌ External | ❌ External | ❌ External |
| Reasoning Storage | ✅ Built-in (ReasoningBank) | ❌ Manual | ❌ Manual | ❌ Manual |
| MCP Integration | ✅ 100+ tools | ⚠️ Moderate | ❌ Limited | ⚠️ Moderate |
| Claude-native | ✅ Designed for Claude | ⚠️ Multi-LLM | ⚠️ Multi-LLM | ⚠️ Multi-LLM |
| Complexity | High | High | Medium | Low |
| Cost | High (15x tokens) | High | Medium | Medium |

**Recommendation**:
- **Phase 10** (Reasoning Bank): DIY SQLite - perfect for MrPark
- **Phase 11** (Vector Search): DIY or SQLite extensions - cost-effective
- **Phase 12** (Multi-Agent): Only if workflows become truly complex
  - First choice: **Claude-Flow** (if budget allows, best Claude integration)
  - Alternative: **Crew AI** (if simplicity priority, lower cost)

**Current Decision**: ❌ **NOT NEEDED**
- MrPark's single-agent architecture is optimal
- Multi-agent would add complexity without clear benefit at current scale
- Re-evaluate only when contacts > 10K AND workflows become multi-step complex

**Estimated effort** (if implemented): 3-4 weeks
**Cost impact**: +15x token usage (partially offset by caching)

---

### Phase 13: Real-Time Gmail Push Notifications

**Objective**: Replace batch sync with real-time email notifications

**Current**:
- Batch sync every X hours/days
- Manual `sync emails` command

**Future**:
- Gmail Push Notifications via Cloud Pub/Sub
- Instant thread cache update on new email
- Auto-trigger task update for affected contact

**Benefits**:
- Zero-latency email intelligence
- No manual sync needed
- Always up-to-date task view

**Implementation**:
1. Set up Google Cloud Pub/Sub
2. Register Gmail watch on mailbox
3. Webhook endpoint receives push notifications
4. Auto-sync affected threads
5. Auto-update affected tasks (on-demand, not full rebuild)

**Estimated effort**: 1 week
**Operational cost**: ~$0.10/month (Pub/Sub)

---

### Phase 14: WhatsApp Integration

**Objective**: Extend task system to WhatsApp conversations

**Why**: Many B2B relationships happen over WhatsApp, especially in Italy

**Integration**:
- Fetch WhatsApp history via StarChat API
- Aggregate with email threads in task view
- Unified conversation history (email + WhatsApp)

**Task View Example**:
```
📋 Task: Luisa Boni

Channels: Email (5 threads), WhatsApp (12 messages)

View:
Cliente ha iniziato via email (Feb 2024), poi continuato su WhatsApp.
Conversazioni WhatsApp mostrano crescente frustrazione con setup.
Ultima comunicazione: WhatsApp ieri sera, dice "non riesco ancora".
Molto urgente.

Action: Rispondere su WhatsApp OGGI con videocall di supporto.
```

**Estimated effort**: 1-2 weeks
**Depends on**: StarChat WhatsApp API availability

---

## Architecture Evolution Roadmap

```
Current (v1.0):
├── threads.json (Haiku, JSON cache)
└── tasks.json (Sonnet, JSON cache)

v2.0 (Reasoning History):
├── threads.json
├── tasks.json
│   └── + reasoning_history (per-contact decisions)
└── No new dependencies

v3.0 (Reasoning Bank):
├── threads.json
├── tasks.json (with reasoning_history)
└── reasoning.db (SQLite - cross-contact patterns)
    ├── reasoning_patterns table
    └── Pattern learning queries

v4.0 (Vector Search):
├── threads.json
├── tasks.json
├── reasoning.db
└── vectors/ (FAISS or sqlite-vec)
    ├── contact_embeddings
    └── Semantic search

v5.0 (Real-time):
├── Gmail Push Notifications → Auto-sync
├── Auto-update affected tasks
├── WhatsApp integration
└── Unified multi-channel view

v6.0 (Multi-Agent - Optional):
└── Claude-Flow or similar platform
    ├── Swarm intelligence (if needed)
    ├── AgentDB (vector search)
    ├── ReasoningBank (pattern storage)
    └── 100+ MCP tools

    OR simpler alternative:
    └── Crew AI (role-based agents, lower cost)
```

**Progression Logic**:
1. **v1.0**: Ship & validate core concept ✅
2. **v2.0**: Add memory (cheap, high value)
3. **v3.0**: Add cross-contact learning (moderate effort)
4. **v4.0**: Scale to 5K+ contacts (when needed)
5. **v5.0**: Real-time + multi-channel (operational improvement)
6. **v6.0**: Multi-agent (ONLY if workflows become complex)

**Key Insight**: Phases 2-5 add value WITHOUT architectural complexity. Phase 6 is major shift, only if truly needed.

---

## Technology Evaluation: Claude-Flow

**Source**: https://github.com/ruvnet/claude-flow

### Pros
- ✅ Enterprise-grade multi-agent orchestration
- ✅ Proven performance (96-164x faster search, 32% token reduction)
- ✅ 100+ pre-built MCP tools
- ✅ Persistent memory (AgentDB vector + ReasoningBank SQLite)
- ✅ Swarm intelligence for parallel execution

### Cons
- ❌ Over-engineering for current scale (<1K contacts)
- ❌ Multi-agent complexity (3-5x harder to debug)
- ❌ Dependency bloat (many tools won't be used)
- ❌ 15x token usage (vs. single-agent)

### Decision
- **Not now**: Current architecture is optimal for scale
- **Re-evaluate when**:
  - Contacts > 5K-10K
  - Need complex multi-step workflows
  - Want advanced reasoning patterns

---

## Next Immediate Steps

1. ✅ **Complete task system testing** with real contacts (Luisa Boni case)
2. **Refine Sonnet prompts** based on actual task outputs
3. **Add reasoning history** (Phase 9) - low effort, high value
4. **Document best practices** from real usage
5. **Monitor costs** and optimize if needed

The architecture is designed for incremental evolution. Each phase delivers standalone value without breaking existing functionality.
