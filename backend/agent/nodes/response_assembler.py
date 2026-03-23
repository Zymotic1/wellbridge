"""
Response assembler node — final step before END.

Persists the completed message to chat_messages in Supabase (including
jargon_map and action_cards for history replay), then generates contextual
suggested quick-reply buttons so the user always has a clear next step.

suggested_replies are ephemeral UI hints — they are not persisted to the DB.
The frontend shows them as pill buttons below the most recent assistant message.
"""

import logging

from agent.state import AgentState
from services.suggestions_service import generate_suggested_replies

log = logging.getLogger("wellbridge.response_assembler")

# NOTE: Assistant message persistence was moved to the chat_stream router
# (routers/chat.py) so it is handled with full error visibility alongside
# the user message save. This node now only generates suggested replies.


async def run(state: AgentState) -> dict:
    final = state.get("final_response") or "I'd like to help with that. Could you tell me a bit more?"
    jargon_map = state.get("jargon_map", [])
    action_cards = state.get("action_cards", [])
    intent = state.get("intent")
    records = state.get("records", [])

    # Use brain-generated suggested replies if available, otherwise generate
    suggested_replies = state.get("suggested_replies", [])

    if not suggested_replies:
        user_message = ""
        messages = state.get("messages", [])
        if messages:
            user_message = getattr(messages[-1], "content", "") or ""

        try:
            suggested_replies = await generate_suggested_replies(
                response_text=final,
                user_message=user_message,
                intent=intent,
                has_records=len(records) > 0,
                action_cards=action_cards,
            )
        except Exception as exc:
            log.warning("response_assembler: suggestions failed — %s", exc)

    return {
        "final_response": final,
        "jargon_map": jargon_map,
        "action_cards": action_cards,
        "suggested_replies": suggested_replies,
    }
