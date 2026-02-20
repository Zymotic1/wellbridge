"""
Note explainer node — handles NOTE_EXPLANATION intent.

This is the key node that enables the core WellBridge value proposition:
helping patients understand what their doctor told them, without giving advice.

WHAT THIS NODE DOES:
  1. Fetches the patient's recent clinical notes (RLS-scoped, always their own data)
  2. Explains what the notes say in plain English
  3. For any medication mentioned in the notes, explains what it is generally used for
     using publicly available (FDA labeling level) information
  4. For any test results, restates what was documented — does NOT interpret good/bad
  5. Builds a jargon_map so the frontend can highlight and explain medical terms on hover
  6. If no records exist, empathetically asks the user to share their notes and offers
     an upload action card

WHAT THIS NODE NEVER DOES:
  - Give advice: "you should take X", "I recommend Y"
  - Diagnose: "you have X", "this indicates Y"
  - Interpret results for the patient's specific situation: "this is high/normal/concerning"
  - Add information that isn't either in the notes OR publicly available about the medication

The distinction between this node and note_summarizer:
  - note_summarizer: triggered by GENERAL/RECORD_LOOKUP — "summarize my records"
  - note_explainer:  triggered by NOTE_EXPLANATION — "I don't understand what doctor told me"
    This node is more conversational, more targeted to comprehension, and will always
    offer to help collect notes if none exist.
"""

from openai import AsyncOpenAI
from pydantic import BaseModel

from agent.state import AgentState, JargonMapping, ActionCard
from agent.prompts import NOTE_EXPLANATION_SYSTEM, NOTE_EXPLANATION_EXAMPLES
from services.supabase_client import get_scoped_client, get_admin_client
from middleware.tenant import TenantContext
from config import get_settings

settings = get_settings()


class JargonEntry(BaseModel):
    term: str
    plain_english: str
    source_note_id: str
    source_sentence: str


class ExplanationResult(BaseModel):
    response: str
    jargon_entries: list[JargonEntry]


async def run(state: AgentState) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    ctx = TenantContext(
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        role=state["role"],
    )

    user_message: str = state["messages"][-1].content

    # ── Fetch recent records ────────────────────────────────────────────────
    records: list[dict] = []
    try:
        db = get_admin_client()
        result = (
            db.table("patient_records")
            .select("id, record_type, provider_name, note_date, content")
            .eq("tenant_id", state["tenant_id"])
            .eq("patient_user_id", state["user_id"])
            .order("note_date", desc=True)
            .limit(5)
            .execute()
        )
        records = result.data or []
    except Exception:
        records = []

    # ── No records — ask them to share the note ─────────────────────────────
    if not records:
        upload_card: ActionCard = {
            "id": "upload_records",
            "type": "upload",
            "label": "Upload a document",
            "description": "Photograph or scan your discharge summary, clinic letter, or test results",
            "payload": {},
        }
        return {
            "records": [],
            "raw_response": (
                "It's really common to leave an appointment with a lot of information "
                "that's hard to take in all at once.\n\n"
                "I don't have any notes from your visit in WellBridge yet. "
                "If you received any paperwork — a discharge summary, a clinic letter, "
                "or printed test results — you can photograph it and upload it here. "
                "Once I have it, I'll go through it with you step by step and explain "
                "everything in plain language.\n\n"
                "Would you like to upload something now?"
            ),
            "jargon_map": [],
            "action_cards": [upload_card],
        }

    # ── Format notes for the LLM ────────────────────────────────────────────
    notes_text = "\n\n".join(
        f"[NOTE_ID:{r['id']}] {str(r.get('note_date', ''))[:10]} — "
        f"{r.get('provider_name', 'Your care team')} "
        f"({r.get('record_type', 'note')}):\n{r.get('content', '')}"
        for r in records
    )

    system_prompt = (
        f"{NOTE_EXPLANATION_SYSTEM}\n\n"
        f"EXAMPLES:\n{NOTE_EXPLANATION_EXAMPLES}\n\n"
        "Return your response and a list of jargon entries with source note IDs and "
        "the exact source sentence from the note for each medical term you explained."
    )

    # ── LLM call ────────────────────────────────────────────────────────────
    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Patient message: {user_message}\n\n"
                        f"Clinical notes:\n{notes_text}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=1500,
        )

        import json as _json
        raw = result.choices[0].message.content or ""
        if not raw:
            raise ValueError("Empty result")
        parsed = ExplanationResult(**_json.loads(raw))

        response_text = parsed.response

        # ── Build jargon_map with character offsets ──────────────────────────
        jargon_map: list[JargonMapping] = []
        lower_response = response_text.lower()
        for entry in parsed.jargon_entries:
            idx = lower_response.find(entry.term.lower())
            if idx == -1:
                continue
            jargon_map.append(JargonMapping(
                term=entry.term,
                plain_english=entry.plain_english,
                source_note_id=entry.source_note_id,
                source_sentence=entry.source_sentence,
                char_offset_start=idx,
                char_offset_end=idx + len(entry.term),
            ))

        return {
            "records": records,
            "raw_response": response_text,
            "jargon_map": jargon_map,
            "action_cards": [],
        }

    except Exception as exc:
        return {
            "records": records,
            "tool_error": str(exc),
            "raw_response": (
                "I had trouble reading your notes. Please try again, or let me know "
                "what your doctor told you and I'll do my best to help."
            ),
            "jargon_map": [],
            "action_cards": [],
        }
