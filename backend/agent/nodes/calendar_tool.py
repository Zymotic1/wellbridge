"""
Calendar tool node — handles scheduling intents.

Fetches upcoming appointments from the appointments table (Supabase, RLS-scoped)
and presents them to the user. Creating/modifying appointments is handled by
the /appointments and /ocr routes, not this node.

For natural-language scheduling requests (e.g., "book an appointment with Dr. Smith"),
this node returns a prompt to the user to use the Appointments page, since direct
calendar write access requires an OAuth flow that cannot happen mid-chat.
"""

from agent.state import AgentState
from services.supabase_client import get_scoped_client
from middleware.tenant import TenantContext


async def run(state: AgentState) -> dict:
    ctx = TenantContext(
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        role=state["role"],
    )

    try:
        db = get_scoped_client(ctx)
        result = (
            db.table("appointments")
            .select("provider_name, facility_name, appointment_date, duration_minutes, notes")
            .gte("appointment_date", "now()")
            .order("appointment_date")
            .limit(5)
            .execute()
        )

        appointments = result.data or []
        state_update: dict = {"appointments": appointments}

        if not appointments:
            state_update["raw_response"] = (
                "I don't see any upcoming appointments in your account. "
                "You can add them manually in the Appointments section, or "
                "upload a discharge paper to automatically detect follow-up dates."
            )
            state_update["jargon_map"] = []
            return state_update

        lines = []
        for appt in appointments:
            date = str(appt.get("appointment_date", ""))[:10]
            provider = appt.get("provider_name", "Unknown provider")
            facility = appt.get("facility_name", "")
            loc_str = f" at {facility}" if facility else ""
            lines.append(f"\u2022 {date} — {provider}{loc_str}")

        raw = f"You have {len(appointments)} upcoming appointment(s):\n\n" + "\n".join(lines)
        raw += "\n\nWould you like me to help you prepare questions for any of these?"

        state_update["raw_response"] = raw
        state_update["jargon_map"] = []
        return state_update

    except Exception as exc:
        return {
            "appointments": [],
            "tool_error": str(exc),
            "raw_response": "I had trouble fetching your appointments. Please try again.",
            "jargon_map": [],
        }
