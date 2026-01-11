-- Migration 022: Calendar attendee search optimization
-- Adds GIN index on attendees JSONB column and RPC function for server-side filtering

-- GIN index for fast JSONB containment queries
-- This speeds up searching for events by attendee email
CREATE INDEX IF NOT EXISTS idx_calendar_events_attendees_gin
ON calendar_events USING GIN (attendees);

-- RPC function for server-side attendee filtering
-- Much faster than fetching all events and filtering in Python
CREATE OR REPLACE FUNCTION get_events_by_attendee(
    p_owner_id TEXT,
    p_attendee_email TEXT,
    p_start_time TIMESTAMPTZ,
    p_end_time TIMESTAMPTZ
) RETURNS SETOF calendar_events AS $$
    SELECT * FROM calendar_events
    WHERE owner_id = p_owner_id
      AND start_time >= p_start_time
      AND start_time <= p_end_time
      AND (
          -- Handle simple array of email strings
          attendees @> to_jsonb(ARRAY[LOWER(p_attendee_email)])
          OR
          -- Handle array of objects with 'email' key
          EXISTS (
              SELECT 1 FROM jsonb_array_elements(attendees) elem
              WHERE LOWER(elem->>'email') = LOWER(p_attendee_email)
          )
      )
    ORDER BY start_time;
$$ LANGUAGE sql STABLE;

-- Comment explaining usage
COMMENT ON FUNCTION get_events_by_attendee IS
'Returns calendar events where the given email is an attendee.
Used by task agent to inject calendar context when analyzing emails.
Supports both simple email arrays and object arrays with email field.';
