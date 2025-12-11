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

## Request 5: Multi-Tenant Infrastructure - Owner Isolation e OAuth Token Storage

**Date:** 2025-11-30
**Priority:** CRITICA (Security)
**Requested by:** Zylch AI integration team
**Status:** RICHIESTO

### Contesto

Zylch AI supporta autenticazione Firebase (Google e Microsoft). Ogni utente Firebase ha:
- **owner_id** (Firebase UID)
- **zylch_assistant_id** (ID univoco dell'assistant)
- **provider** (google o microsoft)
- **OAuth tokens** (per accesso email)

**Attualmente:** Zylch CLI salva tutto in filesystem locale (~/.zylch/).

**Futuro:** Zylch API multi-tenant avrà bisogno di StarChat per storage centralizzato e sicuro.

### Architettura Richiesta

```
Firebase UID (owner_id)
    ↓
Zylch Assistant (zylch_assistant_id) - 1:1 mapping
    ↓
Email Channels (Google/Microsoft)
```

**Vincoli di Sicurezza:**
- 1 owner_id → 1 zylch_assistant (relazione 1:1 strict)
- zylch_assistant NON PUÒ essere condiviso tra owner_id diversi
- Token OAuth DEVONO essere isolati per owner_id
- Dati DEVONO essere filtrati per firebase_uid in TUTTE le query

---

### 5.1 Tabella: zylch_assistants

Mappatura tra Firebase UID e Zylch Assistant ID.

```sql
CREATE TABLE zylch_assistants (
    firebase_uid VARCHAR(255) PRIMARY KEY,
    zylch_assistant_id VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_assistant (zylch_assistant_id),
    INDEX idx_assistant (zylch_assistant_id)
);
```

**Vincoli:**
- firebase_uid è PRIMARY KEY (un owner = un assistant)
- zylch_assistant_id è UNIQUE (un assistant non può essere condiviso)
- Se owner tenta di creare secondo assistant → ERROR

**API Endpoint richiesto:**

```
POST /api/zylch/assistants/register
Authorization: Bearer {firebase_jwt}

Request:
{
  "firebase_uid": "abc123xyz",
  "zylch_assistant_id": "assistant_789"
}

Response (success):
{
  "success": true,
  "zylch_assistant_id": "assistant_789"
}

Response (error - già esiste):
{
  "success": false,
  "error": "ASSISTANT_ALREADY_EXISTS",
  "existing_assistant_id": "assistant_456"
}
```

```
GET /api/zylch/assistants/:firebase_uid
Authorization: Bearer {firebase_jwt}

Response (se esiste):
{
  "firebase_uid": "abc123xyz",
  "zylch_assistant_id": "assistant_789",
  "created_at": "2025-11-30T10:00:00Z"
}

Response (se non esiste):
{
  "error": "ASSISTANT_NOT_FOUND"
}
```

---

### 5.2 Tabella: zylch_oauth_tokens

Storage sicuro dei token OAuth (Google e Microsoft).

```sql
CREATE TABLE zylch_oauth_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    firebase_uid VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,  -- 'google' or 'microsoft'
    token_type VARCHAR(50) NOT NULL,  -- 'access' or 'refresh'
    token_value TEXT NOT NULL,  -- ENCRYPTED
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_token (firebase_uid, provider, token_type),
    INDEX idx_owner_provider (firebase_uid, provider)
);
```

**Vincoli:**
- Token DEVONO essere isolati per firebase_uid
- token_value DEVE essere encrypted at rest (AES-256 o equivalente)
- Ogni owner può avere token sia Google che Microsoft
- expires_at può essere NULL per refresh token (lifetime lungo)

**API Endpoint richiesto:**

```
POST /api/zylch/tokens/save
Authorization: Bearer {firebase_jwt}

Request:
{
  "firebase_uid": "abc123xyz",
  "provider": "google",  // or "microsoft"
  "access_token": "ya29.a0AfH6...",
  "refresh_token": "1//0gJx...",
  "expires_at": "2025-11-30T11:00:00Z"
}

Response:
{
  "success": true
}
```

```
GET /api/zylch/tokens/:firebase_uid/:provider
Authorization: Bearer {firebase_jwt}

Response:
{
  "access_token": "ya29.a0AfH6...",
  "refresh_token": "1//0gJx...",
  "expires_at": "2025-11-30T11:00:00Z"
}

Response (se scaduto):
{
  "error": "TOKEN_EXPIRED",
  "refresh_token": "1//0gJx..."  // Può essere usato per refresh
}
```

```
DELETE /api/zylch/tokens/:firebase_uid/:provider
Authorization: Bearer {firebase_jwt}

Response:
{
  "success": true
}
```

---

### 5.3 Isolamento Dati StarChat

**CRITICO:** Tutte le tabelle esistenti devono avere isolamento per firebase_uid.

**Tabelle da verificare:**
- `contacts` - aggiungere colonna `firebase_uid VARCHAR(255) NOT NULL`
- `messages` - aggiungere colonna `firebase_uid VARCHAR(255) NOT NULL`
- `email_threads` - aggiungere colonna `firebase_uid VARCHAR(255) NOT NULL`
- `calendars` - aggiungere colonna `firebase_uid VARCHAR(255) NOT NULL`
- Ogni altra tabella che contiene dati utente

**Migrazione Schema:**
```sql
ALTER TABLE contacts ADD COLUMN firebase_uid VARCHAR(255) NOT NULL DEFAULT 'legacy';
CREATE INDEX idx_contacts_firebase ON contacts(firebase_uid);
```

**TUTTE le query SQL devono filtrare per firebase_uid:**

```sql
-- CORRETTO
SELECT * FROM contacts
WHERE firebase_uid = ?
AND email = ?;

-- SBAGLIATO (PERICOLOSO!)
SELECT * FROM contacts
WHERE email = ?;  -- NO firebase_uid filter!
```

**Endpoint API devono estrarre firebase_uid da JWT:**
```python
@app.get("/api/contacts/{contact_id}")
async def get_contact(contact_id: str, token: str = Depends(verify_firebase_token)):
    firebase_uid = token["uid"]  # From JWT

    # Query DEVE includere firebase_uid
    contact = db.query(
        "SELECT * FROM contacts WHERE id = ? AND firebase_uid = ?",
        contact_id, firebase_uid
    )

    if not contact:
        raise HTTPException(404, "Contact not found")  # O non esiste O non appartiene a questo owner

    return contact
```

---

### 5.4 Audit Log

Tabella per loggare accessi cross-owner (sicurezza).

```sql
CREATE TABLE zylch_access_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    firebase_uid VARCHAR(255) NOT NULL,
    action VARCHAR(100) NOT NULL,  -- 'read_contact', 'write_token', etc.
    resource_type VARCHAR(50) NOT NULL,  -- 'contact', 'token', etc.
    resource_id VARCHAR(255),
    resource_owner_uid VARCHAR(255),
    access_granted BOOLEAN NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_owner (firebase_uid),
    INDEX idx_resource_owner (resource_owner_uid),
    INDEX idx_timestamp (timestamp)
);
```

**Uso:**
- Log ogni accesso a risorse
- Se `firebase_uid != resource_owner_uid` → FLAG DI SICUREZZA
- Alert se `access_granted = false` ripetuto
- Retention policy: 90 giorni (GDPR compliance)

**Esempi di log:**
```json
// Accesso corretto
{
  "firebase_uid": "owner_abc",
  "action": "read_contact",
  "resource_type": "contact",
  "resource_id": "contact_123",
  "resource_owner_uid": "owner_abc",  // STESSO owner
  "access_granted": true
}

// Tentativo cross-owner (ALERT!)
{
  "firebase_uid": "owner_abc",
  "action": "read_contact",
  "resource_type": "contact",
  "resource_id": "contact_456",
  "resource_owner_uid": "owner_xyz",  // DIVERSO owner!
  "access_granted": false
}
```

---

### Use Case: Zylch Multi-Tenant API

**Scenario:** 100 utenti usano Zylch AI via web.

**Flow:**
1. User A fa login con Google → Firebase JWT
2. Zylch API verifica JWT → estrae firebase_uid
3. Zylch API chiama StarChat: `POST /api/zylch/assistants/register`
4. StarChat registra (firebase_uid_A → zylch_assistant_A)
5. Zylch API salva token OAuth: `POST /api/zylch/tokens/save`
6. StarChat cripta e salva token per firebase_uid_A
7. User A sync email → StarChat recupera token per firebase_uid_A
8. User B (firebase_uid_B) NON PUÒ vedere dati di User A (isolamento DB)

**Sicurezza:**
- Token OAuth MAI esposti via API
- Ogni query filtra per firebase_uid
- Audit log traccia ogni accesso
- Cross-owner access = BLOCKED + LOGGED

---

### Benefici

1. **Sicurezza:** Isolamento totale tra owner
2. **Scalabilità:** Supporto multi-tenant nativo
3. **Compliance:** GDPR-ready (data isolation)
4. **Token Management:** Centralizzato e sicuro
5. **Auditability:** Tutti gli accessi tracciati

---

### Priorità Implementazione

**P0 - Critico:**
1. Tabella `zylch_assistants` + API endpoints
2. Isolamento `contacts` con colonna `firebase_uid`
3. Modificare API contacts per filtrare per firebase_uid

**P1 - Alta:**
4. Tabella `zylch_oauth_tokens` + API endpoints
5. Token encryption at rest
6. Migrazione altre tabelle (messages, calendars)

**P2 - Media:**
7. Audit log
8. Monitoring e alerting per cross-owner access
9. Token refresh automatico

---

### Note Implementazione (Lato Zylch)

**Data:** 2025-11-30

Zylch AI ha già implementato l'isolamento lato CLI:
- ✅ Token Google: `~/.zylch/google_tokens/token_<email>.pickle`
- ✅ Token Microsoft: `~/.zylch/credentials.json` (graph_token)
- ✅ GmailClient con account parameter
- ✅ GoogleCalendarClient con account parameter
- ✅ Calendar condizionale in base a provider

**File modificati:**
- `zylch/tools/factory.py` - Account isolation
- `zylch/config.py` - Token path per-user
- `zylch/tools/gcalendar.py` - Account parameter
- `zylch/cli/auth_server.py` - Graph token storage

**Prossimo step:** Quando StarChat implementa le API, Zylch API userà quelle invece del filesystem locale.

Grazie! 🙏

---

## Request 6: (Future requests go here)

