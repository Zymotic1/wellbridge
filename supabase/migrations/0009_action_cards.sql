-- ==============================================================================
-- 0009: Add action_cards column to chat_messages
--
-- action_cards stores structured action prompts alongside assistant messages.
-- These are rendered by the frontend as interactive cards (upload, email, etc.)
-- and are replayed from history just like jargon_map.
-- ==============================================================================

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS action_cards JSONB NOT NULL DEFAULT '[]';
