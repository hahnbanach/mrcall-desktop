-- Migration: 005_drafts_table.sql
-- Description: Email drafts stored in Supabase (Superhuman-style)
-- Author: Claude
-- Date: 2024-12-16

-- Drafts table: store email drafts locally, send via Gmail/Outlook API
CREATE TABLE IF NOT EXISTS drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Email fields
    to_addresses TEXT[] NOT NULL DEFAULT '{}',
    cc_addresses TEXT[] DEFAULT '{}',
    bcc_addresses TEXT[] DEFAULT '{}',
    subject TEXT,
    body TEXT,
    body_format TEXT DEFAULT 'html' CHECK (body_format IN ('html', 'plain')),

    -- Threading (for replies)
    in_reply_to TEXT,                    -- Message-ID of email being replied to
    references TEXT[],                   -- Thread message IDs for proper threading
    thread_id TEXT,                      -- Gmail/Outlook thread ID
    original_message_id TEXT,            -- ID of message being replied to (for context)

    -- Status tracking
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'sending', 'sent', 'failed')),
    provider TEXT CHECK (provider IN ('google', 'microsoft')),
    sent_at TIMESTAMPTZ,
    sent_message_id TEXT,                -- Provider's message ID after sending
    error_message TEXT,                  -- If status = 'failed'

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_drafts_owner ON drafts(owner_id);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_drafts_thread ON drafts(thread_id);
CREATE INDEX IF NOT EXISTS idx_drafts_created ON drafts(owner_id, created_at DESC);

-- Enable RLS
ALTER TABLE drafts ENABLE ROW LEVEL SECURITY;

-- RLS policy: users can only access their own drafts
CREATE POLICY "Users can manage own drafts"
ON drafts FOR ALL
USING (owner_id = auth.uid())
WITH CHECK (owner_id = auth.uid());

-- Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION update_drafts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER drafts_updated_at
    BEFORE UPDATE ON drafts
    FOR EACH ROW
    EXECUTE FUNCTION update_drafts_updated_at();

-- Comment on table
COMMENT ON TABLE drafts IS 'Email drafts stored locally in Supabase. Sent via Gmail/Outlook API when ready.';
COMMENT ON COLUMN drafts.status IS 'draft=editing, sending=in progress, sent=completed, failed=error';
COMMENT ON COLUMN drafts.provider IS 'Email provider used for sending: google or microsoft';
