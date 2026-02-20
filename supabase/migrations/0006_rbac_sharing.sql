-- ==============================================================================
-- 0006: RBAC Trusted Individual Access (record_shares)
-- Allows patients to grant Viewer or Editor access to other users
-- (e.g., sharing records with a family caregiver).
-- ==============================================================================

CREATE TYPE share_role AS ENUM ('viewer', 'editor');

CREATE TABLE IF NOT EXISTS record_shares (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    record_id    UUID NOT NULL REFERENCES patient_records(id) ON DELETE CASCADE,
    granted_by   TEXT NOT NULL,   -- Auth0 sub of the record owner
    granted_to   TEXT NOT NULL,   -- Auth0 sub of the grantee
    role         share_role NOT NULL DEFAULT 'viewer',
    expires_at   TIMESTAMPTZ,     -- NULL = no expiry
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT no_self_share CHECK (granted_by <> granted_to),
    UNIQUE (record_id, granted_to)  -- One share per record per grantee
);

CREATE INDEX idx_shares_granted_to ON record_shares(granted_to, tenant_id);
CREATE INDEX idx_shares_record     ON record_shares(record_id);

ALTER TABLE record_shares ENABLE ROW LEVEL SECURITY;

-- Record owner can see, create, and delete their own shares
CREATE POLICY "shares_owner_full" ON record_shares
    FOR ALL
    USING (
        tenant_id = current_tenant_id()
        AND granted_by = current_user_id()
    );

-- Grantees can see shares where they are the grantee (read-only)
CREATE POLICY "shares_grantee_read" ON record_shares
    FOR SELECT
    USING (
        tenant_id = current_tenant_id()
        AND granted_to = current_user_id()
        AND (expires_at IS NULL OR expires_at > NOW())
    );

-- ==============================================================================
-- Upgrade patient_records RLS policies to include sharing.
-- These replace the owner-only stubs created in 0003, now that record_shares exists.
-- ==============================================================================

DROP POLICY IF EXISTS "records_select" ON patient_records;
CREATE POLICY "records_select" ON patient_records
    FOR SELECT
    USING (
        tenant_id = current_tenant_id()
        AND (
            patient_user_id = current_user_id()
            OR EXISTS (
                SELECT 1 FROM record_shares rs
                WHERE rs.record_id = patient_records.id
                  AND rs.granted_to = current_user_id()
                  AND rs.tenant_id = current_tenant_id()
                  AND (rs.expires_at IS NULL OR rs.expires_at > NOW())
            )
        )
    );

DROP POLICY IF EXISTS "records_update" ON patient_records;
CREATE POLICY "records_update" ON patient_records
    FOR UPDATE
    USING (
        tenant_id = current_tenant_id()
        AND (
            patient_user_id = current_user_id()
            OR EXISTS (
                SELECT 1 FROM record_shares rs
                WHERE rs.record_id = patient_records.id
                  AND rs.granted_to = current_user_id()
                  AND rs.role = 'editor'
                  AND rs.tenant_id = current_tenant_id()
                  AND (rs.expires_at IS NULL OR rs.expires_at > NOW())
            )
        )
    );
