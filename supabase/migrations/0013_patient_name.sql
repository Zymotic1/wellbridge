-- ==============================================================================
-- 0013: Add first_name and last_name columns to patients
--
-- Allows WellBridge to address patients by name in greetings and chat openers
-- rather than using their email address.
--
-- first_name / last_name are set by the user on first login via ProfileSetupModal.
-- display_name is kept in sync as "first_name last_name" for backward compat.
-- ==============================================================================

ALTER TABLE patients
    ADD COLUMN IF NOT EXISTS first_name TEXT,
    ADD COLUMN IF NOT EXISTS last_name  TEXT;
