-- Drop deprecated thread_analysis table
-- This table is no longer used. Email search now uses vector/FTS on emails table directly.
-- Task intelligence comes from task_items table.

DROP TABLE IF EXISTS thread_analysis CASCADE;
