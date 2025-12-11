# Complete Zylch Avatar Database Schema

**File**: `/Users/mal/hb/zylch/docs/integration/04_COMPLETE_SCHEMA.sql`
**Version**: 1.0.0
**Date**: 2025-12-08
**Purpose**: Virgin database installation for Supabase (NOT a migration)

## Overview

Complete SQL schema for fresh Zylch avatar system installation on Supabase. This is a **ground-zero setup**, not a migration script.

## Critical Details

### Owner ID Format
⚠️ **CRITICAL**: `owner_id` is `TEXT` (Firebase UID), **NOT** `UUID`

All tables use `TEXT` for `owner_id` to store Firebase authentication UIDs directly.

## Tables (14 Total)

### Core Email System
1. **emails** - Email archive with full-text search
2. **sync_state** - Gmail sync tracking per user
3. **thread_analysis** - Cached AI analysis of email threads
4. **relationship_gaps** - Detected relationship maintenance gaps
5. **calendar_events** - Calendar events for relationship context

### Memory & Learning
6. **patterns** - Learned behavioral patterns for AI personalization
7. **memories** - Long-term memory patterns and context

### Avatar Intelligence System
8. **avatars** - Contact profiles with AI-computed relationship intelligence
   - Includes: `relationship_summary`, `relationship_status`, `relationship_score`
   - Includes: `suggested_action`, `profile_embedding` (vector 384d)
   - Includes: `last_computed`, `compute_trigger`
9. **identifier_map** - Multi-identifier person resolution (email/phone → contact_id)
10. **avatar_compute_queue** - Background job processing queue for avatar computation

### Authentication & Integration
11. **oauth_tokens** - Encrypted OAuth tokens (Google/Microsoft/Anthropic)
12. **triggers** - Event-driven automation triggers
13. **trigger_events** - Background job queue for trigger execution
14. **sharing_auth** - Data sharing authorization between users

## Features Included

### ✅ Row Level Security (RLS)
- All 14 tables have RLS enabled
- Policies enforce `owner_id` isolation
- Service role bypass for backend operations
- Runtime configuration via `app.current_user_id` and `app.current_user_email`

### ✅ Performance Indices
- Primary indices on all foreign keys
- Composite indices on frequently queried columns
- Full-text search index on emails (GIN)
- Vector similarity indices (IVFFLAT) for embeddings

### ✅ Helper Functions
1. `queue_avatar_compute()` - Idempotent queue insertion
2. `get_stale_avatars()` - Find contacts needing recomputation
3. `search_emails()` - Full-text email search

### ✅ Data Integrity
- Foreign key constraints where appropriate
- UNIQUE constraints to prevent duplicates
- CHECK constraints for enum validation
- DEFAULT values for common fields

## Installation Steps

### 1. Prerequisites
- Fresh Supabase project
- Database access via SQL Editor
- No existing tables (virgin database)

### 2. Execute Schema
```sql
-- Copy entire contents of 04_COMPLETE_SCHEMA.sql
-- Paste into Supabase SQL Editor
-- Execute
```

### 3. Verify Installation
The script includes verification at the end:
```
=== Schema Installation Verification ===
Tables created: 14 of 14
Indices created: <count>
RLS policies created: <count>
✓ All tables created successfully!
```

### 4. Post-Installation (Optional)
After populating avatar data, create vector index:
```sql
CREATE INDEX idx_avatars_embedding ON avatars
    USING ivfflat (profile_embedding vector_cosine_ops)
    WITH (lists = 100);
```

## RLS Configuration

### Backend Setup (Python)
```python
from supabase import create_client

# Service role key (bypasses RLS)
client = create_client(url, service_role_key)

# Set user context for operations
client.postgrest.headers.update({
    'app.current_user_id': firebase_uid,
    'app.current_user_email': user_email
})
```

### PostgreSQL Direct
```sql
SET app.current_user_id = '<firebase_uid>';
SET app.current_user_email = '<user_email>';
```

## Key Differences from Main Schema

The main schema (`supabase_schema.sql`) used `UUID` for `owner_id`. This complete schema uses `TEXT` throughout for Firebase UID compatibility.

### Migration Notes
If migrating from UUID schema:
```sql
ALTER TABLE <table_name>
ALTER COLUMN owner_id TYPE TEXT;
```

## Table Relationships

```
users (implicit, via owner_id TEXT)
  └─> emails (owner_id)
  └─> sync_state (owner_id)
  └─> thread_analysis (owner_id)
  └─> relationship_gaps (owner_id)
  └─> calendar_events (owner_id)
  └─> patterns (owner_id)
  └─> memories (owner_id)
  └─> avatars (owner_id)
  └─> identifier_map (owner_id)
  └─> avatar_compute_queue (owner_id)
  └─> oauth_tokens (owner_id)
  └─> triggers (owner_id)
  └─> trigger_events (owner_id)
  └─> sharing_auth (sender_id)

avatars.contact_id <─> identifier_map.contact_id
avatars.contact_id <─> avatar_compute_queue.contact_id
triggers.id <─> trigger_events.trigger_id (FK)
```

## Extensions Required

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- UUID generation
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector for embeddings
```

## Testing Checklist

After installation, verify:

- [ ] All 14 tables exist
- [ ] All indices created
- [ ] RLS enabled on all tables
- [ ] RLS policies prevent cross-user access
- [ ] Service role can access all tables
- [ ] Helper functions work correctly
- [ ] Extensions installed (uuid-ossp, vector)
- [ ] `owner_id` is TEXT type on all tables

## Support

**Created for**: External testers and virgin Supabase installations
**Maintained in**: `/Users/mal/hb/zylch/docs/integration/`
**Memory key**: `complete_schema` (stored in ReasoningBank)

## Version History

- **1.0.0** (2025-12-08): Initial complete schema for virgin database
  - 14 tables with TEXT owner_id
  - Full RLS policies
  - All indices and helper functions
  - Ready for copy-paste installation
