-- ============================================
-- OAUTH STATES TABLE
-- For multi-instance OAuth CSRF protection
-- Run this in Supabase SQL Editor
-- ============================================

CREATE TABLE IF NOT EXISTS oauth_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    email TEXT,
    cli_callback TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast state lookups
CREATE INDEX IF NOT EXISTS idx_oauth_states_state ON oauth_states(state);

-- Index for cleanup of expired states
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires_at ON oauth_states(expires_at);

COMMENT ON TABLE oauth_states IS 'Temporary OAuth state storage for CSRF protection (multi-instance safe)';
COMMENT ON COLUMN oauth_states.state IS 'Random state token for CSRF protection';
COMMENT ON COLUMN oauth_states.owner_id IS 'Firebase UID of the user initiating OAuth';
COMMENT ON COLUMN oauth_states.cli_callback IS 'Optional CLI callback URL for local OAuth flows';
COMMENT ON COLUMN oauth_states.expires_at IS 'When this state expires (typically 10 minutes)';
