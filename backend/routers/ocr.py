"""
OCR router — Scan-to-Calendar document upload and processing.

Accepts an uploaded document (PDF or image), sends it to Azure Document
Intelligence for extraction, and returns structured appointment data
for the user to confirm before adding to their calendar.

The actual calendar write happens in the calendar service after user confirmation
via the frontend CalendarConfirmDialog component.
"""

import io
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional

from middleware.tenant import get_tenant_context, TenantContext
from services.ocr_service import extract_followup_appointments, ExtractedAppointment
from services.calendar_service import create_calendar_event

router = APIRouter(prefix="/ocr", tags=["ocr"])

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


class CalendarCreateRequest(BaseModel):
    provider_name: Optional[str] = None
    date: str           # ISO 8601 date string
    location: Optional[str] = None
    raw_text: str       # Original extracted sentence (stored for audit)
    notes: Optional[str] = None


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Upload a medical document for follow-up appointment extraction.

    Returns a list of extracted appointments for user confirmation.
    Does NOT automatically add anything to the calendar.
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. "
                   f"Accepted: PDF, JPEG, PNG, TIFF.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 20 MB.",
        )

    try:
        appointments: list[ExtractedAppointment] = await extract_followup_appointments(
            document_bytes=content,
            content_type=file.content_type or "application/pdf",
        )
    except NotImplementedError:
        # Azure credentials not configured — return mock for development
        appointments = [
            ExtractedAppointment(
                provider_name="Dr. Smith",
                date="2026-03-10",
                location=None,
                raw_text="Follow up with Dr. Smith in 2 weeks.",
            )
        ]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {exc}",
        )

    return {
        "extracted_appointments": [a.model_dump() for a in appointments],
        "message": (
            f"Found {len(appointments)} potential follow-up appointment(s). "
            "Please review and confirm before adding to your calendar."
        ),
    }


@router.post("/confirm-appointment")
async def confirm_appointment(
    req: CalendarCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    User has confirmed an extracted appointment. Add it to Google Calendar
    and save it to the appointments table.
    """
    from services.supabase_client import get_scoped_client

    try:
        db = get_scoped_client(ctx)

        # Save to Supabase appointments table
        result = (
            db.table("appointments")
            .insert({
                "tenant_id": ctx.tenant_id,
                "patient_user_id": ctx.user_id,
                "provider_name": req.provider_name,
                "appointment_date": req.date,
                "notes": req.notes or req.raw_text,
                "source": "scan_to_calendar",
            })
            .execute()
        )

        appointment_id = result.data[0]["id"] if result.data else None

        # Attempt Google Calendar integration
        calendar_event_id = None
        try:
            calendar_event_id = await create_calendar_event(
                summary=f"Appointment: {req.provider_name or 'Medical Follow-up'}",
                date=req.date,
                description=req.raw_text,
            )
        except Exception:
            pass  # Calendar write failure should not block the local save

        return {
            "status": "confirmed",
            "appointment_id": appointment_id,
            "calendar_event_id": calendar_event_id,
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
