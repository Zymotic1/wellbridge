-- Migration 0020: Upgrade search_cms_providers to accept TEXT[] array filters
--
-- Replaces the single-value state_f/specialty_f params from 0019 with
-- TEXT[] arrays so the frontend can pass multiple selections.
--
-- Calling convention:
--   Single:   search_cms_providers(q, states => '{NJ}', specialties => '{CARDIOLOGY}')
--   Multi:    search_cms_providers(q, states => '{NJ,NY}', specialties => '{CARDIOLOGY,"FAMILY PRACTICE"}')
--   No filter: search_cms_providers(q)          -- arrays default to NULL = no filter

CREATE OR REPLACE FUNCTION search_cms_providers(
    q           TEXT,
    states      TEXT[]  DEFAULT NULL,   -- e.g. '{NJ,NY,CA}'
    specialties TEXT[]  DEFAULT NULL,   -- e.g. '{CARDIOLOGY,"FAMILY PRACTICE"}'
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
    -- State filter: NULL array = no filter; otherwise match any of the selected states
    AND (states      IS NULL OR state_abbr = ANY(states))
    -- Specialty filter: NULL array = no filter; match any of the selected specialties
    AND (specialties IS NULL OR upper(specialty) = ANY(
            SELECT upper(s) FROM unnest(specialties) s
        ))
    ORDER BY score DESC, display_name
    LIMIT lim;
$$;
