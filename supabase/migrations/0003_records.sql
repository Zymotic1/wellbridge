-- ==============================================================================
-- 0003: Patient records (clinical notes, lab results, discharge summaries)
-- Includes full-text search index and pgvector for semantic retrieval.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE record_type AS ENUM (
    'clinical_note',
    'lab_result',
    'discharge_summary',
    'prescription',
    'imaging_report'
);

CREATE TABLE IF NOT EXISTS patient_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_user_id  TEXT NOT NULL,        -- Auth0 sub
    record_type      record_type NOT NULL,
    provider_name    TEXT,
    facility_name    TEXT,
    note_date        TIMESTAMPTZ NOT NULL,
    content          TEXT NOT NULL,        -- Full text of the record
    content_fhir     JSONB,                -- Optional FHIR R4 resource representation
    -- 1536-dim embedding from text-embedding-3-small for semantic search
    content_vector   VECTOR(1536),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_records_tenant_user ON patient_records(tenant_id, patient_user_id);
CREATE INDEX idx_records_note_date   ON patient_records(note_date DESC);

-- Full-text search index (used by search_patient_notes function)
CREATE INDEX idx_records_fts ON patient_records
    USING gin(to_tsvector('english', content));

-- pgvector approximate nearest-neighbor index for semantic search
-- (requires at least 100 rows of data before this index activates)
CREATE INDEX idx_records_vector ON patient_records
    USING ivfflat (content_vector vector_cosine_ops)
    WITH (lists = 100);

ALTER TABLE patient_records ENABLE ROW LEVEL SECURITY;

-- Owner-only SELECT (sharing subquery added in 0006 after record_shares is created)
CREATE POLICY "records_select" ON patient_records
    FOR SELECT
    USING (
        tenant_id = current_tenant_id()
        AND patient_user_id = current_user_id()
    );

-- Only the record owner can insert
CREATE POLICY "records_insert" ON patient_records
    FOR INSERT
    WITH CHECK (
        tenant_id = current_tenant_id()
        AND patient_user_id = current_user_id()
    );

-- Owner-only UPDATE (editor sharing subquery added in 0006 after record_shares is created)
CREATE POLICY "records_update" ON patient_records
    FOR UPDATE
    USING (
        tenant_id = current_tenant_id()
        AND patient_user_id = current_user_id()
    );

-- Only owner can delete
CREATE POLICY "records_delete" ON patient_records
    FOR DELETE
    USING (
        tenant_id = current_tenant_id()
        AND patient_user_id = current_user_id()
    );

-- ==============================================================================
-- Full-text search helper used by the refusal node and jargon explainer.
-- Defined here (not in 0001) because it references the patient_records table.
-- ==============================================================================
CREATE OR REPLACE FUNCTION search_patient_notes(
    query_text TEXT,
    user_id_param TEXT,
    limit_n INT DEFAULT 3
) RETURNS TABLE (
    id               UUID,
    provider_name    TEXT,
    note_date        TIMESTAMPTZ,
    relevant_excerpt TEXT
) AS $$
    SELECT
        id,
        provider_name,
        note_date,
        -- Return up to 200 chars of the best matching content
        LEFT(content, 200) AS relevant_excerpt
    FROM patient_records
    WHERE patient_user_id = user_id_param
      AND tenant_id = current_tenant_id()
      AND to_tsvector('english', content) @@ plainto_tsquery('english', query_text)
    ORDER BY note_date DESC
    LIMIT limit_n;
$$ LANGUAGE sql STABLE SECURITY DEFINER;
