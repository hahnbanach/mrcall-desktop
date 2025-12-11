-- Create triggers table for event-driven automation
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS triggers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  owner_id TEXT NOT NULL,
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('session_start', 'email_received', 'sms_received', 'call_received')),
  instruction TEXT NOT NULL,
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookup by owner
CREATE INDEX IF NOT EXISTS idx_triggers_owner ON triggers(owner_id);

-- Index for active triggers by type (for execution)
CREATE INDEX IF NOT EXISTS idx_triggers_active_type ON triggers(owner_id, trigger_type) WHERE active = true;

-- Enable RLS
ALTER TABLE triggers ENABLE ROW LEVEL SECURITY;

-- RLS policy: users can only access their own triggers
CREATE POLICY "Users can manage their own triggers"
  ON triggers
  FOR ALL
  USING (owner_id = auth.uid()::text)
  WITH CHECK (owner_id = auth.uid()::text);

-- For service role access (backend)
CREATE POLICY "Service role has full access to triggers"
  ON triggers
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

COMMENT ON TABLE triggers IS 'Event-driven automation triggers for Zylch users';
COMMENT ON COLUMN triggers.trigger_type IS 'session_start, email_received, sms_received, call_received';
COMMENT ON COLUMN triggers.instruction IS 'Natural language instruction to execute when trigger fires';
