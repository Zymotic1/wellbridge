"""
Pre-visit prep node — generates questions for an upcoming doctor appointment.

Questions are grounded exclusively in the patient's documented records.
Uses structured output to produce 3–5 information-seeking questions.

Key behavior:
  - Works WITH or WITHOUT a formal appointment in the DB.
    If the user asks "what should I discuss with my doctor?" but no appointment
    is scheduled, we still generate questions from available records.
  - Also uses conversation history: if records were summarised earlier in the
    chat, their content feeds into question generation even before a DB fetch.
  - Questions are information-seeking only ("what were my results?") — never
    advice-seeking ("should I take X?").
"""

import json as _json

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage

from agent.state import AgentState
from agent.prompts import CONSTITUTIONAL_SYSTEM, PRE_VISIT_PREP_EXAMPLES
from services.supabase_client import get_admin_client
from config import get_settings

settings = get_settings()


class PrepQuestions(BaseModel):
    questions: list[str] = Field(min_length=3, max_length=5)
    based_on_note_ids: list[str]   # Source note IDs for audit trail


async def run(state: AgentState) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    tenant_id: str = state["tenant_id"]
    user_id: str = state["user_id"]

    records = state.get("records", [])
    appointments = state.get("appointments", [])

    # Fetch records and appointments from DB (admin client for reliable access)
    try:
        db = get_admin_client()

        if not records:
            rec_result = (
                db.table("patient_records")
                .select("id, provider_name, note_date, content")
                .eq("tenant_id", tenant_id)
                .eq("patient_user_id", user_id)
                .order("note_date", desc=True)
                .limit(5)
                .execute()
            )
            records = rec_result.data or []

        if not appointments:
            appt_result = (
                db.table("appointments")
                .select("provider_name, appointment_date, notes")
                .eq("tenant_id", tenant_id)
                .eq("patient_user_id", user_id)
                .gte("appointment_date", "now()")
                .order("appointment_date")
                .limit(1)
                .execute()
            )
            appointments = appt_result.data or []

    except Exception as exc:
        return {
            "tool_error": str(exc),
            "raw_response": "I had trouble retrieving your records. Please try again.",
            "jargon_map": [],
        }

    # If no records in DB, build context from conversation history:
    #   1. Most recent substantial AI summary (e.g. a note that was summarised earlier)
    #   2. Any health concerns the user mentioned across the last few turns
    history_context = ""
    if not records:
        from langchain_core.messages import HumanMessage as HM
        all_messages = state.get("messages", [])

        # Collect AI summaries as before
        assistant_summaries = [
            msg.content for msg in all_messages
            if isinstance(msg, AIMessage) and len(msg.content) > 100
        ]
        if assistant_summaries:
            history_context = assistant_summaries[-1][:1000]

        # Also collect recent human messages that mention health topics —
        # these capture stated concerns when the user has no records yet
        if not history_context:
            recent_human = [
                msg.content for msg in all_messages[-6:]
                if isinstance(msg, HM) and len(msg.content) > 10
            ]
            if recent_human:
                history_context = "Patient-stated concerns:\n" + "\n".join(recent_human[-3:])

    # Still no records and no history context → ask what concerns them
    # (warmly invite them to share topics; don't just tell them to upload)
    if not records and not history_context:
        return {
            "records": [],
            "raw_response": (
                "I'd love to help you prepare for your next visit!\n\n"
                "I don't have any of your health records on file yet — but that's okay, "
                "I can still help you put together good questions.\n\n"
                "What health topics or concerns are you thinking about bringing up with "
                "your doctor? For example: a symptom you've been noticing, a diagnosis "
                "you received, a medication you have questions about, or anything else "
                "that's on your mind."
            ),
            "jargon_map": [],
            "action_cards": [{
                "id": "upload_records",
                "type": "upload",
                "label": "Upload a health record",
                "description": "Add a visit note or lab result so I can tailor your questions to your actual care",
                "payload": {},
            }],
        }

    # Build provider/date string — use DB appointment if available, otherwise generic
    if appointments:
        next_appt = appointments[0]
        provider = next_appt.get("provider_name", "your doctor")
        appt_date = str(next_appt.get("appointment_date", ""))[:10]
        appt_line = f"Upcoming appointment: {provider} on {appt_date}"
        preamble = f"Here are questions to consider asking {provider} on {appt_date}:\n\n"
    else:
        provider = "your doctor"
        appt_line = "No scheduled appointment found — generating questions for the patient's next visit."
        if records:
            preamble = "Here are questions to bring up at your next visit:\n\n"
        else:
            preamble = (
                "Here are some questions to consider bringing to your next visit, "
                "based on what you mentioned:\n\n"
            )

    # Build notes text from DB records or conversation history
    if records:
        notes_text = "\n\n".join(
            f"[NOTE_ID:{r['id']}] {str(r.get('note_date',''))[:10]} — "
            f"{r.get('provider_name','?')}:\n{r.get('content','')[:500]}"
            for r in records[:5]
        )
    else:
        notes_text = f"[From recent conversation summary]\n{history_context}"

    if records:
        task_instruction = (
            "TASK: Generate 3–5 factual, information-seeking questions the patient should "
            "ask at their next doctor visit. Base EVERY question on specific content from "
            "the provided clinical notes — do not invent topics not mentioned in the records. "
            "Questions must seek information ('what were the results of...', 'can you explain "
            "what...', 'what does X in my notes mean for me'), never seek advice ('should I', "
            "'can I stop', 'is it normal for me'). "
            "Return JSON: {\"questions\": [...], \"based_on_note_ids\": [...]}"
        )
    else:
        # No records — generate questions from patient-stated concerns using
        # publicly available general health knowledge. Questions are still
        # information-seeking (the patient asks the DOCTOR), never advice.
        task_instruction = (
            "TASK: The patient has no health records uploaded yet, but has described "
            "some health topics or concerns. Generate 3–5 factual, information-seeking "
            "questions they can ask their doctor at the next visit, based on those concerns "
            "and general publicly available health knowledge. "
            "Questions must seek information from the doctor — they must NOT ask you "
            "(WellBridge) for advice. Format: 'Could you explain...', 'What do the results "
            "of... show?', 'Can we discuss...', 'What does ... mean for...'. "
            "Never write questions like 'Should I take...', 'Do I have...', 'Am I going "
            "to be okay' — those are for the doctor to answer, not for this list. "
            "Set based_on_note_ids to []. "
            "Return JSON: {\"questions\": [...], \"based_on_note_ids\": []}"
        )

    system = (
        f"{CONSTITUTIONAL_SYSTEM}\n\n"
        f"EXAMPLES:\n{PRE_VISIT_PREP_EXAMPLES}\n\n"
        f"{task_instruction}"
    )

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"{appt_line}\n\nRecords:\n{notes_text}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=600,
        )

        raw = result.choices[0].message.content or ""
        if not raw:
            raise ValueError("Empty result")
        parsed = PrepQuestions(**_json.loads(raw))

        footer = (
            "\n\n*These questions are based on your own records — not medical advice.*"
            if records else
            "\n\n*These questions are based on what you shared — your doctor is the right person to answer them.*"
        )
        formatted = (
            preamble
            + "\n".join(f"{i+1}. {q}" for i, q in enumerate(parsed.questions))
            + footer
        )

        return {
            "records": records,
            "appointments": appointments,
            "raw_response": formatted,
            "jargon_map": [],
        }

    except Exception as exc:
        return {
            "tool_error": str(exc),
            "raw_response": "I had trouble generating questions. Please try again.",
            "jargon_map": [],
        }
