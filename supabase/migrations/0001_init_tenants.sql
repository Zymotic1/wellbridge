-- ==============================================================================
-- 0001: Tenant foundation + RLS session variable functions
-- This migration is the cornerstone of multi-tenancy. ALL other tables
-- reference tenants(id) and rely on the functions defined here for RLS.
-- ==============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tenants table
CREATE TABLE IF NOT EXISTS tenants (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT NOT NULL,
    plan       TEXT NOT NULL DEFAULT 'free', -- 'free' | 'pro' | 'enterprise'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==============================================================================
-- Session variable functions
-- These are called inside RLS policies on every table. The backend sets
-- app.tenant_id and app.user_id as transaction-local session variables
-- via get_scoped_client() before every query.
-- ==============================================================================

CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
    SELECT NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID;
$$ LANGUAGE sql STABLE SECURITY DEFINER;

CREATE OR REPLACE FUNCTION current_user_id() RETURNS TEXT AS $$
    SELECT NULLIF(current_setting('app.user_id', TRUE), '');
$$ LANGUAGE sql STABLE SECURITY DEFINER;

-- NOTE: search_patient_notes() is defined in 0003_records.sql,
-- after the patient_records table is created.
