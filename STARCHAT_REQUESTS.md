# StarChat API Enhancement Requests

This document tracks feature requests for the StarChat API to improve Zylch AI integration.

---

## Request 1: Support CrmContactSearch body in BasicAuth GET endpoint

**Date:** 2025-11-17
**Priority:** High
**Requested by:** Zylch AI integration team

### Current Behavior

The BasicAuth endpoint `GET /mrcall/v1/crm/contact/{businessId}` currently:
- Accepts `CrmContactSearch` in the request body (documented in OpenAPI)
- But only uses the `id` query parameter in the actual implementation
- Does not filter by `emails`, `phones`, or other fields from the body

**Code reference:** `CrmContactResource.scala:285-288`
```scala
psqlService.search(
  businessId = businessId,
  id = contactId  // Only uses ID, ignores body
)
```

### Desired Behavior

Please implement full `CrmContactSearch` body support, similar to the Firebase JWT endpoint:
- Search by `emails: [{"address": "user@example.com"}]`
- Search by `phones: [{"number": "+391234567890"}]`
- Search by `displayName`, `name`, etc.

This would enable proper contact lookup without requiring JWT authentication.

### Use Case

Zylch AI needs to check if a contact already exists before creating/updating:
```python
# Current workaround: GET all contacts and filter in Python (slow)
all_contacts = await get_all_contacts(business_id)
matching = [c for c in all_contacts
            if any(e.get("address") == email for e in c.get("emails", []))]

# Desired: Direct API search
contacts = await search_contacts(
    business_id=business_id,
    emails=[{"address": email}]
)
```

### Benefits

1. **Performance**: Avoid fetching all contacts and filtering client-side
2. **Consistency**: BasicAuth and JWT endpoints have same capabilities
3. **Proper upsert**: Enable "check before create" pattern to prevent duplicates

### Implementation Notes

The Firebase endpoint already does this correctly. Please extend the same functionality to the BasicAuth endpoint by:
1. Parsing the `CrmContactSearch` from request body in `contactGetApiKeyRoute`
2. Passing search criteria to `psqlService.search()`
3. The backend service already supports these parameters (used by Firebase endpoint)

Thank you! 🙏

---

## Request 2: GET all contacts for business_id without requiring id parameter

**Date:** 2025-11-17
**Priority:** High
**Requested by:** Zylch AI integration team
**Status:** WORKAROUND IMPLEMENTED ✅

### Current Behavior

The BasicAuth endpoint `GET /mrcall/v1/crm/contact/{businessId}` currently:
- Accepts optional `id` query parameter
- Calls `psqlService.search(businessId, id)`
- Returns empty list when `id` is not provided (None)

**Code reference:** `CrmContactResource.scala:285-288`
```scala
psqlService.search(
  businessId = businessId,
  id = contactId  // Returns empty if None
)
```

### Desired Behavior

When `id` parameter is not provided, please return **all contacts** for that business_id (with pagination).

This would enable:
```bash
# Get all contacts for business
GET /mrcall/v1/crm/contact/{businessId}
# Returns: all contacts (paginated)

# Get specific contact
GET /mrcall/v1/crm/contact/{businessId}?id={contactId}
# Returns: single contact
```

### Use Case

Zylch AI needs to retrieve all contacts for a business to:
1. Check if contact exists before creating (prevent duplicates)
2. Filter contacts client-side by custom variables
3. List all contacts for the user

### ✅ Workaround Implemented (Zylch AI)

**Date:** 2025-11-18

We discovered that the BasicAuth endpoint DOES support `CrmContactSearch` in the POST body!

```python
# API Endpoint
POST /mrcall/v1/crm/contact/{businessId}
Content-Type: application/json

{
  "from": 0,
  "size": 100
}
```

**Implementation:**
1. Updated `StarChatClient.search_contacts()` to use POST with CrmContactSearch body
2. Added `search_contacts_paginated()` method for fetching all contacts with pagination
3. Created `ListAllContactsTool` for the agent to list all business contacts
4. Tool groups results by RELATIONSHIP_TYPE for better visibility

**Usage:**
```
You: puoi cercare tutti i contatti nel business per favore?
Zylch AI: [Fetches all contacts using ListAllContactsTool]
Found 127 total contacts: customer=45, lead=32, prospect=28, unknown=22
```

### API Enhancement Still Needed

While the workaround works, it would be cleaner if the API explicitly documented the POST body support:
- Document that POST with CrmContactSearch is the recommended approach
- Ensure pagination works reliably (test with large datasets)
- Consider supporting query parameters as alternative to body

### Implementation Notes

The `psqlService.search()` method already supports returning all contacts. We just needed to use the correct HTTP method (POST) and body format (CrmContactSearch).

Thank you! 🙏

---

## Request 3: WhatsApp Messages REST API Endpoint

**Date:** 2025-11-26
**Priority:** Medium
**Requested by:** Zylch AI integration team
**Status:** UNDER DEVELOPMENT 🚧

### Current Situation

StarChat has WhatsApp integration via:
- **WebSocket endpoint:** `GET /mrcall/v1/{realm}/whatsappweb/stream`
- **PostgreSQL storage:** `whatsapp_messages` table

However, there is no REST API endpoint to query WhatsApp messages.

### Desired Behavior

Please add a REST API endpoint to query WhatsApp messages:

```
GET /mrcall/v1/crm/whatsapp/{businessId}/messages
Authorization: Basic <base64(username:password)>

Query Parameters:
- days_back: int (default: 30) - Number of days to look back
- phone: string (optional) - Filter by phone number
- limit: int (default: 100) - Maximum results
- offset: int (default: 0) - Pagination offset

Response:
[
  {
    "id": "msg_123",
    "business_id": "business_456",
    "phone_number": "+391234567890",
    "message_text": "Hello, I need help with...",
    "direction": "inbound",  // or "outbound"
    "timestamp": "2025-11-26T10:30:00Z",
    "contact_id": "contact_789"  // If matched to CRM contact
  }
]
```

### Use Case

Zylch AI needs to:
1. Read WhatsApp conversations to identify contacts by phone number
2. Analyze communication gaps across email + WhatsApp + phone
3. Build person-centric task list including WhatsApp follow-ups

### Benefits

1. **Consistency**: Matches existing REST API patterns
2. **Security**: Uses existing BasicAuth or JWT authentication (NEVER bypass with direct DB access!)
3. **Easier integration**: Clean API interface, no database management
4. **Pagination support**: Handle large message histories efficiently

### Implementation Status (Zylch AI)

**Date:** 2025-11-26

Zylch AI has prepared the tool structure to consume this endpoint once available:

**What's Ready:**
1. `_GetWhatsAppContactsTool` - Agent tool registered and ready
2. `StarChatClient.get_whatsapp_contacts()` - Client method prepared
3. Tool will automatically work once StarChat provides the endpoint

**What's Needed:**
- StarChat REST API endpoint: `GET /mrcall/v1/crm/whatsapp/{businessId}/messages`
- Uses existing BasicAuth authentication
- Returns message list with phone numbers and timestamps

**IMPORTANT:** We will NOT use direct PostgreSQL access - all data access must go through StarChat's authenticated API.

Thank you! 🙏

---

## Request 4: Fast Email Lookup API

**Date:** 2025-11-28
**Priority:** ALTA
**Requested by:** Zylch AI integration team
**Status:** DA IMPLEMENTARE

### Problema

Attualmente per verificare se un contatto esiste in StarChat, dobbiamo:
1. Chiamare `GET /api/contacts?email={email}` che scarica TUTTO il contatto
2. Questo è lento e costoso per semplici verifiche di esistenza

Zylch AI ha implementato una cache locale (`identifier_map.json`) per evitare chiamate remote quando i dati sono freschi, ma serve comunque un modo per verificare se StarChat ha dati più recenti della cache locale.

### Endpoint Richiesto

```
GET /mrcall/v1/crm/contact/{businessId}/lookup
Authorization: Basic <base64(username:password)>
```

**Query Parameters:**
- `email` (string, required): Email da cercare

**Response (leggera, solo metadata):**
```json
{
  "exists": true,
  "contact_id": "abc123",
  "last_updated": "2024-01-15T10:30:00Z"
}
```

Se non esiste:
```json
{
  "exists": false
}
```

### Use Case in Zylch

Prima di fare ricerche costose (Gmail 10+ secondi, web search), Zylch verifica:
1. Il contatto è già in cache locale? → usa cache
2. Il contatto è in StarChat ma più recente della cache? → sync da StarChat
3. Il contatto non esiste da nessuna parte? → ricerche remote

### Benefici

- Riduzione chiamate API Gmail del 70-80%
- Response time da 10s a <100ms per contatti noti
- Risparmio costi API
- Permette sync bidirezionale cache locale ↔ StarChat

### Implementation Status (Zylch AI)

**Date:** 2025-11-28

Zylch AI ha già implementato la struttura per usare questo endpoint quando disponibile:

1. `IdentifierMapCache` - Cache locale con TTL 7 giorni
2. `_SearchLocalMemoryTool` - Tool che cerca prima in cache locale
3. `_SaveContactTool` - Registra identificatori in cache dopo salvataggio

**Placeholder nel codice:**
```python
# TODO: STARCHAT_REQUEST - Quando disponibile, usare StarChat lookup_by_email
# per verificare se il contatto è stato aggiornato remotamente
# async def _check_starchat_freshness(self, email: str) -> Optional[datetime]:
#     result = await self.starchat.lookup_by_email(email, self.business_id)
#     if result and result.get("exists"):
#         return datetime.fromisoformat(result["last_updated"])
#     return None
```

Grazie! 🙏

---

## Request 5: (Future requests go here)

