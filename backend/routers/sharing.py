"""
Sharing router — RBAC grant/revoke for Trusted Individual Access.

Allows patients to share records with family members or caregivers.
Only the record owner can grant or revoke access. Grantees can only
read their active shares.

All operations are tenant-scoped via TenantContext from the JWT.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from middleware.tenant import get_tenant_context, TenantContext
from services.supabase_client import get_scoped_client

router = APIRouter(prefix="/sharing", tags=["sharing"])


class ShareGrantRequest(BaseModel):
    record_id: str
    granted_to_user_id: str
    role: str           # "viewer" | "editor"
    expires_at: Optional[str] = None  # ISO 8601 datetime string


@router.get("/my-shares")
async def list_my_shares(ctx: TenantContext = Depends(get_tenant_context)):
    """List all shares the authenticated user has granted to others."""
    try:
        db = get_scoped_client(ctx)
        result = (
            db.table("record_shares")
            .select("id, record_id, granted_to, role, expires_at, created_at")
            .eq("granted_by", ctx.user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return {"shares": result.data or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/shared-with-me")
async def list_shared_with_me(ctx: TenantContext = Depends(get_tenant_context)):
    """List all records that have been shared with the authenticated user."""
    try:
        db = get_scoped_client(ctx)
        result = (
            db.table("record_shares")
            .select("id, record_id, granted_by, role, expires_at, created_at")
            .eq("granted_to", ctx.user_id)
            .execute()
        )
        return {"shares": result.data or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/grant", status_code=status.HTTP_201_CREATED)
async def grant_access(
    req: ShareGrantRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Grant another user access to one of your records.
    Only the record owner can grant access.
    """
    if req.role not in ("viewer", "editor"):
        raise HTTPException(
            status_code=422,
            detail="Role must be 'viewer' or 'editor'.",
        )

    if req.granted_to_user_id == ctx.user_id:
        raise HTTPException(
            status_code=422,
            detail="Cannot share a record with yourself.",
        )

    try:
        db = get_scoped_client(ctx)

        # Verify ownership — the RLS select policy also enforces this,
        # but we check explicitly for a clear error message
        record = (
            db.table("patient_records")
            .select("patient_user_id")
            .eq("id", req.record_id)
            .single()
            .execute()
        )

        if not record.data:
            raise HTTPException(status_code=404, detail="Record not found.")

        if record.data["patient_user_id"] != ctx.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the record owner can grant access.",
            )

        result = (
            db.table("record_shares")
            .insert({
                "tenant_id": ctx.tenant_id,
                "record_id": req.record_id,
                "granted_by": ctx.user_id,
                "granted_to": req.granted_to_user_id,
                "role": req.role,
                "expires_at": req.expires_at,
            })
            .execute()
        )

        return {"status": "granted", "share": result.data[0]}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/revoke/{share_id}", status_code=status.HTTP_200_OK)
async def revoke_access(
    share_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Revoke a share. Only the granter can revoke.
    The RLS policy ensures granted_by = current_user_id() for DELETE.
    """
    try:
        db = get_scoped_client(ctx)
        result = (
            db.table("record_shares")
            .delete()
            .eq("id", share_id)
            .eq("granted_by", ctx.user_id)  # Explicit check, belt-and-suspenders
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Share not found or you are not authorized to revoke it.",
            )
        return {"status": "revoked"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
