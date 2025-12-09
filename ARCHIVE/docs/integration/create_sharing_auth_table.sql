-- Create sharing_auth table for data sharing between users
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS sharing_auth (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  sender_id TEXT NOT NULL,
  sender_email TEXT NOT NULL,
  recipient_email TEXT NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'authorized', 'revoked')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  authorized_at TIMESTAMPTZ,

  -- Unique constraint: one share request per sender-recipient pair
  UNIQUE(sender_id, recipient_email)
);

-- Index for sender lookups
CREATE INDEX IF NOT EXISTS idx_sharing_sender ON sharing_auth(sender_id);

-- Index for recipient lookups
CREATE INDEX IF NOT EXISTS idx_sharing_recipient ON sharing_auth(recipient_email);

-- Index for status queries
CREATE INDEX IF NOT EXISTS idx_sharing_status ON sharing_auth(status);

-- Enable RLS
ALTER TABLE sharing_auth ENABLE ROW LEVEL SECURITY;

-- RLS policy: users can see shares they sent
CREATE POLICY "Users can see shares they sent"
  ON sharing_auth
  FOR SELECT
  USING (sender_id = auth.uid()::text);

-- RLS policy: users can see shares sent to them
CREATE POLICY "Users can see shares sent to them"
  ON sharing_auth
  FOR SELECT
  USING (recipient_email = auth.jwt()->>'email');

-- RLS policy: users can insert shares they send
CREATE POLICY "Users can insert shares they send"
  ON sharing_auth
  FOR INSERT
  WITH CHECK (sender_id = auth.uid()::text);

-- RLS policy: users can update shares they sent (revoke)
CREATE POLICY "Users can update shares they sent"
  ON sharing_auth
  FOR UPDATE
  USING (sender_id = auth.uid()::text);

-- RLS policy: recipients can update shares sent to them (authorize)
CREATE POLICY "Recipients can authorize shares"
  ON sharing_auth
  FOR UPDATE
  USING (recipient_email = auth.jwt()->>'email');

-- For service role access (backend)
CREATE POLICY "Service role has full access to sharing_auth"
  ON sharing_auth
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

COMMENT ON TABLE sharing_auth IS 'Sharing authorization between Zylch users';
COMMENT ON COLUMN sharing_auth.status IS 'pending (awaiting acceptance), authorized (accepted), revoked (cancelled)';
