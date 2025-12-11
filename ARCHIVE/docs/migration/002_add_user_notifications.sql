-- Migration: 002_add_user_notifications.sql
-- Purpose: Add user_notifications table for background worker failure notifications
-- Date: 2025-12-08

-- Create user_notifications table
CREATE TABLE IF NOT EXISTS user_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    message TEXT NOT NULL,
    notification_type TEXT DEFAULT 'warning',  -- 'info', 'warning', 'error'
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookup of unread notifications per user
CREATE INDEX IF NOT EXISTS idx_user_notifications_owner_unread
    ON user_notifications(owner_id) WHERE read = FALSE;

-- Enable Row Level Security
ALTER TABLE user_notifications ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only access their own notifications
-- Note: Backend uses service_role key (bypasses RLS), but this protects against anon key usage
CREATE POLICY "Users can only access own notifications" ON user_notifications
    FOR ALL
    USING (owner_id = current_setting('request.jwt.claims', true)::json->>'sub')
    WITH CHECK (owner_id = current_setting('request.jwt.claims', true)::json->>'sub');
