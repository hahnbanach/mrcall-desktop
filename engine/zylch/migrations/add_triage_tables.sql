-- Migration: Add Email Triage Tables
-- Created: 2025-12-11
-- Description: Adds tables for email triage system, importance rules, and ML training data

-- =============================================
-- Add is_auto_reply column to emails table
-- =============================================
ALTER TABLE emails ADD COLUMN IF NOT EXISTS is_auto_reply BOOLEAN DEFAULT FALSE;

-- =============================================
-- Email Triage Table
-- Stores AI-generated triage verdicts for email threads
-- =============================================
CREATE TABLE IF NOT EXISTS email_triage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,

    -- Verdict
    needs_human_attention BOOLEAN NOT NULL DEFAULT FALSE,
    triage_category TEXT CHECK (triage_category IN ('urgent', 'normal', 'low', 'noise')),
    reason TEXT,

    -- Classification breakdown
    is_real_customer BOOLEAN,
    is_actionable BOOLEAN,
    is_time_sensitive BOOLEAN,
    is_resolved BOOLEAN,
    is_cold_outreach BOOLEAN,
    is_automated BOOLEAN,

    -- Action
    suggested_action TEXT,
    deadline_detected DATE,

    -- Metadata
    model_used TEXT,
    prompt_version TEXT,
    confidence_score FLOAT,

    -- User feedback
    user_override BOOLEAN DEFAULT FALSE,
    user_override_reason TEXT,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(owner_id, thread_id)
);

-- Index for querying threads needing attention
CREATE INDEX IF NOT EXISTS idx_email_triage_attention
    ON email_triage(owner_id, needs_human_attention, triage_category);

-- Index for deadline queries
CREATE INDEX IF NOT EXISTS idx_email_triage_deadline
    ON email_triage(owner_id, deadline_detected)
    WHERE deadline_detected IS NOT NULL;

-- =============================================
-- Importance Rules Table
-- User-configurable rules for contact importance
-- =============================================
CREATE TABLE IF NOT EXISTS importance_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id UUID REFERENCES email_accounts(id) ON DELETE CASCADE,

    name TEXT NOT NULL,
    condition TEXT NOT NULL,
    importance TEXT NOT NULL CHECK (importance IN ('high', 'normal', 'low')),
    reason TEXT,
    priority INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(owner_id, account_id, name)
);

-- Index for rule lookup
CREATE INDEX IF NOT EXISTS idx_importance_rules_owner
    ON importance_rules(owner_id, enabled);

-- =============================================
-- Training Samples Table
-- Anonymized data for ML model fine-tuning
-- =============================================
CREATE TABLE IF NOT EXISTS training_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,  -- Anonymized owner reference

    -- Deduplication
    sample_hash TEXT NOT NULL,  -- SHA256 of anonymized_input

    -- Training data
    question_type TEXT NOT NULL CHECK (question_type IN ('triage', 'classification', 'action')),
    anonymized_input TEXT NOT NULL,
    model_answer JSONB NOT NULL,

    -- Non-PII metadata
    thread_length INTEGER,
    has_attachments BOOLEAN,
    email_domain_category TEXT,
    importance_rule_matched TEXT,

    -- Training pipeline
    used_in_training BOOLEAN DEFAULT FALSE,
    training_batch_id TEXT,
    model_version_trained TEXT,

    -- Quality signals
    user_override BOOLEAN DEFAULT FALSE,
    user_override_reason TEXT,
    confidence_score FLOAT,

    created_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE(sample_hash)
);

-- Index for training data export
CREATE INDEX IF NOT EXISTS idx_training_samples_unused
    ON training_samples(used_in_training)
    WHERE used_in_training = FALSE;

-- Index for quality-filtered exports
CREATE INDEX IF NOT EXISTS idx_training_samples_override
    ON training_samples(user_override)
    WHERE user_override = TRUE;

-- =============================================
-- Triage Training Samples Table (User Feedback)
-- Stores user corrections for model improvement
-- =============================================
CREATE TABLE IF NOT EXISTS triage_training_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL,

    -- Original email data (anonymized before storage)
    email_data JSONB NOT NULL,

    -- Model prediction
    predicted_verdict JSONB NOT NULL,

    -- User correction (if any)
    actual_verdict JSONB,
    feedback_type TEXT CHECK (feedback_type IN ('correction', 'confirmation')),

    -- Training status
    used_for_training BOOLEAN DEFAULT FALSE,
    training_batch_id TEXT,

    created_at TIMESTAMPTZ DEFAULT now()
);

-- Index for training export
CREATE INDEX IF NOT EXISTS idx_triage_training_unused
    ON triage_training_samples(used_for_training)
    WHERE used_for_training = FALSE;

-- =============================================
-- Row Level Security (RLS)
-- =============================================

-- Enable RLS on all new tables
ALTER TABLE email_triage ENABLE ROW LEVEL SECURITY;
ALTER TABLE importance_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE triage_training_samples ENABLE ROW LEVEL SECURITY;

-- Email triage policies
CREATE POLICY email_triage_owner_policy ON email_triage
    FOR ALL USING (owner_id = auth.uid());

-- Importance rules policies
CREATE POLICY importance_rules_owner_policy ON importance_rules
    FOR ALL USING (owner_id = auth.uid());

-- Training samples policies
CREATE POLICY triage_training_owner_policy ON triage_training_samples
    FOR ALL USING (owner_id = auth.uid());

-- =============================================
-- Updated timestamp trigger
-- =============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_email_triage_updated_at
    BEFORE UPDATE ON email_triage
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_importance_rules_updated_at
    BEFORE UPDATE ON importance_rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
