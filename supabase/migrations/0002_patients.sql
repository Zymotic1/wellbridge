-- ==============================================================================
-- 0002: Patient profiles
-- Maps Auth0 user sub → tenant-scoped patient profile
-- ==============================================================================

CREATE TABLE IF NOT EXISTS patients (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id      TEXT NOT NULL,          -- Auth0 sub (e.g., "auth0|abc123")
    display_name TEXT,
    date_of_birth DATE,
    home_address TEXT,
    timezone     TEXT NOT NULL DEFAULT 'America/New_York',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, user_id)
);

CREATE INDEX idx_patients_tenant_user ON patients(tenant_id, user_id);

ALTER TABLE patients ENABLE ROW LEVEL SECURITY;

CREATE POLICY "patients_own_row" ON patients
    FOR ALL
    USING (
        tenant_id = current_tenant_id()
        AND user_id = current_user_id()
    );
