-- ==============================================================================
-- 0007: Add owner_user_id to tenants
-- Allows the Auth0 Post-Login Action to look up or create a tenant by Auth0
-- user ID and store a proper UUID in app_metadata for JWT claims.
-- ==============================================================================

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS owner_user_id TEXT UNIQUE;
