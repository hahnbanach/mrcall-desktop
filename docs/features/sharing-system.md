---
description: |
  Consent-based intelligence sharing between Zylch users. Sender initiates /share, intel goes to
  pending queue, recipient must explicitly accept before anything is visible. States: pending,
  accepted, rejected, revoked. Shared data stored in ZylchMemory namespace
  shared:{recipient_owner_id}:{sender_owner_id}. After first acceptance, future shares are automatic.
---

# Sharing System - Consent-Based Intelligence Sharing

## Overview

The Sharing System enables Zylch users to share contact intelligence with each other through a consent-based architecture. Users can share insights about mutual contacts while maintaining privacy and requiring explicit recipient acceptance before any information is visible.

## Key Concepts

### Consent-Based Architecture

**No sharing happens without consent.** Before any intelligence is visible to a recipient:
1. Sender registers recipient with `/share recipient@email.com`
2. Sender shares intel: "Condividi con Luigi che Marco Ferrari ha firmato"
3. Intel goes to **pending queue** (not visible to recipient yet)
4. Recipient sees pending request and must explicitly **accept**
5. Only after acceptance, pending intel moves to recipient's shared namespace
6. Future shares from same sender are automatic (no re-acceptance needed)

### Authorization States

| State | Description | Can Share? |
|-------|-------------|------------|
| **Not registered** | No relationship exists | No - must register first |
| **Pending** | Registration sent, waiting for acceptance | Queued (not visible yet) |
| **Accepted** | Recipient accepted sharing | Yes - immediate visibility |
| **Rejected** | Recipient rejected sharing | No - sender blocked |
| **Revoked** | Previously accepted, now revoked | No - future shares blocked |

**Important**: Revocation stops future shares but keeps existing shared intel visible.

### Namespace Pattern

Shared intelligence is stored in ZylchMemory using a privacy-preserving namespace:

```
shared:{recipient_owner_id}:{sender_owner_id}
```

**Benefits**:
- **Privacy**: Only recipient can see their `shared:*` namespaces
- **Attribution**: Namespace includes sender's owner_id for source tracking
- **Easy lookup**: Query all shares from a sender: `shared:luigi:mario`
- **Scoped access**: Recipient controls what they see via authorization

**Example**:
- Mario (owner_id: `mario_123`) shares with Luigi (owner_id: `luigi_456`)
- Namespace: `shared:luigi_456:mario_123`
- Only Luigi can query this namespace
- Luigi knows intel came from Mario

## How It Works

### 1. User Registration

Before sharing, users must register with Zylch and register recipients:

**Self-registration** (automatic on first login):
```python
# In CLI initialization
auth_manager.register_user(
    owner_id="mario_123",
    email="mario@example.com",
    display_name="Mario Rossi"
)
```

**Recipient registration** (via `/share` command):
```bash
/share luigi@example.com

# Output: "Registrato Luigi come destinatario. Quando condividerai info, Luigi dovrà accettare."
```

**Behind the scenes**:
```python
auth_manager.register_recipient(
    sender_email="mario@example.com",
    recipient_email="luigi@example.com"
)

# Creates entry in share_authorizations table with status='pending'
```

### 2. Sharing Intelligence

When sender shares intel about a contact:

**User intent**: "Condividi con Luigi che Marco Ferrari ha firmato il contratto"

**AI agent calls**:
```python
intel_share.share_intel(
    sender_owner_id="mario_123",
    sender_email="mario@example.com",
    recipient_owner_id="luigi_456",
    recipient_email="luigi@example.com",
    context="Marco Ferrari ha firmato il contratto",
    identifiers={
        "email": "marco.ferrari@client.com",
        "name": "Marco Ferrari"
    },
    sender_display_name="Mario Rossi"
)
```

**Flow**:
1. Check authorization status
   - If **accepted**: Store directly in shared namespace
   - If **pending**: Add to pending_shares queue
   - If **rejected/revoked**: Return error
   - If **not registered**: Return error (must register first)

2. For accepted authorization:
   - Build namespace: `shared:luigi_456:mario_123`
   - Store in ZylchMemory as `contact_intel` category
   - Include metadata (sender, identifiers, timestamp) in pattern field

3. For pending authorization:
   - Add to `pending_shares` table
   - Wait for recipient to accept

### 3. Recipient Acceptance

When recipient logs in and sees pending request:

**Pending notification** (automatic at session start):
```
📬 Hai 1 richiesta di condivisione da Mario Rossi (mario@example.com)
   - "Marco Ferrari ha firmato il contratto" e altre 2 info

Vuoi accettare? (sì/no)
```

**User responds**: "Sì, accetta Mario"

**AI agent calls**:
```python
# 1. Accept authorization
auth_manager.accept_authorization(
    recipient_email="luigi@example.com",
    sender_email="mario@example.com"
)

# 2. Process pending shares
processed = intel_share.process_accepted_authorization(
    recipient_owner_id="luigi_456",
    recipient_email="luigi@example.com",
    sender_email="mario@example.com"
)

# Result: 3 pending shares moved to shared:luigi_456:mario_123
```

### 4. Retrieving Shared Intel

When recipient queries contact information:

**User asks**: "Cosa sai su Marco Ferrari?"

**AI agent calls**:
```python
# Automatically called when searching for contact
shared_intel = intel_share.get_shared_intel(
    recipient_owner_id="luigi_456",
    identifiers={
        "email": "marco.ferrari@client.com",
        "name": "Marco Ferrari"
    },
    limit=10
)
```

**Search process**:
1. Get all authorized senders for Luigi
2. For each sender, query their namespace (e.g., `shared:luigi_456:mario_123`)
3. Search for contact using email/phone/name identifiers
4. Match identifiers (case-insensitive email, last 9 digits for phone)
5. Return intel with sender attribution

**Result**:
```python
[
    SharedIntel(
        context="Marco Ferrari ha firmato il contratto",
        identifiers={"email": "marco.ferrari@client.com", "name": "Marco Ferrari"},
        sender_email="mario@example.com",
        sender_display_name="Mario Rossi",
        shared_at="2025-12-08T10:30:00Z",
        confidence=1.0,
        similarity=0.95
    )
]
```

**Displayed to user**:
```
📋 Informazioni condivise su Marco Ferrari:

🔹 Da Mario Rossi (mario@example.com) - 8 dic 2025
   "Marco Ferrari ha firmato il contratto"
```

## Implementation Details

### File References

**Core Services**:
- `zylch/sharing/authorization.py` - Authorization and user management (667 lines)
- `zylch/sharing/intel_share.py` - Intelligence sharing and retrieval (434 lines)

**Tools**:
- `zylch/tools/sharing_tools.py` - CLI tools for sharing (489 lines)
  - `ShareContactIntelTool` - Share intel with another user
  - `GetSharedIntelTool` - Retrieve shared intel about a contact
  - `AcceptShareRequestTool` - Accept pending share requests
  - `RejectShareRequestTool` - Reject share requests

**Command Handler**:
- `zylch/services/command_handlers.py:handle_sharing()` - CLI `/share` command dispatcher

### Database Schema

**`zylch_users` table** (SQLite):
```sql
CREATE TABLE zylch_users (
    owner_id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Purpose**: Maps Zylch users' emails to owner_ids for sharing lookups.

**`share_authorizations` table** (SQLite):
```sql
CREATE TABLE share_authorizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_email TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, accepted, rejected, revoked
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accepted_at TIMESTAMP NULL,
    revoked_at TIMESTAMP NULL,
    UNIQUE(sender_email, recipient_email)
);
```

**Purpose**: Tracks authorization state between sender-recipient pairs.

**`pending_shares` table** (SQLite):
```sql
CREATE TABLE pending_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    authorization_id INTEGER NOT NULL,
    intel_context TEXT NOT NULL,
    identifiers TEXT NOT NULL,  -- JSON: {"email": "...", "phone": "...", "name": "..."}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (authorization_id) REFERENCES share_authorizations(id)
);
```

**Purpose**: Queue for intel waiting for recipient acceptance.

**Shared Intel Storage** (Supabase pg_vector):

Shared intelligence is NOT stored in these tables. Instead, it goes to ZylchMemory:

```python
# Namespace pattern
namespace = f"shared:{recipient_owner_id}:{sender_owner_id}"

# Stored in memories table
memory_id = zylch_memory.store_memory(
    namespace=namespace,
    category="contact_intel",
    context="Marco Ferrari ha firmato il contratto",
    pattern=json.dumps({
        "sender_owner_id": "mario_123",
        "sender_email": "mario@example.com",
        "sender_display_name": "Mario Rossi",
        "identifiers": {"email": "marco.ferrari@client.com", "name": "Marco Ferrari"},
        "shared_at": "2025-12-08T10:30:00Z"
    }),
    force_new=True  # No reconsolidation for shared intel
)
```

### Key Classes

#### `SharingAuthorizationManager`

Manages authorization between Zylch users.

**Methods**:
- `register_user(owner_id, email, display_name)` → bool
  - Register a Zylch user for sharing
  - Called automatically on user login

- `register_recipient(sender_email, recipient_email)` → (bool, str)
  - Register a recipient for sharing (creates pending authorization)
  - Called by `/share <email>` command

- `accept_authorization(recipient_email, sender_email)` → (bool, str)
  - Accept sharing authorization from sender
  - Changes status from pending → accepted

- `reject_authorization(recipient_email, sender_email)` → (bool, str)
  - Reject sharing authorization
  - Changes status from pending → rejected

- `revoke_authorization(recipient_email, sender_email)` → (bool, str)
  - Revoke an accepted authorization
  - Changes status from accepted → revoked
  - Keeps existing shared intel visible

- `is_authorized(sender_email, recipient_email)` → bool
  - Check if sender can share with recipient
  - Returns True only if status = 'accepted'

- `list_authorized_senders(recipient_email)` → List[Dict]
  - List all users who can share with this recipient
  - Used when retrieving shared intel

- `get_pending_requests(recipient_email)` → List[Dict]
  - Get pending share requests for a recipient
  - Shown at session start for acceptance

**Private methods**:
- `add_pending_share(sender_email, recipient_email, intel_context, identifiers)` → (bool, str)
  - Add intel to pending queue when authorization is not yet accepted

- `get_pending_shares_for_authorization(auth_id)` → List[Dict]
  - Get all pending shares for a specific authorization

- `delete_pending_shares(auth_id)` → int
  - Delete pending shares after acceptance (moved to shared namespace)

#### `IntelShareManager`

Manages actual sharing and retrieval of contact intelligence.

**Methods**:
- `share_intel(sender_owner_id, sender_email, recipient_owner_id, recipient_email, context, identifiers, sender_display_name)` → (bool, str)
  - Share intelligence with recipient
  - Checks authorization before storing
  - Stores in shared namespace if accepted, or pending queue if pending

- `get_shared_intel(recipient_owner_id, identifiers, limit)` → List[SharedIntel]
  - Retrieve shared intel about a contact
  - Searches all authorized senders' namespaces
  - Matches by email/phone identifiers

- `process_accepted_authorization(recipient_owner_id, recipient_email, sender_email)` → int
  - Process pending shares after authorization is accepted
  - Moves intel from pending queue to shared namespace
  - Returns number of shares processed

**Private methods**:
- `_make_namespace(recipient_owner_id, sender_owner_id)` → str
  - Create namespace pattern: `shared:{recipient}:{sender}`

- `_identifiers_match(search_ids, stored_ids)` → bool
  - Check if identifiers match (email case-insensitive, phone last 9 digits)

- `_normalize_phone(phone)` → str
  - Normalize phone to digits only for comparison

#### `SharedIntel`

Data class representing a piece of shared intelligence.

**Attributes**:
- `memory_id` - ZylchMemory ID
- `context` - The intelligence text
- `identifiers` - Contact identifiers (email, phone, name)
- `sender_owner_id` - Who shared it
- `sender_email` - Sender's email
- `sender_display_name` - Sender's name
- `shared_at` - Timestamp
- `confidence` - Confidence score (1.0 for manual shares)
- `similarity` - Semantic similarity score from search

## Usage Examples

### Example 1: Registering a Recipient

**User intent**: "I want to share intel with my colleague Luigi"

```bash
/share luigi@example.com

# Output:
✅ Registrato Luigi (luigi@example.com) come destinatario.
   Quando condividerai info, Luigi dovrà accettare.
```

**What happens**:
1. Check if luigi@example.com is a Zylch user (lookup in zylch_users)
2. Create pending authorization in share_authorizations table
3. Luigi will see notification next time he logs in

### Example 2: Sharing Contact Intel

**User intent**: "Share with Luigi that Marco Ferrari signed the contract"

```
User: Condividi con Luigi che Marco Ferrari ha firmato il contratto

# AI agent extracts:
# - Recipient: Luigi (resolves to luigi@example.com)
# - Contact: Marco Ferrari
# - Intel: "Marco Ferrari ha firmato il contratto"

# Output (if authorization pending):
✅ Info in attesa di accettazione da parte di Luigi.
   Sarà visibile quando Luigi accetterà.

# Output (if authorization accepted):
✅ Condiviso con Luigi: Marco Ferrari - ha firmato il contratto
```

**What happens**:
1. AI calls `share_contact_intel` tool
2. Check authorization status (mario → luigi)
3. If pending: Add to pending_shares table
4. If accepted: Store in `shared:luigi_456:mario_123` namespace

### Example 3: Accepting Share Requests

**Scenario**: Luigi logs in and has pending request from Mario

```
# At session start:
📬 Hai 1 richiesta di condivisione da Mario Rossi (mario@example.com)
   - "Marco Ferrari ha firmato il contratto" e altre 2 info

User: Accetta la richiesta da Mario

# Output:
✅ Accettato. Mario può ora condividere informazioni con te.
   3 info già condivise sono ora visibili.
```

**What happens**:
1. AI calls `accept_share_request` tool
2. Update share_authorizations: status = 'accepted', accepted_at = NOW()
3. Call `process_accepted_authorization()`:
   - Fetch 3 pending shares from pending_shares table
   - For each, call `share_intel()` (now authorized, stores in namespace)
   - Delete from pending_shares table

### Example 4: Viewing Shared Intel

**User asks**: "What do you know about Marco Ferrari?"

**AI agent**:
1. Searches own knowledge base (emails, calendar, tasks)
2. **Automatically** calls `get_shared_intel` to include shared insights
3. Combines results

**Response**:
```
📋 Marco Ferrari (marco.ferrari@client.com)

📧 Tue email con Marco:
   - "Re: Contratto Q4" - 5 dic 2025
   - "Follow-up meeting" - 2 dic 2025

📅 1 evento nel calendario:
   - "Demo with Marco" - 10 dic 2025

🔹 Informazioni condivise:
   Da Mario Rossi - 8 dic 2025
   "Marco Ferrari ha firmato il contratto"
```

### Example 5: Revoking Authorization

**User intent**: "I don't want Mario to share intel with me anymore"

```bash
/revoke mario@example.com

# Output:
✅ Revocato. Mario non può più condividere informazioni con te.
   Le informazioni già condivise rimangono visibili.
```

**What happens**:
1. Update share_authorizations: status = 'revoked', revoked_at = NOW()
2. Future shares from Mario will be rejected
3. Existing shared intel in `shared:luigi_456:mario_123` remains accessible

## CLI Commands

### `/share <email>`
Register a recipient for sharing.

**Usage**:
```bash
/share luigi@example.com

# Output:
✅ Registrato Luigi (luigi@example.com) come destinatario.
   Quando condividerai info, Luigi dovrà accettare.
```

**Checks**:
- Email must be a registered Zylch user
- Creates pending authorization if new
- Returns existing status if already registered

### `/share --list`
List all authorized recipients.

**Output**:
```
📋 Destinatari autorizzati (2):

1. Luigi Bianchi (luigi@example.com)
   Accettato: 7 dic 2025

2. Giovanni Verdi (giovanni@example.com)
   Accettato: 5 dic 2025
```

### `/share --pending`
List pending authorizations waiting for acceptance.

**Output**:
```
⏳ Richieste in attesa (1):

1. Sara Neri (sara@example.com)
   Richiesta inviata: 8 dic 2025
```

### `/accept <email>` or `/accept`
Accept pending share request.

**Usage**:
```bash
# Accept specific sender
/accept mario@example.com

# Accept only pending request (if just one)
/accept

# Output:
✅ Accettato. Mario può ora condividere informazioni con te.
   3 info già condivise sono ora visibili.
```

### `/reject <email>`
Reject pending share request.

**Usage**:
```bash
/reject spam@example.com

# Output:
✅ Rifiutato. spam@example.com non potrà condividere informazioni con te.
```

### `/revoke <email>`
Revoke an accepted authorization.

**Usage**:
```bash
/revoke oldpartner@example.com

# Output:
✅ Revocato. oldpartner@example.com non può più condividere informazioni con te.
   Le informazioni già condivise rimangono visibili.
```

## Performance Characteristics

### Authorization Checks
- **Lookup time**: <5ms (indexed by sender_email, recipient_email)
- **Typical authorizations per user**: 5-20
- **Storage**: SQLite (local, fast)

### Sharing Intel
- **Accepted authorization**: <50ms (direct ZylchMemory write)
- **Pending authorization**: <10ms (SQLite INSERT)
- **Processing pending shares**: <200ms per share (batch on acceptance)

### Retrieval
- **Identifier lookup**: <30ms per sender namespace
- **Typical authorized senders**: 3-10
- **Total retrieval time**: <300ms for 10 senders
- **Results**: Sorted by shared_at (newest first)

### Storage Overhead
- **Authorization record**: ~100 bytes (SQLite)
- **Pending share**: ~500 bytes (includes intel + identifiers)
- **Shared intel**: ~1KB (ZylchMemory with embeddings)
- **Namespace count**: 1 per sender-recipient pair

## Security & Privacy

### Authorization Isolation
- Authorizations scoped by email pairs
- No cross-user authorization access
- SQLite database local to user (not shared)

### Data Isolation
- Shared intel stored in recipient-scoped namespaces
- Namespace pattern prevents cross-user access
- Only recipient can query their `shared:*` namespaces

### Consent Requirements
- **Explicit acceptance required** before intel is visible
- Pending shares kept in queue until acceptance
- Rejection blocks future shares
- Revocation stops future shares but preserves existing intel

### Input Validation
- Email addresses validated before registration
- Recipient must be registered Zylch user
- Contact identifiers sanitized before storage
- Intel context max length enforced (TBD: add limit)

## Known Limitations

1. **Local authorization storage**: SQLite database is local, not synced across devices
2. **No share modification**: Once shared, intel cannot be edited or deleted by sender
3. **No expiration**: Shared intel persists indefinitely (no TTL)
4. **No group sharing**: Must register each recipient individually
5. **No share notifications**: Recipient sees pending shares only at session start (no real-time push)
6. **Email-only registration**: Cannot register recipients by phone or name alone

## Future Enhancements

### Planned (Phase I+)
- **Supabase authorization sync**: Move share_authorizations to Supabase for multi-device sync
- **Share expiration**: Add TTL for time-sensitive intel
- **Share modification**: Allow sender to update or delete shared intel
- **Group sharing**: Share with multiple recipients in one command
- **Real-time notifications**: WebSocket push when new share requests arrive

### Optimization (Phase J - Scaling)
- **Batch sharing**: Share multiple intel items in one command
- **Share templates**: Pre-defined intel formats for common scenarios
- **Share analytics**: Track who shares what, when, and how often
- **Auto-sharing**: Trigger-based automatic sharing (e.g., "share all deals with sales team")

### Intelligence Improvements
- **Duplicate detection**: Prevent sharing intel already shared
- **Conflict resolution**: Merge conflicting intel from different senders
- **Trust scoring**: Weight intel by sender reliability
- **Share recommendations**: Suggest who to share intel with based on context

## Related Documentation

- **[Entity Memory System](entity-memory-system.md)** - Entity-centric memory with hybrid search
- **[Relationship Intelligence](relationship-intelligence.md)** - Contact intelligence enriched by shared intel
- **[Architecture](../ARCHITECTURE.md#sharing-system)** - Sharing system design philosophy

## References

**Source Code**:
- `zylch/sharing/authorization.py` - Authorization and user management (667 lines)
- `zylch/sharing/intel_share.py` - Intelligence sharing and retrieval (434 lines)
- `zylch/tools/sharing_tools.py` - CLI tools for sharing (489 lines)
- `zylch/services/command_handlers.py:handle_sharing()` - CLI command handler

**Database Tables**:
- `zylch_users` (SQLite) - Zylch user registry
- `share_authorizations` (SQLite) - Authorization state tracking
- `pending_shares` (SQLite) - Intel queue waiting for acceptance
- `memories` (Supabase pg_vector) - Shared intel storage with `shared:*` namespaces

---

**Last Updated**: December 2025
