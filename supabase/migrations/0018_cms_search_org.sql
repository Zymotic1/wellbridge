-- Migration 0018: Improve cms_providers search to include org_name (Facility Name)
--
-- The CMS DAC dataset stores each provider's affiliated facility in org_name.
-- Searching only display_name (provider's personal name) misses queries like
-- "Monmouth Medical" which should surface all providers at that facility.
--
-- Changes:
--   1. Add trigram GIN index on org_name
--   2. Replace search_cms_providers() to include org_name in ILIKE match and scoring

-- Trigram index on org_name (facility/practice name)
CREATE INDEX IF NOT EXISTS cms_providers_org_trgm
    ON cms_providers USING GIN (org_name gin_trgm_ops);

-- Updated search function — searches provider name, facility name, and city
CREATE OR REPLACE FUNCTION search_cms_providers(
    q        TEXT,
    state_f  TEXT DEFAULT NULL,
    lim      INT  DEFAULT 15
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
        -- Score: best match across name, facility, or city
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
    AND (state_f IS NULL OR state_abbr = upper(state_f))
    ORDER BY score DESC, display_name
    LIMIT lim;
$$;
