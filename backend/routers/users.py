"""
User profile router — GET/PATCH /users/me

Allows patients to read and update their stored first/last name.

WHY admin client: The patients table RLS uses app.tenant_id / app.user_id
session variables. In production, get_scoped_client() passes the Auth0 JWT
to PostgREST, which never sets those session variables, so the RLS USING clause
(tenant_id = current_tenant_id()) always evaluates to false and returns zero rows.

Using the admin (service-role) client bypasses RLS, which is safe here because:
  1. We explicitly filter by ctx.tenant_id and ctx.user_id in every query.
  2. The TenantContext is extracted from a validated Auth0 JWT — users cannot
     forge these values.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.tenant import get_tenant_context, TenantContext
from services.supabase_client import get_admin_client

router = APIRouter(prefix="/users", tags=["users"])


class ProfileUpdate(BaseModel):
    first_name: str
    last_name: str = ""


@router.get("/me")
async def get_profile(ctx: TenantContext = Depends(get_tenant_context)):
    """Return the current user's stored profile (first_name, last_name, display_name)."""
    try:
        db = get_admin_client()
        result = (
            db.table("patients")
            .select("first_name, last_name, display_name")
            .eq("tenant_id", ctx.tenant_id)
            .eq("user_id", ctx.user_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return {"first_name": None, "last_name": None, "display_name": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/me")
async def update_profile(
    body: ProfileUpdate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Upsert first_name and last_name for the current user.
    Creates the patients row if it doesn't exist yet.
    """
    first = body.first_name.strip()
    last = body.last_name.strip()
    if not first:
        raise HTTPException(status_code=422, detail="first_name is required.")

    display_name = f"{first} {last}".strip()

    try:
        db = get_admin_client()
        db.table("patients").upsert(
            {
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "first_name": first,
                "last_name": last,
                "display_name": display_name,
            },
            on_conflict="tenant_id,user_id",
        ).execute()
        return {"first_name": first, "last_name": last, "display_name": display_name}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
