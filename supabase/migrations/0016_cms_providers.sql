-- Migration 0016: CMS Doctors & Clinicians provider lookup table
--
-- Source: CMS Provider Data — Doctors and Clinicians
-- URL:    https://data.cms.gov/provider-data/topics/doctors-clinicians
-- File:   DAC_NationalDownloadableFile.csv  (~2.7M active Medicare providers)
--
-- Populated by running:  python scripts/import_cms_providers.py
--
-- pg_trgm is used for fast partial-name matching (e.g. "Monmou" → Monmouth Medical).
-- No RLS — this is fully public data.

-- Enable trigram extension (safe to run multiple times)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── Provider table ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cms_providers (
    npi          TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,     -- "First Last" for individuals, org name for groups
    first_name   TEXT,
    last_name    TEXT,
    org_name     TEXT,
    credential   TEXT,              -- MD, DO, NP, PA, etc.
    specialty    TEXT,              -- Primary specialty
    address      TEXT,              -- "123 Main St, Suite 4"
    city         TEXT,
    state_abbr   TEXT,
    zip          TEXT,
    phone        TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trigram GIN index on display_name → supports ILIKE '%partial%' at scale
CREATE INDEX IF NOT EXISTS cms_providers_name_trgm
    ON cms_providers USING GIN (display_name gin_trgm_ops);

-- Trigram index on city → lets users search "Monmouth" as city filter too
CREATE INDEX IF NOT EXISTS cms_providers_city_trgm
    ON cms_providers USING GIN (city gin_trgm_ops);

-- B-tree on state for fast state-scoped lookups
CREATE INDEX IF NOT EXISTS cms_providers_state_idx
    ON cms_providers (state_abbr);

-- ─── Search function ──────────────────────────────────────────────────────────
-- Called from the backend via: db.rpc("search_cms_providers", {...}).execute()
--
-- Uses ILIKE with the trigram index for fast recall, then ranks by similarity.
-- Searches both the provider/org name AND the city, so:
--   "Monmou"  → finds "Monmouth Medical Center" (org) and providers IN Monmouth, NJ
--   "Smith"   → finds Dr. Smith (individual) and Smith Medical Group (org)
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
        -- Score: max of name-similarity and city-similarity so city matches surface
        GREATEST(
            similarity(display_name, q),
            similarity(city, q)
        )::FLOAT AS score
    FROM cms_providers
    WHERE (
        display_name ILIKE '%' || q || '%'
        OR city ILIKE '%' || q || '%'
    )
    AND (state_f IS NULL OR state_abbr = upper(state_f))
    ORDER BY score DESC, display_name
    LIMIT lim;
$$;
