-- ==============================================================================
-- 0012: Vector similarity search function for patient records
--
-- match_patient_records() performs a cosine similarity search against the
-- content_vector column (populated by text-embedding-3-small at upload time).
--
-- Called from the backend via db.rpc("match_patient_records", {...}).
-- RLS session variables (app.tenant_id, app.user_id) must be set by the
-- caller (get_scoped_client() handles this).
-- ==============================================================================

CREATE OR REPLACE FUNCTION match_patient_records(
    query_embedding  VECTOR(1536),
    match_threshold  FLOAT   DEFAULT 0.4,   -- cosine similarity floor (0=orthogonal, 1=identical)
    match_count      INT     DEFAULT 8       -- maximum rows to return
)
RETURNS TABLE (
    id              UUID,
    record_type     TEXT,
    provider_name   TEXT,
    facility_name   TEXT,
    note_date       TIMESTAMPTZ,
    content         TEXT,
    similarity      FLOAT
) AS $$
    SELECT
        id,
        record_type::TEXT,
        provider_name,
        facility_name,
        note_date,
        content,
        1 - (content_vector <=> query_embedding) AS similarity
    FROM patient_records
    WHERE
        tenant_id       = current_tenant_id()
        AND patient_user_id = current_user_id()
        AND content_vector IS NOT NULL
        AND 1 - (content_vector <=> query_embedding) > match_threshold
    ORDER BY content_vector <=> query_embedding   -- ascending distance = descending similarity
    LIMIT match_count;
$$ LANGUAGE sql STABLE SECURITY DEFINER;
