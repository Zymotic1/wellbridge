-- Migration 0017: Provider data sync tracking + Epic endpoint directory
--
-- cms_sync_log        — audit trail for every CMS / Epic sync run
-- epic_endpoint_directory — public list of Epic-connected health systems
--                           (source: open.epic.com/Endpoints/R4)
--                           Used by patients choosing their hospital in the Epic connect flow.

-- ─── Sync log ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cms_sync_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset         TEXT        NOT NULL,        -- 'cms_dac' | 'epic_r4'
    source_url      TEXT,
    source_modified TIMESTAMPTZ,                 -- Last-modified reported by the source
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    rows_upserted   INT,
    rows_deleted    INT,
    status          TEXT        NOT NULL DEFAULT 'running', -- running | success | error | skipped
    error           TEXT
);

-- Quick lookup: "what was the last successful sync for dataset X?"
CREATE INDEX IF NOT EXISTS cms_sync_log_dataset_status_idx
    ON cms_sync_log (dataset, started_at DESC)
    WHERE status IN ('success', 'skipped');

-- ─── Epic SMART endpoint directory ───────────────────────────────────────────
-- Populated weekly from open.epic.com/Endpoints/R4
-- Each row is one Epic-connected health system patients can link to.
-- No RLS — fully public data.
CREATE TABLE IF NOT EXISTS epic_endpoint_directory (
    id                TEXT        PRIMARY KEY,    -- stable ID derived from FHIR URL hash
    organization_name TEXT        NOT NULL,
    fhir_r4_url       TEXT,
    fhir_dstu2_url    TEXT,
    state_abbr        TEXT,
    is_production     BOOLEAN     NOT NULL DEFAULT true,
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Support fast "find Epic orgs in my state" searches
CREATE INDEX IF NOT EXISTS epic_endpoint_dir_state_idx
    ON epic_endpoint_directory (state_abbr);

-- Trigram on org name for search-as-you-type (e.g. "Monmouth" → Monmouth Medical)
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- idempotent; also created in 0016
CREATE INDEX IF NOT EXISTS epic_endpoint_dir_name_trgm
    ON epic_endpoint_directory USING GIN (organization_name gin_trgm_ops);
