"""
Note explainer node — handles NOTE_EXPLANATION intent.

This node explains the patient's OWN clinical records in plain language.
It is only reached when the triage determines information_source=patient_records
(or via the supervisor for complex multi-agent queries).

Public knowledge questions (medication side effects, condition explanations, etc.)
are now routed to the public_knowledge node by the triage — this node no longer
needs to handle them.

This node NEVER:
  - Gives advice: "you should take X", "I recommend Y"
  - Diagnoses: "you have X", "this indicates Y"
  - Interprets results: "this is high/normal/concerning"
"""

import json as _json
import logging

from openai import AsyncOpenAI
from services.openai_client import get_openai_client
from pydantic import BaseModel

from agent.state import AgentState, JargonMapping, ActionCard
from agent.prompts import NOTE_EXPLANATION_SYSTEM, NOTE_EXPLANATION_EXAMPLES
from services.supabase_client import get_admin_client
from middleware.tenant import TenantContext
from config import get_settings

log = logging.getLogger("wellbridge.note_explainer")
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
    client = get_openai_client()
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

    # ── No records — guide them to upload ─────────────────────────────────
    if not records:
        upload_card: ActionCard = {
            "id": "upload_records",
            "type": "upload",
            "label": "Upload your visit notes",
            "description": "Photograph or scan your discharge summary, clinic letter, or test results",
            "payload": {},
        }
        return {
            "records": [],
            "raw_response": (
                "It sounds like you'd like help understanding what your doctor told you — "
                "that's exactly what I'm here for.\n\n"
                "To get started, I'll need your visit notes. If you received any "
                "paperwork — a discharge summary, clinic letter, or printed results — "
                "you can photograph it and upload it using the paperclip button or the "
                "button below.\n\n"
                "If you don't have the paperwork handy, you can also tell me what your "
                "doctor said in your own words and I'll help explain it."
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
        "Return JSON with your response and a list of jargon entries with source note IDs and "
        "the exact source sentence from the note for each medical term you explained."
    )

    # ── Primary LLM call ────────────────────────────────────────────────────
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
            max_completion_tokens=3000,
        )

        raw = result.choices[0].message.content or ""
        if not raw.strip():
            raise ValueError(f"Empty response (finish_reason={result.choices[0].finish_reason})")
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
        log.warning("note_explainer: LLM call failed — %s", exc)

        # Smart fallback: show what records we have and offer guidance
        upload_card: ActionCard = {
            "id": "upload_records",
            "type": "upload",
            "label": "Upload your visit notes",
            "description": "Photograph or scan your discharge summary, clinic letter, or test results",
            "payload": {},
        }

        # Build a helpful summary of available records
        record_summary = "\n".join(
            f"• {r.get('provider_name', 'Document')} ({r.get('record_type', 'note')}, "
            f"{str(r.get('note_date', ''))[:10]})"
            for r in records[:5]
        )

        fallback_msg = (
            f"I can see you have these records on file:\n{record_summary}\n\n"
            "I wasn't able to process them right now. You can try:\n"
            "• Asking a more specific question, like \"What medications are listed in my notes?\"\n"
            "• Uploading a new document if you're asking about a recent visit\n"
            "• Telling me what your doctor said in your own words"
        )

        return {
            "records": records,
            "tool_error": str(exc),
            "raw_response": fallback_msg,
            "jargon_map": [],
            "action_cards": [upload_card],
        }
