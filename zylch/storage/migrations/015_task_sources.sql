-- Add sources column to task_items for data traceability
-- Stores references to all data sources used when creating the task
-- Example: {"emails": ["uuid1", "uuid2"], "blobs": ["blob-uuid1"], "calendar_events": ["cal-uuid1"]}

ALTER TABLE task_items ADD COLUMN IF NOT EXISTS sources jsonb DEFAULT '{}';

-- Add comment for documentation
COMMENT ON COLUMN task_items.sources IS 'JSONB dict tracking data sources used to create this task. Keys are table names, values are arrays of UUIDs.';
