-- Migration: Create verification_codes table
-- Description: Support for migrated sms_tools (moving away from legacy memory)
-- Note: Trigger functionality has been removed per user request.

-- Note: Removed foreign key to public.users to avoid dependency issues if that table doesn't exist
-- owner_id matches auth.users.id implicitly

CREATE TABLE IF NOT EXISTS verification_codes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    code TEXT NOT NULL,
    context TEXT, -- 'callback_request', 'phone_verification'
    expires_in_minutes INTEGER DEFAULT 15,
    expires_at TIMESTAMPTZ NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_verification_codes_lookup 
    ON verification_codes(owner_id, phone_number, code) 
    WHERE verified = FALSE;

-- RLS Policies (Row Level Security)
ALTER TABLE verification_codes ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own verification codes
CREATE POLICY "Users can view own verification codes" 
    ON verification_codes FOR SELECT 
    USING (auth.uid()::text = owner_id);

CREATE POLICY "Users can insert own verification codes" 
    ON verification_codes FOR INSERT 
    WITH CHECK (auth.uid()::text = owner_id);

CREATE POLICY "Users can update own verification codes" 
    ON verification_codes FOR UPDATE 
    USING (auth.uid()::text = owner_id);
