-- Reset Zylch Database to Scratch
-- WARNING: This will DELETE ALL DATA from all tables
-- Use this for testing/development only

-- Delete all data from tables (in dependency order)
-- Note: Using DELETE instead of TRUNCATE to respect foreign keys

-- 1. Delete avatar computation queue
DELETE FROM avatar_compute_queue;

-- 2. Delete avatars
DELETE FROM avatars;

-- 3. Delete identifier map
DELETE FROM identifier_map;

-- 4. Delete relationship gaps
DELETE FROM relationship_gaps;

-- 5. Delete thread analysis
DELETE FROM thread_analysis;

-- 6. Delete calendar events
DELETE FROM calendar_events;

-- 7. Delete patterns
DELETE FROM patterns;

-- 8. Delete memories
DELETE FROM memories;

-- 9. Delete emails
DELETE FROM emails;

-- 10. Delete sync state
DELETE FROM sync_state;

-- 11. Delete trigger events (optional - uncomment if exists)
-- DELETE FROM trigger_events;

-- 12. Delete triggers (optional - uncomment if exists)
-- DELETE FROM triggers;

-- 13. Delete sharing auth (optional - uncomment if exists)
-- DELETE FROM sharing_auth;

-- 14. Delete oauth tokens (optional - uncomment if you want to reset auth)
-- DELETE FROM oauth_tokens;

-- Verify cleanup
SELECT 'avatar_compute_queue' as table_name, COUNT(*) as remaining FROM avatar_compute_queue
UNION ALL
SELECT 'avatars', COUNT(*) FROM avatars
UNION ALL
SELECT 'identifier_map', COUNT(*) FROM identifier_map
UNION ALL
SELECT 'relationship_gaps', COUNT(*) FROM relationship_gaps
UNION ALL
SELECT 'thread_analysis', COUNT(*) FROM thread_analysis
UNION ALL
SELECT 'calendar_events', COUNT(*) FROM calendar_events
UNION ALL
SELECT 'patterns', COUNT(*) FROM patterns
UNION ALL
SELECT 'memories', COUNT(*) FROM memories
UNION ALL
SELECT 'emails', COUNT(*) FROM emails
UNION ALL
SELECT 'sync_state', COUNT(*) FROM sync_state
ORDER BY table_name;

-- Success message
SELECT '✅ Database reset complete!' as status;
