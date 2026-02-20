"""
Record collector node — handles RECORD_COLLECTION intent.

When the patient mentions a recent visit, document, scan result, prescription,
or any medical information they haven't yet stored in WellBridge, this node:
  1. Generates a warm, natural response acknowledging what they shared
  2. Offers concrete, non-form-like ways to capture that information
  3. Returns action_cards the frontend renders as interactive options

The response never feels like a task or an instruction manual.
It feels like a knowledgeable friend saying "I'd love to help you keep that."
"""

from openai import AsyncOpenAI
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState, ActionCard
from agent.prompts import RECORD_COLLECTOR_SYSTEM
from config import get_settings

settings = get_settings()


def _infer_action_cards(user_message: str, facts: list[str]) -> list[ActionCard]:
    """
    Infer which action cards to show based on what the user mentioned.
    We return at most 2 cards — enough to offer a path without overwhelming.
    """
    message_lower = user_message.lower()
    cards: list[ActionCard] = []

    # Document / scan / letter / report → offer upload
    has_document = any(w in message_lower for w in [
        "letter", "report", "scan", "result", "document", "pdf",
        "image", "photo", "form", "paperwork", "discharge",
    ])
    # Visit / appointment → offer upload + notes capture
    has_visit = any(w in message_lower for w in [
        "appointment", "visit", "saw", "doctor", "hospital", "clinic",
        "just came from", "just got back", "just had",
    ])
    # Prescription / medication → offer medication capture
    has_rx = any(w in message_lower for w in [
        "prescription", "medication", "medicine", "drug", "pill",
        "started taking", "prescribed",
    ])

    if has_document or has_visit:
        cards.append({
            "id": "upload_document",
            "type": "upload",
            "label": "Upload a document",
            "description": "Photo, PDF, or scan — I'll help you understand it",
            "payload": {},
        })

    if has_rx and len(cards) < 2:
        cards.append({
            "id": "add_medication",
            "type": "link",
            "label": "Add medication to your records",
            "description": "I'll store it and explain what it is",
            "payload": {"href": "/records/new?type=prescription"},
        })

    # Always offer email as a fallback if we have at most one card
    if len(cards) < 2:
        cards.append({
            "id": "request_records_email",
            "type": "email",
            "label": "Request records by email",
            "description": "I'll generate a template you can send to your provider",
            "payload": {
                "template": (
                    "Dear [Provider/Records Department],\n\n"
                    "I am requesting a copy of my medical records, including visit notes, "
                    "lab results, and any imaging reports from my recent visit.\n\n"
                    "Please send records to me at [your email address].\n\n"
                    "Thank you,\n[Your name]\nDate of Birth: [DOB]"
                ),
            },
        })

    return cards


async def run(state: AgentState) -> dict:
    """
    Generate a warm record-collection response and return action cards.
    """
    last_message = state["messages"][-1].content if state.get("messages") else ""
    facts: list[str] = state.get("care_context", {}).get("facts", [])
    emotional_state = state.get("emotional_state", "calm")

    action_cards = _infer_action_cards(last_message, facts)

    if not settings.openai_configured:
        # Graceful fallback without LLM
        return {
            "raw_response": (
                "I'd love to help you keep track of that. "
                "You can upload any documents or photos of records — "
                "I'll help you make sense of what they say."
            ),
            "action_cards": action_cards,
            "jargon_map": [],
        }

    # Build conversation history for continuity
    history = []
    for msg in state.get("messages", [])[-5:-1]:
        if isinstance(msg, HumanMessage):
            history.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            history.append({"role": "assistant", "content": msg.content})

    # Let the LLM craft the natural-language part
    context = (
        f"Patient emotional state: {emotional_state}\n"
        f"Known facts: {'; '.join(facts) if facts else 'none yet'}\n"
        f"Action options being shown: {', '.join(c['label'] for c in action_cards)}"
    )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        RECORD_COLLECTOR_SYSTEM
                        + f"\n\nCONTEXT:\n{context}"
                        + "\n\nNote: The UI will automatically show action buttons below your "
                        "message. You do NOT need to describe the buttons in text — just "
                        "write a warm 2-3 sentence message explaining you'd love to help "
                        "capture their information."
                    ),
                },
                *history,
                {"role": "user", "content": last_message},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        raw_response = response.choices[0].message.content or ""
    except Exception:
        raw_response = (
            "I'd love to help you keep everything organized. "
            "You can share any documents or notes from your care team "
            "and I'll help you understand and remember what they say."
        )

    return {
        "raw_response": raw_response,
        "action_cards": action_cards,
        "jargon_map": [],
    }
