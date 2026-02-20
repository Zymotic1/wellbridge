-- ==============================================================================
-- 0008: Update RLS helper functions to use native Auth0 JWT
--
-- Now that Supabase is configured to verify Auth0 JWTs natively, the session
-- variable approach (current_setting('app.tenant_id')) is replaced by
-- auth.jwt() which Supabase populates directly from the verified Bearer token.
--
-- COALESCE fallback keeps dev mode working (no JWT → fall back to session vars).
-- ALL existing RLS policies continue to work unchanged — only the function
-- implementations change.
-- ==============================================================================

CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS UUID AS $$
  SELECT COALESCE(
    -- Production: Auth0 JWT verified natively by Supabase
    (auth.jwt() ->> 'https://wellbridge.app/tenant_id')::UUID,
    -- Dev mode fallback: session variable set by get_scoped_client()
    NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
  );
$$ LANGUAGE sql STABLE SECURITY DEFINER;

CREATE OR REPLACE FUNCTION current_user_id() RETURNS TEXT AS $$
  SELECT COALESCE(
    -- Production: Auth0 sub from verified JWT
    auth.jwt() ->> 'sub',
    -- Dev mode fallback: session variable set by get_scoped_client()
    NULLIF(current_setting('app.user_id', TRUE), '')
  );
$$ LANGUAGE sql STABLE SECURITY DEFINER;
