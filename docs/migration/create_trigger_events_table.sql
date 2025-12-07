-- Create trigger_events table for background job queue
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS trigger_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  owner_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('email_received', 'sms_received', 'call_received')),

  -- Event payload (what happened)
  event_data JSONB NOT NULL DEFAULT '{}',
  -- Example event_data for email_received:
  -- { "from": "john@example.com", "subject": "Meeting tomorrow", "snippet": "Hi, about our meeting..." }
  -- Example event_data for call_received:
  -- { "caller": "+39123456789", "duration_seconds": 120, "transcript": "..." }
  -- Example event_data for sms_received:
  -- { "from": "+39123456789", "body": "Please call me back" }

  -- Processing status
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),

  -- Execution tracking
  trigger_id UUID REFERENCES triggers(id),  -- Which trigger was executed (set after processing)
  result JSONB,  -- Result of execution (success message, error, etc.)

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  processed_at TIMESTAMPTZ,

  -- Retry logic
  attempts INTEGER DEFAULT 0,
  last_error TEXT
);

-- Index for finding pending events to process
CREATE INDEX IF NOT EXISTS idx_trigger_events_pending
  ON trigger_events(status, created_at)
  WHERE status = 'pending';

-- Index for owner lookups (viewing history)
CREATE INDEX IF NOT EXISTS idx_trigger_events_owner
  ON trigger_events(owner_id, created_at DESC);

-- Index for status queries
CREATE INDEX IF NOT EXISTS idx_trigger_events_status
  ON trigger_events(status);

-- Enable RLS
ALTER TABLE trigger_events ENABLE ROW LEVEL SECURITY;

-- RLS policy: users can see their own events
CREATE POLICY "Users can see their own trigger events"
  ON trigger_events
  FOR SELECT
  USING (owner_id = auth.uid()::text);

-- For service role access (backend worker)
CREATE POLICY "Service role has full access to trigger_events"
  ON trigger_events
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

COMMENT ON TABLE trigger_events IS 'Queue for background trigger execution';
COMMENT ON COLUMN trigger_events.event_type IS 'email_received, sms_received, call_received';
COMMENT ON COLUMN trigger_events.status IS 'pending (waiting), processing (being handled), completed (done), failed (error)';
COMMENT ON COLUMN trigger_events.event_data IS 'JSON payload with event details (from, subject, body, etc.)';
