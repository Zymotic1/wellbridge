-- ==============================================================================
-- 0015: Add contact fields to appointments
--
-- phone   — provider/practice phone number (from NPI registry or manual entry)
-- address — full practice address (from NPI registry or manual entry)
-- npi     — National Provider Identifier (10-digit, from NPI registry search)
--
-- These columns are optional and populated when the user selects a provider
-- from the NPI registry search in the Create Appointment modal.
-- ==============================================================================

ALTER TABLE appointments
    ADD COLUMN IF NOT EXISTS phone   TEXT,
    ADD COLUMN IF NOT EXISTS address TEXT,
    ADD COLUMN IF NOT EXISTS npi     TEXT;
