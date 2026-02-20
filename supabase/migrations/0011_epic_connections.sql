-- ==============================================================================
-- 0011: Epic MyChart / SMART on FHIR Connections
--
-- Stores per-patient Epic OAuth tokens and sync state.
-- One row per patient (UPSERT on connect/reconnect).
-- Tokens are stored encrypted at the application layer (Fernet AES-128).
-- ==============================================================================

CREATE TABLE IF NOT EXISTS epic_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_user_id     TEXT NOT NULL,

    -- Hospital / health system info
    organization_name   TEXT NOT NULL,
    fhir_base_url       TEXT NOT NULL,

    -- OAuth tokens (application-layer encrypted)
    access_token_enc    TEXT,
    refresh_token_enc   TEXT,
    token_expires_at    TIMESTAMPTZ,
    scope               TEXT,

    -- Epic-side patient identity
    patient_fhir_id     TEXT,

    -- Sync tracking
    last_sync_at        TIMESTAMPTZ,
    sync_status         TEXT DEFAULT 'pending',  -- pending | success | error
    sync_error          TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One active Epic connection per patient per tenant
    UNIQUE(tenant_id, patient_user_id)
);

CREATE INDEX idx_epic_tenant_user ON epic_connections(tenant_id, patient_user_id);

ALTER TABLE epic_connections ENABLE ROW LEVEL SECURITY;

CREATE POLICY "epic_connections_isolation" ON epic_connections
    FOR ALL
    USING (
        tenant_id = current_tenant_id()
        AND patient_user_id = current_user_id()
    );
