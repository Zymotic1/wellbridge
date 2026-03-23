-- ==============================================================================
-- 0022: Dedicated medications table for active/discontinued tracking
--
-- Separates medication tracking from the generic patient_records table.
-- Supports:
--   - Active vs discontinued vs adjusted status
--   - Dose change history via predecessor_id chain
--   - Prescribed date vs entry date distinction
--   - Source record linking back to the uploaded document
-- ==============================================================================

CREATE TABLE IF NOT EXISTS medications (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id          TEXT NOT NULL,

    -- Medication details
    name             TEXT NOT NULL,                  -- e.g., "Entresto"
    dose             TEXT,                           -- e.g., "24mg/26mg"
    frequency        TEXT,                           -- e.g., "twice daily"
    instructions     TEXT,                           -- e.g., "take with food"

    -- Status tracking
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'discontinued', 'adjusted')),
    prescribed_date  DATE,                          -- When the doctor prescribed it
    discontinued_date DATE,                         -- When it was stopped (if applicable)

    -- Dose change chain: if dose was adjusted, this points to the previous entry
    predecessor_id   UUID REFERENCES medications(id) ON DELETE SET NULL,

    -- Link back to the uploaded document that contained this prescription
    source_record_id UUID REFERENCES patient_records(id) ON DELETE SET NULL,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (tenant_id, user_id, name, dose)
);

CREATE INDEX idx_medications_tenant_user ON medications(tenant_id, user_id);
CREATE INDEX idx_medications_status ON medications(tenant_id, user_id, status);
CREATE INDEX idx_medications_predecessor ON medications(predecessor_id);

ALTER TABLE medications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "medications_own_row" ON medications
    FOR ALL
    USING (
        tenant_id = current_tenant_id()
        AND user_id = current_user_id()
    );
