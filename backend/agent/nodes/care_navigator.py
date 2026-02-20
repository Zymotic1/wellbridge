"""
Care navigator node — handles CARE_NAVIGATION intent.

This is the proactive, empathetic core of the WellBridge experience.
When a user is navigating their health journey — sharing news, expressing
emotions, or simply describing their situation — this node responds with
warmth and gentle guidance rather than a form or task list.

Key behaviors:
  - Validates the patient's experience before informing
  - Adapts tone based on emotional_state from the assessor
  - Surfaces what they likely need next (records, prep questions, etc.)
  - Grounds everything in documented records when available
  - Asks at most ONE question per response
  - If the user mentions having a note/document, ALWAYS returns an upload
    action card — never a generic "tell me more" loop
"""

import re

from openai import AsyncOpenAI
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState, ActionCard
from agent.prompts import CARE_NAVIGATOR_SYSTEM, CARE_NAVIGATOR_EXAMPLES
from services.supabase_client import get_scoped_client, get_admin_client
from config import get_settings

settings = get_settings()

# Phrases that indicate the user has a physical document to share
_HAS_DOCUMENT_PATTERN = re.compile(
    r"\b(note|notes|letter|report|discharge|summary|paperwork|document|papers|"
    r"prescription|results?|scan|lab|form|records?)\b",
    re.IGNORECASE,
)
_GAVE_OR_HAS_PATTERN = re.compile(
    r"\b(gave|given|got|received|have|has|here|bring|brought|upload|photo|photograph|"
    r"picture|don'?t understand|can'?t read|summarize|explain|help me|help with)\b",
    re.IGNORECASE,
)


def _user_has_document(message: str) -> bool:
    """Return True if the message strongly suggests the user has a physical document."""
    return bool(_HAS_DOCUMENT_PATTERN.search(message) and _GAVE_OR_HAS_PATTERN.search(message))


def _build_context_block(state: AgentState) -> str:
    """Build a context string for the navigator from available state."""
    parts = []

    emotional_state = state.get("emotional_state", "calm")
    care_stage = state.get("care_stage", "unknown")
    parts.append(f"Patient emotional state: {emotional_state}")
    parts.append(f"Care stage: {care_stage}")

    facts = state.get("care_context", {}).get("facts", [])
    if facts:
        parts.append(f"Known facts from conversation: {'; '.join(facts)}")

    records = state.get("records", [])
    if records:
        record_summaries = []
        for r in records[:3]:
            date = r.get("note_date", "unknown date")
            provider = r.get("provider_name", "unknown provider")
            content = r.get("content", "")[:200]
            record_summaries.append(f"[{date}, {provider}]: {content}")
        parts.append("Recent records:\n" + "\n".join(record_summaries))
    else:
        parts.append("No records found in the patient's profile yet.")

    appointments = state.get("appointments", [])
    if appointments:
        next_appt = appointments[0]
        parts.append(
            f"Next appointment: {next_appt.get('provider_name', 'unknown')} "
            f"on {next_appt.get('appointment_date', 'unknown date')}"
        )

    return "\n".join(parts)


async def run(state: AgentState) -> dict:
    """
    Generate an empathetic, proactive care navigation response.
    Fetches recent records to ground the response in documented facts.
    """
    last_message = state["messages"][-1].content if state.get("messages") else ""

    # ── Fast path: user explicitly has a document — offer upload immediately ─
    if _user_has_document(last_message):
        upload_card: ActionCard = {
            "id": "upload_note",
            "type": "upload",
            "label": "Upload your note or letter",
            "description": "Photograph or scan the document — I'll read through it and explain everything in plain language",
            "payload": {},
        }
        return {
            "raw_response": (
                "Of course — I'd love to help you make sense of it.\n\n"
                "You can photograph or scan the note and upload it here. "
                "Once I have it, I'll go through everything step by step: "
                "what the doctor documented, what any prescriptions are for, "
                "any follow-up appointments, and any terms that might be confusing.\n\n"
                "Would you like to upload it now?"
            ),
            "action_cards": [upload_card],
            "jargon_map": [],
        }

    if not settings.openai_configured:
        return {
            "raw_response": (
                "I'm here with you. What's going on — did something happen at your "
                "appointment, or is there something you'd like help understanding?"
            ),
            "action_cards": [],
            "jargon_map": [],
        }

    # Fetch recent records and appointments for context
    try:
        db = get_admin_client()

        records_result = (
            db.table("patient_records")
            .select("id, note_date, provider_name, content, record_type")
            .eq("tenant_id", state["tenant_id"])
            .eq("patient_user_id", state["user_id"])
            .order("note_date", desc=True)
            .limit(3)
            .execute()
        )
        state = {**state, "records": records_result.data or []}

        appt_result = (
            db.table("appointments")
            .select("provider_name, appointment_date, notes")
            .eq("tenant_id", state["tenant_id"])
            .eq("patient_user_id", state["user_id"])
            .gte("appointment_date", "now()")
            .order("appointment_date")
            .limit(1)
            .execute()
        )
        state = {**state, "appointments": appt_result.data or []}
    except Exception:
        pass

    context_block = _build_context_block(state)

    history = []
    for msg in state.get("messages", [])[-7:-1]:
        if isinstance(msg, HumanMessage):
            history.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            history.append({"role": "assistant", "content": msg.content})

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        CARE_NAVIGATOR_SYSTEM
                        + f"\n\nCURRENT CONTEXT:\n{context_block}"
                        + f"\n\nEXAMPLES:\n{CARE_NAVIGATOR_EXAMPLES}"
                    ),
                },
                *history,
                {"role": "user", "content": last_message},
            ],
            temperature=0.4,
            max_tokens=500,
        )
        raw_response = response.choices[0].message.content or ""
    except Exception:
        raw_response = (
            "I'm here. What's going on — did something happen at your appointment, "
            "or is there something you'd like help understanding?"
        )

    # Build context-aware action cards and suggested replies
    action_cards: list[ActionCard] = []
    records = state.get("records", [])
    care_stage = state.get("care_stage", "unknown")

    if not records:
        # No records at all — offer upload if context suggests post-visit or diagnosis
        if care_stage in ("post-visit", "post-surgery", "diagnosis", "treatment"):
            action_cards.append({
                "id": "upload_note",
                "type": "upload",
                "label": "Upload a note or letter",
                "description": "Share any paperwork from your visit and I'll help explain it",
                "payload": {},
            })
        suggested_replies = [
            "I have a note from my doctor to share",
            "What can WellBridge help me with?",
            "Tell me more about how this works",
        ]
    else:
        # Records exist — guide user toward useful next actions
        suggested_replies = [
            "What questions should I ask my doctor?",
            "Can you summarize my recent records?",
            "What should I focus on next?",
        ]

    return {
        "raw_response": raw_response,
        "records": state.get("records", []),
        "appointments": state.get("appointments", []),
        "action_cards": action_cards,
        "suggested_replies": suggested_replies,
        "jargon_map": [],
    }
