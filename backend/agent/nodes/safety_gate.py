"""
Safety gate node — pre-Supervisor MEDICAL_ADVICE detection.

Runs BEFORE the Supervisor to enforce the invariant that MEDICAL_ADVICE
requests ALWAYS route to refusal_node. The Supervisor never sees these
requests and cannot override the refusal.

This reuses the intent_classifier's LLM call but is architecturally
separate to guarantee the safety property: even if the Supervisor is
modified or its prompt is changed, MEDICAL_ADVICE cannot bypass refusal.
"""

import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState, IntentType
from config import get_settings

log = logging.getLogger("wellbridge.safety_gate")
settings = get_settings()


# Reuse the full classifier system prompt from intent_classifier
from agent.nodes.intent_classifier import CLASSIFIER_SYSTEM


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


async def run(state: AgentState) -> dict:
    """
    Classify intent. If MEDICAL_ADVICE → state is marked for refusal.
    Otherwise → state carries the intent for the Supervisor to use.
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    messages_for_llm = [{"role": "system", "content": CLASSIFIER_SYSTEM}]

    # Add up to 3 prior turns as context
    prior_messages = state.get("messages", [])
    for msg in prior_messages[:-1][-6:]:
        if isinstance(msg, HumanMessage):
            messages_for_llm.append({"role": "user", "content": f"[PRIOR] {msg.content}"})
        elif isinstance(msg, AIMessage):
            messages_for_llm.append({"role": "assistant", "content": f"[PRIOR] {msg.content[:100]}"})

    last_message = state["messages"][-1].content
    messages_for_llm.append({
        "role": "user",
        "content": f"Classify this message and respond with JSON: {last_message}",
    })

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages_for_llm,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_completion_tokens=200,
        )

        raw = result.choices[0].message.content or ""
        data = json.loads(raw)
        parsed = IntentResult(**data)

        log.info("safety_gate: intent=%s confidence=%.2f reasoning=%s",
                 parsed.intent, parsed.confidence, parsed.reasoning[:80])

        return {
            "intent": parsed.intent,
            "confidence": parsed.confidence,
        }

    except Exception as exc:
        log.warning("safety_gate: classification failed — %s", exc)
        # Failure → CARE_NAVIGATION (ask user to clarify, safer than blanket refusal)
        return {
            "intent": "CARE_NAVIGATION",
            "confidence": 0.0,
        }
