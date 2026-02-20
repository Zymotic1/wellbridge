-- ==============================================================================
-- 0014: Update match_patient_records to accept explicit tenant/user params
--
-- Problem: the original function relied on current_tenant_id() / current_user_id()
-- session variables. When called via the admin (service-role) client those
-- session variables are not set, returning 0 rows.
--
-- Fix: add optional p_tenant_id / p_user_id parameters. The admin client now
-- passes these explicitly; legacy callers get the same COALESCE fallback to
-- session variables (dev mode / PostgREST JWT path).
--
-- SECURITY DEFINER means the function runs as the owning role (postgres), so
-- it bypasses row-level security. Security is enforced by the WHERE clause
-- which will always have non-NULL values via one of the two paths.
-- ==============================================================================

CREATE OR REPLACE FUNCTION match_patient_records(
    query_embedding  VECTOR(1536),
    match_threshold  FLOAT   DEFAULT 0.4,
    match_count      INT     DEFAULT 8,
    p_tenant_id      UUID    DEFAULT NULL,   -- explicit override (admin-client path)
    p_user_id        TEXT    DEFAULT NULL    -- explicit override (admin-client path)
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
        tenant_id       = COALESCE(p_tenant_id, current_tenant_id())
        AND patient_user_id = COALESCE(p_user_id, current_user_id())
        AND content_vector IS NOT NULL
        AND 1 - (content_vector <=> query_embedding) > match_threshold
    ORDER BY content_vector <=> query_embedding
    LIMIT match_count;
$$ LANGUAGE sql STABLE SECURITY DEFINER;

-- ==============================================================================
-- Also update search_patient_notes to accept an explicit p_tenant_id param.
-- The original relied solely on current_tenant_id() (session variable), which
-- is not set when called via the admin service-role client.
-- ==============================================================================

CREATE OR REPLACE FUNCTION search_patient_notes(
    query_text      TEXT,
    user_id_param   TEXT,
    limit_n         INT     DEFAULT 3,
    p_tenant_id     UUID    DEFAULT NULL   -- explicit override (admin-client path)
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
        LEFT(content, 200) AS relevant_excerpt
    FROM patient_records
    WHERE patient_user_id = user_id_param
      AND tenant_id = COALESCE(p_tenant_id, current_tenant_id())
      AND to_tsvector('english', content) @@ plainto_tsquery('english', query_text)
    ORDER BY note_date DESC
    LIMIT limit_n;
$$ LANGUAGE sql STABLE SECURITY DEFINER;
