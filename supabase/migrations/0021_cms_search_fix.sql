-- Migration 0021: Fix search_cms_providers — column coverage, case-insensitivity
--
-- Changes from 0020:
--   1. WHERE clause now matches against first_name, last_name, org_name, and
--      display_name (all via ILIKE — inherently case-insensitive).
--      City removed from match criteria per spec.
--   2. State filter made explicitly case-insensitive (upper() on both sides)
--      so "nj" or "NJ" both work regardless of how the client sends them.
--   3. Similarity scoring updated to include first_name and last_name so
--      fuzzy ranking works correctly for individual-provider searches.

CREATE OR REPLACE FUNCTION search_cms_providers(
    q           TEXT,
    states      TEXT[]  DEFAULT NULL,   -- e.g. '{NJ,NY}'       — NULL = no filter
    specialties TEXT[]  DEFAULT NULL,   -- e.g. '{CARDIOLOGY}'   — NULL = no filter
    lim         INT     DEFAULT 15
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
            COALESCE(similarity(first_name,   q), 0),
            COALESCE(similarity(last_name,    q), 0),
            COALESCE(similarity(org_name,     q), 0),
            similarity(display_name, q)
        )::FLOAT AS score
    FROM cms_providers
    WHERE (
        -- Case-insensitive partial match across all name columns
        first_name   ILIKE '%' || q || '%'
        OR last_name   ILIKE '%' || q || '%'
        OR org_name    ILIKE '%' || q || '%'
        OR display_name ILIKE '%' || q || '%'
    )
    -- State filter: case-insensitive; NULL array = no filter
    AND (states IS NULL OR upper(state_abbr) = ANY(
            SELECT upper(s) FROM unnest(states) s
        ))
    -- Specialty filter: case-insensitive; NULL array = no filter
    AND (specialties IS NULL OR upper(specialty) = ANY(
            SELECT upper(s) FROM unnest(specialties) s
        ))
    ORDER BY score DESC, display_name
    LIMIT lim;
$$;
