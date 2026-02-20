"""
Records router — CRUD for patient_records.

All endpoints use get_scoped_client(), which enforces RLS at the database
level. The application-level ownership check in POST is belt-and-suspenders.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from middleware.tenant import get_tenant_context, TenantContext
from services.supabase_client import get_scoped_client, get_admin_client

router = APIRouter(prefix="/records", tags=["records"])


class RecordCreate(BaseModel):
    record_type: str
    provider_name: Optional[str] = None
    facility_name: Optional[str] = None
    note_date: datetime
    content: str
    content_fhir: Optional[dict] = None


@router.get("/")
async def list_records(
    ctx: TenantContext = Depends(get_tenant_context),
    limit: int = 20,
    offset: int = 0,
):
    """List the authenticated patient's records (explicit tenant/user filtering)."""
    try:
        db = get_admin_client()
        result = (
            db.table("patient_records")
            .select("id, record_type, provider_name, facility_name, note_date, content, created_at")
            .eq("tenant_id", ctx.tenant_id)
            .eq("patient_user_id", ctx.user_id)
            .order("note_date", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return {"records": result.data or [], "total": len(result.data or [])}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{record_id}")
async def get_record(
    record_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Fetch a single record. Explicit tenant/user filtering ensures the user can only access their own records."""
    try:
        db = get_admin_client()
        result = (
            db.table("patient_records")
            .select("*")
            .eq("tenant_id", ctx.tenant_id)
            .eq("patient_user_id", ctx.user_id)
            .eq("id", record_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Record not found.")
        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_record(
    body: RecordCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Create a new patient record."""
    try:
        db = get_admin_client()
        result = (
            db.table("patient_records")
            .insert({
                "tenant_id": ctx.tenant_id,
                "patient_user_id": ctx.user_id,
                "record_type": body.record_type,
                "provider_name": body.provider_name,
                "facility_name": body.facility_name,
                "note_date": body.note_date.isoformat(),
                "content": body.content,
                "content_fhir": body.content_fhir,
            })
            .execute()
        )
        return result.data[0]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Delete a record. Explicit tenant/user filtering enforces ownership — only the owner can delete."""
    try:
        db = get_admin_client()
        result = (
            db.table("patient_records")
            .delete()
            .eq("tenant_id", ctx.tenant_id)
            .eq("patient_user_id", ctx.user_id)
            .eq("id", record_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Record not found or access denied.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
