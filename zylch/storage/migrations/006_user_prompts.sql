-- User Prompts Table
-- Stores personalized prompts generated from user's email patterns
-- Each user can have one prompt per type (e.g., memory_email, memory_calendar, triage)

CREATE TABLE IF NOT EXISTS user_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    prompt_type TEXT NOT NULL,  -- 'memory_email', 'memory_calendar', 'triage', etc.
    prompt_content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,  -- generation stats, sample count, generated_at, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(owner_id, prompt_type)
);

-- Index for fast lookups by owner
CREATE INDEX IF NOT EXISTS idx_user_prompts_owner ON user_prompts(owner_id);

-- Index for lookups by owner + type (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_user_prompts_owner_type ON user_prompts(owner_id, prompt_type);

-- RLS Policy (for direct Supabase access)
ALTER TABLE user_prompts ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_prompts_owner_policy ON user_prompts
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- Auto-update timestamp trigger
CREATE OR REPLACE FUNCTION update_user_prompts_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_prompts_updated_at
    BEFORE UPDATE ON user_prompts
    FOR EACH ROW
    EXECUTE FUNCTION update_user_prompts_timestamp();
