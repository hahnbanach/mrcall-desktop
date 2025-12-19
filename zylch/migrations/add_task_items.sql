-- Task items table for LLM-analyzed actionable items
-- Replaces the avatar-based task system with LLM reasoning

CREATE TABLE IF NOT EXISTS task_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id TEXT NOT NULL,

    -- Source event reference
    event_type TEXT NOT NULL,  -- 'email', 'calendar', 'mrcall'
    event_id TEXT NOT NULL,    -- Reference to source event

    -- Contact info (denormalized for display)
    contact_email TEXT,
    contact_name TEXT,

    -- LLM decision
    action_required BOOLEAN NOT NULL DEFAULT false,
    urgency TEXT,              -- 'high', 'medium', 'low'
    reason TEXT,               -- Why action is needed
    suggested_action TEXT,     -- What user should do

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    analyzed_at TIMESTAMPTZ,   -- When LLM analyzed this
    completed_at TIMESTAMPTZ,  -- When user marked complete

    UNIQUE(owner_id, event_type, event_id)
);

-- Index for querying user's actionable items
CREATE INDEX IF NOT EXISTS idx_task_items_owner ON task_items(owner_id);

-- Partial index for fast lookup of items needing action
CREATE INDEX IF NOT EXISTS idx_task_items_action ON task_items(owner_id, action_required)
WHERE action_required = true;

-- Index for cleanup of old completed items
CREATE INDEX IF NOT EXISTS idx_task_items_completed ON task_items(completed_at)
WHERE completed_at IS NOT NULL;
