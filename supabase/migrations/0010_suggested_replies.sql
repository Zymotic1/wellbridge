-- ==============================================================================
-- 0010: Add suggested_replies column to chat_messages
--
-- suggested_replies stores the AI-generated quick-reply pill suggestions
-- alongside each assistant message. Stored as JSONB array of strings.
-- Enables history replay: pill buttons reappear when loading past messages.
-- ==============================================================================

ALTER TABLE chat_messages
    ADD COLUMN IF NOT EXISTS suggested_replies JSONB NOT NULL DEFAULT '[]';
