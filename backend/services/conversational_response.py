"""
Conversational response service — LLM-powered contextual responses.

This is the universal fallback for ALL agent nodes. Instead of hardcoded
"I had trouble..." strings, agents call this service to generate an
intelligent, context-aware response.

The LLM receives:
  - What the user asked
  - What the agent was trying to do
  - What went wrong (or what data is missing)
  - What options the user has next

The LLM generates a warm, helpful response that guides the user forward.
This ensures the user NEVER gets a robotic, pre-written error message.

The ONLY hardcoded elements are UI action cards (upload buttons, calendar
links) — those are structural, not conversational.
"""

import logging
from services.openai_client import get_openai_client
from config import get_settings

log = logging.getLogger("wellbridge.conversational")
settings = get_settings()

CONVERSATIONAL_SYSTEM = """You are WellBridge, a personal health companion. You are generating
a helpful response to guide a patient when the system needs to ask for clarification,
suggest an action, or explain what happened.

RULES:
- Write at a 6th-grade reading level
- Be warm, supportive, and clear
- NEVER give medical advice, diagnose, or interpret results
- NEVER say "I'm sorry" repeatedly or sound robotic
- Suggest specific next steps the user can take
- Keep it concise: 2-4 sentences unless more context is needed
- Use "you/your" not "the patient"
- If the user needs to upload a document, mention the paperclip button
- If you're unsure what the user needs, ask ONE clarifying question

You are NOT explaining an error. You are having a natural conversation
and guiding the user to what they need next."""


async def generate_contextual_response(
    user_message: str,
    situation: str,
    available_actions: list[str] | None = None,
    records_summary: str | None = None,
    emotional_state: str = "calm",
) -> str:
    """
    Generate a contextual, LLM-crafted response for any agent situation.

    Args:
        user_message: What the user said
        situation: What's happening (e.g., "no records uploaded", "user asking about a visit")
        available_actions: What the user can do next (e.g., ["upload documents", "describe verbally"])
        records_summary: Brief summary of records on file (if any)
        emotional_state: User's emotional state from triage
    """
    try:
        client = get_openai_client()

        context_parts = [f"The user said: \"{user_message}\""]
        context_parts.append(f"Situation: {situation}")

        if records_summary:
            context_parts.append(f"Records on file: {records_summary}")
        if available_actions:
            context_parts.append(f"Available next steps: {', '.join(available_actions)}")
        if emotional_state != "calm":
            context_parts.append(f"The user seems {emotional_state} — adjust your tone accordingly")

        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": CONVERSATIONAL_SYSTEM},
                {"role": "user", "content": "\n".join(context_parts)},
            ],
            temperature=0.4,
            max_completion_tokens=400,
        )

        response = result.choices[0].message.content or ""
        if response.strip():
            return response.strip()

    except Exception as exc:
        log.warning("conversational_response: LLM failed — %s", exc)

    # Absolute last resort — only if the LLM itself is completely down
    return (
        "I'd like to help with that. Could you tell me a bit more about "
        "what you're looking for? I can explain medical information, help "
        "you understand your records, or help you prepare for a visit."
    )
