-- Migration 014: Drop legacy memories table
-- This table was used by the old SQLite-based ZylchMemory system.
-- It has been replaced by the entity-centric `blobs` table (see 004_entity_memory_blobs.sql).

DROP TABLE IF EXISTS memories;

-- Note: If the table had RLS policies, they would be dropped automatically with the table.
-- If there were any functions referencing this table, they should be updated or removed.
