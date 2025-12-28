-- Drop deprecated avatar tables
-- The avatars table was designed for pre-computed relationship intelligence
-- but the write pipeline was never implemented. Task intelligence now comes
-- from the task_items table, which is actively populated by task_agent.py.

DROP TABLE IF EXISTS avatar_compute_queue CASCADE;
DROP TABLE IF EXISTS avatars CASCADE;
DROP TABLE IF EXISTS identifier_map CASCADE;
