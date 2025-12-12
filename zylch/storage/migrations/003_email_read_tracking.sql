-- =====================================================================
-- Migration: 003_email_read_tracking
-- Description: Add email read tracking tables and columns
-- Created: 2025-12-12
-- =====================================================================

-- =====================================================================
-- SECTION 1: email_read_events TABLE
-- Tracks all email read events with dual tracking support:
-- - SendGrid webhook events (for batch emails)
-- - Custom tracking pixel events (for individual emails)
-- =====================================================================

CREATE TABLE email_read_events (
    -- Primary identification
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tracking_id TEXT,  -- NULL for SendGrid webhook events
    sendgrid_message_id TEXT,  -- NULL for custom pixel events

    -- Multi-tenant isolation
    owner_id TEXT NOT NULL,

    -- Email reference
    message_id TEXT NOT NULL,  -- References messages table
    recipient_email TEXT NOT NULL,

    -- Tracking source
    tracking_source TEXT NOT NULL,  -- 'sendgrid_webhook' or 'custom_pixel'

    -- Read tracking
    read_count INTEGER DEFAULT 0,
    first_read_at TIMESTAMPTZ,
    last_read_at TIMESTAMPTZ,

    -- Metadata
    user_agents TEXT[],  -- Track all user agents (email clients)
    ip_addresses TEXT[], -- Track all IPs (optional, privacy consideration)

    -- SendGrid specific data
    sendgrid_event_data JSONB,  -- Store full SendGrid webhook payload

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT check_tracking_identifier
        CHECK (
            (tracking_source = 'sendgrid_webhook' AND sendgrid_message_id IS NOT NULL) OR
            (tracking_source = 'custom_pixel' AND tracking_id IS NOT NULL)
        ),
    CONSTRAINT check_tracking_source
        CHECK (tracking_source IN ('sendgrid_webhook', 'custom_pixel'))
);

-- =====================================================================
-- INDEXES for email_read_events
-- Optimized for performance on common query patterns
-- =====================================================================

-- Multi-tenant queries
CREATE INDEX idx_email_read_events_owner_id
    ON email_read_events(owner_id);

-- Message-based queries (most common)
CREATE INDEX idx_email_read_events_message_id
    ON email_read_events(message_id);

-- Custom pixel lookups
CREATE INDEX idx_email_read_events_tracking_id
    ON email_read_events(tracking_id)
    WHERE tracking_id IS NOT NULL;

-- SendGrid webhook lookups
CREATE INDEX idx_email_read_events_sendgrid_msg_id
    ON email_read_events(sendgrid_message_id)
    WHERE sendgrid_message_id IS NOT NULL;

-- Recipient-based queries
CREATE INDEX idx_email_read_events_recipient
    ON email_read_events(recipient_email);

-- Time-based queries
CREATE INDEX idx_email_read_events_first_read
    ON email_read_events(first_read_at);

-- Analytics and filtering
CREATE INDEX idx_email_read_events_tracking_source
    ON email_read_events(tracking_source);

-- Composite index for common query pattern: owner + message
CREATE INDEX idx_email_read_events_owner_message
    ON email_read_events(owner_id, message_id);

-- =====================================================================
-- ROW LEVEL SECURITY for email_read_events
-- Enforce multi-tenant data isolation
-- =====================================================================

ALTER TABLE email_read_events ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only view their own read events
CREATE POLICY "Users can only see their own read events"
    ON email_read_events
    FOR SELECT
    USING (owner_id = current_setting('app.owner_id', true));

-- Policy: Users can only insert their own read events
CREATE POLICY "Users can only insert their own read events"
    ON email_read_events
    FOR INSERT
    WITH CHECK (owner_id = current_setting('app.owner_id', true));

-- Policy: Users can only update their own read events
CREATE POLICY "Users can only update their own read events"
    ON email_read_events
    FOR UPDATE
    USING (owner_id = current_setting('app.owner_id', true))
    WITH CHECK (owner_id = current_setting('app.owner_id', true));

-- =====================================================================
-- SECTION 2: sendgrid_message_mapping TABLE
-- Maps SendGrid message IDs to Zylch message IDs for webhook processing
-- =====================================================================

CREATE TABLE sendgrid_message_mapping (
    -- SendGrid message ID (from webhook)
    sendgrid_message_id TEXT PRIMARY KEY,

    -- Zylch message ID (internal)
    message_id TEXT NOT NULL,

    -- Multi-tenant isolation
    owner_id TEXT NOT NULL,

    -- Recipient for this specific message
    recipient_email TEXT NOT NULL,

    -- Campaign/batch information
    campaign_id TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '90 days'  -- Auto-cleanup after 90 days
);

-- =====================================================================
-- INDEXES for sendgrid_message_mapping
-- =====================================================================

-- Lookup by Zylch message ID
CREATE INDEX idx_sendgrid_mapping_message_id
    ON sendgrid_message_mapping(message_id);

-- Multi-tenant queries
CREATE INDEX idx_sendgrid_mapping_owner_id
    ON sendgrid_message_mapping(owner_id);

-- Cleanup queries for expired entries
CREATE INDEX idx_sendgrid_mapping_expires
    ON sendgrid_message_mapping(expires_at)
    WHERE expires_at IS NOT NULL;

-- Campaign-based queries
CREATE INDEX idx_sendgrid_mapping_campaign
    ON sendgrid_message_mapping(campaign_id)
    WHERE campaign_id IS NOT NULL;

-- =====================================================================
-- ROW LEVEL SECURITY for sendgrid_message_mapping
-- =====================================================================

ALTER TABLE sendgrid_message_mapping ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only view their own mappings
CREATE POLICY "Users can only see their own mappings"
    ON sendgrid_message_mapping
    FOR SELECT
    USING (owner_id = current_setting('app.owner_id', true));

-- Policy: Users can only insert their own mappings
CREATE POLICY "Users can only insert their own mappings"
    ON sendgrid_message_mapping
    FOR INSERT
    WITH CHECK (owner_id = current_setting('app.owner_id', true));

-- =====================================================================
-- SECTION 3: MODIFY messages TABLE
-- Add read_events JSONB column for quick summary access
-- =====================================================================

-- Add new column to messages table
ALTER TABLE messages
ADD COLUMN read_events JSONB DEFAULT '[]'::jsonb;

-- Add comment to column
COMMENT ON COLUMN messages.read_events IS 'Summary of read events per recipient. Format: [{"recipient": "email@example.com", "read_count": 3, "first_read_at": "2025-12-12T10:30:00Z", "last_read_at": "2025-12-12T14:45:00Z"}]';

-- =====================================================================
-- INDEX for messages.read_events
-- GIN index for efficient JSONB queries
-- =====================================================================

CREATE INDEX idx_messages_read_events
    ON messages USING GIN (read_events);

-- =====================================================================
-- HELPER FUNCTIONS
-- Utility functions for common operations
-- =====================================================================

-- Function: Get read statistics for a message
CREATE OR REPLACE FUNCTION get_message_read_stats(p_message_id TEXT)
RETURNS TABLE (
    total_recipients BIGINT,
    total_reads BIGINT,
    unique_reads BIGINT,
    read_rate NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        jsonb_array_length(m.read_events)::BIGINT as total_recipients,
        COALESCE(SUM((event->>'read_count')::INT), 0)::BIGINT as total_reads,
        COUNT(DISTINCT event->>'recipient')::BIGINT as unique_reads,
        CASE
            WHEN jsonb_array_length(m.read_events) > 0
            THEN ROUND(
                COUNT(DISTINCT event->>'recipient')::NUMERIC /
                jsonb_array_length(m.read_events)::NUMERIC,
                2
            )
            ELSE 0
        END as read_rate
    FROM messages m
    CROSS JOIN LATERAL jsonb_array_elements(m.read_events) as event
    WHERE m.id = p_message_id
    GROUP BY m.id, m.read_events;
END;
$$ LANGUAGE plpgsql;

-- Function: Cleanup expired SendGrid mappings
CREATE OR REPLACE FUNCTION cleanup_expired_sendgrid_mappings()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM sendgrid_message_mapping
    WHERE expires_at IS NOT NULL
    AND expires_at < NOW();

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Function: Cleanup old read events (90 day retention)
CREATE OR REPLACE FUNCTION cleanup_old_read_events(retention_days INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM email_read_events
    WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- AUTOMATIC CLEANUP TRIGGER
-- Periodically cleanup expired mappings (can be called by cron job)
-- =====================================================================

-- Note: In production, use pg_cron or external scheduler to run:
-- SELECT cleanup_expired_sendgrid_mappings();
-- SELECT cleanup_old_read_events(90);

-- =====================================================================
-- DATA VALIDATION
-- Ensure data integrity
-- =====================================================================

-- Add trigger to update updated_at on email_read_events
CREATE OR REPLACE FUNCTION update_email_read_events_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_email_read_events_updated_at
    BEFORE UPDATE ON email_read_events
    FOR EACH ROW
    EXECUTE FUNCTION update_email_read_events_timestamp();

-- =====================================================================
-- PERMISSIONS
-- Grant necessary permissions (adjust based on your user roles)
-- =====================================================================

-- Note: Adjust these grants based on your actual user roles
-- Example: GRANT SELECT, INSERT, UPDATE ON email_read_events TO authenticated;
-- Example: GRANT SELECT, INSERT ON sendgrid_message_mapping TO authenticated;
-- Example: GRANT SELECT, UPDATE ON messages TO authenticated;

-- =====================================================================
-- MIGRATION COMPLETE
-- =====================================================================

-- Verify tables created
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name IN ('email_read_events', 'sendgrid_message_mapping')
    ) THEN
        RAISE NOTICE 'Migration 003_email_read_tracking completed successfully';
        RAISE NOTICE 'Tables created: email_read_events, sendgrid_message_mapping';
        RAISE NOTICE 'Column added: messages.read_events';
    ELSE
        RAISE EXCEPTION 'Migration failed: Tables not created';
    END IF;
END $$;

-- =====================================================================
-- ROLLBACK SCRIPT
-- Run this section to rollback the migration
-- =====================================================================

/*
-- ROLLBACK INSTRUCTIONS:
-- To rollback this migration, execute the following commands:

-- Drop helper functions
DROP FUNCTION IF EXISTS get_message_read_stats(TEXT);
DROP FUNCTION IF EXISTS cleanup_expired_sendgrid_mappings();
DROP FUNCTION IF EXISTS cleanup_old_read_events(INTEGER);
DROP FUNCTION IF EXISTS update_email_read_events_timestamp() CASCADE;

-- Drop tables (CASCADE removes dependent objects)
DROP TABLE IF EXISTS email_read_events CASCADE;
DROP TABLE IF EXISTS sendgrid_message_mapping CASCADE;

-- Remove column from messages table
ALTER TABLE messages DROP COLUMN IF EXISTS read_events;

-- Verify rollback
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name IN ('email_read_events', 'sendgrid_message_mapping')
    ) THEN
        RAISE NOTICE 'Rollback completed successfully';
        RAISE NOTICE 'Tables dropped: email_read_events, sendgrid_message_mapping';
        RAISE NOTICE 'Column removed: messages.read_events';
    ELSE
        RAISE EXCEPTION 'Rollback failed: Tables still exist';
    END IF;
END $$;
*/
