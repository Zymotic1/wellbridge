-- ==============================================================================
-- 0005: Appointments
-- Synced from Google/Outlook Calendar. Also created via Scan-to-Calendar.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS appointments (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    patient_user_id   TEXT NOT NULL,
    provider_name     TEXT,
    facility_name     TEXT,
    appointment_date  TIMESTAMPTZ NOT NULL,
    duration_minutes  INT DEFAULT 30,
    notes             TEXT,
    -- Calendar integration metadata
    google_event_id   TEXT,
    outlook_event_id  TEXT,
    -- Source: 'manual' | 'google_calendar' | 'scan_to_calendar'
    source            TEXT NOT NULL DEFAULT 'manual',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_appt_tenant_user_date ON appointments(tenant_id, patient_user_id, appointment_date DESC);

ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "appointments_isolation" ON appointments
    FOR ALL
    USING (
        tenant_id = current_tenant_id()
        AND patient_user_id = current_user_id()
    );
