"""
Note explainer node — handles NOTE_EXPLANATION intent.

This node enables the core WellBridge value proposition: helping patients
understand what their doctor told them, without giving advice.

INTELLIGENCE HIERARCHY:
  1. If the user asks about something IN their records → explain from records + public info
  2. If the user asks a general medical knowledge question (side effects, what a drug does)
     → answer from publicly available (FDA-level) information, even without records
  3. If the user asks about a specific visit but has no records → guide them to upload

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
from agent.prompts import NOTE_EXPLANATION_SYSTEM, NOTE_EXPLANATION_EXAMPLES, MEDICATION_INFO_SYSTEM
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


# Patterns that indicate a public-knowledge question (doesn't require records)
import re
_PUBLIC_KNOWLEDGE_PATTERNS = [
    re.compile(r"\b(?:what\s+(?:is|are)|tell\s+me\s+about)\b.*\b(?:side\s+effects?|used\s+for|medication|drug|medicine)\b", re.I),
    re.compile(r"\b(?:side\s+effects?|common\s+effects?)\s+(?:of|for)\b", re.I),
    re.compile(r"\b(?:what\s+does|what\s+is)\b.*\b(?:do|treat|for|used)\b", re.I),
    re.compile(r"\b(?:how\s+does)\b.*\b(?:work|help)\b", re.I),
]


def _is_public_knowledge_question(message: str) -> bool:
    """Detect if the question can be answered from public FDA-level info."""
    return any(p.search(message) for p in _PUBLIC_KNOWLEDGE_PATTERNS)


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

    # ── No records: check if it's a public knowledge question ─────────────
    if not records:
        if _is_public_knowledge_question(user_message):
            return await _answer_from_public_knowledge(client, user_message)

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

    # ── LLM call with records ────────────────────────────────────────────────
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

        # ── Intelligent fallback: try answering from public knowledge ────────
        if _is_public_knowledge_question(user_message):
            log.info("note_explainer: falling back to public knowledge for medication question")
            return await _answer_from_public_knowledge(client, user_message, records=records)

        # ── Last resort: guide the user ──────────────────────────────────────
        upload_card: ActionCard = {
            "id": "upload_records",
            "type": "upload",
            "label": "Upload your visit notes",
            "description": "Photograph or scan your discharge summary, clinic letter, or test results",
            "payload": {},
        }

        if records:
            fallback_msg = (
                "I can see you have some records on file, but I wasn't able to process "
                "them just now.\n\n"
                "If you're asking about a **recent visit**, the notes from that visit "
                "might not be uploaded yet. You can share them by tapping the paperclip "
                "button or the upload button below.\n\n"
                "Or, you can tell me what your doctor said in your own words and I'll "
                "help you make sense of it."
            )
        else:
            fallback_msg = (
                "It sounds like you'd like help understanding what your doctor told you — "
                "that's exactly what I'm here for.\n\n"
                "To get started, I'll need your visit notes. You can upload them using "
                "the paperclip button or the button below."
            )

        return {
            "records": records,
            "tool_error": str(exc),
            "raw_response": fallback_msg,
            "jargon_map": [],
            "action_cards": [upload_card],
        }


async def _answer_from_public_knowledge(
    client: AsyncOpenAI,
    user_message: str,
    records: list[dict] | None = None,
) -> dict:
    """
    Answer a medication/condition question from publicly available (FDA-level)
    information. Used when the question doesn't require personal records.
    """
    system = (
        f"{MEDICATION_INFO_SYSTEM}\n\n"
        "Additionally:\n"
        "- Explain common, publicly known side effects\n"
        "- Write at a 6th-grade reading level\n"
        "- Use [JARGON: term | plain_english] for medical terms\n"
        "- End with: 'If you have specific concerns, please discuss them with your doctor or pharmacist.'\n"
        "- NEVER say whether the patient should take or stop taking the medication\n"
    )

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_completion_tokens=1000,
        )
        raw = result.choices[0].message.content or ""
        if not raw.strip():
            raise ValueError("Empty response")

        raw += (
            "\n\n*This is general information from publicly available sources. "
            "It is not personalized medical advice. Please ask your pharmacist "
            "or doctor about your specific situation.*"
        )

        return {
            "records": records or [],
            "raw_response": raw,
            "jargon_map": [],
            "action_cards": [],
        }

    except Exception as exc:
        log.warning("note_explainer: public knowledge fallback failed — %s", exc)
        return {
            "records": records or [],
            "raw_response": (
                "I wasn't able to look that up just now. You can try asking again, "
                "or ask your pharmacist — they're a great resource for medication questions."
            ),
            "jargon_map": [],
            "action_cards": [],
        }
