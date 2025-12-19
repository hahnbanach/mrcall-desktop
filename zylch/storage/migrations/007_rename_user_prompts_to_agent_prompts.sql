-- Rename user_prompts table to agent_prompts
-- Also rename prompt_type and prompt_content columns to agent_type and agent_prompt

-- Rename the table
ALTER TABLE user_prompts RENAME TO agent_prompts;

-- Rename columns
ALTER TABLE agent_prompts RENAME COLUMN prompt_type TO agent_type;
ALTER TABLE agent_prompts RENAME COLUMN prompt_content TO agent_prompt;

-- Drop old indexes and create new ones with updated names
DROP INDEX IF EXISTS idx_user_prompts_owner;
DROP INDEX IF EXISTS idx_user_prompts_owner_type;

CREATE INDEX IF NOT EXISTS idx_agent_prompts_owner ON agent_prompts(owner_id);
CREATE INDEX IF NOT EXISTS idx_agent_prompts_owner_type ON agent_prompts(owner_id, agent_type);

-- Update RLS policy
DROP POLICY IF EXISTS user_prompts_owner_policy ON agent_prompts;
CREATE POLICY agent_prompts_owner_policy ON agent_prompts
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- Update trigger
DROP TRIGGER IF EXISTS user_prompts_updated_at ON agent_prompts;
DROP FUNCTION IF EXISTS update_user_prompts_timestamp();

CREATE OR REPLACE FUNCTION update_agent_prompts_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER agent_prompts_updated_at
    BEFORE UPDATE ON agent_prompts
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_prompts_timestamp();
