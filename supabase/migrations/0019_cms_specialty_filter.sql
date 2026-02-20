-- Migration 0019: Add specialty filter to search_cms_providers
--
-- Adds:
--   1. B-tree index on specialty for fast equality filtering
--   2. specialty_f parameter to search_cms_providers() RPC

CREATE INDEX IF NOT EXISTS cms_providers_specialty_idx
    ON cms_providers (specialty);

-- Replace with updated signature — all existing callers still work because
-- specialty_f defaults to NULL (no filter applied).
CREATE OR REPLACE FUNCTION search_cms_providers(
    q           TEXT,
    state_f     TEXT DEFAULT NULL,
    specialty_f TEXT DEFAULT NULL,
    lim         INT  DEFAULT 15
)
RETURNS TABLE (
    npi          TEXT,
    display_name TEXT,
    specialty    TEXT,
    address      TEXT,
    city         TEXT,
    state_abbr   TEXT,
    phone        TEXT,
    org_name     TEXT,
    score        FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        npi,
        display_name,
        specialty,
        address,
        city,
        state_abbr,
        phone,
        org_name,
        GREATEST(
            similarity(display_name, q),
            COALESCE(similarity(org_name, q), 0),
            similarity(coalesce(city, ''), q)
        )::FLOAT AS score
    FROM cms_providers
    WHERE (
        display_name ILIKE '%' || q || '%'
        OR org_name  ILIKE '%' || q || '%'
        OR city      ILIKE '%' || q || '%'
    )
    AND (state_f     IS NULL OR state_abbr = upper(state_f))
    AND (specialty_f IS NULL OR specialty  ILIKE specialty_f)
    ORDER BY score DESC, display_name
    LIMIT lim;
$$;
