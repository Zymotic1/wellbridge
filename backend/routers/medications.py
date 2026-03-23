"""
Medications router — GET /medications

Provides endpoints for listing active and past medications, with dose
change history support via the predecessor_id chain.

Uses the admin client (service-role) with explicit tenant/user filters
for the same reasons documented in users.py.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.tenant import get_tenant_context, TenantContext
from services.supabase_client import get_admin_client

log = logging.getLogger("wellbridge.medications")

router = APIRouter(prefix="/medications", tags=["medications"])


@router.get("/")
async def list_medications(
    status: str = Query(None, description="Filter by status: active, discontinued, adjusted"),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    List the patient's medications, optionally filtered by status.

    Returns medications sorted by name, with dose history available
    via the /medications/{id}/history endpoint.
    """
    try:
        db = get_admin_client()
        query = (
            db.table("medications")
            .select("id, name, dose, frequency, instructions, status, "
                    "prescribed_date, discontinued_date, predecessor_id, "
                    "source_record_id, created_at, updated_at")
            .eq("tenant_id", ctx.tenant_id)
            .eq("user_id", ctx.user_id)
            .order("name")
        )
        if status:
            query = query.eq("status", status)

        result = query.execute()
        return {"medications": result.data or []}
    except Exception as exc:
        log.error("list_medications: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{medication_id}/history")
async def medication_history(
    medication_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get the dose change history for a specific medication.

    Follows the predecessor_id chain backward to build a chronological
    history of dose adjustments. Returns oldest-first.
    """
    try:
        db = get_admin_client()

        # Start with the requested medication
        current = (
            db.table("medications")
            .select("id, name, dose, frequency, instructions, status, "
                    "prescribed_date, discontinued_date, predecessor_id, created_at")
            .eq("id", medication_id)
            .eq("tenant_id", ctx.tenant_id)
            .eq("user_id", ctx.user_id)
            .limit(1)
            .execute()
        )
        if not current.data:
            raise HTTPException(status_code=404, detail="Medication not found.")

        # Build history chain
        history = [current.data[0]]
        seen = {medication_id}
        pred_id = current.data[0].get("predecessor_id")

        # Walk backward through predecessors (max 20 to prevent infinite loops)
        while pred_id and pred_id not in seen and len(history) < 20:
            seen.add(pred_id)
            pred = (
                db.table("medications")
                .select("id, name, dose, frequency, instructions, status, "
                        "prescribed_date, discontinued_date, predecessor_id, created_at")
                .eq("id", pred_id)
                .eq("tenant_id", ctx.tenant_id)
                .limit(1)
                .execute()
            )
            if not pred.data:
                break
            history.append(pred.data[0])
            pred_id = pred.data[0].get("predecessor_id")

        # Return oldest-first
        history.reverse()
        return {"history": history}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("medication_history: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
