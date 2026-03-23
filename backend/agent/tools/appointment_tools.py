"""
Appointment tools — database operations for appointments.
"""

import logging
from services.supabase_client import get_admin_client

log = logging.getLogger("wellbridge.tools.appointments")


async def get_appointments(tenant_id: str, user_id: str) -> dict:
    """Get upcoming appointments for the patient."""
    try:
        db = get_admin_client()
        result = (
            db.table("appointments")
            .select("id, provider_name, facility_name, appointment_date, duration_minutes, notes, phone, address")
            .eq("tenant_id", tenant_id)
            .eq("patient_user_id", user_id)
            .gte("appointment_date", "now()")
            .order("appointment_date")
            .limit(5)
            .execute()
        )
        appointments = result.data or []
        return {
            "appointments": [
                {
                    "provider": a.get("provider_name", "Your doctor"),
                    "facility": a.get("facility_name", ""),
                    "date": a.get("appointment_date", ""),
                    "duration_minutes": a.get("duration_minutes", 30),
                    "notes": a.get("notes", ""),
                    "phone": a.get("phone", ""),
                    "address": a.get("address", ""),
                }
                for a in appointments
            ],
            "total": len(appointments),
        }
    except Exception as exc:
        return {"appointments": [], "total": 0, "error": str(exc)}
