-- ============================================
-- DROP ALL EXISTING TABLES AND FUNCTIONS
-- WARNING: This will DELETE ALL DATA permanently!
-- ============================================

-- Drop all tables in correct order (dependencies first)
DROP TABLE IF EXISTS trigger_events CASCADE;
DROP TABLE IF EXISTS triggers CASCADE;
DROP TABLE IF EXISTS sharing_auth CASCADE;
DROP TABLE IF EXISTS avatar_compute_queue CASCADE;
DROP TABLE IF EXISTS identifier_map CASCADE;
DROP TABLE IF EXISTS avatars CASCADE;
DROP TABLE IF EXISTS memories CASCADE;
DROP TABLE IF EXISTS patterns CASCADE;
DROP TABLE IF EXISTS calendar_events CASCADE;
DROP TABLE IF EXISTS relationship_gaps CASCADE;
DROP TABLE IF EXISTS thread_analysis CASCADE;
DROP TABLE IF EXISTS oauth_tokens CASCADE;
DROP TABLE IF EXISTS sync_state CASCADE;
DROP TABLE IF EXISTS emails CASCADE;

-- Drop helper functions
DROP FUNCTION IF EXISTS queue_avatar_compute(TEXT, TEXT, TEXT, INTEGER) CASCADE;
DROP FUNCTION IF EXISTS get_stale_avatars(TEXT, INTEGER) CASCADE;
DROP FUNCTION IF EXISTS search_emails(TEXT, TEXT, INT) CASCADE;

-- Verify all tables are dropped
DO $$
DECLARE
    v_table_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
          'emails', 'sync_state', 'thread_analysis', 'relationship_gaps',
          'calendar_events', 'patterns', 'memories', 'avatars',
          'identifier_map', 'avatar_compute_queue', 'oauth_tokens',
          'triggers', 'trigger_events', 'sharing_auth'
      );

    IF v_table_count = 0 THEN
        RAISE NOTICE '✓ All tables dropped successfully! Ready for fresh schema.';
    ELSE
        RAISE WARNING 'Some tables still exist: %', v_table_count;
    END IF;
END $$;
