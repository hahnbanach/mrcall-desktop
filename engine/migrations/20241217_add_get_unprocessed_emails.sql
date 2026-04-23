-- Migration: Add get_unprocessed_emails RPC function
-- Description: Returns emails not yet processed by Memory Agent
-- Run in: Supabase SQL Editor or via migration tool

CREATE OR REPLACE FUNCTION get_unprocessed_emails(
    p_owner_id TEXT,
    p_limit INT DEFAULT 100
)
RETURNS TABLE (
    id TEXT,
    from_email TEXT,
    body_plain TEXT,
    snippet TEXT,
    subject TEXT,
    date TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id,
        e.from_email,
        e.body_plain,
        e.snippet,
        e.subject,
        e.date
    FROM emails e
    WHERE e.owner_id = p_owner_id
    AND NOT EXISTS (
        SELECT 1 FROM memory m
        WHERE m.owner_id = p_owner_id
        AND e.id = ANY(m.examples)
    )
    ORDER BY e.date DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Grant access to authenticated users
GRANT EXECUTE ON FUNCTION get_unprocessed_emails(TEXT, INT) TO authenticated;
GRANT EXECUTE ON FUNCTION get_unprocessed_emails(TEXT, INT) TO service_role;
