---
description: |
  Multi-tenant system where each owner (Firebase UID) has complete data isolation via PostgreSQL with owner_id filtering.
  Currently limited to single-assistant mode (one Zylch assistant per owner, auto-created as
  default_assistant). Namespace structure is {owner}:{assistant}:{contact} for future multi-assistant
  expansion. Each tenant gets separate business info, contacts, memories with zero data leakage.
---

# Multi-Tenant Architecture

**Complete guide to Zylch AI's multi-tenant person-centric memory system**

---

## 🚨 Current Limitation (v0.2.0)

**Single-Assistant Mode**: Currently, each owner can have only **ONE** Zylch assistant.

- ✅ Auto-created on first startup as `default_assistant`
- ✅ `/assistant --create` blocked if assistant already exists
- ✅ Simplifies development without requiring StarChat modifications
- ✅ Architecture ready for multi-assistant support in future versions

**Why?** This allows us to move forward without requiring changes to StarChat while maintaining the multi-tenant namespace structure (`{owner}:{assistant}:{contact}`) for future expansion.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Namespace Structure](#namespace-structure)
4. [Configuration](#configuration)
5. [CLI Commands](#cli-commands)
6. [Use Cases](#use-cases)
7. [AssistantManager Service](#assistantmanager-service)
8. [Migration Guide](#migration-guide)

---

## Overview

Zylch AI implements a **complete multi-tenant architecture** that enables:

- ✅ **Multiple owners**: Each owner (Firebase UID) has complete data isolation
- ⚠️ **Single assistant per owner** (current limitation, see above)
- ✅ **Complete workspace isolation**: Each owner has separate business info, contacts, memories
- ✅ **Scalable to thousands of users**: No data leakage between tenants
- ✅ **Person-centric memory**: Auto-populated relationship intelligence per contact
- ✅ **Future-ready structure**: Namespace architecture supports multi-assistant when needed

### Key Features

- 🏢 **Multi-Tenant**: Complete isolation per owner (Firebase UID)
- 🤖 **Single-Assistant Mode**: One assistant per owner (v0.2.0 limitation)
- 👤 **Person-Centric**: Semantic memory per contact with HNSW vector search
- 🔒 **Zero Data Leakage**: `{owner}:{zylch_assistant_id}` namespace structure
- 📊 **Relationship Intelligence**: Auto-populated from email history
- 🎯 **Business Context Injection**: Always remembers what the business sells
- 🚀 **Future-Ready**: Architecture supports multi-assistant expansion

---

## Architecture

### The Problem

Original Zylch used global namespaces like `"business"` and `"person:{email}"`. This would create **catastrophic data leakage** in a multi-tenant system:

```
❌ WRONG: Global namespace
namespace = "business"  → All users share same business info!
namespace = "person:mario@example.com"  → All assistants share same contact!
```

### The Solution: Owner + Assistant Scoped Namespaces

Every piece of data is scoped to `{owner}:{zylch_assistant_id}`:

```python
# Business-level data
namespace = f"{owner}:{zylch_assistant_id}"
category = "business" | "config" | "style"

# Person-level data
namespace = f"{owner}:{zylch_assistant_id}:{contact_id}"
category = "person" | "relationship"
```

**Example:**
```
owner_mario:mrcall_assistant              → category="business"
owner_mario:mrcall_assistant:contact_123  → category="person"

owner_mario:caffe_assistant               → category="business"  (ISOLATED!)
owner_mario:caffe_assistant:contact_456   → category="person"   (ISOLATED!)
```

### Why Two-Level Isolation?

**Owner-level isolation:**
- Different companies/people don't see each other's data
- Firebase UID as tenant identifier
- Example: `owner_mario` vs `owner_luigi`

**Assistant-level isolation:**
- Same owner can run multiple completely different businesses
- Example: Mario runs both "MrCall Telecom" and "Caffè Rosso"
- Zero data sharing between assistants!

---

## Namespace Structure

### Namespace Patterns

| Data Type | Namespace | Category | Example |
|-----------|-----------|----------|---------|
| Business info | `{owner}:{zylch_assistant_id}` | `business` | Mission, services, pricing |
| Email style | `{owner}:{zylch_assistant_id}` | `style` | Email writing preferences |
| Config | `{owner}:{zylch_assistant_id}` | `config` | Assistant configuration |
| Person memory | `{owner}:{zylch_assistant_id}:{contact_id}` | `person` | Relationship intelligence |

### Complete Isolation Example

```python
# Owner: owner_mario
# Assistant 1: mrcall_assistant (telecom business)
"owner_mario:mrcall_assistant"
  → category="business"
  → "We sell AI phone assistants for SMBs"

"owner_mario:mrcall_assistant:contact_123"
  → category="person"
  → "Tech-savvy customer, prefers email, interested in APIs"

# Assistant 2: caffe_assistant (coffee shop)
"owner_mario:caffe_assistant"
  → category="business"
  → "We sell artisan coffee and pastries"

"owner_mario:caffe_assistant:contact_456"
  → category="person"
  → "Local customer, regular morning visits, likes cappuccino"
```

**Zero overlap!** Even though same owner, the two assistants are completely isolated.

---

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Multi-tenant Configuration
OWNER_ID=owner_default              # Firebase UID or placeholder
ZYLCH_ASSISTANT_ID=default_assistant  # Assistant identifier
```

### Production Environment (Railway)

```bash
# Encryption key for OAuth tokens and API keys
ENCRYPTION_KEY=<fernet-key>
# Generate: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

**Important:** Store `ENCRYPTION_KEY` only in Railway, never in Supabase or version control. Local development can run without encryption (single-tenant mode).

### Config Settings

In `zylch/config.py`:

```python
class Settings(BaseSettings):
    # Multi-tenant Configuration
    owner_id: str = Field(
        default="owner_default",
        description="Owner ID (Firebase UID or placeholder)"
    )
    zylch_assistant_id: str = Field(
        default="default_assistant",
        description="Zylch assistant ID"
    )
```

### Placeholder Mode (Development)

For development/testing without Firebase:

```bash
OWNER_ID=owner_mario
ZYLCH_ASSISTANT_ID=mrcall_assistant
```

Later migrate to Firebase authentication for production.

---

## CLI Commands

### `/assistant` - Manage Zylch Assistant

View and manage your Zylch assistant (single-assistant mode).

```bash
# Show current assistant
/assistant

# List your assistant
/assistant --list

# Create assistant (only works if none exists)
/assistant --create "My Business"

# Switch assistant (requires restart)
/assistant --id default_assistant

# Help
/assistant --help
```

**⚠️ Single-Assistant Mode Behavior:**

```bash
# First assistant creation (auto-created on startup)
→ ✅ Auto-created default assistant: default_assistant

# Viewing current assistant
/assistant
→ 📌 Current Zylch Assistant
   Owner ID: owner_mario
   Assistant ID: default_assistant
   Name: Default Assistant (owner_mario)
   MrCall link: Not linked

# Attempting to create second assistant
/assistant --create "Second Business"
→ ❌ Owner 'owner_mario' already has an assistant: 'default_assistant'
   For now, only ONE assistant per owner is supported.
   Use /assistant to view current assistant or /mrcall --id to link MrCall

# List assistants
/assistant --list
→ 📋 Your Zylch Assistant
   ⚠️  Single-assistant mode: Only 1 assistant per owner

   ✅ 1. Default Assistant (owner_mario) (default_assistant)
      Business: N/A
      MrCall: Not linked
```

### `/mrcall` - Link MrCall/StarChat Assistant

Connect your Zylch assistant to a MrCall assistant for contact management.

```bash
# Show current MrCall link
/mrcall

# List available MrCall assistants (coming soon)
/mrcall --list

# Link to MrCall assistant
/mrcall --id hahnbanach_personal

# Help
/mrcall --help
```

**What does linking do?**

When you link a Zylch assistant to a MrCall assistant:
- All enriched contacts are saved to that MrCall assistant's contact list
- Contacts are isolated per MrCall assistant
- Different Zylch assistants can link to different MrCall assistants

**Example:**

```bash
# Link MrCall assistant to save contacts
/mrcall --id hahnbanach_personal
→ ✅ Linked to MrCall assistant: hahnbanach_personal
   All enriched contacts will be saved to this assistant
```

---

## Use Cases

### Use Case 1: Single Business per Owner (Current)

**Scenario:** Mario owns MrCall telecom company and uses Zylch for sales intelligence.

**Setup:**

```bash
# 1. First startup - auto-creates assistant
python -m zylch.cli.main
→ ✅ Auto-created default assistant: default_assistant

# 2. Populate business memory
python scripts/populate_business_memory.py
→ Namespace: owner_mario:default_assistant
→ Category: business
→ Content: "We sell AI phone assistants for SMBs..."

# 3. Link to MrCall assistant for contacts
/mrcall --id hahnbanach_personal
→ ✅ Linked to MrCall assistant: hahnbanach_personal
```

**Result:**
- Single assistant with complete business context
- All contacts linked to MrCall assistant
- Ready for multi-assistant expansion in future

**Future (Multi-Assistant Support):** When we add multi-assistant support, Mario will be able to create separate assistants for different businesses (e.g., MrCall + Caffè Rosso) with complete isolation.

### Use Case 2: Multi-Tenant SaaS

**Scenario:** Zylch deployed for 1000s of customers.

**Setup:**

```python
# Customer 1: owner_company_a, assistant: sales_assistant
namespace = "owner_company_a:sales_assistant"
→ Company A's business info, contacts, memories

# Customer 2: owner_company_b, assistant: sales_assistant
namespace = "owner_company_b:sales_assistant"
→ Company B's business info, contacts, memories (ISOLATED!)
```

**Benefits:**
- ✅ Complete tenant isolation
- ✅ Each customer has private workspace
- ✅ Scalable to millions of users
- ✅ No data leakage risk

### Use Case 3: Person-Centric Memory

**Scenario:** Build relationship intelligence from email history.

**Workflow:**

```bash
# 1. Sync emails (last 30 days)
/sync 30

# 2. Build person memories from email threads
/memory --build --days 30

→ Processing contacts...
→ Analyzing relationships with AI...
→ Storing in namespace: owner_mario:mrcall_assistant:contact_123

# 3. Draft personalized email
"Draft email to sig. Rossi about new features"

→ Retrieves memories:
   - Namespace: owner_mario:mrcall_assistant:contact_123
   - Category: person
   - Content: "Tech-savvy, prefers technical details, uses 'tu'"

→ Drafts email with personalized style!
```

---

## AssistantManager Service

### Overview

JSON-based service to manage multiple assistants per owner.

**Storage:** `cache/zylch_assistants.json`

**Schema:**

```json
{
  "owner_mario": {
    "owner_id": "owner_mario",
    "assistants": [
      {
        "id": "mrcall_assistant",
        "name": "MrCall Telecom",
        "mrcall_assistant_id": "hahnbanach_personal",
        "business_type": "telecom",
        "created_at": "2025-11-27T10:00:00",
        "updated_at": "2025-11-27T10:00:00"
      },
      {
        "id": "caffe_assistant",
        "name": "Caffè Rosso",
        "mrcall_assistant_id": null,
        "business_type": "retail",
        "created_at": "2025-11-27T11:00:00",
        "updated_at": "2025-11-27T11:00:00"
      }
    ]
  }
}
```

### Programmatic Usage

```python
from zylch.services.assistant_manager import AssistantManager

# Initialize
manager = AssistantManager()

# Create assistant
assistant = manager.create_assistant(
    owner_id="owner_mario",
    zylch_assistant_id="mrcall_assistant",
    name="MrCall Telecom",
    business_type="telecom"
)

# List assistants
assistants = manager.list_assistants("owner_mario")

# Get specific assistant
assistant = manager.get_assistant("owner_mario", "mrcall_assistant")

# Link to MrCall assistant
manager.link_mrcall_assistant(
    owner_id="owner_mario",
    zylch_assistant_id="mrcall_assistant",
    mrcall_assistant_id="hahnbanach_personal"
)
```

---

## Migration Guide

### From Single-Tenant to Multi-Tenant

**Before:**
```python
namespace = "business"  # Global!
namespace = f"person:{email}"  # No owner isolation!
```

**After:**
```python
namespace = f"{owner_id}:{zylch_assistant_id}"  # Isolated!
namespace = f"{owner_id}:{zylch_assistant_id}:{contact_id}"  # Person-level!
```

### Migration Steps

1. **Update `.env`:**
   ```bash
   OWNER_ID=owner_default
   ZYLCH_ASSISTANT_ID=default_assistant
   ```

2. **Re-populate business memory:**
   ```bash
   python scripts/populate_business_memory.py
   ```

   This will create memories with new namespace structure.

3. **Rebuild person memories:**
   ```bash
   /memory --build --days 30 --force
   ```

   This will rebuild all person memories with correct namespaces.

4. **Verify isolation:**
   ```bash
   # Check memory database
   sqlite3 cache/zylch_memory.db

   sqlite> SELECT DISTINCT namespace FROM memories;
   → owner_default:default_assistant
   → owner_default:default_assistant:contact_123
   ```

### Data Migration Script

For migrating existing memories from old structure:

```python
import sqlite3

conn = sqlite3.connect("cache/zylch_memory.db")
cursor = conn.cursor()

# Migrate business memories
cursor.execute("""
    UPDATE memories
    SET namespace = 'owner_default:default_assistant'
    WHERE namespace = 'business'
""")

# Migrate person memories
cursor.execute("""
    UPDATE memories
    SET namespace = 'owner_default:default_assistant:' ||
                    REPLACE(namespace, 'person:', '')
    WHERE namespace LIKE 'person:%'
""")

conn.commit()
conn.close()
```

---

## Architecture Benefits

### Scalability

- ✅ **Linear scaling**: Each namespace is independent
- ✅ **HNSW indexing**: O(log n) semantic search per namespace
- ✅ **No cross-tenant queries**: Automatic isolation
- ✅ **Efficient storage**: SQLite + HNSW indices

### Security

- ✅ **Zero data leakage**: Namespace-based isolation
- ✅ **Firebase integration ready**: Owner = Firebase UID
- ✅ **Row-level security**: Every query includes namespace filter
- ✅ **Audit trail**: Track who accessed what
- ✅ **Encryption at rest**: OAuth tokens and API keys encrypted with Fernet (AES-128-CBC + HMAC)
- ✅ **Key separation**: Encryption key in Railway, encrypted data in Supabase (neither alone can decrypt)

### Developer Experience

- ✅ **Simple API**: Just add `owner_id` and `zylch_assistant_id`
- ✅ **Backward compatible**: Defaults to `owner_default`
- ✅ **Easy testing**: Use different owner IDs for test isolation
- ✅ **Clear semantics**: `{owner}:{assistant}:{contact}` structure

---

## Technical Implementation

### Files Modified

**Core system:**
- `zylch/config.py` - Added owner_id and zylch_assistant_id settings
- `zylch/tools/task_manager.py` - Multi-tenant person memory
- `zylch/tools/factory.py` - DraftEmailFromMemoryTool multi-tenant
- `zylch/cli/main.py` - CLI commands and initialization
- `scripts/populate_business_memory.py` - Multi-tenant business memory

**New files:**
- `zylch/services/assistant_manager.py` - AssistantManager service
- `zylch/services/__init__.py` - Services module init

### Namespace Filtering

All memory operations automatically filter by namespace:

```python
# ZylchMemory core (zylch_memory/core.py)
def retrieve_memories(
    self,
    query: str,
    namespace: str,  # REQUIRED!
    category: Optional[str] = None,
    limit: int = 5
) -> List[Dict]:
    """Retrieve memories with namespace isolation."""

    # Get index for this namespace
    index = self._get_or_create_index(namespace)

    # Search only within this namespace
    labels, distances = index.search(query_vector, k=limit)

    # Fetch from storage with namespace filter
    memories = self.storage.get_memories_by_namespace(
        namespace, category, limit=100
    )
```

**Key points:**
- ✅ Every namespace has separate HNSW index
- ✅ Searches are isolated by design
- ✅ No risk of cross-namespace leakage
- ✅ Efficient: Only searches relevant index

---

## Best Practices

### Naming Conventions

**Owner IDs:**
- Development: `owner_mario`, `owner_luigi`
- Production: Firebase UID (e.g., `VQzJpP3cNKhFdMGHPzK8XYwqN9s1`)

**Assistant IDs:**
- Use descriptive names: `mrcall_assistant`, `caffe_assistant`
- Lowercase with underscores
- No spaces or special characters

**Contact IDs:**
- Use StarChat contact ID when available
- Fallback: `email_{email.replace('@', '_at_')}`

### Multi-Assistant Workflow

1. **One assistant per business/use case**
2. **Completely separate business info** per assistant
3. **Link each to appropriate MrCall assistant** for contacts
4. **Rebuild memories** when switching assistants
5. **Clear naming** to avoid confusion

### Memory Population

```bash
# For each assistant:

# 1. Switch to assistant
# Update ZYLCH_ASSISTANT_ID in .env
# Restart Zylch

# 2. Populate business memory
python scripts/populate_business_memory.py

# 3. Build person memories
/memory --build --days 30

# 4. Link MrCall assistant (optional)
/mrcall --id <mrcall_assistant_id>
```

---

## Future Enhancements

### Phase 2: Multi-Assistant Support

- [ ] Remove single-assistant constraint
- [ ] Enable `/assistant --create` for multiple assistants
- [ ] StarChat integration for per-assistant contacts
- [ ] UI for switching between assistants
- [ ] Memory migration tools (move data between assistants)

### Phase 3: Firebase Integration

- [ ] Replace placeholder owner_id with Firebase UID
- [ ] Automatic tenant provisioning on user signup
- [ ] Row-level security rules in Firebase
- [ ] JWT-based authentication

### Phase 4: Advanced Features

- [ ] `/mrcall --list` - List MrCall assistants from StarChat API
- [ ] Assistant templates (quick setup for common business types)
- [ ] Analytics per assistant (usage, costs, performance)

---

## References

### Documentation
- **ZylchMemory Architecture**: `zylch_memory/ZYLCH_MEMORY_ARCHITECTURE.md`
- **Entity Memory System**: `docs/features/entity-memory-system.md`
- **Quick Start**: `docs/setup/quick-start.md`

### Implementation
- **AssistantManager**: `zylch/services/assistant_manager.py`
- **TaskManager**: `zylch/tools/task_manager.py`
- **DraftEmailFromMemoryTool**: `zylch/tools/factory.py`
- **CLI Commands**: `zylch/cli/main.py`

---

## Summary

Zylch AI's multi-tenant architecture enables:

✅ **Complete isolation** per owner and assistant
✅ **Scalable to thousands of users** with zero data leakage
✅ **Person-centric memory** with semantic search
✅ **Multiple businesses per owner** (completely isolated)
✅ **Simple namespace structure**: `{owner}:{assistant}:{contact}`

**Next steps:** See [Quick Start Guide](../setup/quick-start.md) to get started!
