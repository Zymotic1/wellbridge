"""
Note summarizer node — translates clinical notes into 6th-grade English.

This node is responsible for the jargon_map that powers the frontend hover feature.
It runs two structured GPT-4o calls:
  1. Summarize the notes in plain English
  2. Extract all medical terms with their plain-English definitions and the
     exact source sentence from the original note (for the tooltip)

Character offsets are computed by str.find() on the summary string so the
frontend can highlight spans without fragile word-index counting.
"""

from openai import AsyncOpenAI
from services.openai_client import get_openai_client
from pydantic import BaseModel

from agent.state import AgentState, JargonMapping
from services.conversational_response import generate_contextual_response
from agent.prompts import NOTE_SUMMARIZER_SYSTEM, NOTE_SUMMARIZER_EXAMPLES
from services.supabase_client import get_scoped_client, get_admin_client
from middleware.tenant import TenantContext
from config import get_settings

settings = get_settings()


class JargonEntry(BaseModel):
    term: str
    plain_english: str
    source_note_id: str
    source_sentence: str


class SummaryWithJargon(BaseModel):
    summary: str
    jargon_entries: list[JargonEntry]


async def run(state: AgentState) -> dict:
    client = get_openai_client()
    records = state.get("records", [])

    # If records not yet loaded, fetch them
    if not records:
        ctx = TenantContext(
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            role=state["role"],
        )
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

    if not records:
        user_message = state["messages"][-1].content if state.get("messages") else ""
        response = await generate_contextual_response(
            user_message=user_message,
            situation="The user wants a summary of their records, but no clinical records have been uploaded yet.",
            available_actions=["upload documents using the paperclip button in the chat", "tell WellBridge about their recent visits or medications"],
            emotional_state=state.get("emotional_state", "calm"),
        )
        return {
            "records": [],
            "raw_response": response,
            "jargon_map": [],
            "action_cards": [{"id": "upload_records", "type": "upload",
                              "label": "Upload a document",
                              "description": "Share your clinical notes, letters, or test results",
                              "payload": {}}],
        }

    # Format notes with IDs so GPT-4o can reference them in jargon entries
    notes_text = "\n\n".join(
        f"[NOTE_ID:{r['id']}] {str(r.get('note_date',''))[:10]} — "
        f"{r.get('provider_name','Unknown')}:\n{r.get('content','')}"
        for r in records
    )

    system_prompt = (
        f"{NOTE_SUMMARIZER_SYSTEM}\n\n"
        f"EXAMPLES:\n{NOTE_SUMMARIZER_EXAMPLES}\n\n"
        "Return JSON with the summary and a list of jargon entries with source note IDs and "
        "the exact source sentence from the note for each term."
    )

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Please summarize these clinical notes in plain language:\n\n"
                        f"{notes_text}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_completion_tokens=2500,
        )

        import json as _json
        raw = result.choices[0].message.content or ""
        if not raw:
            raise ValueError("Empty result")
        parsed = SummaryWithJargon(**_json.loads(raw))

        summary = parsed.summary

        # Build jargon_map with character offsets into the summary
        jargon_map: list[JargonMapping] = []
        for entry in parsed.jargon_entries:
            # Case-insensitive search for the term in the summary
            lower_summary = summary.lower()
            lower_term = entry.term.lower()
            idx = lower_summary.find(lower_term)
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
            "raw_response": summary,
            "jargon_map": jargon_map,
        }

    except Exception as exc:
        user_message = state["messages"][-1].content if state.get("messages") else ""
        record_count = len(records)
        fallback = await generate_contextual_response(
            user_message=user_message,
            situation=f"The user wants a summary of their records. {record_count} record(s) on file. The summarization couldn't complete — suggest they ask a specific question or upload additional documents.",
            available_actions=["ask a specific question about their records", "upload new documents using the paperclip button"],
            records_summary=f"{record_count} record(s) on file" if records else "none",
            emotional_state=state.get("emotional_state", "calm"),
        )
        return {
            "records": records,
            "tool_error": str(exc),
            "raw_response": fallback,
            "jargon_map": [],
            "action_cards": [{"id": "upload_records", "type": "upload",
                              "label": "Upload a document",
                              "description": "Share your clinical notes, letters, or test results",
                              "payload": {}}] if not records else [],
        }
