"""
Emotional assessor node — the first node in the new agentic graph.

Reads the user's message and recent conversation context to assess:
  - emotional_state: how to pace and tone the response
  - care_stage: where in their health journey they are
  - new care facts: concrete information extracted from the message

This runs before the intent_classifier so every downstream node
can adapt its response style to the patient's actual state.

Temperature is 0.1 — we want consistency, not creativity.
"""

import json
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agent.state import AgentState, EmotionalState, CareStage
from agent.prompts import EMOTIONAL_ASSESSOR_SYSTEM
from config import get_settings

settings = get_settings()


class EmotionalAssessment(BaseModel):
    emotional_state: EmotionalState = Field(
        default="calm",
        description="Patient's emotional state inferred from their message",
    )
    care_stage: CareStage = Field(
        default="unknown",
        description="Where in their care journey the patient appears to be",
    )
    new_facts: list[str] = Field(
        default_factory=list,
        description="Concrete facts extracted (conditions, medications, providers, dates)",
    )


async def run(state: AgentState) -> dict:
    """
    Assess emotional state and extract care context from the conversation.
    Falls back to neutral defaults if the LLM call fails — never blocks the graph.
    """
    if not settings.openai_configured:
        return {
            "emotional_state": "calm",
            "care_stage": state.get("care_stage", "unknown"),
            "care_context": state.get("care_context", {}),
        }

    # Build a short conversation summary for context (last 4 messages max)
    recent_messages = state.get("messages", [])[-4:]
    conversation_snippet = "\n".join(
        f"{m.type.upper()}: {m.content}" for m in recent_messages
    )

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": EMOTIONAL_ASSESSOR_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Conversation so far:\n{conversation_snippet}\n\n"
                        f"Assess the patient's emotional state and extract care context."
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=300,
        )

        import json as _json
        raw = result.choices[0].message.content or ""
        parsed = EmotionalAssessment(**_json.loads(raw))
        if not raw:
            raise ValueError("Empty result")

        # Merge new facts into existing care_context dict
        existing_context: dict = state.get("care_context", {})
        existing_facts: list = existing_context.get("facts", [])
        merged_facts = list(dict.fromkeys(existing_facts + parsed.new_facts))  # Deduplicate preserving order

        return {
            "emotional_state": parsed.emotional_state,
            "care_stage": parsed.care_stage if parsed.care_stage != "unknown" else state.get("care_stage", "unknown"),
            "care_context": {**existing_context, "facts": merged_facts},
        }

    except Exception:
        # Assessment failure is non-critical — return current state unchanged
        return {
            "emotional_state": state.get("emotional_state", "calm"),
            "care_stage": state.get("care_stage", "unknown"),
            "care_context": state.get("care_context", {}),
        }
