-- Reset Zylch Database to Scratch
-- WARNING: This will DELETE ALL DATA from all tables
-- Use this for testing/development only

-- Delete all data from tables (in dependency order)
-- Note: Using DELETE instead of TRUNCATE to respect foreign keys

-- 1. Delete relationship gaps
DELETE FROM relationship_gaps;

-- 2. Delete task items
DELETE FROM task_items;

-- 3. Delete calendar events
DELETE FROM calendar_events;

-- 4. Delete patterns
DELETE FROM patterns;

-- 5. Delete blobs
DELETE FROM blobs;

-- 6. Delete emails
DELETE FROM emails;

-- 7. Delete sync state
DELETE FROM sync_state;

-- 8. Delete trigger events (optional - uncomment if exists)
-- DELETE FROM trigger_events;

-- 9. Delete triggers (optional - uncomment if exists)
-- DELETE FROM triggers;

-- 10. Delete sharing auth (optional - uncomment if exists)
-- DELETE FROM sharing_auth;

-- 11. Delete oauth tokens (optional - uncomment if you want to reset auth)
-- DELETE FROM oauth_tokens;

-- Verify cleanup
SELECT 'relationship_gaps' as table_name, COUNT(*) as remaining FROM relationship_gaps
UNION ALL
SELECT 'task_items', COUNT(*) FROM task_items
UNION ALL
SELECT 'calendar_events', COUNT(*) FROM calendar_events
UNION ALL
SELECT 'patterns', COUNT(*) FROM patterns
UNION ALL
SELECT 'blobs', COUNT(*) FROM blobs
UNION ALL
SELECT 'emails', COUNT(*) FROM emails
UNION ALL
SELECT 'sync_state', COUNT(*) FROM sync_state
ORDER BY table_name;

-- Success message
SELECT '✅ Database reset complete!' as status;
