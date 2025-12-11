# MrCall Integration - Telephony & WhatsApp via StarChat

## Overview

MrCall (via StarChat API) provides telephony and WhatsApp integration for Zylch, enabling AI-powered phone calls and multi-channel messaging. The integration supports contact management (CRM), outbound calls, assistant configuration, and future WhatsApp messaging capabilities.

**Note**: WhatsApp integration is documented but not yet implemented, pending StarChat REST API endpoint (see [WhatsApp Integration TODO](WHATSAPP_INTEGRATION_TODO.md)).

## Key Concepts

### StarChat API

StarChat is the Firebase-backed API layer for MrCall services. It provides:
- **Contact CRM**: Create, read, update, delete contacts
- **Business Configuration**: Manage MrCall assistant variables
- **Outbound Calls**: Trigger AI-powered phone calls
- **WhatsApp** (pending): Access WhatsApp message history

**Authentication**: Supports both JWT (Firebase) and Basic Auth.

### MrCall Assistants

MrCall assistants are AI-powered phone agents with customizable behavior via variables:

**Common Variables**:
- `OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT` - Greeting when customer calls
- `OSCAR_OUTBOUND_WELCOME_MESSAGE_PROMPT` - Greeting when assistant calls out
- `OSCAR_OBJECTIVE` - Assistant's primary goal
- `OSCAR_QUESTIONS` - Questions to ask during call
- `GREETING_MESSAGE` - Initial greeting text

**Variable Preservation**: When modifying prompts via LLM, variables must be preserved exactly (e.g., `%%name=Guest%%`, `{{public.TIME}}`).

## How It Works

### 1. Contact Management

**Search contacts**:
```python
from zylch.tools.starchat import StarChatClient

client = StarChatClient(
    base_url="https://api.starchat.com",
    username="user",
    password="pass",
    realm="default"
)

# Search by email
contacts = await client.search_contacts(
    email="john@example.com",
    business_id="biz_123",
    limit=10
)

# Or search by phone
contacts = await client.search_contacts(
    phone="+12025551234",
    business_id="biz_123"
)
```

**Create contact**:
```python
contact_data = {
    "email": "john@example.com",
    "phones": [{"number": "+12025551234"}],
    "variables": {
        "PRIORITY_SCORE": "8",
        "COMPANY": "Acme Corp"
    }
}

created = await client.create_contact(
    contact_data=contact_data,
    business_id="biz_123"
)
```

**Update contact variables**:
```python
await client.update_contact_variables(
    contact_id="contact_abc123",
    variables={
        "PRIORITY_SCORE": "9",
        "LAST_INTERACTION": "2025-12-08"
    }
)
```

### 2. Outbound Calls

Trigger AI-powered phone calls:

```python
result = await client.initiate_outbound_call(
    phone_number="+12025551234",
    business_id="biz_123",
    caller_id="+12025559999",  # Optional: verified caller ID
    contact_id="contact_abc123",  # Optional: known contact
    variables={
        "CUSTOMER_NAME": "John Smith",
        "APPOINTMENT_TIME": "2PM tomorrow"
    }
)

# Response:
{
    "status": "initiated",
    "call_id": "call_xyz789",
    "phone_number": "+12025551234",
    "business_id": "biz_123"
}
```

**Call variables** are passed to the assistant script and can be referenced in prompts.

### 3. Assistant Configuration

**Get business configuration**:
```python
config = await client.get_business_config(business_id="biz_123")

# Returns:
{
    "businessId": "biz_123",
    "businessName": "My Company",
    "variables": {
        "OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT": "Hello! How can I help?",
        "OSCAR_OBJECTIVE": "Schedule appointments",
        ...
    }
}
```

**Update assistant variable**:
```python
await client.update_business_variable(
    business_id="biz_123",
    variable_name="OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT",
    value="Buongiorno! Come posso aiutarti?"
)
```

**Get variable schema**:
```python
schema = await client.get_variable_schema(
    template_name="private",
    language="it-IT",
    nested=True
)

# Returns variable catalog from business_variable.csv
```

## Implementation Details

### File References

**Core Client**:
- `zylch/tools/starchat.py` - StarChat API client (701 lines)

**MrCall Tools**:
- `zylch/tools/mrcall/` - MrCall assistant configuration tools
  - `GetAssistantCatalogTool` - List assistant variables
  - `ConfigureAssistantTool` - Modify assistant prompts via LLM
  - `SaveMrCallAdminRuleTool` - Save admin-level configuration rules

**Tests**:
- `tests/test_mrcall_integration.py` - Integration tests (243 lines)

### Key Classes

#### `StarChatClient`

Main API client for StarChat.

**Methods**:

**Contact Management**:
- `get_contact(contact_id)` → Optional[Dict]
  - Get contact by ID
- `get_contact_by_email(email, business_id)` → Optional[Dict]
  - Search contact by email address
- `search_contacts(email, phone, business_id, limit)` → List[Dict]
  - Search contacts by criteria
- `create_contact(contact_data, business_id)` → Dict
  - Create new contact
- `update_contact(contact_id, updates)` → Dict
  - Update contact data
- `update_contact_variables(contact_id, variables)` → Dict
  - Update contact variables (merge with existing)
- `delete_contact(contact_id)` → None
  - Delete contact

**Business Configuration**:
- `get_business_config(business_id)` → Optional[Dict]
  - Fetch business configuration with variables
- `get_variable_schema(template_name, language, nested)` → Dict
  - Fetch variable catalog schema
- `update_business_variable(business_id, variable_name, value)` → Dict
  - Update a business variable
- `check_user_role(business_id)` → Optional[str]
  - Check user's role (admin/user)

**Telephony**:
- `initiate_outbound_call(phone_number, business_id, caller_id, contact_id, variables)` → Dict
  - Trigger AI-powered outbound call

**WhatsApp (pending)**:
- `get_whatsapp_contacts(business_id, days_back)` → List[Dict]
  - Get contacts from WhatsApp messages (not yet available)

### Variable Utils

**`extract_variables(text)`**:
```python
from zylch.tools.mrcall.variable_utils import extract_variables

text = "Hello %%name=Guest%%! Time: {{public.TIME}}"
variables = extract_variables(text)
# Returns: ["%%name=Guest%%", "{{public.TIME}}"]
```

**`validate_variable_preservation(original, modified)`**:
```python
from zylch.tools.mrcall.variable_utils import validate_variable_preservation

original = "Ciao %%name=Guest%%! Come posso aiutarti?"
modified = "Buongiorno %%name=Guest%%! Sono qui per assisterti."

result = validate_variable_preservation(original, modified)
# Returns: {
#     "all_preserved": True,
#     "removed": [],
#     "added": [],
#     "preserved": ["%%name=Guest%%"]
# }
```

**`validate_no_placeholders(text)`**:
```python
from zylch.tools.mrcall.variable_utils import validate_no_placeholders

text = "Complete text without ..."
is_valid, error = validate_no_placeholders(text)
# Returns: (True, None)

text_with_placeholder = "Text with ... ellipsis"
is_valid, error = validate_no_placeholders(text_with_placeholder)
# Returns: (False, "Found ellipsis (...) - complete the text")
```

## Usage Examples

### Example 1: Sync Contacts from Gmail

**Scenario**: After syncing emails, create StarChat contacts for unknown senders.

```python
# In email sync service
from zylch.tools.starchat import StarChatClient

starchat = StarChatClient(base_url=STARCHAT_URL, ...)

for email in new_emails:
    sender_email = email['from_email']

    # Check if contact exists
    contact = await starchat.get_contact_by_email(
        email=sender_email,
        business_id=business_id
    )

    if not contact:
        # Create new contact
        contact_data = {
            "email": sender_email,
            "variables": {
                "EMAIL_ADDRESS": sender_email,
                "FIRST_CONTACT_DATE": datetime.now().isoformat()
            }
        }
        await starchat.create_contact(contact_data, business_id)
```

### Example 2: Trigger Follow-Up Call

**User intent**: "Call John to follow up on the proposal"

```python
# AI agent calls:
result = await starchat_client.initiate_outbound_call(
    phone_number="+12025551234",
    business_id="biz_123",
    contact_id="contact_john",
    variables={
        "CUSTOMER_NAME": "John",
        "CALL_REASON": "Follow up on proposal",
        "PROPOSAL_DATE": "December 5th"
    }
)

# MrCall assistant calls John
# Script includes variables: "Hi John, calling to follow up on the proposal from December 5th..."
```

### Example 3: Customize Assistant Greeting

**User intent**: "Make the greeting more formal"

```python
# Get current configuration
config = await starchat.get_business_config(business_id="biz_123")
original_prompt = config["variables"]["OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT"]

# Modify via LLM (preserving variables)
modified_prompt = await modify_prompt_with_llm(
    original_prompt=original_prompt,
    request="Make it more formal",
    api_key=ANTHROPIC_API_KEY
)

# Validate variables preserved
validation = validate_variable_preservation(original_prompt, modified_prompt)
if not validation["all_preserved"]:
    raise ValueError("Variables not preserved!")

# Update configuration
await starchat.update_business_variable(
    business_id="biz_123",
    variable_name="OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT",
    value=modified_prompt
)
```

## CLI Commands

*(MrCall CLI commands are part of the larger Zylch CLI - see [CLI Commands](../guides/cli-commands.md))*

**Select Assistant**:
```bash
/mrcall --select <business_id>
```

**List Assistants**:
```bash
/mrcall --list
```

**Configure Assistant**:
```bash
/mrcall --configure VARIABLE_NAME "modification request"
```

**Initiate Call**:
```bash
/call +12025551234
```

## Performance Characteristics

### API Calls
- **Contact search**: <100ms (StarChat API)
- **Create contact**: <200ms (StarChat API)
- **Outbound call initiation**: <500ms (StarChat + telephony provider)

### Batch Operations
- **Sync 100 contacts**: <10s (100 API calls, parallel)
- **Search all contacts**: <2s for 1000 contacts (BasicAuth endpoint)

## Known Limitations

1. **WhatsApp not available**: REST API endpoint pending from StarChat
2. **No call status tracking**: Cannot query call status after initiation
3. **No call recordings**: Call recording access not yet available via API
4. **Variable validation client-side**: Server doesn't validate variable preservation
5. **No bulk contact operations**: Must create/update contacts one-at-a-time
6. **BasicAuth pagination**: GET /crm/contact/{businessId} returns all contacts (no pagination)

## Future Enhancements

### Planned (Phase I+)
- **WhatsApp messaging**: Send/receive WhatsApp messages via StarChat API
- **Call status tracking**: Query call status and duration
- **Call recordings**: Access call transcripts and recordings
- **Webhook integration**: Receive real-time call events (incoming, completed, failed)
- **Bulk operations**: Batch create/update contacts

### WhatsApp Integration (High Priority)

See [WHATSAPP_INTEGRATION_TODO.md](WHATSAPP_INTEGRATION_TODO.md) for comprehensive WhatsApp roadmap:
- WhatsApp message history retrieval
- Send/reply to WhatsApp messages
- WhatsApp conversation threading
- WhatsApp contact sync
- Multi-channel inbox (email + WhatsApp)

### Intelligence Improvements
- **Call sentiment analysis**: Analyze call tone and sentiment
- **Auto-categorize contacts**: AI-based contact categorization from call transcripts
- **Call suggestions**: Recommend who to call based on relationship gaps
- **Script optimization**: A/B test assistant scripts, learn what works

## Related Documentation

- **[WhatsApp Integration](WHATSAPP_INTEGRATION_TODO.md)** - Comprehensive WhatsApp roadmap
- **[Email Archive](email-archive.md)** - Email sync creates StarChat contacts
- **[Relationship Intelligence](relationship-intelligence.md)** - Gaps detection suggests calls
- **[Triggers & Automation](triggers-automation.md)** - Auto-trigger calls on events

## References

**Source Code**:
- `zylch/tools/starchat.py` - StarChat API client (701 lines)
- `zylch/tools/mrcall/` - MrCall configuration tools
- `tests/test_mrcall_integration.py` - Integration tests (243 lines)

**External APIs**:
- StarChat REST API: https://api.starchat.com (requires authentication)
- MrCall Web App: https://app.mrcall.ai

**Technologies**:
- httpx (async HTTP client)
- Firebase Auth (JWT authentication)
- Basic Auth (username/password)

---

**Last Updated**: December 2025
