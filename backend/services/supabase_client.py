"""
Supabase client factory.

IMPORTANT: This module is the only place that creates Supabase clients.
All data-access code must use get_scoped_client() — never instantiate
a raw client elsewhere. This ensures RLS session variables are always set.

Two clients are provided:
  - get_scoped_client(ctx)  — sets app.tenant_id and app.user_id so RLS
                               policies are enforced for the current user
  - get_admin_client()      — service role, bypasses RLS; use ONLY for
                               migrations, background jobs, or explicit
                               admin endpoints that check permissions themselves
"""

from supabase import create_client, Client
from middleware.tenant import TenantContext
from config import get_settings

settings = get_settings()


def get_admin_client() -> Client:
    """
    Service-role Supabase client. Bypasses RLS.
    Use with caution — verify authorization in application code before
    calling any query with this client.
    """
    return create_client(settings.supabase_url, settings.supabase_service_key)


def get_scoped_client(ctx: TenantContext) -> Client:
    """
    Returns a Supabase client with RLS session variables set for the
    given TenantContext. Every query executed on this client will be
    filtered by the current_tenant_id() and current_user_id() RLS policies.

    The is_local=True flag scopes each setting to the current transaction,
    preventing session variable leakage between concurrent requests.

    Also auto-provisions the tenants row on first request — the Auth0 action
    generates a deterministic UUID but does not insert into Supabase directly,
    so we upsert here using the admin (service-role) client.
    """
    # Always use the admin client to auto-provision the tenant row (no-op if exists)
    admin = create_client(settings.supabase_url, settings.supabase_service_key)
    admin.table("tenants").upsert(
        {
            "id":            ctx.tenant_id,
            "owner_user_id": ctx.user_id,
            "name":          ctx.user_id,
        },
        on_conflict="id",
    ).execute()

    if ctx.raw_token and settings.supabase_anon_key:
        # Production path — pass Auth0 JWT to Supabase so it verifies natively.
        # RLS policies use auth.jwt() which Supabase populates from this token.
        # No manual session variable setting needed.
        client = create_client(settings.supabase_url, settings.supabase_anon_key)
        client.postgrest.auth(ctx.raw_token)
        return client

    # Dev mode fallback — no real JWT; set session variables manually so the
    # COALESCE fallback in current_tenant_id() / current_user_id() still works.
    admin.rpc("set_config", {
        "setting": "app.tenant_id",
        "value":   str(ctx.tenant_id),
        "is_local": True,
    }).execute()
    admin.rpc("set_config", {
        "setting": "app.user_id",
        "value":   ctx.user_id,
        "is_local": True,
    }).execute()
    return admin
