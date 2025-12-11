# Zylch Avatar Database Installation Checklist

**Schema File**: `04_COMPLETE_SCHEMA.sql`
**For**: Virgin Supabase database installations
**Version**: 1.0.0

## Pre-Installation

### Environment
- [ ] Fresh Supabase project created
- [ ] Project is in a clean state (no existing tables)
- [ ] Database access confirmed (SQL Editor works)
- [ ] Service role key obtained from Supabase settings

### Prerequisites Check
```sql
-- Verify PostgreSQL version (should be 14+)
SELECT version();

-- Verify no existing tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public';
-- Should return empty or only Supabase defaults
```

## Installation Steps

### Step 1: Load Schema File
- [ ] Open `04_COMPLETE_SCHEMA.sql` in text editor
- [ ] Copy **entire** contents (723 lines)
- [ ] Open Supabase SQL Editor
- [ ] Paste contents into editor

### Step 2: Execute Schema
- [ ] Click "Run" button in SQL Editor
- [ ] Wait for completion (may take 10-30 seconds)
- [ ] Check for success message in output panel
- [ ] Look for verification output:
  ```
  NOTICE:  === Schema Installation Verification ===
  NOTICE:  Tables created: 14 of 14
  NOTICE:  Indices created: <count>
  NOTICE:  RLS policies created: <count>
  NOTICE:  ✓ All tables created successfully!
  ```

### Step 3: Verify Installation

#### Table Count
```sql
SELECT COUNT(*) as table_count
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'emails', 'sync_state', 'thread_analysis', 'relationship_gaps',
    'calendar_events', 'patterns', 'memories', 'avatars',
    'identifier_map', 'avatar_compute_queue', 'oauth_tokens',
    'triggers', 'trigger_events', 'sharing_auth'
  );
-- Expected: 14
```

- [ ] Result shows 14 tables

#### Extensions Check
```sql
SELECT extname FROM pg_extension
WHERE extname IN ('uuid-ossp', 'vector');
```

- [ ] `uuid-ossp` extension installed
- [ ] `vector` extension installed

#### RLS Enabled Check
```sql
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

- [ ] All 14 tables show `rowsecurity = true`

#### owner_id Type Check
```sql
SELECT
  table_name,
  column_name,
  data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND column_name = 'owner_id'
ORDER BY table_name;
```

- [ ] All `owner_id` columns show `data_type = text` (NOT uuid)

#### Index Count
```sql
SELECT COUNT(*) as index_count
FROM pg_indexes
WHERE schemaname = 'public';
```

- [ ] Index count > 30 (exact number varies by PG version)

#### RLS Policies Count
```sql
SELECT tablename, COUNT(*) as policy_count
FROM pg_policies
WHERE schemaname = 'public'
GROUP BY tablename
ORDER BY tablename;
```

- [ ] All tables have at least 1 policy
- [ ] `oauth_tokens`, `triggers`, `trigger_events`, `sharing_auth` have service_role policies

#### Helper Functions
```sql
SELECT proname
FROM pg_proc
WHERE proname IN ('queue_avatar_compute', 'get_stale_avatars', 'search_emails');
```

- [ ] `queue_avatar_compute` exists
- [ ] `get_stale_avatars` exists
- [ ] `search_emails` exists

## Post-Installation Configuration

### Backend Setup (Python)
- [ ] Install Supabase client: `pip install supabase`
- [ ] Set environment variables:
  ```bash
  SUPABASE_URL=https://your-project.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
  ```

### Test RLS Isolation
```python
from supabase import create_client

client = create_client(url, service_role_key)

# Test 1: Insert with user context
client.postgrest.headers['app.current_user_id'] = 'test_user_123'
result = client.table('avatars').insert({
    'owner_id': 'test_user_123',
    'contact_id': 'contact_1',
    'display_name': 'Test Contact'
}).execute()
```

- [ ] Insert succeeds
- [ ] Record created in `avatars` table

```python
# Test 2: Verify isolation
client.postgrest.headers['app.current_user_id'] = 'different_user_456'
result = client.table('avatars').select('*').execute()
# Should return empty (RLS blocks access to other user's data)
```

- [ ] Query returns empty result (RLS working)

```python
# Test 3: Service role bypass
client.postgrest.headers.pop('app.current_user_id', None)
result = client.table('avatars').select('*').execute()
# Should return all records (service role bypasses RLS)
```

- [ ] Query returns all records (service role working)

### Cleanup Test Data
```sql
DELETE FROM avatars WHERE owner_id IN ('test_user_123', 'different_user_456');
```

- [ ] Test records deleted successfully

## Functional Tests

### Email Archive Test
```python
# Insert test email
client.postgrest.headers['app.current_user_id'] = 'test_user'
client.table('emails').insert({
    'owner_id': 'test_user',
    'gmail_id': 'test_email_1',
    'thread_id': 'thread_1',
    'from_email': 'test@example.com',
    'subject': 'Test Email',
    'date': '2025-12-08T10:00:00Z',
    'body_plain': 'This is a test email'
}).execute()
```

- [ ] Email inserted successfully
- [ ] Full-text search index populated

### Avatar Compute Queue Test
```sql
SELECT queue_avatar_compute('test_user', 'contact_1', 'manual', 7);
```

- [ ] Function returns UUID
- [ ] Record appears in `avatar_compute_queue`
- [ ] Second call with same params updates priority (idempotent)

### Stale Avatars Test
```sql
-- Insert avatar with old last_computed
INSERT INTO avatars (owner_id, contact_id, display_name, last_computed, relationship_score)
VALUES ('test_user', 'contact_stale', 'Stale Contact', NOW() - INTERVAL '25 hours', 8);

-- Check staleness
SELECT * FROM get_stale_avatars('test_user', 24);
```

- [ ] Function returns stale contact
- [ ] `hours_since_update` is correct

## Production Readiness

### Security
- [ ] Service role key secured (not in git, environment variables only)
- [ ] RLS policies tested and working
- [ ] No sensitive data in code
- [ ] Encryption at rest enabled in Supabase settings

### Performance
- [ ] All indices created successfully
- [ ] Query performance acceptable for test data
- [ ] Connection pooling configured in backend

### Monitoring
- [ ] Supabase dashboard accessible
- [ ] Database metrics visible
- [ ] Logs working in Supabase

### Backup
- [ ] Automatic backups enabled in Supabase
- [ ] Point-in-time recovery configured
- [ ] Backup retention policy set

## Common Issues & Solutions

### Issue: Extensions not found
**Solution**: Run in SQL Editor:
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
```

### Issue: RLS blocking all queries
**Solution**: Ensure you're setting the runtime config:
```python
client.postgrest.headers['app.current_user_id'] = firebase_uid
```

### Issue: Foreign key violations
**Solution**: Check that `trigger_events.trigger_id` references exist:
```sql
-- Verify trigger exists before inserting event
SELECT id FROM triggers WHERE id = '<trigger_id>';
```

### Issue: Vector index creation fails
**Solution**: Create vector index AFTER populating data:
```sql
-- Wait until avatars table has data
CREATE INDEX idx_avatars_embedding ON avatars
    USING ivfflat (profile_embedding vector_cosine_ops)
    WITH (lists = 100);
```

## Sign-Off

Installation completed by: ___________________

Date: ___________________

Verified by: ___________________

Date: ___________________

### Final Checklist
- [ ] All 14 tables created
- [ ] All indices created
- [ ] All RLS policies active
- [ ] All helper functions working
- [ ] Backend connection tested
- [ ] RLS isolation verified
- [ ] Test data cleaned up
- [ ] Production ready

## Next Steps

1. **Integrate with Backend**
   - Update backend code to use new schema
   - Test all CRUD operations
   - Verify RLS behavior in production flow

2. **Deploy Application Code**
   - Update connection strings
   - Deploy backend services
   - Monitor for errors

3. **Populate Initial Data**
   - Run initial Gmail sync
   - Compute initial avatars
   - Verify data integrity

4. **Monitor & Optimize**
   - Watch query performance
   - Add additional indices if needed
   - Tune RLS policies as required

---

**Support**: Check `04_SCHEMA_SUMMARY.md` for detailed documentation
**Schema File**: `04_COMPLETE_SCHEMA.sql` (723 lines)
**Version**: 1.0.0
